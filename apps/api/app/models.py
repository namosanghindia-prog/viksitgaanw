"""SQLAlchemy models for the offline-first local database.

Two families of tables live here:

* The **LGD administrative hierarchy** (states -> districts -> sub-districts ->
  villages), imported from the data.gov.in Local Government Directory dump by
  ``scripts/import_lgd.py``. This is read-only reference data.
* The **user's own records** (farmers, land parcels) plus the plumbing that
  makes them safe to sync later: a durable ``sync_queue`` and an append-only
  ``app_events`` log.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
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
