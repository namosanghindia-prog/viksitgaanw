"""Device-owner profiles for all six segments."""

from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, Farmer, SyncQueueEntry

from .conftest import NASHIK, PINDRA, RAMPUR_BUJURG, UP, VARANASI

MAHARASHTRA = "27"


def farmer_body(**overrides) -> dict:
    body = {
        "segment": "farmer",
        "displayName": "Ramesh Yadav",
        "phone": "98765 43210",
        "preferredLanguage": "hi",
        "stateCode": UP,
        "districtCode": VARANASI,
        "subdistrictCode": PINDRA,
        "villageCode": RAMPUR_BUJURG,
        "details": {"yearsFarming": 20, "needs": ["investment", "loan"], "hasKcc": True},
    }
    body.update(overrides)
    return body


def investor_india_body(**overrides) -> dict:
    body = {
        "segment": "investor_india",
        "displayName": "Priya Sharma",
        "organisationName": "Sharma Agri Ventures",
        "phone": "+91 91234 56789",
        "stateCode": UP,
        "details": {
            "investorType": "family_office",
            "pan": "abcde1234f",
            "sectors": ["horticulture", "livestock"],
            "modes": ["revenue_share", "equity"],
            "ticketMin": 200000,
            "ticketMax": 2500000,
            "preferredStates": [UP],
            "riskAppetite": "medium",
        },
    }
    body.update(overrides)
    return body


def investor_international_body(**overrides) -> dict:
    body = {
        "segment": "investor_international",
        "displayName": "Anil Mehta",
        "email": "Anil@Example.com",
        "phone": "+44 20 7946 0958",
        "countryCode": "gb",
        "city": "London",
        "details": {
            "investorType": "nri",
            "modes": ["offtake"],
            "complianceAcknowledged": True,
        },
    }
    body.update(overrides)
    return body


def partner_national_body(**overrides) -> dict:
    body = {
        "segment": "partner_national",
        "displayName": "Sunita Patil",
        "organisationName": "Nashik Grape Growers FPO",
        "phone": "9822012345",
        "stateCode": MAHARASHTRA,
        "districtCode": NASHIK,
        "details": {
            "organisationType": "fpo",
            "gstin": "27abcde1234f1z5",
            "partnershipTypes": ["buy_back", "export"],
            "crops": ["grapes"],
            "operatingStates": [MAHARASHTRA],
            "memberFarmers": 850,
        },
    }
    body.update(overrides)
    return body


def partner_international_body(**overrides) -> dict:
    body = {
        "segment": "partner_international",
        "displayName": "Jan de Vries",
        "organisationName": "Holland Fresh Imports BV",
        "email": "jan@hollandfresh.example",
        "countryCode": "NL",
        "city": "Rotterdam",
        "details": {
            "organisationType": "importer",
            "partnershipTypes": ["buy_back", "certification"],
            "crops": ["grapes", "pomegranate"],
            "certificationsRequired": ["globalgap"],
        },
    }
    body.update(overrides)
    return body


def government_body(**overrides) -> dict:
    body = {
        "segment": "government",
        "displayName": "Rakesh Verma",
        "organisationName": "Block Agriculture Office, Pindra",
        "email": "bao.pindra@up.gov.in",
        "stateCode": UP,
        "districtCode": VARANASI,
        "subdistrictCode": PINDRA,
        "details": {
            "level": "block",
            "department": "Department of Agriculture",
            "designation": "Block Agriculture Officer",
        },
    }
    body.update(overrides)
    return body


def test_no_profile_before_onboarding(client):
    response = client.get("/api/v1/profile")
    assert response.status_code == 200
    assert response.json() is None


def test_farmer_profile_links_the_device_farmer(client, parcel_id):
    response = client.post("/api/v1/profile", json=farmer_body())
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["segment"] == "farmer"
    assert body["phone"] == "+919876543210"
    assert body["location"]["village"]["code"] == RAMPUR_BUJURG
    assert body["details"]["yearsFarming"] == 20
    assert body["details"]["hasKcc"] is True
    assert body["kycStatus"] == "unverified"
    assert "aadhaar_ekyc" in body["kycMethods"]

    # The land saved before onboarding belongs to the same person.
    parcel = client.get(f"/api/v1/land-parcels/{parcel_id}").json()
    assert parcel["farmerId"] == body["farmerId"]
    with session_scope() as session:
        farmer = session.get(Farmer, body["farmerId"])
        assert farmer.name == "Ramesh Yadav"
        assert farmer.phone == "+919876543210"

        events = session.scalars(
            select(AppEvent.event_type).where(AppEvent.entity_id == body["id"])
        ).all()
        assert "profile.created" in events
        queued = session.scalars(
            select(SyncQueueEntry).where(SyncQueueEntry.entity_id == body["id"])
        ).all()
        assert [entry.operation for entry in queued] == ["create"]


def test_only_one_profile_per_device(client):
    assert client.post("/api/v1/profile", json=farmer_body()).status_code == 201
    response = client.post("/api/v1/profile", json=investor_india_body())
    assert response.status_code == 409


def test_farmer_needs_phone_and_district(client):
    response = client.post("/api/v1/profile", json=farmer_body(phone=None))
    assert response.status_code == 422
    assert "mobile number" in response.text

    response = client.post(
        "/api/v1/profile",
        json=farmer_body(districtCode=None, subdistrictCode=None, villageCode=None),
    )
    assert response.status_code == 422
    assert "district" in response.text


def test_phone_must_be_a_real_indian_mobile(client):
    response = client.post("/api/v1/profile", json=farmer_body(phone="12345"))
    assert response.status_code == 422
    assert "10-digit Indian mobile" in response.text


