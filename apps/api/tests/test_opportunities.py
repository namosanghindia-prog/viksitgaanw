"""The suggestion engine.

These tests are written around what a farmer would notice, not around internal
mechanics: that salty water rules out a salt-sensitive crop, that a business
which needs no land is still offered to someone with a tenth of an acre, and
that the app never claims an orchard has paid for itself before it has fruited.
"""

from __future__ import annotations

import pytest

from app import knowledge
from app.services.opportunities import (
    RECOMMENDED_AT,
    LandProfile,
    assess,
    compute_economics,
    compute_sizing,
    rank,
    revenue_factor,
)


def _opportunity(code: str) -> dict:
    item = knowledge.get_opportunity(code)
    assert item is not None, f"{code} is missing from the knowledge base"
    return item


# --------------------------------------------------------------------------- #
# Blockers: things the land simply cannot support
# --------------------------------------------------------------------------- #


def test_salty_water_blocks_a_salt_sensitive_crop(land_profile, labels):
    """Banana on brackish water is not a caution, it is a no."""
    result = assess(
        _opportunity("banana_tissue_culture"),
        land_profile(water_type="salty"),
        labels=labels,
    )
    assert result.verdict == "unsuitable"
    assert any(signal.key == "fit.salinityRisk" for signal in result.blockers)


def test_salt_tolerant_crop_survives_the_same_water(land_profile, labels):
    result = assess(
        _opportunity("lemongrass_oil"),
        land_profile(water_type="salty", soil_type="saline_alkaline", state_code="9"),
        labels=labels,
    )
    assert result.verdict != "unsuitable"
    assert any(signal.key == "fit.salinityTolerant" for signal in result.reasons)


def test_land_below_the_minimum_is_blocked_with_both_numbers(land_profile, labels):
    result = assess(
        _opportunity("mango_orchard_hd"), land_profile(area_hectares=0.05), labels=labels
    )
    assert result.verdict == "unsuitable"
    blocker = next(s for s in result.blockers if s.key == "fit.areaTooSmall")
    # The farmer is told the threshold and their own size, not just "too small".
    assert blocker.variables["min"] and blocker.variables["area"]


def test_irrigated_crop_is_blocked_on_a_rainfed_plot(land_profile, labels):
    result = assess(
        _opportunity("banana_tissue_culture"),
        land_profile(irrigation_type="rainfed", water_sources=("rainfed",)),
        labels=labels,
    )
    assert result.verdict == "unsuitable"
    assert any(signal.key == "fit.irrigationMissing" for signal in result.blockers)


def test_a_named_water_source_counts_as_irrigation_without_a_method(land_profile, labels):
    """Farmers often name the source and skip the method. That is still irrigated."""
    profile = land_profile(irrigation_type=None, water_sources=("canal",))
    assert profile.is_irrigated
    result = assess(_opportunity("banana_tissue_culture"), profile, labels=labels)
    assert result.verdict != "unsuitable"


def test_a_crop_that_climbs_needs_something_to_climb(land_profile, labels):
    blocked = assess(
        _opportunity("black_pepper_intercrop"),
        land_profile(state_code="32", soil_type="laterite", existing_crops=()),
        labels=labels,
    )
    assert blocked.verdict == "unsuitable"

    allowed = assess(
        _opportunity("black_pepper_intercrop"),
        land_profile(state_code="32", soil_type="laterite", existing_crops=("coconut",)),
        labels=labels,
    )
    assert allowed.verdict != "unsuitable"


def test_soil_the_crop_will_not_grow_in_is_a_blocker(land_profile, labels):
    result = assess(
        _opportunity("cumin_arid"),
        land_profile(state_code="8", soil_type="clayey"),
        labels=labels,
    )
    assert result.verdict == "unsuitable"


# --------------------------------------------------------------------------- #
# Sizing
# --------------------------------------------------------------------------- #


