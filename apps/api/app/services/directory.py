"""Finding each other: farmers find investors, investors find farmers.

Investors could already browse farmers' project requests ("Opportunities").
This adds the other direction, and the people behind the projects:

* **Find investors.** For a farmer: every investor -- and every partner
  organisation that also invests -- who has shared their profile online. The
  profile *is* the listing: what they fund, how much, where, how, and a video
  about it. Ranked by how well they suit the farmer's own open requests,
  using the same match investors see from their side.
* **Send my project.** The farmer puts one of their shared requests in front
  of an investor they found (a ``ProjectInvite``). The investor is notified
  and sees the request pinned at the top of their Opportunities, and answers
  the usual way -- with an interest, which the farmer accepts or declines.
* **Find farmers.** For an investor or partner: the farmers who shared their
  profile, with their biodata video and the open projects the viewer may see.

Contact details stay hidden throughout, exactly as on a request: they are
shared once the farmer accepts, or the two people connect.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import segments as seg
from ..models import InvestmentInterest, InvestmentRequest, Profile, ProjectInvite
from ..schemas import (
    FarmerListingOut,
    FarmerRequestBrief,
    FitOut,
    InvestorListingOut,
    ProjectInviteInput,
    ProjectInviteOut,
)
from . import marketplace, videos
from .events import EventType, enqueue_sync, record_event
from .profiles import card

ENTITY = "project_invite"


class DirectoryError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _online(session: Session, segments: tuple[str, ...], exclude: str) -> list[Profile]:
    return list(
        session.scalars(
            select(Profile)
            .where(Profile.visibility == "online", Profile.id != exclude, Profile.segment.in_(segments))
            .order_by(Profile.display_name)
        )
    )


def _open_requests(session: Session, farmer_id: str) -> list[InvestmentRequest]:
    return list(
        session.scalars(
            select(InvestmentRequest).where(
                InvestmentRequest.profile_id == farmer_id,
                InvestmentRequest.status == "open",
                InvestmentRequest.visibility == "online",
            )
        )
    )


def _invites(session: Session, *, farmer_id: str | None = None, investor_id: str | None = None) -> list[ProjectInvite]:
    stmt = select(ProjectInvite)
    if farmer_id:
        stmt = stmt.where(ProjectInvite.farmer_profile_id == farmer_id)
    if investor_id:
        stmt = stmt.where(ProjectInvite.investor_profile_id == investor_id)
    return list(session.scalars(stmt))


def _best(fits: list[FitOut | None]) -> FitOut | None:
    scored = [f for f in fits if f is not None]
    return max(scored, key=lambda f: f.score) if scored else None


# --------------------------------------------------------------------------- #
# Find investors
# --------------------------------------------------------------------------- #


def _terms(investor: Profile) -> dict:
    """What an investor or investing partner says they fund, from their profile."""
    details = investor.details or {}
    if investor.segment in seg.INVESTORS:
        return {
            "sectors": details.get("sectors") or [],
            "modes": details.get("modes") or [],
            "preferred_states": details.get("preferred_states") or [],
            "ticket_min": details.get("ticket_min"),
            "ticket_max": details.get("ticket_max"),
        }
    return {
        "sectors": [],
        "modes": details.get("investment_modes") or [],
        "preferred_states": details.get("operating_states") or [],
        "ticket_min": details.get("ticket_min"),
        "ticket_max": details.get("ticket_max"),
    }


def investors(session: Session, farmer: Profile, *, state_code: str | None = None) -> list[InvestorListingOut]:
    if farmer.segment != seg.FARMER:
        raise DirectoryError("Finding investors is for farmers.", 403)
    requests = _open_requests(session, farmer.id)
    sent: dict[str, set[str]] = {}
    for invite in _invites(session, farmer_id=farmer.id):
        sent.setdefault(invite.investor_profile_id, set()).add(invite.request_id)

    rows: list[tuple[tuple, InvestorListingOut]] = []
    for investor in _online(session, seg.RESPONDERS, farmer.id):
        if not videos.lists_investments(investor):
            continue
        terms = _terms(investor)
        if state_code and terms["preferred_states"] and state_code not in terms["preferred_states"]:
            continue
        visible = [r for r in requests if marketplace.visible_to(r, investor)]
        answered = {
            interest.request_id
            for interest in session.scalars(
                select(InvestmentInterest).where(
                    InvestmentInterest.profile_id == investor.id,
                    InvestmentInterest.request_id.in_([r.id for r in visible] or [""]),
                )
            )
        }
        invited = sent.get(investor.id, set())
        fit = _best([marketplace.fit(r, investor) for r in visible])
        in_my_state = not terms["preferred_states"] or farmer.state_code in terms["preferred_states"]
        listing = InvestorListingOut(
            profile=card(session, investor),
            about=investor.about,
            intro_video=videos.out(investor.intro_video),
            currency="USD" if investor.segment.endswith("international") else "INR",
            fit=fit,
            sendable_request_ids=[r.id for r in visible if r.id not in invited and r.id not in answered],
            invited_request_ids=sorted(invited),
            answered_request_ids=sorted(answered),
            **terms,
        )
        rows.append(((-(fit.score if fit else -1), not in_my_state, investor.display_name.lower()), listing))
    rows.sort(key=lambda row: row[0])
    return [listing for _, listing in rows]


# --------------------------------------------------------------------------- #
# Find farmers
# --------------------------------------------------------------------------- #


def farmers(session: Session, viewer: Profile, *, state_code: str | None = None) -> list[FarmerListingOut]:
    if viewer.segment not in seg.RESPONDERS:
        raise DirectoryError("Finding farmers is for investors and partners.", 403)
    invited_by = {invite.request_id for invite in _invites(session, investor_id=viewer.id)}
    preferred = set(_terms(viewer)["preferred_states"])

    rows: list[tuple[tuple, FarmerListingOut]] = []
    for farmer in _online(session, (seg.FARMER,), viewer.id):
        if state_code and farmer.state_code != state_code:
            continue
        briefs = [
            FarmerRequestBrief(
                id=r.id,
                title=r.title,
                amount_sought=r.amount_sought,
                fit=marketplace.fit(r, viewer),
                invited_me=r.id in invited_by,
            )
            for r in _open_requests(session, farmer.id)
            if marketplace.visible_to(r, viewer)
        ]
        briefs.sort(key=lambda b: -(b.fit.score if b.fit else 0))
        details = farmer.details or {}
        best = _best([b.fit for b in briefs])
        rows.append(
            (
                (
                    not any(b.invited_me for b in briefs),
                    -(best.score if best else -1),
                    not (farmer.state_code in preferred) if preferred else False,
                    farmer.display_name.lower(),
                ),
                FarmerListingOut(
                    profile=card(session, farmer),
                    about=farmer.about,
                    years_farming=details.get("years_farming"),
                    needs=details.get("needs") or [],
                    fpo_member=bool(details.get("fpo_member")),
                    has_kcc=bool(details.get("has_kcc")),
                    requests=briefs,
                ),
            )
        )
    rows.sort(key=lambda row: row[0])
    return [listing for _, listing in rows]


# --------------------------------------------------------------------------- #
# Invites
# --------------------------------------------------------------------------- #


def invite(session: Session, farmer: Profile, investor_id: str, data: ProjectInviteInput) -> ProjectInvite:
    if farmer.segment != seg.FARMER:
        raise DirectoryError("Only a farmer can send their project.", 403)
    investor = session.get(Profile, investor_id)
    if investor is None or investor.visibility != "online" or not videos.lists_investments(investor):
        raise DirectoryError("That investor is not listed.", 404)
    request = session.get(InvestmentRequest, data.request_id)
    if request is None or request.profile_id != farmer.id:
        raise DirectoryError("Project request not found.", 404)
    if request.status != "open" or request.visibility != "online":
        raise DirectoryError("Share the project request online first.")
    if not marketplace.visible_to(request, investor):
        raise DirectoryError("This project is not shown to their kind of investor. Change who can see it first.")
    if "investment" not in (request.seeking or []):
        raise DirectoryError("This project is not asking for investment.")
    if any(interest.profile_id == investor.id for interest in request.interests):
        raise DirectoryError("They have already answered this project.")
    existing = session.scalars(
        select(ProjectInvite).where(
            ProjectInvite.request_id == request.id, ProjectInvite.investor_profile_id == investor.id
        )
    ).first()
    if existing is not None:
        raise DirectoryError("You have already sent them this project.")

    row = ProjectInvite(
        request_id=request.id,
        farmer_profile_id=farmer.id,
        investor_profile_id=investor.id,
        message=data.message,
        origin="local",
    )
    session.add(row)
    session.flush()
    record_event(session, EventType.INVITE_SENT, entity_type=ENTITY, entity_id=row.id,
                 payload={"request_id": request.id, "segment": investor.segment})
    enqueue_sync(session, entity_type=ENTITY, entity_id=row.id, operation="create")
    return row


def decline(session: Session, investor: Profile, row: ProjectInvite) -> ProjectInvite:
    if row.investor_profile_id != investor.id:
        raise DirectoryError("Only the investor it was sent to can answer it.", 403)
    if row.status != "sent":
        raise DirectoryError("This has already been answered.")
    row.status, row.responded_at = "declined", _now()
    session.flush()
    record_event(session, EventType.INVITE_DECLINED, entity_type=ENTITY, entity_id=row.id)
    enqueue_sync(session, entity_type=ENTITY, entity_id=row.id, operation="update")
    return row


def mark_answered(session: Session, investor: Profile, request: InvestmentRequest) -> None:
    """The investor sent an interest: any invite for that project is answered."""
    for row in session.scalars(
        select(ProjectInvite).where(
            ProjectInvite.request_id == request.id,
            ProjectInvite.investor_profile_id == investor.id,
            ProjectInvite.status == "sent",
        )
    ):
        row.status, row.responded_at = "answered", _now()
        enqueue_sync(session, entity_type=ENTITY, entity_id=row.id, operation="update")


def serialise(session: Session, owner: Profile, row: ProjectInvite) -> ProjectInviteOut:
    request = session.get(InvestmentRequest, row.request_id)
    return ProjectInviteOut(
        id=row.id,
        request_id=row.request_id,
        request_title=request.title if request else None,
        farmer=card(session, session.get(Profile, row.farmer_profile_id)),
        investor=card(session, session.get(Profile, row.investor_profile_id)),
        message=row.message,
        status=row.status,  # type: ignore[arg-type]
        sent_by_me=row.farmer_profile_id == owner.id,
        created_at=row.created_at,
    )


def invites_for(session: Session, owner: Profile) -> list[ProjectInviteOut]:
    rows = session.scalars(
        select(ProjectInvite)
        .where((ProjectInvite.farmer_profile_id == owner.id) | (ProjectInvite.investor_profile_id == owner.id))
        .order_by(ProjectInvite.created_at.desc())
    )
    return [serialise(session, owner, row) for row in rows]


def on_incoming(session: Session, row: ProjectInvite, before: dict | None, owner: Profile) -> None:
    """A farmer's invite reached the investor's device: tell them."""
    from .notify import notify  # noqa: PLC0415

    if row.investor_profile_id == owner.id and before is None and row.status == "sent":
        farmer = session.get(Profile, row.farmer_profile_id)
        request = session.get(InvestmentRequest, row.request_id)
        notify(
            session, owner.id, "project_invited",
            params={"name": farmer.display_name if farmer else "", "title": request.title if request else ""},
            link="/", entity_type=ENTITY, entity_id=row.id,
        )
