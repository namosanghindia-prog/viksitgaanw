"""Turning cloud sync on and off, and running it."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_session
from ..schemas import SyncConfigInput, SyncRunOut, SyncStatusOut
from ..services import kyc, promotion, subscription, sync_client, videos
from .deps import fail

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/status", response_model=SyncStatusOut)
def sync_status(session: Session = Depends(get_session)) -> SyncStatusOut:
    return sync_client.status(session)


@router.put("/config", response_model=SyncStatusOut)
def configure(payload: SyncConfigInput, session: Session = Depends(get_session)) -> SyncStatusOut:
    """Set the sync server address, or clear it to switch sync off."""
    result = sync_client.configure(session, payload.server_url)
    session.commit()
    return result


@router.post("/run", response_model=SyncRunOut)
def run(session: Session = Depends(get_session)) -> SyncRunOut:
    """Push what is shared and pull what others shared, once."""
    try:
        result = sync_client.run(session)
    except sync_client.SyncError as exc:
        session.commit()  # keep last_error
        raise fail(exc) from exc
    session.commit()
    # Online again: carry on with any video still on its way to Mux, and see
    # whether a payment or an identity check finished since the app last looked.
    videos.kick()
    subscription.check_pending(session)
    kyc.check_pending(session)
    try:
        promotion.refresh(session)  # one the operator granted since
    except subscription.SubscriptionError:
        pass  # offline again, or an older server: next time
    session.commit()
    return SyncRunOut(
        pushed=result.pushed, pulled=result.pulled, errors=result.errors, status=sync_client.status(session)
    )
