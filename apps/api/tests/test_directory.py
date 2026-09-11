"""Farmers find investors, investors find farmers, and farmers send their projects."""

from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, Notification, ProjectInvite, SyncQueueEntry
from app.services import sync_client
from app.services.profiles import get_owner

from .conftest import UP, become
from .test_marketplace import MAHARASHTRA, insert_interest, insert_profile, insert_request, make_owner, request_body
from .test_profiles import farmer_body, investor_india_body
from .test_sync import INVESTOR, OtherDevice, ServerTransport, run, server  # noqa: F401 - fixture

VIDEO = {"provider": "youtube", "id": "dQw4w9WgXcQ"}


def shared_request(client, parcel_id: str, **overrides) -> dict:
    request = client.post("/api/v1/investment-requests", json=request_body(parcel_id, **overrides)).json()
    shared = client.post(f"/api/v1/investment-requests/{request['id']}/share")
    assert shared.status_code == 200, shared.text
    return request


def investor(**fields) -> str:
    details = {
        "investor_type": "family_office",
        "sectors": ["horticulture"],
        "modes": ["revenue_share"],
        "preferred_states": [UP],
        "ticket_min": 200000,
        "ticket_max": 1000000,
    }
    details.update(fields.pop("details", {}))
    return insert_profile(fields.pop("segment", "investor_india"), details=details, **fields)


# --------------------------------------------------------------------------- #
# Find investors
# --------------------------------------------------------------------------- #


def test_a_farmer_finds_investors_best_match_first(client, parcel_id):
    make_owner(client, farmer_body())
    request = shared_request(client, parcel_id)
    investor(display_name="Asha Good Fit", intro_video=VIDEO, about="We fund orchards in UP.")
    far = investor(display_name="Bala Elsewhere", details={"sectors": ["livestock"], "preferred_states": [MAHARASHTRA]})
    partner = insert_profile(
        "partner_national", display_name="Chetan Agro",
        details={"organisation_type": "agri_company", "partnership_types": ["buy_back"], "also_invests": True,
                 "investment_modes": ["revenue_share"], "operating_states": [UP]},
    )
    insert_profile("partner_national", display_name="Not investing",
                   details={"organisation_type": "fpo", "partnership_types": ["buy_back"]})
    investor(display_name="Offline investor", visibility="offline")
    abroad = investor(segment="investor_international", display_name="Dana Abroad")

    listings = client.get("/api/v1/directory/investors").json()
    names = [row["profile"]["displayName"] for row in listings]
    assert names[0] == "Asha Good Fit"
    assert "Not investing" not in names and "Offline investor" not in names
    assert {"Bala Elsewhere", "Chetan Agro", "Dana Abroad"} <= set(names)

    top = listings[0]
    assert top["introVideo"] == VIDEO and top["about"] == "We fund orchards in UP."
    assert top["sectors"] == ["horticulture"] and top["ticketMax"] == 1000000 and top["currency"] == "INR"
    assert top["fit"]["score"] == 100 and set(top["fit"]["reasons"]) >= {"state", "sector"}
    assert top["sendableRequestIds"] == [request["id"]]
    assert top["profile"]["contact"] is None, "no phone number from a listing"

    by_id = {row["profile"]["id"]: row for row in listings}
    assert by_id[abroad]["currency"] == "USD"
    assert by_id[abroad]["sendableRequestIds"] == [], "the project is not shown to international investors"
    assert by_id[partner]["sendableRequestIds"] == [request["id"]]
    assert by_id[far]["fit"]["score"] < top["fit"]["score"]

    only_up = client.get("/api/v1/directory/investors", params={"stateCode": MAHARASHTRA}).json()
    assert "Asha Good Fit" not in [row["profile"]["displayName"] for row in only_up]


def test_only_farmers_find_investors_and_only_responders_find_farmers(client):
    make_owner(client, investor_india_body())
    assert client.get("/api/v1/directory/investors").status_code == 403
    assert client.get("/api/v1/directory/farmers").status_code == 200


# --------------------------------------------------------------------------- #
# Sending a project
# --------------------------------------------------------------------------- #


