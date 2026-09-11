"""Checking the owner's identity, through the sync server."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Profile
from ..schemas import KycOut, KycStartInput, KycStartOut
from ..services import kyc
from ..services.kyc import KycError
from .deps import fail, owner

router = APIRouter(prefix="/kyc", tags=["kyc"])


@router.get("", response_model=KycOut)
def status(_: Profile = Depends(owner), session: Session = Depends(get_session)) -> KycOut:
    """The owner's identity check, and the checks they can take."""
    result = kyc.status(session)
    session.commit()
    return result


@router.post("/start", response_model=KycStartOut, status_code=201)
def start(payload: KycStartInput, _: Profile = Depends(owner), session: Session = Depends(get_session)) -> KycStartOut:
    """An address to open in the browser, where the owner signs in and agrees."""
    try:
        result = kyc.start(session, payload.method)
    except KycError as exc:
        session.commit()  # keep the device's registration, and anything a sync just did
        raise fail(exc) from exc
    session.commit()
    return result