def test_area_options_use_the_plot_and_stop_at_the_ceiling(land_profile):
    small = compute_sizing(_opportunity("guava_meadow"), land_profile(area_hectares=1.2))
    assert small.hectares == pytest.approx(1.2)
    assert not small.capped

    huge = compute_sizing(_opportunity("guava_meadow"), land_profile(area_hectares=500))
    assert huge.hectares == pytest.approx(20.0)  # maxHa in the knowledge base
    assert huge.capped


def test_a_standalone_business_does_not_multiply_with_land(land_profile):
    """Owning fifty hectares is no reason to plan eight dal mills."""
    for hectares in (0.2, 5.0, 50.0):
        sizing = compute_sizing(_opportunity("mini_dal_mill"), land_profile(area_hectares=hectares))
        assert sizing.units == 1, hectares


def test_a_land_limited_unit_does_scale_with_land(land_profile):
    one = compute_sizing(_opportunity("polyhouse_vegetables"), land_profile(area_hectares=0.2))
    many = compute_sizing(_opportunity("polyhouse_vegetables"), land_profile(area_hectares=1.2))
    assert one.units == 1
    assert many.units > one.units


def test_a_landless_business_is_offered_to_a_tiny_holding(land_profile, labels):
    result = assess(
        _opportunity("mushroom_oyster"), land_profile(area_hectares=0.02), labels=labels
    )
    assert result.verdict != "unsuitable"
    assert any(signal.key == "fit.landless" for signal in result.reasons)


# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #


def test_economics_scale_with_the_area_actually_used(land_profile):
    one = compute_economics(
        _opportunity("guava_meadow"),
        compute_sizing(_opportunity("guava_meadow"), land_profile(area_hectares=1.0)),
    )
    two = compute_economics(
        _opportunity("guava_meadow"),
        compute_sizing(_opportunity("guava_meadow"), land_profile(area_hectares=2.0)),
    )
    assert two.capex.mid == pytest.approx(one.capex.mid * 2)
    assert two.revenue_per_year.mid == pytest.approx(one.revenue_per_year.mid * 2)


def test_the_net_band_pairs_worst_with_worst(land_profile):
    """The low end must be the worst income against the worst cost."""
    economics = compute_economics(
        _opportunity("guava_meadow"),
        compute_sizing(_opportunity("guava_meadow"), land_profile()),
    )
    assert economics.net_per_year.low == pytest.approx(
        economics.revenue_per_year.low - economics.opex_per_year.high
    )
    assert economics.net_per_year.high == pytest.approx(
        economics.revenue_per_year.high - economics.opex_per_year.low
    )


@pytest.mark.parametrize(
    ("year", "gestation", "full_year", "expected"),
    [
        (1, 30, 4, 0.0),  # nothing during a two-and-a-half-year gestation
        (3, 30, 4, 0.5),  # first bearing year, half a crop
        (4, 30, 4, 1.0),
        (9, 30, 4, 1.0),
        (1, 3, 1, 1.0),  # an annual crop is at full output in year one
    ],
)
def test_revenue_ramps_only_after_the_gestation(year, gestation, full_year, expected):
    assert revenue_factor(year, gestation, full_year) == pytest.approx(expected)


def test_payback_never_precedes_the_first_harvest(land_profile):
    """An orchard that fruits in year three cannot pay for itself in year one.

    Dividing cost by full-yield income would say it does, and a farmer might
    borrow against that answer.
    """
    opportunity = _opportunity("guava_meadow")
    economics = compute_economics(
        opportunity, compute_sizing(opportunity, land_profile(area_hectares=1.2))
    )
    first_earning_year = economics.gestation_months // 12
    assert economics.payback_years is not None
    assert economics.payback_years > first_earning_year


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #


def test_blocked_options_always_sort_below_real_answers(land_profile, labels):
    results = rank(land_profile(), labels=labels)
    verdicts = [result.verdict for result in results]
    assert verdicts == sorted(
        verdicts, key=lambda v: {"recommended": 0, "possible": 1, "unsuitable": 2}[v]
    )


