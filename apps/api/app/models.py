"""SQLAlchemy models for the offline-first local database.

Two families of tables live here:

* The **LGD administrative hierarchy** (states -> districts -> sub-districts ->
  villages), imported from the data.gov.in Local Government Directory dump by
  ``scripts/import_lgd.py``. This is read-only reference data.
* The **user's own records** (farmers, land parcels) plus the plumbing that
  makes them safe to sync later: a durable ``sync_queue`` and an append-only
  ``app_events`` log.
* The **marketplace**: profiles for all six user segments, farmers' investment
  requests, and the interests investors and partners send back.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# LGD administrative hierarchy
# --------------------------------------------------------------------------- #


class State(Base):
    __tablename__ = "states"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_local: Mapped[str | None] = mapped_column(String(160))
    name_norm: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    census_code: Mapped[str | None] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    districts: Mapped[list["District"]] = relationship(back_populates="state")


class District(Base):
    __tablename__ = "districts"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    state_code: Mapped[str] = mapped_column(
        ForeignKey("states.code", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_local: Mapped[str | None] = mapped_column(String(160))
    name_norm: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    census_code: Mapped[str | None] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    state: Mapped[State] = relationship(back_populates="districts")


class SubDistrict(Base):
    """Tehsil / taluk / mandal / community-development block, per the state."""

    __tablename__ = "subdistricts"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    district_code: Mapped[str] = mapped_column(
        ForeignKey("districts.code", ondelete="CASCADE"), nullable=False, index=True
    )
    state_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_local: Mapped[str | None] = mapped_column(String(160))
    name_norm: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    census_code: Mapped[str | None] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Village(Base):
    """~660k rows once the full LGD dump is imported.

    ``state_code`` and ``district_code`` are denormalised so the cascading
    selector and search can filter at any level without a three-way join.
    """

    __tablename__ = "villages"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    subdistrict_code: Mapped[str] = mapped_column(
        ForeignKey("subdistricts.code", ondelete="CASCADE"), nullable=False, index=True
    )
    district_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    state_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_local: Mapped[str | None] = mapped_column(String(160))
    name_norm: Mapped[str] = mapped_column(String(160), nullable=False)
    census_code: Mapped[str | None] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        # Search-as-you-type inside a chosen sub-district, and nationwide.
        Index("ix_villages_subdistrict_name", "subdistrict_code", "name_norm"),
        Index("ix_villages_name_norm", "name_norm"),
    )


class DatasetMeta(Base):
    """Provenance for each imported reference dataset.

    A project report may be reviewed by a bank years later, so we record which
    LGD dump produced the location names printed on it.
    """

    __tablename__ = "dataset_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    notes: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- #
# User data
# --------------------------------------------------------------------------- #


class Farmer(Base):
    __tablename__ = "farmers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    preferred_language: Mapped[str] = mapped_column(String(8), default="hi", nullable=False)
    # Set once Aadhaar eKYC / DigiLocker verification lands. Phase 1 only
    # records the field so nothing has to be migrated later.
    kyc_status: Mapped[str] = mapped_column(String(24), default="unverified", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    parcels: Mapped[list["LandParcel"]] = relationship(
        back_populates="farmer", cascade="all, delete-orphan"
    )


class LandParcel(Base):
    __tablename__ = "land_parcels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    farmer_id: Mapped[str] = mapped_column(
        ForeignKey("farmers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False)

    # Location. Sub-district and village are nullable because parts of the LGD
    # hierarchy are genuinely incomplete, and an urban-fringe plot may have no
    # village code at all. District is the minimum we insist on.
    state_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    district_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    subdistrict_code: Mapped[str | None] = mapped_column(String(8), index=True)
    village_code: Mapped[str | None] = mapped_column(String(12), index=True)

    survey_number: Mapped[str | None] = mapped_column(String(64))
    ownership_type: Mapped[str | None] = mapped_column(String(32))

    # Area is kept as the farmer entered it *and* normalised, so a report can
    # show "2 bigha" while every calculation uses hectares.
    area_value: Mapped[float] = mapped_column(Float, nullable=False)
    area_unit: Mapped[str] = mapped_column(String(24), nullable=False)
    area_hectares: Mapped[float] = mapped_column(Float, nullable=False)

    soil_type: Mapped[str | None] = mapped_column(String(32))
    water_sources: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Water quality (sweet / salty / other) and depth to water. Salinity rules
    # crops in and out, and depth drives the cost of lifting it, so both feed
    # the suggestion engine and the project report.
    water_type: Mapped[str | None] = mapped_column(String(32))
    water_depth_value: Mapped[float | None] = mapped_column(Float)
    water_depth_unit: Mapped[str | None] = mapped_column(String(16))
    water_depth_metres: Mapped[float | None] = mapped_column(Float)

    irrigation_type: Mapped[str | None] = mapped_column(String(32))
    existing_crops: Mapped[list[str]] = mapped_column(JSON, default=list)

    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    #: An introduction video, shown on the plot's card once it is shared. See
    #: services/videos.py for the shape: {"provider": "youtube"|"mux", "id": ...}.
    intro_video: Mapped[dict | None] = mapped_column(JSON)

    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    farmer: Mapped[Farmer] = relationship(back_populates="parcels")


# --------------------------------------------------------------------------- #
# Offline-first plumbing
# --------------------------------------------------------------------------- #


class SyncQueueEntry(Base):
    """Durable outbox.

    Nothing in the app waits on the network: writes land in SQLite first and a
    queue entry is drained whenever connectivity returns.
    """

    __tablename__ = "sync_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation: Mapped[str] = mapped_column(String(12), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class AppEvent(Base):
    """Append-only event log.

    The business model bills on completed deals and generated reports, so those
    have to be countable from day one without a later rearchitecture. Nothing
    reads this yet beyond diagnostics; it just has to be written correctly.
    """

    __tablename__ = "app_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(48))
    entity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True
    )


class ProjectReport(Base):
    """A generated DPR.

    The file itself lives on disk; this row is the index. It exists as a real
    table rather than a directory listing for two reasons: the monetisation
    plan meters generated reports, so they have to be countable without
    walking a filesystem, and a farmer needs to find the report they made last
    month without knowing what it was called.
    """

    __tablename__ = "project_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    parcel_id: Mapped[str] = mapped_column(
        ForeignKey("land_parcels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    farmer_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    #: Which option from the knowledge base this report is for.
    opportunity_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: The language the PDF was written in, not the farmer's UI language.
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    #: Share of the report's strings that existed in that language, 0 to 1.
    translation_coverage: Mapped[float] = mapped_column(Float, default=1.0)

    #: Human-facing reference printed on the cover, e.g. VG-2026-0007.
    report_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    promoter_name: Mapped[str] = mapped_column(String(160), nullable=False)

    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)

    #: Headline figures, kept here so a list of reports can be rendered without
    #: re-running the whole engine or reopening the PDF.
    suitability_score: Mapped[int] = mapped_column(Integer, default=0)
    total_project_cost: Mapped[float] = mapped_column(Float, default=0.0)
    term_loan: Mapped[float] = mapped_column(Float, default=0.0)
    net_per_year: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --------------------------------------------------------------------------- #
# People and organisations, and the investment marketplace
# --------------------------------------------------------------------------- #


class Profile(Base):
    """Anyone taking part: a farmer, an investor, a partner organisation or a
    government office.

    Exactly one row per device is the **device owner** -- the person whose
    laptop or phone this is. Every other row is a counterparty: the farmer
    behind a request an investor is looking at, or the investor who answered a
    farmer's request. Those arrive through cloud sync (or the demo seed until
    sync exists), and are marked by ``origin``.

    What differs between the six segments lives in ``details``, validated by
    a per-segment schema in ``schemas.py``. Six near-identical tables would
    mean six migrations every time a common field is added.
    """

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    #: farmer | investor_india | investor_international | partner_national |
    #: partner_international | government. Fixed once created.
    segment: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    is_device_owner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: local (made on this device) | synced (from the cloud) | demo (seed data).
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)

    #: The person's own name. For an organisation, the contact person.
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    organisation_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    preferred_language: Mapped[str] = mapped_column(String(8), default="hi", nullable=False)

    # Where they are in India -- or, for a government office, what it covers.
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    district_code: Mapped[str | None] = mapped_column(String(8), index=True)
    subdistrict_code: Mapped[str | None] = mapped_column(String(8))
    village_code: Mapped[str | None] = mapped_column(String(12))
    #: ISO 3166-1 alpha-2. "IN" for every segment except the international ones.
    country_code: Mapped[str] = mapped_column(String(2), default="IN", nullable=False)
    city: Mapped[str | None] = mapped_column(String(120))

    about: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    #: A video of the person telling their own story -- their biodata. Anyone
    #: who can see the profile card can play it.
    biodata_video: Mapped[dict | None] = mapped_column(JSON)
    #: For investors and partners who invest, a video introducing what they
    #: fund: the profile is their listing under "Find investors".
    intro_video: Mapped[dict | None] = mapped_column(JSON)

    # Identity verification. Aadhaar numbers are never stored here: eKYC goes
    # through a UIDAI-authorised KUA, which hands back a reference, and that
    # reference is all this row may keep. See services/kyc.py.
    kyc_status: Mapped[str] = mapped_column(String(24), default="unverified", nullable=False)
    kyc_method: Mapped[str | None] = mapped_column(String(32))
    kyc_reference: Mapped[str | None] = mapped_column(String(128))
    kyc_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: For a farmer on their own device, the farmer row their land hangs off.
    farmer_id: Mapped[str | None] = mapped_column(
        ForeignKey("farmers.id", ondelete="SET NULL"), index=True
    )

    #: offline (only on this device) | online (shared to the common timeline).
    #: Everything starts offline; the owner decides when to share.
    visibility: Mapped[str] = mapped_column(String(16), default="offline", nullable=False)
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (
        # One owner per device, enforced by SQLite rather than by hoping every
        # code path remembers to check.
        Index(
            "ux_profiles_device_owner",
            "is_device_owner",
            unique=True,
            sqlite_where=text("is_device_owner = 1"),
        ),
    )


class InvestmentRequest(Base):
    """A farmer asking for investment or a partner, for one plot.

    ``listing`` is the public face of the request: a snapshot of the land and
    the plan taken when it was published. It is what an investor on another
    device sees, and that device has neither the parcel nor the report -- only
    the synced request. It deliberately leaves out the phone number, survey
    number and exact pin; those are shared only after the farmer accepts.
    """

    __tablename__ = "investment_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Set when a group (FPO, cooperative) asks on behalf of its members.
    group_id: Mapped[str | None] = mapped_column(
        ForeignKey("farmer_groups.id", ondelete="SET NULL"), index=True
    )
    # Local links, present only on the farmer's own device.
    parcel_id: Mapped[str | None] = mapped_column(
        ForeignKey("land_parcels.id", ondelete="SET NULL"), index=True
    )
    report_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_reports.id", ondelete="SET NULL")
    )
    opportunity_code: Mapped[str | None] = mapped_column(String(64))
    #: Denormalised from the snapshot so browsing can filter without JSON.
    opportunity_kind: Mapped[str | None] = mapped_column(String(32), index=True)
    state_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    district_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    subdistrict_code: Mapped[str | None] = mapped_column(String(8))

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    #: Rupees.
    amount_sought: Mapped[float] = mapped_column(Float, nullable=False)
    own_contribution: Mapped[float | None] = mapped_column(Float)

    #: ["investment"], ["partnership"] or both.
    seeking: Mapped[list[str]] = mapped_column(JSON, default=list)
    modes: Mapped[list[str]] = mapped_column(JSON, default=list)
    partnership_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: Segments allowed to see this request. The farmer chooses; international
    #: visibility and government visibility are both opt-in.
    open_to: Mapped[list[str]] = mapped_column(JSON, default=list)

    listing: Mapped[dict] = mapped_column(JSON, default=dict)
    intro_video: Mapped[dict | None] = mapped_column(JSON)

    #: open | closed | withdrawn
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False, index=True)
    #: offline | online. A request is a private draft on the farmer's device
    #: until they press "Share online".
    visibility: Mapped[str] = mapped_column(
        String(16), default="offline", nullable=False, index=True
    )
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped[Profile] = relationship()
    interests: Mapped[list["InvestmentInterest"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )


class InvestmentInterest(Base):
    """An investor or partner answering a request.

    Accepting one is a *match*, not a deal: no money moves through the app
    until the milestone-based trust layer exists. ``deal.completed`` stays
    reserved for that.
    """

    __tablename__ = "investment_interests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    request_id: Mapped[str] = mapped_column(
        ForeignKey("investment_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: investment | partnership, following the responder's segment.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Rupees, for investment interests.
    amount_offered: Mapped[float | None] = mapped_column(Float)
    mode: Mapped[str | None] = mapped_column(String(32))
    partnership_type: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text)

    #: sent | accepted | declined | withdrawn
    status: Mapped[str] = mapped_column(String(16), default="sent", nullable=False, index=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    request: Mapped[InvestmentRequest] = relationship(back_populates="interests")
    profile: Mapped[Profile] = relationship()

    __table_args__ = (
        # One answer per responder per request; a change of terms edits it.
        UniqueConstraint("request_id", "profile_id", name="uq_interest_request_profile"),
    )


class InsurancePolicy(Base):
    """One insurance cover, attached to exactly one thing it protects.

    * a **land parcel** -- the crop, or a polyhouse standing on it;
    * a **profile** -- a farmer's own accident, life or health cover, or a
      partner's cargo and trade-credit cover;
    * an **investment request** -- the cover the project itself carries, which
      investors see.

    Three nullable foreign keys rather than a generic owner column, so each
    policy cascades away with the thing it covers and SQLite can check the
    link. ``status = planned`` is the farmer's promise to insure before any
    money is released; it is only meaningful on a request.
    """

    __tablename__ = "insurance_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    parcel_id: Mapped[str | None] = mapped_column(
        ForeignKey("land_parcels.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey("investment_requests.id", ondelete="CASCADE"), index=True
    )

    #: A code from insurance-types.json: crop, livestock, structure, ...
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    #: insured | planned
    status: Mapped[str] = mapped_column(String(16), default="insured", nullable=False)
    #: A code from insurance-schemes.json (pmfby, pmsby, ecgc, private, ...).
    scheme: Mapped[str | None] = mapped_column(String(32))
    insurer: Mapped[str | None] = mapped_column(String(160))
    policy_number: Mapped[str | None] = mapped_column(String(80))
    sum_insured: Mapped[float | None] = mapped_column(Float)
    premium: Mapped[float | None] = mapped_column(Float)
    #: ISO 4217. Rupees except for partners trading abroad.
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    #: Crop cover only: kharif | rabi | zaid | annual, and the year it started.
    season: Mapped[str | None] = mapped_column(String(16))
    season_year: Mapped[int | None] = mapped_column(Integer)
    #: What is covered, in the farmer's words: "5 cows, ear tags 1101-1105".
    covered: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)

    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (
        CheckConstraint(
            "(parcel_id IS NOT NULL) + (profile_id IS NOT NULL) + (request_id IS NOT NULL) = 1",
            name="ck_insurance_one_owner",
        ),
    )


# --------------------------------------------------------------------------- #
# Pictures
# --------------------------------------------------------------------------- #


class MediaFile(Base):
    """A picture stored on the device: a profile photo or logo, or a machine.

    The file lives in the media directory; this row says what it belongs to.
    ``entity_type`` + ``entity_id`` rather than a foreign key, because two
    different tables own pictures; the owner's delete removes both.
    """

    __tablename__ = "media_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    #: profile | equipment
    entity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    #: Order among an entity's pictures; a profile has only position 0.
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_name: Mapped[str] = mapped_column(String(80), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_media_entity", "entity_type", "entity_id", "position"),)


# --------------------------------------------------------------------------- #
# Equipment: machines for sale or rent, and the seller's partner network
# --------------------------------------------------------------------------- #


class EquipmentListing(Base):
    """A machine an agriculture organisation sells, rents out, or both."""

    __tablename__ = "equipment_listings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: A code from equipment-types.json.
    equipment_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    year_made: Mapped[int | None] = mapped_column(Integer)
    #: new | like_new | good | fair
    condition: Mapped[str] = mapped_column(String(16), default="new", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    for_sale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Rupees.
    sale_price: Mapped[float | None] = mapped_column(Float)
    for_rent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rent_rate: Mapped[float | None] = mapped_column(Float)
    #: hour | day | acre | season
    rent_unit: Mapped[str | None] = mapped_column(String(16))
    #: How many units the seller can supply or keeps for hire.
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    with_operator: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delivery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Where the machine is. Required: a farmer renting a tractor needs to know
    # whether it is in the next village or the next state.
    state_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    district_code: Mapped[str | None] = mapped_column(String(8), index=True)
    subdistrict_code: Mapped[str | None] = mapped_column(String(8))

    intro_video: Mapped[dict | None] = mapped_column(JSON)
    #: active | paused | sold
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(
        String(16), default="offline", nullable=False, index=True
    )
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    profile: Mapped[Profile] = relationship()
    enquiries: Mapped[list["EquipmentEnquiry"]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )


class EquipmentEnquiry(Base):
    """Someone asking to rent or buy a listed machine.

    Like an investment interest, accepting shares contact details and records
    the match; no money changes hands through the app.
    """

    __tablename__ = "equipment_enquiries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    listing_id: Mapped[str] = mapped_column(
        ForeignKey("equipment_listings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: rent | buy
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    #: For per-acre hire: how much land.
    area_acres: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str | None] = mapped_column(Text)
    #: sent | accepted | declined | withdrawn
    status: Mapped[str] = mapped_column(String(16), default="sent", nullable=False, index=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    listing: Mapped[EquipmentListing] = relationship(back_populates="enquiries")
    profile: Mapped[Profile] = relationship()


class EquipmentPartnership(Base):
    """One link in an equipment seller's network.

    The partner is a **farmer**, a **village**, a **district** or a
    **distributor**. Farmers and distributors are usually people on the
    platform (``partner_profile_id``); a village or district partner is a
    place (LGD codes), optionally with a named contact -- the Gram Panchayat,
    a district dealer -- who may not use the app at all. Either side can
    start it: the seller appoints, or a farmer asks to become a partner.
    """

    __tablename__ = "equipment_partnerships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    seller_profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: farmer | village | district | distributor
    partner_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    partner_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    #: For partners not on the platform.
    contact_name: Mapped[str | None] = mapped_column(String(160))
    contact_phone: Mapped[str | None] = mapped_column(String(20))

    # The area the partnership covers.
    state_code: Mapped[str | None] = mapped_column(String(8))
    district_code: Mapped[str | None] = mapped_column(String(8), index=True)
    subdistrict_code: Mapped[str | None] = mapped_column(String(8))
    village_code: Mapped[str | None] = mapped_column(String(12))

    #: A code from partner-roles.json.
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Equipment types the partnership covers; empty means all of them.
    equipment_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    commission_percent: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str | None] = mapped_column(Text)

    #: seller | partner
    initiated_by: Mapped[str] = mapped_column(String(8), nullable=False)
    #: proposed | active | declined | ended
    status: Mapped[str] = mapped_column(String(16), default="proposed", nullable=False, index=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    seller: Mapped[Profile] = relationship(foreign_keys=[seller_profile_id])
    partner: Mapped[Profile | None] = relationship(foreign_keys=[partner_profile_id])



# --------------------------------------------------------------------------- #
# Notifications and messages
# --------------------------------------------------------------------------- #


class Notification(Base):
    """Something that happened to the device owner and wants their attention.

    Only ever stored for the owner: a notification for someone on another
    device is generated *there*, when their device receives the change by
    sync. ``params`` carries names and figures, never sentences, so the app
    renders it in whichever language is chosen when it is read.
    """

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: interest_received | interest_answered | enquiry_received | ...
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Where in the app it leads, e.g. "/requests".
    link: Mapped[str | None] = mapped_column(String(200))
    entity_type: Mapped[str | None] = mapped_column(String(48))
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )


class Message(Base):
    """One message between two people who already have something in common.

    There is one thread per pair of profiles; ``context_*`` says which
    request, machine or deal a message was about, when it was about one.
    """

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sender_profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    context_type: Mapped[str | None] = mapped_column(String(32))
    context_id: Mapped[str | None] = mapped_column(String(36))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )


# --------------------------------------------------------------------------- #
# Trust: deals, milestones, ratings, disputes
# --------------------------------------------------------------------------- #


class Deal(Base):
    """An accepted investment turned into a plan both sides agreed to.

    The money is released milestone by milestone, *outside* the app: the
    investor records each release here after approving the evidence. Real
    escrow needs a regulated banking partner; until then this is the ledger
    both sides and any mediator can point at.
    """

    __tablename__ = "deals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    interest_id: Mapped[str] = mapped_column(
        ForeignKey("investment_interests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    request_id: Mapped[str] = mapped_column(
        ForeignKey("investment_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    farmer_profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    investor_profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Rupees. The milestones add up to exactly this.
    amount_total: Mapped[float] = mapped_column(Float, nullable=False)
    mode: Mapped[str | None] = mapped_column(String(32))
    terms: Mapped[str | None] = mapped_column(Text)
    #: Who drew up the current plan; the other side agrees to it.
    proposed_by: Mapped[str] = mapped_column(String(36), nullable=False)
    #: drafting | active | disputed | completed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="drafting", nullable=False, index=True)
    agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="deal", cascade="all, delete-orphan", order_by="Milestone.position"
    )


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    deal_id: Mapped[str] = mapped_column(
        ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    #: Rupees released when this milestone is approved.
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    #: planned | submitted | approved | rejected
    status: Mapped[str] = mapped_column(String(16), default="planned", nullable=False)
    evidence_note: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When the investor recorded paying this tranche, outside the app.
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reference: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    deal: Mapped[Deal] = relationship(back_populates="milestones")


class Rating(Base):
    """One side's rating of the other after working together. Public."""

    __tablename__ = "ratings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rater_profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rated_profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: deal | enquiry | partnership -- what they did together.
    context_type: Mapped[str] = mapped_column(String(16), nullable=False)
    context_id: Mapped[str] = mapped_column(String(36), nullable=False)
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("rater_profile_id", "context_type", "context_id", name="uq_rating_once"),
        CheckConstraint("stars BETWEEN 1 AND 5", name="ck_rating_stars"),
    )


