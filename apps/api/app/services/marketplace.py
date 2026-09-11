"""Investment requests, the interests that answer them, and who may see what.

The flow is deliberately short, because it has to make sense to someone
reading slowly on a shared laptop:

1. A farmer turns a plot -- ideally with its project report -- into a request,
   and chooses who may see it.
2. Investors and partners in those segments browse, and send an interest.
3. The farmer accepts or declines. Accepting shares both sides' phone and
   email with each other, and that is where the app steps back.

No money moves through any of this. The brief is explicit that ratings and
milestone-based fund release must exist before it does, so an accepted
interest is recorded as a *match* and nothing more.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import knowledge
from .. import segments as seg
from ..models import (
    InvestmentInterest,
    InvestmentRequest,
    LandParcel,
    ProjectReport,
    Profile,
)
from ..schemas import (
    FitOut,
    InterestInput,
    InterestOut,
    InvestmentRequestInput,
    InvestmentRequestOut,
    InvestmentRequestUpdate,
)
from . import insurance as cover
from . import videos
from .events import EventType, enqueue_sync, record_event
from .hierarchy import resolve_location
from .profiles import card

REQUEST_ENTITY = "investment_request"
INTEREST_ENTITY = "investment_interest"
LISTING_VERSION = 1


class MarketplaceError(Exception):
    """A request the rules do not allow. ``status`` is the HTTP status to use."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# The public snapshot
# --------------------------------------------------------------------------- #


def opportunity_summary(code: str | None) -> dict[str, Any] | None:
    if not code:
        return None
    item = knowledge.get_opportunity(code)
    if item is None:
        return None
    return {"code": item["code"], "kind": item["kind"], "name": item.get("label", {})}


def make_listing(
    session: Session,
    *,
    state_code: str,
    district_code: str,
    subdistrict_code: str | None,
    village_code: str | None,
    land: dict[str, Any],
    opportunity_code: str | None,
    plan: dict[str, Any] | None,
) -> dict[str, Any]:
    """What anyone allowed to see the request is shown, frozen at publication.

    Place names come from the LGD rows here rather than on the viewer's
    device, because the viewer may be abroad with no LGD data at all. Survey
    number, pin coordinates and phone are left out on purpose.
    """
    path = resolve_location(
        session,
        village_code=village_code,
        subdistrict_code=subdistrict_code,
        district_code=district_code,
        state_code=state_code,
    )
    return {
        "version": LISTING_VERSION,
        "location": {
            level: ({"code": unit.code, "name": unit.name} if unit is not None else None)
            for level, unit in (
                ("state", path.state),
                ("district", path.district),
                ("subdistrict", path.subdistrict),
                ("village", path.village),
            )
        },
        "land": land,
        "opportunity": opportunity_summary(opportunity_code),
        "plan": plan,
    }


def _land_facts(parcel: LandParcel) -> dict[str, Any]:
    return {
        "areaHectares": parcel.area_hectares,
        "areaValue": parcel.area_value,
        "areaUnit": parcel.area_unit,
        "ownershipType": parcel.ownership_type,
        "soilType": parcel.soil_type,
        "waterSources": list(parcel.water_sources or []),
        "waterType": parcel.water_type,
        "waterDepthMetres": parcel.water_depth_metres,
        "irrigationType": parcel.irrigation_type,
        "existingCrops": list(parcel.existing_crops or []),
    }


def _plan_facts(report: ProjectReport) -> dict[str, Any]:
    return {
        "reportNumber": report.report_number,
        "reportLanguage": report.language,
        "suitabilityScore": report.suitability_score,
        "totalProjectCost": report.total_project_cost,
        "termLoan": report.term_loan,
        "netPerYear": report.net_per_year,
    }


# --------------------------------------------------------------------------- #
# Who may see and do what
# --------------------------------------------------------------------------- #


def visible_to(request: InvestmentRequest, viewer: Profile) -> bool:
    """Whether ``viewer`` may see ``request`` at all.

    The farmer always sees their own. Anyone else needs the request to be
    shared online *and* shown to their kind of profile.
    """
    if request.profile_id == viewer.id:
        return True
    if request.visibility != "online":
        return False
    if viewer.segment not in (request.open_to or []):
        return False
    if viewer.segment == seg.GOVERNMENT:
        return in_jurisdiction(request, viewer)
    return True


