"""Investment requests, interests, visibility and fit.

One profile per device means a single test can only ever *be* one person.
The other side of every exchange is inserted straight into the database with
``origin="synced"``, which is exactly how it will arrive once cloud sync
exists.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, InvestmentInterest, InvestmentRequest, Profile
from app.services.marketplace import make_listing

from .conftest import NASHIK, PINDRA, RAMPUR_BUJURG, UP, VARANASI
from .test_profiles import (
    farmer_body,
    government_body,
    investor_india_body,
    investor_international_body,
    partner_national_body,
)

MAHARASHTRA = "27"


def request_body(parcel_id: str, **overrides) -> dict:
    body = {
        "parcelId": parcel_id,
        "opportunityCode": "pomegranate_orchard",
        "title": "Pomegranate orchard on 1 acre",
        "summary": "Drip is already in. Need money for saplings and trellis.",
        "amountSought": 450000,
        "ownContribution": 100000,
        "seeking": ["investment", "partnership"],
        "modes": ["revenue_share", "loan"],
        "partnershipTypes": ["buy_back"],
        "openTo": ["investor_india", "partner_national", "government"],
    }
    body.update(overrides)
    return body


def insert_profile(segment: str, **fields) -> str:
    defaults = {
        "display_name": f"Synced {segment}",
        "phone": "+919800000001",
        "email": f"{segment}@example.com",
        "country_code": "IN",
        "details": {},
        "origin": "synced",
        "is_device_owner": False,
        # Anything that reached this device by sync was shared online.
        "visibility": "online",
    }
    defaults.update(fields)
    with session_scope() as session:
        profile = Profile(segment=segment, **defaults)
        session.add(profile)
        session.flush()
        return profile.id


def insert_request(profile_id: str, **fields) -> str:
    """A request from a farmer on some other device."""
    state = fields.pop("state_code", UP)
    district = fields.pop("district_code", VARANASI)
    subdistrict = fields.pop("subdistrict_code", PINDRA)
    with session_scope() as session:
        listing = make_listing(
            session,
            state_code=state,
            district_code=district,
            subdistrict_code=subdistrict,
            village_code=None,
            land={"areaHectares": 0.8, "existingCrops": ["grapes", "onion"]},
            opportunity_code="pomegranate_orchard",
            plan=None,
        )
        defaults = {
            "title": "Orchard on a synced device",
            "amount_sought": 600000,
            "seeking": ["investment", "partnership"],
            "modes": ["revenue_share"],
            "partnership_types": ["buy_back"],
            "open_to": ["investor_india", "investor_international", "partner_national", "government"],
            "opportunity_code": "pomegranate_orchard",
            "opportunity_kind": "horticulture",
            "listing": listing,
            "status": "open",
            "visibility": "online",
            "origin": "synced",
        }
        defaults.update(fields)
        request = InvestmentRequest(
            profile_id=profile_id,
            state_code=state,
            district_code=district,
            subdistrict_code=subdistrict,
            **defaults,
        )
        session.add(request)
        session.flush()
        return request.id


def insert_interest(request_id: str, profile_id: str, **fields) -> str:
    defaults = {
        "kind": "investment",
        "amount_offered": 300000,
        "mode": "revenue_share",
        "status": "sent",
        "origin": "synced",
    }
    defaults.update(fields)
    with session_scope() as session:
        interest = InvestmentInterest(request_id=request_id, profile_id=profile_id, **defaults)
        session.add(interest)
        session.flush()
        return interest.id


def make_owner(client, body: dict) -> dict:
    """Create this device's profile and share it online, as answering requires."""
    response = client.post("/api/v1/profile", json=body)
    assert response.status_code == 201, response.text
    shared = client.post("/api/v1/profile/share")
    assert shared.status_code == 200, shared.text
    return shared.json()


def event_types() -> list[str]:
    with session_scope() as session:
        return list(session.scalars(select(AppEvent.event_type)))


@pytest.fixture()
def farmer(client) -> dict:
    response = client.post("/api/v1/profile", json=farmer_body())
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def investor(client) -> dict:
    return make_owner(client, investor_india_body())


