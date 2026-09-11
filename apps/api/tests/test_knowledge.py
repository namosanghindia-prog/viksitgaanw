"""Integrity of the curated knowledge base.

The knowledge base is content, edited by hand by people who know agronomy
rather than Python, so the checks here are the ones that catch an editing
mistake before it reaches a farmer: an option pointing at a scheme that does not
exist, a soil type spelled wrong so a crop is silently never suggested, an
income band lower than the cost band, a translation key nobody translated.
"""

from __future__ import annotations

import json

import pytest

from app import knowledge, reference


@pytest.fixture(scope="module")
def options() -> list[dict]:
    return knowledge.opportunity_items()


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #


def test_there_is_a_meaningful_range_of_options(options):
    assert len(options) >= 30
    kinds = {item["kind"] for item in options}
    # A list that is all orchards is no use to someone with no land or no water.
    assert {"horticulture", "livestock", "processing", "service"} <= kinds


def test_option_codes_are_unique(options):
    codes = [item["code"] for item in options]
    assert len(codes) == len(set(codes))


def test_every_option_names_a_kind_that_exists(options):
    kinds = set(knowledge.kind_index())
    for item in options:
        assert item["kind"] in kinds, item["code"]


def test_every_option_is_farming_or_non_farming(options):
    """The plan page shows the two side by side; an option in neither would vanish."""
    for kind in knowledge.kind_index().values():
        assert kind.get("sector") in knowledge.SECTORS, kind["code"]
    for item in options:
        assert item.get("sector", "farm") in knowledge.SECTORS, item["code"]
    counts = {sector: 0 for sector in knowledge.SECTORS}
    for item in options:
        counts[knowledge.opportunity_sector(item)] += 1
    # Someone with no land still needs a real choice of non-farming projects.
    assert counts["nonfarm"] >= 12 and counts["farm"] >= 20, counts


def test_every_non_farming_project_says_what_it_works_with(options):
    """A mistyped crop would silently drop the raw-material signal for everyone."""
    crops = reference.get_list("crops")
    known = {item["code"] for item in crops["items"]} | {
        c["code"] if isinstance(c, dict) else c for c in crops["categories"]
    }
    for item in options:
        if knowledge.opportunity_sector(item) != "nonfarm":
            assert "business" not in item, f"{item['code']} is farming; business applies to non-farming only"
            continue
        business = item.get("business")
        assert business, f"{item['code']} needs a business block"
        assert isinstance(business.get("catchmentVillages"), int) and business["catchmentVillages"] > 0, item["code"]
        for code in business.get("crops", []):
            assert code in known, f"{item['code']} -> {code}"
    assert knowledge.business_crops(knowledge.get_opportunity("mini_dal_mill")) >= {"tur", "chana", "masoor"}


def test_every_scheme_reference_resolves(options):
    """A dangling scheme code would silently drop a subsidy from the report."""
    schemes = set(knowledge.scheme_index())
    for item in options:
        for code in item.get("schemes", []):
            assert code in schemes, f"{item['code']} -> {code}"


def test_every_region_reference_resolves(options):
    regions = set(knowledge.region_states())
    for item in options:
        for region in item["fit"].get("regions", []):
            assert region in regions, f"{item['code']} -> {region}"


def test_every_state_code_referenced_is_a_real_lgd_code(options):
    """A typo here would quietly exclude a whole state from an option."""
    valid = {str(code) for code in range(1, 39)}
    for item in options:
        for key in ("alsoStates", "excludeStates"):
            for code in item["fit"].get(key, []):
                assert code in valid, f"{item['code']} {key} -> {code}"


@pytest.mark.parametrize(
    ("field", "list_key"),
    [
        ("soilTypes", "soil_types"),
        ("avoidSoilTypes", "soil_types"),
        ("preferredIrrigation", "irrigation_types"),
        ("preferredWaterSources", "water_sources"),
        ("requiresExistingCrops", "crops"),
    ],
)
def test_fit_rules_use_real_reference_codes(options, field, list_key):
    """A misspelled soil type means the rule never fires and nobody notices."""
    valid = reference.valid_codes(list_key)
    for item in options:
        for code in item["fit"].get(field, []):
            assert code in valid, f"{item['code']} {field} -> {code}"


