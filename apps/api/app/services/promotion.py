"""Promoting a project: a paid place at the top of investors' and partners' lists.

A farmer who has shared a project online can buy days of promotion for it --
a package the sync server's operator prices, like "Featured for 7 days", or
one that also alerts, once, the investors and partners the project suits. The
project then comes first in their lists and on the common timeline, and every
card says it is promoted: an advertisement must look like one.

The sync server does the paying, as for a subscription (services/subscription.py,
whose payment calls and receipts this shares), and alone records a promotion:
it stamps ``promoted_until`` onto the project everyone pulls, and whatever a
device pushes is overwritten. The owner's device learns its own promotion from
the payment -- or, for one the operator granted, by asking (``refresh``).

Each checkout and each promotion that goes through is an ``app_events`` entry,
with the amount in paise: a revenue line the monetisation plan counts.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import InvestmentRequest, Profile, SubscriptionPayment
from ..schemas import PromotionOut, PromotionPlanOut
from . import subscription
from .events import EventType, record_event
from .marketplace import REQUEST_ENTITY, is_featured
from .subscription import SubscriptionError

#: The server calls the project this, in a promotion's target.
TARGET = "investment_request"


def _own_request(session: Session, owner: Profile, request_id: str) -> InvestmentRequest:
    request = session.get(InvestmentRequest, request_id)
    if request is None:
        raise SubscriptionError("Project not found.", 404)
    if request.profile_id != owner.id:
        raise SubscriptionError("You can promote only your own projects.", 403)
    return request


def _apply(session: Session, promotion: dict[str, Any] | None) -> None:
    """Keep the server's word on one of the owner's projects."""
    if not promotion or promotion.get("entityType") != TARGET:
        return
    request = session.get(InvestmentRequest, promotion["entityId"])
    if request is None:
        return
    request.promoted_until = date.fromisoformat(promotion["until"]) if promotion.get("until") else None
    alert_at = promotion.get("alertAt")
    request.promotion_alert_at = datetime.fromisoformat(alert_at) if alert_at else None


def on_paid(session: Session, payment: SubscriptionPayment, promotion: dict[str, Any] | None) -> None:
    """A promotion went through: feature the project here too, count it, and say so."""
    from .notify import notify  # noqa: PLC0415
    from .profiles import get_owner  # noqa: PLC0415

    _apply(session, promotion)
    request = session.get(InvestmentRequest, payment.target_id) if payment.target_id else None
    if request is not None and promotion is None and payment.until:
        request.promoted_until = payment.until  # an older server that does not say
    record_event(
        session, EventType.PROMOTION_PAID, entity_type=REQUEST_ENTITY, entity_id=payment.target_id,
        payload={"plan": payment.plan, "amount_paise": payment.amount_paise, "days": payment.days},
    )
    owner = get_owner(session)
    notify(
        session, owner.id if owner else None, "promotion_paid",
        params={"title": request.title if request else "", "date": payment.until.isoformat() if payment.until else ""},
        link="/requests", entity_type=REQUEST_ENTITY, entity_id=payment.target_id,
    )


def refresh(session: Session, transport: Any = None) -> None:
    """Ask the server about the owner's promotions -- the operator may have granted one."""
    answer = subscription._call(session, transport, "GET", "/v1/promotions")
    for promotion in answer.get("promotions") or []:
        _apply(session, promotion)


def _why_not(request: InvestmentRequest) -> str | None:
    if request.status != "open":
        return "closed"
    if request.visibility != "online":
        return "not_shared"
    return None


def overview(session: Session, owner: Profile, request_id: str, transport: Any = None) -> PromotionOut:
    """One project's promotion: how long it is featured, the packages on sale, and what was paid."""
    request = _own_request(session, owner, request_id)
    reason = _why_not(request)
    plans: list[PromotionPlanOut] = []
    available = False
    if reason is None:
        try:
            subscription.check_pending(session, transport)
            refresh(session, transport)
            answer = subscription._call(session, transport, "GET", "/v1/plans")
        except SubscriptionError as exc:
            reason = "sync_off" if exc.status == 409 else "offline"
        else:
            available = bool(answer.get("paymentsAvailable"))
            plans = [
                PromotionPlanOut(code=p["code"], name=p["name"], amount_paise=p["amountPaise"],
                                 days=p.get("days") or 0, alert=bool(p.get("alert")))
                for p in answer.get("plans") or []
                if p.get("kind") == "promotion"
            ]
            if not available:
                reason = "payments_off"
            elif not plans:
                reason = "no_plans"
    receipts = session.scalars(
        select(SubscriptionPayment)
        .where(SubscriptionPayment.target_id == request.id)
        .order_by(SubscriptionPayment.created_at.desc())
    )
    return PromotionOut(
        request_id=request.id,
        promoted_until=request.promoted_until,
        featured=is_featured(request),
        payments_available=available,
        plans=plans,
        payments=[subscription.serialise(row) for row in receipts],
        reason=reason,
    )


def checkout(session: Session, owner: Profile, request_id: str, plan_code: str,
             transport: Any = None) -> SubscriptionPayment:
    """A payment link for one package, for one of the owner's shared, open projects."""
    from . import sync_client  # noqa: PLC0415

    request = _own_request(session, owner, request_id)
    reason = _why_not(request)
    if reason == "closed":
        raise SubscriptionError("Only an open project can be promoted.")
    if reason == "not_shared":
        raise SubscriptionError("Share the project online first, then promote it.")
    if request.sync_state != "synced":
        # The server promotes the project it holds: make sure it holds this one.
        try:
            sync_client.run(session, transport)
        except sync_client.SyncError as exc:
            raise SubscriptionError(subscription._detail(exc), exc.status) from exc
    answer = subscription._call(
        session, transport, "POST", "/v1/payments",
        {"plan": plan_code, "target_type": TARGET, "target_id": request.id},
    )
    row, _ = subscription._save(session, answer)
    record_event(
        session, EventType.PROMOTION_CHECKOUT, entity_type=REQUEST_ENTITY, entity_id=request.id,
        payload={"plan": row.plan, "amount_paise": row.amount_paise, "days": row.days},
    )
    return row
