"""Read-only endpoints over the imported LGD administrative hierarchy.

These back the cascading state -> district -> sub-district -> village selector.
Everything here answers from local SQLite, so it works with the device in
aeroplane mode.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..models import District, State, SubDistrict, Village
from ..schemas import AdminUnitOut, LocationPathOut
from ..services.hierarchy import UnknownLocationError, resolve_location
from ..services.hierarchy import to_admin_unit as _unit
from ..services.text import normalise_name

router = APIRouter(prefix="/locations", tags=["locations"])


def _page_size(limit: int) -> int:
    return min(limit, get_settings().max_page_size)


@router.get("/states", response_model=list[AdminUnitOut])
def list_states(
    q: str | None = Query(default=None, description="Optional name filter"),
    session: Session = Depends(get_session),
) -> list[AdminUnitOut]:
    stmt = select(State).where(State.is_active.is_(True)).order_by(State.name)
    if q:
        stmt = stmt.where(State.name_norm.like(f"%{normalise_name(q)}%"))
    return [_unit(row, "state", None) for row in session.scalars(stmt)]


@router.get("/districts", response_model=list[AdminUnitOut])
def list_districts(
    state_code: str = Query(alias="stateCode"),
    q: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[AdminUnitOut]:
    stmt = (
        select(District)
        .where(District.state_code == state_code, District.is_active.is_(True))
        .order_by(District.name)
    )
    if q:
        stmt = stmt.where(District.name_norm.like(f"%{normalise_name(q)}%"))
    return [_unit(row, "district", row.state_code) for row in session.scalars(stmt)]


@router.get("/subdistricts", response_model=list[AdminUnitOut])
def list_subdistricts(
    district_code: str = Query(alias="districtCode"),
    q: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[AdminUnitOut]:
    stmt = (
        select(SubDistrict)
        .where(SubDistrict.district_code == district_code, SubDistrict.is_active.is_(True))
        .order_by(SubDistrict.name)
    )
    if q:
        stmt = stmt.where(SubDistrict.name_norm.like(f"%{normalise_name(q)}%"))
    return [_unit(row, "subdistrict", row.district_code) for row in session.scalars(stmt)]


@router.get("/villages", response_model=list[AdminUnitOut])
def list_villages(
    subdistrict_code: str | None = Query(default=None, alias="subdistrictCode"),
    district_code: str | None = Query(default=None, alias="districtCode"),
    state_code: str | None = Query(default=None, alias="stateCode"),
    q: str | None = Query(default=None, description="Search-as-you-type on the village name"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[AdminUnitOut]:
    """List or search villages.

    At least one of ``subdistrictCode``, ``districtCode``, ``stateCode`` or a
    search term is required: the full table is ~660k rows and an unbounded
    listing would be useless on a low-end village laptop.
    """
    if not any([subdistrict_code, district_code, state_code, q]):
        raise HTTPException(
            status_code=422,
            detail="Provide subdistrictCode, districtCode, stateCode or a search term q.",
        )

    stmt = select(Village).where(Village.is_active.is_(True))
    if subdistrict_code:
        stmt = stmt.where(Village.subdistrict_code == subdistrict_code)
    if district_code:
        stmt = stmt.where(Village.district_code == district_code)
    if state_code:
        stmt = stmt.where(Village.state_code == state_code)

    if q:
        term = normalise_name(q)
        if term:
            # Prefix match on the whole name or on any word inside it. This
            # rides the (subdistrict_code, name_norm) index for the common
            # case where a sub-district is already chosen.
            stmt = stmt.where(
                or_(
                    Village.name_norm.like(f"{term}%"),
                    Village.name_norm.like(f"% {term}%"),
                )
            )

    stmt = stmt.order_by(Village.name).limit(_page_size(limit)).offset(offset)
    return [_unit(row, "village", row.subdistrict_code) for row in session.scalars(stmt)]


@router.get("/resolve", response_model=LocationPathOut)
def resolve_path(
    village_code: str | None = Query(default=None, alias="villageCode"),
    subdistrict_code: str | None = Query(default=None, alias="subdistrictCode"),
    district_code: str | None = Query(default=None, alias="districtCode"),
    state_code: str | None = Query(default=None, alias="stateCode"),
    session: Session = Depends(get_session),
) -> LocationPathOut:
    """Expand any code into the full state -> village chain.

    Used to render a stored parcel's location without the client keeping four
    separate lookups in sync.
    """
    if not any([village_code, subdistrict_code, district_code, state_code]):
        raise HTTPException(status_code=422, detail="Provide at least one location code.")
    try:
        return resolve_location(
            session,
            village_code=village_code,
            subdistrict_code=subdistrict_code,
            district_code=district_code,
            state_code=state_code,
            strict=True,
        )
    except UnknownLocationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
