"""Connections, and the farm updates connections see."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Connection, FarmUpdate, Profile
from ..schemas import (
    ConnectionAnswer,
    ConnectionInput,
    ConnectionOut,
    ConnectionsOut,
    FarmUpdateInput,
    FarmUpdateOut,
    LandShareOut,
)
from ..services import connections, landshare, media
from ..services.connections import ConnectionError_
from ..services.landshare import ShareError
from ..services.sharing import SharingError
from .deps import owner

router = APIRouter(tags=["connections"])


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=getattr(exc, "status", 409), detail=str(exc))


# --------------------------------------------------------------------------- #
# Connections
# --------------------------------------------------------------------------- #


@router.get("/connections", response_model=ConnectionsOut)
def list_connections(me: Profile = Depends(owner), session: Session = Depends(get_session)) -> ConnectionsOut:
    """Who the owner is connected to, requests both ways, and people to connect with."""
    return connections.overview(session, me)


@router.post("/connections", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
def ask_to_connect(
    payload: ConnectionInput, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> ConnectionOut:
    try:
        row = connections.request(session, me, payload)
    except (ConnectionError_, SharingError) as exc:
        raise _fail(exc) from exc
    session.commit()
    return connections.serialise(session, me, row)


def _row(session: Session, me: Profile, connection_id: str) -> Connection:
    row = session.get(Connection, connection_id)
    if row is None or me.id not in (row.requester_profile_id, row.addressee_profile_id):
        raise HTTPException(status_code=404, detail="Connection not found.")
    return row


@router.patch("/connections/{connection_id}", response_model=ConnectionOut)
def answer_connection(
    connection_id: str,
    payload: ConnectionAnswer,
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> ConnectionOut:
    row = _row(session, me, connection_id)
    try:
        connections.answer(session, me, row, payload.status)
    except ConnectionError_ as exc:
        raise _fail(exc) from exc
    session.commit()
    return connections.serialise(session, me, row)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_connection(
    connection_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> None:
    """End a connection, or withdraw a request the owner sent."""
    row = _row(session, me, connection_id)
    try:
        connections.remove(session, me, row)
    except ConnectionError_ as exc:
        raise _fail(exc) from exc
    session.commit()


# --------------------------------------------------------------------------- #
# Shared land and updates
# --------------------------------------------------------------------------- #


@router.get("/land-shares/{share_id}", response_model=LandShareOut)
def get_land_share(share_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> LandShareOut:
    share = landshare.share_for(session, share_id)
    if (
        share is None
        or share.visibility != "online"
        or not connections.are_connected(session, me.id, share.profile_id)
    ):
        raise HTTPException(status_code=404, detail="Land not found.")
    return landshare.serialise_land(session, share, me)


@router.get("/updates", response_model=list[FarmUpdateOut])
def list_updates(
    land_share_id: str | None = Query(default=None, alias="landShareId"),
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> list[FarmUpdateOut]:
    """Updates from the owner and their connections, newest first."""
    connected = connections.connected_ids(session, me.id)
    return [
        landshare.serialise_update(session, update, me)
        for update in landshare.visible_updates(session, me, connected, land_share_id)
    ]


@router.post("/updates", response_model=FarmUpdateOut, status_code=status.HTTP_201_CREATED)
def post_update(
    payload: FarmUpdateInput, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> FarmUpdateOut:
    try:
        update = landshare.post_update(session, me, payload)
    except (ShareError, SharingError) as exc:
        raise _fail(exc) from exc
    session.commit()
    return landshare.serialise_update(session, update, me)


def _mine(session: Session, me: Profile, update_id: str) -> FarmUpdate:
    try:
        return landshare.owned_update(session, me, update_id)
    except ShareError as exc:
        raise _fail(exc) from exc


@router.post("/updates/{update_id}/photos", response_model=FarmUpdateOut)
async def add_update_photo(
    update_id: str, request: Request, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> FarmUpdateOut:
    update = _mine(session, me, update_id)
    try:
        media.save(
            session, entity_type="update", entity_id=update.id,
            data=await request.body(), content_type=request.headers.get("content-type"),
        )
    except media.MediaError as exc:
        raise _fail(exc) from exc
    # The picture must travel with the update: send it again.
    from ..services.events import enqueue_sync  # noqa: PLC0415

    enqueue_sync(session, entity_type=landshare.UPDATE, entity_id=update.id, operation="update")
    session.commit()
    return landshare.serialise_update(session, update, me)


@router.delete("/updates/{update_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_update(update_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> None:
    landshare.delete_update(session, me, _mine(session, me, update_id))
    session.commit()
