"""Promoting a project: a paid place at the top of others' lists, set only by the sync server."""

from __future__ import annotations

import importlib
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, InvestmentRequest, Notification
from app.services import marketplace, sync_client, timeline
from app.services.events import EventType

from .conftest import UP, VARANASI, become
from .test_marketplace import insert_profile, insert_request, make_owner, request_body
from .test_profiles import farmer_body, investor_india_body
from .test_subscription import FakeRazorpay, add_plan, webhook
from .test_sync import INVESTOR, SYNC_DIR, OtherDevice, ServerTransport, fresh_sync_module


@pytest.fixture()
def cloud(monkeypatch):
    """A sync server taking payments through a fake Razorpay, and this device pointed at it."""
    module = fresh_sync_module(monkeypatch)
    module.razorpay = FakeRazorpay(module.RazorpayClient.signature_ok)
    server = TestClient(module.app)
    monkeypatch.setattr(sync_client, "HttpTransport", lambda url: ServerTransport(server))
    yield server, module
    sys.path.remove(str(SYNC_DIR))


def add_promotion(module, code="feature-week", name="Featured for 7 days", paise=9900, days=7, alert=False) -> None:
    with module.db() as con:
        con.execute(
            "INSERT INTO plans (code, name, amount_paise, months, active, created_at, kind, days, alert) "
            "VALUES (?, ?, ?, 0, 1, ?, 'promotion', ?, ?)",
            (code, name, paise, module._now(), days, int(alert)),
        )


def shared_project(client, parcel_id: str) -> dict:
    """A farmer with sync on, and one project shared online and on the server."""
    make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    project = client.post("/api/v1/investment-requests", json=request_body(parcel_id))
    assert project.status_code == 201, project.text
    shared = client.post(f"/api/v1/investment-requests/{project.json()['id']}/share")
    assert shared.status_code == 200, shared.text
    assert client.post("/api/v1/sync/run").status_code == 200
    return shared.json()


def pay(client, module, project_id: str, plan: str = "feature-week") -> dict:
    payment = client.post(f"/api/v1/investment-requests/{project_id}/promotion/checkout", json={"plan": plan})
    assert payment.status_code == 201, payment.text
    link_id = max(module.razorpay.links)  # the newest link
    module.razorpay.pay(link_id)
    checked = client.post(f"/api/v1/subscription/payments/{payment.json()['id']}/check")
    assert checked.status_code == 200, checked.text
    return checked.json()


def events(kind: str) -> list[AppEvent]:
    with session_scope() as session:
        rows = list(session.scalars(select(AppEvent).where(AppEvent.event_type == kind)))
        session.expunge_all()
        return rows


def day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


# --------------------------------------------------------------------------- #
# Buying a promotion
# --------------------------------------------------------------------------- #


def test_a_farmer_promotes_a_shared_project(client, cloud, parcel_id):
    server, module = cloud
    add_plan(module)  # a subscription on sale too: it must not be offered here
    add_promotion(module)
    add_promotion(module, code="spotlight-week", name="Featured 7 days + alert", paise=19900, alert=True)
    project = shared_project(client, parcel_id)

    before = client.get(f"/api/v1/investment-requests/{project['id']}/promotion").json()
    assert before["reason"] is None and before["featured"] is False
    assert [(p["code"], p["days"], p["alert"]) for p in before["plans"]] == [
        ("feature-week", 7, False), ("spotlight-week", 7, True),
    ]
    assert [p["code"] for p in client.get("/api/v1/subscription").json()["plans"]] == ["video-month"]

    paid = pay(client, module, project["id"])
    assert paid["status"] == "paid" and paid["kind"] == "promotion" and paid["until"] == day(6)
    assert paid["targetId"] == project["id"]

    mine = client.get("/api/v1/investment-requests/mine").json()
    assert mine[0]["featured"] is True and mine[0]["promotedUntil"] == day(6)
    assert [e.payload["amount_paise"] for e in events(EventType.PROMOTION_PAID)] == [9900]
    assert len(events(EventType.PROMOTION_CHECKOUT)) == 1
    with session_scope() as session:
        assert "promotion_paid" in set(session.scalars(select(Notification.kind)))

    # Everyone else pulls the project stamped by the server.
    seen = [r for r in OtherDevice(server, INVESTOR).pull() if r["entityId"] == project["id"]]
    assert seen[-1]["payload"]["promoted_until"] == day(6)


