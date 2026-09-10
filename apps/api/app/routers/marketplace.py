"""Investment requests and interests.

Every call acts as the device owner. There is no ``profileId`` parameter to
spoof: the API listens on loopback only, and the owner is whoever this device
belongs to.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import InvestmentInterest, InvestmentRequest, Profile
from ..schemas import (
    InterestInput,
    InterestUpdate,
    InvestmentRequestInput,
    InvestmentRequestOut,
    InvestmentRequestUpdate,
)
from ..services import marketplace, sharing
from ..services.marketplace import MarketplaceError
from ..services.profiles import get_owner

router = APIRouter(tags=["marketplace"])


def _owner(session: Session) -> Profile:
    owner = get_owner(session)
    if owner is None:
        raise HTTPException(status_code=409, detail="Set up your profile first.")
    return owner


def _request_or_404(session: Session, request_id: str, viewer: Profile) -> InvestmentRequest:
    request = session.get(InvestmentRequest, request_id)
    # A request the viewer may not see is reported as missing, not forbidden:
    # its existence is itself something the farmer did not choose to share.
    if request is None or not marketplace.visible_to(request, viewer):
        raise HTTPException(status_code=404, detail="Request not found.")
    return request


def _fail(error: MarketplaceError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=str(error))


@router.post(
    "/investment-requests",
    response_model=InvestmentRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def create_request(
    payload: InvestmentRequestInput, session: Session = Depends(get_session)
) -> InvestmentRequestOut:
    owner = _owner(session)
    try:
        request = marketplace.create_request(session, owner, payload)
    except MarketplaceError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(request)
    return marketplace.serialise_request(session, request, owner)


@router.get("/investment-requests", response_model=list[InvestmentRequestOut])
def browse_requests(
    state_code: str | None = Query(default=None, alias="stateCode"),
    kind: str | None = Query(default=None),
    seeking: Literal["investment", "partnership"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[InvestmentRequestOut]:
    """Open requests shown to the owner's segment, best fit first."""
    owner = _owner(session)
    try:
        return marketplace.browse(
            session, owner, state_code=state_code, kind=kind, seeking=seeking, limit=limit
        )
    except MarketplaceError as exc:
        raise _fail(exc) from exc


@router.get("/investment-requests/mine", response_model=list[InvestmentRequestOut])
def my_requests(session: Session = Depends(get_session)) -> list[InvestmentRequestOut]:
    return marketplace.my_requests(session, _owner(session))


@router.get("/investment-requests/{request_id}", response_model=InvestmentRequestOut)
def get_request(request_id: str, session: Session = Depends(get_session)) -> InvestmentRequestOut:
    owner = _owner(session)
    return marketplace.serialise_request(
        session, _request_or_404(session, request_id, owner), owner
    )


@router.patch("/investment-requests/{request_id}", response_model=InvestmentRequestOut)
def update_request(
    request_id: str,
    payload: InvestmentRequestUpdate,
    session: Session = Depends(get_session),
) -> InvestmentRequestOut:
    owner = _owner(session)
    request = _request_or_404(session, request_id, owner)
    try:
        marketplace.update_request(session, owner, request, payload)
    except MarketplaceError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(request)
    return marketplace.serialise_request(session, request, owner)


@router.post("/investment-requests/{request_id}/share", response_model=InvestmentRequestOut)
def share_request(request_id: str, session: Session = Depends(get_session)) -> InvestmentRequestOut:
    """Put a draft request on the common timeline for the audiences it names."""
    owner = _owner(session)
    request = _request_or_404(session, request_id, owner)
    try:
        sharing.share_item(session, owner, request)
    except sharing.SharingError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    session.commit()
    session.refresh(request)
    return marketplace.serialise_request(session, request, owner)


@router.post("/investment-requests/{request_id}/unshare", response_model=InvestmentRequestOut)
def unshare_request(request_id: str, session: Session = Depends(get_session)) -> InvestmentRequestOut:
    owner = _owner(session)
    request = _request_or_404(session, request_id, owner)
    try:
        sharing.unshare_item(session, owner, request)
    except sharing.SharingError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    session.commit()
    session.refresh(request)
    return marketplace.serialise_request(session, request, owner)


@router.post(
    "/investment-requests/{request_id}/interests",
    response_model=InvestmentRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def send_interest(
    request_id: str,
    payload: InterestInput,
    session: Session = Depends(get_session),
) -> InvestmentRequestOut:
    """Answer a request. Sending again before the farmer replies updates the
    terms rather than stacking a second interest."""
    owner = _owner(session)
    request = _request_or_404(session, request_id, owner)
    try:
        marketplace.send_interest(session, owner, request, payload)
    except MarketplaceError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(request)
    return marketplace.serialise_request(session, request, owner)


@router.get("/investment-interests/mine", response_model=list[InvestmentRequestOut])
def my_interests(session: Session = Depends(get_session)) -> list[InvestmentRequestOut]:
    """Requests the owner has answered, each carrying ``myInterest``."""
    return marketplace.my_interests(session, _owner(session))


@router.patch("/investment-interests/{interest_id}", response_model=InvestmentRequestOut)
def respond_to_interest(
    interest_id: str,
    payload: InterestUpdate,
    session: Session = Depends(get_session),
) -> InvestmentRequestOut:
    owner = _owner(session)
    interest = session.get(InvestmentInterest, interest_id)
    if interest is None or owner.id not in (interest.profile_id, interest.request.profile_id):
        raise HTTPException(status_code=404, detail="Interest not found.")
    try:
        marketplace.respond(session, owner, interest, payload.status)
    except MarketplaceError as exc:
        raise _fail(exc) from exc
    session.commit()
    request = interest.request
    session.refresh(request)
    return marketplace.serialise_request(session, request, owner)
