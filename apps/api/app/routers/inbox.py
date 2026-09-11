"""Notifications and messages."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Profile
from ..schemas import ConversationOut, InboxCounts, MessageInput, MessageOut, NotificationOut, ReadInput
from ..services import messages, notify
from .deps import fail, owner

router = APIRouter(tags=["inbox"])


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    unread: bool = Query(default=False),
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> list[NotificationOut]:
    rows = notify.inbox(session, me, unread_only=unread)
    session.commit()
    return rows


@router.get("/notifications/counts", response_model=InboxCounts)
def notification_counts(me: Profile = Depends(owner), session: Session = Depends(get_session)) -> InboxCounts:
    """Unread notifications and messages, for the badge in the top bar."""
    counts = notify.counts(session, me)
    session.commit()
    return counts


@router.post("/notifications/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(payload: ReadInput, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> None:
    notify.mark_read(session, me, payload.ids)
    session.commit()


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(me: Profile = Depends(owner), session: Session = Depends(get_session)) -> list[ConversationOut]:
    return messages.conversations(session, me)


def _other(session: Session, profile_id: str) -> Profile:
    other = session.get(Profile, profile_id)
    if other is None:
        raise HTTPException(status_code=404, detail="Person not found.")
    return other


@router.get("/conversations/{profile_id}/messages", response_model=list[MessageOut])
def read_thread(
    profile_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> list[MessageOut]:
    other = _other(session, profile_id)
    if not messages.related(session, me.id, other.id):
        raise HTTPException(status_code=404, detail="Person not found.")
    rows = messages.thread(session, me, other)
    session.commit()
    return rows


@router.post(
    "/conversations/{profile_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
    profile_id: str,
    payload: MessageInput,
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> MessageOut:
    other = _other(session, profile_id)
    try:
        message = messages.send(session, me, other, payload)
    except messages.MessageError as exc:
        raise fail(exc) from exc
    session.commit()
    return messages.serialise(message, me)
