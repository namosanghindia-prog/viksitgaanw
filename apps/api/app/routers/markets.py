"""Mandi prices, exchange rates, and government schemes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from .. import reference
from ..db import get_session
from ..models import Profile
from ..schemas import (
    FxManualInput,
    FxOut,
    PriceSummaryOut,
    SchemeApplicationInput,
    SchemeApplicationOut,
    SchemeOut,
)
from ..services import prices, schemes
from ..services.hierarchy import resolve_location
from ..services.profiles import get_owner
from .deps import fail, owner

router = APIRouter(tags=["markets"])


@router.get("/prices/{crop}", response_model=PriceSummaryOut)
def crop_prices(
    crop: str,
    days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(get_session),
) -> PriceSummaryOut:
    """Latest mandi prices for a crop, the owner's own state first."""
    if not reference.is_valid("crops", crop):
        raise fail(prices.PriceError(f"Unknown crop: {crop}", 404))
    me = get_owner(session)
    state_name = None
    if me and me.state_code:
        path = resolve_location(session, state_code=me.state_code)
        state_name = path.state.name if path.state else None
    return prices.summary(session, crop, state_name=state_name, days=days)


@router.post("/prices/import", status_code=status.HTTP_201_CREATED)
async def import_prices(request: Request, session: Session = Depends(get_session)) -> dict[str, int]:
    """Import an Agmarknet CSV (the body is the file)."""
    text = (await request.body()).decode("utf-8-sig", errors="replace")
    count = prices.import_csv(session, text)
    session.commit()
    return {"imported": count}


@router.post("/prices/fetch", status_code=status.HTTP_201_CREATED)
def fetch_prices(
    state: str | None = Query(default=None), session: Session = Depends(get_session)
) -> dict[str, int]:
    """Pull today's prices from data.gov.in; needs VG_DATA_GOV_API_KEY."""
    try:
        count = prices.fetch_agmarknet(session, state=state)
    except prices.PriceError as exc:
        raise fail(exc) from exc
    session.commit()
    return {"imported": count}


@router.get("/fx", response_model=FxOut)
def fx_rates(session: Session = Depends(get_session)) -> FxOut:
    return prices.rates(session)


@router.post("/fx/refresh", response_model=FxOut)
def refresh_fx(session: Session = Depends(get_session)) -> FxOut:
    result = prices.refresh_rates(session)
    session.commit()
    return result


@router.put("/fx/{currency}", response_model=FxOut)
def set_fx(currency: str, payload: FxManualInput, session: Session = Depends(get_session)) -> FxOut:
    try:
        result = prices.set_manual(session, currency, payload.inr_per_unit)
    except prices.PriceError as exc:
        raise fail(exc) from exc
    session.commit()
    return result


@router.delete("/fx/{currency}", response_model=FxOut)
def clear_fx(currency: str, session: Session = Depends(get_session)) -> FxOut:
    result = prices.clear_manual(session, currency)
    session.commit()
    return result


@router.get("/schemes", response_model=list[SchemeOut])
def list_schemes(me: Profile = Depends(owner), session: Session = Depends(get_session)) -> list[SchemeOut]:
    """Schemes with the owner's likely eligibility, applications first."""
    return schemes.for_owner(session, me)


@router.put("/schemes/{code}/application", response_model=SchemeApplicationOut)
def save_application(
    code: str, payload: SchemeApplicationInput, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> SchemeApplicationOut:
    try:
        result = schemes.save_application(session, me, code, payload)
    except schemes.SchemeError as exc:
        raise fail(exc) from exc
    session.commit()
    return result


@router.delete("/schemes/{code}/application", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(code: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> None:
    try:
        schemes.delete_application(session, me, code)
    except schemes.SchemeError as exc:
        raise fail(exc) from exc
    session.commit()