def in_jurisdiction(request: InvestmentRequest, officer: Profile) -> bool:
    """A block officer sees their block, a district officer their district.

    Central ministries and public institutions see the whole country.
    """
    level = (officer.details or {}).get("level")
    if level in ("gram_panchayat", "block"):
        return request.subdistrict_code == officer.subdistrict_code
    if level == "district":
        return request.district_code == officer.district_code
    if level == "state":
        return request.state_code == officer.state_code
    return True


def _interest_of(request: InvestmentRequest, profile_id: str) -> InvestmentInterest | None:
    for interest in request.interests:
        if interest.profile_id == profile_id:
            return interest
    return None


def _connected(request: InvestmentRequest, viewer: Profile) -> bool:
    """True once the farmer has accepted this viewer, which unlocks contact."""
    interest = _interest_of(request, viewer.id)
    return interest is not None and interest.status == "accepted"


# --------------------------------------------------------------------------- #
# Fit
# --------------------------------------------------------------------------- #


def fit(request: InvestmentRequest, viewer: Profile) -> FitOut | None:
    """A rough 0-100 match between a request and the viewer's stated interests.

    Each criterion the viewer has an opinion on scores full marks on a match
    and nothing on a miss. A criterion they left blank scores half, so an
    investor who ticked no sectors is not shown every request as a poor fit.
    """
    details = viewer.details or {}
    criteria: list[tuple[int, bool | None, str]] = []

    if viewer.segment in seg.INVESTORS:
        states = details.get("preferred_states") or []
        sectors = details.get("sectors") or []
        modes = details.get("modes") or []
        criteria.append((30, request.state_code in states if states else None, "state"))
        criteria.append(
            (30, request.opportunity_kind in sectors if sectors else None, "sector")
        )
        if viewer.segment == "investor_india":
            low, high = details.get("ticket_min"), details.get("ticket_max")
            if low is None and high is None:
                criteria.append((25, None, "ticket"))
            else:
                amount = request.amount_sought
                within = (low is None or amount >= low) and (high is None or amount <= high)
                criteria.append((25, within, "ticket"))
        criteria.append(
            (15, bool(set(modes) & set(request.modes or [])) if modes else None, "mode")
        )

    elif viewer.segment in seg.PARTNERS:
        states = details.get("operating_states") or []
        kinds = details.get("partnership_types") or []
        crops = details.get("crops") or []
        grown = set((request.listing or {}).get("land", {}).get("existingCrops") or [])
        criteria.append((35, request.state_code in states if states else None, "state"))
        criteria.append(
            (
                40,
                bool(set(kinds) & set(request.partnership_types or [])) if kinds else None,
                "partnership",
            )
        )
        criteria.append((25, bool(set(crops) & grown) if crops else None, "crop"))

    else:
        return None

    total = sum(weight for weight, _, _ in criteria)
    earned = 0.0
    reasons: list[str] = []
    for weight, matched, code in criteria:
        if matched is None:
            earned += weight / 2
        elif matched:
            earned += weight
            reasons.append(code)
    return FitOut(score=round(earned * 100 / total), reasons=reasons)


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #


def serialise_interest(
    session: Session, interest: InvestmentInterest, *, reveal_contact: bool
) -> InterestOut:
    return InterestOut(
        id=interest.id,
        request_id=interest.request_id,
        kind=interest.kind,
        amount_offered=interest.amount_offered,
        mode=interest.mode,
        partnership_type=interest.partnership_type,
        message=interest.message,
        status=interest.status,
        responder=card(session, interest.profile, reveal_contact=reveal_contact),
        origin=interest.origin,
        created_at=interest.created_at,
        responded_at=interest.responded_at,
    )


