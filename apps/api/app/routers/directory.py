"""Find investors (for farmers), find farmers (for investors), and project invites."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Profile, ProjectInvite
from ..schemas import (
    FarmerListingOut,
    InvestorListingOut,
    ProjectInviteAnswer,
    ProjectInviteInput,
    ProjectInviteOut,
)
from ..services import directory
from ..services.directory import DirectoryError
from .deps import fail, owner

router = APIRouter(prefix="/directory", tags=["directory"])


@router.get("/investors", response_model=list[InvestorListingOut])
def find_investors(
    state_code: str | None = Query(default=None, alias="stateCode"),
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> list[InvestorListingOut]:
    """Investors and investing partners who shared their profile, best match first."""
    try:
        return directory.investors(session, me, state_code=state_code)
    except DirectoryError as exc:
        raise fail(exc) from exc


@router.get("/farmers", response_model=list[FarmerListingOut])
def find_farmers(
    state_code: str | None = Query(default=None, alias="stateCode"),
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> list[FarmerListingOut]:
    """Farmers who shared their profile, with the projects the viewer may see."""
    try:
        return directory.farmers(session, me, state_code=state_code)
    except DirectoryError as exc:
        raise fail(exc) from exc


@router.post("/investors/{profile_id}/invite", response_model=ProjectInviteOut, status_code=status.HTTP_201_CREATED)
def send_project(
    profile_id: str,
    payload: ProjectInviteInput,
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> ProjectInviteOut:
    """Put one of the farmer's shared projects in front of an investor."""
    try:
        row = directory.invite(session, me, profile_id, payload)
    except DirectoryError as exc:
        raise fail(exc) from exc
    session.commit()
    return directory.serialise(session, me, row)


@router.get("/invites", response_model=list[ProjectInviteOut])
def list_invites(me: Profile = Depends(owner), session: Session = Depends(get_session)) -> list[ProjectInviteOut]:
    """Projects the owner sent, or was sent."""
    return directory.invites_for(session, me)


@router.patch("/invites/{invite_id}", response_model=ProjectInviteOut)
def answer_invite(
    invite_id: str,
    payload: ProjectInviteAnswer,
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> ProjectInviteOut:
    """The investor is not interested. (Interested means sending an interest.)"""
    row = session.get(ProjectInvite, invite_id)
    if row is None or me.id not in (row.farmer_profile_id, row.investor_profile_id):
        raise HTTPException(status_code=404, detail="Invite not found.")
    try:
        directory.decline(session, me, row)
    except DirectoryError as exc:
        raise fail(exc) from exc
    session.commit()
    return directory.serialise(session, me, row)
