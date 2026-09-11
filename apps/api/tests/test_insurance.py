"""Insurance: required cover per project, and policies on plots and profiles."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, InsurancePolicy

from .test_marketplace import insert_interest, insert_profile, insert_request, request_body
from .test_profiles import farmer_body, investor_india_body, partner_international_body

NEXT_YEAR = (date.today() + timedelta(days=365)).isoformat()
LAST_YEAR = (date.today() - timedelta(days=30)).isoformat()


def livestock_policy(**overrides) -> dict:
    body = {
        "category": "livestock",
        "status": "insured",
        "scheme": "nlm_livestock",
        "insurer": "National Insurance Co.",
        "policyNumber": "NLM-2026-778812",
        "sumInsured": 300000,
        "premium": 4200,
        "validUntil": NEXT_YEAR,
        "covered": "5 cows, ear tags 1101-1105",
    }
    body.update(overrides)
    return body


@pytest.fixture()
def farmer(client) -> dict:
    response = client.post("/api/v1/profile", json=farmer_body())
    assert response.status_code == 201, response.text
    return response.json()


def dairy_request(parcel_id: str, insurance: list[dict]) -> dict:
    return request_body(
        parcel_id,
        opportunityCode="dairy_crossbred",
        title="Five-cow dairy",
        insurance=insurance,
    )


# --------------------------------------------------------------------------- #
# Requirements
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("code", "required", "recommended"),
    [
        ("dairy_crossbred", ["livestock"], []),
        ("polyhouse_vegetables", ["structure"], ["crop"]),
        ("modular_cold_room", ["property"], ["machinery"]),
        ("pomegranate_orchard", [], ["crop"]),
        ("drone_spraying_service", ["machinery"], []),
        ("vermicompost_unit", [], ["property"]),
    ],
)
def test_requirements_follow_the_option(client, code, required, recommended):
    body = client.get("/api/v1/insurance/requirements", params={"opportunityCode": code}).json()
    assert body["required"] == required
    assert body["recommended"] == recommended


def test_an_option_rule_explains_itself(client):
    body = client.get(
        "/api/v1/insurance/requirements", params={"opportunityCode": "drone_spraying_service"}
    ).json()
    assert "drone" in body["reason"]["en"]
    assert body["reason"]["hi"]


def test_a_plot_with_no_option_is_advised_crop_cover(client):
    body = client.get("/api/v1/insurance/requirements").json()
    assert body["required"] == [] and body["recommended"] == ["crop"]


def test_every_rule_names_real_categories_and_options():
    """A typo in insurance-rules.json would silently drop a requirement."""
    from app import knowledge, reference

    rules = knowledge.load_insurance_rules()
    categories = reference.valid_codes("insurance_types")
    blocks = [rules["default"], *rules["byKind"].values(), *rules["byOpportunity"].values()]
    for block in blocks:
        assert set(block["required"]) <= categories
        assert set(block["recommended"]) <= categories
    assert set(rules["byKind"]) <= set(knowledge.kind_index())
    for code in rules["byOpportunity"]:
        assert knowledge.get_opportunity(code) is not None, code


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


def test_required_cover_must_be_given(client, farmer, parcel_id):
    response = client.post("/api/v1/investment-requests", json=dairy_request(parcel_id, []))
    assert response.status_code == 422
    assert "Animals, birds, fish and bees is required" in response.json()["detail"]


def test_a_promise_to_insure_is_accepted_and_shown(client, farmer, parcel_id):
    response = client.post(
        "/api/v1/investment-requests",
        json=dairy_request(parcel_id, [{"category": "livestock", "status": "planned"}]),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["insuranceRequired"] == ["livestock"]
    assert body["fullyInsured"] is False
    [policy] = body["insurance"]
    assert policy["status"] == "planned" and policy["isCurrent"] is False


def test_a_current_policy_makes_the_project_fully_insured(client, farmer, parcel_id):
    response = client.post(
        "/api/v1/investment-requests", json=dairy_request(parcel_id, [livestock_policy()])
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["fullyInsured"] is True
    # The farmer sees their own policy in full.
    assert body["insurance"][0]["policyNumber"] == "NLM-2026-778812"
    assert body["insurance"][0]["premium"] == 4200

    with session_scope() as session:
        events = session.scalars(select(AppEvent.event_type)).all()
    assert "insurance_policy.added" in events


def test_an_expired_policy_does_not_count(client, farmer, parcel_id):
    response = client.post(
        "/api/v1/investment-requests",
        json=dairy_request(parcel_id, [livestock_policy(validUntil=LAST_YEAR)]),
    )
    assert response.status_code == 422
    assert "expired" in response.json()["detail"]


def test_personal_cover_is_not_project_cover(client, farmer, parcel_id):
    response = client.post(
        "/api/v1/investment-requests",
        json=dairy_request(
            parcel_id,
            [
                {"category": "livestock", "status": "planned"},
                {"category": "life", "scheme": "pmjjby", "status": "insured"},
            ],
        ),
    )
    assert response.status_code == 422


def test_turning_a_promise_into_a_policy(client, farmer, parcel_id):
    body = client.post(
        "/api/v1/investment-requests",
        json=dairy_request(parcel_id, [{"category": "livestock", "status": "planned"}]),
    ).json()
    policy_id = body["insurance"][0]["id"]

    response = client.put(f"/api/v1/insurance/{policy_id}", json=livestock_policy())
    assert response.status_code == 200, response.text
    assert response.json()["isCurrent"] is True

    mine = client.get("/api/v1/investment-requests/mine").json()[0]
    assert mine["fullyInsured"] is True

    response = client.put(
        f"/api/v1/insurance/{policy_id}",
        json=livestock_policy(category="machinery", scheme="private"),
    )
    assert response.status_code == 409


def test_required_cover_cannot_be_deleted_while_open(client, farmer, parcel_id):
    body = client.post(
        "/api/v1/investment-requests", json=dairy_request(parcel_id, [livestock_policy()])
    ).json()
    policy_id = body["insurance"][0]["id"]

    assert client.delete(f"/api/v1/insurance/{policy_id}").status_code == 409
    client.patch(f"/api/v1/investment-requests/{body['id']}", json={"status": "closed"})
    assert client.delete(f"/api/v1/insurance/{policy_id}").status_code == 204


def test_recommended_cover_can_be_added_later(client, farmer, parcel_id):
    request_id = client.post(
        "/api/v1/investment-requests", json=request_body(parcel_id)
    ).json()["id"]
    response = client.post(
        "/api/v1/insurance",
        json={
            "requestId": request_id,
            "category": "crop",
            "scheme": "rwbcis",
            "insurer": "AIC of India",
            "season": "annual",
            "seasonYear": 2026,
            "sumInsured": 120000,
        },
    )
    assert response.status_code == 201, response.text
    mine = client.get("/api/v1/investment-requests/mine").json()[0]
    assert [policy["category"] for policy in mine["insurance"]] == ["crop"]


def test_investors_see_masked_cover_until_accepted(client):
    client.post("/api/v1/profile", json=investor_india_body())
    investor_id = client.get("/api/v1/profile").json()["id"]
    request_id = insert_request(insert_profile("farmer"), opportunity_code="dairy_crossbred", opportunity_kind="livestock")
    with session_scope() as session:
        session.add(
            InsurancePolicy(
                request_id=request_id,
                category="livestock",
                status="insured",
                scheme="nlm_livestock",
                insurer="National Insurance Co.",
                policy_number="NLM-2026-778812",
                premium=4200,
                sum_insured=300000,
                notes="private",
                origin="synced",
            )
        )

    row = client.get(f"/api/v1/investment-requests/{request_id}").json()
    [policy] = row["insurance"]
    assert policy["policyNumber"] == "••••8812"
    assert policy["premium"] is None and policy["notes"] is None
    assert policy["sumInsured"] == 300000 and policy["insurer"] == "National Insurance Co."
    assert row["fullyInsured"] is True

    insert_interest(request_id, investor_id, status="accepted")
    row = client.get(f"/api/v1/investment-requests/{request_id}").json()
    assert row["insurance"][0]["policyNumber"] == "NLM-2026-778812"


# --------------------------------------------------------------------------- #
# Plots and profiles
# --------------------------------------------------------------------------- #


def test_crop_cover_on_a_plot(client, farmer, parcel_id):
    response = client.post(
        "/api/v1/insurance",
        json={
            "parcelId": parcel_id,
            "category": "crop",
            "scheme": "pmfby",
            "insurer": "Agriculture Insurance Company of India",
            "policyNumber": "PMFBY-UP-26-K-0001",
            "season": "kharif",
            "seasonYear": 2026,
            "sumInsured": 80000,
            "premium": 1600,
            "covered": "Paddy, 1.2 ha",
        },
    )
    assert response.status_code == 201, response.text
    listed = client.get("/api/v1/insurance", params={"parcelId": parcel_id}).json()
    assert [(p["category"], p["season"]) for p in listed] == [("crop", "kharif")]


def test_a_plot_does_not_take_life_cover_or_promises(client, farmer, parcel_id):
    life = {"parcelId": parcel_id, "category": "life", "scheme": "pmjjby"}
    assert client.post("/api/v1/insurance", json=life).status_code == 422

    promise = {"parcelId": parcel_id, "category": "crop", "status": "planned"}
    response = client.post("/api/v1/insurance", json=promise)
    assert response.status_code == 422
    assert "promise" in response.json()["detail"]


def test_a_policy_needs_a_scheme_or_an_insurer(client, farmer, parcel_id):
    response = client.post("/api/v1/insurance", json={"parcelId": parcel_id, "category": "crop"})
    assert response.status_code == 422


def test_scheme_must_fit_the_category(client, farmer):
    response = client.post(
        "/api/v1/insurance", json={"onProfile": True, "category": "accident", "scheme": "pmfby"}
    )
    assert response.status_code == 422
    assert "does not cover" in response.text


def test_farmer_personal_cover(client, farmer):
    for body in (
        {"category": "accident", "scheme": "pmsby", "sumInsured": 200000, "premium": 20},
        {"category": "life", "scheme": "pmjjby", "sumInsured": 200000, "premium": 436},
        {"category": "health", "scheme": "pmjay", "sumInsured": 500000},
    ):
        response = client.post("/api/v1/insurance", json={"onProfile": True, **body})
        assert response.status_code == 201, response.text
    listed = client.get("/api/v1/insurance").json()
    assert sorted(p["category"] for p in listed) == ["accident", "health", "life"]

    cargo = {"onProfile": True, "category": "cargo", "insurer": "Any"}
    assert client.post("/api/v1/insurance", json=cargo).status_code == 422


def test_partner_trade_cover_in_foreign_currency(client):
    client.post("/api/v1/profile", json=partner_international_body())
    response = client.post(
        "/api/v1/insurance",
        json={
            "onProfile": True,
            "category": "cargo",
            "insurer": "Rotterdam Marine Underwriters",
            "sumInsured": 250000,
            "currency": "eur",
            "validUntil": NEXT_YEAR,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["currency"] == "EUR"


def test_investors_do_not_record_insurance(client):
    client.post("/api/v1/profile", json=investor_india_body())
    response = client.post(
        "/api/v1/insurance", json={"onProfile": True, "category": "life", "scheme": "pmjjby"}
    )
    assert response.status_code == 403


def test_one_target_only(client, farmer, parcel_id):
    response = client.post(
        "/api/v1/insurance",
        json={"parcelId": parcel_id, "onProfile": True, "category": "crop", "insurer": "X"},
    )
    assert response.status_code == 422
