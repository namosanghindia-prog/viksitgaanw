"""Farmer groups: pooled land, members, and group requests."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Profile
from ..schemas import (
    GroupInput,
    GroupJoinInput,
    GroupMemberInput,
    GroupOut,
    GroupRequestInput,
    InvestmentRequestOut,
)
from ..services import groups, marketplace, sharing
from ..services.groups import GroupError
from .deps import fail, owner

router = APIRouter(prefix="/groups", tags=["groups"])


def _out(session: Session, me: Profile, group_id: str) -> GroupOut:
    session.commit()
    return groups.serialise(session, groups.visible(session, me, group_id), me)


@router.get("", response_model=list[GroupOut])
def browse(
    district_code: str | None = Query(default=None, alias="districtCode"),
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> list[GroupOut]:
    """Groups others have shared online, the owner's own district first."""
    return groups.browse(session, me, district_code=district_code)


@router.get("/mine", response_model=list[GroupOut])
def mine(me: Profile = Depends(owner), session: Session = Depends(get_session)) -> list[GroupOut]:
    return groups.mine(session, me)


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create(payload: GroupInput, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> GroupOut:
    try:
        group = groups.create(session, me, payload)
    except GroupError as exc:
        raise fail(exc) from exc
    return _out(session, me, group.id)


@router.get("/{group_id}", response_model=GroupOut)
def get_group(group_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> GroupOut:
    try:
        return groups.serialise(session, groups.visible(session, me, group_id), me)
    except GroupError as exc:
        raise fail(exc) from exc


@router.put("/{group_id}", response_model=GroupOut)
def update(group_id: str, payload: GroupInput, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> GroupOut:
    try:
        groups.update(session, me, groups.owned(session, me, group_id), payload)
    except GroupError as exc:
        raise fail(exc) from exc
    return _out(session, me, group_id)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(group_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> None:
    try:
        groups.delete(session, me, groups.owned(session, me, group_id))
    except GroupError as exc:
        raise fail(exc) from exc
    session.commit()


@router.post("/{group_id}/share", response_model=GroupOut)
def share(group_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> GroupOut:
    try:
        sharing.share_item(session, me, groups.owned(session, me, group_id))
    except (GroupError, sharing.SharingError) as exc:
        raise fail(exc) from exc
    return _out(session, me, group_id)


@router.post("/{group_id}/unshare", response_model=GroupOut)
def unshare(group_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> GroupOut:
    try:
        sharing.unshare_item(session, me, groups.owned(session, me, group_id))
    except (GroupError, sharing.SharingError) as exc:
        raise fail(exc) from exc
    return _out(session, me, group_id)


@router.post("/{group_id}/members", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def add_member(
    group_id: str, payload: GroupMemberInput, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> GroupOut:
    try:
        groups.add_member(session, groups.owned(session, me, group_id), payload)
    except GroupError as exc:
        raise fail(exc) from exc
    return _out(session, me, group_id)


@router.patch("/{group_id}/members/{member_id}", response_model=GroupOut)
def set_member(
    group_id: str,
    member_id: str,
    status_value: str = Query(alias="status"),
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> GroupOut:
    """Approve a join request (active) or mark a member as having left."""
    try:
        groups.set_member_status(session, groups.owned(session, me, group_id), member_id, status_value)
    except GroupError as exc:
        raise fail(exc) from exc
    return _out(session, me, group_id)


@router.delete("/{group_id}/members/{member_id}", response_model=GroupOut)
def remove_member(
    group_id: str, member_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> GroupOut:
    try:
        groups.remove_member(session, groups.owned(session, me, group_id), member_id)
    except GroupError as exc:
        raise fail(exc) from exc
    return _out(session, me, group_id)


@router.post("/{group_id}/join", response_model=GroupOut)
def join(group_id: str, payload: GroupJoinInput, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> GroupOut:
    try:
        groups.join(session, me, groups.visible(session, me, group_id), payload)
    except GroupError as exc:
        raise fail(exc) from exc
    return _out(session, me, group_id)


@router.post("/{group_id}/leave", response_model=GroupOut)
def leave(group_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> GroupOut:
    try:
        groups.leave(session, me, groups.visible(session, me, group_id))
    except GroupError as exc:
        raise fail(exc) from exc
    return _out(session, me, group_id)


@router.post("/{group_id}/requests", response_model=InvestmentRequestOut, status_code=status.HTTP_201_CREATED)
def group_request(
    group_id: str, payload: GroupRequestInput, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> InvestmentRequestOut:
    """Ask for investment on behalf of the whole group's land."""
    try:
        request = groups.create_group_request(session, me, groups.owned(session, me, group_id), payload)
    except GroupError as exc:
        raise fail(exc) from exc
    session.commit()
    session.refresh(request)
    return marketplace.serialise_request(session, request, me)
