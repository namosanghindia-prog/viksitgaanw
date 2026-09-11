"""Shared land and farm updates: what a farmer shows their connections.

A plot is private until its owner shares it. Shared, it appears on the
timeline of the owner's connections (see services/connections) as a card built
from a snapshot of the plot: where it is (village, block, district, state),
how big, the soil, the water, what grows there, and pictures. The survey
number, the exact map pin, notes and ownership never leave the plot.

Editing a shared plot refreshes the card and marks it updated, so connections
see the change. Updates are short posts -- "sowing done", "first picking" --
with a picture, shown to the same people.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import FarmUpdate, LandParcel, LandShare, Profile
from ..schemas import FarmUpdateInput, FarmUpdateOut, LandShareOut, MediaOut
from . import media
from .events import EventType, enqueue_sync, record_event
from .hierarchy import resolve_location

LAND = "land_share"
UPDATE = "farm_update"


class ShareError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _photos(session: Session, entity_type: str, entity_id: str) -> list[MediaOut]:
    return [
        MediaOut(id=f.id, url=media.url_for(f), width=f.width, height=f.height, position=f.position)
        for f in media.for_entity(session, entity_type, entity_id)
    ]


# --------------------------------------------------------------------------- #
# Land
# --------------------------------------------------------------------------- #


def snapshot(session: Session, parcel: LandParcel) -> dict[str, Any]:
    """What connections may know about a plot -- and nothing more."""
    path = resolve_location(
        session,
        village_code=parcel.village_code,
        subdistrict_code=parcel.subdistrict_code,
        district_code=parcel.district_code,
        state_code=parcel.state_code,
    )
    place = ", ".join(
        unit.name for unit in (path.village, path.subdistrict, path.district, path.state) if unit is not None
    )
    return {
        "label": parcel.label,
        "place": place or None,
        "state_code": parcel.state_code,
        "area_value": parcel.area_value,
        "area_unit": parcel.area_unit,
        "area_hectares": round(parcel.area_hectares, 3),
        "soil_type": parcel.soil_type,
        "water_sources": list(parcel.water_sources or []),
        "water_type": parcel.water_type,
        "irrigation_type": parcel.irrigation_type,
        "existing_crops": list(parcel.existing_crops or []),
    }


def owned_parcel(session: Session, owner: Profile, parcel_id: str) -> LandParcel:
    parcel = session.get(LandParcel, parcel_id)
    if parcel is None or (owner.farmer_id and parcel.farmer_id != owner.farmer_id):
        raise ShareError("Land parcel not found.", 404)
    return parcel


def share_for(session: Session, parcel_id: str) -> LandShare | None:
    return session.get(LandShare, parcel_id)


def share_land(session: Session, owner: Profile, parcel: LandParcel) -> LandShare:
    from .sharing import require_online  # noqa: PLC0415

    if owner.segment != "farmer":
        raise ShareError("Only a farmer's own land can be shared.", 403)
    require_online(owner)
    share = share_for(session, parcel.id)
    if share is None:
        share = LandShare(id=parcel.id, profile_id=owner.id, parcel_id=parcel.id, origin="local")
        session.add(share)
    if share.visibility == "online":
        return share
    share.snapshot = snapshot(session, parcel)
    share.visibility = "online"
    share.shared_at = _now()
    share.changed_at = None
    # Not yet seen by anyone: see _mark_changed.
    share.sync_state = "local_only"
    session.flush()
    record_event(session, EventType.LAND_SHARED, entity_type=LAND, entity_id=share.id)
    enqueue_sync(session, entity_type=LAND, entity_id=share.id, operation="share")
    return share


def unshare_land(session: Session, owner: Profile, parcel: LandParcel) -> LandShare | None:
    share = share_for(session, parcel.id)
    if share is None or share.visibility != "online":
        return share
    share.visibility = "offline"
    record_event(session, EventType.LAND_UNSHARED, entity_type=LAND, entity_id=share.id)
    enqueue_sync(session, entity_type=LAND, entity_id=share.id, operation="unshare")
    return share


def _mark_changed(share: LandShare) -> None:
    """Mark the card updated -- once connections may already have seen it.

    Until the card has left the device, nobody else has seen it, so a picture
    added straight after sharing is part of sharing it, not an update.
    """
    if share.sync_state != "local_only":
        share.changed_at = _now()
        share.sync_state = "queued"


def refresh(session: Session, parcel: LandParcel) -> None:
    """The plot changed: bring its shared card up to date, marked as updated."""
    share = share_for(session, parcel.id)
    if share is None or share.visibility != "online":
        return
    fresh = snapshot(session, parcel)
    if fresh == share.snapshot:
        # A change only in private fields (survey number, notes, pin).
        return
    share.snapshot = fresh
    _mark_changed(share)
    enqueue_sync(session, entity_type=LAND, entity_id=share.id, operation="update")


def touch(session: Session, parcel_id: str) -> None:
    """A picture was added or removed: connections see the plot as updated."""
    share = share_for(session, parcel_id)
    if share is not None and share.visibility == "online":
        _mark_changed(share)
        enqueue_sync(session, entity_type=LAND, entity_id=share.id, operation="update")


def forget_parcel(session: Session, parcel_id: str) -> None:
    """The plot is being deleted: take its card down everywhere."""
    share = share_for(session, parcel_id)
    if share is not None:
        enqueue_sync(session, entity_type=LAND, entity_id=share.id, operation="delete")
        session.delete(share)
    media.remove_all(session, "land", parcel_id)


def serialise_land(session: Session, share: LandShare, viewer: Profile | None) -> LandShareOut:
    from .profiles import card  # noqa: PLC0415

    snap = share.snapshot or {}
    updates = session.scalar(
        select(func.count()).select_from(FarmUpdate).where(
            FarmUpdate.land_share_id == share.id, FarmUpdate.visibility == "online"
        )
    )
    return LandShareOut(
        id=share.id,
        owner=card(session, share.profile),
        is_mine=bool(viewer and share.profile_id == viewer.id),
        label=snap.get("label") or "",
        place=snap.get("place"),
        state_code=snap.get("state_code"),
        area_value=snap.get("area_value"),
        area_unit=snap.get("area_unit"),
        area_hectares=snap.get("area_hectares"),
        soil_type=snap.get("soil_type"),
        water_sources=snap.get("water_sources") or [],
        water_type=snap.get("water_type"),
        irrigation_type=snap.get("irrigation_type"),
        existing_crops=snap.get("existing_crops") or [],
        photos=_photos(session, "land", share.id),
        visibility=share.visibility,
        shared_at=share.shared_at,
        changed_at=share.changed_at,
        updates=updates or 0,
        origin=share.origin,
    )


# --------------------------------------------------------------------------- #
# Updates
# --------------------------------------------------------------------------- #


def post_update(session: Session, owner: Profile, data: FarmUpdateInput) -> FarmUpdate:
    from .sharing import require_online  # noqa: PLC0415

    require_online(owner)
    if data.land_share_id:
        share = share_for(session, data.land_share_id)
        if share is None or share.profile_id != owner.id:
            raise ShareError("That plot is not yours.", 404)
        if share.visibility != "online":
            raise ShareError("Share the plot with your connections first.")
    update = FarmUpdate(profile_id=owner.id, land_share_id=data.land_share_id, body=data.body, origin="local")
    session.add(update)
    session.flush()
    record_event(session, EventType.UPDATE_POSTED, entity_type=UPDATE, entity_id=update.id,
                 payload={"with_land": bool(data.land_share_id)})
    enqueue_sync(session, entity_type=UPDATE, entity_id=update.id, operation="create")
    return update


def owned_update(session: Session, owner: Profile, update_id: str) -> FarmUpdate:
    update = session.get(FarmUpdate, update_id)
    if update is None or update.profile_id != owner.id:
        raise ShareError("Update not found.", 404)
    return update


def delete_update(session: Session, owner: Profile, update: FarmUpdate) -> None:
    record_event(session, EventType.UPDATE_REMOVED, entity_type=UPDATE, entity_id=update.id)
    enqueue_sync(session, entity_type=UPDATE, entity_id=update.id, operation="delete")
    media.remove_all(session, "update", update.id)
    session.delete(update)


def serialise_update(session: Session, update: FarmUpdate, viewer: Profile | None) -> FarmUpdateOut:
    from .profiles import card  # noqa: PLC0415

    share = share_for(session, update.land_share_id) if update.land_share_id else None
    return FarmUpdateOut(
        id=update.id,
        owner=card(session, session.get(Profile, update.profile_id)),
        is_mine=bool(viewer and update.profile_id == viewer.id),
        body=update.body,
        land_share_id=update.land_share_id,
        land_label=(share.snapshot or {}).get("label") if share and share.visibility == "online" else None,
        photos=_photos(session, "update", update.id),
        created_at=update.created_at,
        origin=update.origin,
    )


# --------------------------------------------------------------------------- #
# Who sees what
# --------------------------------------------------------------------------- #


def visible_lands(session: Session, viewer: Profile, connected: set[str]) -> list[LandShare]:
    audience = connected | {viewer.id}
    return list(
        session.scalars(
            select(LandShare).where(LandShare.visibility == "online", LandShare.profile_id.in_(audience))
        )
    )


def visible_updates(
    session: Session, viewer: Profile, connected: set[str], land_share_id: str | None = None
) -> list[FarmUpdate]:
    audience = connected | {viewer.id}
    stmt = select(FarmUpdate).where(FarmUpdate.visibility == "online", FarmUpdate.profile_id.in_(audience))
    if land_share_id:
        stmt = stmt.where(FarmUpdate.land_share_id == land_share_id)
    return list(session.scalars(stmt.order_by(FarmUpdate.created_at.desc())))


def unshare_everything(session: Session, owner: Profile) -> int:
    """The owner took their profile offline: their land and updates go with it."""
    count = 0
    for share in session.scalars(
        select(LandShare).where(LandShare.profile_id == owner.id, LandShare.visibility == "online")
    ):
        share.visibility = "offline"
        enqueue_sync(session, entity_type=LAND, entity_id=share.id, operation="unshare")
        count += 1
    for update in session.scalars(
        select(FarmUpdate).where(FarmUpdate.profile_id == owner.id, FarmUpdate.visibility == "online")
    ):
        update.visibility = "offline"
        enqueue_sync(session, entity_type=UPDATE, entity_id=update.id, operation="unshare")
        count += 1
    return count
