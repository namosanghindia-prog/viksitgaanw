"""Position endpoints.

The browser's own geolocation is tried first by the frontend, because on a
phone it is both the most accurate and the most private. These endpoints exist
because that call cannot work inside the Electron desktop shell -- Chromium
resolves position through a Google service that needs an API key the build does
not carry -- and because a farmer pressing "find my field" deserves an answer
rather than a silent failure.

Nothing here runs on its own. Every call is the direct result of the farmer
pressing a button, and the response says which provider answered so the screen
can be honest about the accuracy.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..schemas import GeoFixOut, GeoLocateOut, PlaceSuggestionOut
from ..services import geolocation
from ..services.place_matching import match_place

logger = logging.getLogger("viksitgaanw.geo")

router = APIRouter(prefix="/geo", tags=["geo"])


def _fix_out(fix: geolocation.Fix) -> GeoFixOut:
    return GeoFixOut(
        latitude=fix.latitude,
        longitude=fix.longitude,
        accuracy_metres=fix.accuracy_metres,
        source=fix.source,
        label=fix.label,
        attribution=fix.attribution,
    )


def _suggest(
    session: Session,
    latitude: float,
    longitude: float,
    *,
    allow_network: bool,
) -> PlaceSuggestionOut | None:
    """Turn a coordinate into an LGD suggestion, online if allowed."""
    place = geolocation.reverse_online(latitude, longitude) if allow_network else None
    if place is None:
        place = geolocation.reverse_offline(latitude, longitude)
    if place is None:
        return None

    # The offline path only knows the state, so hand its guess in as a hint
    # rather than as a name to match.
    hint = None
    if place.source == "offline_bbox":
        guess = geolocation.state_for_point(latitude, longitude)
        hint = guess[0] if guess else None

    match = match_place(
        session,
        state=place.state if place.source != "offline_bbox" else None,
        district=place.district,
        subdistrict=place.subdistrict,
        state_code_hint=hint,
    )
    if match.is_empty:
        return None

    # A suggestion can never be more trustworthy than the weaker of the two
    # steps behind it: the geocoding, and the name match onto the LGD.
    rank = {"high": 0, "medium": 1, "low": 2}
    confidence = max((match.confidence, place.confidence), key=lambda level: rank[level])

    return PlaceSuggestionOut(
        state_code=match.state_code,
        state_name=match.state_name,
        district_code=match.district_code,
        district_name=match.district_name,
        subdistrict_code=match.subdistrict_code,
        subdistrict_name=match.subdistrict_name,
        confidence=confidence,
        display_name=place.display_name,
        source=place.source,
        attribution=place.attribution,
    )


@router.get("/locate", response_model=GeoLocateOut)
def locate(
    state_code: str | None = Query(default=None, alias="stateCode"),
    allow_network: bool = Query(default=True, alias="allowNetwork"),
    resolve_place: bool = Query(default=True, alias="resolvePlace"),
    session: Session = Depends(get_session),
) -> GeoLocateOut:
    """Find the device's position, falling back until something answers.

    ``stateCode`` is the state the farmer has already chosen in the selector.
    It is the last-resort fallback and the reason this endpoint can always
    answer once the cascading selector has been used at all.
    """
    settings = get_settings()
    networked = allow_network and settings.allow_network

    tried: list[str] = []

    fix = geolocation.os_fix()
    if fix is None:
        tried.append("os_location")
        if networked:
            fix = geolocation.network_fix()
            if fix is None:
                tried.append("network_ip")
    if fix is None:
        fix = geolocation.state_centroid(state_code)
        if fix is None:
            tried.append("admin_centroid")
            raise HTTPException(
                status_code=404,
                detail=(
                    "No position could be found on this device. Choose your state "
                    "first, or tap your field on the map."
                ),
            )

    place = None
    if resolve_place and fix.source != "admin_centroid":
        try:
            place = _suggest(
                session, fix.latitude, fix.longitude, allow_network=networked
            )
        except Exception:  # pragma: no cover - a suggestion is never essential
            logger.exception("Place suggestion failed; returning the fix alone")

    return GeoLocateOut(fix=_fix_out(fix), place=place, tried=tried)


@router.get("/reverse", response_model=PlaceSuggestionOut)
def reverse(
    latitude: float = Query(alias="lat", ge=-90, le=90),
    longitude: float = Query(alias="lon", ge=-180, le=180),
    allow_network: bool = Query(default=True, alias="allowNetwork"),
    session: Session = Depends(get_session),
) -> PlaceSuggestionOut:
    """Suggest the LGD location for a pin the farmer dropped by hand."""
    settings = get_settings()
    place = _suggest(
        session,
        latitude,
        longitude,
        allow_network=allow_network and settings.allow_network,
    )
    if place is None:
        raise HTTPException(
            status_code=404,
            detail="That point could not be matched to a district in the LGD dataset.",
        )
    return place