def test_a_farmer_sends_their_project_to_an_investor(client, parcel_id):
    make_owner(client, farmer_body())
    request = shared_request(client, parcel_id)
    asha = investor(display_name="Asha")
    abroad = investor(segment="investor_international")

    sent = client.post(f"/api/v1/directory/investors/{asha}/invite",
                       json={"requestId": request["id"], "message": "  Please take a look.  "})
    assert sent.status_code == 201, sent.text
    assert sent.json()["status"] == "sent" and sent.json()["sentByMe"]
    assert sent.json()["message"] == "Please take a look."
    again = client.post(f"/api/v1/directory/investors/{asha}/invite", json={"requestId": request["id"]})
    assert again.status_code == 409

    [listing] = [r for r in client.get("/api/v1/directory/investors").json() if r["profile"]["id"] == asha]
    assert listing["sendableRequestIds"] == [] and listing["invitedRequestIds"] == [request["id"]]

    not_open = client.post(f"/api/v1/directory/investors/{abroad}/invite", json={"requestId": request["id"]})
    assert not_open.status_code == 409 and "kind of investor" in not_open.json()["detail"]
    nobody = client.post("/api/v1/directory/investors/no-such-person/invite", json={"requestId": request["id"]})
    assert nobody.status_code == 404

    with session_scope() as session:
        assert "project_invite.sent" in list(session.scalars(select(AppEvent.event_type)))
        assert session.scalars(select(SyncQueueEntry).where(SyncQueueEntry.entity_type == "project_invite")).first()


def test_a_project_must_be_shared_and_not_yet_answered(client, parcel_id):
    make_owner(client, farmer_body())
    draft = client.post("/api/v1/investment-requests", json=request_body(parcel_id)).json()
    asha = investor()
    offline = client.post(f"/api/v1/directory/investors/{asha}/invite", json={"requestId": draft["id"]})
    assert offline.status_code == 409 and "online" in offline.json()["detail"]

    client.post(f"/api/v1/investment-requests/{draft['id']}/share")
    insert_interest(draft["id"], asha)
    answered = client.post(f"/api/v1/directory/investors/{asha}/invite", json={"requestId": draft["id"]})
    assert answered.status_code == 409 and "already answered" in answered.json()["detail"]


def test_the_investor_answers_an_invite(client, parcel_id):
    farmer = make_owner(client, farmer_body())
    first = shared_request(client, parcel_id, title="Orchard one")
    second = shared_request(client, parcel_id, title="Orchard two")
    asha = investor(display_name="Asha")
    for request in (first, second):
        client.post(f"/api/v1/directory/investors/{asha}/invite", json={"requestId": request["id"]})

    become(asha)
    invites = client.get("/api/v1/directory/invites").json()
    assert {i["requestTitle"] for i in invites} == {"Orchard one", "Orchard two"}
    assert not any(i["sentByMe"] for i in invites)

    # Interested: an interest answers the invite.
    interest = client.post(f"/api/v1/investment-requests/{first['id']}/interests",
                           json={"kind": "investment", "mode": "revenue_share", "amountOffered": 300000})
    assert interest.status_code == 201, interest.text
    # Not interested: said so.
    other = next(i for i in invites if i["requestId"] == second["id"])
    declined = client.patch(f"/api/v1/directory/invites/{other['id']}", json={"status": "declined"})
    assert declined.status_code == 200 and declined.json()["status"] == "declined"
    assert client.patch(f"/api/v1/directory/invites/{other['id']}", json={"status": "declined"}).status_code == 409

    statuses = {i["requestId"]: i["status"] for i in client.get("/api/v1/directory/invites").json()}
    assert statuses == {first["id"]: "answered", second["id"]: "declined"}

    become(farmer["id"])
    assert client.patch(f"/api/v1/directory/invites/{other['id']}", json={"status": "declined"}).status_code in (403, 409)


# --------------------------------------------------------------------------- #
# Find farmers
# --------------------------------------------------------------------------- #


