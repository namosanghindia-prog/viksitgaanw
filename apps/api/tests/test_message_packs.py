"""Message packs: paying to write to people one is not connected with."""

from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, Message, Notification
from app.services import sync_client
from app.services.events import EventType

from .test_marketplace import make_owner
from .test_profiles import farmer_body
from .test_subscription import FakeRazorpay
from .test_sync import INVESTOR, SYNC_DIR, OtherDevice, ServerTransport, fresh_sync_module


@pytest.fixture()
def cloud(monkeypatch):
    module = fresh_sync_module(monkeypatch)
    module.razorpay = FakeRazorpay(module.RazorpayClient.signature_ok)
    server = TestClient(module.app)
    monkeypatch.setattr(sync_client, "HttpTransport", lambda url: ServerTransport(server))
    yield server, module
    sys.path.remove(str(SYNC_DIR))


def add_pack(module, credits: int, paise: int) -> None:
    with module.db() as con:
        con.execute(
            "INSERT INTO plans (code, name, amount_paise, months, active, created_at, kind, credits) "
            "VALUES (?, ?, ?, 0, 1, ?, 'messages', ?)",
            (f"messages-{credits}", f"{credits} messages", paise, module._now(), credits),
        )


def investor_on_server(server) -> OtherDevice:
    """An investor who shared their profile, whom this farmer has nothing with."""
    investor = OtherDevice(server, INVESTOR)
    investor.push({"entity_type": "profile", "entity_id": INVESTOR["id"], "payload": INVESTOR})
    return investor


def ready(client) -> dict:
    me = make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    assert client.post("/api/v1/sync/run").status_code == 200
    return me


def write(client, profile_id: str, body: str = "Namaste, I grow guava in Pindra."):
    return client.post(f"/api/v1/conversations/{profile_id}/messages", json={"body": body})


def events(kind: str) -> list[AppEvent]:
    with session_scope() as session:
        rows = list(session.scalars(select(AppEvent).where(AppEvent.event_type == kind)))
        session.expunge_all()
        return rows


def test_a_farmer_buys_a_pack_and_writes_to_an_investor(client, cloud):
    server, module = cloud
    for credits, paise in ((10, 4900), (20, 8900), (30, 11900), (40, 14900)):
        add_pack(module, credits, paise)
    investor = investor_on_server(server)
    ready(client)

    # No pack yet: nothing is sent, and nothing is left behind looking sent.
    assert client.get(f"/api/v1/conversations/{INVESTOR['id']}/cost").json() == {
        "free": False, "credits": 0, "packsOnSale": True, "reason": None}
    refused = write(client, INVESTOR["id"])
    assert refused.status_code == 402 and "message pack" in refused.json()["detail"]
    with session_scope() as session:
        assert session.scalars(select(Message)).first() is None

    overview = client.get("/api/v1/subscription").json()
    assert [(p["credits"], p["amountPaise"]) for p in overview["messagePacks"]] == [
        (10, 4900), (20, 8900), (30, 11900), (40, 14900)]
    assert overview["messageCredits"] == 0
    assert overview["plans"] == []  # packs are not subscriptions

    payment = client.post("/api/v1/subscription/checkout", json={"plan": "messages-20"}).json()
    assert payment["kind"] == "messages" and payment["credits"] == 20
    module.razorpay.pay("plink_1")
    paid = client.post(f"/api/v1/subscription/payments/{payment['id']}/check").json()
    assert paid["status"] == "paid"
    assert [(e.payload["credits"], e.payload["amount_paise"]) for e in events(EventType.MESSAGES_PAID)] == [(20, 8900)]
    with session_scope() as session:
        assert "messages_paid" in set(session.scalars(select(Notification.kind)))

    sent = write(client, INVESTOR["id"])
    assert sent.status_code == 201, sent.text
    assert client.get(f"/api/v1/conversations/{INVESTOR['id']}/cost").json()["credits"] == 19
    assert len(events(EventType.MESSAGE_PAID)) == 1
    delivered = [r for r in investor.pull() if r["entityType"] == "message"]
    assert delivered and delivered[-1]["payload"]["paid"] is True

    # The investor answers for free; after that the farmer's replies are free too.
    investor.push({"entity_type": "message", "entity_id": "f0000000-0000-0000-0000-00000000aa01", "payload": {
        "id": "f0000000-0000-0000-0000-00000000aa01", "sender_profile_id": INVESTOR["id"],
        "recipient_profile_id": delivered[-1]["payload"]["sender_profile_id"], "body": "Tell me more.",
    }})
    client.post("/api/v1/sync/run")
    assert client.get(f"/api/v1/conversations/{INVESTOR['id']}/cost").json()["free"] is True
    assert write(client, INVESTOR["id"], "Here are the details.").status_code == 201
    assert client.get("/api/v1/subscription").json()["messageCredits"] == 19