# --------------------------------------------------------------------------- #
# The farmer's side
# --------------------------------------------------------------------------- #


def test_marketplace_needs_a_profile(client, parcel_id):
    response = client.post("/api/v1/investment-requests", json=request_body(parcel_id))
    assert response.status_code == 409
    assert "profile" in response.json()["detail"]


def test_farmer_publishes_a_request(client, farmer, parcel_id):
    response = client.post("/api/v1/investment-requests", json=request_body(parcel_id))
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["isMine"] is True
    assert body["status"] == "open"
    assert body["opportunityKind"] == "horticulture"
    assert body["stateCode"] == UP and body["districtCode"] == VARANASI

    listing = body["listing"]
    assert listing["location"]["village"]["code"] == RAMPUR_BUJURG
    assert listing["location"]["district"]["name"]
    assert listing["land"]["soilType"] == "alluvial"
    assert listing["opportunity"]["name"]["en"]
    # An investor abroad sees where the model comes from, and whether it is a hybrid.
    assert listing["opportunity"]["sector"] in {"farm", "nonfarm", "hybrid"}
    assert len(listing["opportunity"]["origin"]["country"]) == 2
    assert listing["opportunity"]["origin"]["note"]["en"]
    # Nothing that lets a stranger find the field or phone the farmer.
    assert "surveyNumber" not in listing["land"]
    assert "phone" not in str(listing)
    assert body["requester"]["contact"] is None

    assert "investment_request.created" in event_types()
    mine = client.get("/api/v1/investment-requests/mine").json()
    assert [row["id"] for row in mine] == [body["id"]]


def test_request_carries_the_project_report_figures(client, farmer, parcel_id):
    report = client.post(
        f"/api/v1/land-parcels/{parcel_id}/reports",
        json={"opportunityCode": "pomegranate_orchard", "language": "en", "promoterName": "Ramesh"},
    )
    assert report.status_code == 201, report.text
    report = report.json()

    response = client.post(
        "/api/v1/investment-requests",
        json=request_body(parcel_id, reportId=report["id"], opportunityCode=None),
    )
    assert response.status_code == 201, response.text
    plan = response.json()["listing"]["plan"]
    assert plan["reportNumber"] == report["reportNumber"]
    assert plan["totalProjectCost"] == report["totalProjectCost"]
    assert response.json()["opportunityCode"] == "pomegranate_orchard"


def test_request_validation(client, farmer, parcel_id):
    no_modes = request_body(parcel_id, modes=[])
    assert client.post("/api/v1/investment-requests", json=no_modes).status_code == 422

    partners_only = request_body(parcel_id, openTo=["partner_national"])
    response = client.post("/api/v1/investment-requests", json=partners_only)
    assert response.status_code == 422
    assert "investor" in response.text

    to_farmers = request_body(parcel_id, openTo=["farmer"])
    assert client.post("/api/v1/investment-requests", json=to_farmers).status_code == 422

    missing_land = request_body("no-such-parcel")
    assert client.post("/api/v1/investment-requests", json=missing_land).status_code == 404


def test_only_farmers_ask_for_investment(client, investor, parcel_id):
    response = client.post("/api/v1/investment-requests", json=request_body(parcel_id))
    assert response.status_code == 403


def test_farmers_do_not_browse(client, farmer):
    assert client.get("/api/v1/investment-requests").status_code == 403


