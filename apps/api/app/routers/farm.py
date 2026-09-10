"""The farm itself: diary, traceability records, weather."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import DiaryEntry, LandParcel
from ..schemas import DiaryInput, DiaryOut, DiarySummaryOut, WeatherOut
from ..services import diary, media, notify, weather
from ..services.diary import DiaryError
from ..services.profiles import get_owner
from .deps import fail

router = APIRouter(tags=["farm"])


def _parcel(session: Session, parcel_id: str) -> LandParcel:
    try:
        return diary.owned_parcel(session, get_owner(session), parcel_id)
    except DiaryError as exc:
        raise fail(exc) from exc


def _entry(session: Session, entry_id: str) -> DiaryEntry:
    entry = session.get(DiaryEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Diary entry not found.")
    _parcel(session, entry.parcel_id)
    return entry


@router.get("/land-parcels/{parcel_id}/diary", response_model=list[DiaryOut])
def list_diary(parcel_id: str, session: Session = Depends(get_session)) -> list[DiaryOut]:
    parcel = _parcel(session, parcel_id)
    return [diary.serialise(session, entry) for entry in diary.entries(session, parcel)]


@router.get("/land-parcels/{parcel_id}/diary/summary", response_model=DiarySummaryOut)
def diary_summary(parcel_id: str, session: Session = Depends(get_session)) -> DiarySummaryOut:
    return diary.summary(session, _parcel(session, parcel_id))


@router.post("/land-parcels/{parcel_id}/diary", response_model=DiaryOut, status_code=status.HTTP_201_CREATED)
def add_diary(parcel_id: str, payload: DiaryInput, session: Session = Depends(get_session)) -> DiaryOut:
    entry = diary.add(session, _parcel(session, parcel_id), payload)
    session.commit()
    return diary.serialise(session, entry)


@router.put("/diary/{entry_id}", response_model=DiaryOut)
def update_diary(entry_id: str, payload: DiaryInput, session: Session = Depends(get_session)) -> DiaryOut:
    entry = diary.update(session, _entry(session, entry_id), payload)
    session.commit()
    return diary.serialise(session, entry)


@router.delete("/diary/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_diary(entry_id: str, session: Session = Depends(get_session)) -> None:
    diary.remove(session, _entry(session, entry_id))
    session.commit()


@router.post("/diary/{entry_id}/photos", response_model=DiaryOut)
async def add_diary_photo(entry_id: str, request: Request, session: Session = Depends(get_session)) -> DiaryOut:
    entry = _entry(session, entry_id)
    data = await request.body()
    try:
        media.save(session, entity_type="diary", entity_id=entry.id, data=data,
                   content_type=request.headers.get("content-type"))
    except media.MediaError as exc:
        raise fail(exc) from exc
    session.commit()
    return diary.serialise(session, entry)


@router.get("/diary/{entry_id}/traceability.pdf")
def traceability(entry_id: str, session: Session = Depends(get_session)) -> Response:
    """The traceability record for one harvest lot, for a buyer."""
    entry = _entry(session, entry_id)
    try:
        pdf = diary.traceability_pdf(session, entry, get_owner(session))
    except DiaryError as exc:
        raise fail(exc) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{entry.lot_code or "lot"}.pdf"'},
    )


@router.get("/land-parcels/{parcel_id}/weather", response_model=WeatherOut)
def plot_weather(
    parcel_id: str, refresh: bool = Query(default=False), session: Session = Depends(get_session)
) -> WeatherOut:
    """Seven days for this plot, with what to do about it. Works offline from cache."""
    parcel = session.get(LandParcel, parcel_id)
    if parcel is None:
        raise HTTPException(status_code=404, detail="Land parcel not found.")
    result = weather.forecast(session, parcel, refresh=refresh)
    owner = get_owner(session)
    if owner is not None:
        for advisory in result.advisories:
            if advisory.severity == "alert":
                notify.notify(
                    session,
                    owner.id,
                    "weather_alert",
                    params={"code": advisory.code, "date": advisory.day.isoformat(), "plot": parcel.label},
                    link=f"/land/{parcel.id}/farm",
                    entity_type="weather",
                    entity_id=f"{parcel.id}:{advisory.code}:{advisory.day.isoformat()}",
                    once=True,
                )
    session.commit()
    return result
