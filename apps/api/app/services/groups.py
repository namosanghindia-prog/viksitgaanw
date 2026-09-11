"""Farmer groups: pooling small plots into something an investor can fund.

Most Indian farmers hold under two hectares. An investor, a buyer or a bank
looking for fifty hectares of one crop will not talk to twenty-five farmers
separately, but will talk to their FPO. A group records who its members are
and the land each brings; it can ask for investment on behalf of all of them.

Members need not use the app: the group's organiser adds them by name and
phone, which is how most FPO registers work. A farmer who *is* on the app
can also ask to join a group that has been shared online.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import segments as seg
from ..models import FarmerGroup, GroupMember, InvestmentRequest, Profile
from ..schemas import (
    GroupInput,
    GroupJoinInput,
    GroupMemberInput,
    GroupMemberOut,
    GroupOut,
    GroupRequestInput,
)
from . import insurance as cover
from . import videos
from .events import EventType, enqueue_sync, record_event
from .hierarchy import location_error, resolve_location
from .marketplace import make_listing, opportunity_summary
from .notify import notify
from .profiles import card

ENTITY = "farmer_group"
ORGANISER_TYPES = ("fpo", "cooperative", "shg")


class GroupError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _can_organise(owner: Profile) -> bool:
    if owner.segment == seg.FARMER:
        return True
    return (
        owner.segment == "partner_national"
        and (owner.details or {}).get("organisation_type") in ORGANISER_TYPES
    )


def _place(session: Session, group: FarmerGroup) -> str | None:
    path = resolve_location(
        session,
        subdistrict_code=group.subdistrict_code,
        district_code=group.district_code,
        state_code=group.state_code,
    )
    return ", ".join(u.name for u in (path.subdistrict, path.district, path.state) if u) or None


def active_members(group: FarmerGroup) -> list[GroupMember]:
    return [member for member in group.members if member.status == "active"]


def _member_out(session: Session, member: GroupMember, *, owner_view: bool) -> GroupMemberOut:
    village = None
    if member.village_code:
        path = resolve_location(session, village_code=member.village_code)
        village = path.village.name if path.village else None
    profile = session.get(Profile, member.profile_id) if member.profile_id else None
    return GroupMemberOut(
        id=member.id,
        profile=card(session, profile) if profile else None,
        name=member.name or (profile.display_name if profile else None),
        phone=member.phone if owner_view else None,
        village=village,
        land_hectares=member.land_hectares,
        crops=list(member.crops or []),
        status=member.status,
        created_at=member.created_at,
    )


def serialise(session: Session, group: FarmerGroup, viewer: Profile) -> GroupOut:
    mine = group.owner_profile_id == viewer.id
    active = active_members(group)
    own = next((m for m in group.members if m.profile_id == viewer.id), None)
    request_ids = list(
        session.scalars(select(InvestmentRequest.id).where(InvestmentRequest.group_id == group.id))
    )
    return GroupOut(
        id=group.id,
        name=group.name,
        kind=group.kind,
        description=group.description,
        intro_video=videos.out(group.intro_video),
        state_code=group.state_code,
        district_code=group.district_code,
        subdistrict_code=group.subdistrict_code,
        place=_place(session, group),
        crops=list(group.crops or []),
        visibility=group.visibility,
        shared_at=group.shared_at,
        owner=card(session, session.get(Profile, group.owner_profile_id)),
        is_mine=mine,
        member_count=len(active),
        total_hectares=round(sum(m.land_hectares for m in active), 3),
        members=[_member_out(session, m, owner_view=True) for m in group.members] if mine else [],
        my_membership=_member_out(session, own, owner_view=False) if own and not mine else None,
        request_ids=request_ids,
        origin=group.origin,
        created_at=group.created_at,
    )


def _apply(session: Session, group: FarmerGroup, data: GroupInput) -> None:
    error = location_error(
        session,
        state_code=data.state_code,
        district_code=data.district_code,
        subdistrict_code=data.subdistrict_code,
    )
    if error:
        raise GroupError(error, 422)
    for field in ("name", "kind", "description", "state_code", "district_code", "subdistrict_code", "crops"):
        setattr(group, field, getattr(data, field))


def create(session: Session, owner: Profile, data: GroupInput) -> FarmerGroup:
    if not _can_organise(owner):
        raise GroupError("Farmers and FPOs, cooperatives or self-help groups can run a group.", 403)
    group = FarmerGroup(owner_profile_id=owner.id, origin="local")
    _apply(session, group, data)
    session.add(group)
    session.flush()
    record_event(session, EventType.GROUP_CREATED, entity_type=ENTITY, entity_id=group.id,
                 payload={"kind": group.kind, "district": group.district_code})
    enqueue_sync(session, entity_type=ENTITY, entity_id=group.id, operation="create")
    return group


def owned(session: Session, owner: Profile, group_id: str) -> FarmerGroup:
    group = session.get(FarmerGroup, group_id)
    if group is None or group.owner_profile_id != owner.id:
        raise GroupError("Group not found.", 404)
    return group


def visible(session: Session, viewer: Profile, group_id: str) -> FarmerGroup:
    group = session.get(FarmerGroup, group_id)
    if group is None:
        raise GroupError("Group not found.", 404)
    member = any(m.profile_id == viewer.id for m in group.members)
    if group.owner_profile_id != viewer.id and group.visibility != "online" and not member:
        raise GroupError("Group not found.", 404)
    return group


def update(session: Session, owner: Profile, group: FarmerGroup, data: GroupInput) -> FarmerGroup:
    _apply(session, group, data)
    _changed(session, group)
    return group


def delete(session: Session, owner: Profile, group: FarmerGroup) -> None:
    enqueue_sync(session, entity_type=ENTITY, entity_id=group.id, operation="delete")
    session.delete(group)


def _changed(session: Session, group: FarmerGroup) -> None:
    record_event(session, EventType.GROUP_UPDATED, entity_type=ENTITY, entity_id=group.id)
    enqueue_sync(session, entity_type=ENTITY, entity_id=group.id, operation="update")


def add_member(session: Session, group: FarmerGroup, data: GroupMemberInput) -> GroupMember:
    if data.village_code:
        path = resolve_location(session, village_code=data.village_code)
        if path.village is None:
            raise GroupError(f"Unknown village code: {data.village_code}", 422)
    member = GroupMember(
        group_id=group.id,
        name=data.name,
        phone=data.phone,
        village_code=data.village_code,
        land_hectares=data.land_hectares,
        crops=data.crops,
        status="active",
        origin="local",
    )
    group.members.append(member)
    session.flush()
    _changed(session, group)
    return member


def set_member_status(session: Session, group: FarmerGroup, member_id: str, status: str) -> GroupMember:
    member = next((m for m in group.members if m.id == member_id), None)
    if member is None:
        raise GroupError("Member not found.", 404)
    if status not in ("active", "left"):
        raise GroupError("A member is either active or has left.", 422)
    member.status = status
    _changed(session, group)
    return member


def remove_member(session: Session, group: FarmerGroup, member_id: str) -> None:
    member = next((m for m in group.members if m.id == member_id), None)
    if member is None:
        raise GroupError("Member not found.", 404)
    group.members.remove(member)
    _changed(session, group)


def join(session: Session, owner: Profile, group: FarmerGroup, data: GroupJoinInput) -> GroupMember:
    if owner.segment != seg.FARMER:
        raise GroupError("Farmers join groups.", 403)
    if group.owner_profile_id == owner.id:
        raise GroupError("You run this group.")
    if owner.visibility != "online":
        raise GroupError("Share your profile online first, so the organiser can see who is asking.")
    if any(m.profile_id == owner.id and m.status != "left" for m in group.members):
        raise GroupError("You have already asked to join, or are a member.")
    member = GroupMember(
        group_id=group.id,
        profile_id=owner.id,
        village_code=owner.village_code,
        land_hectares=data.land_hectares,
        crops=data.crops,
        status="requested",
        origin="local",
    )
    group.members.append(member)
    session.flush()
    enqueue_sync(session, entity_type=ENTITY, entity_id=group.id, operation="update")
    return member


def leave(session: Session, owner: Profile, group: FarmerGroup) -> None:
    member = next((m for m in group.members if m.profile_id == owner.id and m.status != "left"), None)
    if member is None:
        raise GroupError("You are not in this group.", 404)
    member.status = "left"
    enqueue_sync(session, entity_type=ENTITY, entity_id=group.id, operation="update")


def mine(session: Session, owner: Profile) -> list[GroupOut]:
    member_of = select(GroupMember.group_id).where(GroupMember.profile_id == owner.id)
    rows = session.scalars(
        select(FarmerGroup)
        .where(or_(FarmerGroup.owner_profile_id == owner.id, FarmerGroup.id.in_(member_of)))
        .order_by(FarmerGroup.created_at.desc())
    )
    return [serialise(session, group, owner) for group in rows]


def browse(session: Session, viewer: Profile, *, district_code: str | None = None) -> list[GroupOut]:
    stmt = (
        select(FarmerGroup)
        .where(FarmerGroup.visibility == "online", FarmerGroup.owner_profile_id != viewer.id)
        .order_by(FarmerGroup.shared_at.desc())
    )
    if district_code:
        stmt = stmt.where(FarmerGroup.district_code == district_code)
    rows = [serialise(session, group, viewer) for group in session.scalars(stmt)]
    # Groups in the viewer's own district first: that is the one they can join.
    rows.sort(key=lambda row: row.district_code != viewer.district_code)
    return rows


def create_group_request(
    session: Session, owner: Profile, group: FarmerGroup, data: GroupRequestInput
) -> InvestmentRequest:
    """Ask for investment on behalf of every active member's land together."""
    members = active_members(group)
    if not members:
        raise GroupError("Add the members and their land before asking for investment.", 422)
    opportunity = opportunity_summary(data.opportunity_code)
    if data.opportunity_code and opportunity is None:
        raise GroupError(f"Unknown farming option: {data.opportunity_code}", 422)
    rule = cover.requirements(data.opportunity_code, opportunity["kind"] if opportunity else None)
    shortfall = cover.request_cover_error(rule.required, data.insurance)
    if shortfall:
        raise GroupError(shortfall, 422)

    crops = sorted({crop for member in members for crop in (member.crops or [])} | set(group.crops or []))
    land = {
        "areaHectares": round(sum(member.land_hectares for member in members), 3),
        "existingCrops": crops,
        "members": len(members),
        "groupName": group.name,
        "groupKind": group.kind,
    }
    request = InvestmentRequest(
        profile_id=owner.id,
        group_id=group.id,
        opportunity_code=data.opportunity_code,
        opportunity_kind=opportunity["kind"] if opportunity else None,
        state_code=group.state_code,
        district_code=group.district_code,
        subdistrict_code=group.subdistrict_code,
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
            state_code=group.state_code,
            district_code=group.district_code,
            subdistrict_code=group.subdistrict_code,
            village_code=None,
            land=land,
            opportunity_code=data.opportunity_code,
            plan=None,
        ),
        status="open",
        origin="local",
    )
    session.add(request)
    session.flush()
    record_event(
        session,
        EventType.REQUEST_CREATED,
        entity_type="investment_request",
        entity_id=request.id,
        payload={"group": group.id, "members": len(members), "amount_sought": request.amount_sought},
    )
    enqueue_sync(session, entity_type="investment_request", entity_id=request.id, operation="create")
    cover.add_to_request(session, request, data.insurance)
    return request


def on_join_request(session: Session, group: FarmerGroup, member: GroupMember) -> None:
    """A join request arrived by sync: tell the organiser."""
    asker = session.get(Profile, member.profile_id) if member.profile_id else None
    notify(
        session,
        group.owner_profile_id,
        "group_join_requested",
        params={"name": asker.display_name if asker else member.name, "group": group.name},
        link=f"/groups/{group.id}",
        entity_type=ENTITY,
        entity_id=member.id,
    )
