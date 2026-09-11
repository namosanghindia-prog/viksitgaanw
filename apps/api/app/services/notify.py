"""Notifications for the device owner.

A notification is only ever written for the owner of this device. When
something happens to someone on another device, *their* device notices it on
its next sync and writes its own. That keeps one rule simple: this table is
the owner's inbox and nothing else.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import InsurancePolicy, InvestmentRequest, LandParcel, Message, Notification, Profile
from ..schemas import InboxCounts, NotificationOut


def _owner_id(session: Session) -> str | None:
    return session.scalar(select(Profile.id).where(Profile.is_device_owner.is_(True)))


def notify(
    session: Session,
    profile_id: str | None,
    kind: str,
    *,
    params: dict[str, Any] | None = None,
    link: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    once: bool = False,
) -> Notification | None:
    """Tell the owner something. A no-op when ``profile_id`` is someone else.

    With ``once``, a second notification of the same kind about the same
    thing is not created -- used for reminders that are re-checked on every
    visit, such as a policy about to expire.
    """
    if not profile_id or profile_id != _owner_id(session):
        return None
    if once and entity_id:
        session.flush()
        existing = session.scalars(
            select(Notification).where(
                Notification.profile_id == profile_id,
                Notification.kind == kind,
                Notification.entity_id == entity_id,
            )
        ).first()
        if existing:
            return existing
    note = Notification(
        profile_id=profile_id,
        kind=kind,
        params=params or {},
        link=link,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    session.add(note)
    return note


def serialise(note: Notification) -> NotificationOut:
    return NotificationOut(
        id=note.id,
        kind=note.kind,
        params=note.params or {},
        link=note.link,
        entity_type=note.entity_type,
        entity_id=note.entity_id,
        read=note.read_at is not None,
        created_at=note.created_at,
    )


def inbox(session: Session, owner: Profile, *, unread_only: bool = False, limit: int = 100) -> list[NotificationOut]:
    refresh_reminders(session, owner)
    stmt = (
        select(Notification)
        .where(Notification.profile_id == owner.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return [serialise(note) for note in session.scalars(stmt)]


def counts(session: Session, owner: Profile) -> InboxCounts:
    refresh_reminders(session, owner)
    unread = session.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.profile_id == owner.id, Notification.read_at.is_(None)
        )
    )
    messages = session.scalar(
        select(func.count()).select_from(Message).where(
            Message.recipient_profile_id == owner.id, Message.read_at.is_(None)
        )
    )
    return InboxCounts(notifications=unread or 0, messages=messages or 0)


def mark_read(session: Session, owner: Profile, ids: list[str]) -> int:
    stmt = select(Notification).where(
        Notification.profile_id == owner.id, Notification.read_at.is_(None)
    )
    if ids:
        stmt = stmt.where(Notification.id.in_(ids))
    now = datetime.now(timezone.utc)
    rows = list(session.scalars(stmt))
    for note in rows:
        note.read_at = now
    return len(rows)


def refresh_reminders(session: Session, owner: Profile, today: date | None = None) -> None:
    """Reminders that come from the calendar rather than from anyone's action.

    Today that is insurance about to lapse: 30 days' notice on any policy the
    owner holds -- on their profile, their land, or their projects.
    """
    today = today or date.today()
    horizon = today + timedelta(days=30)

    parcel_ids = select(LandParcel.id).where(LandParcel.farmer_id == owner.farmer_id) if owner.farmer_id else None
    request_ids = select(InvestmentRequest.id).where(InvestmentRequest.profile_id == owner.id)
    ownership = [InsurancePolicy.profile_id == owner.id, InsurancePolicy.request_id.in_(request_ids)]
    if parcel_ids is not None:
        ownership.append(InsurancePolicy.parcel_id.in_(parcel_ids))

    expiring = session.scalars(
        select(InsurancePolicy).where(
            InsurancePolicy.status == "insured",
            InsurancePolicy.valid_until.is_not(None),
            InsurancePolicy.valid_until >= today,
            InsurancePolicy.valid_until <= horizon,
            or_(*ownership),
        )
    )
    for policy in expiring:
        notify(
            session,
            owner.id,
            "insurance_expiring",
            params={"category": policy.category, "date": policy.valid_until.isoformat()},
            link=(
                f"/land/{policy.parcel_id}/insurance"
                if policy.parcel_id
                else "/requests" if policy.request_id else "/profile"
            ),
            entity_type="insurance_policy",
            entity_id=policy.id,
            once=True,
        )
    # The session does not autoflush, and the caller reads the inbox next.
    session.flush()
