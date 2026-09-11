"""Messages: free between people with something in common, paid to anyone else.

Two profiles talk freely once there is an interest, an enquiry, a
partnership, a deal, a group or a connection between them -- which is also
when they are in a position to need to -- and anyone may answer someone who
wrote to them first.

Writing to someone one has nothing with takes one message from a **message
pack**, bought on the Subscription page (10, 20, 30 or 40 messages, as the
operator prices them). The sync server keeps the count and takes the message
as it arrives, so a device cannot give itself messages. Such a message needs
the internet: the app asks the server first, then delivers it at once, and a
message the server refuses is not left behind looking sent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Connection,
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
from ..schemas import ConversationOut, MessageCostOut, MessageInput, MessageOut
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
    if member:
        return True
    # People who agreed to connect may talk, too.
    connection = session.scalar(
        select(Connection.id)
        .where(Connection.status == "accepted")
        .where(pair(Connection.requester_profile_id, Connection.addressee_profile_id))
        .limit(1)
    )
    return bool(connection)


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


def wrote_first(session: Session, sender: str, recipient: str) -> bool:
    """Whether ``sender`` has written to ``recipient``: answering them is free."""
    return session.scalar(
        select(Message.id)
        .where(Message.sender_profile_id == sender, Message.recipient_profile_id == recipient)
        .limit(1)
    ) is not None


def free_here(session: Session, owner: Profile, other: Profile) -> bool:
    """Free as far as this device knows: something in common, or they wrote first."""
    return related(session, owner.id, other.id) or wrote_first(session, other.id, owner.id)


def _ask_server(session: Session, other: Profile, transport: Any) -> dict:
    """The owner's message balance, and whether the server counts writing to ``other`` as free."""
    from . import subscription, sync_client  # noqa: PLC0415 - both import far into the app

    try:
        transport, token = subscription._connect(session, transport)
        return transport.get("/v1/message-credits", {"to": other.id}, token)
    except subscription.SubscriptionError as exc:
        if exc.status == 409:
            raise MessageError(
                "Writing to someone you are not connected with goes through the sync server: switch sync on first "
                "(More → My data & sync).", 409
            ) from exc
        raise MessageError("Writing to someone new needs the internet. Try again when you are online.", 503) from exc
    except sync_client.SyncError as exc:
        raise MessageError("Writing to someone new needs the internet. Try again when you are online.", 503) from exc


def cost(session: Session, owner: Profile, other: Profile, transport: Any = None) -> MessageCostOut:
    """What a message to ``other`` would cost: nothing, or one from a pack -- and how many are left."""
    if other.id == owner.id or free_here(session, owner, other):
        return MessageCostOut(free=True)
    try:
        answer = _ask_server(session, other, transport)
    except MessageError as exc:
        return MessageCostOut(free=False, reason="sync_off" if exc.status == 409 else "offline")
    return MessageCostOut(
        free=bool(answer.get("free")),
        credits=int(answer.get("balance") or 0),
        packs_on_sale=bool(answer.get("packsOnSale")) and bool(answer.get("paymentsAvailable")),
    )


def send(session: Session, owner: Profile, other: Profile, data: MessageInput, transport: Any = None) -> Message:
    if other.id == owner.id:
        raise MessageError("You cannot message yourself.", 422)
    if free_here(session, owner, other):
        return _create(session, owner, other, data, paid=False)

    # Someone the owner has nothing with: one message from a pack, delivered now.
    if owner.visibility != "online":
        raise MessageError("Share your profile online first, so they can see who is writing.", 409)
    answer = _ask_server(session, other, transport)
    if answer.get("free"):
        # The server knows of a link this device has not heard of yet.
        return _create(session, owner, other, data, paid=False)
    if int(answer.get("balance") or 0) < 1:
        raise MessageError(
            "You have no messages left to write to people you are not connected with. Buy a message pack "
            "on the Subscription page.", 402
        )
    message = _create(session, owner, other, data, paid=True)
    _deliver_now(session, message, transport)
    return message


def _create(session: Session, owner: Profile, other: Profile, data: MessageInput, *, paid: bool) -> Message:
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
        payload={"context_type": message.context_type, "paid": paid},
    )
    enqueue_sync(session, entity_type=ENTITY, entity_id=message.id, operation="create")
    return message


def _deliver_now(session: Session, message: Message, transport: Any) -> None:
    """Push a message from a pack at once; if the server refuses it, take it back."""
    from . import sync_client  # noqa: PLC0415

    session.flush()  # sessions here do not autoflush: the push must see this message's queue entry
    try:
        result = sync_client.run(session, transport)
    except sync_client.SyncError as exc:
        _take_back(session, message)
        raise MessageError("Writing to someone new needs the internet. Try again when you are online.", 503) from exc
    refused = next((error for error in result.errors if message.id[:8] in error), None)
    if refused:
        _take_back(session, message)
        reason = refused.split(": ", 1)[-1]
        raise MessageError(reason, 402 if "message pack" in reason else 409)
    record_event(session, EventType.MESSAGE_PAID, entity_type=ENTITY, entity_id=message.id)


def _take_back(session: Session, message: Message) -> None:
    from ..models import SyncQueueEntry  # noqa: PLC0415

    for entry in session.scalars(select(SyncQueueEntry).where(SyncQueueEntry.entity_id == message.id)):
        session.delete(entry)
    session.delete(message)
    session.flush()


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
