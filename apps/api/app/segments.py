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
#: Other farmers see it on the common timeline, read-only, if chosen.
AUDIENCES: tuple[str, ...] = RESPONDERS + (GOVERNMENT, FARMER)

#: Agriculture organisations that sell or rent out machines and build a
#: partner network of farmers, villages, districts and distributors.
EQUIPMENT_SELLERS: tuple[str, ...] = PARTNERS

#: Segments based outside India. Everyone else must be in India.
INTERNATIONAL: tuple[str, ...] = ("investor_international", "partner_international")

#: Investor types for which an organisation name makes no sense.
PERSONAL_INVESTOR_TYPES: frozenset[str] = frozenset({"individual", "angel", "nri"})


def interest_kinds(segment: str, details: dict | None = None) -> tuple[str, ...]:
    """What a responder in ``segment`` may offer.

    Investors offer money. Partner organisations offer a working partnership,
    and money too if their profile says they also invest -- a device holds one
    profile, so an agri-company that partners farmers and funds them should
    not need two.
    """
    if segment in INVESTORS:
        return ("investment",)
    if segment in PARTNERS:
        if (details or {}).get("also_invests"):
            return ("partnership", "investment")
        return ("partnership",)
    return ()
