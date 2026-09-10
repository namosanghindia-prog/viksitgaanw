"""The device owner's profile.

Singular on purpose: ``/profile`` is *this device's* profile. Other people's
profiles only ever appear as cards inside a request or an interest, with
their contact details held back until a farmer accepts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..schemas import ProfileInput, ProfileOut
from ..services.profiles import (
    NoProfileError,
    ProfileExistsError,
    SegmentChangeError,
    create_owner,
    delete_owner,
    get_owner,
    place_error,
    replace_owner,
    serialise_owner,
)

router = APIRouter(prefix="/profile", tags=["profile"])


def _check_places(session: Session, payload: ProfileInput) -> None:
    error = place_error(session, payload)
    if error:
        raise HTTPException(status_code=422, detail=error)


@router.get("", response_model=ProfileOut | None)
def get_profile(session: Session = Depends(get_session)) -> ProfileOut | None:
    """The owner's profile, or ``null`` before onboarding."""
    owner = get_owner(session)
    return serialise_owner(session, owner) if owner else None


@router.post("", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: ProfileInput, session: Session = Depends(get_session)
) -> ProfileOut:
    _check_places(session, payload)
    try:
        profile = create_owner(session, payload)
    except ProfileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(profile)
    return serialise_owner(session, profile)


@router.put("", response_model=ProfileOut)
def replace_profile(
    payload: ProfileInput, session: Session = Depends(get_session)
) -> ProfileOut:
    """Replace the whole profile. The form always holds every field, and
    validating the whole thing is simpler to trust than merging a patch into
    segment-specific details."""
    _check_places(session, payload)
    try:
        profile = replace_owner(session, payload)
    except NoProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SegmentChangeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(profile)
    return serialise_owner(session, profile)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def remove_profile(session: Session = Depends(get_session)) -> None:
    try:
        delete_owner(session)
    except NoProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
