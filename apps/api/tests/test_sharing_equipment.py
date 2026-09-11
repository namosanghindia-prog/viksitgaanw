"""Share online, profile photos, the common timeline, and the equipment marketplace."""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from PIL import Image
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import AppEvent, EquipmentListing, EquipmentPartnership, SyncQueueEntry

from .conftest import NASHIK, PINDRA, UP, VARANASI
from .test_marketplace import insert_profile, insert_request, make_owner, request_body
from .test_profiles import farmer_body, investor_india_body, partner_national_body

MAHARASHTRA = "27"


def picture(width: int = 2000, height: int = 1500, fmt: str = "JPEG", with_exif: bool = True) -> bytes:
    image = Image.new("RGB", (width, height), (40, 120, 60))
    out = io.BytesIO()
    if with_exif and fmt == "JPEG":
        exif = Image.Exif()
        exif[0x010F] = "PhoneMaker"  # Make
        exif[0x0110] = "Model X"  # Model
        image.save(out, format=fmt, exif=exif)
    else:
        image.save(out, format=fmt)
    return out.getvalue()


def machine(**overrides) -> dict:
    body = {
        "equipmentType": "tractor",
        "title": "45 HP tractor with driver",
        "condition": "good",
        "yearMade": 2021,
        "forRent": True,
        "rentRate": 900,
        "rentUnit": "hour",
        "quantity": 3,
        "withOperator": True,
        "stateCode": UP,
        "districtCode": VARANASI,
        "subdistrictCode": PINDRA,
    }
    body.update(overrides)
    return body


def insert_listing(profile_id: str, **fields) -> str:
    """A machine listed on some other device and received by sync."""
    defaults = {
        "equipment_type": "harvester",
        "title": "Combine harvester",
        "condition": "good",
        "for_rent": True,
        "rent_rate": 2200,
        "rent_unit": "acre",
        "for_sale": False,
        "quantity": 2,
        "state_code": UP,
        "district_code": VARANASI,
        "status": "active",
        "visibility": "online",
        "origin": "synced",
    }
    defaults.update(fields)
    with session_scope() as session:
        listing = EquipmentListing(profile_id=profile_id, **defaults)
        session.add(listing)
        session.flush()
        return listing.id


@pytest.fixture()
def seller(client) -> dict:
    body = partner_national_body(stateCode=UP, districtCode=VARANASI)
    body["details"]["operatingStates"] = [UP]
    return make_owner(client, body)


# --------------------------------------------------------------------------- #
# Share online
# --------------------------------------------------------------------------- #


def test_everything_starts_offline(client, parcel_id):
    profile = client.post("/api/v1/profile", json=farmer_body()).json()
    assert profile["visibility"] == "offline"
    request = client.post("/api/v1/investment-requests", json=request_body(parcel_id)).json()
    assert request["visibility"] == "offline" and request["sharedAt"] is None


def test_an_item_needs_the_profile_shared_first(client, parcel_id):
    client.post("/api/v1/profile", json=farmer_body())
    request_id = client.post("/api/v1/investment-requests", json=request_body(parcel_id)).json()["id"]

    response = client.post(f"/api/v1/investment-requests/{request_id}/share")
    assert response.status_code == 409
    assert "Share your profile online first" in response.json()["detail"]

    client.post("/api/v1/profile/share")
    response = client.post(f"/api/v1/investment-requests/{request_id}/share")
    assert response.status_code == 200
    assert response.json()["visibility"] == "online" and response.json()["sharedAt"]

    with session_scope() as session:
        operations = session.scalars(
            select(SyncQueueEntry.operation).where(SyncQueueEntry.entity_id == request_id)
        ).all()
    assert "share" in operations


def test_taking_the_profile_offline_takes_everything_with_it(client, parcel_id):
    client.post("/api/v1/profile", json=farmer_body())
    client.post("/api/v1/profile/share")
    request_id = client.post("/api/v1/investment-requests", json=request_body(parcel_id)).json()["id"]
    client.post(f"/api/v1/investment-requests/{request_id}/share")

    profile = client.post("/api/v1/profile/unshare").json()
    assert profile["visibility"] == "offline"
    mine = client.get("/api/v1/investment-requests/mine").json()
    assert mine[0]["visibility"] == "offline"

    with session_scope() as session:
        events = session.scalars(select(AppEvent.event_type)).all()
    assert events.count("visibility.taken_offline") == 2