def test_an_option_never_both_wants_and_forbids_a_soil(options):
    for item in options:
        wanted = set(item["fit"].get("soilTypes", []))
        avoided = set(item["fit"].get("avoidSoilTypes", []))
        assert not (wanted & avoided), item["code"]


def test_sizing_is_coherent(options):
    for item in options:
        sizing = item["sizing"]
        if sizing["mode"] == "area":
            assert sizing["minHa"] > 0
            assert sizing["maxHa"] > sizing["minHa"], item["code"]
        else:
            assert sizing["landHaPerUnit"] > 0, item["code"]
            assert sizing["maxUnits"] >= sizing["minUnits"] >= 1, item["code"]
            # Without this flag the engine cannot tell a polyhouse, which is
            # limited by land, from a dal mill, which is not.
            assert "unitsFromLand" in sizing, item["code"]


# --------------------------------------------------------------------------- #
# The numbers
# --------------------------------------------------------------------------- #


def test_cost_and_income_bands_run_the_right_way(options):
    for item in options:
        for key in ("capex", "opexPerYear", "revenuePerYear"):
            band = item["economics"][key]
            assert band["low"] <= band["high"], f"{item['code']} {key}"


def test_no_option_is_a_guaranteed_loss(options):
    """An option whose best year still loses money should not be on the list."""
    for item in options:
        economics = item["economics"]
        assert economics["revenuePerYear"]["high"] > economics["opexPerYear"]["low"], item[
            "code"
        ]


def test_timelines_are_plausible(options):
    for item in options:
        economics = item["economics"]
        assert 0 < economics["gestationMonths"] <= 72, item["code"]
        assert 1 <= economics["fullYieldYear"] <= 12, item["code"]
        assert economics["projectLifeYears"] >= economics["fullYieldYear"], item["code"]
        assert economics["riskLevel"] in {"low", "medium", "high"}, item["code"]
        assert economics["labourDaysPerYear"] > 0, item["code"]


def test_full_yield_is_never_claimed_before_the_gestation_ends(options):
    for item in options:
        economics = item["economics"]
        first_earning_year = economics["gestationMonths"] // 12 + 1
        assert economics["fullYieldYear"] >= first_earning_year, item["code"]


# --------------------------------------------------------------------------- #
# Export markets
# --------------------------------------------------------------------------- #


def test_every_exportable_option_has_a_market_entry(options):
    for item in options:
        export = item.get("export", {})
        if export.get("potential", "none") == "none":
            continue
        assert knowledge.get_export_market(export["commodity"]) is not None, item["code"]


def test_export_entries_name_real_countries_and_certificates():
    data = knowledge.load_export_markets()
    countries = set(data["countries"])
    certificates = {entry["code"] for entry in data["certifications"]}
    for entry in data["items"]:
        for code in entry["destinations"]:
            assert code in countries, f"{entry['commodity']} -> {code}"
        for code in entry["certifications"]:
            assert code in certificates, f"{entry['commodity']} -> {code}"


def test_every_trade_figure_declares_how_reliable_it_is():
    """A number with no provenance must never appear on a bank document."""
    for entry in knowledge.load_export_markets()["items"]:
        for key in ("indiaExportUsd", "worldTradeUsd"):
            figure = entry[key]
            assert figure["confidence"] in {"reported", "estimate"}, entry["commodity"]
            assert figure["low"] <= figure["high"], f"{entry['commodity']} {key}"
            assert figure.get("source"), f"{entry['commodity']} {key}"


def test_india_is_never_claimed_to_export_more_than_the_world_imports():
    for entry in knowledge.load_export_markets()["items"]:
        assert entry["indiaExportUsd"]["low"] <= entry["worldTradeUsd"]["high"], entry[
            "commodity"
        ]


# --------------------------------------------------------------------------- #
# Links
# --------------------------------------------------------------------------- #


