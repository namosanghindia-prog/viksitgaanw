"""Request/response models.

The wire format is camelCase to match ``packages/shared/src/types.ts``, while
Python keeps snake_case internally. Requests accept either spelling so a hand
written curl call is not a trap.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from . import reference

AdminLevel = Literal["state", "district", "subdistrict", "village"]
SyncState = Literal["local_only", "queued", "synced", "conflict"]


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #


class AdminUnitOut(ApiModel):
    code: str
    name: str
    name_local: str | None = None
    level: AdminLevel
    parent_code: str | None = None


class LocationPathOut(ApiModel):
    state: AdminUnitOut | None = None
    district: AdminUnitOut | None = None
    subdistrict: AdminUnitOut | None = None
    village: AdminUnitOut | None = None


# --------------------------------------------------------------------------- #
# Land parcels
# --------------------------------------------------------------------------- #


class LandParcelBase(ApiModel):
    label: str = Field(min_length=1, max_length=160)
    state_code: str = Field(min_length=1, max_length=8)
    district_code: str = Field(min_length=1, max_length=8)
    subdistrict_code: str | None = Field(default=None, max_length=8)
    village_code: str | None = Field(default=None, max_length=12)

    survey_number: str | None = Field(default=None, max_length=64)
    ownership_type: str | None = None

    area_value: float = Field(gt=0, le=1_000_000)
    area_unit: str

    soil_type: str | None = None
    water_sources: list[str] = Field(default_factory=list)
    water_type: str | None = None
    water_depth_value: float | None = Field(default=None, gt=0, le=5000)
    water_depth_unit: str | None = None
    irrigation_type: str | None = None
    existing_crops: list[str] = Field(default_factory=list)

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("area_unit")
    @classmethod
    def _known_area_unit(cls, value: str) -> str:
        if not reference.is_valid("area_units", value):
            raise ValueError(f"Unknown area unit: {value}")
        return value

    @field_validator("ownership_type")
    @classmethod
    def _known_ownership(cls, value: str | None) -> str | None:
        if not reference.is_valid("ownership_types", value):
            raise ValueError(f"Unknown ownership type: {value}")
        return value

    @field_validator("soil_type")
    @classmethod
    def _known_soil(cls, value: str | None) -> str | None:
        if not reference.is_valid("soil_types", value):
            raise ValueError(f"Unknown soil type: {value}")
        return value

    @field_validator("irrigation_type")
    @classmethod
    def _known_irrigation(cls, value: str | None) -> str | None:
        if not reference.is_valid("irrigation_types", value):
            raise ValueError(f"Unknown irrigation type: {value}")
        return value

    @field_validator("water_type")
    @classmethod
    def _known_water_type(cls, value: str | None) -> str | None:
        if not reference.is_valid("water_types", value):
            raise ValueError(f"Unknown water type: {value}")
        return value

    @field_validator("water_depth_unit")
    @classmethod
    def _known_depth_unit(cls, value: str | None) -> str | None:
        if not reference.is_valid("depth_units", value):
            raise ValueError(f"Unknown depth unit: {value}")
        return value

    @model_validator(mode="after")
    def _depth_needs_a_unit(self) -> "LandParcelBase":
        """A bare number is meaningless: 40 feet and 40 metres are different
        wells. Accept a depth only when its unit came with it."""
        if self.water_depth_value is not None and not self.water_depth_unit:
            raise ValueError("water_depth_unit is required when a depth is given.")
        return self

    @field_validator("water_sources")
    @classmethod
    def _known_water(cls, values: list[str]) -> list[str]:
        unknown = [v for v in values if not reference.is_valid("water_sources", v)]
        if unknown:
            raise ValueError(f"Unknown water sources: {', '.join(unknown)}")
        return _dedupe(values)

    @field_validator("existing_crops")
    @classmethod
    def _known_crops(cls, values: list[str]) -> list[str]:
        unknown = [v for v in values if not reference.is_valid("crops", v)]
        if unknown:
            raise ValueError(f"Unknown crops: {', '.join(unknown)}")
        return _dedupe(values)


def _dedupe(values: list[str]) -> list[str]:
    """Drop duplicates, preserving the order the farmer picked them in."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


class LandParcelCreate(LandParcelBase):
    farmer_id: str | None = None


class LandParcelUpdate(ApiModel):
    """Every field optional; only what is sent gets changed."""

    label: str | None = Field(default=None, min_length=1, max_length=160)
    survey_number: str | None = Field(default=None, max_length=64)
    ownership_type: str | None = None
    area_value: float | None = Field(default=None, gt=0, le=1_000_000)
    area_unit: str | None = None
    soil_type: str | None = None
    water_sources: list[str] | None = None
    water_type: str | None = None
    water_depth_value: float | None = Field(default=None, gt=0, le=5000)
    water_depth_unit: str | None = None
    irrigation_type: str | None = None
    existing_crops: list[str] | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    notes: str | None = Field(default=None, max_length=4000)


class LandParcelOut(LandParcelBase):
    id: str
    farmer_id: str
    area_hectares: float
    area_acres: float
    water_depth_metres: float | None = None
    location: LocationPathOut
    sync_state: SyncState
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Farmers
# --------------------------------------------------------------------------- #


class FarmerCreate(ApiModel):
    name: str = Field(min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=20)
    preferred_language: str = "hi"


class FarmerOut(ApiModel):
    id: str
    name: str
    phone: str | None
    preferred_language: str
    kyc_status: str
    created_at: datetime


# --------------------------------------------------------------------------- #
# Health / reference
# --------------------------------------------------------------------------- #


class DatabaseHealth(ApiModel):
    path: str
    ready: bool
    lgd_loaded: bool
    counts: dict[str, int]


class HealthOut(ApiModel):
    status: Literal["ok", "degraded"]
    version: str
    database: DatabaseHealth


class ReferenceOut(ApiModel):
    lists: dict[str, Any]


class TileStatusOut(ApiModel):
    """Whether an offline map tile pack is installed on this device."""

    available: bool
    path: str | None = None
    name: str | None = None
    format: str = "png"
    min_zoom: int | None = None
    max_zoom: int | None = None
    #: [west, south, east, north]
    bounds: list[float] | None = None
    attribution: str | None = None
