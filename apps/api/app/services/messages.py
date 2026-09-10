"""Messages between people who already have something in common.

Nobody can message a stranger. Two profiles may talk once there is an
interest, an enquiry, a partnership or a deal between them -- which is also
when they are in a position to need to. It keeps cold approaches out of a
villager's inbox, and puts the conversation where a later dispute can refer
to it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Deal,
    EquipmentEnquiry,
    EquipmentListing,
    EquipmentPartnership,
    FarmerGroup,
    GroupMember,
    InvestmentInterest,
    InvestmentRequest,
    Message,
    Profile,
)
from ..schemas import ConversationOut, MessageInput, MessageOut
from .events import EventType, enqueue_sync, record_event
from .notify import notify
from .profiles import card

ENTITY = "message"


class MessageError(Exception):
    def __init__(self, message: str, status: int = 403) -> None:
        super().__init__(message)
        self.status = status


def related(session: Session, a: str, b: str) -> bool:
    """Whether profiles ``a`` and ``b`` have anything going on between them."""
    pair = lambda x, y: or_(and_(x == a, y == b), and_(x == b, y == a))  # noqa: E731

    interest = session.scalar(
        select(InvestmentInterest.id)
        .join(InvestmentRequest, InvestmentRequest.id == InvestmentInterest.request_id)
        .where(pair(InvestmentInterest.profile_id, InvestmentRequest.profile_id))
        .limit(1)
    )
    if interest:
        return True
    enquiry = session.scalar(
        select(EquipmentEnquiry.id)
        .join(EquipmentListing, EquipmentListing.id == EquipmentEnquiry.listing_id)
        .where(pair(EquipmentEnquiry.profile_id, EquipmentListing.profile_id))
        .limit(1)
    )
    if enquiry:
        return True
    partnership = session.scalar(
        select(EquipmentPartnership.id)
        .where(pair(EquipmentPartnership.seller_profile_id, EquipmentPartnership.partner_profile_id))
        .limit(1)
    )
    if partnership:
        return True
    deal = session.scalar(
        select(Deal.id).where(pair(Deal.farmer_profile_id, Deal.investor_profile_id)).limit(1)
    )
    if deal:
        return True
    member = session.scalar(
        select(GroupMember.id)
        .join(FarmerGroup, FarmerGroup.id == GroupMember.group_id)
        .where(pair(GroupMember.profile_id, FarmerGroup.owner_profile_id))
        .limit(1)
    )
    return bool(member)


def serialise(message: Message, owner: Profile) -> MessageOut:
    return MessageOut(
        id=message.id,
        body=message.body,
        context_type=message.context_type,
        context_id=message.context_id,
        mine=message.sender_profile_id == owner.id,
        read=message.read_at is not None,
        created_at=message.created_at,
    )


def send(session: Session, owner: Profile, other: Profile, data: MessageInput) -> Message:
    if other.id == owner.id:
        raise MessageError("You cannot message yourself.", 422)
    if not related(session, owner.id, other.id):
        raise MessageError(
            "You can message someone once you have a request, enquiry, partnership or deal with them."
        )
    message = Message(
        sender_profile_id=owner.id,
        recipient_profile_id=other.id,
        body=data.body,
        context_type=data.context_type,
        context_id=data.context_id,
        origin="local",
    )
    session.add(message)
    session.flush()
    record_event(
        session,
        EventType.MESSAGE_SENT,
        entity_type=ENTITY,
        entity_id=message.id,
        payload={"context_type": message.context_type},
    )
    enqueue_sync(session, entity_type=ENTITY, entity_id=message.id, operation="create")
    return message


def receive(session: Session, message: Message) -> None:
    """Called when a message arrives by sync: tell the owner."""
    sender = session.get(Profile, message.sender_profile_id)
    notify(
        session,
        message.recipient_profile_id,
        "message_received",
        params={"name": (sender.organisation_name or sender.display_name) if sender else ""},
        link=f"/messages/{message.sender_profile_id}",
        entity_type=ENTITY,
        entity_id=message.id,
    )


def thread(session: Session, owner: Profile, other: Profile) -> list[MessageOut]:
    """The whole conversation, oldest first; marks what the owner received as read."""
    rows = list(
        session.scalars(
            select(Message)
            .where(
                or_(
                    and_(Message.sender_profile_id == owner.id, Message.recipient_profile_id == other.id),
                    and_(Message.sender_profile_id == other.id, Message.recipient_profile_id == owner.id),
                )
            )
            .order_by(Message.created_at)
        )
    )
    now = datetime.now(timezone.utc)
    for message in rows:
        if message.recipient_profile_id == owner.id and message.read_at is None:
            message.read_at = now
    return [serialise(message, owner) for message in rows]


def conversations(session: Session, owner: Profile) -> list[ConversationOut]:
    rows = session.scalars(
        select(Message)
        .where(or_(Message.sender_profile_id == owner.id, Message.recipient_profile_id == owner.id))
        .order_by(Message.created_at.desc())
    )
    latest: dict[str, Message] = {}
    unread: dict[str, int] = {}
    for message in rows:
        other_id = (
            message.recipient_profile_id
            if message.sender_profile_id == owner.id
            else message.sender_profile_id
        )
        latest.setdefault(other_id, message)
        if message.recipient_profile_id == owner.id and message.read_at is None:
            unread[other_id] = unread.get(other_id, 0) + 1

    out: list[ConversationOut] = []
    for other_id, message in latest.items():
        other = session.get(Profile, other_id)
        if other is None:
            continue
        out.append(
            ConversationOut(
                other=card(session, other),
                last_message=serialise(message, owner),
                unread=unread.get(other_id, 0),
            )
        )
    return out
