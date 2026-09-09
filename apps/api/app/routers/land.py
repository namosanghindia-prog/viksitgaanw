"""Land parcel CRUD.

Every write here is local-first: it commits to SQLite, appends an event, and
drops an entry in the sync outbox. Nothing blocks on the network.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import District, LandParcel, State, SubDistrict, Village
from ..schemas import LandParcelCreate, LandParcelOut, LandParcelUpdate
from ..services.area import UnknownAreaUnitError, hectares_to_acres, to_hectares
from ..services.events import EventType, enqueue_sync, record_event
from ..services.farmers import get_or_create_default_farmer
from ..services.hierarchy import resolve_location

router = APIRouter(prefix="/land-parcels", tags=["land"])

ENTITY = "land_parcel"


def _serialise(session: Session, parcel: LandParcel) -> LandParcelOut:
    return LandParcelOut(
        id=parcel.id,
        farmer_id=parcel.farmer_id,
        label=parcel.label,
        state_code=parcel.state_code,
        district_code=parcel.district_code,
        subdistrict_code=parcel.subdistrict_code,
        village_code=parcel.village_code,
        survey_number=parcel.survey_number,
        ownership_type=parcel.ownership_type,
        area_value=parcel.area_value,
        area_unit=parcel.area_unit,
        area_hectares=parcel.area_hectares,
        area_acres=hectares_to_acres(parcel.area_hectares),
        soil_type=parcel.soil_type,
        water_sources=parcel.water_sources or [],
        irrigation_type=parcel.irrigation_type,
        existing_crops=parcel.existing_crops or [],
        latitude=parcel.latitude,
        longitude=parcel.longitude,
        notes=parcel.notes,
        location=resolve_location(
            session,
            village_code=parcel.village_code,
            subdistrict_code=parcel.subdistrict_code,
            district_code=parcel.district_code,
            state_code=parcel.state_code,
        ),
        sync_state=parcel.sync_state,
        created_at=parcel.created_at,
        updated_at=parcel.updated_at,
    )


def _validate_location(session: Session, payload: LandParcelCreate) -> None:
    """Reject codes that are not in the imported LGD dataset.

    A parcel whose district code does not exist would produce a project report
    no bank could verify, so this fails loudly rather than storing it.
    """
    if session.get(State, payload.state_code) is None:
        raise HTTPException(
            status_code=422, detail=f"Unknown state code: {payload.state_code}"
        )

    district = session.get(District, payload.district_code)
    if district is None:
        raise HTTPException(
            status_code=422, detail=f"Unknown district code: {payload.district_code}"
        )
    if district.state_code != payload.state_code:
        raise HTTPException(
            status_code=422,
            detail=f"District {payload.district_code} does not belong to state {payload.state_code}.",
        )

    if payload.subdistrict_code:
        subdistrict = session.get(SubDistrict, payload.subdistrict_code)
        if subdistrict is None:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown sub-district code: {payload.subdistrict_code}",
            )
        if subdistrict.district_code != payload.district_code:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Sub-district {payload.subdistrict_code} does not belong to "
                    f"district {payload.district_code}."
                ),
            )

    if payload.village_code:
        if not payload.subdistrict_code:
            raise HTTPException(
                status_code=422,
                detail="A village cannot be set without its sub-district.",
            )
        village = session.get(Village, payload.village_code)
        if village is None:
            raise HTTPException(
                status_code=422, detail=f"Unknown village code: {payload.village_code}"
            )
        if village.subdistrict_code != payload.subdistrict_code:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Village {payload.village_code} does not belong to "
                    f"sub-district {payload.subdistrict_code}."
                ),
            )


@router.post("", response_model=LandParcelOut, status_code=status.HTTP_201_CREATED)
def create_parcel(
    payload: LandParcelCreate,
    session: Session = Depends(get_session),
) -> LandParcelOut:
    _validate_location(session, payload)

    try:
        hectares = to_hectares(payload.area_value, payload.area_unit)
    except UnknownAreaUnitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    farmer = get_or_create_default_farmer(session)

    parcel = LandParcel(
        farmer_id=payload.farmer_id or farmer.id,
        label=payload.label.strip(),
        state_code=payload.state_code,
        district_code=payload.district_code,
        subdistrict_code=payload.subdistrict_code,
        village_code=payload.village_code,
        survey_number=payload.survey_number,
        ownership_type=payload.ownership_type,
        area_value=payload.area_value,
        area_unit=payload.area_unit,
        area_hectares=hectares,
        soil_type=payload.soil_type,
        water_sources=payload.water_sources,
        irrigation_type=payload.irrigation_type,
        existing_crops=payload.existing_crops,
        latitude=payload.latitude,
        longitude=payload.longitude,
        notes=payload.notes,
        sync_state="local_only",
    )
    session.add(parcel)
    session.flush()

    record_event(
        session,
        EventType.PARCEL_CREATED,
        entity_type=ENTITY,
        entity_id=parcel.id,
        payload={
            "state_code": parcel.state_code,
            "district_code": parcel.district_code,
            "area_hectares": parcel.area_hectares,
        },
    )
    enqueue_sync(session, entity_type=ENTITY, entity_id=parcel.id, operation="create")
    session.commit()
    session.refresh(parcel)
    return _serialise(session, parcel)


@router.get("", response_model=list[LandParcelOut])
def list_parcels(
    farmer_id: str | None = Query(default=None, alias="farmerId"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[LandParcelOut]:
    stmt = select(LandParcel).order_by(LandParcel.created_at.desc())
    if farmer_id:
        stmt = stmt.where(LandParcel.farmer_id == farmer_id)
    stmt = stmt.limit(limit).offset(offset)
    return [_serialise(session, parcel) for parcel in session.scalars(stmt)]


@router.get("/{parcel_id}", response_model=LandParcelOut)
def get_parcel(parcel_id: str, session: Session = Depends(get_session)) -> LandParcelOut:
    parcel = session.get(LandParcel, parcel_id)
    if parcel is None:
        raise HTTPException(status_code=404, detail="Land parcel not found.")
    return _serialise(session, parcel)


@router.patch("/{parcel_id}", response_model=LandParcelOut)
def update_parcel(
    parcel_id: str,
    payload: LandParcelUpdate,
    session: Session = Depends(get_session),
) -> LandParcelOut:
    parcel = session.get(LandParcel, parcel_id)
    if parcel is None:
        raise HTTPException(status_code=404, detail="Land parcel not found.")

    changes = payload.model_dump(exclude_unset=True, by_alias=False)
    for field, value in changes.items():
        setattr(parcel, field, value)

    # Area value and unit can move independently, so recompute from whatever
    # the parcel holds after the patch is applied.
    if "area_value" in changes or "area_unit" in changes:
        try:
            parcel.area_hectares = to_hectares(parcel.area_value, parcel.area_unit)
        except UnknownAreaUnitError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if parcel.sync_state == "synced":
        parcel.sync_state = "queued"

    record_event(
        session,
        EventType.PARCEL_UPDATED,
        entity_type=ENTITY,
        entity_id=parcel.id,
        payload={"fields": sorted(changes.keys())},
    )
    enqueue_sync(session, entity_type=ENTITY, entity_id=parcel.id, operation="update")
    session.commit()
    session.refresh(parcel)
    return _serialise(session, parcel)


@router.delete("/{parcel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_parcel(parcel_id: str, session: Session = Depends(get_session)) -> None:
    parcel = session.get(LandParcel, parcel_id)
    if parcel is None:
        raise HTTPException(status_code=404, detail="Land parcel not found.")

    # The queue entry is written before the row goes, so the cloud copy can
    # still be reconciled after a local delete.
    enqueue_sync(session, entity_type=ENTITY, entity_id=parcel.id, operation="delete")
    record_event(
        session,
        EventType.PARCEL_DELETED,
        entity_type=ENTITY,
        entity_id=parcel.id,
        payload={"label": parcel.label},
    )
    session.delete(parcel)
    session.commit()
