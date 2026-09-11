"""Loans: lenders' products, and applications with a project report."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import LoanApplication, LoanProduct, Profile
from ..schemas import (
    LoanApplicationInput,
    LoanApplicationOut,
    LoanDecisionInput,
    LoanProductInput,
    LoanProductOut,
)
from ..services import loans, sharing
from ..services.loans import LoanError
from ..services.sharing import SharingError
from .deps import fail, owner

router = APIRouter(tags=["loans"])


def _product(session: Session, product_id: str) -> LoanProduct:
    product = session.get(LoanProduct, product_id)
    if product is None:
        raise fail(LoanError("Loan not found.", 404))
    return product


def _application(session: Session, application_id: str) -> LoanApplication:
    application = session.get(LoanApplication, application_id)
    if application is None:
        raise fail(LoanError("Application not found.", 404))
    return application


@router.get("/loans/roles")
def roles(me: Profile = Depends(owner)) -> dict[str, bool]:
    """Whether the owner lends, applies, or neither -- which loan screens to show."""
    return loans.summary(me)


@router.get("/loans", response_model=list[LoanProductOut])
def browse(
    report_id: str | None = Query(default=None, alias="reportId"),
    purpose: str | None = None,
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> list[LoanProductOut]:
    """Loans the owner may apply for, best suited to the report first."""
    try:
        return loans.browse(session, me, report_id=report_id, purpose=purpose)
    except LoanError as exc:
        raise fail(exc) from exc


@router.get("/loans/mine", response_model=list[LoanProductOut])
def mine(me: Profile = Depends(owner), session: Session = Depends(get_session)) -> list[LoanProductOut]:
    return loans.my_products(session, me)


@router.post("/loans", response_model=LoanProductOut, status_code=201)
def create(payload: LoanProductInput, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> LoanProductOut:
    try:
        product = loans.create_product(session, me, payload)
    except LoanError as exc:
        raise fail(exc) from exc
    session.commit()
    return loans.serialise_product(session, product, me)


@router.put("/loans/{product_id}", response_model=LoanProductOut)
def update(product_id: str, payload: LoanProductInput, me: Profile = Depends(owner),
           session: Session = Depends(get_session)) -> LoanProductOut:
    try:
        product = loans.update_product(session, me, _product(session, product_id), payload)
    except LoanError as exc:
        raise fail(exc) from exc
    session.commit()
    return loans.serialise_product(session, product, me)


@router.delete("/loans/{product_id}", status_code=204)
def delete(product_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> None:
    try:
        loans.delete_product(session, me, _product(session, product_id))
    except LoanError as exc:
        raise fail(exc) from exc
    session.commit()


@router.post("/loans/{product_id}/share", response_model=LoanProductOut)
def share(product_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> LoanProductOut:
    product = _product(session, product_id)
    try:
        sharing.share_item(session, me, product)
    except SharingError as exc:
        raise fail(exc) from exc
    session.commit()
    return loans.serialise_product(session, product, me)


@router.post("/loans/{product_id}/unshare", response_model=LoanProductOut)
def unshare(product_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> LoanProductOut:
    product = _product(session, product_id)
    try:
        sharing.unshare_item(session, me, product)
    except SharingError as exc:
        raise fail(exc) from exc
    session.commit()
    return loans.serialise_product(session, product, me)


@router.post("/loan-applications", response_model=LoanApplicationOut, status_code=201)
def apply(payload: LoanApplicationInput, me: Profile = Depends(owner),
          session: Session = Depends(get_session)) -> LoanApplicationOut:
    """Apply for one loan, sharing what the applicant agreed to."""
    try:
        application = loans.apply(session, me, payload)
    except LoanError as exc:
        raise fail(exc) from exc
    session.commit()
    return loans.serialise_application(session, application, me)


@router.get("/loan-applications/mine", response_model=list[LoanApplicationOut])
def my_applications(me: Profile = Depends(owner), session: Session = Depends(get_session)) -> list[LoanApplicationOut]:
    return loans.my_applications(session, me)


@router.get("/loan-applications/desk", response_model=list[LoanApplicationOut])
def desk(me: Profile = Depends(owner), session: Session = Depends(get_session)) -> list[LoanApplicationOut]:
    """A lender's incoming applications."""
    try:
        return loans.desk(session, me)
    except LoanError as exc:
        raise fail(exc) from exc


@router.post("/loan-applications/{application_id}/decide", response_model=LoanApplicationOut)
def decide(application_id: str, payload: LoanDecisionInput, me: Profile = Depends(owner),
           session: Session = Depends(get_session)) -> LoanApplicationOut:
    """One step: review, ask for documents, sanction, disburse, decline -- or withdraw, reply."""
    try:
        application = loans.decide(session, me, _application(session, application_id), payload)
    except LoanError as exc:
        raise fail(exc) from exc
    session.commit()
    return loans.serialise_application(session, application, me)