def test_offline_requests_are_invisible_to_others(client):
    make_owner(client, investor_india_body())
    farmer_id = insert_profile("farmer")
    hidden = insert_request(farmer_id, visibility="offline")
    shown = insert_request(farmer_id)

    ids = [row["id"] for row in client.get("/api/v1/investment-requests").json()]
    assert ids == [shown]
    assert client.get(f"/api/v1/investment-requests/{hidden}").status_code == 404


def test_answering_needs_a_shared_profile(client):
    client.post("/api/v1/profile", json=investor_india_body())
    request_id = insert_request(insert_profile("farmer"))
    response = client.post(
        f"/api/v1/investment-requests/{request_id}/interests", json={"mode": "revenue_share"}
    )
    assert response.status_code == 409
    assert "Share your profile" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Photos
# --------------------------------------------------------------------------- #


def test_profile_photo_is_resized_and_stripped_of_exif(client):
    client.post("/api/v1/profile", json=farmer_body())
    response = client.put(
        "/api/v1/profile/photo", content=picture(), headers={"Content-Type": "image/jpeg"}
    )
    assert response.status_code == 200, response.text
    url = response.json()["photoUrl"]
    assert url.startswith("/media/")

    stored = client.get(f"/api/v1{url}")
    assert stored.status_code == 200
    assert stored.headers["content-type"] == "image/jpeg"
    image = Image.open(io.BytesIO(stored.content))
    assert max(image.size) == 512
    assert dict(image.getexif()) == {}, "EXIF can carry where the photo was taken"

    # The file lives beside the database, not in the repository.
    assert any(get_settings().media_dir.glob("profile-*.jpg"))


def test_a_new_photo_replaces_the_old_one(client):
    client.post("/api/v1/profile", json=farmer_body())
    first = client.put(
        "/api/v1/profile/photo", content=picture(), headers={"Content-Type": "image/jpeg"}
    ).json()["photoUrl"]
    second = client.put(
        "/api/v1/profile/photo",
        content=picture(fmt="PNG", with_exif=False),
        headers={"Content-Type": "image/png"},
    ).json()["photoUrl"]
    assert first != second
    assert client.get(f"/api/v1{first}").status_code == 404

    removed = client.delete("/api/v1/profile/photo").json()
    assert removed["photoUrl"] is None


def test_only_real_pictures_are_accepted(client):
    client.post("/api/v1/profile", json=farmer_body())
    response = client.put(
        "/api/v1/profile/photo", content=b"not a picture", headers={"Content-Type": "image/jpeg"}
    )
    assert response.status_code == 422
    response = client.put(
        "/api/v1/profile/photo", content=b"%PDF-1.4", headers={"Content-Type": "application/pdf"}
    )
    assert response.status_code == 415


# --------------------------------------------------------------------------- #
# Organisations that partner and invest
# --------------------------------------------------------------------------- #


def test_a_partner_organisation_can_also_invest(client):
    body = partner_national_body()
    body["details"].update({"alsoInvests": True})
    response = client.post("/api/v1/profile", json=body)
    assert response.status_code == 422
    assert "invests" in response.text

    body["details"].update({"investmentModes": ["revenue_share"], "ticketMax": 1000000})
    make_owner(client, body)

    request_id = insert_request(
        insert_profile("farmer"), state_code=MAHARASHTRA, district_code=NASHIK, subdistrict_code=None
    )
    response = client.post(
        f"/api/v1/investment-requests/{request_id}/interests",
        json={"kind": "investment", "mode": "revenue_share", "amountOffered": 250000},
    )
    assert response.status_code == 201, response.text
    assert response.json()["myInterest"]["kind"] == "investment"


def test_a_partner_that_does_not_invest_cannot_offer_money(client):
    make_owner(client, partner_national_body())
    request_id = insert_request(
        insert_profile("farmer"), state_code=MAHARASHTRA, district_code=NASHIK, subdistrict_code=None
    )
    response = client.post(
        f"/api/v1/investment-requests/{request_id}/interests",
        json={"kind": "investment", "mode": "revenue_share"},
    )
    assert response.status_code == 422
    assert "also invest" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Equipment listings
