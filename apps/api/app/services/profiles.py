"""The device owner's profile, and how profiles are shown to each other.

One profile per device: this laptop or phone belongs to one farmer, one
investor, one partner organisation or one government office. That person's
profile is the *owner* row; everyone else in the ``profiles`` table is a
counterparty that arrived by sync.

Because there is no login -- the API only listens on loopback, and the device
is the user's own -- "who is asking" is always "the owner". Every permission
check in the marketplace starts from :func:`get_owner`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import reference
from .. import segments as seg
from ..models import EquipmentListing, Profile, State
from ..schemas import ContactOut, ProfileCardOut, ProfileInput, ProfileOut
from . import kyc, media, videos
from .events import EventType, enqueue_sync, record_event
from .farmers import get_or_create_default_farmer
from .hierarchy import location_error, resolve_location

ENTITY = "profile"


class ProfileExistsError(Exception):
    """This device already has an owner."""


class NoProfileError(LookupError):
    """This device has no owner profile yet."""


class SegmentChangeError(ValueError):
    """An existing profile cannot switch segment."""


def get_owner(session: Session) -> Profile | None:
    return session.scalars(
        select(Profile).where(Profile.is_device_owner.is_(True)).limit(1)
    ).first()


def require_owner(session: Session) -> Profile:
    owner = get_owner(session)
    if owner is None:
        raise NoProfileError("Set up your profile first.")
    return owner


def place_error(session: Session, data: ProfileInput) -> str | None:
    """Check every LGD code the profile mentions against the imported data."""
    error = location_error(
        session,
        state_code=data.state_code,
        district_code=data.district_code,
        subdistrict_code=data.subdistrict_code,
        village_code=data.village_code,
    )
    if error:
        return error
    if data.subdistrict_code and not data.district_code:
        return "A block or tehsil cannot be set without its district."
    if data.district_code and not data.state_code:
        return "A district cannot be set without its state."

    listed: list[str] = []
    listed += data.details.get("preferred_states", [])
    listed += data.details.get("operating_states", [])
    for code in listed:
        if session.get(State, code) is None:
            return f"Unknown state code: {code}"
    return None


def _apply(profile: Profile, data: ProfileInput) -> None:
    profile.display_name = data.display_name
    profile.organisation_name = data.organisation_name
    profile.phone = data.phone
    profile.email = data.email
    profile.preferred_language = data.preferred_language
    profile.state_code = data.state_code
    profile.district_code = data.district_code
    profile.subdistrict_code = data.subdistrict_code
    profile.village_code = data.village_code
    profile.country_code = data.country_code
    profile.city = data.city
    profile.about = data.about
    profile.details = data.details


def _link_farmer(session: Session, profile: Profile) -> None:
    """A farmer's land already hangs off the device's farmer row; keep the two
    describing the same person, so a project report and a profile never
    disagree about whose land it is."""
    farmer = get_or_create_default_farmer(session)
    farmer.name = profile.display_name
    farmer.phone = profile.phone
    farmer.preferred_language = profile.preferred_language
    profile.farmer_id = farmer.id


def create_owner(session: Session, data: ProfileInput) -> Profile:
    if get_owner(session) is not None:
        raise ProfileExistsError("This device already has a profile.")

    profile = Profile(segment=data.segment, is_device_owner=True, origin="local")
    _apply(profile, data)
    session.add(profile)
    session.flush()
    if profile.segment == seg.FARMER:
        _link_farmer(session, profile)

    record_event(
        session,
        EventType.PROFILE_CREATED,
        entity_type=ENTITY,
        entity_id=profile.id,
        payload={"segment": profile.segment, "country": profile.country_code},
    )
    enqueue_sync(session, entity_type=ENTITY, entity_id=profile.id, operation="create")
    return profile


def replace_owner(session: Session, data: ProfileInput) -> Profile:
    profile = require_owner(session)
    if data.segment != profile.segment:
        # Switching an investor into a farmer would orphan every interest they
        # sent. Starting again is a deliberate act; see delete_owner.
        raise SegmentChangeError(
            "A profile cannot change type. Delete it and create a new one instead."
        )

    _apply(profile, data)
    if profile.segment == seg.FARMER:
        _link_farmer(session, profile)
    if profile.sync_state == "synced":
        profile.sync_state = "queued"

    record_event(
        session,
        EventType.PROFILE_UPDATED,
        entity_type=ENTITY,
        entity_id=profile.id,
        payload={"segment": profile.segment},
    )
    enqueue_sync(session, entity_type=ENTITY, entity_id=profile.id, operation="update")
    return profile


def delete_owner(session: Session) -> None:
    """Remove the owner's profile, and with it their requests and interests.

    Land parcels and project reports stay: they belong to the farmer row, and
    a farmer who re-creates their profile should find their land still there.
    """
    profile = require_owner(session)
    enqueue_sync(session, entity_type=ENTITY, entity_id=profile.id, operation="delete")
    record_event(
        session,
        EventType.PROFILE_DELETED,
        entity_type=ENTITY,
        entity_id=profile.id,
        payload={"segment": profile.segment},
    )
    media.remove_all(session, "profile", profile.id)
    for listing in session.scalars(
        select(EquipmentListing).where(EquipmentListing.profile_id == profile.id)
    ):
        media.remove_all(session, "equipment", listing.id)
    session.delete(profile)


# --------------------------------------------------------------------------- #
# Presentation
# --------------------------------------------------------------------------- #


def details_out(details: dict[str, Any] | None) -> dict[str, Any]:
    """Stored details are snake_case like the rest of Python; the wire is camelCase."""
    return {to_camel(key): value for key, value in (details or {}).items()}


def place_label(session: Session, profile: Profile) -> str | None:
    """'Varanasi, Uttar Pradesh' in India, 'Rotterdam, Netherlands' abroad."""
    if profile.country_code != "IN":
        country = reference.label_of("countries", profile.country_code) or profile.country_code
        return ", ".join(part for part in (profile.city, country) if part)
    path = resolve_location(
        session,
        district_code=profile.district_code,
        state_code=profile.state_code,
    )
    parts = [unit.name for unit in (path.district, path.state) if unit is not None]
    return ", ".join(parts) or None


def type_code(profile: Profile) -> str | None:
    details = profile.details or {}
    return details.get("investor_type") or details.get("organisation_type") or details.get("level")


def card(session: Session, profile: Profile, *, reveal_contact: bool = False) -> ProfileCardOut:
    from . import connections  # noqa: PLC0415 - connections imports this module
    from .trust import rating_stats  # noqa: PLC0415 - trust imports this module

    rating_avg, rating_count = rating_stats(session, profile.id)
    owner_id = session.scalar(select(Profile.id).where(Profile.is_device_owner.is_(True)))
    connection = connections.state(session, owner_id, profile.id)
    if connection is not None and connection.state == "connected" and connection.via == "request":
        # Two people who both agreed to connect see each other's number.
        reveal_contact = True
    return ProfileCardOut(
        connection=connection,
        rating_avg=rating_avg,
        rating_count=rating_count,
        id=profile.id,
        segment=profile.segment,
        display_name=profile.display_name,
        organisation_name=profile.organisation_name,
        type_code=type_code(profile),
        place=place_label(session, profile),
        country_code=profile.country_code,
        kyc_status=profile.kyc_status,
        origin=profile.origin,
        photo_url=media.first_url(session, "profile", profile.id),
        biodata_video=videos.out(profile.biodata_video),
        contact=(
            ContactOut(phone=profile.phone, email=profile.email) if reveal_contact else None
        ),
    )


def known_profiles(session: Session, owner: Profile, segments: tuple[str, ...]) -> list[Profile]:
    """Other people on this device's copy of the platform, shared online.

    Used when a seller picks a farmer or distributor for their network: only
    someone who has chosen to be visible can be picked.
    """
    stmt = (
        select(Profile)
        .where(Profile.id != owner.id)
        .where(Profile.visibility == "online")
        .where(Profile.segment.in_(segments))
        .order_by(Profile.display_name)
    )
    return list(session.scalars(stmt))


# --------------------------------------------------------------------------- #
# Sharing online
# --------------------------------------------------------------------------- #


def _now() -> datetime:
    return datetime.now(timezone.utc)


def share_owner(session: Session) -> Profile:
    """Make the owner's profile card visible to others on the common timeline.

    The card carries name, organisation, place, type and photo. Phone and
    email stay private until the owner accepts someone.
    """
    profile = require_owner(session)
    if profile.visibility != "online":
        profile.visibility = "online"
        profile.shared_at = _now()
        record_event(
            session,
            EventType.SHARED_ONLINE,
            entity_type=ENTITY,
            entity_id=profile.id,
            payload={"segment": profile.segment},
        )
        enqueue_sync(session, entity_type=ENTITY, entity_id=profile.id, operation="share")
    return profile


def unshare_owner(session: Session) -> Profile:
    """Take the profile offline, and everything shared under it with it.

    A project or machine on the timeline with no visible owner behind it
    would be a listing nobody can trust, so the two go offline together.
    """
    from .sharing import unshare_all_items  # noqa: PLC0415 - avoids an import cycle

    profile = require_owner(session)
    if profile.visibility == "online":
        from .landshare import unshare_everything  # noqa: PLC0415

        unshare_all_items(session, profile)
        unshare_everything(session, profile)
        profile.visibility = "offline"
        record_event(
            session,
            EventType.TAKEN_OFFLINE,
            entity_type=ENTITY,
            entity_id=profile.id,
            payload={"segment": profile.segment},
        )
        enqueue_sync(session, entity_type=ENTITY, entity_id=profile.id, operation="unshare")
    return profile


def serialise_owner(session: Session, profile: Profile) -> ProfileOut:
    return ProfileOut(
        id=profile.id,
        segment=profile.segment,
        display_name=profile.display_name,
        organisation_name=profile.organisation_name,
        phone=profile.phone,
        email=profile.email,
        preferred_language=profile.preferred_language,
        state_code=profile.state_code,
        district_code=profile.district_code,
        subdistrict_code=profile.subdistrict_code,
        village_code=profile.village_code,
        location=resolve_location(
            session,
            village_code=profile.village_code,
            subdistrict_code=profile.subdistrict_code,
            district_code=profile.district_code,
            state_code=profile.state_code,
        ),
        country_code=profile.country_code,
        city=profile.city,
        about=profile.about,
        details=details_out(profile.details),
        kyc_status=profile.kyc_status,
        kyc_method=profile.kyc_method,
        kyc_methods=kyc.methods_for(profile.segment),
        farmer_id=profile.farmer_id,
        photo_url=media.first_url(session, "profile", profile.id),
        biodata_video=videos.out(profile.biodata_video),
        intro_video=videos.out(profile.intro_video),
        visibility=profile.visibility,
        shared_at=profile.shared_at,
        sync_state=profile.sync_state,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )
