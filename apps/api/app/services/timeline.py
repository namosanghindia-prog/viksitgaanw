"""The common timeline: everything people have chosen to share.

One feed, newest first, of farm projects, machines, land and farm updates. It
is "common" in that every kind of user reads the same feed, but each still sees
only what they are allowed to: a project appears only for the kinds of profile
its farmer chose (and, for government, only in the officer's own area);
machines are open to everyone; land and updates only to the owner's
connections. Your own shared items appear too, so you can see what others see.

A shared plot that changes moves back up the feed, marked as updated.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EquipmentListing, InvestmentRequest, Profile
from ..schemas import TimelineItemOut
from . import connections, equipment, landshare, marketplace

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _when(value: datetime | None) -> datetime:
    if value is None:
        return _EPOCH
    # SQLite hands back naive datetimes; treat them as the UTC they were written in.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def feed(
    session: Session,
    viewer: Profile,
    *,
    kind: str | None = None,
    state_code: str | None = None,
    limit: int = 100,
) -> list[TimelineItemOut]:
    items: list[TimelineItemOut] = []

    if kind in (None, "project"):
        stmt = select(InvestmentRequest).where(
            InvestmentRequest.visibility == "online", InvestmentRequest.status == "open"
        )
        if state_code:
            stmt = stmt.where(InvestmentRequest.state_code == state_code)
        for request in session.scalars(stmt):
            if marketplace.visible_to(request, viewer):
                items.append(
                    TimelineItemOut(
                        type="project",
                        id=request.id,
                        shared_at=request.shared_at,
                        project=marketplace.serialise_request(session, request, viewer),
                    )
                )

    if kind in (None, "equipment"):
        stmt = select(EquipmentListing).where(
            EquipmentListing.visibility == "online", EquipmentListing.status == "active"
        )
        if state_code:
            stmt = stmt.where(EquipmentListing.state_code == state_code)
        for listing in session.scalars(stmt):
            items.append(
                TimelineItemOut(
                    type="equipment",
                    id=listing.id,
                    shared_at=listing.shared_at,
                    equipment=equipment.serialise(session, listing, viewer),
                )
            )

    # "land" is shared plots only; "updates" is everything from connections.
    if kind in (None, "land", "updates"):
        connected = connections.connected_ids(session, viewer.id)
        for share in landshare.visible_lands(session, viewer, connected):
            if state_code and (share.snapshot or {}).get("state_code") != state_code:
                continue
            items.append(
                TimelineItemOut(
                    type="land",
                    id=share.id,
                    # An edit brings the plot back to the top.
                    shared_at=max(_when(share.shared_at), _when(share.changed_at)),
                    land=landshare.serialise_land(session, share, viewer),
                )
            )
        if kind != "land":
            for update in landshare.visible_updates(session, viewer, connected):
                items.append(
                    TimelineItemOut(
                        type="update",
                        id=update.id,
                        shared_at=update.created_at,
                        update=landshare.serialise_update(session, update, viewer),
                    )
                )

    items.sort(key=lambda item: _when(item.shared_at), reverse=True)
    return items[:limit]
