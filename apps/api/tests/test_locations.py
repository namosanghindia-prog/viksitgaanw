"""The cascading location selector must work offline and find messy names."""

from __future__ import annotations

from .conftest import NASHIK, PINDRA, RAMPUR_BUJURG, UP, VARANASI


def test_health_reports_loaded_dataset(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["database"]["lgdLoaded"] is True
    assert body["database"]["counts"]["villages"] == 72


def test_states_are_listed_alphabetically(client):
    states = client.get("/api/v1/locations/states").json()
    assert len(states) == 36
    assert [s["name"] for s in states] == sorted(s["name"] for s in states)


def test_state_carries_local_language_name(client):
    states = client.get("/api/v1/locations/states").json()
    up = next(s for s in states if s["code"] == UP)
    assert up["name"] == "Uttar Pradesh"
    assert up["nameLocal"] == "उत्तर प्रदेश"


def test_cascade_narrows_at_each_level(client):
    districts = client.get("/api/v1/locations/districts", params={"stateCode": UP}).json()
    assert {d["code"] for d in districts} == {VARANASI, "990902"}

    subdistricts = client.get(
        "/api/v1/locations/subdistricts", params={"districtCode": VARANASI}
    ).json()
    assert {s["name"] for s in subdistricts} == {"Pindra", "Rajatalab"}

    villages = client.get(
        "/api/v1/locations/villages", params={"subdistrictCode": PINDRA}
    ).json()
    assert len(villages) == 6
    assert "Rampur Bujurg" in {v["name"] for v in villages}


def test_districts_of_one_state_never_leak_into_another(client):
    up_districts = client.get("/api/v1/locations/districts", params={"stateCode": UP}).json()
    assert NASHIK not in {d["code"] for d in up_districts}


def test_village_search_matches_a_word_inside_the_name(client):
    """A farmer types the word they know, not the full official name."""
    results = client.get("/api/v1/locations/villages", params={"q": "bujurg"}).json()
    assert [v["code"] for v in results] == [RAMPUR_BUJURG]


def test_village_search_ignores_case_and_punctuation(client):
    results = client.get(
        "/api/v1/locations/villages", params={"q": "  PIMPALGAON,  baswant "}
    ).json()
    assert [v["name"] for v in results] == ["Pimpalgaon Baswant"]


def test_village_search_can_be_scoped_to_a_state(client):
    everywhere = client.get("/api/v1/locations/villages", params={"q": "ho"}).json()
    in_up = client.get(
        "/api/v1/locations/villages", params={"q": "ho", "stateCode": UP}
    ).json()
    assert len(in_up) < len(everywhere)
    assert all(v["code"].startswith("9909") for v in in_up)


def test_unbounded_village_listing_is_rejected(client):
    """~660k rows once the real dump is loaded; refuse rather than crawl."""
    assert client.get("/api/v1/locations/villages").status_code == 422


def test_resolve_expands_a_village_into_the_full_chain(client):
    path = client.get(
        "/api/v1/locations/resolve", params={"villageCode": RAMPUR_BUJURG}
    ).json()
    assert path["state"]["name"] == "Uttar Pradesh"
    assert path["district"]["name"] == "Varanasi"
    assert path["subdistrict"]["name"] == "Pindra"
    assert path["village"]["name"] == "Rampur Bujurg"


def test_resolve_from_a_district_leaves_deeper_levels_empty(client):
    path = client.get("/api/v1/locations/resolve", params={"districtCode": VARANASI}).json()
    assert path["state"]["code"] == UP
    assert path["district"]["code"] == VARANASI
    assert path["subdistrict"] is None
    assert path["village"] is None


def test_resolve_rejects_an_unknown_code(client):
    response = client.get("/api/v1/locations/resolve", params={"villageCode": "404404404"})
    assert response.status_code == 404
