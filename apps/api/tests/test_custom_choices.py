"""Choices people type themselves: ``custom:<text>`` on the lists that take one."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import reference
from app.db import session_scope
from app.models import LandParcel
from app.services.i18n import Translator
from app.services.planning import land_profile

from .test_groups_data import group_body
from .test_marketplace import make_owner
from .test_profiles import farmer_body, investor_india_body, partner_national_body
from .test_sharing_equipment import machine

#: Lists people may add to, and lists they may not: units are converted,
#: countries and segments are complete, and the rest drive rules.
OPEN = {
    "certifications", "crops", "diary_activities", "dispute_reasons", "equipment_conditions",
    "equipment_types", "farmer_needs", "group_kinds", "insurance_types", "investment_modes",
    "investor_types", "irrigation_types", "loan_documents", "organisation_types", "ownership_types", "partner_roles",
    "partnership_types", "soil_types", "water_sources", "water_types",
}
FIXED = {
    "area_units", "countries", "depth_units", "government_levels", "insurance_schemes", "loan_purposes",
    "quantity_units", "rent_units", "risk_appetites", "user_segments",
}


def test_every_list_says_whether_it_takes_a_typed_choice():
    assert OPEN | FIXED == set(reference.REFERENCE_FILES)
    assert {key for key in reference.REFERENCE_FILES if reference.allows_custom(key)} == OPEN


@pytest.mark.parametrize("code", [
    "custom:Dragon fruit", "custom:ड्रैगन फ्रूट", "custom:A", "custom:" + "x" * reference.CUSTOM_MAX_LENGTH,
])
def test_a_well_formed_choice_is_taken_on_open_lists_only(code):
    assert reference.is_valid("crops", code)
    assert not reference.is_valid("area_units", code)
    assert not reference.is_valid("countries", code)


@pytest.mark.parametrize("code", [
    "custom:", "custom: padded", "custom:two  spaces", "custom:line\nbreak", "custom:<b>bold</b>",
    "custom:" + "x" * (reference.CUSTOM_MAX_LENGTH + 1), "Custom:Dragon fruit", "not_a_crop",
])
def test_a_malformed_choice_is_refused(code):
    assert not reference.is_valid("crops", code)


def test_a_typed_choice_reads_as_typed_in_every_language():
    code = "custom:Dragon fruit"
    assert reference.label_of("crops", code) == "Dragon fruit"
    assert reference.label_of("crops", code, "hi") == "Dragon fruit"
    assert reference.get_item("crops", code)["custom"] is True
    assert reference.get_item("area_units", "custom:Guntha") is None
    assert Translator("hi").reference("crops", code) == "Dragon fruit"
    assert Translator("ta").reference_list("crops", ["wheat", code]).endswith(", Dragon fruit")


# --------------------------------------------------------------------------- #
# A plot, its suggestions and its report
# --------------------------------------------------------------------------- #


def custom_plot(parcel_payload: dict) -> dict:
    return {
        **parcel_payload,
        "ownershipType": "custom:Temple trust land",
        "soilType": "custom:Kankar mixed",
        "waterSources": ["borewell", "custom:Village pond"],
        "waterType": "custom:Slightly hard",
        "irrigationType": "custom:Pitcher irrigation",
        "existingCrops": ["wheat", "custom:Dragon fruit"],
    }


def test_a_plot_keeps_what_was_typed(client, parcel_payload):
    created = client.post("/api/v1/land-parcels", json=custom_plot(parcel_payload))
    assert created.status_code == 201, created.text
    body = client.get(f"/api/v1/land-parcels/{created.json()['id']}").json()
    assert body["soilType"] == "custom:Kankar mixed"
    assert body["existingCrops"] == ["wheat", "custom:Dragon fruit"]
    assert body["waterSources"] == ["borewell", "custom:Village pond"]


def test_a_unit_cannot_be_typed(client, parcel_payload):
    refused = client.post("/api/v1/land-parcels", json={**parcel_payload, "areaUnit": "custom:Guntha"})
    assert refused.status_code == 422
    refused = client.post("/api/v1/land-parcels", json={**parcel_payload, "soilType": "custom:<script>"})
    assert refused.status_code == 422


def test_the_engine_treats_a_typed_choice_as_not_stated(client, parcel_payload):
    typed = client.post("/api/v1/land-parcels", json=custom_plot(parcel_payload)).json()["id"]
    unstated = client.post("/api/v1/land-parcels", json={
        **parcel_payload, "ownershipType": None, "soilType": None, "waterSources": ["borewell"],
        "waterType": None, "irrigationType": None, "existingCrops": ["wheat"],
    }).json()["id"]

    with session_scope() as session:
        land = land_profile(session.get(LandParcel, typed))
    assert land.soil_type is None and land.water_type is None and land.irrigation_type is None
    assert land.existing_crops == ("wheat",) and land.water_sources == ("borewell",)

    def scores(parcel_id: str) -> dict[str, int]:
        answer = client.get(f"/api/v1/land-parcels/{parcel_id}/opportunities", params={"lang": "en"})
        assert answer.status_code == 200, answer.text
        return {item["code"]: item["score"] for item in answer.json()["items"]}

    # Neither a reward nor a penalty: the same suggestions as saying nothing.
    assert scores(typed) == scores(unstated)


def test_a_report_prints_what_was_typed(client, parcel_payload):
    parcel_id = client.post("/api/v1/land-parcels", json=custom_plot(parcel_payload)).json()["id"]
    for language in ("en", "hi"):
        created = client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json={
            "opportunityCode": "guava_meadow", "language": language, "promoterName": "Ram Prasad Yadav",
        })
        assert created.status_code == 201, created.text


# --------------------------------------------------------------------------- #
# Everywhere else a list is offered
# --------------------------------------------------------------------------- #


def test_profiles_take_typed_types_sectors_and_needs(client):
    farmer = client.post("/api/v1/profile", json=farmer_body(
        details={"needs": ["loan", "custom:Cold room nearby"]},
    ))
    assert farmer.status_code == 201, farmer.text
    assert farmer.json()["details"]["needs"] == ["loan", "custom:Cold room nearby"]
    client.delete("/api/v1/profile")

    # A type of their own may be a person: no company name is insisted on.
    investor = investor_india_body(organisationName=None)
    investor["details"] = {**investor["details"], "investorType": "custom:Retired teacher",
                           "sectors": ["horticulture", "custom:Bamboo"],
                           "modes": ["revenue_share", "custom:Buy-back of produce"]}
    created = client.post("/api/v1/profile", json=investor)
    assert created.status_code == 201, created.text
    assert created.json()["details"]["sectors"] == ["horticulture", "custom:Bamboo"]
    client.delete("/api/v1/profile")

    partner = partner_national_body()
    partner["details"] = {**partner["details"], "organisationType": "custom:Women's collective",
                          "certificationsRequired": ["custom:Bird-friendly"]}
    assert client.post("/api/v1/profile", json=partner).status_code == 201
    client.delete("/api/v1/profile")

    # Fixed lists stay fixed.
    risky = investor_india_body()
    risky["details"] = {**risky["details"], "riskAppetite": "custom:Whatever"}
    assert client.post("/api/v1/profile", json=risky).status_code == 422


def test_machines_diaries_groups_and_insurance_take_typed_choices(client, parcel_id):
    make_owner(client, partner_national_body())
    listing = client.post("/api/v1/equipment", json=machine(
        equipmentType="custom:Mini dal mill", condition="custom:Rebuilt engine",
    ))
    assert listing.status_code == 201, listing.text
    assert listing.json()["equipmentType"] == "custom:Mini dal mill"
    assert client.post("/api/v1/equipment", json=machine(rentUnit="custom:Per trolley")).status_code == 422
    client.delete("/api/v1/profile")

    make_owner(client, farmer_body())
    diary = client.post(f"/api/v1/land-parcels/{parcel_id}/diary", json={
        "activity": "custom:Bird netting", "entryDate": (date.today() - timedelta(days=3)).isoformat(),
        "crop": "custom:Dragon fruit",
    })
    assert diary.status_code == 201, diary.text

    group = client.post("/api/v1/groups", json=group_body(kind="custom:Kisan club", crops=["custom:Dragon fruit"]))
    assert group.status_code == 201, group.text
    assert group.json()["crops"] == ["custom:Dragon fruit"]

    policy = client.post("/api/v1/insurance", json={
        "parcelId": parcel_id, "category": "custom:Pump set cover", "insurer": "Gramin Bima Samiti",
    })
    assert policy.status_code == 201, policy.text
