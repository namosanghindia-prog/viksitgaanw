"""Deals, milestones, disputes and ratings -- the layer that has to exist
before real money moves through the platform.

The shape follows how agricultural finance actually goes wrong: money handed
over in one lump, spent on something else, and no record either side can
point to. So an accepted investment becomes a **deal** with **milestones**
("saplings planted", "drip installed"), each with its own tranche. The farmer
submits evidence -- a note and photographs -- and the investor approves it
and records releasing that tranche. Payment itself happens outside the app
until a regulated escrow partner exists; this is the ledger both sides agreed
to, and the one a mediator would read.

A **dispute** pauses the deal until the side that did not raise it accepts a
resolution. **Ratings** are given once the work is done, and are public.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Deal,
    Dispute,
    EquipmentEnquiry,
    EquipmentPartnership,
    InvestmentInterest,
    InvestmentRequest,
    Milestone,
    Profile,
    Rating,
)
from ..schemas import (
    DealInput,
    DealOut,
    DealPlanInput,
    DisputeInput,
    DisputeOut,
    MediaOut,
    MilestoneOut,
    MilestoneReview,
    RatingInput,
    RatingOut,
    RatingSummaryOut,
)
from . import media
from .events import EventType, enqueue_sync, record_event
from .notify import notify
from .profiles import card


class TrustError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log(session: Session, event: str, entity: str, entity_id: str, payload: dict | None = None) -> None:
    record_event(session, event, entity_type=entity, entity_id=entity_id, payload=payload or {})
    enqueue_sync(session, entity_type=entity, entity_id=entity_id, operation="update")


def _party(deal: Deal, owner: Profile) -> str:
    if owner.id == deal.farmer_profile_id:
        return "farmer"
    if owner.id == deal.investor_profile_id:
        return "investor"
    raise TrustError("Deal not found.", 404)


def _other(deal: Deal, owner: Profile) -> str:
    return deal.investor_profile_id if owner.id == deal.farmer_profile_id else deal.farmer_profile_id


# --------------------------------------------------------------------------- #
# Deals
# --------------------------------------------------------------------------- #


def _set_plan(deal: Deal, data: DealPlanInput) -> None:
    deal.terms = data.terms
    deal.milestones.clear()
    for position, item in enumerate(data.milestones):
        deal.milestones.append(
            Milestone(
                position=position,
                title=item.title,
                description=item.description,
                amount=item.amount,
                due_date=item.due_date,
            )
        )
    deal.amount_total = round(sum(item.amount for item in data.milestones), 2)


def create_deal(session: Session, owner: Profile, data: DealInput) -> Deal:
    interest = session.get(InvestmentInterest, data.interest_id)
    if interest is None:
        raise TrustError("Interest not found.", 404)
    request = interest.request
    if owner.id not in (interest.profile_id, request.profile_id):
        raise TrustError("Interest not found.", 404)
    if interest.kind != "investment":
        raise TrustError("A deal with milestones is for investments. Partnerships are agreed directly.", 422)
    if interest.status != "accepted":
        raise TrustError("The farmer has to accept the interest before a deal can be planned.")
    if session.scalar(select(Deal.id).where(Deal.interest_id == interest.id)):
        raise TrustError("There is already a deal for this interest.")

    deal = Deal(
        interest_id=interest.id,
        request_id=request.id,
        farmer_profile_id=request.profile_id,
        investor_profile_id=interest.profile_id,
        mode=interest.mode,
        proposed_by=owner.id,
        status="drafting",
        amount_total=0,
        origin="local",
    )
    _set_plan(deal, data)
    session.add(deal)
    session.flush()
    record_event(
        session,
        EventType.DEAL_PROPOSED,
        entity_type="deal",
        entity_id=deal.id,
        payload={"amount_total": deal.amount_total, "milestones": len(deal.milestones)},
    )
    enqueue_sync(session, entity_type="deal", entity_id=deal.id, operation="create")
    return deal


def replace_plan(session: Session, owner: Profile, deal: Deal, data: DealPlanInput) -> Deal:
    """Either side may redraw the plan while it is being agreed; the other then agrees."""
    _party(deal, owner)
    if deal.status != "drafting":
        raise TrustError("The plan is agreed. Raise a dispute if something has to change.")
    _set_plan(deal, data)
    deal.proposed_by = owner.id
    _log(session, EventType.DEAL_PROPOSED, "deal", deal.id, {"amount_total": deal.amount_total})
    return deal


def agree(session: Session, owner: Profile, deal: Deal) -> Deal:
    _party(deal, owner)
    if deal.status != "drafting":
        raise TrustError("This plan is not waiting for agreement.")
    if deal.proposed_by == owner.id:
        raise TrustError("The other side has to agree to a plan you drew up.", 403)
    deal.status = "active"
    deal.agreed_at = _now()
    _log(session, EventType.DEAL_AGREED, "deal", deal.id, {"amount_total": deal.amount_total})
    return deal


def cancel(session: Session, owner: Profile, deal: Deal) -> Deal:
    _party(deal, owner)
    if deal.status != "drafting":
        raise TrustError("Only a plan that has not been agreed can be cancelled.")
    deal.status = "cancelled"
    _log(session, EventType.DEAL_CANCELLED, "deal", deal.id)
    return deal


def _milestone(session: Session, owner: Profile, milestone_id: str) -> tuple[Milestone, Deal, str]:
    milestone = session.get(Milestone, milestone_id)
    if milestone is None:
        raise TrustError("Milestone not found.", 404)
    deal = milestone.deal
    return milestone, deal, _party(deal, owner)


def submit(session: Session, owner: Profile, milestone_id: str, note: str) -> Milestone:
    milestone, deal, side = _milestone(session, owner, milestone_id)
    if side != "farmer":
        raise TrustError("The farmer submits the evidence for a milestone.", 403)
    if deal.status != "active":
        raise TrustError("Evidence can be submitted once the plan is agreed and no dispute is open.")
    if milestone.status not in ("planned", "rejected"):
        raise TrustError("This milestone has already been submitted.")
    milestone.status = "submitted"
    milestone.evidence_note = note
    milestone.submitted_at = _now()
    milestone.review_note = None
    _log(session, EventType.MILESTONE_SUBMITTED, "deal", deal.id, {"milestone": milestone.id})
    return milestone


def review(session: Session, owner: Profile, milestone_id: str, data: MilestoneReview) -> Milestone:
    milestone, deal, side = _milestone(session, owner, milestone_id)
    if side != "investor":
        raise TrustError("The investor reviews the evidence.", 403)
    if deal.status != "active":
        raise TrustError("Close the dispute before reviewing milestones.")
    if milestone.status != "submitted":
        raise TrustError("There is no evidence waiting for review.")

    milestone.reviewed_at = _now()
    milestone.review_note = data.note
    if data.approved:
        milestone.status = "approved"
        milestone.released_at = milestone.reviewed_at
        milestone.release_reference = data.release_reference
        record_event(
            session,
            EventType.TRANCHE_RELEASED,
            entity_type="deal",
            entity_id=deal.id,
            payload={"milestone": milestone.id, "amount": milestone.amount},
        )
    else:
        milestone.status = "rejected"
        record_event(
            session, EventType.MILESTONE_REJECTED, entity_type="deal", entity_id=deal.id,
            payload={"milestone": milestone.id},
        )

    if all(item.status == "approved" for item in deal.milestones):
        deal.status = "completed"
        deal.completed_at = _now()
        # The unit the success fee is measured against, reserved since phase 1.
        record_event(
            session,
            EventType.DEAL_COMPLETED,
            entity_type="deal",
            entity_id=deal.id,
            payload={
                "amount_total": deal.amount_total,
                "request_id": deal.request_id,
                "investor": deal.investor_profile_id,
            },
        )
    enqueue_sync(session, entity_type="deal", entity_id=deal.id, operation="update")
    return milestone


def add_evidence_photo(
    session: Session, owner: Profile, milestone_id: str, data: bytes, content_type: str | None
) -> Milestone:
    milestone, deal, side = _milestone(session, owner, milestone_id)
    if side != "farmer":
        raise TrustError("The farmer adds the photographs.", 403)
    if milestone.status == "approved":
        raise TrustError("This milestone is already approved.")
    media.save(session, entity_type="milestone", entity_id=milestone.id, data=data, content_type=content_type)
    return milestone


# --------------------------------------------------------------------------- #
# Disputes
# --------------------------------------------------------------------------- #


def open_dispute(session: Session, owner: Profile, data: DisputeInput) -> Dispute:
    deal = session.get(Deal, data.deal_id)
    if deal is None:
        raise TrustError("Deal not found.", 404)
    _party(deal, owner)
    if deal.status not in ("active", "completed"):
        raise TrustError("A dispute can be raised on an agreed deal.")
    if data.milestone_id and not any(m.id == data.milestone_id for m in deal.milestones):
        raise TrustError("That milestone is not part of this deal.", 422)
    if session.scalar(select(Dispute.id).where(Dispute.deal_id == deal.id, Dispute.status == "open")):
        raise TrustError("A dispute is already open on this deal.")

    dispute = Dispute(
        deal_id=deal.id,
        milestone_id=data.milestone_id,
        opened_by_profile_id=owner.id,
        reason=data.reason,
        description=data.description,
        origin="local",
    )
    session.add(dispute)
    deal.status = "disputed"
    session.flush()
    record_event(
        session, EventType.DISPUTE_OPENED, entity_type="dispute", entity_id=dispute.id,
        payload={"deal": deal.id, "reason": dispute.reason},
    )
    enqueue_sync(session, entity_type="dispute", entity_id=dispute.id, operation="create")
    enqueue_sync(session, entity_type="deal", entity_id=deal.id, operation="update")
    return dispute


def _close(session: Session, dispute: Dispute, status: str) -> None:
    deal = session.get(Deal, dispute.deal_id)
    dispute.status = status
    dispute.resolved_at = _now()
    if deal and deal.status == "disputed":
        deal.status = (
            "completed" if all(item.status == "approved" for item in deal.milestones) else "active"
        )
    _log(session, EventType.DISPUTE_CLOSED, "dispute", dispute.id, {"status": status})
    if deal:
        enqueue_sync(session, entity_type="deal", entity_id=deal.id, operation="update")


def update_dispute(session: Session, owner: Profile, dispute: Dispute, action: str, resolution: str | None) -> Dispute:
    deal = session.get(Deal, dispute.deal_id)
    if deal is None:
        raise TrustError("Dispute not found.", 404)
    _party(deal, owner)
    if dispute.status != "open":
        raise TrustError("This dispute is closed.")

    if action == "withdraw":
        if dispute.opened_by_profile_id != owner.id:
            raise TrustError("Only the side that raised a dispute can withdraw it.", 403)
        _close(session, dispute, "withdrawn")
    elif action == "propose":
        if not resolution or not resolution.strip():
            raise TrustError("Write down the resolution you propose.", 422)
        dispute.resolution = resolution.strip()
        dispute.resolution_proposed_by = owner.id
        _log(session, EventType.DISPUTE_UPDATED, "dispute", dispute.id, {"proposal": True})
    elif action == "confirm":
        if not dispute.resolution or dispute.resolution_proposed_by in (None, owner.id):
            raise TrustError("The other side has to confirm a resolution you proposed.", 403)
        _close(session, dispute, "resolved")
    return dispute


# --------------------------------------------------------------------------- #
# Ratings
# --------------------------------------------------------------------------- #


def _rating_target(session: Session, owner: Profile, context_type: str, context_id: str) -> str:
    """Who the owner may rate for this piece of work, or raise why not."""
    if context_type == "deal":
        deal = session.get(Deal, context_id)
        if deal is None:
            raise TrustError("Deal not found.", 404)
        _party(deal, owner)
        if deal.status != "completed":
            raise TrustError("Ratings open once every milestone is approved.")
        return _other(deal, owner)
    if context_type == "enquiry":
        enquiry = session.get(EquipmentEnquiry, context_id)
        if enquiry is None:
            raise TrustError("Enquiry not found.", 404)
        seller = enquiry.listing.profile_id
        if owner.id not in (seller, enquiry.profile_id):
            raise TrustError("Enquiry not found.", 404)
        # Agreeing is not the work: the hire has to be over, or the machine
        # handed over, before either side knows how it went.
        if enquiry.status != "completed":
            raise TrustError("Ratings open once the hire or sale is marked done.")
        return enquiry.profile_id if owner.id == seller else seller
    if context_type == "partnership":
        partnership = session.get(EquipmentPartnership, context_id)
        if partnership is None or owner.id not in (partnership.seller_profile_id, partnership.partner_profile_id):
            raise TrustError("Partnership not found.", 404)
        if not partnership.partner_profile_id:
            raise TrustError("An off-platform partner cannot be rated here.")
        # "ended" only follows "active": a proposal taken back is "withdrawn".
        if partnership.status not in ("active", "ended"):
            raise TrustError("Ratings open once the partnership is active.")
        return (
            partnership.partner_profile_id
            if owner.id == partnership.seller_profile_id
            else partnership.seller_profile_id
        )
    raise TrustError("Nothing to rate there.", 422)


def rate(session: Session, owner: Profile, data: RatingInput) -> Rating:
    target = _rating_target(session, owner, data.context_type, data.context_id)
    existing = session.scalars(
        select(Rating).where(
            Rating.rater_profile_id == owner.id,
            Rating.context_type == data.context_type,
            Rating.context_id == data.context_id,
        )
    ).first()
    rating = existing or Rating(
        rater_profile_id=owner.id,
        rated_profile_id=target,
        context_type=data.context_type,
        context_id=data.context_id,
        origin="local",
    )
    rating.stars = data.stars
    rating.comment = data.comment
    if existing is None:
        session.add(rating)
    session.flush()
    record_event(
        session, EventType.RATING_GIVEN, entity_type="rating", entity_id=rating.id,
        payload={"stars": rating.stars, "context": rating.context_type},
    )
    enqueue_sync(session, entity_type="rating", entity_id=rating.id, operation="create" if existing is None else "update")
    return rating


def rating_stats(session: Session, profile_id: str) -> tuple[float | None, int]:
    avg, count = session.execute(
        select(func.avg(Rating.stars), func.count(Rating.id)).where(Rating.rated_profile_id == profile_id)
    ).one()
    return (round(float(avg), 1) if avg is not None else None), int(count or 0)


def rating_state(session: Session, viewer: Profile, context_type: str, context_id: str) -> tuple[bool, RatingOut | None]:
    """Whether the viewer may rate this piece of work now, and what they gave."""
    try:
        _rating_target(session, viewer, context_type, context_id)
        can = True
    except TrustError:
        can = False
    mine = session.scalars(
        select(Rating).where(
            Rating.rater_profile_id == viewer.id,
            Rating.context_type == context_type,
            Rating.context_id == context_id,
        )
    ).first()
    return can, serialise_rating(session, mine) if mine else None


def _about(session: Session, rating: Rating) -> str | None:
    """What the work was, in a few words, as far as this device knows."""
    if rating.context_type == "deal":
        deal = session.get(Deal, rating.context_id)
        request = session.get(InvestmentRequest, deal.request_id) if deal else None
        return request.title if request else None
    if rating.context_type == "enquiry":
        enquiry = session.get(EquipmentEnquiry, rating.context_id)
        return enquiry.listing.title if enquiry and enquiry.listing else None
    return None


def serialise_rating(session: Session, rating: Rating) -> RatingOut:
    rater = session.get(Profile, rating.rater_profile_id)
    return RatingOut(
        id=rating.id,
        stars=rating.stars,
        comment=rating.comment,
        context_type=rating.context_type,
        context_id=rating.context_id,
        about=_about(session, rating),
        rater=card(session, rater),
        created_at=rating.created_at,
    )


def rating_summary(session: Session, profile_id: str) -> RatingSummaryOut:
    rows = list(
        session.scalars(
            select(Rating).where(Rating.rated_profile_id == profile_id).order_by(Rating.created_at.desc())
        )
    )
    average, count = rating_stats(session, profile_id)
    return RatingSummaryOut(
        average=average, count=count, ratings=[serialise_rating(session, row) for row in rows[:50]]
    )


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #


def serialise_milestone(session: Session, milestone: Milestone) -> MilestoneOut:
    return MilestoneOut(
        id=milestone.id,
        position=milestone.position,
        title=milestone.title,
        description=milestone.description,
        amount=milestone.amount,
        due_date=milestone.due_date,
        status=milestone.status,
        evidence_note=milestone.evidence_note,
        submitted_at=milestone.submitted_at,
        review_note=milestone.review_note,
        reviewed_at=milestone.reviewed_at,
        released_at=milestone.released_at,
        release_reference=milestone.release_reference,
        photos=[
            MediaOut(id=f.id, url=media.url_for(f), width=f.width, height=f.height, position=f.position)
            for f in media.for_entity(session, "milestone", milestone.id)
        ],
        overdue=bool(
            milestone.due_date
            and milestone.status in ("planned", "rejected")
            and milestone.due_date < date.today()
        ),
    )


def serialise_dispute(dispute: Dispute, owner: Profile) -> DisputeOut:
    proposed_by_me = (
        None if dispute.resolution_proposed_by is None else dispute.resolution_proposed_by == owner.id
    )
    return DisputeOut(
        id=dispute.id,
        deal_id=dispute.deal_id,
        milestone_id=dispute.milestone_id,
        opened_by_me=dispute.opened_by_profile_id == owner.id,
        reason=dispute.reason,
        description=dispute.description,
        status=dispute.status,
        resolution=dispute.resolution,
        resolution_proposed_by_me=proposed_by_me,
        can_confirm=dispute.status == "open" and proposed_by_me is False,
        created_at=dispute.created_at,
        resolved_at=dispute.resolved_at,
    )


def serialise(session: Session, deal: Deal, owner: Profile) -> DealOut:
    side = _party(deal, owner)
    request = session.get(InvestmentRequest, deal.request_id)
    farmer = session.get(Profile, deal.farmer_profile_id)
    investor = session.get(Profile, deal.investor_profile_id)
    disputes = session.scalars(
        select(Dispute).where(Dispute.deal_id == deal.id).order_by(Dispute.created_at.desc())
    )
    mine = session.scalars(
        select(Rating).where(
            Rating.rater_profile_id == owner.id, Rating.context_type == "deal", Rating.context_id == deal.id
        )
    ).first()
    # Both sides are connected by an accepted interest, so contact is shown.
    return DealOut(
        id=deal.id,
        interest_id=deal.interest_id,
        request_id=deal.request_id,
        request_title=request.title if request else "",
        farmer=card(session, farmer, reveal_contact=side == "investor"),
        investor=card(session, investor, reveal_contact=side == "farmer"),
        i_am=side,
        amount_total=deal.amount_total,
        amount_released=round(
            sum(item.amount for item in deal.milestones if item.status == "approved"), 2
        ),
        mode=deal.mode,
        terms=deal.terms,
        status=deal.status,
        proposed_by_me=deal.proposed_by == owner.id,
        can_agree=deal.status == "drafting" and deal.proposed_by != owner.id,
        milestones=[serialise_milestone(session, item) for item in deal.milestones],
        disputes=[serialise_dispute(item, owner) for item in disputes],
        can_rate=deal.status == "completed",
        my_rating=serialise_rating(session, mine) if mine else None,
        created_at=deal.created_at,
        agreed_at=deal.agreed_at,
        completed_at=deal.completed_at,
    )


def my_deals(session: Session, owner: Profile) -> list[DealOut]:
    rows = session.scalars(
        select(Deal)
        .where(or_(Deal.farmer_profile_id == owner.id, Deal.investor_profile_id == owner.id))
        .order_by(Deal.updated_at.desc())
    )
    return [serialise(session, deal, owner) for deal in rows]


def deal_for(session: Session, owner: Profile, deal_id: str) -> Deal:
    deal = session.get(Deal, deal_id)
    if deal is None:
        raise TrustError("Deal not found.", 404)
    _party(deal, owner)
    return deal


# --------------------------------------------------------------------------- #
# What arrives from the other side, by sync
# --------------------------------------------------------------------------- #


def on_incoming_deal(session: Session, deal: Deal, before: dict | None) -> None:
    """Tell the owner what the other side just did to a deal they share."""
    owner_id = session.scalar(select(Profile.id).where(Profile.is_device_owner.is_(True)))
    if owner_id not in (deal.farmer_profile_id, deal.investor_profile_id):
        return
    link = f"/deals/{deal.id}"
    previous = (before or {}).get("status")
    if before is None and deal.proposed_by != owner_id:
        notify(session, owner_id, "deal_proposed", params={"amount": deal.amount_total}, link=link,
               entity_type="deal", entity_id=deal.id)
    elif previous != deal.status and deal.status in ("active", "completed", "disputed", "cancelled"):
        notify(session, owner_id, f"deal_{deal.status}", params={"amount": deal.amount_total}, link=link,
               entity_type="deal", entity_id=deal.id)
    before_ms = {m["id"]: m.get("status") for m in (before or {}).get("milestones", [])}
    for milestone in deal.milestones:
        was = before_ms.get(milestone.id)
        if was == milestone.status:
            continue
        if milestone.status == "submitted" and owner_id == deal.investor_profile_id:
            notify(session, owner_id, "milestone_submitted", params={"title": milestone.title},
                   link=link, entity_type="milestone", entity_id=milestone.id)
        elif milestone.status in ("approved", "rejected") and owner_id == deal.farmer_profile_id:
            notify(session, owner_id, f"milestone_{milestone.status}",
                   params={"title": milestone.title, "amount": milestone.amount},
                   link=link, entity_type="milestone", entity_id=milestone.id)
