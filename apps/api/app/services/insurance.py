"""Insurance: what a project must carry, and the policies people hold.

Three places hold policies, and each allows a different set of categories
(the ``scopes`` in insurance-types.json):

* a land parcel -- crop cover and polyhouse structures (``parcel``);
* the owner's profile -- a farmer's accident, life, health, animals and
  machinery (``farmer``), or a partner's cargo, trade credit and premises
  (``partner``);
* an investment request -- the project's own cover (``request``).

On a request, the farming option decides which categories are **required**
and which are only **recommended** (insurance-rules.json). A required category
needs either a policy or the farmer's promise to insure before any money is
released. Blocking outright would shut out exactly the smallholders who can
only afford a premium once a loan is sanctioned; a visible promise lets an
investor judge for themselves.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import knowledge, reference
from .. import segments as seg
from ..models import InsurancePolicy, InvestmentRequest, LandParcel, Profile
from ..schemas import InsuranceCreate, InsuranceInput, InsuranceOut, InsuranceRequirementOut
from .events import EventType, enqueue_sync, record_event

ENTITY = "insurance_policy"


class InsuranceError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _today() -> date:
    return date.today()


# --------------------------------------------------------------------------- #
# What is required
# --------------------------------------------------------------------------- #


def requirements(opportunity_code: str | None, kind: str | None = None) -> InsuranceRequirementOut:
    """Required and recommended cover for a farming option.

    An option's own rule wins over its kind's; with neither, crop cover is
    recommended, since almost every plot grows something.
    """
    rules = knowledge.load_insurance_rules()
    if opportunity_code and kind is None:
        item = knowledge.get_opportunity(opportunity_code)
        kind = item["kind"] if item else None

    rule = (
        rules.get("byOpportunity", {}).get(opportunity_code or "")
        or rules.get("byKind", {}).get(kind or "")
        or rules.get("default", {})
    )
    required = list(rule.get("required", []))
    recommended = [code for code in rule.get("recommended", []) if code not in required]
    return InsuranceRequirementOut(
        opportunity_code=opportunity_code,
        kind=kind,
        required=required,
        recommended=recommended,
        reason=rule.get("reason"),
    )


def category_label(code: str) -> str:
    return reference.label_of("insurance_types", code) or code


def scope_allows(scope: str, category: str) -> bool:
    item = reference.get_item("insurance_types", category) or {}
    return scope in item.get("scopes", [])


def is_current(policy: InsurancePolicy | InsuranceInput, today: date | None = None) -> bool:
    if policy.status != "insured":
        return False
    return policy.valid_until is None or policy.valid_until >= (today or _today())


def request_cover_error(required: list[str], entries: list[InsuranceInput]) -> str | None:
    """Why a request's cover falls short of its option's rule, or None."""
    today = _today()
    for entry in entries:
        if not scope_allows("request", entry.category):
            return f"{category_label(entry.category)} is not project insurance."
        if entry.status == "insured" and not is_current(entry, today):
            return f"The {category_label(entry.category).lower()} policy has already expired."
    given = {entry.category for entry in entries}
    for category in required:
        if category not in given:
            return (
                f"{category_label(category)} is required for this project. Add the policy, "
                "or promise to insure before any money is released."
            )
    return None


# --------------------------------------------------------------------------- #
# Presentation
# --------------------------------------------------------------------------- #


def _mask(number: str | None) -> str | None:
    if not number:
        return None
    return "••••" + number[-4:] if len(number) > 4 else "••••"


def serialise(policy: InsurancePolicy, *, full: bool) -> InsuranceOut:
    """``full`` for the owner, and for a counterparty the farmer has accepted.

    Everyone else sees that the cover exists, who with, for how much and until
    when -- enough to judge the risk -- but not the policy number, the premium
    paid or private notes.
    """
    today = _today()
    current = is_current(policy, today)
    return InsuranceOut(
        id=policy.id,
        category=policy.category,
        status=policy.status,
        scheme=policy.scheme,
        insurer=policy.insurer,
        policy_number=policy.policy_number if full else _mask(policy.policy_number),
        sum_insured=policy.sum_insured,
        premium=policy.premium if full else None,
        currency=policy.currency,
        valid_from=policy.valid_from,
        valid_until=policy.valid_until,
        season=policy.season,
        season_year=policy.season_year,
        covered=policy.covered,
        notes=policy.notes if full else None,
        is_current=current,
        expired=policy.status == "insured" and not current,
        parcel_id=policy.parcel_id,
        profile_id=policy.profile_id,
        request_id=policy.request_id,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def for_request(session: Session, request_id: str) -> list[InsurancePolicy]:
    return list(
        session.scalars(
            select(InsurancePolicy)
            .where(InsurancePolicy.request_id == request_id)
            .order_by(InsurancePolicy.created_at)
        )
    )


def list_for(
    session: Session, *, parcel_id: str | None = None, profile_id: str | None = None
) -> list[InsurancePolicy]:
    stmt = select(InsurancePolicy).order_by(InsurancePolicy.created_at)
    if parcel_id:
        stmt = stmt.where(InsurancePolicy.parcel_id == parcel_id)
    elif profile_id:
        stmt = stmt.where(InsurancePolicy.profile_id == profile_id)
    else:
        return []
    return list(session.scalars(stmt))


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #


def _apply(policy: InsurancePolicy, data: InsuranceInput) -> None:
    for field in (
        "category",
        "status",
        "scheme",
        "insurer",
        "policy_number",
        "sum_insured",
        "premium",
        "currency",
        "valid_from",
        "valid_until",
        "season",
        "season_year",
        "covered",
        "notes",
    ):
        setattr(policy, field, getattr(data, field))


def _profile_scope(profile: Profile) -> str:
    if profile.segment == seg.FARMER:
        return "farmer"
    if profile.segment in seg.PARTNERS:
        return "partner"
    raise InsuranceError("This kind of profile does not record insurance.", 403)


def _scope_of(session: Session, policy: InsurancePolicy) -> str:
    if policy.parcel_id:
        return "parcel"
    if policy.request_id:
        return "request"
    profile = session.get(Profile, policy.profile_id)
    return _profile_scope(profile) if profile else "farmer"


def _check_owner(session: Session, owner: Profile, policy: InsurancePolicy) -> None:
    """Only the device owner's own things carry editable policies."""
    if policy.profile_id and policy.profile_id != owner.id:
        raise InsuranceError("Insurance policy not found.", 404)
    if policy.request_id:
        request = session.get(InvestmentRequest, policy.request_id)
        if request is None or request.profile_id != owner.id:
            raise InsuranceError("Insurance policy not found.", 404)
    if policy.parcel_id and owner.farmer_id:
        parcel = session.get(LandParcel, policy.parcel_id)
        if parcel is None or parcel.farmer_id != owner.farmer_id:
            raise InsuranceError("Insurance policy not found.", 404)


