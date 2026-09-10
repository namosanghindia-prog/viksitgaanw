"""Event logging and the offline sync outbox.

Both exist from day one on purpose. The monetisation plan meters completed
deals and generated reports, and the app has to work with no internet at all,
so writes are recorded locally and queued rather than pushed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import AppEvent, SyncQueueEntry


class EventType:
    """Known event names. Keep these stable: they are billing inputs."""

    PARCEL_CREATED = "land_parcel.created"
    PARCEL_UPDATED = "land_parcel.updated"
    PARCEL_DELETED = "land_parcel.deleted"
    FARMER_CREATED = "farmer.created"
    PROFILE_CREATED = "profile.created"
    PROFILE_UPDATED = "profile.updated"
    PROFILE_DELETED = "profile.deleted"
    REQUEST_CREATED = "investment_request.created"
    REQUEST_UPDATED = "investment_request.updated"
    INTEREST_SENT = "investment_interest.sent"
    INTEREST_UPDATED = "investment_interest.updated"
    #: A farmer accepted an investor or partner. The unit the success fee
    #: will eventually be measured against, so it is its own event rather than
    #: a status inside INTEREST_UPDATED.
    MATCH_MADE = "investment_interest.accepted"
    INSURANCE_ADDED = "insurance_policy.added"
    INSURANCE_UPDATED = "insurance_policy.updated"
    INSURANCE_REMOVED = "insurance_policy.removed"
    REPORT_GENERATED = "project_report.generated"
    # Reserved: needs the milestone-based trust layer before real money moves.
    DEAL_COMPLETED = "deal.completed"


def record_event(
    session: Session,
    event_type: str,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AppEvent:
    """Append an event. The caller owns the transaction."""
    event = AppEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload or {},
    )
    session.add(event)
    return event


def enqueue_sync(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    operation: str,
    payload: dict[str, Any] | None = None,
) -> SyncQueueEntry:
    """Queue a local change for the eventual cloud push.

    Nothing drains this queue yet -- the cloud endpoint is a phase-2 concern.
    Writing to it now means the sync worker can be added later without
    backfilling history or touching any of the write paths.
    """
    entry = SyncQueueEntry(
        entity_type=entity_type,
        entity_id=entity_id,
        operation=operation,
        payload=payload or {},
        status="pending",
    )
    session.add(entry)
    return entry