class Dispute(Base):
    """A disagreement about a deal or one of its milestones.

    Opening one pauses the deal. It ends when the side that did not open it
    accepts a resolution, or the opener withdraws it. A mediator -- a
    government officer or, later, the platform -- is a phase-3 addition.
    """

    __tablename__ = "disputes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    deal_id: Mapped[str] = mapped_column(
        ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    milestone_id: Mapped[str | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL")
    )
    opened_by_profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    #: A code from dispute-reasons.json.
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    #: open | resolved | withdrawn
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False, index=True)
    resolution: Mapped[str | None] = mapped_column(Text)
    #: Proposed by one side; the dispute closes when the other confirms it.
    resolution_proposed_by: Mapped[str | None] = mapped_column(String(36))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# --------------------------------------------------------------------------- #
# Farm diary
# --------------------------------------------------------------------------- #


class DiaryEntry(Base):
    """One thing done on a plot: sown, sprayed, irrigated, harvested, sold.

    Export buyers ask for exactly this record -- what was sprayed, when, and
    whether the harvest waited out the pre-harvest interval -- and an investor
    can see real progress from it.
    """

    __tablename__ = "diary_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    parcel_id: Mapped[str] = mapped_column(
        ForeignKey("land_parcels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: A code from diary-activities.json.
    activity: Mapped[str] = mapped_column(String(24), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    crop: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(16))
    #: Rupees spent (or, for a sale, received).
    amount: Mapped[float | None] = mapped_column(Float)
    #: Sprays and fertilisers.
    product: Mapped[str | None] = mapped_column(String(160))
    active_ingredient: Mapped[str | None] = mapped_column(String(160))
    dose: Mapped[str | None] = mapped_column(String(80))
    #: Days that must pass between this spray and harvest.
    pre_harvest_days: Mapped[int | None] = mapped_column(Integer)
    #: Harvests get a lot code that follows the produce to the buyer.
    lot_code: Mapped[str | None] = mapped_column(String(40), unique=True)
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# --------------------------------------------------------------------------- #
# Weather, market prices and exchange rates
# --------------------------------------------------------------------------- #


class WeatherCache(Base):
    """The last forecast fetched for a spot, kept so it still shows offline."""

    __tablename__ = "weather_cache"

    #: "lat,lon" rounded to 0.05 degrees (about 5 km).
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MandiPrice(Base):
    """One day's price for one commodity at one market (Agmarknet)."""

    __tablename__ = "mandi_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    state_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    district_name: Mapped[str] = mapped_column(String(80), nullable=False)
    market: Mapped[str] = mapped_column(String(120), nullable=False)
    commodity: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    variety: Mapped[str | None] = mapped_column(String(80))
    grade: Mapped[str | None] = mapped_column(String(40))
    arrival_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: Rupees per quintal, as Agmarknet reports them.
    min_price: Mapped[float | None] = mapped_column(Float)
    max_price: Mapped[float | None] = mapped_column(Float)
    modal_price: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint(
            "market", "commodity", "variety", "grade", "arrival_date", name="uq_mandi_price_day"
        ),
    )