def serialise_request(
    session: Session, request: InvestmentRequest, viewer: Profile
) -> InvestmentRequestOut:
    mine = request.profile_id == viewer.id
    connected = _connected(request, viewer)
    own_interest = None if mine else _interest_of(request, viewer.id)

    counts: dict[str, int] = {}
    if mine:
        for interest in request.interests:
            counts[interest.status] = counts.get(interest.status, 0) + 1

    rule = cover.requirements(request.opportunity_code, request.opportunity_kind)
    policies = cover.for_request(session, request.id)

    return InvestmentRequestOut(
        id=request.id,
        title=request.title,
        summary=request.summary,
        amount_sought=request.amount_sought,
        own_contribution=request.own_contribution,
        seeking=list(request.seeking or []),
        modes=list(request.modes or []),
        partnership_types=list(request.partnership_types or []),
        open_to=list(request.open_to or []),
        status=request.status,
        listing=request.listing or {},
        intro_video=videos.out(request.intro_video),
        opportunity_code=request.opportunity_code,
        opportunity_kind=request.opportunity_kind,
        state_code=request.state_code,
        district_code=request.district_code,
        parcel_id=request.parcel_id if mine else None,
        report_id=request.report_id if mine else None,
        requester=card(session, request.profile, reveal_contact=connected),
        is_mine=mine,
        interests=(
            [
                serialise_interest(
                    session, interest, reveal_contact=interest.status == "accepted"
                )
                for interest in sorted(request.interests, key=lambda i: i.created_at)
            ]
            if mine
            else []
        ),
        my_interest=(
            serialise_interest(session, own_interest, reveal_contact=False)
            if own_interest is not None
            else None
        ),
        interest_counts=counts,
        fit=None if mine else fit(request, viewer),
        insurance=[cover.serialise(policy, full=mine or connected) for policy in policies],
        insurance_required=rule.required,
        insurance_recommended=rule.recommended,
        fully_insured=cover.summary(policies, rule.required)["fully_insured"],
        visibility=request.visibility,
        shared_at=request.shared_at,
        featured=is_featured(request),
        promoted_until=request.promoted_until,
        origin=request.origin,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


def is_featured(request: InvestmentRequest, today: date | None = None) -> bool:
    """A promotion is running on an open, shared project."""
    return (
        request.status == "open"
        and request.visibility == "online"
        and request.promoted_until is not None
        and request.promoted_until >= (today or date.today())
    )


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


def create_request(
    session: Session, owner: Profile, data: InvestmentRequestInput
) -> InvestmentRequest:
    if owner.segment != seg.FARMER:
        raise MarketplaceError("Only a farmer profile can ask for investment.", 403)

    parcel = session.get(LandParcel, data.parcel_id)
    if parcel is None:
        raise MarketplaceError("Land parcel not found.", 404)
    if owner.farmer_id and parcel.farmer_id != owner.farmer_id:
        raise MarketplaceError("That land is not yours.", 403)

    report = None
    if data.report_id:
        report = session.get(ProjectReport, data.report_id)
        if report is None or report.parcel_id != parcel.id:
            raise MarketplaceError("That project report is not for this land.", 422)

    opportunity_code = report.opportunity_code if report else data.opportunity_code
    opportunity = opportunity_summary(opportunity_code)
    if opportunity_code and opportunity is None:
        raise MarketplaceError(f"Unknown farming option: {opportunity_code}", 422)

    rule = cover.requirements(opportunity_code, opportunity["kind"] if opportunity else None)
    shortfall = cover.request_cover_error(rule.required, data.insurance)
    if shortfall:
        raise MarketplaceError(shortfall, 422)

    request = InvestmentRequest(
        profile_id=owner.id,
        parcel_id=parcel.id,
        report_id=report.id if report else None,
        opportunity_code=opportunity_code,
        opportunity_kind=opportunity["kind"] if opportunity else None,
        state_code=parcel.state_code,
        district_code=parcel.district_code,
        subdistrict_code=parcel.subdistrict_code,
        title=data.title,
        summary=data.summary,
        amount_sought=data.amount_sought,
        own_contribution=data.own_contribution,
        seeking=list(data.seeking),
        modes=data.modes if "investment" in data.seeking else [],
        partnership_types=data.partnership_types if "partnership" in data.seeking else [],
        open_to=data.open_to,
        listing=make_listing(
            session,
            state_code=parcel.state_code,
            district_code=parcel.district_code,
            subdistrict_code=parcel.subdistrict_code,
            village_code=parcel.village_code,
            land=_land_facts(parcel),
            opportunity_code=opportunity_code,
            plan=_plan_facts(report) if report else None,
        ),
        status="open",
        origin="local",
    )
    session.add(request)
    session.flush()

    record_event(
        session,
        EventType.REQUEST_CREATED,
        entity_type=REQUEST_ENTITY,
        entity_id=request.id,
        payload={
            "amount_sought": request.amount_sought,
            "seeking": request.seeking,
            "open_to": request.open_to,
            "has_report": report is not None,
            "state_code": request.state_code,
            "insurance": {entry.category: entry.status for entry in data.insurance},
        },
    )
    enqueue_sync(session, entity_type=REQUEST_ENTITY, entity_id=request.id, operation="create")
    # After the request's own sync entry, so a sync worker replaying the
    # outbox in order never meets a policy for a request it has not seen.
    cover.add_to_request(session, request, data.insurance)
    return request


def update_request(
    session: Session, owner: Profile, request: InvestmentRequest, data: InvestmentRequestUpdate
) -> InvestmentRequest:
    if request.profile_id != owner.id:
        raise MarketplaceError("Only the farmer who made this request can change it.", 403)

    changes = data.model_dump(exclude_unset=True)
    if "open_to" in changes and changes["open_to"] is not None:
        open_to = changes["open_to"]
        if "investment" in request.seeking and not any(s in seg.INVESTORS for s in open_to):
            raise MarketplaceError("Show the request to at least one kind of investor.", 422)
        if "partnership" in request.seeking and not any(s in seg.PARTNERS for s in open_to):
            raise MarketplaceError("Show the request to at least one kind of partner.", 422)

    for field, value in changes.items():
        if value is None and field != "summary":
            continue
        setattr(request, field, value)

    if "status" in changes:
        request.closed_at = None if request.status == "open" else _now()
    if request.sync_state == "synced":
        request.sync_state = "queued"

    record_event(
        session,
        EventType.REQUEST_UPDATED,
        entity_type=REQUEST_ENTITY,
        entity_id=request.id,
        payload={"fields": sorted(changes.keys()), "status": request.status},
    )
    enqueue_sync(session, entity_type=REQUEST_ENTITY, entity_id=request.id, operation="update")
    return request


def browse(
    session: Session,
    viewer: Profile,
    *,
    state_code: str | None = None,
    kind: str | None = None,
    seeking: str | None = None,
    limit: int = 100,
) -> list[InvestmentRequestOut]:
    """Open requests the viewer may see, best fit first."""
    if viewer.segment == seg.FARMER:
        raise MarketplaceError(
            "Farmers see their own requests under 'My requests'.", 403
        )

    stmt = (
        select(InvestmentRequest)
        .where(InvestmentRequest.status == "open")
        .where(InvestmentRequest.profile_id != viewer.id)
        .order_by(InvestmentRequest.created_at.desc())
    )
    if state_code:
        stmt = stmt.where(InvestmentRequest.state_code == state_code)
    if kind:
        stmt = stmt.where(InvestmentRequest.opportunity_kind == kind)

    # ``open_to`` and ``seeking`` are JSON lists; the table is small on any
    # one device, so they are filtered here rather than with json_each().
    rows = [
        serialise_request(session, request, viewer)
        for request in session.scalars(stmt)
        if visible_to(request, viewer)
        and (seeking is None or seeking in (request.seeking or []))
    ]
    # Promoted projects first -- labelled as such on every card -- then best fit.
    rows.sort(key=lambda row: (row.featured, row.fit.score if row.fit else 0), reverse=True)
    return rows[:limit]


def my_requests(session: Session, owner: Profile) -> list[InvestmentRequestOut]:
    stmt = (
        select(InvestmentRequest)
        .where(InvestmentRequest.profile_id == owner.id)
        .order_by(InvestmentRequest.created_at.desc())
    )
    return [serialise_request(session, request, owner) for request in session.scalars(stmt)]


# --------------------------------------------------------------------------- #
# Interests
# --------------------------------------------------------------------------- #


def send_interest(
    session: Session, owner: Profile, request: InvestmentRequest, data: InterestInput
) -> InvestmentInterest:
    if owner.segment not in seg.RESPONDERS:
        raise MarketplaceError("Only investors and partners can respond to a request.", 403)
    if not visible_to(request, owner) or request.profile_id == owner.id:
        raise MarketplaceError("This request is not open to your profile type.", 403)
    if request.status != "open":
        raise MarketplaceError("This request is no longer open.")
    if owner.visibility != "online":
        raise MarketplaceError(
            "Share your profile online first, so the farmer can see who is answering."
        )

    allowed = seg.interest_kinds(owner.segment, owner.details)
    kind = data.kind or allowed[0]
    if kind not in allowed:
        raise MarketplaceError(
            "Your profile does not offer investment. Tick 'we also invest' on your profile first.",
            422,
        )
    if kind not in (request.seeking or []):
        raise MarketplaceError(
            "This farmer is not looking for "
            + ("investors." if kind == "investment" else "partners."),
        )
    if kind == "investment" and not data.mode:
        raise MarketplaceError("Choose how you would invest.", 422)
    if kind == "partnership" and not data.partnership_type:
        raise MarketplaceError("Choose the kind of partnership you offer.", 422)

    interest = _interest_of(request, owner.id)
    created = interest is None
    if interest is not None and interest.status in ("accepted", "declined"):
        raise MarketplaceError(
            "The farmer has already answered you, so these terms cannot be changed here."
        )
    if interest is None:
        interest = InvestmentInterest(request_id=request.id, profile_id=owner.id, origin="local")
        session.add(interest)
        request.interests.append(interest)

    interest.kind = kind
    interest.amount_offered = data.amount_offered if kind == "investment" else None
    interest.mode = data.mode if kind == "investment" else None
    interest.partnership_type = data.partnership_type if kind == "partnership" else None
    interest.message = data.message
    interest.status = "sent"
    interest.responded_at = None
    session.flush()

    record_event(
        session,
        EventType.INTEREST_SENT,
        entity_type=INTEREST_ENTITY,
        entity_id=interest.id,
        payload={
            "request_id": request.id,
            "kind": kind,
            "segment": owner.segment,
            "amount_offered": interest.amount_offered,
            "resent": not created,
        },
    )
    enqueue_sync(
        session,
        entity_type=INTEREST_ENTITY,
        entity_id=interest.id,
        operation="create" if created else "update",
    )
    from .directory import mark_answered  # noqa: PLC0415 - directory imports this module

    mark_answered(session, owner, request)
    return interest


def respond(
    session: Session, owner: Profile, interest: InvestmentInterest, status: str
) -> InvestmentInterest:
    """Accept or decline (the farmer), or withdraw (the responder)."""
    request = interest.request

    if status == "withdrawn":
        if interest.profile_id != owner.id:
            raise MarketplaceError("Only the sender can withdraw an interest.", 403)
        if interest.status not in ("sent", "accepted"):
            raise MarketplaceError("This interest cannot be withdrawn now.")
    else:
        if request.profile_id != owner.id:
            raise MarketplaceError("Only the farmer who made the request can answer.", 403)
        if interest.status != "sent":
            raise MarketplaceError("This interest has already been answered.")
        if request.status != "open":
            raise MarketplaceError("Reopen the request before answering interests.")

    interest.status = status
    interest.responded_at = _now()
    if interest.sync_state == "synced":
        interest.sync_state = "queued"

    record_event(
        session,
        EventType.INTEREST_UPDATED,
        entity_type=INTEREST_ENTITY,
        entity_id=interest.id,
        payload={"request_id": request.id, "status": status},
    )
    if status == "accepted":
        record_event(
            session,
            EventType.MATCH_MADE,
            entity_type=INTEREST_ENTITY,
            entity_id=interest.id,
            payload={
                "request_id": request.id,
                "kind": interest.kind,
                "amount_offered": interest.amount_offered,
                "responder_segment": interest.profile.segment,
            },
        )
    enqueue_sync(session, entity_type=INTEREST_ENTITY, entity_id=interest.id, operation="update")
    return interest


def my_interests(session: Session, owner: Profile) -> list[InvestmentRequestOut]:
    """Requests the owner has answered, newest answer first."""
    stmt = (
        select(InvestmentInterest)
        .where(InvestmentInterest.profile_id == owner.id)
        .order_by(InvestmentInterest.updated_at.desc())
    )
    return [
        serialise_request(session, interest.request, owner)
        for interest in session.scalars(stmt)
    ]