def test_farmer_accepts_an_interest_and_contact_is_shared(client, farmer, parcel_id):
    request_id = client.post(
        "/api/v1/investment-requests", json=request_body(parcel_id)
    ).json()["id"]
    investor_id = insert_profile(
        "investor_india",
        display_name="Priya",
        organisation_name="Sharma Agri",
        details={"investor_type": "family_office"},
    )
    interest_id = insert_interest(request_id, investor_id, message="Happy to fund saplings.")

    mine = client.get("/api/v1/investment-requests/mine").json()[0]
    assert mine["interestCounts"] == {"sent": 1}
    [interest] = mine["interests"]
    assert interest["responder"]["organisationName"] == "Sharma Agri"
    assert interest["responder"]["typeCode"] == "family_office"
    assert interest["responder"]["contact"] is None

    response = client.patch(
        f"/api/v1/investment-interests/{interest_id}", json={"status": "accepted"}
    )
    assert response.status_code == 200, response.text
    [interest] = response.json()["interests"]
    assert interest["status"] == "accepted"
    assert interest["responder"]["contact"]["phone"] == "+919800000001"
    assert "investment_interest.accepted" in event_types()

    again = client.patch(
        f"/api/v1/investment-interests/{interest_id}", json={"status": "declined"}
    )
    assert again.status_code == 409


def test_farmer_cannot_withdraw_someone_elses_interest(client, farmer, parcel_id):
    request_id = client.post(
        "/api/v1/investment-requests", json=request_body(parcel_id)
    ).json()["id"]
    interest_id = insert_interest(request_id, insert_profile("investor_india"))
    response = client.patch(
        f"/api/v1/investment-interests/{interest_id}", json={"status": "withdrawn"}
    )
    assert response.status_code == 403