# --------------------------------------------------------------------------- #


def test_only_organisations_list_machines(client):
    make_owner(client, farmer_body())
    assert client.post("/api/v1/equipment", json=machine()).status_code == 403


def test_listing_rules(client, seller):
    no_offer = machine(forRent=False)
    response = client.post("/api/v1/equipment", json=no_offer)
    assert response.status_code == 422
    assert "for sale, for rent" in response.text

    no_price = machine(forSale=True)
    assert client.post("/api/v1/equipment", json=no_price).status_code == 422

    wrong_place = machine(districtCode=NASHIK, subdistrictCode=None)
    assert client.post("/api/v1/equipment", json=wrong_place).status_code == 422


def test_a_listing_starts_offline_with_photos_and_can_be_shared(client, seller):
    listing = client.post("/api/v1/equipment", json=machine()).json()
    assert listing["visibility"] == "offline"
    assert listing["place"].startswith("Pindra, Varanasi")

    for _ in range(4):
        response = client.post(
            f"/api/v1/equipment/{listing['id']}/photos",
            content=picture(),
            headers={"Content-Type": "image/jpeg"},
        )
        assert response.status_code == 200, response.text
    assert len(response.json()["photos"]) == 4
    assert max(response.json()["photos"][0]["width"], response.json()["photos"][0]["height"]) == 1280
    too_many = client.post(
        f"/api/v1/equipment/{listing['id']}/photos",
        content=picture(),
        headers={"Content-Type": "image/jpeg"},
    )
    assert too_many.status_code == 409

    shared = client.post(f"/api/v1/equipment/{listing['id']}/share").json()
    assert shared["visibility"] == "online"
    assert [row["id"] for row in client.get("/api/v1/equipment/mine").json()] == [listing["id"]]


def test_browsing_machines(client):
    make_owner(client, farmer_body())
    seller_id = insert_profile("partner_national", organisation_name="Doaba Agro")
    harvester = insert_listing(seller_id)
    insert_listing(seller_id, equipment_type="chaff_cutter", for_rent=False, rent_rate=None, rent_unit=None, for_sale=True, sale_price=18500)
    insert_listing(seller_id, visibility="offline")
    insert_listing(seller_id, status="sold")

    rows = client.get("/api/v1/equipment").json()
    assert len(rows) == 2
    assert all(row["seller"]["contact"] is None for row in rows)
    rent = client.get("/api/v1/equipment", params={"offer": "rent"}).json()
    assert [row["id"] for row in rent] == [harvester]
    by_type = client.get("/api/v1/equipment", params={"type": "chaff_cutter"}).json()
    assert len(by_type) == 1 and by_type[0]["forSale"] is True


# --------------------------------------------------------------------------- #
# Enquiries
# --------------------------------------------------------------------------- #


def test_farmer_asks_to_rent_and_the_seller_is_revealed_on_acceptance(client):
    make_owner(client, farmer_body())
    seller_id = insert_profile("partner_national", phone="+919812345678")
    listing_id = insert_listing(seller_id)
    start = (date.today() + timedelta(days=7)).isoformat()
    end = (date.today() + timedelta(days=8)).isoformat()

    response = client.post(
        f"/api/v1/equipment/{listing_id}/enquiries",
        json={"kind": "rent", "startDate": start, "endDate": end, "areaAcres": 4, "message": "Before the rains"},
    )
    assert response.status_code == 201, response.text
    enquiry = response.json()["myEnquiry"]
    assert enquiry["status"] == "sent" and enquiry["areaAcres"] == 4

    buy = client.post(f"/api/v1/equipment/{listing_id}/enquiries", json={"kind": "buy"})
    assert buy.status_code == 422, "the harvester is for rent only"
    too_many = client.post(f"/api/v1/equipment/{listing_id}/enquiries", json={"kind": "rent", "quantity": 9})
    assert too_many.status_code == 422

    # The seller, on their device, accepts; that arrives here by sync.
    from app.models import EquipmentEnquiry

    with session_scope() as session:
        row = session.get(EquipmentEnquiry, enquiry["id"])
        row.status = "accepted"
    listing = client.get(f"/api/v1/equipment/{listing_id}").json()
    assert listing["myEnquiry"]["status"] == "accepted"
    assert listing["seller"]["contact"]["phone"] == "+919812345678"

    listed = client.get("/api/v1/equipment-enquiries/mine").json()
    assert [row["id"] for row in listed] == [listing_id]


