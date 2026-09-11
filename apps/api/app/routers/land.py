"""Land parcel CRUD.

Every write here is local-first: it commits to SQLite, appends an event, and
drops an entry in the sync outbox. Nothing blocks on the network.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import LandParcel, MediaFile
from ..schemas import LandParcelCreate, LandParcelOut, LandParcelUpdate, MediaOut
from ..services import landshare, media
from ..services.landshare import ShareError
from ..services.profiles import get_owner
from ..services.sharing import SharingError
from ..services.area import UnknownAreaUnitError, hectares_to_acres, to_hectares
from ..services.depth import UnknownDepthUnitError
from ..services.depth import to_metres as depth_to_metres
from ..services.events import EventType, enqueue_sync, record_event
from ..services.farmers import get_or_create_default_farmer
from ..services.hierarchy import location_error, resolve_location

router = APIRouter(prefix="/land-parcels", tags=["land"])

ENTITY = "land_parcel"


def _serialise(session: Session, parcel: LandParcel) -> LandParcelOut:
    share = landshare.share_for(session, parcel.id)
    return LandParcelOut(
        share_visibility=share.visibility if share else "offline",
        shared_at=share.shared_at if share else None,
        photos=[
            MediaOut(id=f.id, url=media.url_for(f), width=f.width, height=f.height, position=f.position)
            for f in media.for_entity(session, "land", parcel.id)
        ],
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
        water_type=parcel.water_type,
        water_depth_value=parcel.water_depth_value,
        water_depth_unit=parcel.water_depth_unit,
        water_depth_metres=parcel.water_depth_metres,
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
    error = location_error(
        session,
        state_code=payload.state_code,
        district_code=payload.district_code,
        subdistrict_code=payload.subdistrict_code,
        village_code=payload.village_code,
    )
    if error:
        raise HTTPException(status_code=422, detail=error)


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

    try:
        depth_metres = (
            depth_to_metres(payload.water_depth_value, payload.water_depth_unit)
            if payload.water_depth_value is not None and payload.water_depth_unit
            else None
        )
    except UnknownDepthUnitError as exc:
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
        water_type=payload.water_type,
        water_depth_value=payload.water_depth_value,
        water_depth_unit=payload.water_depth_unit,
        water_depth_metres=depth_metres,
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

    # Depth and its unit can move independently too.
    if "water_depth_value" in changes or "water_depth_unit" in changes:
        if parcel.water_depth_value is None:
            parcel.water_depth_metres = None
        elif not parcel.water_depth_unit:
            raise HTTPException(
                status_code=422,
                detail="water_depth_unit is required when a depth is given.",
            )
        else:
            try:
                parcel.water_depth_metres = depth_to_metres(
                    parcel.water_depth_value, parcel.water_depth_unit
                )
            except UnknownDepthUnitError as exc:
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
    session.flush()
    landshare.refresh(session, parcel)
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
    landshare.forget_parcel(session, parcel.id)
    session.delete(parcel)
    session.commit()


# --------------------------------------------------------------------------- #
# Sharing with connections, and pictures of the plot
# --------------------------------------------------------------------------- #


def _owned(session: Session, parcel_id: str) -> LandParcel:
    owner = get_owner(session)
    if owner is None:
        raise HTTPException(status_code=409, detail="Set up your profile first.")
    try:
        return landshare.owned_parcel(session, owner, parcel_id)
    except ShareError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/{parcel_id}/share", response_model=LandParcelOut)
def share_parcel(parcel_id: str, session: Session = Depends(get_session)) -> LandParcelOut:
    """Show this plot to the owner's connections on the timeline."""
    parcel = _owned(session, parcel_id)
    try:
        landshare.share_land(session, get_owner(session), parcel)
    except (ShareError, SharingError) as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    session.commit()
    return _serialise(session, parcel)


@router.post("/{parcel_id}/unshare", response_model=LandParcelOut)
def unshare_parcel(parcel_id: str, session: Session = Depends(get_session)) -> LandParcelOut:
    parcel = _owned(session, parcel_id)
    landshare.unshare_land(session, get_owner(session), parcel)
    session.commit()
    return _serialise(session, parcel)


@router.post("/{parcel_id}/photos", response_model=LandParcelOut)
async def add_parcel_photo(parcel_id: str, request: Request, session: Session = Depends(get_session)) -> LandParcelOut:
    """A picture of the plot, shown on its card to connections once shared."""
    parcel = _owned(session, parcel_id)
    try:
        media.save(
            session, entity_type="land", entity_id=parcel.id,
            data=await request.body(), content_type=request.headers.get("content-type"),
        )
    except media.MediaError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    landshare.touch(session, parcel.id)
    session.commit()
    return _serialise(session, parcel)


@router.delete("/{parcel_id}/photos/{media_id}", response_model=LandParcelOut)
def delete_parcel_photo(parcel_id: str, media_id: str, session: Session = Depends(get_session)) -> LandParcelOut:
    parcel = _owned(session, parcel_id)
    file = session.get(MediaFile, media_id)
    if file is None or file.entity_type != "land" or file.entity_id != parcel.id:
        raise HTTPException(status_code=404, detail="Picture not found.")
    media.remove(session, file)
    landshare.touch(session, parcel.id)
    session.commit()
    return _serialise(session, parcel)