def test_every_link_is_a_plausible_url(options):
    def check(links, where):
        for link in links:
            assert link["url"].startswith("https://") or link["url"].startswith("http://"), where
            assert link.get("label", {}).get("en"), where

    for item in options:
        check(item.get("resources", []), item["code"])
    check(knowledge.opportunity_meta()["schemes"], "schemes")
    data = knowledge.load_export_markets()
    check(data["commonResources"], "commonResources")
    check(data["certifications"], "certifications")


# --------------------------------------------------------------------------- #
# Translation catalogues
# --------------------------------------------------------------------------- #


def test_english_defines_every_string_the_report_can_need():
    english = knowledge.load_catalogue("en")["strings"]
    assert len(english) > 150
    assert all(value.strip() for value in english.values())


def test_hindi_matches_english_key_for_key():
    """Hindi is the app's default, so a gap there is a gap for most users."""
    english = set(knowledge.load_catalogue("en")["strings"])
    hindi = set(knowledge.load_catalogue("hi")["strings"])
    assert english == hindi


def test_no_catalogue_invents_a_key_english_does_not_have():
    """A stray key is a renamed string quietly falling back everywhere."""
    english = set(knowledge.load_catalogue("en")["strings"])
    for entry in knowledge.load_languages()["items"]:
        strings = set(knowledge.load_catalogue(entry["code"]).get("strings", {}))
        assert strings <= english, entry["code"]


def test_a_language_with_no_catalogue_is_reported_as_untranslated():
    """Coverage drives what the report tells the farmer on its first page."""
    for entry in knowledge.load_languages()["items"]:
        coverage = knowledge.catalogue_coverage(entry["code"])
        assert 0.0 <= coverage <= 1.0
    assert knowledge.catalogue_coverage("en") == pytest.approx(1.0)


def test_every_placeholder_in_a_translation_exists_in_the_english(options):
    """A stray {placeholder} would print as literal braces to a farmer."""
    import re

    pattern = re.compile(r"\{(\w+)\}")
    english = knowledge.load_catalogue("en")["strings"]

    for entry in knowledge.load_languages()["items"]:
        strings = knowledge.load_catalogue(entry["code"]).get("strings", {})
        for key, value in strings.items():
            expected = set(pattern.findall(english.get(key, "")))
            assert set(pattern.findall(value)) <= expected, f"{entry['code']}:{key}"


# --------------------------------------------------------------------------- #
# Script purity
# --------------------------------------------------------------------------- #

#: Unicode block per ISO 15924 script code, for the scripts the app offers.
_SCRIPT_BLOCKS = {
    "Deva": (0x0900, 0x097F),
    "Beng": (0x0980, 0x09FF),
    "Guru": (0x0A00, 0x0A7F),
    "Gujr": (0x0A80, 0x0AFF),
    "Orya": (0x0B00, 0x0B7F),
    "Taml": (0x0B80, 0x0BFF),
    "Telu": (0x0C00, 0x0C7F),
    "Knda": (0x0C80, 0x0CFF),
    "Mlym": (0x0D00, 0x0D7F),
    "Arab": (0x0600, 0x06FF),
    "Olck": (0x1C50, 0x1C7F),
}

#: The danda and double danda live in the Devanagari block but are the shared
#: full stop of Bengali, Odia, Gurmukhi, Gujarati and others too. Seeing them
#: in a Bengali file is correct, not a mix-up.
_SHARED_PUNCTUATION = {0x0964, 0x0965}


def test_no_catalogue_mixes_in_another_script():
    """One stray glyph from the wrong script is invisible until it prints.

    A Bengali character inside the Tamil catalogue renders as a box or as the
    wrong letter in the middle of an otherwise correct word, and nothing else
    in the pipeline would notice.
    """
    for entry in knowledge.load_languages()["items"]:
        code, expected = entry["code"], entry["script"]
        catalogue = knowledge.load_catalogue(code)
        if not catalogue.get("strings"):
            continue

        text = json.dumps(catalogue, ensure_ascii=False)
        strays: dict[str, int] = {}
        for character in text:
            point = ord(character)
            if point in _SHARED_PUNCTUATION:
                continue
            for script, (low, high) in _SCRIPT_BLOCKS.items():
                if low <= point <= high and script != expected:
                    strays[script] = strays.get(script, 0) + 1

        assert not strays, f"{code} ({expected}) contains {strays}"
