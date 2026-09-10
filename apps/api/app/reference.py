"""Loader for the bilingual reference lists in ``packages/shared/reference``.

Those JSON files are the single source of truth for soil types, water sources,
area units and crops. The React app imports them directly at build time; the
API reads the same files at runtime, so a dropdown option and the value the
server will accept can never drift apart.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import get_settings

#: reference key -> filename in packages/shared/reference
REFERENCE_FILES: dict[str, str] = {
    "area_units": "area-units.json",
    "certifications": "certifications.json",
    "countries": "countries.json",
    "crops": "crops.json",
    "depth_units": "depth-units.json",
    "farmer_needs": "farmer-needs.json",
    "government_levels": "government-levels.json",
    "insurance_schemes": "insurance-schemes.json",
    "insurance_types": "insurance-types.json",
    "investment_modes": "investment-modes.json",
    "investor_types": "investor-types.json",
    "irrigation_types": "irrigation-types.json",
    "organisation_types": "organisation-types.json",
    "ownership_types": "ownership-types.json",
    "partnership_types": "partnership-types.json",
    "risk_appetites": "risk-appetites.json",
    "soil_types": "soil-types.json",
    "user_segments": "user-segments.json",
    "water_sources": "water-sources.json",
    "water_types": "water-types.json",
}


class ReferenceUnavailableError(RuntimeError):
    """Raised when the shared reference data cannot be located."""


def _reference_dir() -> Path:
    return get_settings().reference_dir


@lru_cache(maxsize=1)
def load_all() -> dict[str, dict[str, Any]]:
    """Read and cache every reference list.

    Cached for the process lifetime: these files ship with the app and only
    change on upgrade. Tests can clear it with ``load_all.cache_clear()``.
    """
    directory = _reference_dir()
    if not directory.is_dir():
        raise ReferenceUnavailableError(
            f"Reference directory not found: {directory}. "
            "Set VG_REFERENCE_DIR or run from the repository root."
        )

    lists: dict[str, dict[str, Any]] = {}
    for key, filename in REFERENCE_FILES.items():
        path = directory / filename
        if not path.is_file():
            raise ReferenceUnavailableError(f"Missing reference file: {path}")
        with path.open(encoding="utf-8") as handle:
            lists[key] = json.load(handle)
    return lists


def get_list(key: str) -> dict[str, Any]:
    lists = load_all()
    if key not in lists:
        raise KeyError(key)
    return lists[key]


@lru_cache(maxsize=None)
def valid_codes(key: str) -> frozenset[str]:
    return frozenset(item["code"] for item in get_list(key)["items"])


def is_valid(key: str, code: str | None) -> bool:
    """True when ``code`` is a member of the reference list (None passes)."""
    if code is None:
        return True
    return code in valid_codes(key)


def get_item(key: str, code: str | None) -> dict[str, Any] | None:
    """The full reference entry for ``code``, or None."""
    if code is None:
        return None
    for item in get_list(key)["items"]:
        if item["code"] == code:
            return item
    return None


def label_of(key: str, code: str | None, language: str = "en") -> str | None:
    """A reference entry's label in ``language``, falling back to English."""
    item = get_item(key, code)
    if item is None:
        return None
    labels = item.get("label", {})
    return labels.get(language) or labels.get("en") or item["code"]


def allowed_for_segment(key: str, code: str | None, segment: str) -> bool:
    """True when ``code`` exists and is offered to ``segment``.

    Lists such as investor and organisation types carry a ``segments`` array,
    because an NRI is an international investor and a Gram Panchayat is not a
    partner organisation. Entries without the array are open to everyone.
    """
    item = get_item(key, code)
    if item is None:
        return False
    segments = item.get("segments")
    return segments is None or segment in segments


def area_unit_factor(unit: str) -> float | None:
    """Hectares per one unit of ``unit``, or None if the unit is unknown."""
    for item in get_list("area_units")["items"]:
        if item["code"] == unit:
            return float(item["hectares"])
    return None


def depth_unit_factor(unit: str) -> float | None:
    """Metres per one unit of ``unit``, or None if the unit is unknown."""
    for item in get_list("depth_units")["items"]:
        if item["code"] == unit:
            return float(item["metres"])
    return None
