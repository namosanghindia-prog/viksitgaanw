"""The common timeline: everything people have chosen to share online.

One feed, newest first, of farm projects and machines. It is "common" in that
every kind of user reads the same feed, but each still sees only what they are
allowed to: a project appears only for the kinds of profile its farmer chose
(and, for government, only in the officer's own area), while machines are
open to everyone. Your own shared items appear too, so you can see what others
see.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EquipmentListing, InvestmentRequest, Profile
from ..schemas import TimelineItemOut
from . import equipment, marketplace

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

    items.sort(key=lambda item: _when(item.shared_at), reverse=True)
    return items[:limit]
