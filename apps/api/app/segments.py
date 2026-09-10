"""The six kinds of people who use ViksitGaanw, and what each may do.

The codes match ``packages/shared/reference/user-segments.json``. Grouping
them here keeps the permission rules in one readable place instead of
scattered string comparisons across routers.
"""

from __future__ import annotations

from typing import Literal

Segment = Literal[
    "farmer",
    "investor_india",
    "investor_international",
    "partner_national",
    "partner_international",
    "government",
]

FARMER = "farmer"
GOVERNMENT = "government"

INVESTORS: tuple[str, ...] = ("investor_india", "investor_international")
PARTNERS: tuple[str, ...] = ("partner_national", "partner_international")

#: Segments that answer a farmer's request.
RESPONDERS: tuple[str, ...] = INVESTORS + PARTNERS

#: Segments a farmer may show a request to. Government is there so a block
#: officer can help with schemes -- but only if the farmer ticks the box.
AUDIENCES: tuple[str, ...] = RESPONDERS + (GOVERNMENT,)

#: Segments based outside India. Everyone else must be in India.
INTERNATIONAL: tuple[str, ...] = ("investor_international", "partner_international")

#: Investor types for which an organisation name makes no sense.
PERSONAL_INVESTOR_TYPES: frozenset[str] = frozenset({"individual", "angel", "nri"})


def interest_kind(segment: str) -> str:
    """What a responder in ``segment`` offers: money, or a working partnership."""
    return "investment" if segment in INVESTORS else "partnership"
