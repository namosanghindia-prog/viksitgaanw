"""Loans: lenders' offers, and farmers applying with their project report.

A smallholder's real source of money is a bank, not a stranger: banks, NBFCs
and cooperative banks have agriculture to lend to, and what they lack is a
sound project report, the land's facts and a verified borrower. The app
already makes all three. Here a lender -- a partner organisation of the right
type -- publishes **loan products**; a farmer (or an FPO for its members) sees
the ones that suit their project report and applies in one step, agreeing to
exactly what is shared; the lender reviews, asks for documents, sanctions and
records the disbursement.

What the app does not do is lend or move money. The lender decides and pays
out, and the app records what it is told -- the sanctioned and disbursed
amounts are the lines a lender's commission is invoiced on (``app_events``
here, and the sync server's own record, ``admin.py loans``).

Which side may write which field is fixed in ``LENDER_FIELDS`` and enforced on
the sync server as well: an applicant cannot mark their own loan sanctioned,
and a lender cannot rewrite what was asked for.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import knowledge, reference
from ..models import LandParcel, LoanApplication, LoanProduct, ProjectReport, Profile
from ..schemas import (
    LoanApplicationInput,
    LoanApplicationOut,
    LoanDecisionInput,
    LoanMatchOut,
    LoanProductInput,
    LoanProductOut,
)
from .events import EventType, enqueue_sync, record_event
from .hierarchy import resolve_location
from .marketplace import _land_facts, _plan_facts
from .profiles import card

PRODUCT = "loan_product"
APPLICATION = "loan_application"

#: Organisation types that lend. A partner of one of these may publish loans.
LENDER_TYPES = frozenset({"bank", "nbfc", "cooperative_bank"})
#: Still waiting on the lender.
OPEN = ("submitted", "under_review", "documents_requested")
#: The lender's half of an application; mirrored on the sync server.
LENDER_FIELDS = (
    "lender_note", "documents_requested", "sanctioned_amount", "interest_rate",
    "sanctioned_tenure_months", "disbursed_amount", "disbursed_on", "responded_at",
)


class LoanError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_lender(profile: Profile | None) -> bool:
    return bool(
        profile
        and profile.segment == "partner_national"
        and (profile.details or {}).get("organisation_type") in LENDER_TYPES
    )


def can_apply(profile: Profile | None) -> bool:
    """Farmers, and national partners borrowing for their members (FPOs, cooperatives)."""
    return bool(profile and profile.segment in ("farmer", "partner_national") and not is_lender(profile))


def _require_lender(owner: Profile) -> None:
    if not is_lender(owner):
        raise LoanError("Only a bank, NBFC or cooperative bank can offer loans here.", 403)


# --------------------------------------------------------------------------- #
# Matching a loan to a project
# --------------------------------------------------------------------------- #


def _kind_of(report: ProjectReport | None) -> str | None:
    if report is None:
        return None
    item = knowledge.get_opportunity(report.opportunity_code)
    return item.get("kind") if item else None


def match(product: LoanProduct, applicant: Profile, report: ProjectReport | None,
          state_code: str | None) -> LoanMatchOut:
    """0-100: does it lend for this kind of project, this much, in this state?

    Purpose counts 40, amount 30, state 30. What cannot be judged -- no report
    to know the project or the amount by -- scores half, so a farmer without a
    report still sees every loan, just not ranked by it.
    """
    score, reasons, misses = 0, [], []
    purpose = reference.get_item("loan_purposes", product.purpose) or {}
    kind = _kind_of(report)
    if kind is None:
        score += 20
    elif kind in (purpose.get("kinds") or []):
        score += 40
        reasons.append("purpose")
    else:
        misses.append("purpose")

    need = report.term_loan if report is not None and report.term_loan else None
    if need is None:
        score += 15
    elif product.min_amount <= need <= product.max_amount:
        score += 30
        reasons.append("amount")
    else:
        misses.append("amount")

    if not product.states or (state_code and state_code in product.states):
        score += 30
        reasons.append("state")
    else:
        misses.append("state")
    return LoanMatchOut(score=score, reasons=reasons, misses=misses)


# --------------------------------------------------------------------------- #
# Serialising
# --------------------------------------------------------------------------- #


def serialise_product(
    session: Session, product: LoanProduct, viewer: Profile, *,
    report: ProjectReport | None = None, state_code: str | None = None,
) -> LoanProductOut:
    mine = product.profile_id == viewer.id
    counts: dict[str, int] = {}
    if mine:
        for application in product.applications:
            counts[application.status] = counts.get(application.status, 0) + 1
    open_application = next(
        (a for a in product.applications if a.profile_id == viewer.id and a.status in OPEN), None
    )
    return LoanProductOut(
        id=product.id,
        purpose=product.purpose,
        title=product.title,
        summary=product.summary,
        min_amount=product.min_amount,
        max_amount=product.max_amount,
        rate_min=product.rate_min,
        rate_max=product.rate_max,
        tenure_min_months=product.tenure_min_months,
        tenure_max_months=product.tenure_max_months,
        collateral=product.collateral,
        processing_fee=product.processing_fee,
        documents=list(product.documents or []),
        states=list(product.states or []),
        segments=list(product.segments or []),
        status=product.status,
        lender=card(session, product.profile, reveal_contact=False),
        is_mine=mine,
        application_counts=counts,
        match=None if mine else match(product, viewer, report, state_code or viewer.state_code),
        my_application_id=open_application.id if open_application else None,
        visibility=product.visibility,
        shared_at=product.shared_at,
        origin=product.origin,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def serialise_application(session: Session, application: LoanApplication, viewer: Profile) -> LoanApplicationOut:
    mine = application.profile_id == viewer.id
    product = application.product
    # Applying shared the applicant's contact with this lender; the lender's
    # own contact is an institution's, shown once it takes the application up.
    engaged = application.status not in ("submitted", "withdrawn")
    return LoanApplicationOut(
        id=application.id,
        product_id=application.product_id,
        product_title=product.title if product else "",
        purpose=product.purpose if product else "",
        lender=card(session, product.profile if product else viewer, reveal_contact=mine and engaged),
        applicant=card(session, application.profile,
                       reveal_contact=not mine and bool((application.consent or {}).get("contact"))),
        is_mine=mine,
        amount_requested=application.amount_requested,
        tenure_months=application.tenure_months,
        applicant_note=application.applicant_note,
        snapshot=application.snapshot or {},
        consent=application.consent or {},
        consented_at=application.consented_at,
        status=application.status,
        lender_note=application.lender_note,
        documents_requested=list(application.documents_requested or []),
        sanctioned_amount=application.sanctioned_amount,
        interest_rate=application.interest_rate,
        sanctioned_tenure_months=application.sanctioned_tenure_months,
        disbursed_amount=application.disbursed_amount,
        disbursed_on=application.disbursed_on,
        responded_at=application.responded_at,
        report_id=application.report_id if mine else None,
        origin=application.origin,
        created_at=application.created_at,
        updated_at=application.updated_at,
    )


# --------------------------------------------------------------------------- #
# The lender's loan products
# --------------------------------------------------------------------------- #


def _apply(product: LoanProduct, data: LoanProductInput) -> None:
    for field in (
        "purpose", "title", "summary", "min_amount", "max_amount", "rate_min", "rate_max",
        "tenure_min_months", "tenure_max_months", "collateral", "processing_fee",
        "documents", "states", "segments", "status",
    ):
        setattr(product, field, getattr(data, field))


def create_product(session: Session, owner: Profile, data: LoanProductInput) -> LoanProduct:
    _require_lender(owner)
    product = LoanProduct(profile_id=owner.id, origin="local", visibility="offline")
    _apply(product, data)
    session.add(product)
    session.flush()
    record_event(session, EventType.LOAN_PRODUCT_CREATED, entity_type=PRODUCT, entity_id=product.id,
                 payload={"purpose": product.purpose, "max_amount": product.max_amount})
    enqueue_sync(session, entity_type=PRODUCT, entity_id=product.id, operation="create")
    return product


def update_product(session: Session, owner: Profile, product: LoanProduct, data: LoanProductInput) -> LoanProduct:
    if product.profile_id != owner.id:
        raise LoanError("Only the lender can change this loan.", 403)
    _apply(product, data)
    if product.sync_state == "synced":
        product.sync_state = "queued"
    enqueue_sync(session, entity_type=PRODUCT, entity_id=product.id, operation="update")
    return product


def delete_product(session: Session, owner: Profile, product: LoanProduct) -> None:
    if product.profile_id != owner.id:
        raise LoanError("Only the lender can delete this loan.", 403)
    if any(a.status in OPEN + ("sanctioned",) for a in product.applications):
        raise LoanError("Answer its open applications first, or pause the loan instead.")
    enqueue_sync(session, entity_type=PRODUCT, entity_id=product.id, operation="delete")
    session.delete(product)


def my_products(session: Session, owner: Profile) -> list[LoanProductOut]:
    stmt = select(LoanProduct).where(LoanProduct.profile_id == owner.id).order_by(LoanProduct.created_at.desc())
    return [serialise_product(session, product, owner) for product in session.scalars(stmt)]


def _own_report(session: Session, owner: Profile, report_id: str | None) -> tuple[ProjectReport | None, LandParcel | None]:
    if not report_id:
        return None, None
    report = session.get(ProjectReport, report_id)
    parcel = session.get(LandParcel, report.parcel_id) if report else None
    if report is None or parcel is None or (owner.farmer_id and parcel.farmer_id != owner.farmer_id):
        raise LoanError("That project report is not yours.", 404)
    return report, parcel


def browse(session: Session, viewer: Profile, *, report_id: str | None = None,
           purpose: str | None = None) -> list[LoanProductOut]:
    """Loans others offer that the viewer may apply for, best suited first."""
    report, parcel = _own_report(session, viewer, report_id)
    state_code = parcel.state_code if parcel is not None else viewer.state_code
    stmt = (
        select(LoanProduct)
        .where(LoanProduct.visibility == "online", LoanProduct.status == "active")
        .where(LoanProduct.profile_id != viewer.id)
    )
    if purpose:
        stmt = stmt.where(LoanProduct.purpose == purpose)
    rows = [
        serialise_product(session, product, viewer, report=report, state_code=state_code)
        for product in session.scalars(stmt)
        if viewer.segment in (product.segments or ["farmer"])
    ]
    rows.sort(key=lambda row: (row.match.score if row.match else 0, row.max_amount), reverse=True)
    return rows


# --------------------------------------------------------------------------- #
# Applying
# --------------------------------------------------------------------------- #


def _snapshot(session: Session, owner: Profile, report: ProjectReport | None, parcel: LandParcel | None,
              data: LoanApplicationInput) -> dict[str, Any]:
    """Exactly what the applicant agreed to share, frozen when they applied."""
    codes = (
        {"state_code": parcel.state_code, "district_code": parcel.district_code,
         "subdistrict_code": parcel.subdistrict_code, "village_code": parcel.village_code}
        if parcel is not None
        else {"state_code": owner.state_code, "district_code": owner.district_code,
              "subdistrict_code": owner.subdistrict_code, "village_code": owner.village_code}
    )
    path = resolve_location(session, **codes)
    snapshot: dict[str, Any] = {
        "place": ", ".join(unit.name for unit in (path.village, path.subdistrict, path.district, path.state) if unit),
        "stateCode": codes["state_code"],
        "segment": owner.segment,
        "kycStatus": owner.kyc_status,
    }
    if data.share_report and report is not None:
        item = knowledge.get_opportunity(report.opportunity_code) or {}
        snapshot["plan"] = {**_plan_facts(report), "opportunity": item.get("label", {}), "kind": item.get("kind")}
    if data.share_land and parcel is not None:
        snapshot["land"] = _land_facts(parcel)
    if data.share_contact:
        snapshot["contact"] = {"name": owner.organisation_name or owner.display_name,
                               "phone": owner.phone, "email": owner.email}
    return snapshot


def apply(session: Session, owner: Profile, data: LoanApplicationInput) -> LoanApplication:
    if not can_apply(owner):
        raise LoanError("Farmers and FPOs can apply for loans here.", 403)
    product = session.get(LoanProduct, data.product_id)
    if product is None or product.visibility != "online" or product.status != "active":
        raise LoanError("This loan is not on offer now.", 404)
    if product.profile_id == owner.id:
        raise LoanError("This is your own loan.", 403)
    if owner.segment not in (product.segments or ["farmer"]):
        raise LoanError("This lender does not offer this loan to your kind of profile.", 403)
    if owner.visibility != "online":
        raise LoanError("Share your profile online first, so the lender can see who is applying.")
    if not data.share_contact:
        raise LoanError("A lender cannot answer someone it cannot reach: agree to share your phone number.", 422)
    if not product.min_amount <= data.amount_requested <= product.max_amount:
        raise LoanError(
            f"This loan is for Rs {product.min_amount:,.0f} to Rs {product.max_amount:,.0f}.", 422
        )
    if any(a.profile_id == owner.id and a.status in OPEN for a in product.applications):
        raise LoanError("You have already applied for this loan; it is waiting on the lender.")
    report, parcel = _own_report(session, owner, data.report_id)

    application = LoanApplication(
        product_id=product.id,
        profile_id=owner.id,
        lender_profile_id=product.profile_id,
        report_id=report.id if report else None,
        parcel_id=parcel.id if parcel else None,
        amount_requested=data.amount_requested,
        tenure_months=data.tenure_months,
        applicant_note=data.applicant_note,
        snapshot=_snapshot(session, owner, report, parcel, data),
        consent={"report": bool(data.share_report and report), "land": bool(data.share_land and parcel),
                 "contact": True},
        consented_at=_now(),
        status="submitted",
        origin="local",
    )
    session.add(application)
    product.applications.append(application)
    session.flush()
    record_event(session, EventType.LOAN_APPLIED, entity_type=APPLICATION, entity_id=application.id,
                 payload={"amount": application.amount_requested, "purpose": product.purpose,
                          "lender_profile_id": product.profile_id, "has_report": report is not None})
    enqueue_sync(session, entity_type=APPLICATION, entity_id=application.id, operation="create")
    return application


def decide(session: Session, owner: Profile, application: LoanApplication, data: LoanDecisionInput) -> LoanApplication:
    """One step on an application: the lender's, or the applicant's withdraw and reply."""
    applicant = application.profile_id == owner.id
    lender = application.lender_profile_id == owner.id
    if not (applicant or lender):
        raise LoanError("Application not found.", 404)
    action, status = data.action, application.status

    if action in ("withdraw", "reply"):
        if not applicant:
            raise LoanError("Only the applicant can do that.", 403)
        if status not in OPEN:
            raise LoanError("This application is no longer open.")
        if action == "withdraw":
            application.status = "withdrawn"
        else:
            if not data.note:
                raise LoanError("Write the reply first.", 422)
            application.applicant_note = data.note
    else:
        if not lender:
            raise LoanError("Only the lender can do that.", 403)
        if action == "review":
            if status != "submitted":
                raise LoanError("This application is already being dealt with.")
            application.status = "under_review"
        elif action == "documents":
            if status not in OPEN:
                raise LoanError("This application is no longer open.")
            if not data.documents and not data.note:
                raise LoanError("Say which documents are needed.", 422)
            application.status = "documents_requested"
            application.documents_requested = data.documents
        elif action == "sanction":
            if status not in OPEN:
                raise LoanError("Only an open application can be sanctioned.")
            if not data.amount:
                raise LoanError("Give the sanctioned amount.", 422)
            application.status = "sanctioned"
            application.sanctioned_amount = data.amount
            application.interest_rate = data.rate
            application.sanctioned_tenure_months = data.tenure_months
        elif action == "disburse":
            if status != "sanctioned":
                raise LoanError("Only a sanctioned loan can be disbursed.")
            when = data.disbursed_on or date.today()
            if when > date.today():
                raise LoanError("A disbursement cannot be in the future.", 422)
            application.status = "disbursed"
            application.disbursed_amount = data.amount or application.sanctioned_amount
            application.disbursed_on = when
        elif action == "decline":
            if status not in OPEN:
                raise LoanError("This application is no longer open.")
            application.status = "declined"
        if data.note:
            application.lender_note = data.note
        application.responded_at = _now()

    session.flush()
    event = {
        "sanction": EventType.LOAN_SANCTIONED,
        "disburse": EventType.LOAN_DISBURSED,
    }.get(action, EventType.LOAN_UPDATED)
    record_event(session, event, entity_type=APPLICATION, entity_id=application.id, payload={
        "action": action,
        "status": application.status,
        "amount": application.disbursed_amount if action == "disburse" else application.sanctioned_amount,
        "purpose": application.product.purpose if application.product else None,
        "lender_profile_id": application.lender_profile_id,
    })
    enqueue_sync(session, entity_type=APPLICATION, entity_id=application.id, operation="update")
    return application


def my_applications(session: Session, owner: Profile) -> list[LoanApplicationOut]:
    stmt = (select(LoanApplication).where(LoanApplication.profile_id == owner.id)
            .order_by(LoanApplication.updated_at.desc()))
    return [serialise_application(session, a, owner) for a in session.scalars(stmt)]


def desk(session: Session, owner: Profile) -> list[LoanApplicationOut]:
    """The lender's applications: open ones first, newest first."""
    _require_lender(owner)
    stmt = (select(LoanApplication).where(LoanApplication.lender_profile_id == owner.id)
            .order_by(LoanApplication.created_at.desc()))
    rows = [serialise_application(session, a, owner) for a in session.scalars(stmt)]
    rows.sort(key=lambda row: row.status not in OPEN)
    return rows


def summary(owner: Profile) -> dict[str, bool]:
    """Which loan screens the owner gets."""
    return {"lender": is_lender(owner), "applicant": can_apply(owner)}