def test_paying_again_adds_the_days_after_the_last(client, cloud, parcel_id):
    _, module = cloud
    add_promotion(module)
    project = shared_project(client, parcel_id)
    pay(client, module, project["id"])
    assert pay(client, module, project["id"])["until"] == day(13)


def test_the_webhook_counts_a_promotion_once(client, cloud, parcel_id):
    server, module = cloud
    add_promotion(module)
    project = shared_project(client, parcel_id)
    client.post(f"/api/v1/investment-requests/{project['id']}/promotion/checkout", json={"plan": "feature-week"})
    link = module.razorpay.links["plink_1"]
    module.razorpay.pay("plink_1")
    assert webhook(server, "payment_link.paid", link, event_id="evt_p1").json() == {"status": "ok"}
    assert webhook(server, "payment_link.paid", link, event_id="evt_p1").json() == {"status": "duplicate"}
    with module.db() as con:
        assert con.execute("SELECT until FROM promotions").fetchone()["until"] == day(6)


def test_what_cannot_be_promoted(client, cloud, parcel_id):
    server, module = cloud
    add_promotion(module)
    make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    draft = client.post("/api/v1/investment-requests", json=request_body(parcel_id)).json()

    # Not shared yet: nothing to promote, and the server would refuse it anyway.
    assert client.get(f"/api/v1/investment-requests/{draft['id']}/promotion").json()["reason"] == "not_shared"
    refused = client.post(f"/api/v1/investment-requests/{draft['id']}/promotion/checkout", json={"plan": "feature-week"})
    assert refused.status_code == 409

    client.post(f"/api/v1/investment-requests/{draft['id']}/share")
    client.post("/api/v1/sync/run")
    client.patch(f"/api/v1/investment-requests/{draft['id']}", json={"status": "closed"})
    assert client.get(f"/api/v1/investment-requests/{draft['id']}/promotion").json()["reason"] == "closed"

    # Someone else's project, straight at the server.
    stranger = OtherDevice(server, {"id": "a0000000-0000-0000-0000-0000000000c1", "segment": "farmer"})
    answer = server.post("/v1/payments", json={"plan": "feature-week", "target_type": "investment_request",
                                               "target_id": draft["id"]}, headers=stranger.headers)
    assert answer.status_code == 403
    answer = server.post("/v1/payments", json={"plan": "feature-week"}, headers=stranger.headers)
    assert answer.status_code == 422


def test_a_device_cannot_promote_itself(cloud):
    server, _ = cloud
    farmer = OtherDevice(server, {"id": "a0000000-0000-0000-0000-0000000000c2", "segment": "farmer"})
    request_id = "d0000000-0000-0000-0000-0000000000c2"
    farmer.push({"entity_type": "investment_request", "entity_id": request_id, "payload": {
        "id": request_id, "profile_id": farmer.profile["id"], "title": "Free advert", "status": "open",
        "open_to": ["investor_india"], "promoted_until": "2099-12-31", "promotion_alert_at": "2099-01-01T00:00:00+00:00",
    }})
    seen = [r for r in OtherDevice(server, INVESTOR).pull() if r["entityId"] == request_id][-1]["payload"]
    assert seen["promoted_until"] is None and seen["promotion_alert_at"] is None


# --------------------------------------------------------------------------- #
# What investors and partners see
# --------------------------------------------------------------------------- #