def test_scores_are_spread_rather_than_all_pinned_at_the_top(land_profile, labels):
    """A list where everything is 'recommended' has told the farmer nothing."""
    results = rank(land_profile(), labels=labels)
    usable = [r for r in results if r.verdict != "unsuitable"]
    recommended = [r for r in usable if r.verdict == "recommended"]

    assert len(recommended) < len(usable) / 2
    assert max(r.score for r in usable) <= 100
    assert len({r.score for r in usable}) > 5


def test_recommended_means_it_cleared_the_bar(land_profile, labels):
    for result in rank(land_profile(), labels=labels):
        if result.verdict == "recommended":
            assert result.score >= RECOMMENDED_AT
            assert not result.blockers


def test_a_waterlogged_bihar_plot_leads_with_makhana(labels):
    """The clearest case in the knowledge base: land that floods every year."""
    profile = LandProfile(
        area_hectares=0.3,
        state_code="10",
        soil_type="clayey",
        water_sources=("pond_tank",),
        water_type="sweet",
        irrigation_type="flood",
        existing_crops=("rice",),
    )
    results = rank(profile, labels=labels, include_unsuitable=False)
    assert results[0].opportunity["code"] == "makhana_foxnut"


def test_a_dry_saline_rajasthan_plot_leads_with_hardy_crops(labels):
    profile = LandProfile(
        area_hectares=4.0,
        state_code="8",
        soil_type="sandy",
        water_sources=("borewell",),
        water_type="salty",
        water_depth_metres=120.0,
        irrigation_type="sprinkler",
        existing_crops=("bajra", "mustard"),
    )
    top = [r.opportunity["code"] for r in rank(profile, labels=labels)[:5]]
    assert {"lemongrass_oil", "moringa_drumstick"} & set(top)
    # Nothing thirsty and salt-sensitive should be anywhere near the top.
    assert "banana_tissue_culture" not in top


def test_every_reason_has_a_string_to_render(land_profile, labels):
    """A reason code with no catalogue entry would print as a raw key."""
    english = knowledge.load_catalogue("en")["strings"]
    for result in rank(land_profile(), labels=labels):
        for signal in result.reasons + result.cautions + result.blockers:
            assert signal.key in english, signal.key


# --------------------------------------------------------------------------- #
# The endpoints
# --------------------------------------------------------------------------- #