def test_closing_a_request(client, farmer, parcel_id):
    request_id = client.post(
        "/api/v1/investment-requests", json=request_body(parcel_id)
    ).json()["id"]
    response = client.patch(
        f"/api/v1/investment-requests/{request_id}", json={"status": "closed"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "closed"

    interest_id = insert_interest(request_id, insert_profile("investor_india"))
    response = client.patch(
        f"/api/v1/investment-interests/{interest_id}", json={"status": "accepted"}
    )
    assert response.status_code == 409


# --------------------------------------------------------------------------- #
# The investor's and partner's side
# --------------------------------------------------------------------------- #


def test_investor_browses_and_sends_interest(client, investor):
    farmer_id = insert_profile("farmer", display_name="Ramesh", state_code=UP, district_code=VARANASI)
    request_id = insert_request(farmer_id)

    rows = client.get("/api/v1/investment-requests").json()
    assert [row["id"] for row in rows] == [request_id]
    row = rows[0]
    assert row["isMine"] is False
    assert row["requester"]["displayName"] == "Ramesh"
    assert row["requester"]["contact"] is None
    assert row["interests"] == []
    # Preferred state, sector and ticket size all match the investor profile.
    assert row["fit"]["score"] >= 80
    assert {"state", "sector", "ticket", "mode"} <= set(row["fit"]["reasons"])

    response = client.post(
        f"/api/v1/investment-requests/{request_id}/interests",
        json={"amountOffered": 300000, "mode": "revenue_share", "message": "Interested."},
    )
    assert response.status_code == 201, response.text
    mine = response.json()["myInterest"]
    assert mine["status"] == "sent" and mine["kind"] == "investment"

    # Sending again updates the terms instead of stacking a second interest.
    response = client.post(
        f"/api/v1/investment-requests/{request_id}/interests",
        json={"amountOffered": 350000, "mode": "loan"},
    )
    assert response.status_code == 201
    assert response.json()["myInterest"]["amountOffered"] == 350000
    with session_scope() as session:
        assert len(session.scalars(select(InvestmentInterest)).all()) == 1

    listed = client.get("/api/v1/investment-interests/mine").json()
    assert [row["id"] for row in listed] == [request_id]


def test_investor_must_say_how_they_would_invest(client, investor):
    request_id = insert_request(insert_profile("farmer"))
    response = client.post(
        f"/api/v1/investment-requests/{request_id}/interests", json={"amountOffered": 1000}
    )
    assert response.status_code == 422


def test_contact_is_shared_once_accepted(client, investor):
    farmer_id = insert_profile("farmer", phone="+919811111111")
    request_id = insert_request(farmer_id)
    insert_interest(request_id, investor["id"], status="accepted")

    row = client.get(f"/api/v1/investment-requests/{request_id}").json()
    assert row["myInterest"]["status"] == "accepted"
    assert row["requester"]["contact"]["phone"] == "+919811111111"


def test_investor_withdraws(client, investor):
    request_id = insert_request(insert_profile("farmer"))
    interest_id = insert_interest(request_id, investor["id"])
    response = client.patch(
        f"/api/v1/investment-interests/{interest_id}", json={"status": "withdrawn"}
    )
    assert response.status_code == 200
    assert response.json()["myInterest"]["status"] == "withdrawn"

    # And the investor cannot accept on the farmer's behalf.
    other = insert_interest(insert_request(insert_profile("farmer")), investor["id"])
    response = client.patch(
        f"/api/v1/investment-interests/{other}", json={"status": "accepted"}
    )
    assert response.status_code == 403


def test_requests_hidden_from_segments_not_chosen(client):
    make_owner(client, investor_international_body())
    request_id = insert_request(
        insert_profile("farmer"), open_to=["investor_india", "partner_national"]
    )
    assert client.get("/api/v1/investment-requests").json() == []
    assert client.get(f"/api/v1/investment-requests/{request_id}").status_code == 404
    response = client.post(
        f"/api/v1/investment-requests/{request_id}/interests",
        json={"mode": "offtake"},
    )
    assert response.status_code == 404


def test_closed_requests_are_not_listed_or_answerable(client, investor):
    request_id = insert_request(insert_profile("farmer"), status="closed")
    assert client.get("/api/v1/investment-requests").json() == []
    response = client.post(
        f"/api/v1/investment-requests/{request_id}/interests", json={"mode": "loan"}
    )
    assert response.status_code == 409


def test_partner_offers_a_partnership(client):
    make_owner(client, partner_national_body())
    request_id = insert_request(
        insert_profile("farmer"),
        state_code=MAHARASHTRA,
        district_code=NASHIK,
        subdistrict_code=None,
    )
    [row] = client.get("/api/v1/investment-requests").json()
    assert {"state", "partnership", "crop"} <= set(row["fit"]["reasons"])

    response = client.post(
        f"/api/v1/investment-requests/{request_id}/interests",
        json={"partnershipType": "buy_back", "amountOffered": 99, "mode": "loan"},
    )
    assert response.status_code == 201, response.text
    mine = response.json()["myInterest"]
    assert mine["kind"] == "partnership"
    assert mine["partnershipType"] == "buy_back"
    # Money terms do not belong on a partnership offer.
    assert mine["amountOffered"] is None and mine["mode"] is None


def test_partner_cannot_answer_an_investment_only_request(client):
    make_owner(client, partner_national_body())
    request_id = insert_request(
        insert_profile("farmer"),
        seeking=["investment"],
        partnership_types=[],
    )
    response = client.post(
        f"/api/v1/investment-requests/{request_id}/interests",
        json={"partnershipType": "buy_back"},
    )
    assert response.status_code == 409


def test_filtering_by_kind_and_state(client, investor):
    farmer_id = insert_profile("farmer")
    in_up = insert_request(farmer_id)
    insert_request(farmer_id, state_code=MAHARASHTRA, district_code=NASHIK, subdistrict_code=None)

    rows = client.get("/api/v1/investment-requests", params={"stateCode": UP}).json()
    assert [row["id"] for row in rows] == [in_up]
    assert client.get("/api/v1/investment-requests", params={"kind": "livestock"}).json() == []


# --------------------------------------------------------------------------- #
# Government
# --------------------------------------------------------------------------- #


def test_block_officer_sees_only_their_block_and_only_with_consent(client):
    make_owner(client, government_body())
    farmer_id = insert_profile("farmer")
    in_block = insert_request(farmer_id)
    insert_request(farmer_id, open_to=["investor_india"])  # no consent
    insert_request(
        farmer_id, state_code=MAHARASHTRA, district_code=NASHIK, subdistrict_code=None
    )  # elsewhere

    rows = client.get("/api/v1/investment-requests").json()
    assert [row["id"] for row in rows] == [in_block]
    assert rows[0]["fit"] is None

    response = client.post(
        f"/api/v1/investment-requests/{in_block}/interests", json={"mode": "grant"}
    )
    assert response.status_code == 403