def test_promoted_projects_lead_the_lists_and_the_timeline(client):
    investor = make_owner(client, investor_india_body())
    farmer = insert_profile("farmer")
    # A strong fit, and a weaker one in another state that paid to be seen.
    good = insert_request(farmer, title="Strong fit")
    promoted = insert_request(farmer, title="Promoted", state_code="27", district_code="992701",
                              subdistrict_code=None, promoted_until=date.today() + timedelta(days=3))
    lapsed = insert_request(farmer, title="Lapsed", promoted_until=date.today() - timedelta(days=1))

    rows = client.get("/api/v1/investment-requests").json()
    assert [row["title"] for row in rows][0] == "Promoted"
    assert {row["id"]: row["featured"] for row in rows} == {promoted: True, good: False, lapsed: False}
    assert rows[1]["fit"]["score"] > rows[0]["fit"]["score"]  # promotion does not touch the fit

    with session_scope() as session:
        from app.models import Profile

        feed = timeline.feed(session, session.get(Profile, investor["id"]), kind="project")
    assert feed[0].id == promoted


def test_an_alerting_promotion_tells_a_matching_investor_once(client, cloud):
    server, module = cloud
    make_owner(client, investor_india_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    client.post("/api/v1/sync/run")

    farmer = OtherDevice(server, {"id": "a0000000-0000-0000-0000-0000000000c3", "segment": "farmer"})
    farmer.push({"entity_type": "profile", "entity_id": farmer.profile["id"], "payload": {
        "id": farmer.profile["id"], "segment": "farmer", "display_name": "Ramesh Yadav", "country_code": "IN",
        "preferred_language": "hi", "details": {}, "visibility": "online",
    }})
    request_id = "d0000000-0000-0000-0000-0000000000c3"
    listing = {"version": 1, "location": {"state": {"code": UP, "name": "Uttar Pradesh"},
                                          "district": {"code": VARANASI, "name": "Varanasi"}},
               "land": {}, "opportunity": None, "plan": None}
    farmer.push({"entity_type": "investment_request", "entity_id": request_id, "payload": {
        "id": request_id, "profile_id": farmer.profile["id"], "title": "Guava orchard", "status": "open",
        "state_code": UP, "district_code": VARANASI, "amount_sought": 500000, "seeking": ["investment"],
        "modes": ["revenue_share"], "partnership_types": [], "open_to": ["investor_india"],
        "opportunity_kind": "horticulture", "listing": listing, "visibility": "online",
    }})
    with module.db() as con:
        module._extend_promotion(con, "investment_request", request_id, farmer.profile["id"], 7, True)

    client.post("/api/v1/sync/run")
    with session_scope() as session:
        alerts = list(session.scalars(select(Notification).where(Notification.kind == "project_featured")))
        assert len(alerts) == 1 and alerts[0].params["title"] == "Guava orchard"
        assert session.get(InvestmentRequest, request_id).promoted_until == date.today() + timedelta(days=6)

    # Pulled again -- say the farmer edits it -- it does not alert twice.
    with module.db() as con:
        module._stamp_promotion(con, "investment_request", request_id)
    client.post("/api/v1/sync/run")
    with session_scope() as session:
        assert len(list(session.scalars(select(Notification).where(Notification.kind == "project_featured")))) == 1


def test_an_investor_it_does_not_suit_is_not_alerted(client, cloud):
    server, module = cloud
    body = investor_india_body()
    body["details"] = {**body["details"], "preferredStates": ["27"], "sectors": ["livestock"]}
    make_owner(client, body)
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    farmer = OtherDevice(server, {"id": "a0000000-0000-0000-0000-0000000000c4", "segment": "farmer"})
    farmer.push({"entity_type": "profile", "entity_id": farmer.profile["id"], "payload": {
        "id": farmer.profile["id"], "segment": "farmer", "display_name": "Mohan", "country_code": "IN",
        "preferred_language": "hi", "details": {}, "visibility": "online",
    }})
    request_id = "d0000000-0000-0000-0000-0000000000c4"
    farmer.push({"entity_type": "investment_request", "entity_id": request_id, "payload": {
        "id": request_id, "profile_id": farmer.profile["id"], "title": "Guava orchard", "status": "open",
        "state_code": UP, "district_code": VARANASI, "amount_sought": 500000, "seeking": ["investment"],
        "modes": ["loan"], "partnership_types": [], "open_to": ["investor_india"],
        "opportunity_kind": "horticulture", "listing": {}, "visibility": "online",
    }})
    with module.db() as con:
        module._extend_promotion(con, "investment_request", request_id, farmer.profile["id"], 7, True)
    client.post("/api/v1/sync/run")
    with session_scope() as session:
        assert not list(session.scalars(select(Notification).where(Notification.kind == "project_featured")))


# --------------------------------------------------------------------------- #
# The operator's side
# --------------------------------------------------------------------------- #


def test_admin_prices_grants_and_counts_promotions(client, cloud, parcel_id, capsys):
    server, module = cloud
    sys.modules.pop("admin", None)
    admin = importlib.import_module("admin")
    admin.server = module

    with pytest.raises(SystemExit):
        admin.set_plan("feature-week", "x", "99", None, "promotion", None)
    admin.set_plan("feature-week", "Featured for 7 days", "99", None, "promotion", 7)
    admin.set_plan("spotlight-week", "Featured 7 days + alert", "199", None, "promotion", 7, True)
    admin.list_plans()
    out = capsys.readouterr().out
    assert "promotion+alert" in out and "Rs 199" in out

    project = shared_project(client, parcel_id)
    pay(client, module, project["id"])
    admin.revenue(30)
    assert "Rs 99" in capsys.readouterr().out

    admin.promote(project["id"], 3, False)  # a free extension, after the paid week
    assert f"until {day(9)}" in capsys.readouterr().out
    client.post("/api/v1/sync/run")  # the owner's device hears of it
    assert client.get("/api/v1/investment-requests/mine").json()[0]["promotedUntil"] == day(9)

    admin.list_promotions()
    assert "live" in capsys.readouterr().out
    admin.unpromote(project["id"])
    seen = [r for r in OtherDevice(server, INVESTOR).pull() if r["entityId"] == project["id"]]
    assert seen[-1]["payload"]["promoted_until"] is None
    with pytest.raises(SystemExit):
        admin.unpromote(project["id"])


def test_the_payments_sandbox_walks_the_whole_flow(client, parcel_id, monkeypatch):
    """VG_PAYMENTS_SANDBOX=1 with no keys: a pretend payment page, for development."""
    for key in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VG_PAYMENTS_SANDBOX", "1")
    module = fresh_sync_module(monkeypatch)
    server = TestClient(module.app)
    monkeypatch.setattr(sync_client, "HttpTransport", lambda url: ServerTransport(server))
    try:
        assert isinstance(module.razorpay, module.SandboxPayments)
        add_promotion(module)
        project = shared_project(client, parcel_id)
        payment = client.post(f"/api/v1/investment-requests/{project['id']}/promotion/checkout",
                              json={"plan": "feature-week"}).json()
        path = payment["url"].split("127.0.0.1:8900", 1)[1]
        page = server.get(path)
        assert "TEST" in page.text and "no money moves" in page.text
        assert "is <strong>paid</strong>" in server.get(path, params={"action": "pay"}).text
        checked = client.post(f"/api/v1/subscription/payments/{payment['id']}/check").json()
        assert checked["status"] == "paid" and checked["until"] == day(6)
    finally:
        sys.path.remove(str(SYNC_DIR))


def test_an_older_database_gets_the_new_columns_with_their_defaults(monkeypatch):
    """Rows made before promotions existed are subscriptions, not NULL."""
    path = Path(tempfile.mkdtemp()) / "old.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE plans (code TEXT PRIMARY KEY, name TEXT NOT NULL, amount_paise INTEGER NOT NULL, "
                    "months INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)")
        con.execute("INSERT INTO plans VALUES ('video-month', 'Video', 9900, 1, 1, '2026-01-01')")
    sys.path.insert(0, str(SYNC_DIR))
    try:
        import storage

        store = storage.Store(f"sqlite:///{path}")
        store.create()
        with store.connect() as con:
            row = con.execute("SELECT kind, alert FROM plans").fetchone()
        store.engine.dispose()
    finally:
        sys.path.remove(str(SYNC_DIR))
    assert row["kind"] == "subscription" and row["alert"] == 0
