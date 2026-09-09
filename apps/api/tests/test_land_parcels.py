"""Land intake: what gets stored, what gets refused, and what gets logged."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, LandParcel, SyncQueueEntry
from app.services.area import to_hectares

from .conftest import NASHIK, PINDRA, RAMPUR_BUJURG, UP, VARANASI


def test_create_returns_the_resolved_location(client, parcel_payload):
    response = client.post("/api/v1/land-parcels", json=parcel_payload)
    assert response.status_code == 201
    body = response.json()
    assert body["location"]["village"]["name"] == "Rampur Bujurg"
    assert body["location"]["state"]["name"] == "Uttar Pradesh"
    assert body["syncState"] == "local_only"


def test_area_is_stored_as_entered_and_normalised(client, parcel_payload):
    """The farmer said 2.5 bigha; the bank needs hectares. Keep both."""
    body = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    assert body["areaValue"] == 2.5
    assert body["areaUnit"] == "bigha"
    # 1 pucca bigha = 5/8 acre, so 2.5 bigha = 1.5625 acre.
    assert body["areaAcres"] == pytest.approx(1.5625)
    assert body["areaHectares"] == pytest.approx(0.63232132, rel=1e-6)


@pytest.mark.parametrize(
    ("unit", "value", "expected_hectares"),
    [
        ("hectare", 1, 1.0),
        ("acre", 1, 0.40468564224),
        ("guntha", 40, 0.40468564224),  # 40 guntha = 1 acre
        ("cent", 100, 0.40468564224),  # 100 cent = 1 acre
        ("kanal", 8, 0.40468564224),  # 8 kanal = 1 acre
        ("marla", 160, 0.40468564224),  # 160 marla = 1 acre
        ("square_metre", 10000, 1.0),
    ],
)
def test_area_unit_conversions(unit, value, expected_hectares):
    assert to_hectares(value, unit) == pytest.approx(expected_hectares, rel=1e-9)


def test_duplicate_water_sources_are_collapsed(client, parcel_payload):
    parcel_payload["waterSources"] = ["borewell", "canal", "borewell"]
    body = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    assert body["waterSources"] == ["borewell", "canal"]


def test_village_without_its_subdistrict_is_refused(client, parcel_payload):
    parcel_payload["subdistrictCode"] = None
    response = client.post("/api/v1/land-parcels", json=parcel_payload)
    assert response.status_code == 422
    assert "sub-district" in response.json()["detail"].lower()


def test_district_from_the_wrong_state_is_refused(client, parcel_payload):
    """A mismatched chain would print an unverifiable address on a report."""
    parcel_payload["districtCode"] = NASHIK
    response = client.post("/api/v1/land-parcels", json=parcel_payload)
    assert response.status_code == 422
    assert "does not belong to state" in response.json()["detail"]


def test_village_from_the_wrong_subdistrict_is_refused(client, parcel_payload):
    parcel_payload["villageCode"] = "9909010201"  # Rajatalab village, Pindra claimed
    response = client.post("/api/v1/land-parcels", json=parcel_payload)
    assert response.status_code == 422
    assert "does not belong to sub-district" in response.json()["detail"]


def test_unknown_codes_are_refused(client, parcel_payload):
    parcel_payload["districtCode"] = "999999"
    assert client.post("/api/v1/land-parcels", json=parcel_payload).status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("areaUnit", "football_fields"),
        ("soilType", "chocolate"),
        ("irrigationType", "telepathy"),
        ("ownershipType", "vibes"),
        ("existingCrops", ["dragonfruit"]),
        ("waterSources", ["moonbeams"]),
    ],
)
def test_values_outside_the_shared_reference_lists_are_refused(
    client, parcel_payload, field, value
):
    parcel_payload[field] = value
    assert client.post("/api/v1/land-parcels", json=parcel_payload).status_code == 422


@pytest.mark.parametrize("area", [0, -1])
def test_non_positive_area_is_refused(client, parcel_payload, area):
    parcel_payload["areaValue"] = area
    assert client.post("/api/v1/land-parcels", json=parcel_payload).status_code == 422


def test_a_district_only_parcel_is_allowed(client, parcel_payload):
    """LGD coverage is genuinely patchy; district is the minimum we insist on."""
    parcel_payload["subdistrictCode"] = None
    parcel_payload["villageCode"] = None
    response = client.post("/api/v1/land-parcels", json=parcel_payload)
    assert response.status_code == 201
    body = response.json()
    assert body["location"]["district"]["name"] == "Varanasi"
    assert body["location"]["village"] is None


def test_patch_recomputes_the_normalised_area(client, parcel_payload):
    parcel = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    updated = client.patch(
        f"/api/v1/land-parcels/{parcel['id']}", json={"areaValue": 1, "areaUnit": "acre"}
    ).json()
    assert updated["areaHectares"] == pytest.approx(0.40468564224)
    assert updated["areaAcres"] == pytest.approx(1.0)


def test_patch_only_touches_the_fields_sent(client, parcel_payload):
    parcel = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    updated = client.patch(
        f"/api/v1/land-parcels/{parcel['id']}", json={"label": "Renamed plot"}
    ).json()
    assert updated["label"] == "Renamed plot"
    assert updated["soilType"] == parcel["soilType"]
    assert updated["existingCrops"] == parcel["existingCrops"]


def test_delete_removes_the_parcel(client, parcel_payload):
    parcel = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    assert client.delete(f"/api/v1/land-parcels/{parcel['id']}").status_code == 204
    assert client.get(f"/api/v1/land-parcels/{parcel['id']}").status_code == 404


def test_missing_parcel_is_a_404(client):
    assert client.get("/api/v1/land-parcels/does-not-exist").status_code == 404


# --------------------------------------------------------------------------- #
# Offline-first plumbing
# --------------------------------------------------------------------------- #


def test_writes_are_queued_for_a_later_sync(client, parcel_payload):
    """Nothing waits on the network, but nothing is lost either."""
    parcel = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    with session_scope() as session:
        entries = session.scalars(select(SyncQueueEntry)).all()
    assert [(e.entity_type, e.entity_id, e.operation, e.status) for e in entries] == [
        ("land_parcel", parcel["id"], "create", "pending")
    ]


def test_a_delete_is_queued_before_the_row_disappears(client, parcel_payload):
    parcel = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    client.delete(f"/api/v1/land-parcels/{parcel['id']}")
    with session_scope() as session:
        operations = [
            entry.operation
            for entry in session.scalars(
                select(SyncQueueEntry).where(SyncQueueEntry.entity_id == parcel["id"])
            )
        ]
        assert session.get(LandParcel, parcel["id"]) is None
    assert operations == ["create", "delete"]


def test_lifecycle_events_are_logged(client, parcel_payload):
    """These counts are the billing input; they have to be right from day one."""
    parcel = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    client.patch(f"/api/v1/land-parcels/{parcel['id']}", json={"label": "New name"})
    client.delete(f"/api/v1/land-parcels/{parcel['id']}")

    with session_scope() as session:
        events = session.scalars(select(AppEvent).order_by(AppEvent.id)).all()
        types = [event.event_type for event in events]

    assert types == [
        "farmer.created",
        "land_parcel.created",
        "land_parcel.updated",
        "land_parcel.deleted",
    ]


def test_parcels_share_the_devices_default_farmer(client, parcel_payload):
    first = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    second = client.post(
        "/api/v1/land-parcels", json={**parcel_payload, "label": "Second plot"}
    ).json()
    assert first["farmerId"] == second["farmerId"]
    assert len(client.get("/api/v1/land-parcels").json()) == 2
