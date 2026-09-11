"""The device owner's profile.

Singular on purpose: ``/profile`` is *this device's* profile. Other people's
profiles only ever appear as cards inside a request or an interest, with
their contact details held back until a farmer accepts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from .. import segments as seg
from ..db import get_session
from ..schemas import ProfileCardOut, ProfileInput, ProfileOut
from ..services import media
from ..services.profiles import (
    NoProfileError,
    ProfileExistsError,
    SegmentChangeError,
    card,
    create_owner,
    delete_owner,
    get_owner,
    known_profiles,
    place_error,
    replace_owner,
    serialise_owner,
    share_owner,
    unshare_owner,
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


@router.post("/share", response_model=ProfileOut)
def share_profile(session: Session = Depends(get_session)) -> ProfileOut:
    """Show the profile card on the common timeline. Contact stays private."""
    try:
        profile = share_owner(session)
    except NoProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return serialise_owner(session, profile)


@router.post("/unshare", response_model=ProfileOut)
def unshare_profile(session: Session = Depends(get_session)) -> ProfileOut:
    """Take the profile offline, with every project and machine shared under it."""
    try:
        profile = unshare_owner(session)
    except NoProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return serialise_owner(session, profile)


@router.put("/photo", response_model=ProfileOut)
async def upload_photo(request: Request, session: Session = Depends(get_session)) -> ProfileOut:
    """Set the profile photo or organisation logo.

    The body is the image itself (JPEG, PNG or WebP), not a form upload: the
    desktop app sends the file straight from the picker, and it spares the
    backend a multipart parser.
    """
    owner = get_owner(session)
    if owner is None:
        raise HTTPException(status_code=404, detail="Set up your profile first.")
    data = await request.body()
    try:
        media.save(
            session,
            entity_type="profile",
            entity_id=owner.id,
            data=data,
            content_type=request.headers.get("content-type"),
            replace=True,
        )
    except media.MediaError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    session.commit()
    return serialise_owner(session, owner)


@router.delete("/photo", response_model=ProfileOut)
def delete_photo(session: Session = Depends(get_session)) -> ProfileOut:
    owner = get_owner(session)
    if owner is None:
        raise HTTPException(status_code=404, detail="Set up your profile first.")
    media.remove_all(session, "profile", owner.id)
    session.commit()
    return serialise_owner(session, owner)


known_router = APIRouter(prefix="/profiles", tags=["profile"])


@known_router.get("", response_model=list[ProfileCardOut])
def list_known_profiles(
    segment: list[str] = Query(default_factory=list),
    session: Session = Depends(get_session),
) -> list[ProfileCardOut]:
    """Other people shared online, for picking a partner. Never with contact."""
    owner = get_owner(session)
    if owner is None:
        raise HTTPException(status_code=409, detail="Set up your profile first.")
    wanted = tuple(segment) or seg.AUDIENCES
    return [card(session, profile) for profile in known_profiles(session, owner, wanted)]
