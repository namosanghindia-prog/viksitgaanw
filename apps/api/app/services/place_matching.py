"""Matching reverse-geocoded place names onto the LGD hierarchy.

OpenStreetMap and the Local Government Directory disagree constantly about
spelling -- "Varanasi" against "Varanasi", but also "Pindra" against "PINDRA",
"Kanpur Nagar" against "Kanpur (Nagar)", "Bengaluru Urban" against "Bangalore
Urban". So a name that comes back from reverse geocoding is normalised the same
way the importer normalised the dataset, then compared, and only accepted above
a confidence floor.

Nothing here decides anything on the farmer's behalf. It returns a *suggestion*
that the location selector offers to fill in, which the farmer confirms or
ignores. A district silently guessed wrong would put a wrong address on a bank
document, so the confidence is always carried through to the screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import District, State, SubDistrict
from .text import normalise_name

Confidence = Literal["high", "medium", "low"]

#: Below this the two names are treated as different places. Set deliberately
#: high: a wrong district is worse than no suggestion at all.
_ACCEPT_RATIO = 0.82

#: A sub-district match is allowed to be looser, because OSM frequently returns
#: the tehsil headquarters town rather than the tehsil name.
_ACCEPT_RATIO_SUBDISTRICT = 0.75


@dataclass(frozen=True)
class PlaceMatch:
    state_code: str | None = None
    state_name: str | None = None
    district_code: str | None = None
    district_name: str | None = None
    subdistrict_code: str | None = None
    subdistrict_name: str | None = None
    confidence: Confidence = "low"

    @property
    def is_empty(self) -> bool:
        return self.state_code is None


def _similarity(left: str, right: str) -> float:
    """How alike two already-normalised place names are, 0 to 1."""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    # A dataset name often carries a qualifier the map does not, as in
    # "kanpur nagar" against "kanpur". Containment is a strong signal there.
    if left in right or right in left:
        shorter, longer = sorted((left, right), key=len)
        return max(0.85, len(shorter) / len(longer))
    return SequenceMatcher(None, left, right).ratio()


def _best(candidates: list[tuple[str, str]], name: str, floor: float):
    """Pick the closest (code, name) pair to ``name``, or None."""
    target = normalise_name(name)
    if not target:
        return None, 0.0
    best_row, best_score = None, 0.0
    for code, candidate in candidates:
        score = _similarity(target, normalise_name(candidate))
        if score > best_score:
            best_row, best_score = (code, candidate), score
    if best_row is None or best_score < floor:
        return None, best_score
    return best_row, best_score


def match_place(
    session: Session,
    *,
    state: str | None,
    district: str | None = None,
    subdistrict: str | None = None,
    state_code_hint: str | None = None,
) -> PlaceMatch:
    """Resolve place names to LGD codes, as far down as the names allow.

    ``state_code_hint`` lets a caller supply the state from the offline
    bounding boxes when reverse geocoding produced no state name of its own.
    """
    scores: list[float] = []

    state_row = None
    if state:
        candidates = [
            (row.code, row.name)
            for row in session.scalars(select(State).where(State.is_active.is_(True)))
        ]
        match, score = _best(candidates, state, _ACCEPT_RATIO)
        if match:
            state_row = match
            scores.append(score)

    if state_row is None and state_code_hint:
        row = session.get(State, state_code_hint)
        if row is not None:
            state_row = (row.code, row.name)
            # A bounding-box guess is worth far less than a name match, and the
            # overall confidence has to reflect that.
            scores.append(0.5)

    if state_row is None:
        return PlaceMatch()

    district_row = None
    if district:
        candidates = [
            (row.code, row.name)
            for row in session.scalars(
                select(District).where(
                    District.state_code == state_row[0], District.is_active.is_(True)
                )
            )
        ]
        match, score = _best(candidates, district, _ACCEPT_RATIO)
        if match:
            district_row = match
            scores.append(score)

    subdistrict_row = None
    if district_row is not None and subdistrict:
        candidates = [
            (row.code, row.name)
            for row in session.scalars(
                select(SubDistrict).where(
                    SubDistrict.district_code == district_row[0],
                    SubDistrict.is_active.is_(True),
                )
            )
        ]
        match, score = _best(candidates, subdistrict, _ACCEPT_RATIO_SUBDISTRICT)
        if match:
            subdistrict_row = match
            scores.append(score)

    average = sum(scores) / len(scores) if scores else 0.0
    if district_row is not None and average >= 0.9:
        confidence: Confidence = "high"
    elif district_row is not None:
        confidence = "medium"
    else:
        confidence = "low"

    return PlaceMatch(
        state_code=state_row[0],
        state_name=state_row[1],
        district_code=district_row[0] if district_row else None,
        district_name=district_row[1] if district_row else None,
        subdistrict_code=subdistrict_row[0] if subdistrict_row else None,
        subdistrict_name=subdistrict_row[1] if subdistrict_row else None,
        confidence=confidence,
    )
