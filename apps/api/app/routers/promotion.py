"""Promoting a project: the packages on sale, and paying for one."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Profile
from ..schemas import PaymentOut, PromotionCheckoutInput, PromotionOut
from ..services import promotion, subscription
from ..services.subscription import SubscriptionError
from .deps import fail, owner

router = APIRouter(prefix="/investment-requests", tags=["promotion"])


@router.get("/{request_id}/promotion", response_model=PromotionOut)
def overview(request_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> PromotionOut:
    """How long a project is featured, and the packages that would feature it."""
    try:
        result = promotion.overview(session, me, request_id)
    except SubscriptionError as exc:
        raise fail(exc) from exc
    session.commit()
    return result


@router.post("/{request_id}/promotion/checkout", response_model=PaymentOut, status_code=201)
def checkout(
    request_id: str, payload: PromotionCheckoutInput, me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> PaymentOut:
    """A payment link for one package. The app opens it in the browser, then
    follows it with /subscription/payments/{id}/check like any payment."""
    try:
        row = promotion.checkout(session, me, request_id, payload.plan)
    except SubscriptionError as exc:
        session.commit()  # keep the device's registration, and anything a sync just did
        raise fail(exc) from exc
    session.commit()
    return subscription.serialise(row)
