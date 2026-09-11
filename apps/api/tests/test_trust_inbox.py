"""Notifications, messages, and the trust layer: deals, milestones, disputes, ratings."""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from PIL import Image
from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, InsurancePolicy, Notification

from .conftest import become
from .test_marketplace import insert_interest, insert_profile, insert_request, make_owner, request_body
from .test_profiles import farmer_body, investor_india_body


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (800, 600), (10, 120, 40)).save(out, format="JPEG")
    return out.getvalue()


def plan(*amounts: float) -> list[dict]:
    return [
        {"title": f"Stage {i + 1}", "amount": amount, "dueDate": (date.today() + timedelta(days=30 * (i + 1))).isoformat()}
        for i, amount in enumerate(amounts)
    ]


@pytest.fixture()
def matched(client):
    """A farmer (this device) whose request an investor has answered and been accepted."""
    farmer = make_owner(client, farmer_body())
    investor_id = insert_profile("investor_india", display_name="Priya", organisation_name="Sharma Agri")
    request_id = insert_request(farmer["id"], visibility="online", origin="local")
    interest_id = insert_interest(request_id, investor_id, status="accepted", amount_offered=400000)
    return {"farmer": farmer["id"], "investor": investor_id, "request": request_id, "interest": interest_id}


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #


def test_notifications_are_only_for_the_owner(client, matched):
    from app.services.notify import notify

    with session_scope() as session:
        assert notify(session, matched["investor"], "interest_received") is None
        assert notify(session, matched["farmer"], "interest_received", params={"name": "Priya"}) is not None

    counts = client.get("/api/v1/notifications/counts").json()
    assert counts["notifications"] == 1
    [note] = client.get("/api/v1/notifications").json()
    assert note["kind"] == "interest_received" and note["params"]["name"] == "Priya"

    client.post("/api/v1/notifications/read", json={"ids": []})
    assert client.get("/api/v1/notifications/counts").json()["notifications"] == 0


def test_insurance_about_to_lapse_is_a_reminder_once(client):
    make_owner(client, farmer_body())
    profile_id = client.get("/api/v1/profile").json()["id"]
    with session_scope() as session:
        session.add(
            InsurancePolicy(
                profile_id=profile_id, category="accident", scheme="pmsby", status="insured",
                valid_until=date.today() + timedelta(days=10),
            )
        )
    first = client.get("/api/v1/notifications").json()
    second = client.get("/api/v1/notifications").json()
    assert [n["kind"] for n in first] == ["insurance_expiring"]
    assert len(second) == 1


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #


def test_no_free_messages_to_strangers(client):
    """Writing to someone one has nothing with takes a message pack, through the sync server (test_message_packs)."""
    make_owner(client, farmer_body())
    stranger = insert_profile("investor_india")
    response = client.post(f"/api/v1/conversations/{stranger}/messages", json={"body": "Hello"})
    assert response.status_code == 409 and "sync" in response.json()["detail"]
    assert client.get(f"/api/v1/conversations/{stranger}/cost").json()["reason"] == "sync_off"


