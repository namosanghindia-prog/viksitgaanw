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

    #: open | closed | withdrawn
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False, index=True)
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
