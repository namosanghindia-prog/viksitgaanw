"""Loader for the curated knowledge base in ``packages/shared/knowledge``.

Three bodies of data live there, and all of them are read-only content that
ships with the app rather than user data:

* **Opportunities** -- the farming and agri-business options the suggestion
  engine ranks, split one file per kind so a horticulture expert and a
  livestock expert can edit different files.
* **Export markets** -- what a commodity earns abroad, who buys it, and what
  registration it needs, keyed by the ``export.commodity`` of an opportunity.
* **DPR translation catalogues** -- one file per language, holding the report's
  headings and labels plus, for languages the shared reference lists do not
  cover, the opportunity names and reference labels too.

The frontend imports the same JSON at build time, so a card on screen and a
line in a generated PDF cannot disagree about what something is called.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import get_settings

#: What a missing string falls back to. English only -- deliberately *not*
#: Hindi. A Tamil or Malayalam speaker who asked for a report in their own
#: language is not helped by getting one in Hindi, and English is the language
#: every bank in India will accept a project report in. Hindi is used when it
#: is asked for, and never as a substitute for another Indian language.
FALLBACK_CHAIN = ("en",)

#: Label dictionaries in the shared data carry these two languages only. Any
#: other language gets its labels from the DPR catalogue instead.
NATIVE_LABEL_LANGUAGES = frozenset({"en", "hi"})


class KnowledgeUnavailableError(RuntimeError):
    """Raised when the knowledge base cannot be located or is malformed."""


def _knowledge_dir() -> Path:
    directory = get_settings().knowledge_dir
    if not directory.is_dir():
        raise KnowledgeUnavailableError(
            f"Knowledge directory not found: {directory}. "
            "Set VG_KNOWLEDGE_DIR or run from the repository root."
        )
    return directory


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise KnowledgeUnavailableError(f"Missing knowledge file: {path}")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


# --------------------------------------------------------------------------- #
# Opportunities
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def load_opportunities() -> dict[str, Any]:
    """Merge ``opportunities/_meta.json`` with every kind file beside it.

    Returns ``{"meta": {...}, "items": [...]}``. Cached for the process
    lifetime; tests clear it with ``load_opportunities.cache_clear()``.
    """
    directory = _knowledge_dir() / "opportunities"
    if not directory.is_dir():
        raise KnowledgeUnavailableError(f"Missing knowledge directory: {directory}")

    meta = _read_json(directory / "_meta.json")

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        block = _read_json(path)
        if not isinstance(block, list):
            raise KnowledgeUnavailableError(f"{path} must hold a JSON array of options.")
        for item in block:
            code = item.get("code")
            if not code:
                raise KnowledgeUnavailableError(f"{path}: an option has no code.")
            if code in seen:
                # Two files claiming the same code would make the ranking
                # non-deterministic depending on filesystem order.
                raise KnowledgeUnavailableError(f"Duplicate opportunity code: {code}")
            # Every suggestion says where its model comes from: a farmer weighs
            # a Dutch greenhouse differently from a Rahuri pomegranate.
            country = (item.get("origin") or {}).get("country")
            if not (isinstance(country, str) and len(country) == 2 and country.isupper()):
                raise KnowledgeUnavailableError(f"{path}: {code} has no origin country.")
            if item.get("sector") not in (None, *SECTORS):
                raise KnowledgeUnavailableError(f"{path}: {code} has an unknown sector.")
            seen.add(code)
            items.append(item)

    return {"meta": meta, "items": items}


def opportunity_items() -> list[dict[str, Any]]:
    return load_opportunities()["items"]


def opportunity_meta() -> dict[str, Any]:
    return load_opportunities()["meta"]


@lru_cache(maxsize=1)
def _opportunity_index() -> dict[str, dict[str, Any]]:
    return {item["code"]: item for item in opportunity_items()}


def get_opportunity(code: str) -> dict[str, Any] | None:
    return _opportunity_index().get(code)


@lru_cache(maxsize=1)
def scheme_index() -> dict[str, dict[str, Any]]:
    return {scheme["code"]: scheme for scheme in opportunity_meta().get("schemes", [])}


@lru_cache(maxsize=1)
def kind_index() -> dict[str, dict[str, Any]]:
    return {kind["code"]: kind for kind in opportunity_meta().get("kinds", [])}


#: Farm (crops and allied: livestock, fisheries, beekeeping) or non-farm
#: (processing, storage, services), as NABARD and NRLM split livelihoods --
#: and hybrid: a farm with its own business on top (a dairy with a biogas and
#: compost unit, a turmeric farm that sells powder, an orchard with a farm stay).
SECTORS = ("farm", "nonfarm", "hybrid")

#: The country an option's model is Indian to. Anything else is international.
HOME_COUNTRY = "IN"


def opportunity_sector(item: dict[str, Any]) -> str:
    """Whether an option is a farming, a non-farming or a hybrid project.

    Its kind decides, unless the option says otherwise -- a sapling nursery is
    filed as a service business but is plants growing on land, and a hybrid
    names itself.
    """
    return item.get("sector") or kind_index()[item["kind"]]["sector"]


def opportunity_origin(item: dict[str, Any]) -> dict[str, Any]:
    """Where the option's farming or business model comes from.

    ``{"country": "IL", "note": {...}}`` -- every option carries one, and the
    loader refuses a knowledge base where one does not.
    """
    return item.get("origin") or {"country": HOME_COUNTRY}


def opportunity_scope(item: dict[str, Any]) -> str:
    """national (an Indian model) or international (one from abroad)."""
    return "national" if opportunity_origin(item).get("country") == HOME_COUNTRY else "international"


def business_crops(item: dict[str, Any]) -> frozenset[str]:
    """The crops a non-farming project works with, as crop codes.

    For a processing unit they are its raw material; for a service, what its
    customers grow. The knowledge base may name a whole category ("pulse")
    rather than every crop in it, so categories are expanded here.
    """
    from . import reference  # noqa: PLC0415 - knowledge loads before reference in some scripts

    wanted = set((item.get("business") or {}).get("crops") or [])
    crops = reference.get_list("crops")["items"]
    return frozenset(
        crop["code"] for crop in crops if crop["code"] in wanted or crop.get("category") in wanted
    )


@lru_cache(maxsize=1)
def region_states() -> dict[str, frozenset[str]]:
    """Region name -> the LGD state codes in it. An empty set means all-India."""
    return {
        name: frozenset(codes)
        for name, codes in opportunity_meta().get("regions", {}).items()
    }


# --------------------------------------------------------------------------- #
# Export markets
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def load_export_markets() -> dict[str, Any]:
    return _read_json(_knowledge_dir() / "export-markets.json")


@lru_cache(maxsize=1)
def _export_index() -> dict[str, dict[str, Any]]:
    return {item["commodity"]: item for item in load_export_markets().get("items", [])}


def get_export_market(commodity: str | None) -> dict[str, Any] | None:
    if not commodity:
        return None
    return _export_index().get(commodity)


# --------------------------------------------------------------------------- #
# Insurance
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def load_insurance_rules() -> dict[str, Any]:
    """Which cover each kind of project must carry, and which is advised."""
    return _read_json(_knowledge_dir() / "insurance-rules.json")


@lru_cache(maxsize=1)
def load_schemes() -> dict[str, Any]:
    """Government schemes, with what the app can and cannot check."""
    return _read_json(_knowledge_dir() / "schemes.json")


@lru_cache(maxsize=1)
def load_mandi_commodities() -> dict[str, Any]:
    """How each crop is named in Agmarknet price data."""
    return _read_json(_knowledge_dir() / "mandi-commodities.json")


# --------------------------------------------------------------------------- #
# Languages
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def load_languages() -> dict[str, Any]:
    return _read_json(_knowledge_dir() / "languages.json")


@lru_cache(maxsize=1)
def language_index() -> dict[str, dict[str, Any]]:
    return {item["code"]: item for item in load_languages()["items"]}


def get_language(code: str) -> dict[str, Any] | None:
    return language_index().get(code)


@lru_cache(maxsize=1)
def _catalogue_dir() -> Path:
    return _knowledge_dir() / "dpr"


@lru_cache(maxsize=1)
def translated_languages() -> frozenset[str]:
    """Language codes that have a DPR catalogue file on disk."""
    directory = _catalogue_dir()
    if not directory.is_dir():
        return frozenset()
    return frozenset(path.stem for path in directory.glob("*.json"))


@lru_cache(maxsize=32)
def load_catalogue(language: str) -> dict[str, Any]:
    """Read one language's DPR catalogue, or an empty one if it is absent.

    A missing catalogue is not an error: the language is still offered, every
    string falls back to English, and the coverage figure tells the caller
    (and the report's own cover) how much was actually translated.
    """
    path = _catalogue_dir() / f"{language}.json"
    if not path.is_file():
        return {"language": language, "strings": {}}
    return _read_json(path)


def catalogue_coverage(language: str) -> float:
    """Fraction of everything a report can print that this language covers.

    Not just the headings. An option's name and its descriptive paragraph, and
    the labels for soil, water and crops, all appear in the report too, and a
    language that has the headings but none of those still produces a document
    half in English. Counting only ``strings`` would let the report claim to be
    fully translated when it plainly is not, which is the one thing the
    coverage figure exists to prevent.
    """
    english = load_catalogue("en").get("strings", {})
    if not english:
        return 0.0

    catalogue = load_catalogue(language)
    strings = catalogue.get("strings", {})
    done = sum(1 for key in english if strings.get(key))
    total = len(english)

    # English and Hindi take names, summaries and reference labels from the
    # shared data files, which always carry both, so there is nothing else to
    # count for them.
    if language in NATIVE_LABEL_LANGUAGES:
        return done / total

    names = catalogue.get("opportunities", {})
    summaries = catalogue.get("summaries", {})
    for item in opportunity_items():
        total += 2
        done += 1 if names.get(item["code"]) else 0
        done += 1 if summaries.get(item["code"]) else 0

    return done / total if total else 0.0


def clear_caches() -> None:
    """Drop every cached read. Used by tests that write knowledge fixtures."""
    for cached in (
        load_opportunities,
        _opportunity_index,
        scheme_index,
        kind_index,
        region_states,
        load_export_markets,
        _export_index,
        load_insurance_rules,
        load_schemes,
        load_mandi_commodities,
        load_languages,
        language_index,
        _catalogue_dir,
        translated_languages,
        load_catalogue,
    ):
        cached.cache_clear()
