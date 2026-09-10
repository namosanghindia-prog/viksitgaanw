"""Insurance policies on plots, profiles and investment requests.

Like the marketplace, every write acts as the device owner. A request's own
cover is also returned inside the request itself, masked for anyone the
farmer has not accepted; these endpoints are for the owner managing theirs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import InsurancePolicy, LandParcel, Profile
from ..schemas import InsuranceCreate, InsuranceInput, InsuranceOut, InsuranceRequirementOut
from ..services import insurance
from ..services.insurance import InsuranceError
from ..services.profiles import get_owner

router = APIRouter(prefix="/insurance", tags=["insurance"])


def _owner(session: Session) -> Profile:
    owner = get_owner(session)
    if owner is None:
        raise HTTPException(status_code=409, detail="Set up your profile first.")
    return owner


def _fail(error: InsuranceError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=str(error))


@router.get("/requirements", response_model=InsuranceRequirementOut)
def get_requirements(
    opportunity_code: str | None = Query(default=None, alias="opportunityCode"),
    kind: str | None = Query(default=None),
) -> InsuranceRequirementOut:
    """Which cover a project for this farming option must carry."""
    return insurance.requirements(opportunity_code, kind)


@router.get("", response_model=list[InsuranceOut])
def list_policies(
    parcel_id: str | None = Query(default=None, alias="parcelId"),
    session: Session = Depends(get_session),
) -> list[InsuranceOut]:
    """Policies on one plot, or (with no plot given) on the owner's profile."""
    if parcel_id:
        if session.get(LandParcel, parcel_id) is None:
            raise HTTPException(status_code=404, detail="Land parcel not found.")
        policies = insurance.list_for(session, parcel_id=parcel_id)
    else:
        policies = insurance.list_for(session, profile_id=_owner(session).id)
    return [insurance.serialise(policy, full=True) for policy in policies]


@router.post("", response_model=InsuranceOut, status_code=status.HTTP_201_CREATED)
def add_policy(payload: InsuranceCreate, session: Session = Depends(get_session)) -> InsuranceOut:
    owner = _owner(session)
    try:
        policy = insurance.add(session, owner, payload)
    except InsuranceError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(policy)
    return insurance.serialise(policy, full=True)


@router.put("/{policy_id}", response_model=InsuranceOut)
def update_policy(
    policy_id: str, payload: InsuranceInput, session: Session = Depends(get_session)
) -> InsuranceOut:
    """Replace a policy's details -- typically turning a promise into a policy."""
    owner = _owner(session)
    policy = session.get(InsurancePolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Insurance policy not found.")
    try:
        insurance.update(session, owner, policy, payload)
    except InsuranceError as exc:
        raise _fail(exc) from exc
    session.commit()
    session.refresh(policy)
    return insurance.serialise(policy, full=True)


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy(policy_id: str, session: Session = Depends(get_session)) -> None:
    owner = _owner(session)
    policy = session.get(InsurancePolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Insurance policy not found.")
    try:
        insurance.remove(session, owner, policy)
    except InsuranceError as exc:
        raise _fail(exc) from exc
    session.commit()