def test_a_conversation(client, matched):
    response = client.post(
        f"/api/v1/conversations/{matched['investor']}/messages",
        json={"body": "  When can you visit the field?  ", "contextType": "interest", "contextId": matched["interest"]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["body"] == "When can you visit the field?"

    from app.models import Message

    with session_scope() as session:
        session.add(Message(sender_profile_id=matched["investor"], recipient_profile_id=matched["farmer"],
                            body="Next Tuesday.", origin="synced"))
    [conversation] = client.get("/api/v1/conversations").json()
    assert conversation["other"]["organisationName"] == "Sharma Agri"
    assert conversation["unread"] == 1
    assert client.get("/api/v1/notifications/counts").json()["messages"] == 1

    thread = client.get(f"/api/v1/conversations/{matched['investor']}/messages").json()
    assert [m["mine"] for m in thread] == [True, False]
    assert client.get("/api/v1/notifications/counts").json()["messages"] == 0


# --------------------------------------------------------------------------- #
# Deals and milestones
# --------------------------------------------------------------------------- #


def test_a_deal_from_plan_to_completion(client, matched):
    # The farmer draws up the plan.
    response = client.post(
        "/api/v1/deals",
        json={"interestId": matched["interest"], "terms": "Revenue share 20% for 3 seasons.", "milestones": plan(150000, 250000)},
    )
    assert response.status_code == 201, response.text
    deal = response.json()
    assert deal["status"] == "drafting" and deal["amountTotal"] == 400000
    assert deal["iAm"] == "farmer" and deal["canAgree"] is False
    assert deal["investor"]["contact"]["phone"], "matched parties see each other's contact"

    assert client.post(f"/api/v1/deals/{deal['id']}/agree").status_code == 403
    submit_first = client.post(f"/api/v1/milestones/{deal['milestones'][0]['id']}/submit", json={"note": "early"})
    assert submit_first.status_code == 409, "nothing can be submitted before the plan is agreed"

    # The investor, on their device, agrees.
    become(matched["investor"])
    deal = client.post(f"/api/v1/deals/{deal['id']}/agree").json()
    assert deal["status"] == "active" and deal["iAm"] == "investor"

    # The farmer submits evidence with a photograph.
    become(matched["farmer"])
    first = deal["milestones"][0]["id"]
    assert client.post(f"/api/v1/milestones/{first}/photos", content=jpeg(), headers={"Content-Type": "image/jpeg"}).status_code == 200
    deal = client.post(f"/api/v1/milestones/{first}/submit", json={"note": "Saplings planted, 450 plants."}).json()
    assert deal["milestones"][0]["status"] == "submitted"
    assert len(deal["milestones"][0]["photos"]) == 1

    # The investor sends the first back, then approves it.
    become(matched["investor"])
    deal = client.post(f"/api/v1/milestones/{first}/review", json={"approved": False, "note": "Photo of the drip too"}).json()
    assert deal["milestones"][0]["status"] == "rejected"
    become(matched["farmer"])
    client.post(f"/api/v1/milestones/{first}/submit", json={"note": "Added the drip photo."})
    become(matched["investor"])
    deal = client.post(f"/api/v1/milestones/{first}/review", json={"approved": True, "releaseReference": "UTR 1234"}).json()
    assert deal["milestones"][0]["releasedAt"] and deal["amountReleased"] == 150000

    become(matched["farmer"])
    second = deal["milestones"][1]["id"]
    client.post(f"/api/v1/milestones/{second}/submit", json={"note": "Fencing done."})
    become(matched["investor"])
    deal = client.post(f"/api/v1/milestones/{second}/review", json={"approved": True}).json()
    assert deal["status"] == "completed" and deal["canRate"] is True

    with session_scope() as session:
        events = session.scalars(select(AppEvent.event_type)).all()
    assert "deal.completed" in events and events.count("milestone.released") == 2

    # Ratings are public and show on the card.
    response = client.post("/api/v1/ratings", json={"contextType": "deal", "contextId": deal["id"], "stars": 5, "comment": "Kept every promise."})
    assert response.status_code == 201, response.text
    summary = client.get(f"/api/v1/profiles/{matched['farmer']}/ratings").json()
    assert summary["average"] == 5.0 and summary["count"] == 1
    card = client.get("/api/v1/deals").json()[0]["farmer"]
    assert card["ratingAvg"] == 5.0 and card["ratingCount"] == 1


def test_a_deal_needs_an_accepted_investment(client):
    farmer = make_owner(client, farmer_body())
    request_id = insert_request(farmer["id"], origin="local")
    pending = insert_interest(request_id, insert_profile("investor_india"), status="sent")
    response = client.post("/api/v1/deals", json={"interestId": pending, "milestones": plan(1000)})
    assert response.status_code == 409

    partner = insert_interest(request_id, insert_profile("partner_national"), kind="partnership", status="accepted",
                              mode=None, amount_offered=None, partnership_type="buy_back")
    response = client.post("/api/v1/deals", json={"interestId": partner, "milestones": plan(1000)})
    assert response.status_code == 422


def test_a_dispute_pauses_the_deal_until_the_other_side_agrees(client, matched):
    deal = client.post("/api/v1/deals", json={"interestId": matched["interest"], "milestones": plan(100000)}).json()
    become(matched["investor"])
    client.post(f"/api/v1/deals/{deal['id']}/agree")

    become(matched["farmer"])
    response = client.post(
        "/api/v1/disputes",
        json={"dealId": deal["id"], "reason": "payment_not_received", "description": "The advance never came."},
    )
    assert response.status_code == 201, response.text
    deal = response.json()
    assert deal["status"] == "disputed"
    dispute = deal["disputes"][0]
    submit = client.post(f"/api/v1/milestones/{deal['milestones'][0]['id']}/submit", json={"note": "x"})
    assert submit.status_code == 409, "work pauses while a dispute is open"

    # The farmer proposes; only the investor can confirm.
    deal = client.patch(f"/api/v1/disputes/{dispute['id']}", json={"action": "propose", "resolution": "Pay the advance by Friday."}).json()
    assert client.patch(f"/api/v1/disputes/{dispute['id']}", json={"action": "confirm"}).status_code == 403
    become(matched["investor"])
    deal = client.patch(f"/api/v1/disputes/{dispute['id']}", json={"action": "confirm"}).json()
    assert deal["status"] == "active" and deal["disputes"][0]["status"] == "resolved"


def test_incoming_deal_changes_notify_the_owner(client, matched):
    from app.models import Deal
    from app.services.trust import on_incoming_deal

    deal = client.post("/api/v1/deals", json={"interestId": matched["interest"], "milestones": plan(5000)}).json()
    with session_scope() as session:
        row = session.get(Deal, deal["id"])
        before = {"status": row.status, "milestones": [{"id": m.id, "status": m.status} for m in row.milestones]}
        row.status = "active"
        on_incoming_deal(session, row, before)
    with session_scope() as session:
        kinds = list(session.scalars(select(Notification.kind)))
    assert "deal_active" in kinds
