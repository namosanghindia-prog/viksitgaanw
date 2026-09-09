"""Farmer records.

Phase 1 is single-user: the villager's own laptop or phone *is* the server for
that villager, so there is no login. Every parcel still hangs off a farmer row
because phase 2 (FPO grouping, investor matching, KYC) needs a real owner
identity, and backfilling one later would mean migrating live farm data.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Farmer
from .events import EventType, record_event

DEFAULT_FARMER_NAME = "This device"


def get_default_farmer(session: Session) -> Farmer | None:
    return session.scalars(select(Farmer).order_by(Farmer.created_at).limit(1)).first()


def get_or_create_default_farmer(session: Session) -> Farmer:
    """Return the device owner, creating a placeholder on first use.

    The placeholder is deliberately unnamed rather than fake: the onboarding
    screen fills in the real name, and nothing downstream should mistake the
    default for verified identity.
    """
    farmer = get_default_farmer(session)
    if farmer is not None:
        return farmer

    farmer = Farmer(name=DEFAULT_FARMER_NAME, preferred_language="hi")
    session.add(farmer)
    session.flush()
    record_event(
        session,
        EventType.FARMER_CREATED,
        entity_type="farmer",
        entity_id=farmer.id,
        payload={"bootstrap": True},
    )
    return farmer