def test_the_server_takes_a_message_from_the_pack_whatever_the_device_says(cloud):
    server, module = cloud
    stranger = OtherDevice(server, {"id": "a0000000-0000-0000-0000-0000000000d1", "segment": "farmer"})
    investor = investor_on_server(server)

    def send(message_id: str) -> dict:
        return stranger.push({"entity_type": "message", "entity_id": message_id, "payload": {
            "id": message_id, "sender_profile_id": stranger.profile["id"], "recipient_profile_id": INVESTOR["id"],
            "body": "Buy my crop",
        }})

    assert send("f0000000-0000-0000-0000-00000000d101")["rejected"][0]["reason"].startswith("No messages left")
    with module.db() as con:
        module.add_message_credits(con, stranger.profile["id"], 1)
    assert send("f0000000-0000-0000-0000-00000000d102")["accepted"] == 1
    assert send("f0000000-0000-0000-0000-00000000d103")["rejected"]  # the one message is spent
    with module.db() as con:
        assert module.message_credits(con, stranger.profile["id"]) == 0
    assert [r["entityId"] for r in investor.pull() if r["entityType"] == "message"] == [
        "f0000000-0000-0000-0000-00000000d102"]


def test_messages_between_people_dealing_with_each_other_stay_free(cloud):
    server, module = cloud
    farmer = OtherDevice(server, {"id": "a0000000-0000-0000-0000-0000000000d2", "segment": "farmer"})
    investor = investor_on_server(server)
    request_id = "d0000000-0000-0000-0000-0000000000d2"
    farmer.push({"entity_type": "investment_request", "entity_id": request_id, "payload": {
        "id": request_id, "profile_id": farmer.profile["id"], "title": "Orchard", "status": "open",
        "open_to": ["investor_india"],
    }})
    investor.push({"entity_type": "investment_interest", "entity_id": "b0000000-0000-0000-0000-0000000000d2",
                   "payload": {"id": "b0000000-0000-0000-0000-0000000000d2", "request_id": request_id,
                               "profile_id": INVESTOR["id"], "kind": "investment", "status": "sent"}})
    answer = farmer.push({"entity_type": "message", "entity_id": "f0000000-0000-0000-0000-00000000d201", "payload": {
        "id": "f0000000-0000-0000-0000-00000000d201", "sender_profile_id": farmer.profile["id"],
        "recipient_profile_id": INVESTOR["id"], "body": "Thank you for your interest.",
    }})
    assert answer["accepted"] == 1  # no pack needed


def test_writing_to_someone_new_needs_a_shared_profile(client, cloud):
    server, module = cloud
    investor_on_server(server)
    make_owner_body = farmer_body()
    client.post("/api/v1/profile", json=make_owner_body)  # not shared
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    client.post("/api/v1/sync/run")
    refused = write(client, INVESTOR["id"])
    assert refused.status_code == 409 and "Share your profile" in refused.json()["detail"]


def test_admin_prices_packs_and_gives_messages(client, cloud, capsys):
    server, module = cloud
    sys.modules.pop("admin", None)
    admin = importlib.import_module("admin")
    admin.server = module
    with pytest.raises(SystemExit):
        admin.set_plan("messages-10", "10 messages", "49", None, "messages")  # no --credits
    admin.set_plan("messages-10", "10 messages", "49", None, "messages", credits=10)
    admin.list_plans()
    assert "message pack" in capsys.readouterr().out

    investor_on_server(server)
    me = ready(client)
    admin.give_messages(me["id"], 5)
    assert "5 left" in capsys.readouterr().out
    assert write(client, INVESTOR["id"]).status_code == 201
    assert client.get(f"/api/v1/conversations/{INVESTOR['id']}/cost").json()["credits"] == 4