def test_the_options_endpoint_answers_for_a_saved_parcel(client, parcel_id):
    response = client.get(
        f"/api/v1/land-parcels/{parcel_id}/opportunities", params={"lang": "en"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["parcelId"] == parcel_id
    assert body["items"]
    assert body["dataAsOf"]
    assert body["basis"]  # the report says where its numbers come from
    assert sum(body["counts"].values()) == len(body["items"])


# --------------------------------------------------------------------------- #
# Non-farming projects: raw material, customers and catchment, not soil
# --------------------------------------------------------------------------- #


def _keys(assessment) -> set[str]:
    return {s.key for s in assessment.reasons + assessment.cautions + assessment.blockers}


def test_a_mill_is_judged_on_its_raw_material_not_the_soil(land_profile, labels):
    mill = _opportunity("mini_dal_mill")
    strong = assess(
        mill,
        land_profile(
            existing_crops=("chana", "wheat"),
            subdistrict_name="Pindra",
            catchment_villages=180,
            nearby_farms=(frozenset({"tur"}), frozenset({"moong", "rice"})),
        ),
        labels=labels,
    )
    keys = _keys(strong)
    assert {"fit.ownFeedstock", "fit.nearbyFeedstock", "fit.catchmentLarge"} <= keys
    assert not {k for k in keys if k.startswith(("fit.soil", "fit.irrigation", "fit.water", "fit.rainfed"))}, keys
    assert strong.verdict == "recommended", strong.score
    own = next(s for s in strong.reasons if s.key == "fit.ownFeedstock")
    assert own.variables["crops"] == "chana"

    # The same mill with nothing to go on: it has to buy everything in.
    weak = assess(mill, land_profile(existing_crops=("wheat",)), labels=labels)
    assert "fit.buyFeedstock" in _keys(weak)
    assert weak.verdict == "possible" and weak.score < strong.score


def test_an_unknown_soil_says_nothing_about_a_business(land_profile, labels):
    """'Get a soil test' is advice for a crop, not for a cold room."""
    result = assess(_opportunity("modular_cold_room"), land_profile(soil_type=None, water_type="salty"), labels=labels)
    assert result.verdict != "unsuitable"
    assert "fit.soilUnknown" not in _keys(result)
    assert "fit.soilUnknown" in _keys(assess(_opportunity("guava_meadow"), land_profile(soil_type=None), labels=labels))


def test_crops_on_the_family_s_other_plots_count_for_a_business(land_profile, labels):
    result = assess(
        _opportunity("oil_expeller_unit"),
        land_profile(existing_crops=("rice",), household_crops=("rice", "mustard")),
        labels=labels,
    )
    assert "fit.ownFeedstock" in _keys(result)


def test_farms_nearby_that_grow_it_are_a_supply(land_profile, labels):
    result = assess(
        _opportunity("mini_dal_mill"),
        land_profile(existing_crops=(), nearby_farms=(frozenset({"chana"}), frozenset({"tur", "wheat"}), frozenset({"rice"}))),
        labels=labels,
    )
    nearby = next(s for s in result.reasons if s.key == "fit.nearbyFeedstock")
    assert nearby.variables["n"] == "2", "only farms growing pulses count"
    assert "fit.buyFeedstock" not in _keys(result)


def test_a_service_s_crops_are_its_customers(land_profile, labels):
    result = assess(_opportunity("custom_hiring_centre"), land_profile(existing_crops=("wheat",)), labels=labels)
    assert "fit.ownCustomers" in _keys(result)
    assert "fit.buyFeedstock" not in _keys(result), "a hiring centre buys no raw material"


def test_a_small_catchment_is_a_caution(land_profile, labels):
    result = assess(
        _opportunity("drone_spraying_service"),
        land_profile(subdistrict_name="Tiny", catchment_villages=12),
        labels=labels,
    )
    small = next(s for s in result.cautions if s.key == "fit.catchmentSmall")
    assert small.variables == {"n": "12", "tehsil": "Tiny"}


def test_a_business_can_earn_beyond_a_small_holding(land_profile, labels):
    small = assess(_opportunity("village_bakery"), land_profile(area_hectares=0.3), labels=labels)
    large = assess(_opportunity("village_bakery"), land_profile(area_hectares=3.0), labels=labels)
    assert "fit.smallHoldingBusiness" in _keys(small)
    assert "fit.smallHoldingBusiness" not in _keys(large)


def test_a_district_mandi_trading_it_is_evidence_it_is_grown(land_profile, labels):
    mill = _opportunity("mini_dal_mill")
    without = assess(mill, land_profile(existing_crops=("wheat",)), labels=labels)
    traded = assess(
        mill,
        land_profile(existing_crops=("wheat",), district_name="Varanasi", mandi_crops=("tur", "wheat")),
        labels=labels,
    )
    mandi = next(s for s in traded.reasons if s.key == "fit.mandiFeedstock")
    assert mandi.variables == {"crops": "tur", "district": "Varanasi"}
    assert "fit.buyFeedstock" not in _keys(traded), "raw material can be bought locally"
    assert traded.score > without.score
    # Wheat in the mandi is no evidence for a dal mill.
    assert "fit.mandiFeedstock" not in _keys(
        assess(mill, land_profile(district_name="Varanasi", mandi_crops=("wheat",)), labels=labels)
    )


def test_imported_mandi_prices_reach_the_plan_page(client, parcel_id):
    from datetime import date

    from app.db import session_scope
    from app.models import MandiPrice

    with session_scope() as session:
        for commodity, district in (("Arhar (Tur/Red Gram)(Whole)", "Varanasi"), ("Onion", "Nashik")):
            session.add(MandiPrice(state_name="Uttar Pradesh", district_name=district, market=f"{district} mandi",
                                   commodity=commodity, arrival_date=date(2026, 8, 1), modal_price=7200,
                                   source="agmarknet", imported_at=date(2026, 8, 2)))
    items = {
        item["code"]: item
        for item in client.get(f"/api/v1/land-parcels/{parcel_id}/opportunities", params={"lang": "en"}).json()["items"]
    }
    mill_text = " ".join(s["text"] for s in items["mini_dal_mill"]["reasons"])
    assert "Mandis in Varanasi trade" in mill_text, mill_text
    # Onion was traded in another district, so it says nothing about this one.
    assert not any(s["code"] == "fit.mandiFeedstock" for s in items["modular_cold_room"]["reasons"])


def test_the_plan_page_sees_the_district_and_the_tehsil(client, parcel_id):
    """Other farmers' projects in the district, and the village directory, reach the reasons."""
    from .test_marketplace import insert_profile, insert_request

    for name in ("Ramesh", "Suresh"):
        insert_request(insert_profile("farmer", display_name=name))  # grows grapes and onion
    # Sample data is not evidence of anything.
    insert_request(insert_profile("farmer", display_name="Sample", origin="demo"), origin="demo")
    items = {
        item["code"]: item
        for item in client.get(f"/api/v1/land-parcels/{parcel_id}/opportunities", params={"lang": "en"}).json()["items"]
    }
    dryer = items["solar_dehydration_unit"]
    texts = " ".join(s["text"] for s in dryer["reasons"] + dryer["cautions"])
    # Grapes and onion both feed a dryer; with two farms each, the tie goes alphabetically.
    assert "Farms near you grow Grapes: 2 in your district" in texts, texts
    assert "Pindra tehsil has" in texts, texts


def test_every_option_says_whether_it_is_farming_or_not(client, parcel_id):
    """The plan page puts farming, non-farming and hybrid projects apart."""
    body = client.get(
        f"/api/v1/land-parcels/{parcel_id}/opportunities", params={"lang": "en"}
    ).json()
    sector = {item["code"]: item["sector"] for item in body["items"]}
    assert set(sector.values()) == {"farm", "nonfarm", "hybrid"}
    assert sector["dairy_crossbred"] == "farm"
    assert sector["modular_cold_room"] == "nonfarm"
    assert sector["custom_hiring_centre"] == "nonfarm"
    assert sector["grafted_sapling_nursery"] == "farm", "a nursery is plants growing on land"
    assert sector["dairy_biogas_vermi"] == "hybrid"
    assert sector["farmstead_cheese"] == "hybrid"


def test_every_option_names_its_country_of_origin(client, parcel_id):
    """Each suggestion says where its model comes from, in the reader's language."""
    body = client.get(
        f"/api/v1/land-parcels/{parcel_id}/opportunities", params={"lang": "en"}
    ).json()
    origin = {item["code"]: item["origin"] for item in body["items"]}
    for code, entry in origin.items():
        assert len(entry["country"]) == 2 and entry["country"].isupper(), code
        assert entry["countryName"] and entry["countryName"] != entry["country"], code
        assert entry["note"], code
        assert entry["scope"] == ("national" if entry["country"] == "IN" else "international"), code

    assert origin["dairy_crossbred"]["scope"] == "national"
    assert origin["polyhouse_vegetables"]["country"] == "NL"
    assert origin["avocado_hass"]["country"] == "MX"
    assert origin["farmstead_cheese"]["country"] == "CH"

    scopes = {(item["sector"], item["origin"]["scope"]) for item in body["items"]}
    for sector in ("farm", "nonfarm", "hybrid"):
        for scope in ("national", "international"):
            assert (sector, scope) in scopes, f"no {scope} {sector} option at all"

    hindi = client.get(
        f"/api/v1/land-parcels/{parcel_id}/opportunities", params={"lang": "hi"}
    ).json()
    cheese = next(item for item in hindi["items"] if item["code"] == "farmstead_cheese")
    assert cheese["origin"]["countryName"] != "Switzerland"
    assert any("ऀ" <= ch <= "ॿ" for ch in cheese["origin"]["note"])


def test_a_hybrid_option_is_judged_on_the_land_and_the_business(client, parcel_id):
    """A hybrid project needs the land to suit the farm half, and still shows the business half's evidence."""
    body = client.get(
        f"/api/v1/land-parcels/{parcel_id}/opportunities", params={"lang": "en"}
    ).json()
    hybrid = [item for item in body["items"] if item["sector"] == "hybrid"]
    assert len(hybrid) >= 8
    for item in hybrid:
        assert item["economics"]["capex"]["mid"] > 0
        assert item["reasons"] or item["cautions"] or item["blockers"], item["code"]


def test_every_reason_arrives_as_a_finished_sentence(client, parcel_id):
    """The API renders reasons; the UI must never have to build one."""
    body = client.get(
        f"/api/v1/land-parcels/{parcel_id}/opportunities", params={"lang": "en"}
    ).json()
    for item in body["items"]:
        for signal in item["reasons"] + item["cautions"] + item["blockers"]:
            assert signal["text"]
            assert "{" not in signal["text"], signal
            assert signal["text"] != signal["code"]


def test_hindi_options_come_back_in_hindi(client, parcel_id):
    body = client.get(
        f"/api/v1/land-parcels/{parcel_id}/opportunities", params={"lang": "hi"}
    ).json()
    top = body["items"][0]
    assert any("ऀ" <= ch <= "ॿ" for ch in top["name"] + top["summary"])


def test_unsuitable_options_can_be_left_out(client, parcel_id):
    everything = client.get(
        f"/api/v1/land-parcels/{parcel_id}/opportunities", params={"lang": "en"}
    ).json()
    filtered = client.get(
        f"/api/v1/land-parcels/{parcel_id}/opportunities",
        params={"lang": "en", "includeUnsuitable": "false"},
    ).json()
    assert filtered["counts"]["unsuitable"] == 0
    assert len(filtered["items"]) <= len(everything["items"])


def test_the_export_filter_returns_only_exportable_options(client, parcel_id):
    body = client.get(
        f"/api/v1/land-parcels/{parcel_id}/opportunities",
        params={"lang": "en", "exportOnly": "true"},
    ).json()
    assert body["items"]
    for item in body["items"]:
        assert item["export"]["potential"] != "none"
        assert item["export"]["worldTradeUsd"]


def test_options_for_a_missing_parcel_is_a_404(client):
    assert client.get("/api/v1/land-parcels/nope/opportunities").status_code == 404


def test_an_unknown_language_is_rejected(client, parcel_id):
    response = client.get(
        f"/api/v1/land-parcels/{parcel_id}/opportunities", params={"lang": "xx"}
    )
    assert response.status_code == 422


def test_export_markets_can_be_browsed_without_a_parcel(client):
    body = client.get("/api/v1/export-markets", params={"lang": "en"}).json()
    assert len(body["items"]) >= 20
    assert body["disclaimer"]
    assert body["commonResources"]


def test_one_commodity_can_be_asked_for(client):
    body = client.get(
        "/api/v1/export-markets", params={"lang": "en", "commodity": "basmati_rice"}
    ).json()
    assert len(body["items"]) == 1
    entry = body["items"][0]
    assert entry["destinations"]
    assert entry["certifications"]
    assert entry["indiaExportUsd"]["confidence"] in {"reported", "estimate"}


def test_an_unknown_commodity_is_a_404(client):
    assert (
        client.get("/api/v1/export-markets", params={"commodity": "unobtanium"}).status_code
        == 404
    )
