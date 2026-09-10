"""Finding the device, and matching a coordinate back onto the LGD.

The bug these cover is specific: `navigator.geolocation` cannot work inside the
Electron desktop shell, because Chromium resolves position through a Google
service the build has no key for. Every provider here is therefore expected to
fail sometimes, and the contract is that the chain still produces an answer and
says honestly where that answer came from.

Nothing in this file is allowed to touch the network. The two providers that
would are patched out, because a test suite that fails on a train is worse than
no test.
"""

from __future__ import annotations

import pytest

from app.services import geolocation
from app.services.place_matching import match_place


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Nothing here reaches the internet."""
    monkeypatch.setattr(geolocation, "network_fix", lambda: None)
    monkeypatch.setattr(geolocation, "reverse_online", lambda *_args, **_kwargs: None)


# --------------------------------------------------------------------------- #
# The offline last resort
# --------------------------------------------------------------------------- #


def test_state_centroid_answers_for_every_state():
    """The fallback is only a fallback if it covers the whole country."""
    states = geolocation._centroids()["states"]
    assert len(states) >= 36
    for code in states:
        fix = geolocation.state_centroid(code)
        assert fix is not None
        assert 6.0 <= fix.latitude <= 37.5
        assert 68.0 <= fix.longitude <= 97.5


def test_a_centroid_is_reported_as_the_coarse_thing_it_is():
    fix = geolocation.state_centroid("9")
    assert fix is not None
    assert fix.source == "admin_centroid"
    # Well over a hundred kilometres, so the UI cannot present it as a plot pin.
    assert fix.accuracy_metres and fix.accuracy_metres > 100_000


def test_unknown_state_has_no_centroid():
    assert geolocation.state_centroid("999") is None
    assert geolocation.state_centroid(None) is None


@pytest.mark.parametrize(
    ("latitude", "longitude", "expected"),
    [
        (25.32, 82.97, "9"),  # Varanasi
        (18.52, 73.85, "27"),  # Pune
        (12.97, 77.59, "29"),  # Bengaluru
        (26.91, 75.79, "8"),  # Jaipur
        (22.57, 88.36, "19"),  # Kolkata
        (9.93, 76.27, "32"),  # Kochi
    ],
)
def test_a_point_resolves_to_the_right_state_offline(latitude, longitude, expected):
    guess = geolocation.state_for_point(latitude, longitude)
    assert guess is not None
    assert guess[0] == expected


def test_a_point_far_out_to_sea_resolves_to_nothing():
    assert geolocation.state_for_point(0.0, 60.0) is None


# --------------------------------------------------------------------------- #
# The chain
# --------------------------------------------------------------------------- #


def test_the_chain_prefers_the_operating_system(monkeypatch):
    monkeypatch.setattr(
        geolocation,
        "os_fix",
        lambda: geolocation.Fix(25.3, 82.9, 40.0, "os_location", None, None),
    )
    fix = geolocation.locate(state_code="9")
    assert fix.source == "os_location"


def test_the_chain_falls_through_to_the_chosen_state(monkeypatch):
    """A laptop with no GPS and no internet still gets a usable map centre."""
    monkeypatch.setattr(geolocation, "os_fix", lambda: None)
    fix = geolocation.locate(state_code="9", allow_network=False)
    assert fix.source == "admin_centroid"
    assert fix.label == "Uttar Pradesh"


def test_the_chain_gives_up_honestly_when_nothing_is_known(monkeypatch):
    monkeypatch.setattr(geolocation, "os_fix", lambda: None)
    with pytest.raises(geolocation.GeolocationUnavailable):
        geolocation.locate(state_code=None, allow_network=False)


def test_network_is_skipped_when_the_caller_forbids_it(monkeypatch):
    called = []
    monkeypatch.setattr(geolocation, "os_fix", lambda: None)
    monkeypatch.setattr(
        geolocation, "network_fix", lambda: called.append(True) or None
    )
    geolocation.locate(state_code="9", allow_network=False)
    assert not called


# --------------------------------------------------------------------------- #
# The endpoint
# --------------------------------------------------------------------------- #


def test_locate_endpoint_returns_a_fix_and_says_what_it_tried(client, monkeypatch):
    monkeypatch.setattr(geolocation, "os_fix", lambda: None)
    response = client.get(
        "/api/v1/geo/locate", params={"stateCode": "9", "allowNetwork": "false"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["fix"]["source"] == "admin_centroid"
    assert "os_location" in body["tried"]


def test_locate_endpoint_reports_when_it_cannot_help(client, monkeypatch):
    monkeypatch.setattr(geolocation, "os_fix", lambda: None)
    response = client.get("/api/v1/geo/locate", params={"allowNetwork": "false"})
    assert response.status_code == 404
    assert "state" in response.json()["detail"].lower()


def test_no_place_is_suggested_for_a_state_centroid(client, monkeypatch):
    """A guess at the middle of a state says nothing about which district."""
    monkeypatch.setattr(geolocation, "os_fix", lambda: None)
    body = client.get(
        "/api/v1/geo/locate", params={"stateCode": "9", "allowNetwork": "false"}
    ).json()
    assert body["place"] is None


# --------------------------------------------------------------------------- #
# Matching names onto the LGD
# --------------------------------------------------------------------------- #


def test_exact_names_match(db_session):
    match = match_place(db_session, state="Uttar Pradesh", district="Varanasi")
    assert match.state_code == "9"
    assert match.district_name == "Varanasi"
    assert match.confidence == "high"


def test_case_and_punctuation_do_not_matter(db_session):
    match = match_place(db_session, state="uttar  pradesh", district="VARANASI")
    assert match.state_code == "9"
    assert match.district_code is not None


def test_a_name_from_nowhere_matches_nothing(db_session):
    match = match_place(db_session, state="Atlantis", district="Nowhere")
    assert match.is_empty


def test_a_bounding_box_hint_is_marked_low_confidence(db_session):
    """A guess from a rectangle is not evidence, and must not look like it."""
    match = match_place(db_session, state=None, state_code_hint="9")
    assert match.state_code == "9"
    assert match.district_code is None
    assert match.confidence == "low"


def test_reverse_endpoint_declines_a_point_it_cannot_place(client):
    response = client.get("/api/v1/geo/reverse", params={"lat": 0, "lon": 60})
    assert response.status_code == 404


def test_a_point_in_a_corner_of_two_states_is_not_claimed_confidently():
    """Chennai sits inside both the Tamil Nadu and Andhra Pradesh boxes.

    A rectangle test cannot separate them, so the answer must arrive marked as
    a guess rather than as a fact. The online reverse geocoder gets this right;
    the offline path is only allowed to be honest about not knowing.
    """
    guess = geolocation.state_for_point(13.08, 80.27)
    assert guess is not None
    assert guess[2] == "low"


def test_multi_enclave_union_territories_do_not_swallow_their_neighbours():
    """Puducherry's pieces span from the Kerala coast to the Andhra coast.

    One box round all of them would put Kochi and Coimbatore in Puducherry, so
    each is boxed round its main enclave only.
    """
    assert geolocation.state_for_point(9.93, 76.27)[0] == "32"  # Kochi, Kerala
    assert geolocation.state_for_point(11.02, 76.96)[0] == "33"  # Coimbatore, TN