def test_location_codes_are_checked_against_lgd(client):
    response = client.post(
        "/api/v1/profile", json=farmer_body(districtCode=NASHIK, subdistrictCode=None, villageCode=None)
    )
    assert response.status_code == 422
    assert "does not belong to state" in response.json()["detail"]


def test_indian_investor_profile(client):
    response = client.post("/api/v1/profile", json=investor_india_body())
    assert response.status_code == 201, response.text
    details = response.json()["details"]
    assert details["pan"] == "ABCDE1234F"
    assert details["preferredStates"] == [UP]
    assert details["ticketMax"] == 2500000


def test_indian_investor_rules(client):
    bad_pan = investor_india_body()
    bad_pan["details"]["pan"] = "1234"
    response = client.post("/api/v1/profile", json=bad_pan)
    assert response.status_code == 422
    assert "details.pan" in response.text

    nri = investor_india_body()
    nri["details"]["investorType"] = "nri"
    response = client.post("/api/v1/profile", json=nri)
    assert response.status_code == 422
    assert "not an investor type" in response.text

    no_org = investor_india_body(organisationName=None)
    response = client.post("/api/v1/profile", json=no_org)
    assert response.status_code == 422
    assert "name of the company" in response.text

    backwards = investor_india_body()
    backwards["details"]["ticketMin"] = 5_000_000
    response = client.post("/api/v1/profile", json=backwards)
    assert response.status_code == 422

    unknown_state = investor_india_body()
    unknown_state["details"]["preferredStates"] = ["999"]
    response = client.post("/api/v1/profile", json=unknown_state)
    assert response.status_code == 422
    assert "Unknown state code" in response.text


def test_international_investor_profile(client):
    response = client.post("/api/v1/profile", json=investor_international_body())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["countryCode"] == "GB"
    assert body["email"] == "anil@example.com"
    assert body["phone"] == "+442079460958"
    assert body["stateCode"] is None
    assert body["kycMethods"] == ["passport"]


def test_international_investor_must_be_abroad_and_acknowledge_rules(client):
    response = client.post(
        "/api/v1/profile", json=investor_international_body(countryCode="IN")
    )
    assert response.status_code == 422
    assert "outside India" in response.text

    unacknowledged = investor_international_body()
    unacknowledged["details"]["complianceAcknowledged"] = False
    response = client.post("/api/v1/profile", json=unacknowledged)
    assert response.status_code == 422
    assert "foreign investment" in response.text

    response = client.post("/api/v1/profile", json=investor_international_body(email=None))
    assert response.status_code == 422


def test_national_partner_profile(client):
    response = client.post("/api/v1/profile", json=partner_national_body())
    assert response.status_code == 201, response.text
    details = response.json()["details"]
    assert details["gstin"] == "27ABCDE1234F1Z5"
    assert details["memberFarmers"] == 850


def test_partner_rules(client):
    importer = partner_national_body()
    importer["details"]["organisationType"] = "importer"
    response = client.post("/api/v1/profile", json=importer)
    assert response.status_code == 422
    assert "not an organisation type" in response.text

    response = client.post("/api/v1/profile", json=partner_national_body(organisationName=""))
    assert response.status_code == 422

    bad_gstin = partner_national_body()
    bad_gstin["details"]["gstin"] = "27ABC"
    response = client.post("/api/v1/profile", json=bad_gstin)
    assert response.status_code == 422

    nothing_offered = partner_national_body()
    nothing_offered["details"]["partnershipTypes"] = []
    response = client.post("/api/v1/profile", json=nothing_offered)
    assert response.status_code == 422


def test_international_partner_profile(client):
    response = client.post("/api/v1/profile", json=partner_international_body())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["details"]["certificationsRequired"] == ["globalgap"]
    assert body["countryCode"] == "NL"


def test_government_profile_needs_its_jurisdiction(client):
    response = client.post(
        "/api/v1/profile", json=government_body(subdistrictCode=None)
    )
    assert response.status_code == 422
    assert "block or tehsil" in response.text

    response = client.post("/api/v1/profile", json=government_body())
    assert response.status_code == 201, response.text
    assert response.json()["kycMethods"] == ["official"]


def test_state_level_officer_needs_only_a_state(client):
    body = government_body(districtCode=None, subdistrictCode=None)
    body["details"]["level"] = "state"
    response = client.post("/api/v1/profile", json=body)
    assert response.status_code == 201, response.text


def test_replace_profile(client):
    client.post("/api/v1/profile", json=farmer_body())
    response = client.put(
        "/api/v1/profile",
        json=farmer_body(displayName="Ramesh Kumar Yadav", about="Paddy and wheat."),
    )
    assert response.status_code == 200, response.text
    assert response.json()["displayName"] == "Ramesh Kumar Yadav"
    with session_scope() as session:
        farmer = session.get(Farmer, response.json()["farmerId"])
        assert farmer.name == "Ramesh Kumar Yadav"


def test_profile_cannot_change_segment(client):
    client.post("/api/v1/profile", json=farmer_body())
    response = client.put("/api/v1/profile", json=investor_india_body())
    assert response.status_code == 409


def test_replace_before_create_is_404(client):
    assert client.put("/api/v1/profile", json=farmer_body()).status_code == 404


def test_delete_profile_keeps_land(client, parcel_id):
    client.post("/api/v1/profile", json=farmer_body())
    assert client.delete("/api/v1/profile").status_code == 204
    assert client.get("/api/v1/profile").json() is None
    assert client.get(f"/api/v1/land-parcels/{parcel_id}").status_code == 200
