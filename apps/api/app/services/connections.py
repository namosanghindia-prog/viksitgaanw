"""Who is connected to whom.

Two people are connected when either

* they **work together** -- an accepted investment offer, an accepted rental
  or purchase enquiry, an active machinery partnership, a deal, or the same
  farmer group; or
* they **both agreed** -- one sent a connection request and the other
  accepted it.

Connected people see each other's shared land and farm updates on the
timeline, may message each other, and see each other's phone number. The sync
server applies the same rule (``apps/sync/server.py``), so it holds whichever
device is asking.
"""

from __future__ import annotations

from datetime import datetime, timezone

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
    Profile,
)
from ..schemas import ConnectionInput, ConnectionOut, ConnectionsOut, ConnectionStateOut
from .events import EventType, enqueue_sync, record_event

ENTITY = "connection"


class ConnectionError_(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Working together
# --------------------------------------------------------------------------- #


def work_partners(session: Session, profile_id: str) -> dict[str, set[str]]:
    """Everyone ``profile_id`` works with, and how: {other id: {"deal", ...}}."""
    links: dict[str, set[str]] = {}

    def add(other: str | None, how: str) -> None:
        if other and other != profile_id:
            links.setdefault(other, set()).add(how)

    for investor, farmer in session.execute(
        select(InvestmentInterest.profile_id, InvestmentRequest.profile_id)
        .join(InvestmentRequest, InvestmentRequest.id == InvestmentInterest.request_id)
        .where(InvestmentInterest.status == "accepted")
        .where(or_(InvestmentInterest.profile_id == profile_id, InvestmentRequest.profile_id == profile_id))
    ):
        add(farmer if investor == profile_id else investor, "interest")

    for enquirer, seller in session.execute(
        select(EquipmentEnquiry.profile_id, EquipmentListing.profile_id)
        .join(EquipmentListing, EquipmentListing.id == EquipmentEnquiry.listing_id)
        .where(EquipmentEnquiry.status.in_(("accepted", "completed")))
        .where(or_(EquipmentEnquiry.profile_id == profile_id, EquipmentListing.profile_id == profile_id))
    ):
        add(seller if enquirer == profile_id else enquirer, "enquiry")

    for seller, partner in session.execute(
        select(EquipmentPartnership.seller_profile_id, EquipmentPartnership.partner_profile_id)
        .where(EquipmentPartnership.status == "active")
        .where(or_(EquipmentPartnership.seller_profile_id == profile_id,
                   EquipmentPartnership.partner_profile_id == profile_id))
    ):
        add(partner if seller == profile_id else seller, "partnership")

    for farmer, investor in session.execute(
        select(Deal.farmer_profile_id, Deal.investor_profile_id)
        .where(Deal.status != "cancelled")
        .where(or_(Deal.farmer_profile_id == profile_id, Deal.investor_profile_id == profile_id))
    ):
        add(investor if farmer == profile_id else farmer, "deal")

    # A group's organiser and its active members; members with each other too.
    group_ids = set(
        session.scalars(select(FarmerGroup.id).where(FarmerGroup.owner_profile_id == profile_id))
    ) | set(
        session.scalars(
            select(GroupMember.group_id).where(GroupMember.profile_id == profile_id, GroupMember.status == "active")
        )
    )
    for group_id in group_ids:
        group = session.get(FarmerGroup, group_id)
        if group is None:
            continue
        add(group.owner_profile_id, "group")
        for member in group.members:
            if member.status == "active":
                add(member.profile_id, "group")
    return links


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


def between(session: Session, a: str, b: str) -> Connection | None:
    """The latest connection request between two people, whoever sent it."""
    return session.scalars(
        select(Connection)
        .where(
            or_(
                and_(Connection.requester_profile_id == a, Connection.addressee_profile_id == b),
                and_(Connection.requester_profile_id == b, Connection.addressee_profile_id == a),
            )
        )
        .order_by(Connection.updated_at.desc())
    ).first()


def accepted_ids(session: Session, profile_id: str) -> set[str]:
    rows = session.execute(
        select(Connection.requester_profile_id, Connection.addressee_profile_id).where(
            Connection.status == "accepted",
            or_(Connection.requester_profile_id == profile_id, Connection.addressee_profile_id == profile_id),
        )
    )
    return {b if a == profile_id else a for a, b in rows}


def connected_ids(session: Session, profile_id: str) -> set[str]:
    """Everyone ``profile_id`` is connected to, by either route."""
    return accepted_ids(session, profile_id) | set(work_partners(session, profile_id))


def are_connected(session: Session, a: str, b: str) -> bool:
    if a == b:
        return True
    row = between(session, a, b)
    if row is not None and row.status == "accepted":
        return True
    return b in work_partners(session, a)


def state(session: Session, owner_id: str | None, other_id: str) -> ConnectionStateOut | None:
    """Where the device owner stands with someone, for their profile card."""
    if not owner_id or owner_id == other_id:
        return None
    row = between(session, owner_id, other_id)
    if row is not None and row.status == "accepted":
        return ConnectionStateOut(state="connected", via="request", id=row.id)
    if other_id in work_partners(session, owner_id):
        return ConnectionStateOut(state="connected", via="work", id=row.id if row else None)
    if row is not None and row.status == "requested":
        mine = row.requester_profile_id == owner_id
        return ConnectionStateOut(state="requested_by_me" if mine else "requested_by_them", via="request", id=row.id)
    return ConnectionStateOut(state="none")


def request(session: Session, owner: Profile, data: ConnectionInput) -> Connection:
    from .sharing import require_online  # noqa: PLC0415

    require_online(owner)
    if data.profile_id == owner.id:
        raise ConnectionError_("You cannot connect with yourself.", 422)
    other = session.get(Profile, data.profile_id)
    if other is None or other.visibility != "online":
        raise ConnectionError_("That profile is not shared online.", 404)

    row = between(session, owner.id, other.id)
    if row is not None:
        if row.status == "accepted":
            raise ConnectionError_("You are already connected.")
        if row.status == "requested" and row.requester_profile_id == owner.id:
            raise ConnectionError_("You have already asked. Wait for them to answer.")
        if row.status == "requested":
            # They asked first: asking back is saying yes.
            return answer(session, owner, row, "accepted")
    # A new request -- or asking again after a decline or a removal. A request
    # always belongs to whoever sends it (the sync server lets only the sender
    # rewrite it), so asking again reuses the owner's own earlier request, never
    # the other person's.
    row = session.scalars(
        select(Connection).where(
            Connection.requester_profile_id == owner.id, Connection.addressee_profile_id == other.id
        )
    ).first()
    if row is None:
        row = Connection(requester_profile_id=owner.id, addressee_profile_id=other.id)
        session.add(row)
    row.status, row.message, row.responded_at, row.updated_at = "requested", data.message, None, _now()
    session.flush()
    record_event(session, EventType.CONNECTION_REQUESTED, entity_type=ENTITY, entity_id=row.id)
    enqueue_sync(session, entity_type=ENTITY, entity_id=row.id, operation="create")
    return row


def answer(session: Session, owner: Profile, row: Connection, status: str) -> Connection:
    if row.addressee_profile_id != owner.id:
        raise ConnectionError_("Only the person asked can answer.", 403)
    if row.status != "requested":
        raise ConnectionError_("This request has already been answered.")
    row.status = status
    row.responded_at = _now()
    session.flush()
    record_event(
        session,
        EventType.CONNECTION_ACCEPTED if status == "accepted" else EventType.CONNECTION_DECLINED,
        entity_type=ENTITY,
        entity_id=row.id,
    )
    enqueue_sync(session, entity_type=ENTITY, entity_id=row.id, operation="update")
    return row


def remove(session: Session, owner: Profile, row: Connection) -> Connection:
    """Either side may end a connection, or withdraw a request they sent."""
    if owner.id not in (row.requester_profile_id, row.addressee_profile_id):
        raise ConnectionError_("Connection not found.", 404)
    if row.status not in ("requested", "accepted"):
        return row
    if row.status == "requested" and row.requester_profile_id != owner.id:
        raise ConnectionError_("Decline the request instead.")
    row.status = "removed"
    row.responded_at = _now()
    session.flush()
    record_event(session, EventType.CONNECTION_REMOVED, entity_type=ENTITY, entity_id=row.id)
    enqueue_sync(session, entity_type=ENTITY, entity_id=row.id, operation="update")
    forget_if_unconnected(session, owner.id, _other(row, owner.id))
    return row


def _other(row: Connection, me: str) -> str:
    return row.addressee_profile_id if row.requester_profile_id == me else row.requester_profile_id


def forget_if_unconnected(session: Session, owner_id: str, other_id: str) -> None:
    """Drop what a no-longer-connected person shared with the owner, on this device."""
    from ..models import FarmUpdate, LandShare  # noqa: PLC0415
    from . import media  # noqa: PLC0415

    if are_connected(session, owner_id, other_id):
        return
    for share in session.scalars(select(LandShare).where(LandShare.profile_id == other_id, LandShare.origin != "local")):
        media.remove_all(session, "land", share.id)
        session.delete(share)
    for update in session.scalars(select(FarmUpdate).where(FarmUpdate.profile_id == other_id, FarmUpdate.origin != "local")):
        media.remove_all(session, "update", update.id)
        session.delete(update)


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #


LINK_ORDER = ("deal", "interest", "enquiry", "partnership", "group")


def overview(session: Session, owner: Profile) -> ConnectionsOut:
    from .profiles import card  # noqa: PLC0415

    work = work_partners(session, owner.id)
    rows = list(
        session.scalars(
            select(Connection)
            .where(or_(Connection.requester_profile_id == owner.id, Connection.addressee_profile_id == owner.id))
            .order_by(Connection.updated_at.desc())
        )
    )
    connected: dict[str, ConnectionOut] = {}
    incoming: list[ConnectionOut] = []
    outgoing: list[ConnectionOut] = []

    for row in rows:
        other = session.get(Profile, _other(row, owner.id))
        if other is None:
            continue
        out = ConnectionOut(
            id=row.id,
            other=card(session, other, reveal_contact=row.status == "accepted"),
            status=row.status,
            via="request",
            sent_by_me=row.requester_profile_id == owner.id,
            message=row.message,
            links=sorted(work.get(other.id, set()), key=LINK_ORDER.index),
            created_at=row.created_at,
        )
        if row.status == "accepted":
            connected[other.id] = out
        elif row.status == "requested" and other.id not in work:
            (outgoing if out.sent_by_me else incoming).append(out)

    for other_id, how in work.items():
        if other_id in connected:
            continue
        other = session.get(Profile, other_id)
        if other is None:
            continue
        connected[other_id] = ConnectionOut(
            other=card(session, other, reveal_contact=True),
            status="accepted",
            via="work",
            links=sorted(how, key=LINK_ORDER.index),
        )

    known = set(connected) | {c.other.id for c in incoming + outgoing}
    suggestions = [
        card(session, profile)
        for profile in session.scalars(
            select(Profile)
            .where(Profile.id != owner.id, Profile.visibility == "online", Profile.is_device_owner.is_(False))
            .order_by(Profile.display_name)
        )
        if profile.id not in known
    ]
    # People in the owner's own state first.
    home = _state_name(session, owner)
    suggestions.sort(key=lambda c: not (home and home in (c.place or "")))

    return ConnectionsOut(
        connected=sorted(connected.values(), key=lambda c: (c.other.organisation_name or c.other.display_name).lower()),
        incoming=incoming,
        outgoing=outgoing,
        suggestions=suggestions[:30],
    )


def _state_name(session: Session, owner: Profile) -> str:
    from ..models import State  # noqa: PLC0415

    state_row = session.get(State, owner.state_code) if owner.state_code else None
    return state_row.name if state_row else ""


def serialise(session: Session, owner: Profile, row: Connection) -> ConnectionOut:
    from .profiles import card  # noqa: PLC0415

    other = session.get(Profile, _other(row, owner.id))
    return ConnectionOut(
        id=row.id,
        other=card(session, other, reveal_contact=row.status == "accepted"),
        status=row.status,
        via="request",
        sent_by_me=row.requester_profile_id == owner.id,
        message=row.message,
        links=sorted(work_partners(session, owner.id).get(other.id, set()), key=LINK_ORDER.index),
        created_at=row.created_at,
    )


def on_incoming(session: Session, row: Connection, before: dict | None, owner: Profile) -> None:
    """A connection request or answer arrived by sync: tell the owner."""
    from .notify import notify  # noqa: PLC0415

    other_id = _other(row, owner.id)
    other = session.get(Profile, other_id)
    name = (other.organisation_name or other.display_name) if other else ""
    was = (before or {}).get("status")
    if row.status == "requested" and row.addressee_profile_id == owner.id and was != "requested":
        notify(session, owner.id, "connection_requested", params={"name": name}, link="/connections",
               entity_type=ENTITY, entity_id=row.id)
    elif row.status == "accepted" and was != "accepted":
        notify(session, owner.id, "connection_accepted", params={"name": name}, link="/connections",
               entity_type=ENTITY, entity_id=row.id)
    elif row.status in ("declined", "removed"):
        forget_if_unconnected(session, owner.id, other_id)