def _record(session: Session, event: str, policy: InsurancePolicy, scope: str, operation: str) -> None:
    record_event(
        session,
        event,
        entity_type=ENTITY,
        entity_id=policy.id,
        payload={"category": policy.category, "status": policy.status, "scope": scope},
    )
    enqueue_sync(session, entity_type=ENTITY, entity_id=policy.id, operation=operation)


def add(session: Session, owner: Profile, data: InsuranceCreate) -> InsurancePolicy:
    policy = InsurancePolicy(origin="local")

    if data.parcel_id:
        parcel = session.get(LandParcel, data.parcel_id)
        if parcel is None or (owner.farmer_id and parcel.farmer_id != owner.farmer_id):
            raise InsuranceError("Land parcel not found.", 404)
        scope = "parcel"
        policy.parcel_id = parcel.id
    elif data.request_id:
        request = session.get(InvestmentRequest, data.request_id)
        if request is None or request.profile_id != owner.id:
            raise InsuranceError("Request not found.", 404)
        scope = "request"
        policy.request_id = request.id
    else:
        scope = _profile_scope(owner)
        policy.profile_id = owner.id

    if not scope_allows(scope, data.category):
        raise InsuranceError(f"{category_label(data.category)} cannot be recorded here.")
    if data.status == "planned" and scope != "request":
        raise InsuranceError("A promise to insure only applies to an investment request.")

    _apply(policy, data)
    session.add(policy)
    session.flush()
    _record(session, EventType.INSURANCE_ADDED, policy, scope, "create")
    return policy


def add_to_request(session: Session, request: InvestmentRequest, entries: list[InsuranceInput]) -> None:
    """Attach the cover a request was published with. Already validated."""
    for entry in entries:
        policy = InsurancePolicy(request_id=request.id, origin="local")
        _apply(policy, entry)
        session.add(policy)
        session.flush()
        _record(session, EventType.INSURANCE_ADDED, policy, "request", "create")


def update(session: Session, owner: Profile, policy: InsurancePolicy, data: InsuranceInput) -> InsurancePolicy:
    _check_owner(session, owner, policy)
    scope = _scope_of(session, policy)
    if data.category != policy.category:
        # Changing a livestock policy into a crop policy would quietly leave a
        # required category uncovered. Remove one and add the other instead.
        raise InsuranceError("A policy cannot change category.", 409)
    if data.status == "planned" and scope != "request":
        raise InsuranceError("A promise to insure only applies to an investment request.")

    _apply(policy, data)
    if policy.sync_state == "synced":
        policy.sync_state = "queued"
    _record(session, EventType.INSURANCE_UPDATED, policy, scope, "update")
    return policy


def remove(session: Session, owner: Profile, policy: InsurancePolicy) -> None:
    _check_owner(session, owner, policy)
    scope = _scope_of(session, policy)
    if policy.request_id:
        request = session.get(InvestmentRequest, policy.request_id)
        if request is not None and request.status == "open":
            required = requirements(request.opportunity_code, request.opportunity_kind).required
            others = [
                other
                for other in for_request(session, request.id)
                if other.id != policy.id and other.category == policy.category
            ]
            if policy.category in required and not others:
                raise InsuranceError(
                    f"{category_label(policy.category)} is required while the request is open. "
                    "Change the policy instead, or close the request first.",
                    409,
                )
    _record(session, EventType.INSURANCE_REMOVED, policy, scope, "delete")
    session.delete(policy)


def summary(policies: list[InsurancePolicy], required: list[str]) -> dict[str, Any]:
    """Whether every required category has a current policy, not just a promise."""
    today = _today()
    covered = {policy.category for policy in policies if is_current(policy, today)}
    return {"fully_insured": all(category in covered for category in required)}