def test_seller_answers_an_enquiry(client, seller):
    listing = client.post("/api/v1/equipment", json=machine()).json()
    client.post(f"/api/v1/equipment/{listing['id']}/share")
    farmer_id = insert_profile("farmer", phone="+919811111111")
    from app.models import EquipmentEnquiry

    with session_scope() as session:
        enquiry = EquipmentEnquiry(
            listing_id=listing["id"], profile_id=farmer_id, kind="rent", quantity=1, origin="synced"
        )
        session.add(enquiry)
        session.flush()
        enquiry_id = enquiry.id

    mine = client.get("/api/v1/equipment/mine").json()[0]
    assert mine["enquiryCounts"] == {"sent": 1}
    assert mine["enquiries"][0]["enquirer"]["contact"] is None

    response = client.patch(f"/api/v1/equipment-enquiries/{enquiry_id}", json={"status": "accepted"})
    assert response.status_code == 200, response.text
    assert response.json()["enquiries"][0]["enquirer"]["contact"]["phone"] == "+919811111111"
    with session_scope() as session:
        events = session.scalars(select(AppEvent.event_type)).all()
    assert "equipment_enquiry.accepted" in events

    again = client.patch(f"/api/v1/equipment-enquiries/{enquiry_id}", json={"status": "declined"})
    assert again.status_code == 409


def test_asking_needs_a_shared_profile(client):
    client.post("/api/v1/profile", json=farmer_body())
    listing_id = insert_listing(insert_profile("partner_national"))
    response = client.post(f"/api/v1/equipment/{listing_id}/enquiries", json={"kind": "rent"})
    assert response.status_code == 409


# --------------------------------------------------------------------------- #
# Partner network
# --------------------------------------------------------------------------- #


