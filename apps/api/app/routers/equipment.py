"""Machines for sale or rent, enquiries about them, and seller partnerships.

Every call acts as the device owner, as in the rest of the marketplace.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import EquipmentEnquiry, EquipmentListing, EquipmentPartnership, MediaFile, Profile
from ..schemas import (
    EnquiryInput,
    EquipmentInput,
    EquipmentOut,
    PartnershipAsk,
    PartnershipInput,
    PartnershipOut,
    PartnershipUpdate,
    ResponseUpdate,
    TimelineItemOut,
)
from ..services import equipment, media, sharing, timeline
from ..services.equipment import EquipmentError
from ..services.profiles import get_owner

router = APIRouter(tags=["equipment"])


def _owner(session: Session) -> Profile:
    owner = get_owner(session)
    if owner is None:
        raise HTTPException(status_code=409, detail="Set up your profile first.")
    return owner


def _listing_or_404(session: Session, listing_id: str, viewer: Profile) -> EquipmentListing:
    listing = session.get(EquipmentListing, listing_id)
    if listing is None or not equipment.visible_to(listing, viewer):
        raise HTTPException(status_code=404, detail="Machine not found.")
    return listing


def _fail(error: Exception) -> HTTPException:
    return HTTPException(status_code=getattr(error, "status", 409), detail=str(error))


# --------------------------------------------------------------------------- #
# Listings
# --------------------------------------------------------------------------- #


@router.post("/equipment", response_model=EquipmentOut, status_code=status.HTTP_201_CREATED)
def create_listing(payload: EquipmentInput, session: Session = Depends(get_session)) -> EquipmentOut:
    """List a machine. It stays offline until the seller shares it."""
    owner = _owner(session)
    try:
        listing = equipment.create_listing(session, owner, payload)
    except EquipmentError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(listing)
    return equipment.serialise(session, listing, owner)


@router.get("/equipment", response_model=list[EquipmentOut])
def browse_listings(
    equipment_type: str | None = Query(default=None, alias="type"),
    state_code: str | None = Query(default=None, alias="stateCode"),
    offer: Literal["rent", "sale"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[EquipmentOut]:
    """Machines others have shared online."""
    owner = _owner(session)
    return equipment.browse(
        session, owner, equipment_type=equipment_type, state_code=state_code, offer=offer, limit=limit
    )


@router.get("/equipment/mine", response_model=list[EquipmentOut])
def my_listings(session: Session = Depends(get_session)) -> list[EquipmentOut]:
    return equipment.mine(session, _owner(session))


@router.get("/equipment/{listing_id}", response_model=EquipmentOut)
def get_listing(listing_id: str, session: Session = Depends(get_session)) -> EquipmentOut:
    owner = _owner(session)
    return equipment.serialise(session, _listing_or_404(session, listing_id, owner), owner)


@router.put("/equipment/{listing_id}", response_model=EquipmentOut)
def update_listing(
    listing_id: str, payload: EquipmentInput, session: Session = Depends(get_session)
) -> EquipmentOut:
    owner = _owner(session)
    listing = _listing_or_404(session, listing_id, owner)
    try:
        equipment.update_listing(session, owner, listing, payload)
    except EquipmentError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(listing)
    return equipment.serialise(session, listing, owner)


@router.delete("/equipment/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_listing(listing_id: str, session: Session = Depends(get_session)) -> None:
    owner = _owner(session)
    listing = _listing_or_404(session, listing_id, owner)
    try:
        equipment.delete_listing(session, owner, listing)
    except EquipmentError as exc:
        raise _fail(exc) from exc
    session.commit()


@router.post("/equipment/{listing_id}/share", response_model=EquipmentOut)
def share_listing(listing_id: str, session: Session = Depends(get_session)) -> EquipmentOut:
    owner = _owner(session)
    listing = _listing_or_404(session, listing_id, owner)
    try:
        sharing.share_item(session, owner, listing)
    except sharing.SharingError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(listing)
    return equipment.serialise(session, listing, owner)


@router.post("/equipment/{listing_id}/unshare", response_model=EquipmentOut)
def unshare_listing(listing_id: str, session: Session = Depends(get_session)) -> EquipmentOut:
    owner = _owner(session)
    listing = _listing_or_404(session, listing_id, owner)
    try:
        sharing.unshare_item(session, owner, listing)
    except sharing.SharingError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(listing)
    return equipment.serialise(session, listing, owner)


@router.post("/equipment/{listing_id}/photos", response_model=EquipmentOut)
async def add_photo(
    listing_id: str, request: Request, session: Session = Depends(get_session)
) -> EquipmentOut:
    """Add a picture. The body is the image itself, as for profile photos."""
    owner = _owner(session)
    listing = _listing_or_404(session, listing_id, owner)
    if listing.profile_id != owner.id:
        raise HTTPException(status_code=403, detail="Only the seller can add pictures.")
    data = await request.body()
    try:
        media.save(
            session,
            entity_type="equipment",
            entity_id=listing.id,
            data=data,
            content_type=request.headers.get("content-type"),
        )
    except media.MediaError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(listing)
    return equipment.serialise(session, listing, owner)


@router.delete("/equipment/{listing_id}/photos/{media_id}", response_model=EquipmentOut)
def delete_photo(listing_id: str, media_id: str, session: Session = Depends(get_session)) -> EquipmentOut:
    owner = _owner(session)
    listing = _listing_or_404(session, listing_id, owner)
    file = session.get(MediaFile, media_id)
    if (
        listing.profile_id != owner.id
        or file is None
        or file.entity_type != "equipment"
        or file.entity_id != listing.id
    ):
        raise HTTPException(status_code=404, detail="Picture not found.")
    media.remove(session, file)
    session.commit()
    session.refresh(listing)
    return equipment.serialise(session, listing, owner)


# --------------------------------------------------------------------------- #
# Enquiries
# --------------------------------------------------------------------------- #


@router.post(
    "/equipment/{listing_id}/enquiries",
    response_model=EquipmentOut,
    status_code=status.HTTP_201_CREATED,
)
def send_enquiry(
    listing_id: str, payload: EnquiryInput, session: Session = Depends(get_session)
) -> EquipmentOut:
    """Ask to rent or buy. A pending enquiry is updated rather than doubled."""
    owner = _owner(session)
    listing = _listing_or_404(session, listing_id, owner)
    try:
        equipment.send_enquiry(session, owner, listing, payload)
    except EquipmentError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(listing)
    return equipment.serialise(session, listing, owner)


@router.get("/equipment-enquiries/mine", response_model=list[EquipmentOut])
def my_enquiries(session: Session = Depends(get_session)) -> list[EquipmentOut]:
    return equipment.my_enquiries(session, _owner(session))


@router.patch("/equipment-enquiries/{enquiry_id}", response_model=EquipmentOut)
def respond_to_enquiry(
    enquiry_id: str, payload: ResponseUpdate, session: Session = Depends(get_session)
) -> EquipmentOut:
    owner = _owner(session)
    enquiry = session.get(EquipmentEnquiry, enquiry_id)
    if enquiry is None or owner.id not in (enquiry.profile_id, enquiry.listing.profile_id):
        raise HTTPException(status_code=404, detail="Enquiry not found.")
    try:
        equipment.respond_enquiry(session, owner, enquiry, payload.status)
    except EquipmentError as exc:
        raise _fail(exc) from exc
    session.commit()
    listing = enquiry.listing
    session.refresh(listing)
    return equipment.serialise(session, listing, owner)


# --------------------------------------------------------------------------- #
# Partnerships
# --------------------------------------------------------------------------- #


@router.get("/equipment-partnerships", response_model=list[PartnershipOut])
def my_partnerships(session: Session = Depends(get_session)) -> list[PartnershipOut]:
    """Every partnership the owner is in, as seller or as partner."""
    return equipment.my_partnerships(session, _owner(session))


@router.post(
    "/equipment-partnerships", response_model=PartnershipOut, status_code=status.HTTP_201_CREATED
)
def add_partner(payload: PartnershipInput, session: Session = Depends(get_session)) -> PartnershipOut:
    """A seller adds a farmer, village, district or distributor to their network."""
    owner = _owner(session)
    try:
        partnership = equipment.add_partner(session, owner, payload)
    except EquipmentError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(partnership)
    return equipment.serialise_partnership(session, partnership, owner)


@router.post(
    "/equipment-sellers/{seller_id}/partnerships",
    response_model=PartnershipOut,
    status_code=status.HTTP_201_CREATED,
)
def ask_to_partner(
    seller_id: str, payload: PartnershipAsk, session: Session = Depends(get_session)
) -> PartnershipOut:
    """A farmer or distributor asks to become this seller's partner."""
    owner = _owner(session)
    seller = session.get(Profile, seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found.")
    try:
        partnership = equipment.ask_to_partner(session, owner, seller, payload)
    except EquipmentError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(partnership)
    return equipment.serialise_partnership(session, partnership, owner)


@router.patch("/equipment-partnerships/{partnership_id}", response_model=PartnershipOut)
def respond_to_partnership(
    partnership_id: str, payload: PartnershipUpdate, session: Session = Depends(get_session)
) -> PartnershipOut:
    owner = _owner(session)
    partnership = session.get(EquipmentPartnership, partnership_id)
    if partnership is None:
        raise HTTPException(status_code=404, detail="Partnership not found.")
    try:
        equipment.respond_partnership(session, owner, partnership, payload.status)
    except EquipmentError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(partnership)
    return equipment.serialise_partnership(session, partnership, owner)


# --------------------------------------------------------------------------- #
# The common timeline
# --------------------------------------------------------------------------- #


@router.get("/timeline", response_model=list[TimelineItemOut], tags=["timeline"])
def get_timeline(
    #: "updates" is land and updates from connections, together.
    kind: Literal["project", "equipment", "land", "updates"] | None = Query(default=None),
    state_code: str | None = Query(default=None, alias="stateCode"),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[TimelineItemOut]:
    """Everything shared online that the owner may see, newest first."""
    return timeline.feed(session, _owner(session), kind=kind, state_code=state_code, limit=limit)
