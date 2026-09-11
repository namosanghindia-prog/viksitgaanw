"""Paying for a subscription: plans, checkout, and following a payment."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Profile
from ..schemas import CheckoutInput, PaymentOut, SubscriptionOut
from ..services import subscription
from ..services.subscription import SubscriptionError
from .deps import fail, owner

router = APIRouter(prefix="/subscription", tags=["subscription"])


@router.get("", response_model=SubscriptionOut)
def overview(_: Profile = Depends(owner), session: Session = Depends(get_session)) -> SubscriptionOut:
    """The owner's subscription, the plans on sale, and their payments."""
    result = subscription.overview(session)
    session.commit()
    return result


@router.post("/checkout", response_model=PaymentOut, status_code=201)
def checkout(
    payload: CheckoutInput, _: Profile = Depends(owner), session: Session = Depends(get_session)
) -> PaymentOut:
    """A payment link for a plan. The app opens it in the browser."""
    try:
        row = subscription.checkout(session, payload.plan)
    except SubscriptionError as exc:
        # Keep the device's registration even though the checkout failed: the
        # server has it now, and would refuse the same profile a second time.
        session.commit()
        raise fail(exc) from exc
    session.commit()
    return subscription.serialise(row)


@router.post("/payments/{payment_id}/check", response_model=PaymentOut)
def check(payment_id: str, _: Profile = Depends(owner), session: Session = Depends(get_session)) -> PaymentOut:
    """Ask the server whether a payment has gone through."""
    try:
        row = subscription.check(session, payment_id)
    except SubscriptionError as exc:
        session.commit()  # keep what was learnt before the failure
        raise fail(exc) from exc
    session.commit()
    return subscription.serialise(row)