def test_seller_records_an_off_platform_village_partner(client, seller):
    from .conftest import RAMPUR_BUJURG

    response = client.post(
        "/api/v1/equipment-partnerships",
        json={
            "partnerKind": "village",
            "contactName": "Ram Prasad",
            "contactPhone": "98765 11111",
            "stateCode": UP,
            "districtCode": VARANASI,
            "subdistrictCode": PINDRA,
            "villageCode": RAMPUR_BUJURG,
            "role": "rental_point",
            "equipmentTypes": ["tractor", "rotavator"],
            "commissionPercent": 10,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # Nobody to wait for: an off-platform partner is recorded as active.
    assert body["status"] == "active" and body["isSeller"] is True
    assert body["contactPhone"] == "+919876511111"
    assert body["area"].startswith("Rampur Bujurg")


def test_village_and_district_partners_need_a_place(client, seller):
    response = client.post(
        "/api/v1/equipment-partnerships",
        json={"partnerKind": "village", "contactName": "Ram", "role": "rental_point"},
    )
    assert response.status_code == 422
    response = client.post(
        "/api/v1/equipment-partnerships",
        json={"partnerKind": "district", "contactName": "Dealer", "role": "distributor", "stateCode": UP},
    )
    assert response.status_code == 422


def test_seller_proposes_to_a_farmer_on_the_platform(client, seller):
    farmer_id = insert_profile("farmer", display_name="Mohan", state_code=UP, district_code=VARANASI)
    response = client.post(
        "/api/v1/equipment-partnerships",
        json={"partnerKind": "farmer", "partnerProfileId": farmer_id, "role": "operator", "stateCode": UP, "districtCode": VARANASI},
    )
    assert response.status_code == 201, response.text
    partnership = response.json()
    assert partnership["status"] == "proposed"
    assert partnership["partner"]["displayName"] == "Mohan"

    # The seller cannot accept their own proposal.
    own = client.patch(f"/api/v1/equipment-partnerships/{partnership['id']}", json={"status": "active"})
    assert own.status_code == 403
    # But may withdraw it.
    ended = client.patch(f"/api/v1/equipment-partnerships/{partnership['id']}", json={"status": "ended"})
    assert ended.json()["status"] == "ended"

    distributor = client.post(
        "/api/v1/equipment-partnerships",
        json={"partnerKind": "distributor", "partnerProfileId": farmer_id, "role": "distributor"},
    )
    assert distributor.status_code == 422, "a farmer is not a distributor organisation"


def test_known_profiles_lists_only_shared_ones(client, seller):
    shown = insert_profile("farmer", display_name="Shared farmer")
    insert_profile("farmer", display_name="Private farmer", visibility="offline")
    rows = client.get("/api/v1/profiles", params={"segment": "farmer"}).json()
    assert [row["id"] for row in rows] == [shown]
    assert rows[0]["contact"] is None


def test_farmer_becomes_a_direct_partner(client):
    make_owner(client, farmer_body())
    seller_id = insert_profile("partner_national", organisation_name="Kisan Yantra", phone="+919822222222")
    listing_id = insert_listing(seller_id)

    response = client.post(
        f"/api/v1/equipment-sellers/{seller_id}/partnerships",
        json={"role": "rental_point", "equipmentTypes": ["harvester"], "message": "I have a shed."},
    )
    assert response.status_code == 201, response.text
    partnership = response.json()
    assert partnership["partnerKind"] == "farmer" and partnership["initiatedBy"] == "partner"
    assert partnership["area"].startswith("Rampur Bujurg"), "covers the farmer's own village"

    again = client.post(f"/api/v1/equipment-sellers/{seller_id}/partnerships", json={"role": "operator"})
    assert again.status_code == 409
    own = client.patch(f"/api/v1/equipment-partnerships/{partnership['id']}", json={"status": "active"})
    assert own.status_code == 403, "the seller answers, not the farmer"

    listing = client.get(f"/api/v1/equipment/{listing_id}").json()
    assert listing["myPartnership"]["status"] == "proposed"
    assert listing["seller"]["contact"] is None

    with session_scope() as session:
        session.get(EquipmentPartnership, partnership["id"]).status = "active"
    listing = client.get(f"/api/v1/equipment/{listing_id}").json()
    assert listing["seller"]["contact"]["phone"] == "+919822222222"


def test_investors_cannot_become_equipment_partners(client):
    make_owner(client, investor_india_body())
    seller_id = insert_profile("partner_national")
    response = client.post(f"/api/v1/equipment-sellers/{seller_id}/partnerships", json={"role": "sales_agent"})
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# Timeline
# --------------------------------------------------------------------------- #


def test_timeline_mixes_projects_and_machines_newest_first(client):
    from datetime import datetime, timezone

    make_owner(client, investor_india_body())
    farmer_id = insert_profile("farmer")
    seller_id = insert_profile("partner_national")
    now = datetime.now(timezone.utc)
    old_project = insert_request(farmer_id, shared_at=now - timedelta(days=2))
    new_machine = insert_listing(seller_id, shared_at=now - timedelta(hours=1))
    insert_request(farmer_id, visibility="offline")
    insert_request(farmer_id, open_to=["partner_national"], shared_at=now)

    items = client.get("/api/v1/timeline").json()
    assert [(item["type"], item["id"]) for item in items] == [
        ("equipment", new_machine),
        ("project", old_project),
    ]
    assert items[0]["equipment"]["title"] and items[1]["project"]["title"]

    only_projects = client.get("/api/v1/timeline", params={"kind": "project"}).json()
    assert [item["id"] for item in only_projects] == [old_project]


def test_farmers_see_projects_only_when_shown_to_farmers(client, parcel_id):
    make_owner(client, farmer_body())
    farmer_id = insert_profile("farmer")
    hidden = insert_request(farmer_id)
    shown = insert_request(farmer_id, open_to=["investor_india", "farmer"])

    ids = [item["id"] for item in client.get("/api/v1/timeline").json()]
    assert shown in ids and hidden not in ids

    # A farmer's own shared request is on their timeline too.
    mine = client.post(
        "/api/v1/investment-requests", json=request_body(parcel_id, openTo=["investor_india", "partner_national", "farmer"])
    ).json()
    client.post(f"/api/v1/investment-requests/{mine['id']}/share")
    ids = [item["id"] for item in client.get("/api/v1/timeline").json()]
    assert mine["id"] in ids
