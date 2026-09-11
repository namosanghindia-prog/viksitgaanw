"""Machines for sale or rent, and each seller's partner network.

Agriculture organisations (the partner segments) list machines. Anyone else
can ask to rent or buy one; the seller accepts or declines, and accepting
shares both sides' contact details -- the same shape as an investment
interest, and like it, no money moves through the app.

A seller also builds a **partner network**: farmers who keep machines for
hire in their village, a Gram Panchayat or village rental point, a district
dealer, a distributor organisation. The seller can record a partner who is
not on the platform at all (a name and a phone number), or propose to one who
is. A farmer or distributor can equally ask to become a seller's partner.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import segments as seg
from ..models import EquipmentEnquiry, EquipmentListing, EquipmentPartnership, Profile
from ..schemas import (
    EnquiryInput,
    EnquiryOut,
    EquipmentInput,
    EquipmentOut,
    MediaOut,
    PartnershipAsk,
    PartnershipInput,
    PartnershipOut,
)
from . import media, videos
from .events import EventType, enqueue_sync, record_event
from .hierarchy import location_error, resolve_location
from .profiles import card

LISTING = "equipment_listing"
ENQUIRY = "equipment_enquiry"
PARTNERSHIP = "equipment_partnership"


class EquipmentError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _place(session: Session, **codes: str | None) -> str | None:
    path = resolve_location(session, **codes)
    parts = [unit.name for unit in (path.village, path.subdistrict, path.district, path.state) if unit]
    return ", ".join(parts) or None


def _require_seller(owner: Profile) -> None:
    if owner.segment not in seg.EQUIPMENT_SELLERS:
        raise EquipmentError(
            "Only agriculture organisations can list machines for sale or rent.", 403
        )


# --------------------------------------------------------------------------- #
# Visibility and serialisation
# --------------------------------------------------------------------------- #


def visible_to(listing: EquipmentListing, viewer: Profile) -> bool:
    return listing.profile_id == viewer.id or listing.visibility == "online"


def _latest_enquiry(listing: EquipmentListing, profile_id: str) -> EquipmentEnquiry | None:
    mine = [enquiry for enquiry in listing.enquiries if enquiry.profile_id == profile_id]
    return max(mine, key=lambda enquiry: enquiry.created_at) if mine else None


def partnership_between(session: Session, seller_id: str, partner_id: str) -> EquipmentPartnership | None:
    return session.scalars(
        select(EquipmentPartnership)
        .where(EquipmentPartnership.seller_profile_id == seller_id)
        .where(EquipmentPartnership.partner_profile_id == partner_id)
        .where(EquipmentPartnership.status.in_(("proposed", "active")))
        .order_by(EquipmentPartnership.created_at.desc())
    ).first()


def serialise_enquiry(session: Session, enquiry: EquipmentEnquiry, *, reveal: bool) -> EnquiryOut:
    return EnquiryOut(
        id=enquiry.id,
        listing_id=enquiry.listing_id,
        kind=enquiry.kind,
        quantity=enquiry.quantity,
        start_date=enquiry.start_date,
        end_date=enquiry.end_date,
        area_acres=enquiry.area_acres,
        message=enquiry.message,
        status=enquiry.status,
        enquirer=card(session, enquiry.profile, reveal_contact=reveal),
        origin=enquiry.origin,
        created_at=enquiry.created_at,
        responded_at=enquiry.responded_at,
    )


def serialise_partnership(
    session: Session, partnership: EquipmentPartnership, viewer: Profile
) -> PartnershipOut:
    active = partnership.status == "active"
    is_seller = partnership.seller_profile_id == viewer.id
    return PartnershipOut(
        id=partnership.id,
        partner_kind=partnership.partner_kind,
        role=partnership.role,
        equipment_types=list(partnership.equipment_types or []),
        commission_percent=partnership.commission_percent,
        message=partnership.message,
        initiated_by=partnership.initiated_by,
        status=partnership.status,
        area=_place(
            session,
            village_code=partnership.village_code,
            subdistrict_code=partnership.subdistrict_code,
            district_code=partnership.district_code,
            state_code=partnership.state_code,
        ),
        seller=card(session, partnership.seller, reveal_contact=active and not is_seller),
        partner=(
            card(session, partnership.partner, reveal_contact=active and is_seller)
            if partnership.partner
            else None
        ),
        # An off-platform contact is the seller's own record; nobody else
        # ever sees it.
        contact_name=partnership.contact_name if is_seller else None,
        contact_phone=partnership.contact_phone if is_seller else None,
        is_seller=is_seller,
        origin=partnership.origin,
        created_at=partnership.created_at,
        responded_at=partnership.responded_at,
    )


def serialise(session: Session, listing: EquipmentListing, viewer: Profile) -> EquipmentOut:
    mine = listing.profile_id == viewer.id
    own_enquiry = None if mine else _latest_enquiry(listing, viewer.id)
    partnership = None if mine else partnership_between(session, listing.profile_id, viewer.id)
    connected = (own_enquiry is not None and own_enquiry.status == "accepted") or (
        partnership is not None and partnership.status == "active"
    )

    counts: dict[str, int] = {}
    if mine:
        for enquiry in listing.enquiries:
            counts[enquiry.status] = counts.get(enquiry.status, 0) + 1

    return EquipmentOut(
        intro_video=videos.out(listing.intro_video),
        id=listing.id,
        equipment_type=listing.equipment_type,
        title=listing.title,
        brand=listing.brand,
        model=listing.model,
        year_made=listing.year_made,
        condition=listing.condition,
        description=listing.description,
        for_sale=listing.for_sale,
        sale_price=listing.sale_price,
        for_rent=listing.for_rent,
        rent_rate=listing.rent_rate,
        rent_unit=listing.rent_unit,
        quantity=listing.quantity,
        with_operator=listing.with_operator,
        delivery=listing.delivery,
        state_code=listing.state_code,
        district_code=listing.district_code,
        subdistrict_code=listing.subdistrict_code,
        place=_place(
            session,
            subdistrict_code=listing.subdistrict_code,
            district_code=listing.district_code,
            state_code=listing.state_code,
        ),
        status=listing.status,
        visibility=listing.visibility,
        shared_at=listing.shared_at,
        photos=[
            MediaOut(
                id=file.id,
                url=media.url_for(file),
                width=file.width,
                height=file.height,
                position=file.position,
            )
            for file in media.for_entity(session, "equipment", listing.id)
        ],
        seller=card(session, listing.profile, reveal_contact=connected),
        is_mine=mine,
        my_enquiry=(
            serialise_enquiry(session, own_enquiry, reveal=False) if own_enquiry else None
        ),
        enquiries=(
            [
                serialise_enquiry(session, enquiry, reveal=enquiry.status == "accepted")
                for enquiry in sorted(listing.enquiries, key=lambda e: e.created_at, reverse=True)
            ]
            if mine
            else []
        ),
        enquiry_counts=counts,
        my_partnership=(
            serialise_partnership(session, partnership, viewer) if partnership else None
        ),
        origin=listing.origin,
        created_at=listing.created_at,
        updated_at=listing.updated_at,
    )


# --------------------------------------------------------------------------- #
# Listings
# --------------------------------------------------------------------------- #


def _apply(listing: EquipmentListing, data: EquipmentInput) -> None:
    for field in (
        "equipment_type",
        "title",
        "brand",
        "model",
        "year_made",
        "condition",
        "description",
        "for_sale",
        "sale_price",
        "for_rent",
        "rent_rate",
        "rent_unit",
        "quantity",
        "with_operator",
        "delivery",
        "state_code",
        "district_code",
        "subdistrict_code",
        "status",
    ):
        setattr(listing, field, getattr(data, field))


def _check_place(session: Session, data: EquipmentInput) -> None:
    error = location_error(
        session,
        state_code=data.state_code,
        district_code=data.district_code,
        subdistrict_code=data.subdistrict_code,
    )
    if error:
        raise EquipmentError(error, 422)


def create_listing(session: Session, owner: Profile, data: EquipmentInput) -> EquipmentListing:
    _require_seller(owner)
    _check_place(session, data)
    listing = EquipmentListing(profile_id=owner.id, origin="local", visibility="offline")
    _apply(listing, data)
    session.add(listing)
    session.flush()
    record_event(
        session,
        EventType.EQUIPMENT_CREATED,
        entity_type=LISTING,
        entity_id=listing.id,
        payload={
            "equipment_type": listing.equipment_type,
            "for_sale": listing.for_sale,
            "for_rent": listing.for_rent,
            "state_code": listing.state_code,
        },
    )
    enqueue_sync(session, entity_type=LISTING, entity_id=listing.id, operation="create")
    return listing


def update_listing(
    session: Session, owner: Profile, listing: EquipmentListing, data: EquipmentInput
) -> EquipmentListing:
    if listing.profile_id != owner.id:
        raise EquipmentError("Only the seller can change this listing.", 403)
    _check_place(session, data)
    _apply(listing, data)
    if listing.sync_state == "synced":
        listing.sync_state = "queued"
    record_event(
        session,
        EventType.EQUIPMENT_UPDATED,
        entity_type=LISTING,
        entity_id=listing.id,
        payload={"status": listing.status},
    )
    enqueue_sync(session, entity_type=LISTING, entity_id=listing.id, operation="update")
    return listing


def delete_listing(session: Session, owner: Profile, listing: EquipmentListing) -> None:
    if listing.profile_id != owner.id:
        raise EquipmentError("Only the seller can delete this listing.", 403)
    enqueue_sync(session, entity_type=LISTING, entity_id=listing.id, operation="delete")
    record_event(
        session,
        EventType.EQUIPMENT_DELETED,
        entity_type=LISTING,
        entity_id=listing.id,
        payload={"title": listing.title},
    )
    media.remove_all(session, "equipment", listing.id)
    session.delete(listing)


def mine(session: Session, owner: Profile) -> list[EquipmentOut]:
    stmt = (
        select(EquipmentListing)
        .where(EquipmentListing.profile_id == owner.id)
        .order_by(EquipmentListing.created_at.desc())
    )
    return [serialise(session, listing, owner) for listing in session.scalars(stmt)]


def browse(
    session: Session,
    viewer: Profile,
    *,
    equipment_type: str | None = None,
    state_code: str | None = None,
    offer: str | None = None,
    limit: int = 100,
) -> list[EquipmentOut]:
    """Machines shared online by others, still active, nearest state first."""
    stmt = (
        select(EquipmentListing)
        .where(EquipmentListing.visibility == "online")
        .where(EquipmentListing.status == "active")
        .where(EquipmentListing.profile_id != viewer.id)
        .order_by(EquipmentListing.shared_at.desc(), EquipmentListing.created_at.desc())
    )
    if equipment_type:
        stmt = stmt.where(EquipmentListing.equipment_type == equipment_type)
    if state_code:
        stmt = stmt.where(EquipmentListing.state_code == state_code)
    if offer == "rent":
        stmt = stmt.where(EquipmentListing.for_rent.is_(True))
    elif offer == "sale":
        stmt = stmt.where(EquipmentListing.for_sale.is_(True))

    rows = [serialise(session, listing, viewer) for listing in session.scalars(stmt.limit(limit))]
    # Machines in the viewer's own state first: a harvester three states away
    # is rarely the one a farmer can use.
    if viewer.state_code:
        rows.sort(key=lambda row: row.state_code != viewer.state_code)
    return rows


# --------------------------------------------------------------------------- #
# Enquiries
# --------------------------------------------------------------------------- #


def send_enquiry(
    session: Session, owner: Profile, listing: EquipmentListing, data: EnquiryInput
) -> EquipmentEnquiry:
    if listing.profile_id == owner.id:
        raise EquipmentError("This is your own listing.", 403)
    if not visible_to(listing, owner) or listing.status != "active":
        raise EquipmentError("This machine is not available now.")
    if owner.visibility != "online":
        raise EquipmentError(
            "Share your profile online first, so the seller can see who is asking."
        )
    if data.kind == "rent" and not listing.for_rent:
        raise EquipmentError("This machine is not for rent.", 422)
    if data.kind == "buy" and not listing.for_sale:
        raise EquipmentError("This machine is not for sale.", 422)
    if data.quantity > listing.quantity:
        raise EquipmentError(f"Only {listing.quantity} available.", 422)

    # A pending enquiry is edited rather than duplicated. Once answered, a
    # new one can be sent -- a farmer may hire the same thresher every season.
    enquiry = _latest_enquiry(listing, owner.id)
    created = enquiry is None or enquiry.status != "sent"
    if created:
        enquiry = EquipmentEnquiry(listing_id=listing.id, profile_id=owner.id, origin="local")
        session.add(enquiry)
        listing.enquiries.append(enquiry)
    for field in ("kind", "quantity", "start_date", "end_date", "area_acres", "message"):
        setattr(enquiry, field, getattr(data, field))
    enquiry.status = "sent"
    session.flush()

    record_event(
        session,
        EventType.ENQUIRY_SENT,
        entity_type=ENQUIRY,
        entity_id=enquiry.id,
        payload={"listing_id": listing.id, "kind": enquiry.kind, "resent": not created},
    )
    enqueue_sync(
        session, entity_type=ENQUIRY, entity_id=enquiry.id, operation="create" if created else "update"
    )
    return enquiry


def respond_enquiry(
    session: Session, owner: Profile, enquiry: EquipmentEnquiry, status: str
) -> EquipmentEnquiry:
    listing = enquiry.listing
    if status == "withdrawn":
        if enquiry.profile_id != owner.id:
            raise EquipmentError("Only the person who asked can withdraw.", 403)
        if enquiry.status not in ("sent", "accepted"):
            raise EquipmentError("This enquiry cannot be withdrawn now.")
    else:
        if listing.profile_id != owner.id:
            raise EquipmentError("Only the seller can answer.", 403)
        if enquiry.status != "sent":
            raise EquipmentError("This enquiry has already been answered.")

    enquiry.status = status
    enquiry.responded_at = _now()
    record_event(
        session,
        EventType.ENQUIRY_UPDATED,
        entity_type=ENQUIRY,
        entity_id=enquiry.id,
        payload={"listing_id": listing.id, "status": status},
    )
    if status == "accepted":
        record_event(
            session,
            EventType.ENQUIRY_ACCEPTED,
            entity_type=ENQUIRY,
            entity_id=enquiry.id,
            payload={
                "listing_id": listing.id,
                "kind": enquiry.kind,
                "equipment_type": listing.equipment_type,
                "quantity": enquiry.quantity,
            },
        )
    enqueue_sync(session, entity_type=ENQUIRY, entity_id=enquiry.id, operation="update")
    return enquiry


def my_enquiries(session: Session, owner: Profile) -> list[EquipmentOut]:
    """Listings the owner has asked about, newest question first."""
    stmt = (
        select(EquipmentEnquiry)
        .where(EquipmentEnquiry.profile_id == owner.id)
        .order_by(EquipmentEnquiry.updated_at.desc())
    )
    seen: set[str] = set()
    rows: list[EquipmentOut] = []
    for enquiry in session.scalars(stmt):
        if enquiry.listing_id in seen:
            continue
        seen.add(enquiry.listing_id)
        rows.append(serialise(session, enquiry.listing, owner))
    return rows


# --------------------------------------------------------------------------- #
# Partner network
# --------------------------------------------------------------------------- #


def add_partner(session: Session, owner: Profile, data: PartnershipInput) -> EquipmentPartnership:
    """A seller adds someone to their network.

    A partner already on the platform is *proposed* and must accept. A partner
    who is not -- a village rental point run by someone with only a phone --
    is simply recorded, active from the start, because they cannot answer.
    """
    _require_seller(owner)
    error = location_error(
        session,
        state_code=data.state_code,
        district_code=data.district_code,
        subdistrict_code=data.subdistrict_code,
        village_code=data.village_code,
    )
    if error:
        raise EquipmentError(error, 422)

    partner: Profile | None = None
    if data.partner_profile_id:
        partner = session.get(Profile, data.partner_profile_id)
        if partner is None or partner.id == owner.id or partner.visibility != "online":
            raise EquipmentError("That partner is not on the platform.", 404)
        expected = {
            "farmer": (seg.FARMER,),
            "distributor": seg.PARTNERS,
            "village": (seg.FARMER, seg.GOVERNMENT) + seg.PARTNERS,
            "district": (seg.FARMER, seg.GOVERNMENT) + seg.PARTNERS,
        }[data.partner_kind]
        if partner.segment not in expected:
            raise EquipmentError(f"That profile cannot be a {data.partner_kind} partner.", 422)
        if partnership_between(session, owner.id, partner.id):
            raise EquipmentError("You already have a partnership with them.")

    partnership = EquipmentPartnership(
        seller_profile_id=owner.id,
        partner_kind=data.partner_kind,
        partner_profile_id=partner.id if partner else None,
        contact_name=data.contact_name,
        contact_phone=data.contact_phone,
        state_code=data.state_code,
        district_code=data.district_code,
        subdistrict_code=data.subdistrict_code,
        village_code=data.village_code,
        role=data.role,
        equipment_types=data.equipment_types,
        commission_percent=data.commission_percent,
        message=data.message,
        initiated_by="seller",
        status="proposed" if partner else "active",
        origin="local",
    )
    session.add(partnership)
    session.flush()
    _record_partnership(session, partnership, EventType.PARTNERSHIP_PROPOSED, "create")
    return partnership


def ask_to_partner(
    session: Session, owner: Profile, seller: Profile, data: PartnershipAsk
) -> EquipmentPartnership:
    """A farmer (or a distributor organisation) asks a seller to take them on."""
    if seller.segment not in seg.EQUIPMENT_SELLERS or seller.id == owner.id:
        raise EquipmentError("That profile does not sell machines.", 404)
    if seller.visibility != "online":
        raise EquipmentError("That seller is not on the platform.", 404)
    if owner.segment == seg.FARMER:
        kind = "farmer"
    elif owner.segment in seg.PARTNERS:
        kind = "distributor"
    else:
        raise EquipmentError("Only farmers and organisations can become equipment partners.", 403)
    if owner.visibility != "online":
        raise EquipmentError("Share your profile online first, so the seller can see who is asking.")
    if partnership_between(session, seller.id, owner.id):
        raise EquipmentError("You have already asked this seller, or are already partners.")

    partnership = EquipmentPartnership(
        seller_profile_id=seller.id,
        partner_kind=kind,
        partner_profile_id=owner.id,
        # The partnership covers where the partner is.
        state_code=owner.state_code,
        district_code=owner.district_code,
        subdistrict_code=owner.subdistrict_code,
        village_code=owner.village_code,
        role=data.role,
        equipment_types=data.equipment_types,
        message=data.message,
        initiated_by="partner",
        status="proposed",
        origin="local",
    )
    session.add(partnership)
    session.flush()
    _record_partnership(session, partnership, EventType.PARTNERSHIP_PROPOSED, "create")
    return partnership


def respond_partnership(
    session: Session, owner: Profile, partnership: EquipmentPartnership, status: str
) -> EquipmentPartnership:
    is_seller = partnership.seller_profile_id == owner.id
    is_partner = partnership.partner_profile_id == owner.id
    if not (is_seller or is_partner):
        raise EquipmentError("Partnership not found.", 404)

    if status in ("active", "declined"):
        # Only the side that did *not* propose can accept or decline.
        answering_side = "partner" if partnership.initiated_by == "seller" else "seller"
        if partnership.status != "proposed":
            raise EquipmentError("This partnership has already been answered.")
        if (answering_side == "seller") != is_seller:
            raise EquipmentError("Waiting for the other side to answer.", 403)
    elif status == "ended":
        if partnership.status not in ("proposed", "active"):
            raise EquipmentError("This partnership is already over.")

    partnership.status = status
    partnership.responded_at = _now()
    _record_partnership(session, partnership, EventType.PARTNERSHIP_UPDATED, "update")
    return partnership


def my_partnerships(session: Session, owner: Profile) -> list[PartnershipOut]:
    stmt = (
        select(EquipmentPartnership)
        .where(
            or_(
                EquipmentPartnership.seller_profile_id == owner.id,
                EquipmentPartnership.partner_profile_id == owner.id,
            )
        )
        .order_by(EquipmentPartnership.created_at.desc())
    )
    return [serialise_partnership(session, row, owner) for row in session.scalars(stmt)]


def _record_partnership(
    session: Session, partnership: EquipmentPartnership, event: str, operation: str
) -> None:
    record_event(
        session,
        event,
        entity_type=PARTNERSHIP,
        entity_id=partnership.id,
        payload={
            "partner_kind": partnership.partner_kind,
            "role": partnership.role,
            "status": partnership.status,
            "initiated_by": partnership.initiated_by,
        },
    )
    enqueue_sync(session, entity_type=PARTNERSHIP, entity_id=partnership.id, operation=operation)
