"""Paying for a subscription: plans, payment links, the webhook, and receipts."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, Notification, SubscriptionPayment
from app.services import subscription, sync_client

from .test_marketplace import make_owner
from .test_profiles import farmer_body
from .test_sync import SYNC_DIR, fresh_sync_module, OtherDevice, ServerTransport

WEBHOOK_SECRET = "whsec_test"


class FakeRazorpay:
    """Razorpay Payment Links, as far as a prepaid subscription goes."""

    configured = True

    def __init__(self, signature_ok) -> None:
        self.links: dict[str, dict] = {}
        self.webhook_secret = WEBHOOK_SECRET
        self._signature_ok = signature_ok

    def signature_ok(self, body: bytes, signature: str) -> bool:
        return self._signature_ok(self, body, signature)

    def create_link(self, *, amount_paise, reference_id, description, expire_by, notes) -> dict:
        link_id = f"plink_{len(self.links) + 1}"
        self.links[link_id] = {
            "id": link_id, "short_url": f"https://rzp.test/{link_id}", "status": "created",
            "amount": amount_paise, "amount_paid": 0, "reference_id": reference_id,
            "description": description, "expire_by": expire_by, "notes": notes, "payments": None,
        }
        return self.links[link_id]

    def get_link(self, link_id: str) -> dict:
        return self.links[link_id]

    def pay(self, link_id: str, amount: int | None = None) -> None:
        link = self.links[link_id]
        paid = link["amount"] if amount is None else amount
        link.update(status="paid", amount_paid=paid,
                    payments=[{"payment_id": f"pay_{link_id}", "status": "captured", "amount": paid}])


@pytest.fixture()
def cloud(monkeypatch):
    """A sync server taking payments through a fake Razorpay, and this device pointed at it."""
    module = fresh_sync_module(monkeypatch)
    module.razorpay = FakeRazorpay(module.RazorpayClient.signature_ok)
    server = TestClient(module.app)
    # The app's own HTTP calls to the sync server go to the test server instead.
    monkeypatch.setattr(sync_client, "HttpTransport", lambda url: ServerTransport(server))
    yield server, module
    sys.path.remove(str(SYNC_DIR))


def add_plan(module, code="video-month", name="Video uploads, 1 month", paise=9900, months=1) -> None:
    with module.db() as con:
        con.execute(
            "INSERT INTO plans (code, name, amount_paise, months, active, created_at) VALUES (?, ?, ?, ?, 1, ?) "
            "ON CONFLICT (code) DO UPDATE SET name = excluded.name, amount_paise = excluded.amount_paise, "
            "months = excluded.months, active = 1",
            (code, name, paise, months, module._now()),
        )


def ready(client, module) -> dict:
    """A farmer with sync on and one plan on sale."""
    me = make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    add_plan(module)
    return me


def webhook(server, event: str, link: dict, *, event_id: str, secret: str = WEBHOOK_SECRET):
    body = json.dumps({
        "entity": "event",
        "event": event,
        "payload": {
            "payment_link": {"entity": link},
            "payment": {"entity": {"id": f"pay_{link['id']}", "status": "captured"}},
        },
    }).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return server.post("/v1/webhooks/razorpay", content=body,
                       headers={"X-Razorpay-Signature": signature, "X-Razorpay-Event-Id": event_id,
                                "Content-Type": "application/json"})


def server_until(module, profile_id: str) -> str | None:
    with module.db() as con:
        return module.subscription(con, profile_id)["until"]


def events(kind: str) -> list[AppEvent]:
    with session_scope() as session:
        rows = list(session.scalars(select(AppEvent).where(AppEvent.event_type == kind)))
        session.expunge_all()
        return rows


# --------------------------------------------------------------------------- #
# What is on sale
# --------------------------------------------------------------------------- #


def test_nothing_is_on_sale_until_the_operator_prices_a_plan(client, cloud):
    _, module = cloud
    make_owner(client, farmer_body())
    assert client.get("/api/v1/subscription").json()["reason"] == "sync_off"

    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    module.razorpay.configured = False
    assert client.get("/api/v1/subscription").json()["reason"] == "payments_off"

    module.razorpay.configured = True
    answer = client.get("/api/v1/subscription").json()
    assert answer["reason"] == "no_plans" and answer["plans"] == []

    add_plan(module)
    answer = client.get("/api/v1/subscription").json()
    assert answer["reason"] is None and answer["paymentsAvailable"] is True
    assert answer["plans"] == [{"code": "video-month", "name": "Video uploads, 1 month", "amountPaise": 9900,
                                "months": 1}]
    assert answer["status"]["subscribed"] is False


def test_offline_the_receipts_still_show(client, cloud, monkeypatch):
    _, module = cloud
    ready(client, module)
    client.post("/api/v1/subscription/checkout", json={"plan": "video-month"})

    class Down:
        def post(self, *args, **kwargs):
            raise sync_client.SyncError("Sync server not reachable: no route", 503)

        get = post

    monkeypatch.setattr(sync_client, "HttpTransport", lambda url: Down())
    with session_scope() as session:
        sync_client._set(session, "token", None)  # force a registration, which fails
    answer = client.get("/api/v1/subscription").json()
    assert answer["reason"] == "offline"
    assert [p["status"] for p in answer["payments"]] == ["created"]


# --------------------------------------------------------------------------- #
# Paying
# --------------------------------------------------------------------------- #


def test_a_farmer_pays_and_the_subscription_starts(client, cloud):
    server, module = cloud
    me = ready(client, module)

    started = client.post("/api/v1/subscription/checkout", json={"plan": "video-month"})
    assert started.status_code == 201, started.text
    payment = started.json()
    assert payment["status"] == "created" and payment["amountPaise"] == 9900
    assert payment["url"] == "https://rzp.test/plink_1"
    link = module.razorpay.links["plink_1"]
    assert link["reference_id"] == payment["id"] and len(payment["id"]) <= 40
    assert link["amount"] == 9900 and link["notes"] == {"profile_id": me["id"], "plan": "video-month"}
    assert [e.payload for e in events("subscription.checkout_started")] == [
        {"plan": "video-month", "amount_paise": 9900}
    ]

    check = client.post(f"/api/v1/subscription/payments/{payment['id']}/check").json()
    assert check["status"] == "created", "not paid yet"

    module.razorpay.pay("plink_1")
    check = client.post(f"/api/v1/subscription/payments/{payment['id']}/check").json()
    expected = module._add_months(date.today(), 1).isoformat()
    assert check["status"] == "paid" and check["until"] == expected
    assert check["url"] is None, "a paid link is not offered again"
    assert server_until(module, me["id"]) == expected

    answer = client.get("/api/v1/subscription").json()
    assert answer["status"]["subscribed"] is True and answer["status"]["until"] == expected
    assert client.get("/api/v1/videos/plan").json()["subscribed"] is True, "uploads open straight away"
    assert [e.payload for e in events("subscription.paid")] == [
        {"plan": "video-month", "amount_paise": 9900, "months": 1}
    ]
    with session_scope() as session:
        [note] = session.scalars(select(Notification).where(Notification.kind == "subscription_paid")).all()
        assert note.params == {"plan": "Video uploads, 1 month", "date": expected}

    # Asking again changes nothing and counts nothing twice.
    client.post(f"/api/v1/subscription/payments/{payment['id']}/check")
    assert len(events("subscription.paid")) == 1
    assert server_until(module, me["id"]) == expected


def test_paying_early_adds_the_months_after_the_last_day(client, cloud):
    _, module = cloud
    me = ready(client, module)
    client.get("/api/v1/subscription")  # registers this device with the server
    last_day = date.today() + timedelta(days=10)
    with module.db() as con:
        con.execute("INSERT INTO subscriptions VALUES (?, 'video-month', ?, ?)",
                    (me["id"], last_day.isoformat(), module._now()))
    payment = client.post("/api/v1/subscription/checkout", json={"plan": "video-month"}).json()
    module.razorpay.pay("plink_1")
    check = client.post(f"/api/v1/subscription/payments/{payment['id']}/check").json()
    assert check["until"] == module._add_months(last_day, 1).isoformat()


def test_an_expired_subscription_starts_again_from_today(client, cloud):
    _, module = cloud
    me = ready(client, module)
    client.get("/api/v1/subscription")
    with module.db() as con:
        con.execute("INSERT INTO subscriptions VALUES (?, 'video-month', '2020-01-31', ?)", (me["id"], module._now()))
    payment = client.post("/api/v1/subscription/checkout", json={"plan": "video-month"}).json()
    module.razorpay.pay("plink_1")
    check = client.post(f"/api/v1/subscription/payments/{payment['id']}/check").json()
    assert check["until"] == module._add_months(date.today(), 1).isoformat()


def test_pressing_pay_twice_hands_back_the_same_link(client, cloud):
    _, module = cloud
    ready(client, module)
    first = client.post("/api/v1/subscription/checkout", json={"plan": "video-month"}).json()
    second = client.post("/api/v1/subscription/checkout", json={"plan": "video-month"}).json()
    assert first["id"] == second["id"] and len(module.razorpay.links) == 1

    # A new price is a new link: the open one was made for the old price.
    add_plan(module, paise=14900)
    third = client.post("/api/v1/subscription/checkout", json={"plan": "video-month"}).json()
    assert third["id"] != first["id"] and third["amountPaise"] == 14900


def test_an_expired_link_is_marked_so(client, cloud):
    _, module = cloud
    ready(client, module)
    payment = client.post("/api/v1/subscription/checkout", json={"plan": "video-month"}).json()
    module.razorpay.links["plink_1"]["status"] = "expired"
    check = client.post(f"/api/v1/subscription/payments/{payment['id']}/check").json()
    assert check["status"] == "expired" and check["url"] is None
    assert events("subscription.paid") == []


def test_what_cannot_be_bought(client, cloud):
    _, module = cloud
    me = ready(client, module)
    missing = client.post("/api/v1/subscription/checkout", json={"plan": "gold"})
    assert missing.status_code == 404 and missing.json()["detail"] == "That plan is not on sale."

    module.razorpay.configured = False
    off = client.post("/api/v1/subscription/checkout", json={"plan": "video-month"})
    assert off.status_code == 503 and "not switched on" in off.json()["detail"]

    module.razorpay.configured = True
    with module.db() as con:
        con.execute("INSERT INTO subscriptions VALUES (?, 'granted', NULL, ?)", (me["id"], module._now()))
    assert client.get("/api/v1/subscription").json()["reason"] == "no_end"
    assert client.post("/api/v1/subscription/checkout", json={"plan": "video-month"}).status_code == 409

    client.put("/api/v1/sync/config", json={"serverUrl": None})
    sync_off = client.post("/api/v1/subscription/checkout", json={"plan": "video-month"})
    assert sync_off.status_code == 409 and "sync" in sync_off.json()["detail"]


def test_a_payment_made_after_the_app_closed_counts_at_the_next_check(client, cloud):
    server, module = cloud
    ready(client, module)
    client.post("/api/v1/subscription/checkout", json={"plan": "video-month"})
    module.razorpay.pay("plink_1")
    with session_scope() as session:
        assert subscription.check_pending(session, ServerTransport(server)) == 1
    with session_scope() as session:
        assert session.scalars(select(SubscriptionPayment.status)).one() == "paid"
    # Opening the page does the same; nothing is pending now.
    with session_scope() as session:
        assert subscription.check_pending(session, ServerTransport(server)) == 0


# --------------------------------------------------------------------------- #
# Razorpay's webhook
# --------------------------------------------------------------------------- #


def test_the_webhook_counts_a_payment_once(client, cloud):
    server, module = cloud
    me = ready(client, module)
    payment = client.post("/api/v1/subscription/checkout", json={"plan": "video-month"}).json()
    module.razorpay.pay("plink_1")
    link = module.razorpay.links["plink_1"]

    forged = webhook(server, "payment_link.paid", link, event_id="evt_0", secret="not-the-secret")
    assert forged.status_code == 400
    with module.db() as con:
        assert module.subscription(con, me["id"]) is None, "a forged webhook counts for nothing"

    assert webhook(server, "payment_link.paid", link, event_id="evt_1").json() == {"status": "ok"}
    expected = module._add_months(date.today(), 1).isoformat()
    assert server_until(module, me["id"]) == expected
    assert webhook(server, "payment_link.paid", link, event_id="evt_1").json() == {"status": "duplicate"}
    # Razorpay retrying under a new event id, then the device asking: still once.
    webhook(server, "payment_link.paid", link, event_id="evt_2")
    check = client.post(f"/api/v1/subscription/payments/{payment['id']}/check").json()
    assert check["status"] == "paid" and check["until"] == expected
    assert server_until(module, me["id"]) == expected
    with module.db() as con:
        row = con.execute("SELECT * FROM payments").fetchone()
    assert row["provider_payment_id"] == "pay_plink_1"


def test_the_webhook_ignores_a_short_payment_and_unknown_links(client, cloud):
    server, module = cloud
    me = ready(client, module)
    client.post("/api/v1/subscription/checkout", json={"plan": "video-month"})
    module.razorpay.pay("plink_1", amount=100)
    webhook(server, "payment_link.paid", module.razorpay.links["plink_1"], event_id="evt_short")
    with module.db() as con:
        assert module.subscription(con, me["id"]) is None
    stranger = {"id": "plink_nobody", "amount_paid": 9900}
    assert webhook(server, "payment_link.paid", stranger, event_id="evt_x").json() == {"status": "ignored"}


def test_the_webhook_marks_a_lapsed_link(client, cloud):
    server, module = cloud
    ready(client, module)
    client.post("/api/v1/subscription/checkout", json={"plan": "video-month"})
    webhook(server, "payment_link.expired", module.razorpay.links["plink_1"], event_id="evt_exp")
    with module.db() as con:
        assert con.execute("SELECT status FROM payments").fetchone()["status"] == "expired"


def test_nobody_sees_anyone_elses_payments(client, cloud):
    server, module = cloud
    ready(client, module)
    payment = client.post("/api/v1/subscription/checkout", json={"plan": "video-month"}).json()
    other = OtherDevice(server, {"id": "a0000000-0000-0000-0000-0000000000e1", "segment": "farmer"})
    assert server.get(f"/v1/payments/{payment['id']}", headers=other.headers).status_code == 404
    assert server.get("/v1/payments", headers=other.headers).json() == {"payments": []}


# --------------------------------------------------------------------------- #
# The server's arithmetic and the operator's commands
# --------------------------------------------------------------------------- #


def test_adding_months_keeps_to_real_dates(cloud):
    _, module = cloud
    assert module._add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert module._add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert module._add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert module._add_months(date(2026, 9, 11), 12) == date(2027, 9, 11)


def test_admin_prices_plans_and_lists_payments(client, cloud, capsys):
    server, module = cloud
    sys.modules.pop("admin", None)
    admin = importlib.import_module("admin")
    admin.server = module

    assert admin.to_paise("99") == 9900 and admin.to_paise("149.50") == 14950
    for bad in ("0.50", "abc", "9.999"):
        with pytest.raises(SystemExit):
            admin.to_paise(bad)
    with pytest.raises(SystemExit):
        admin.set_plan("Video Month!", "x", "99", 1)
    with pytest.raises(SystemExit):
        admin.set_plan("video-month", "x", "99", 0)

    admin.set_plan("video-month", "Video uploads, 1 month", "99", 1)
    admin.set_plan("video-year", "Video uploads, 1 year", "999", 12)
    admin.list_plans()
    out = capsys.readouterr().out
    assert "Rs 99" in out and "Rs 999" in out and "on sale" in out

    me = make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    assert [p["code"] for p in client.get("/api/v1/subscription").json()["plans"]] == ["video-month", "video-year"]
    admin.retire_plan("video-year")
    assert [p["code"] for p in client.get("/api/v1/subscription").json()["plans"]] == ["video-month"]
    with pytest.raises(SystemExit):
        admin.retire_plan("no-such-plan")

    client.post("/api/v1/subscription/checkout", json={"plan": "video-month"})
    capsys.readouterr()
    admin.list_payments(me["id"])
    assert "created" in capsys.readouterr().out


def test_erasing_removes_receipts_and_export_lists_them(client, cloud):
    _, module = cloud
    ready(client, module)
    client.post("/api/v1/subscription/checkout", json={"plan": "video-month"})
    assert len(client.get("/api/v1/my-data").json()["subscription_payments"]) == 1
    assert client.post("/api/v1/my-data/erase", json={"confirm": "DELETE MY DATA"}).status_code == 200
    with session_scope() as session:
        assert session.scalars(select(SubscriptionPayment)).first() is None
