"""Paying for a subscription, from the device.

A subscription is prepaid for some months. For now it lets its owner upload
videos directly instead of linking them on YouTube (services/videos.py); the
core app stays free.

The sync server does the paying. It holds the payment provider's keys, makes a
payment link for the chosen plan, and alone decides that a payment went
through -- a device cannot mark itself paid. The device opens the link in the
browser (UPI, cards, netbanking), then asks the server how the payment is
getting on until it is paid or has lapsed. Asking again on every sync catches a
payment made after the app was closed.

What the device keeps is a receipt per payment (``SubscriptionPayment``), and
an ``app_events`` entry for each checkout and each payment that goes through:
the revenue line the monetisation plan counts.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SubscriptionPayment
from ..schemas import PaymentOut, PlanOut, SubscriptionOut
from . import videos
from .events import EventType, record_event


class SubscriptionError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _detail(exc: Exception) -> str:
    """The server's own words from a failed call, rather than the raw response."""
    text = str(exc)
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            detail = json.loads(match.group(0)).get("detail")
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, str):
            return detail
    return text


def _connect(session: Session, transport: Any) -> tuple[Any, str]:
    """The sync server and this device's token there."""
    from . import sync_client  # noqa: PLC0415 - sync_client imports videos, which this imports
    from .profiles import get_owner  # noqa: PLC0415

    url = sync_client._get(session, "server_url")
    owner = get_owner(session)
    if not url or owner is None:
        raise SubscriptionError(
            "Payments go through the sync server: switch sync on first (More → My data & sync).", 409
        )
    transport = transport or sync_client.HttpTransport(url)
    try:
        return transport, sync_client._register(session, transport, owner)
    except sync_client.SyncError as exc:
        raise SubscriptionError(_detail(exc), 503) from exc


def _call(session: Session, transport: Any, method: str, path: str, body: dict | None = None) -> dict:
    from .sync_client import SyncError  # noqa: PLC0415

    transport, token = _connect(session, transport)
    try:
        if method == "POST":
            return transport.post(path, body or {}, token)
        return transport.get(path, {}, token)
    except SyncError as exc:
        raise SubscriptionError(_detail(exc), exc.status) from exc


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _save(session: Session, data: dict[str, Any]) -> tuple[SubscriptionPayment, bool]:
    """Keep the server's word on a payment. Returns the receipt, and whether it has just gone through."""
    from .notify import notify  # noqa: PLC0415
    from .profiles import get_owner  # noqa: PLC0415

    row = session.get(SubscriptionPayment, data["id"])
    if row is None:
        row = SubscriptionPayment(id=data["id"])
        session.add(row)
    was = row.status
    row.plan = data["plan"]
    row.plan_name = data["planName"]
    row.amount_paise = data["amountPaise"]
    row.months = data["months"]
    row.url = data.get("url")
    row.status = data["status"]
    row.until = date.fromisoformat(data["until"]) if data.get("until") else None
    row.expires_at = _when(data.get("expiresAt"))
    row.created_at = _when(data.get("createdAt")) or datetime.now(timezone.utc)
    row.paid_at = _when(data.get("paidAt"))
    row.kind = data.get("kind") or "subscription"
    row.days = data.get("days")
    row.target_id = data.get("targetId")
    session.flush()

    went_through = row.status == "paid" and was != "paid"
    if went_through and row.kind == "promotion":
        from . import promotion  # noqa: PLC0415 - promotion imports this module

        promotion.on_paid(session, row, data.get("promotion"))
    elif went_through:
        record_event(
            session, EventType.SUBSCRIPTION_PAID, entity_type="subscription_payment", entity_id=row.id,
            payload={"plan": row.plan, "amount_paise": row.amount_paise, "months": row.months},
        )
        owner = get_owner(session)
        notify(
            session, owner.id if owner else None, "subscription_paid",
            # "date" is the param the app formats as a date in the reader's language.
            params={"plan": row.plan_name, "date": row.until.isoformat() if row.until else ""},
            link="/subscription", entity_type="subscription_payment", entity_id=row.id,
        )
    return row, went_through


def serialise(row: SubscriptionPayment) -> PaymentOut:
    return PaymentOut(
        id=row.id,
        plan=row.plan,
        plan_name=row.plan_name,
        amount_paise=row.amount_paise,
        months=row.months,
        url=row.url if row.status == "created" else None,
        status=row.status,  # type: ignore[arg-type]
        until=row.until,
        expires_at=row.expires_at,
        created_at=row.created_at,
        paid_at=row.paid_at,
        kind=row.kind or "subscription",  # type: ignore[arg-type]
        days=row.days,
        target_id=row.target_id,
    )


def _receipts(session: Session) -> list[PaymentOut]:
    rows = session.scalars(select(SubscriptionPayment).order_by(SubscriptionPayment.created_at.desc()).limit(20))
    return [serialise(row) for row in rows]


def checkout(session: Session, plan_code: str, transport: Any = None) -> SubscriptionPayment:
    """A payment link for one plan, from the server, to open in the browser."""
    answer = _call(session, transport, "POST", "/v1/payments", {"plan": plan_code})
    row, _ = _save(session, answer)
    record_event(
        session, EventType.SUBSCRIPTION_CHECKOUT, entity_type="subscription_payment", entity_id=row.id,
        payload={"plan": row.plan, "amount_paise": row.amount_paise},
    )
    return row


def check(session: Session, payment_id: str, transport: Any = None) -> SubscriptionPayment:
    """Ask the server how one payment is getting on."""
    row = session.get(SubscriptionPayment, payment_id)
    if row is None:
        raise SubscriptionError("Payment not found.", 404)
    if row.status != "created":
        return row
    row, went_through = _save(session, _call(session, transport, "GET", f"/v1/payments/{payment_id}"))
    if went_through and row.kind == "subscription":
        # Upload rights follow the subscription; refresh them now, not at the next look.
        videos.plan(session, transport)
    return row


def check_pending(session: Session, transport: Any = None) -> int:
    """Ask about every payment still open. Returns how many went through."""
    now = datetime.now(timezone.utc)
    pending = [
        row for row in session.scalars(select(SubscriptionPayment).where(SubscriptionPayment.status == "created"))
        if row.expires_at is None or _aware(row.expires_at) > now
    ]
    paid = 0
    for row in pending:
        try:
            paid += check(session, row.id, transport).status == "paid"
        except SubscriptionError:
            break  # offline, or sync off: next time
    return paid


def overview(session: Session, transport: Any = None) -> SubscriptionOut:
    """The subscription, the plans on sale and the owner's receipts -- as far as can be known now."""
    reason: str | None = None
    plans: list[PlanOut] = []
    available = False
    try:
        check_pending(session, transport)
        answer = _call(session, transport, "GET", "/v1/plans")
    except SubscriptionError as exc:
        answer = None
        reason = "sync_off" if exc.status == 409 else "offline"
    status = videos.plan(session, transport)
    if answer is not None:
        available = bool(answer.get("paymentsAvailable"))
        plans = [
            PlanOut(code=p["code"], name=p["name"], amount_paise=p["amountPaise"], months=p["months"])
            for p in answer.get("plans") or []
            # Promotions are bought from the project they promote, not here.
            if p.get("kind", "subscription") == "subscription"
        ]
        if status.subscribed and status.until is None:
            reason = "no_end"
        elif not available:
            reason = "payments_off"
        elif not plans:
            reason = "no_plans"
    return SubscriptionOut(
        status=status, payments_available=available, plans=plans, payments=_receipts(session), reason=reason
    )
