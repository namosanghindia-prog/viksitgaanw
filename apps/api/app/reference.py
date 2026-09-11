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
    "diary_activities": "diary-activities.json",
    "dispute_reasons": "dispute-reasons.json",
    "equipment_conditions": "equipment-conditions.json",
    "equipment_types": "equipment-types.json",
    "farmer_needs": "farmer-needs.json",
    "government_levels": "government-levels.json",
    "group_kinds": "group-kinds.json",
    "insurance_schemes": "insurance-schemes.json",
    "insurance_types": "insurance-types.json",
    "investment_modes": "investment-modes.json",
    "investor_types": "investor-types.json",
    "irrigation_types": "irrigation-types.json",
    "loan_documents": "loan-documents.json",
    "loan_purposes": "loan-purposes.json",
    "organisation_types": "organisation-types.json",
    "ownership_types": "ownership-types.json",
    "partner_roles": "partner-roles.json",
    "partnership_types": "partnership-types.json",
    "quantity_units": "quantity-units.json",
    "rent_units": "rent-units.json",
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


# --------------------------------------------------------------------------- #
# Choices people type themselves
# --------------------------------------------------------------------------- #

#: A choice the person typed rather than picked -- "Dragon fruit", "Kisan
#: club" -- is kept in the same field as a list code, as ``custom:<text>``.
#: Only lists marked ``"allowCustom": true`` take one; units, countries and
#: the lists rules depend on do not. Such a choice shows as typed in every
#: language, and the engine treats it as not stated.
CUSTOM_PREFIX = "custom:"
CUSTOM_MAX_LENGTH = 60


def custom_text(code: str | None) -> str | None:
    """The typed text of a custom choice; None for a list code."""
    if code and code.startswith(CUSTOM_PREFIX):
        return code[len(CUSTOM_PREFIX):]
    return None


def is_custom(code: str | None) -> bool:
    return custom_text(code) is not None


def allows_custom(key: str) -> bool:
    return bool(get_list(key).get("allowCustom"))


def well_formed_custom(code: str) -> bool:
    """Text a person may type: one line, trimmed, single-spaced, no markup."""
    text = custom_text(code)
    if text is None or not 0 < len(text) <= CUSTOM_MAX_LENGTH:
        return False
    if text != " ".join(text.split()):
        return False
    return all(ch.isprintable() and ch not in "<>" for ch in text)


def is_valid(key: str, code: str | None) -> bool:
    """True when ``code`` is a member of the reference list, or a custom choice
    the list takes (None passes)."""
    if code is None:
        return True
    if code in valid_codes(key):
        return True
    return is_custom(code) and allows_custom(key) and well_formed_custom(code)


def get_item(key: str, code: str | None) -> dict[str, Any] | None:
    """The full reference entry for ``code``, or None.

    A custom choice on a list that takes one comes back as an entry of its
    own, labelled with its text, so labels resolve without special cases.
    """
    if code is None:
        return None
    for item in get_list(key)["items"]:
        if item["code"] == code:
            return item
    if is_valid(key, code) and is_custom(code):
        return {"code": code, "label": {"en": custom_text(code)}, "custom": True}
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
