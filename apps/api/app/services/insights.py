"""What is happening, in numbers, across the area a viewer is responsible for.

A block officer wants their block, a district officer their district, an FPO
its state, and the platform the whole country. The figures are counted from
what this device holds -- its own records plus everything sync has brought
in -- so they grow as more of the network is connected, and are always as
current as the last sync.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import knowledge, reference
from .. import segments as seg
from ..models import (
    Deal,
    EquipmentEnquiry,
    EquipmentListing,
    FarmerGroup,
    InvestmentInterest,
    InvestmentRequest,
    Profile,
)
from ..schemas import CountBucket, InsightsOut
from .hierarchy import resolve_location


def _scope(owner: Profile) -> tuple[str, dict[str, str | None]]:
    if owner.segment == seg.GOVERNMENT:
        level = (owner.details or {}).get("level")
        if level in ("gram_panchayat", "block"):
            return "subdistrict", {"subdistrict_code": owner.subdistrict_code}
        if level == "district":
            return "district", {"district_code": owner.district_code}
        if level == "state":
            return "state", {"state_code": owner.state_code}
    if owner.segment == "partner_national" and owner.state_code:
        return "state", {"state_code": owner.state_code}
    return "national", {}


def _within(row, where: dict[str, str | None]) -> bool:
    return all(getattr(row, field, None) == value for field, value in where.items())


def _kind_label(code: str) -> str | None:
    kind = knowledge.kind_index().get(code)
    return kind.get("label", {}).get("en") if kind else None


def compute(session: Session, owner: Profile) -> InsightsOut:
    scope, where = _scope(owner)

    requests = [
        row
        for row in session.scalars(select(InvestmentRequest).where(InvestmentRequest.status == "open"))
        if (row.visibility == "online" or row.profile_id == owner.id) and _within(row, where)
    ]
    request_ids = {row.id for row in requests}
    interests = [
        row for row in session.scalars(select(InvestmentInterest)) if row.request_id in request_ids
    ]
    deals = [row for row in session.scalars(select(Deal)) if row.request_id in request_ids]
    machines = [
        row
        for row in session.scalars(select(EquipmentListing).where(EquipmentListing.status == "active"))
        if (row.visibility == "online" or row.profile_id == owner.id) and _within(row, where)
    ]
    machine_ids = {row.id for row in machines}
    groups = [
        row
        for row in session.scalars(select(FarmerGroup))
        if (row.visibility == "online" or row.owner_profile_id == owner.id) and _within(row, where)
    ]
    farmers = [
        row
        for row in session.scalars(select(Profile).where(Profile.segment == seg.FARMER))
        if _within(row, where)
    ]

    by_kind: Counter[str] = Counter()
    sought_by_kind: dict[str, float] = defaultdict(float)
    by_state: Counter[str] = Counter()
    sought_by_state: dict[str, float] = defaultdict(float)
    for row in requests:
        kind = row.opportunity_kind or "other"
        by_kind[kind] += 1
        sought_by_kind[kind] += row.amount_sought
        by_state[row.state_code] += 1
        sought_by_state[row.state_code] += row.amount_sought

    state_names = {}
    for code in by_state:
        path = resolve_location(session, state_code=code)
        state_names[code] = path.state.name if path.state else code

    machine_types = Counter(row.equipment_type for row in machines)
    rentals = sum(
        1
        for row in session.scalars(select(EquipmentEnquiry).where(EquipmentEnquiry.status == "accepted"))
        if row.listing_id in machine_ids
    )
    active_members = [m for group in groups for m in group.members if m.status == "active"]

    place = None
    if where:
        path = resolve_location(session, **where)
        place = ", ".join(u.name for u in (path.subdistrict, path.district, path.state) if u) or None

    return InsightsOut(
        scope=scope,
        place=place,
        farmers=len(farmers),
        requests_open=len(requests),
        amount_sought=round(sum(row.amount_sought for row in requests), 2),
        requests_by_kind=[
            CountBucket(code=code, label=_kind_label(code), count=count, amount=round(sought_by_kind[code], 2))
            for code, count in by_kind.most_common()
        ],
        requests_by_state=[
            CountBucket(code=code, label=state_names[code], count=count, amount=round(sought_by_state[code], 2))
            for code, count in by_state.most_common(12)
        ],
        interests=len(interests),
        matches=sum(1 for row in interests if row.status == "accepted"),
        deals_active=sum(1 for row in deals if row.status in ("active", "disputed")),
        deals_completed=sum(1 for row in deals if row.status == "completed"),
        amount_released=round(
            sum(m.amount for deal in deals for m in deal.milestones if m.status == "approved"), 2
        ),
        machines=len(machines),
        machines_by_type=[
            CountBucket(code=code, label=reference.label_of("equipment_types", code), count=count)
            for code, count in machine_types.most_common()
        ],
        rentals_agreed=rentals,
        groups=len(groups),
        group_members=len(active_members),
        group_hectares=round(sum(m.land_hectares for m in active_members), 2),
        generated_at=datetime.now(timezone.utc),
    )
