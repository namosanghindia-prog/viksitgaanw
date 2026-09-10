"""Deals and milestones, disputes, and ratings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Dispute, Profile
from ..schemas import (
    DealInput,
    DealOut,
    DealPlanInput,
    DisputeInput,
    DisputeUpdate,
    MilestoneReview,
    MilestoneSubmit,
    RatingInput,
    RatingOut,
    RatingSummaryOut,
)
from ..services import media, trust
from ..services.trust import TrustError
from .deps import fail, owner

router = APIRouter(tags=["trust"])


def _deal_out(session: Session, me: Profile, deal_id: str) -> DealOut:
    session.commit()
    return trust.serialise(session, trust.deal_for(session, me, deal_id), me)


@router.get("/deals", response_model=list[DealOut])
def my_deals(me: Profile = Depends(owner), session: Session = Depends(get_session)) -> list[DealOut]:
    return trust.my_deals(session, me)


@router.post("/deals", response_model=DealOut, status_code=status.HTTP_201_CREATED)
def create_deal(payload: DealInput, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> DealOut:
    """Turn an accepted investment into a milestone plan for the other side to agree."""
    try:
        deal = trust.create_deal(session, me, payload)
    except TrustError as exc:
        raise fail(exc) from exc
    return _deal_out(session, me, deal.id)


@router.get("/deals/{deal_id}", response_model=DealOut)
def get_deal(deal_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> DealOut:
    try:
        return trust.serialise(session, trust.deal_for(session, me, deal_id), me)
    except TrustError as exc:
        raise fail(exc) from exc


@router.put("/deals/{deal_id}/plan", response_model=DealOut)
def replace_plan(
    deal_id: str, payload: DealPlanInput, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> DealOut:
    try:
        trust.replace_plan(session, me, trust.deal_for(session, me, deal_id), payload)
    except TrustError as exc:
        raise fail(exc) from exc
    return _deal_out(session, me, deal_id)


@router.post("/deals/{deal_id}/agree", response_model=DealOut)
def agree(deal_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> DealOut:
    try:
        trust.agree(session, me, trust.deal_for(session, me, deal_id))
    except TrustError as exc:
        raise fail(exc) from exc
    return _deal_out(session, me, deal_id)


@router.post("/deals/{deal_id}/cancel", response_model=DealOut)
def cancel(deal_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> DealOut:
    try:
        trust.cancel(session, me, trust.deal_for(session, me, deal_id))
    except TrustError as exc:
        raise fail(exc) from exc
    return _deal_out(session, me, deal_id)


@router.post("/milestones/{milestone_id}/submit", response_model=DealOut)
def submit_milestone(
    milestone_id: str, payload: MilestoneSubmit, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> DealOut:
    try:
        milestone = trust.submit(session, me, milestone_id, payload.note)
    except TrustError as exc:
        raise fail(exc) from exc
    return _deal_out(session, me, milestone.deal_id)


@router.post("/milestones/{milestone_id}/review", response_model=DealOut)
def review_milestone(
    milestone_id: str, payload: MilestoneReview, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> DealOut:
    """Approve (and record releasing the tranche) or send the evidence back."""
    try:
        milestone = trust.review(session, me, milestone_id, payload)
    except TrustError as exc:
        raise fail(exc) from exc
    return _deal_out(session, me, milestone.deal_id)


@router.post("/milestones/{milestone_id}/photos", response_model=DealOut)
async def add_milestone_photo(
    milestone_id: str, request: Request, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> DealOut:
    """Evidence photographs. The body is the image itself."""
    data = await request.body()
    try:
        milestone = trust.add_evidence_photo(session, me, milestone_id, data, request.headers.get("content-type"))
    except (TrustError, media.MediaError) as exc:
        raise fail(exc) from exc
    return _deal_out(session, me, milestone.deal_id)


@router.post("/disputes", response_model=DealOut, status_code=status.HTTP_201_CREATED)
def open_dispute(payload: DisputeInput, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> DealOut:
    try:
        trust.open_dispute(session, me, payload)
    except TrustError as exc:
        raise fail(exc) from exc
    return _deal_out(session, me, payload.deal_id)


@router.patch("/disputes/{dispute_id}", response_model=DealOut)
def update_dispute(
    dispute_id: str, payload: DisputeUpdate, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> DealOut:
    dispute = session.get(Dispute, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=404, detail="Dispute not found.")
    try:
        trust.update_dispute(session, me, dispute, payload.action, payload.resolution)
    except TrustError as exc:
        raise fail(exc) from exc
    return _deal_out(session, me, dispute.deal_id)


@router.post("/ratings", response_model=RatingOut, status_code=status.HTTP_201_CREATED)
def rate(payload: RatingInput, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> RatingOut:
    """Rate the other side once the work is done. Rating again replaces it."""
    try:
        rating = trust.rate(session, me, payload)
    except TrustError as exc:
        raise fail(exc) from exc
    session.commit()
    return trust.serialise_rating(session, rating)


@router.get("/profiles/{profile_id}/ratings", response_model=RatingSummaryOut)
def ratings_for(profile_id: str, session: Session = Depends(get_session)) -> RatingSummaryOut:
    if session.get(Profile, profile_id) is None:
        raise HTTPException(status_code=404, detail="Person not found.")
    return trust.rating_summary(session, profile_id)
