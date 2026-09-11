"""Ratings for machine hires and sales, and for partnerships -- as well as deals.

A rating is public and follows someone everywhere, so it opens only once the
work is really done: a hire marked over or a machine handed over, a
partnership that actually ran. The sync server checks the same thing, so a
rating pushed by someone who never worked with that person goes nowhere.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, EquipmentEnquiry, EquipmentPartnership, Notification
from app.services import sync_client
from app.services.profiles import get_owner

from .conftest import UP, VARANASI
from .test_marketplace import insert_profile, make_owner
from .test_profiles import farmer_body
from .test_sharing_equipment import insert_listing, machine, seller  # noqa: F401 - fixture
from .test_sync import OtherDevice, server  # noqa: F401 - fixture


def _enquiry_from(farmer_id: str, listing_id: str, status: str = "sent") -> str:
    with session_scope() as session:
        row = EquipmentEnquiry(listing_id=listing_id, profile_id=farmer_id, kind="rent", quantity=1,
                               status=status, origin="synced")
        session.add(row)
        session.flush()
        return row.id


def _listed(client) -> str:
    listing = client.post("/api/v1/equipment", json=machine()).json()
    client.post(f"/api/v1/equipment/{listing['id']}/share")
    return listing["id"]


def _enquiry_out(client, enquiry_id: str) -> dict:
    mine = client.get("/api/v1/equipment/mine").json()[0]
    return next(row for row in mine["enquiries"] if row["id"] == enquiry_id)


def rate(client, context_type: str, context_id: str, stars: int = 5, comment: str | None = None):
    return client.post("/api/v1/ratings", json={"contextType": context_type, "contextId": context_id,
                                                "stars": stars, "comment": comment})


# --------------------------------------------------------------------------- #
# A hire or a sale
# --------------------------------------------------------------------------- #


def test_a_seller_rates_a_hire_once_it_is_over(client, seller):  # noqa: F811
    listing_id = _listed(client)
    farmer = insert_profile("farmer", display_name="Mohan")
    enquiry_id = _enquiry_from(farmer, listing_id)

    assert rate(client, "enquiry", enquiry_id).status_code == 409, "not before it is agreed"
    client.patch(f"/api/v1/equipment-enquiries/{enquiry_id}", json={"status": "accepted"})
    assert _enquiry_out(client, enquiry_id)["canRate"] is False, "agreeing is not the work"
    refused = rate(client, "enquiry", enquiry_id)
    assert refused.status_code == 409 and "marked done" in refused.json()["detail"]

    done = client.patch(f"/api/v1/equipment-enquiries/{enquiry_id}", json={"status": "completed"})
    assert done.status_code == 200, done.text
    row = _enquiry_out(client, enquiry_id)
    assert row["status"] == "completed" and row["canRate"] is True and row["myRating"] is None
    # Marking it done keeps the two in touch: the phone stays visible.
    assert row["enquirer"]["contact"] is not None

    given = rate(client, "enquiry", enquiry_id, 4, "Returned the tractor on time")
    assert given.status_code == 201, given.text
    assert given.json()["contextId"] == enquiry_id and given.json()["about"] == "45 HP tractor with driver"
    # Rating again changes it rather than adding another.
    assert rate(client, "enquiry", enquiry_id, 5, "Returned on time, paid in full").status_code == 201
    row = _enquiry_out(client, enquiry_id)
    assert row["myRating"]["stars"] == 5 and row["myRating"]["comment"] == "Returned on time, paid in full"

    summary = client.get(f"/api/v1/profiles/{farmer}/ratings").json()
    assert summary["count"] == 1 and summary["average"] == 5.0
    with session_scope() as session:
        kinds = list(session.scalars(select(AppEvent.event_type)))
    assert "equipment_enquiry.completed" in kinds, "a finished hire is a meterable event"


def test_the_one_who_hired_marks_it_done_and_rates_the_seller(client):
    make_owner(client, farmer_body())
    seller_id = insert_profile("partner_national", display_name="Nashik Tractors", state_code=UP,
                               district_code=VARANASI)
    listing_id = insert_listing(seller_id, title="Rotavator")
    client.post(f"/api/v1/equipment/{listing_id}/enquiries", json={"kind": "rent"})
    with session_scope() as session:
        enquiry = session.scalars(select(EquipmentEnquiry)).one()
        enquiry.status = "accepted"  # the seller agreed, on their device
        enquiry_id = enquiry.id

    assert client.patch(f"/api/v1/equipment-enquiries/{enquiry_id}", json={"status": "completed"}).status_code == 200
    assert rate(client, "enquiry", enquiry_id, 3).status_code == 201
    card = client.get(f"/api/v1/equipment/{listing_id}").json()["seller"]
    assert card["ratingAvg"] == 3.0 and card["ratingCount"] == 1
    # A finished hire cannot be withdrawn afterwards to wriggle out of it.
    assert client.patch(f"/api/v1/equipment-enquiries/{enquiry_id}", json={"status": "withdrawn"}).status_code == 409


def test_only_an_agreed_hire_can_be_marked_done(client, seller):  # noqa: F811
    listing_id = _listed(client)
    enquiry_id = _enquiry_from(insert_profile("farmer"), listing_id)
    early = client.patch(f"/api/v1/equipment-enquiries/{enquiry_id}", json={"status": "completed"})
    assert early.status_code == 409
    # Someone who is neither side cannot rate or complete it.
    stranger_listing = insert_listing(insert_profile("partner_national"))
    theirs = _enquiry_from(insert_profile("farmer"), stranger_listing, status="completed")
    assert rate(client, "enquiry", theirs).status_code == 404


# --------------------------------------------------------------------------- #
# A partnership
# --------------------------------------------------------------------------- #


def _propose(client, farmer_id: str) -> dict:
    return client.post(
        "/api/v1/equipment-partnerships",
        json={"partnerKind": "farmer", "partnerProfileId": farmer_id, "role": "operator",
              "stateCode": UP, "districtCode": VARANASI},
    ).json()


def test_a_partnership_is_rated_once_it_has_run(client, seller):  # noqa: F811
    farmer = insert_profile("farmer", display_name="Mohan", state_code=UP, district_code=VARANASI)
    proposal = _propose(client, farmer)
    assert proposal["canRate"] is False
    assert rate(client, "partnership", proposal["id"]).status_code == 409

    with session_scope() as session:
        session.get(EquipmentPartnership, proposal["id"]).status = "active"  # the farmer accepted
    assert rate(client, "partnership", proposal["id"], 5, "Runs the tractor carefully").status_code == 201
    ended = client.patch(f"/api/v1/equipment-partnerships/{proposal['id']}", json={"status": "ended"}).json()
    assert ended["status"] == "ended"
    assert ended["canRate"] is True and ended["myRating"]["stars"] == 5, "a partnership that ran stays ratable"


def test_a_withdrawn_proposal_and_an_off_platform_partner_are_not_rated(client, seller):  # noqa: F811
    withdrawn = _propose(client, insert_profile("farmer", state_code=UP, district_code=VARANASI))
    client.patch(f"/api/v1/equipment-partnerships/{withdrawn['id']}", json={"status": "withdrawn"})
    assert rate(client, "partnership", withdrawn["id"]).status_code == 409

    offline = client.post(
        "/api/v1/equipment-partnerships",
        json={"partnerKind": "district", "contactName": "Ramu", "contactPhone": "9811111111", "role": "rental_point",
              "stateCode": UP, "districtCode": VARANASI},
    ).json()
    assert offline["status"] == "active"
    assert offline["canRate"] is False
    assert rate(client, "partnership", offline["id"]).status_code == 409


# --------------------------------------------------------------------------- #
# Through sync
# --------------------------------------------------------------------------- #


def test_the_other_side_marking_it_done_asks_you_to_rate(client):
    make_owner(client, farmer_body())
    seller_id = insert_profile("partner_national", display_name="Nashik Tractors")
    listing_id = insert_listing(seller_id, title="Rotavator")
    client.post(f"/api/v1/equipment/{listing_id}/enquiries", json={"kind": "rent"})
    with session_scope() as session:
        row = session.scalars(select(EquipmentEnquiry)).one()
        row.status = "completed"  # arrived from the seller's device
        session.flush()
        sync_client._hooks(session, "equipment_enquiry", row, {"status": "accepted"}, get_owner(session))
    with session_scope() as session:
        [note] = session.scalars(select(Notification).where(Notification.kind == "enquiry_completed")).all()
        assert note.params == {"title": "Rotavator", "name": "Nashik Tractors"} and note.link == "/machines"


def _enquiry_record(enquiry_id: str, farmer: str, listing_id: str, status: str) -> dict:
    return {"entity_type": "equipment_enquiry", "entity_id": enquiry_id,
            "payload": {"id": enquiry_id, "profile_id": farmer, "listing_id": listing_id, "kind": "rent",
                        "quantity": 1, "status": status}}


def _rating_record(rating_id: str, rater: str, rated: str, context_type: str, context_id: str, stars: int = 1) -> dict:
    return {"entity_type": "rating", "entity_id": rating_id,
            "payload": {"id": rating_id, "rater_profile_id": rater, "rated_profile_id": rated,
                        "context_type": context_type, "context_id": context_id, "stars": stars}}


def test_the_server_refuses_a_rating_for_work_that_did_not_happen(server):  # noqa: F811
    seller = OtherDevice(server, {"id": "a0000000-0000-0000-0000-0000000000f1", "segment": "partner_national"})
    farmer = OtherDevice(server, {"id": "a0000000-0000-0000-0000-0000000000f2", "segment": "farmer"})
    stranger = OtherDevice(server, {"id": "a0000000-0000-0000-0000-0000000000f3", "segment": "farmer"})
    s, f, x = seller.profile["id"], farmer.profile["id"], stranger.profile["id"]
    seller.push({"entity_type": "equipment_listing", "entity_id": "l1",
                 "payload": {"id": "l1", "profile_id": s, "title": "Tractor", "visibility": "online"}})
    farmer.push(_enquiry_record("e1", f, "l1", "sent"))

    # A stranger inventing a one-star rating, and the farmer rating before the hire is done.
    invented = stranger.push(_rating_record("r0", x, s, "enquiry", "e1"))
    assert invented["accepted"] == 0 and "finished together" in invented["rejected"][0]["reason"]
    early = farmer.push(_rating_record("r1", f, s, "enquiry", "e1", stars=2))
    assert early["accepted"] == 0
    assert farmer.push(_rating_record("r2", f, s, "deal", "no-such-deal"))["accepted"] == 0

    seller.push(_enquiry_record("e1", f, "l1", "accepted"))
    farmer.push(_enquiry_record("e1", f, "l1", "completed"))
    ok = farmer.push(_rating_record("r3", f, s, "enquiry", "e1", stars=4))
    assert ok["accepted"] == 1, ok
    pulled = [r for r in stranger.pull() if r["entityType"] == "rating"]
    assert [r["entityId"] for r in pulled] == ["r3"], "only the real rating reaches anyone"
