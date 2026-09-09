"""Water quality and depth to water.

Salinity rules crops in and out, and depth drives the cost of lifting water, so
both feed the suggestion engine and the project report. Neither is compulsory:
plenty of farmers will not know the depth of their borewell.
"""

from __future__ import annotations

import pytest

from app.services.depth import METRES_PER_FOOT, UnknownDepthUnitError, to_metres


def test_depth_is_stored_as_entered_and_normalised(client, parcel_payload):
    """Farmers say feet; the report needs metres. Keep both."""
    parcel_payload["waterType"] = "salty"
    parcel_payload["waterDepthValue"] = 120
    parcel_payload["waterDepthUnit"] = "foot"

    body = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    assert body["waterType"] == "salty"
    assert body["waterDepthValue"] == 120
    assert body["waterDepthUnit"] == "foot"
    assert body["waterDepthMetres"] == pytest.approx(36.576)


@pytest.mark.parametrize(
    ("value", "unit", "expected_metres"),
    [
        (1, "foot", METRES_PER_FOOT),
        (100, "foot", 30.48),
        (1, "metre", 1.0),
        (40, "metre", 40.0),
    ],
)
def test_depth_unit_conversions(value, unit, expected_metres):
    assert to_metres(value, unit) == pytest.approx(expected_metres, rel=1e-9)


def test_unknown_depth_unit_raises_rather_than_guessing():
    with pytest.raises(UnknownDepthUnitError):
        to_metres(10, "furlong")


@pytest.mark.parametrize("water_type", ["sweet", "salty", "other", "unknown"])
def test_every_water_type_is_accepted(client, parcel_payload, water_type):
    parcel_payload["waterType"] = water_type
    response = client.post("/api/v1/land-parcels", json=parcel_payload)
    assert response.status_code == 201
    assert response.json()["waterType"] == water_type


def test_water_type_outside_the_reference_list_is_refused(client, parcel_payload):
    parcel_payload["waterType"] = "fizzy"
    assert client.post("/api/v1/land-parcels", json=parcel_payload).status_code == 422


def test_depth_unit_outside_the_reference_list_is_refused(client, parcel_payload):
    parcel_payload["waterDepthValue"] = 30
    parcel_payload["waterDepthUnit"] = "furlong"
    assert client.post("/api/v1/land-parcels", json=parcel_payload).status_code == 422


def test_a_depth_without_a_unit_is_refused(client, parcel_payload):
    """40 feet and 40 metres are very different wells; a bare number is not
    something to guess at."""
    parcel_payload["waterDepthValue"] = 40
    response = client.post("/api/v1/land-parcels", json=parcel_payload)
    assert response.status_code == 422
    assert "unit" in str(response.json()["detail"]).lower()


@pytest.mark.parametrize("depth", [0, -5])
def test_non_positive_depth_is_refused(client, parcel_payload, depth):
    parcel_payload["waterDepthValue"] = depth
    parcel_payload["waterDepthUnit"] = "foot"
    assert client.post("/api/v1/land-parcels", json=parcel_payload).status_code == 422


def test_both_water_fields_are_optional(client, parcel_payload):
    """Most farmers will not know their water table depth."""
    parcel_payload.pop("waterType", None)
    parcel_payload.pop("waterDepthValue", None)
    body = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    assert body["waterType"] is None
    assert body["waterDepthValue"] is None
    assert body["waterDepthMetres"] is None


def test_water_type_is_independent_of_water_sources(client, parcel_payload):
    """A borewell can be sweet or salty; the two fields answer different
    questions and must not be conflated."""
    parcel_payload["waterSources"] = ["borewell"]
    parcel_payload["waterType"] = "salty"
    body = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    assert body["waterSources"] == ["borewell"]
    assert body["waterType"] == "salty"


def test_patch_recomputes_the_normalised_depth(client, parcel_payload):
    parcel_payload["waterDepthValue"] = 100
    parcel_payload["waterDepthUnit"] = "foot"
    parcel = client.post("/api/v1/land-parcels", json=parcel_payload).json()
    assert parcel["waterDepthMetres"] == pytest.approx(30.48)

    updated = client.patch(
        f"/api/v1/land-parcels/{parcel['id']}",
        json={"waterDepthValue": 40, "waterDepthUnit": "metre"},
    ).json()
    assert updated["waterDepthMetres"] == pytest.approx(40.0)
    # Unrelated fields survive the patch.
    assert updated["waterSources"] == parcel["waterSources"]


def test_patch_can_change_only_the_unit(client, parcel_payload):
    parcel_payload["waterDepthValue"] = 30
    parcel_payload["waterDepthUnit"] = "foot"
    parcel = client.post("/api/v1/land-parcels", json=parcel_payload).json()

    updated = client.patch(
        f"/api/v1/land-parcels/{parcel['id']}", json={"waterDepthUnit": "metre"}
    ).json()
    assert updated["waterDepthValue"] == 30
    assert updated["waterDepthMetres"] == pytest.approx(30.0)
