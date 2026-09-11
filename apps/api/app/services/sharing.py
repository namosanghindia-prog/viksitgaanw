"""Share online / take offline, for projects and machines.

Everything a user makes starts **offline**: it lives on their device and
nobody else sees it. Pressing *Share online* puts it on the common timeline
(and queues it for the cloud once sync exists); *Take offline* removes it.

Two rules hold throughout:

* An item can only be shared once the owner's profile is shared, because a
  project or a tractor with no visible person behind it is not something
  anyone should act on. The UI asks first and shares both together.
* Taking an item offline stops it being shown from now on. It cannot recall
  a copy another device has already received, and the UI says so.

The sync worker, when it is built, must publish only ``online`` items to the
shared marketplace. Offline items may go at most to the owner's own backup.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EquipmentListing, FarmerGroup, InvestmentRequest, Profile
from .events import EventType, enqueue_sync, record_event

ENTITY_NAMES = {
    InvestmentRequest: "investment_request",
    EquipmentListing: "equipment_listing",
    FarmerGroup: "farmer_group",
}

Shareable = InvestmentRequest | EquipmentListing | FarmerGroup


def _owner_id(item: Shareable) -> str:
    return item.owner_profile_id if isinstance(item, FarmerGroup) else item.profile_id


class SharingError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def require_online(profile: Profile) -> None:
    if profile.visibility != "online":
        raise SharingError(
            "Share your profile online first, so others can see who they are dealing with."
        )


def share_item(session: Session, owner: Profile, item: Shareable) -> None:
    if _owner_id(item) != owner.id:
        raise SharingError("Only the owner can share this.", 403)
    require_online(owner)
    if item.visibility == "online":
        return
    item.visibility = "online"
    item.shared_at = _now()
    entity = ENTITY_NAMES[type(item)]
    record_event(session, EventType.SHARED_ONLINE, entity_type=entity, entity_id=item.id)
    enqueue_sync(session, entity_type=entity, entity_id=item.id, operation="share")


def unshare_item(session: Session, owner: Profile, item: Shareable) -> None:
    if _owner_id(item) != owner.id:
        raise SharingError("Only the owner can take this offline.", 403)
    if item.visibility != "online":
        return
    item.visibility = "offline"
    entity = ENTITY_NAMES[type(item)]
    record_event(session, EventType.TAKEN_OFFLINE, entity_type=entity, entity_id=item.id)
    enqueue_sync(session, entity_type=entity, entity_id=item.id, operation="unshare")


def unshare_all_items(session: Session, owner: Profile) -> int:
    count = 0
    for model in (InvestmentRequest, EquipmentListing, FarmerGroup):
        column = model.owner_profile_id if model is FarmerGroup else model.profile_id
        for item in session.scalars(
            select(model).where(column == owner.id, model.visibility == "online")
        ):
            unshare_item(session, owner, item)
            count += 1
    return count