def test_an_investor_finds_farmers_with_their_projects(client):
    me = make_owner(client, investor_india_body())
    inviter = insert_profile("farmer", display_name="Zara Invited Me", state_code=UP,
                             details={"years_farming": 8, "needs": ["investment"]})
    busy = insert_profile("farmer", display_name="Ravi With Projects", state_code=UP,
                          biodata_video=VIDEO, about="Third generation on this land.",
                          details={"years_farming": 25, "needs": ["investment", "buyers"], "has_kcc": True})
    insert_profile("farmer", display_name="Quiet Farmer", state_code=MAHARASHTRA)
    insert_profile("farmer", display_name="Offline Farmer", visibility="offline")

    busy_request = insert_request(busy, title="Pomegranate on 1 acre")
    insert_request(busy, title="Hidden from investors", open_to=["partner_national"])
    invited_request = insert_request(inviter, title="Guava orchard")
    with session_scope() as session:
        session.add(ProjectInvite(request_id=invited_request, farmer_profile_id=inviter,
                                  investor_profile_id=me["id"], origin="synced"))

    listings = client.get("/api/v1/directory/farmers").json()
    names = [row["profile"]["displayName"] for row in listings]
    assert names[0] == "Zara Invited Me", "someone who sent me their project comes first"
    assert names[1] == "Ravi With Projects"
    assert "Offline Farmer" not in names and "Quiet Farmer" in names

    ravi = listings[1]
    assert ravi["profile"]["biodataVideo"] == VIDEO and ravi["about"] == "Third generation on this land."
    assert ravi["yearsFarming"] == 25 and ravi["hasKcc"] and ravi["needs"] == ["investment", "buyers"]
    assert [r["title"] for r in ravi["requests"]] == ["Pomegranate on 1 acre"], "only projects open to me"
    assert ravi["requests"][0]["fit"]["score"] > 0
    assert listings[0]["requests"][0]["invitedMe"] is True

    in_maharashtra = client.get("/api/v1/directory/farmers", params={"stateCode": MAHARASHTRA}).json()
    assert [row["profile"]["displayName"] for row in in_maharashtra] == ["Quiet Farmer"]


def test_farmers_do_not_find_farmers(client):
    make_owner(client, farmer_body())
    assert client.get("/api/v1/directory/farmers").status_code == 403


# --------------------------------------------------------------------------- #
# Through sync
# --------------------------------------------------------------------------- #


def test_an_invite_reaches_only_the_investor_and_comes_back_answered(client, server, parcel_id):  # noqa: F811
    transport = ServerTransport(server)
    make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    request = shared_request(client, parcel_id)
    insert_profile("investor_india", id=INVESTOR["id"], display_name="Priya Sharma",
                   details={"investor_type": "family_office", "modes": ["revenue_share"]})
    sent = client.post(f"/api/v1/directory/investors/{INVESTOR['id']}/invite", json={"requestId": request["id"]})
    assert sent.status_code == 201, sent.text
    run(transport)

    priya = OtherDevice(server, INVESTOR)
    stranger = OtherDevice(server, {"id": "a0000000-0000-0000-0000-00000000000e", "segment": "investor_india"})
    [invite] = [r for r in priya.pull() if r["entityType"] == "project_invite"]
    assert invite["payload"]["request_id"] == request["id"]
    assert not [r for r in stranger.pull() if r["entityType"] == "project_invite"]

    # The investor may answer it, and nothing else.
    answer = dict(invite["payload"], status="declined", message="rewritten")
    pushed = priya.push({"entity_type": "project_invite", "entity_id": invite["entityId"], "payload": answer})
    assert pushed["accepted"] == 1
    run(transport)
    with session_scope() as session:
        row = session.get(ProjectInvite, invite["entityId"])
        assert row.status == "declined" and row.message is None


def test_an_arriving_invite_tells_the_investor(client):
    me = make_owner(client, investor_india_body())
    farmer = insert_profile("farmer", display_name="Ramesh")
    request = insert_request(farmer, title="Guava orchard")
    with session_scope() as session:
        row = ProjectInvite(request_id=request, farmer_profile_id=farmer, investor_profile_id=me["id"],
                            origin="synced")
        session.add(row)
        session.flush()
        sync_client._hooks(session, "project_invite", row, None, get_owner(session))
    with session_scope() as session:
        [note] = session.scalars(select(Notification).where(Notification.kind == "project_invited")).all()
        assert note.params == {"name": "Ramesh", "title": "Guava orchard"}