class FxRate(Base):
    """Rupees per one unit of a foreign currency, with where it came from."""

    __tablename__ = "fx_rates"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    inr_per_unit: Mapped[float] = mapped_column(Float, nullable=False)
    #: frankfurter (ECB reference rates) | manual
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# --------------------------------------------------------------------------- #
# Government schemes
# --------------------------------------------------------------------------- #


class SchemeApplication(Base):
    """The owner's progress applying to one government scheme."""

    __tablename__ = "scheme_applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheme_code: Mapped[str] = mapped_column(String(48), nullable=False)
    #: planning | documents_ready | applied | approved | rejected
    status: Mapped[str] = mapped_column(String(20), default="planning", nullable=False)
    #: Document codes the applicant has ready.
    documents_ready: Mapped[list[str]] = mapped_column(JSON, default=list)
    applied_on: Mapped[date | None] = mapped_column(Date)
    reference_number: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (
        UniqueConstraint("profile_id", "scheme_code", name="uq_scheme_application"),
    )


# --------------------------------------------------------------------------- #
# Farmer groups (FPOs, cooperatives, informal groups)
# --------------------------------------------------------------------------- #


class FarmerGroup(Base):
    """Smallholders pooling land to qualify for deals none could get alone."""

    __tablename__ = "farmer_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    #: The profile that runs it: a farmer, or an FPO / cooperative.
    owner_profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: fpo | cooperative | shg | informal
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[str] = mapped_column(String(8), nullable=False)
    district_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    subdistrict_code: Mapped[str | None] = mapped_column(String(8))
    #: Crops the group grows or plans to, together.
    crops: Mapped[list[str]] = mapped_column(JSON, default=list)
    intro_video: Mapped[dict | None] = mapped_column(JSON)
    visibility: Mapped[str] = mapped_column(String(16), default="offline", nullable=False)
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    members: Mapped[list["GroupMember"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupMember(Base):
    """A member and the land they bring. Members may not use the app at all."""

    __tablename__ = "group_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    group_id: Mapped[str] = mapped_column(
        ForeignKey("farmer_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    #: For members not on the platform.
    name: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(20))
    village_code: Mapped[str | None] = mapped_column(String(12))
    land_hectares: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    crops: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: requested (asked to join) | active | left
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    group: Mapped[FarmerGroup] = relationship(back_populates="members")


# --------------------------------------------------------------------------- #
# Cloud sync
# --------------------------------------------------------------------------- #


class SyncSetting(Base):
    """Small key/value store for the sync worker: server, device token, cursor."""

    __tablename__ = "sync_settings"

    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# --------------------------------------------------------------------------- #
# Connections, shared land and updates
# --------------------------------------------------------------------------- #


class Connection(Base):
    """Two people who have agreed to follow each other's farm news.

    One row per pair: whoever asked first is the requester. People who already
    work together (an accepted offer, a rental, a partnership, a deal, the same
    group) count as connected without a row here -- see services/connections.
    """

    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("requester_profile_id", "addressee_profile_id", name="uq_connection_pair"),
        CheckConstraint("requester_profile_id <> addressee_profile_id", name="ck_connection_not_self"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    requester_profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    addressee_profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message: Mapped[str | None] = mapped_column(Text)
    #: requested | accepted | declined | removed
    status: Mapped[str] = mapped_column(String(16), default="requested", nullable=False)
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class LandShare(Base):
    """A plot shown to the owner's connections on the timeline.

    It carries a *snapshot* of the plot -- place names, size, soil, water,
    crops -- never the survey number or the exact pin, and it is refreshed
    whenever the owner edits a shared plot. The id is the plot's own id, so the
    plot's pictures (media entity ``land``) belong to both. On other devices
    there is no plot, only this card.
    """

    __tablename__ = "land_shares"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The plot on this device, for the owner's own shares only.
    parcel_id: Mapped[str | None] = mapped_column(ForeignKey("land_parcels.id", ondelete="SET NULL"))
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    #: offline | online (online = visible to connections)
    visibility: Mapped[str] = mapped_column(String(16), default="offline", nullable=False)
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When the plot's details last changed while shared.
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    profile: Mapped[Profile] = relationship()


class FarmUpdate(Base):
    """A short post -- "sowing done", "first harvest" -- for the owner's connections."""

    __tablename__ = "farm_updates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The shared plot this is about, if any (a LandShare id).
    land_share_id: Mapped[str | None] = mapped_column(String(36), index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: online while it is shown; offline once taken down.
    visibility: Mapped[str] = mapped_column(String(16), default="online", nullable=False)
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class VideoUpload(Base):
    """A video a subscriber is uploading from this device, until it plays.

    Stays on the device: other people only ever see the finished video, set on
    the item itself once Mux has it ready. The file waits in the media folder
    while it uploads, so an upload cut off by a dropped connection carries on
    from where it stopped the next time the device is online.
    """

    __tablename__ = "video_uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    #: What the video is for: a target in services/videos.py, and its row id.
    target: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: queued | uploading | processing | ready | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False, index=True)
    mux_upload_id: Mapped[str | None] = mapped_column(String(64))
    upload_url: Mapped[str | None] = mapped_column(Text)
    playback_id: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ProjectInvite(Base):
    """A farmer asking one investor to look at their project request.

    The other half of "Find investors": the investor already browses requests;
    this lets a farmer who found an investor they like put a request in front
    of them. The investor answers it the usual way, by sending an interest.
    """

    __tablename__ = "project_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    request_id: Mapped[str] = mapped_column(
        ForeignKey("investment_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    farmer_profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    investor_profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message: Mapped[str | None] = mapped_column(Text)
    #: sent | declined | answered (the investor sent an interest)
    status: Mapped[str] = mapped_column(String(16), default="sent", nullable=False)
    origin: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class SubscriptionPayment(Base):
    """A payment the owner started for a subscription: their receipt.

    The sync server is the record of what was paid -- it alone talks to the
    payment provider, and a device cannot mark itself paid. This copy is so the
    owner can see their payments offline, and so each one that goes through is
    an ``app_events`` entry. It never leaves the device.
    """

    __tablename__ = "subscription_payments"

    #: The server's payment id (also the provider's reference id).
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    plan: Mapped[str] = mapped_column(String(32), nullable=False)
    plan_name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    months: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The payment page, to open again while the payment is still open.
    url: Mapped[str | None] = mapped_column(Text)
    #: created | paid | expired | cancelled
    status: Mapped[str] = mapped_column(String(16), default="created", nullable=False, index=True)
    #: The subscription's last day once this payment counted.
    until: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
