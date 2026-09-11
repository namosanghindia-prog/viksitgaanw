"""Request/response models.

The wire format is camelCase to match ``packages/shared/src/types.ts``, while
Python keeps snake_case internally. Requests accept either spelling so a hand
written curl call is not a trap.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from . import knowledge, reference
from . import segments as seg

AdminLevel = Literal["state", "district", "subdistrict", "village"]
SyncState = Literal["local_only", "queued", "synced", "conflict"]
#: offline: only on this device. online: shared to the common timeline.
Visibility = Literal["offline", "online"]


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class VideoOut(ApiModel):
    """A video to play: a YouTube video id, or a Mux playback id.

    Only ever a finished, playable video -- an upload still in progress lives
    in ``video_uploads`` on the uploader's own device.
    """

    provider: Literal["youtube", "mux"]
    id: str


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
    #: offline, or online = shown to the owner's connections on the timeline.
    share_visibility: Visibility = "offline"
    shared_at: datetime | None = None
    photos: list["MediaOut"] = Field(default_factory=list)
    intro_video: VideoOut | None = None


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
# Profiles
# --------------------------------------------------------------------------- #

_PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_GSTIN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_INDIAN_MOBILE = re.compile(r"^(?:\+?91|0)?([6-9][0-9]{9})$")
_INTERNATIONAL_PHONE = re.compile(r"^\+[1-9][0-9]{6,14}$")


def _check_code(key: str, value: str | None, what: str) -> str | None:
    if not reference.is_valid(key, value):
        raise ValueError(f"Unknown {what}: {value}")
    return value


def _check_codes(key: str, values: list[str], what: str) -> list[str]:
    unknown = [v for v in values if not reference.is_valid(key, v)]
    if unknown:
        raise ValueError(f"Unknown {what}: {', '.join(unknown)}")
    return _dedupe(values)


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def normalise_phone(phone: str, country_code: str) -> str:
    """Store phone numbers in one shape, so the same person is never two.

    Indian numbers must be a real 10-digit mobile (farmers are reached on
    mobiles, not landlines) and are kept as +91XXXXXXXXXX. Numbers abroad are
    accepted in international format.
    """
    compact = re.sub(r"[\s\-().]", "", phone)
    if country_code == "IN":
        match = _INDIAN_MOBILE.match(compact)
        if not match:
            raise ValueError("Enter a 10-digit Indian mobile number.")
        return f"+91{match.group(1)}"
    if not _INTERNATIONAL_PHONE.match(compact):
        raise ValueError("Enter the phone number with its country code, like +44 20 7946 0958.")
    return compact


class FarmerDetails(ApiModel):
    years_farming: int | None = Field(default=None, ge=0, le=90)
    needs: list[str] = Field(default_factory=list)
    fpo_member: bool = False
    fpo_name: str | None = Field(default=None, max_length=200)
    #: Holds a Kisan Credit Card -- banks ask, and it changes loan terms.
    has_kcc: bool = False
    #: Receives PM-KISAN -- evidence of a registered land-holding farmer.
    pm_kisan: bool = False

    @field_validator("needs")
    @classmethod
    def _known_needs(cls, values: list[str]) -> list[str]:
        return _check_codes("farmer_needs", values, "need")

    @field_validator("fpo_name", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)


class InvestorDetails(ApiModel):
    """What both investor segments share."""

    investor_type: str
    #: Opportunity kinds from the knowledge base: horticulture, livestock, ...
    sectors: list[str] = Field(default_factory=list)
    modes: list[str] = Field(min_length=1)
    #: Smallest and largest single investment. Rupees for Indian investors,
    #: US dollars for international ones -- the currency they think in.
    ticket_min: float | None = Field(default=None, ge=0)
    ticket_max: float | None = Field(default=None, gt=0)
    preferred_states: list[str] = Field(default_factory=list)
    horizon_years: int | None = Field(default=None, ge=1, le=30)
    risk_appetite: str | None = None

    @field_validator("sectors")
    @classmethod
    def _known_sectors(cls, values: list[str]) -> list[str]:
        unknown = [v for v in values if v not in knowledge.kind_index()]
        if unknown:
            raise ValueError(f"Unknown sectors: {', '.join(unknown)}")
        return _dedupe(values)

    @field_validator("modes")
    @classmethod
    def _known_modes(cls, values: list[str]) -> list[str]:
        return _check_codes("investment_modes", values, "investment modes")

    @field_validator("risk_appetite")
    @classmethod
    def _known_risk(cls, value: str | None) -> str | None:
        return _check_code("risk_appetites", value, "risk appetite")

    @field_validator("preferred_states")
    @classmethod
    def _dedupe_states(cls, values: list[str]) -> list[str]:
        # Existence is checked against the LGD tables by the profile service.
        return _dedupe(values)

    @model_validator(mode="after")
    def _ticket_order(self) -> "InvestorDetails":
        if (
            self.ticket_min is not None
            and self.ticket_max is not None
            and self.ticket_min > self.ticket_max
        ):
            raise ValueError("The smallest investment cannot be larger than the largest.")
        return self


class InvestorIndiaDetails(InvestorDetails):
    #: Permanent Account Number. Needed for any investment return to be taxed
    #: correctly; unlike Aadhaar, a PAN may be stored.
    pan: str | None = None

    @field_validator("pan", mode="before")
    @classmethod
    def _valid_pan(cls, value: Any) -> Any:
        value = _blank_to_none(value)
        if value is None:
            return None
        value = str(value).upper().replace(" ", "")
        if not _PAN.match(value):
            raise ValueError("A PAN has 10 characters, like ABCDE1234F.")
        return value


class InvestorInternationalDetails(InvestorDetails):
    #: Foreign investors cannot acquire Indian farmland, and foreign investment
    #: in farming is allowed only for some activities, through an Indian
    #: company, under the FDI policy. The profile cannot be created until the
    #: investor has confirmed they understand that.
    compliance_acknowledged: bool = False

    @field_validator("compliance_acknowledged")
    @classmethod
    def _must_acknowledge(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "Please confirm you understand the rules on foreign investment in Indian farming."
            )
        return value


class PartnerDetails(ApiModel):
    """What both partner segments share."""

    organisation_type: str
    registration_number: str | None = Field(default=None, max_length=64)
    partnership_types: list[str] = Field(min_length=1)
    crops: list[str] = Field(default_factory=list)
    #: Indian states the organisation works in, or wants to.
    operating_states: list[str] = Field(default_factory=list)

    #: An organisation that partners farmers may fund them as well. One device
    #: holds one profile, so this is a switch rather than a second profile.
    also_invests: bool = False
    investment_modes: list[str] = Field(default_factory=list)
    #: Rupees for national partners, US dollars for international ones.
    ticket_min: float | None = Field(default=None, ge=0)
    ticket_max: float | None = Field(default=None, gt=0)

    @field_validator("partnership_types")
    @classmethod
    def _known_partnerships(cls, values: list[str]) -> list[str]:
        return _check_codes("partnership_types", values, "partnership types")

    @field_validator("investment_modes")
    @classmethod
    def _known_modes(cls, values: list[str]) -> list[str]:
        return _check_codes("investment_modes", values, "investment modes")

    @model_validator(mode="after")
    def _investing(self) -> "PartnerDetails":
        if not self.also_invests:
            self.investment_modes = []
            self.ticket_min = self.ticket_max = None
            return self
        if not self.investment_modes:
            raise ValueError("Choose at least one way the organisation invests.")
        if (
            self.ticket_min is not None
            and self.ticket_max is not None
            and self.ticket_min > self.ticket_max
        ):
            raise ValueError("The smallest investment cannot be larger than the largest.")
        return self

    @field_validator("crops")
    @classmethod
    def _known_crops(cls, values: list[str]) -> list[str]:
        return _check_codes("crops", values, "crops")

    @field_validator("operating_states")
    @classmethod
    def _dedupe_states(cls, values: list[str]) -> list[str]:
        return _dedupe(values)

    @field_validator("registration_number", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)


class PartnerNationalDetails(PartnerDetails):
    gstin: str | None = None
    #: For an FPO, cooperative or SHG: how many farmers it speaks for.
    member_farmers: int | None = Field(default=None, ge=1, le=10_000_000)

    @field_validator("gstin", mode="before")
    @classmethod
    def _valid_gstin(cls, value: Any) -> Any:
        value = _blank_to_none(value)
        if value is None:
            return None
        value = str(value).upper().replace(" ", "")
        if not _GSTIN.match(value):
            raise ValueError("A GSTIN has 15 characters, like 27ABCDE1234F1Z5.")
        return value


class PartnerInternationalDetails(PartnerDetails):
    #: Standards the partner's market demands. Telling a farmer up front that a
    #: buyer needs GLOBALG.A.P. saves a season of wasted effort.
    certifications_required: list[str] = Field(default_factory=list)

    @field_validator("certifications_required")
    @classmethod
    def _known_certifications(cls, values: list[str]) -> list[str]:
        return _check_codes("certifications", values, "certifications")


class GovernmentDetails(ApiModel):
    level: str
    department: str = Field(min_length=1, max_length=200)
    designation: str = Field(min_length=1, max_length=160)
    employee_id: str | None = Field(default=None, max_length=64)

    @field_validator("level")
    @classmethod
    def _known_level(cls, value: str) -> str:
        return _check_code("government_levels", value, "government level")  # type: ignore[return-value]

    @field_validator("department", "designation", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("employee_id", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)


DETAILS_MODELS: dict[str, type[ApiModel]] = {
    "farmer": FarmerDetails,
    "investor_india": InvestorIndiaDetails,
    "investor_international": InvestorInternationalDetails,
    "partner_national": PartnerNationalDetails,
    "partner_international": PartnerInternationalDetails,
    "government": GovernmentDetails,
}


def _format_details_error(error: ValidationError) -> str:
    parts = []
    for entry in error.errors():
        where = ".".join(to_camel(str(part)) for part in entry["loc"])
        message = entry["msg"].removeprefix("Value error, ")
        parts.append(f"details.{where}: {message}" if where else f"details: {message}")
    return "; ".join(parts)


class ProfileInput(ApiModel):
    """Create or replace the device owner's profile.

    Common fields sit at the top level; everything that differs by segment is
    in ``details`` and checked against that segment's schema above. Rules that
    need the database (do these LGD codes exist?) are applied by the service.
    """

    segment: seg.Segment
    display_name: str = Field(min_length=1, max_length=160)
    organisation_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=254)
    preferred_language: str = Field(default="hi", min_length=2, max_length=8)

    state_code: str | None = Field(default=None, max_length=8)
    district_code: str | None = Field(default=None, max_length=8)
    subdistrict_code: str | None = Field(default=None, max_length=8)
    village_code: str | None = Field(default=None, max_length=12)
    country_code: str = Field(default="IN", min_length=2, max_length=2)
    city: str | None = Field(default=None, max_length=120)

    about: str | None = Field(default=None, max_length=2000)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "organisation_name",
        "phone",
        "email",
        "state_code",
        "district_code",
        "subdistrict_code",
        "village_code",
        "city",
        "about",
        mode="before",
    )
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("display_name", mode="before")
    @classmethod
    def _strip_name(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("country_code", mode="before")
    @classmethod
    def _upper_country(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _segment_rules(self) -> "ProfileInput":
        segment = self.segment

        # -- Where they are ------------------------------------------------ #
        if not reference.is_valid("countries", self.country_code):
            raise ValueError(f"Unknown country: {self.country_code}")
        if segment in seg.INTERNATIONAL:
            if self.country_code == "IN":
                raise ValueError(
                    "An international profile is for people and organisations based "
                    "outside India. Choose the Indian profile type instead."
                )
            # A foreign office has no LGD codes; drop any that were sent.
            self.state_code = self.district_code = None
            self.subdistrict_code = self.village_code = None
        elif self.country_code != "IN":
            raise ValueError("This profile type is for people and organisations in India.")

        # -- How to reach them -------------------------------------------- #
        if self.phone:
            self.phone = normalise_phone(self.phone, self.country_code)
        if self.email:
            self.email = self.email.lower()
            if not _EMAIL.match(self.email):
                raise ValueError("Enter a valid email address.")

        # -- Segment-specific details -------------------------------------- #
        try:
            details = DETAILS_MODELS[segment].model_validate(self.details)
        except ValidationError as error:
            raise ValueError(_format_details_error(error)) from None
        self.details = details.model_dump(mode="json")

        if segment == seg.FARMER:
            # A farmer is reached by phone and advised by place, so both are
            # the minimum for a profile an investor would take seriously.
            if not self.phone:
                raise ValueError("A mobile number is required.")
            if not (self.state_code and self.district_code):
                raise ValueError("Choose your state and district.")

        elif segment in seg.INVESTORS:
            investor_type = self.details["investor_type"]
            if not reference.allowed_for_segment("investor_types", investor_type, segment):
                raise ValueError(f"'{investor_type}' is not an investor type for this profile.")
            if investor_type not in seg.PERSONAL_INVESTOR_TYPES and not self.organisation_name:
                raise ValueError("Enter the name of the company, fund or institution.")
            if segment == "investor_india" and not self.phone:
                raise ValueError("A mobile number is required.")
            if segment == "investor_international" and not self.email:
                raise ValueError("An email address is required.")

        elif segment in seg.PARTNERS:
            organisation_type = self.details["organisation_type"]
            if not reference.allowed_for_segment(
                "organisation_types", organisation_type, segment
            ):
                raise ValueError(
                    f"'{organisation_type}' is not an organisation type for this profile."
                )
            if not self.organisation_name:
                raise ValueError("Enter the organisation's name.")
            if segment == "partner_national":
                if not self.state_code:
                    raise ValueError("Choose the state where the organisation is based.")
                if not self.phone:
                    raise ValueError("A mobile number is required.")
            elif not self.email:
                raise ValueError("An email address is required.")

        elif segment == seg.GOVERNMENT:
            if not self.organisation_name:
                raise ValueError("Enter the name of the office, like 'Gram Panchayat Rampur'.")
            if not self.email:
                raise ValueError("An official email address is required.")
            level = reference.get_item("government_levels", self.details["level"]) or {}
            jurisdiction = level.get("jurisdiction", "national")
            needed = {
                "subdistrict": (self.state_code, self.district_code, self.subdistrict_code),
                "district": (self.state_code, self.district_code),
                "state": (self.state_code,),
                "national": (),
            }[jurisdiction]
            if not all(needed):
                raise ValueError(
                    f"Choose the {jurisdiction.replace('subdistrict', 'block or tehsil')} "
                    "this office covers."
                )

        return self


class ProfileOut(ApiModel):
    """The device owner's own profile, with everything in it."""

    id: str
    segment: str
    display_name: str
    organisation_name: str | None = None
    phone: str | None = None
    email: str | None = None
    preferred_language: str
    state_code: str | None = None
    district_code: str | None = None
    subdistrict_code: str | None = None
    village_code: str | None = None
    location: LocationPathOut
    country_code: str
    city: str | None = None
    about: str | None = None
    #: camelCase keys, matching the per-segment schema.
    details: dict[str, Any]
    kyc_status: str
    kyc_method: str | None = None
    #: How this profile could be verified once KYC is switched on.
    kyc_methods: list[str] = Field(default_factory=list)
    farmer_id: str | None = None
    #: Where the photo or logo can be fetched, or None.
    photo_url: str | None = None
    biodata_video: VideoOut | None = None
    intro_video: VideoOut | None = None
    visibility: Visibility = "offline"
    shared_at: datetime | None = None
    sync_state: SyncState
    created_at: datetime
    updated_at: datetime


class ContactOut(ApiModel):
    phone: str | None = None
    email: str | None = None


class ProfileCardOut(ApiModel):
    """How one party appears to another.

    No phone, no email, no survey number: those travel in ``contact`` only once
    the farmer has accepted an interest, so publishing a request never exposes
    a villager to cold calls.
    """

    id: str
    segment: str
    display_name: str
    organisation_name: str | None = None
    #: Investor type or organisation type, whichever applies.
    type_code: str | None = None
    #: "Varanasi, Uttar Pradesh" or "Rotterdam, Netherlands".
    place: str | None = None
    country_code: str
    kyc_status: str
    origin: str
    photo_url: str | None = None
    #: Their own video about themselves, playable wherever the card shows.
    biodata_video: VideoOut | None = None
    #: Average stars other people gave after working with them, and how many.
    rating_avg: float | None = None
    rating_count: int = 0
    contact: ContactOut | None = None
    #: Where the device owner stands with this person; None on the owner's own card.
    connection: "ConnectionStateOut | None" = None


class ConnectionStateOut(ApiModel):
    #: none | requested_by_me | requested_by_them | connected
    state: Literal["none", "requested_by_me", "requested_by_them", "connected"]
    #: How a connection came about: an accepted request, or working together.
    via: Literal["request", "work"] | None = None
    #: The connection request, when there is one.
    id: str | None = None


# --------------------------------------------------------------------------- #
# Insurance
# --------------------------------------------------------------------------- #

InsuranceStatus = Literal["insured", "planned"]
CropSeason = Literal["kharif", "rabi", "zaid", "annual"]


class InsuranceInput(ApiModel):
    """One cover, as the farmer (or partner) describes it.

    ``planned`` is a promise to insure before funds are released. It carries
    no policy details, and is accepted only on an investment request.
    """

    category: str
    status: InsuranceStatus = "insured"
    scheme: str | None = None
    insurer: str | None = Field(default=None, max_length=160)
    policy_number: str | None = Field(default=None, max_length=80)
    sum_insured: float | None = Field(default=None, gt=0, le=100_000_000_000)
    premium: float | None = Field(default=None, ge=0, le=10_000_000_000)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    valid_from: date | None = None
    valid_until: date | None = None
    season: CropSeason | None = None
    season_year: int | None = Field(default=None, ge=2000, le=2100)
    covered: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator(
        "scheme", "insurer", "policy_number", "covered", "notes", "season", mode="before"
    )
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("currency", mode="before")
    @classmethod
    def _upper_currency(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        return _check_code("insurance_types", value, "insurance category")  # type: ignore[return-value]

    @model_validator(mode="after")
    def _consistent(self) -> "InsuranceInput":
        if self.scheme is not None:
            scheme = reference.get_item("insurance_schemes", self.scheme)
            if scheme is None:
                raise ValueError(f"Unknown insurance scheme: {self.scheme}")
            if self.category not in scheme.get("categories", []):
                raise ValueError(f"{self.scheme} does not cover {self.category} insurance.")
        if self.category != "crop":
            # Seasons belong to crop cover; anything else sent is noise.
            self.season = self.season_year = None

        if self.status == "planned":
            return self

        if not (self.scheme or self.insurer):
            raise ValueError("Say which scheme or insurance company the policy is with.")
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValueError("The policy cannot end before it starts.")
        return self


class InsuranceCreate(InsuranceInput):
    """Attach a cover to exactly one thing: a plot, the owner's profile, or a request."""

    parcel_id: str | None = Field(default=None, max_length=36)
    request_id: str | None = Field(default=None, max_length=36)
    on_profile: bool = False

    @model_validator(mode="after")
    def _one_target(self) -> "InsuranceCreate":
        targets = [bool(self.parcel_id), bool(self.request_id), self.on_profile]
        if sum(targets) != 1:
            raise ValueError("Attach the policy to one plot, your profile, or one request.")
        return self


class InsuranceOut(ApiModel):
    id: str
    category: str
    status: InsuranceStatus
    scheme: str | None = None
    insurer: str | None = None
    #: Shown in full to the owner and to a connected counterparty; otherwise
    #: only the last four characters, so a listing never leaks a policy.
    policy_number: str | None = None
    sum_insured: float | None = None
    premium: float | None = None
    currency: str
    valid_from: date | None = None
    valid_until: date | None = None
    season: str | None = None
    season_year: int | None = None
    covered: str | None = None
    notes: str | None = None
    #: Insured, and not past its end date.
    is_current: bool
    expired: bool
    parcel_id: str | None = None
    profile_id: str | None = None
    request_id: str | None = None
    created_at: datetime
    updated_at: datetime


class InsuranceRequirementOut(ApiModel):
    opportunity_code: str | None = None
    kind: str | None = None
    required: list[str]
    recommended: list[str]
    #: Why this option has a rule of its own, in English and Hindi.
    reason: dict[str, str] | None = None


# --------------------------------------------------------------------------- #
# Investment requests and interests
# --------------------------------------------------------------------------- #

Seeking = Literal["investment", "partnership"]
RequestStatus = Literal["open", "closed", "withdrawn"]
InterestStatus = Literal["sent", "accepted", "declined", "withdrawn"]


class InvestmentRequestInput(ApiModel):
    parcel_id: str = Field(min_length=1, max_length=36)
    report_id: str | None = Field(default=None, max_length=36)
    #: Used when there is no report yet; a report's own option wins.
    opportunity_code: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    amount_sought: float = Field(gt=0, le=10_000_000_000)
    own_contribution: float | None = Field(default=None, ge=0, le=10_000_000_000)
    seeking: list[Seeking] = Field(min_length=1)
    modes: list[str] = Field(default_factory=list)
    partnership_types: list[str] = Field(default_factory=list)
    open_to: list[str] = Field(min_length=1)
    #: The project's cover. Which categories are required depends on the
    #: farming option; the service checks that against insurance-rules.json.
    insurance: list[InsuranceInput] = Field(default_factory=list)

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("summary", "report_id", "opportunity_code", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("modes")
    @classmethod
    def _known_modes(cls, values: list[str]) -> list[str]:
        return _check_codes("investment_modes", values, "investment modes")

    @field_validator("partnership_types")
    @classmethod
    def _known_partnerships(cls, values: list[str]) -> list[str]:
        return _check_codes("partnership_types", values, "partnership types")

    @field_validator("open_to")
    @classmethod
    def _known_audience(cls, values: list[str]) -> list[str]:
        unknown = [v for v in values if v not in seg.AUDIENCES]
        if unknown:
            raise ValueError(f"A request cannot be shown to: {', '.join(unknown)}")
        return _dedupe(values)

    @model_validator(mode="after")
    def _consistent(self) -> "InvestmentRequestInput":
        self.seeking = _dedupe(self.seeking)  # type: ignore[assignment]
        if "investment" in self.seeking and not self.modes:
            raise ValueError("Choose at least one way you would accept investment.")
        if "partnership" in self.seeking and not self.partnership_types:
            raise ValueError("Choose at least one kind of partnership you want.")
        wants_investors = any(s in seg.INVESTORS for s in self.open_to)
        wants_partners = any(s in seg.PARTNERS for s in self.open_to)
        if "investment" in self.seeking and not wants_investors:
            raise ValueError("Show the request to at least one kind of investor.")
        if "partnership" in self.seeking and not wants_partners:
            raise ValueError("Show the request to at least one kind of partner.")
        return self


class InvestmentRequestUpdate(ApiModel):
    """The farmer may edit what they said, or close the request."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    amount_sought: float | None = Field(default=None, gt=0, le=10_000_000_000)
    open_to: list[str] | None = None
    status: RequestStatus | None = None

    @field_validator("open_to")
    @classmethod
    def _known_audience(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        if not values:
            raise ValueError("Show the request to at least one group.")
        unknown = [v for v in values if v not in seg.AUDIENCES]
        if unknown:
            raise ValueError(f"A request cannot be shown to: {', '.join(unknown)}")
        return _dedupe(values)


class FitOut(ApiModel):
    """How well a request matches the viewer's own profile, 0 to 100."""

    score: int
    #: Reason codes the UI renders in its own language: state, sector, ticket,
    #: mode, partnership, crop.
    reasons: list[str] = Field(default_factory=list)


class InterestInput(ApiModel):
    #: Only needed by a partner organisation that also invests; otherwise the
    #: responder's segment decides.
    kind: Seeking | None = None
    amount_offered: float | None = Field(default=None, gt=0, le=10_000_000_000)
    mode: str | None = None
    partnership_type: str | None = None
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, value: str | None) -> str | None:
        return _check_code("investment_modes", value, "investment mode")

    @field_validator("partnership_type")
    @classmethod
    def _known_partnership(cls, value: str | None) -> str | None:
        return _check_code("partnership_types", value, "partnership type")

    @field_validator("message", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)


class InterestUpdate(ApiModel):
    """accepted / declined by the farmer, withdrawn by the responder."""

    status: Literal["accepted", "declined", "withdrawn"]


class InterestOut(ApiModel):
    id: str
    request_id: str
    kind: Literal["investment", "partnership"]
    amount_offered: float | None = None
    mode: str | None = None
    partnership_type: str | None = None
    message: str | None = None
    status: InterestStatus
    responder: ProfileCardOut
    origin: str
    created_at: datetime
    responded_at: datetime | None = None


class InvestmentRequestOut(ApiModel):
    id: str
    title: str
    summary: str | None = None
    amount_sought: float
    own_contribution: float | None = None
    seeking: list[str]
    modes: list[str]
    partnership_types: list[str]
    open_to: list[str]
    status: RequestStatus
    #: The public snapshot of land and plan. See models.InvestmentRequest.
    listing: dict[str, Any]
    intro_video: VideoOut | None = None
    opportunity_code: str | None = None
    opportunity_kind: str | None = None
    state_code: str
    district_code: str
    parcel_id: str | None = None
    report_id: str | None = None
    requester: ProfileCardOut
    #: True when the device owner made this request.
    is_mine: bool = False
    #: Every answer, for the farmer's own requests.
    interests: list[InterestOut] = Field(default_factory=list)
    #: The viewer's own answer, when they are an investor or partner.
    my_interest: InterestOut | None = None
    #: Counts by status, visible to the farmer.
    interest_counts: dict[str, int] = Field(default_factory=dict)
    fit: FitOut | None = None
    insurance: list[InsuranceOut] = Field(default_factory=list)
    insurance_required: list[str] = Field(default_factory=list)
    insurance_recommended: list[str] = Field(default_factory=list)
    #: Every required category has a current policy -- not merely a promise.
    fully_insured: bool = False
    visibility: Visibility = "offline"
    shared_at: datetime | None = None
    origin: str
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Pictures
# --------------------------------------------------------------------------- #


class MediaOut(ApiModel):
    id: str
    url: str
    width: int
    height: int
    position: int


# --------------------------------------------------------------------------- #
# Equipment
# --------------------------------------------------------------------------- #

RentUnit = Literal["hour", "day", "acre", "season"]
PartnerKind = Literal["farmer", "village", "district", "distributor"]


class EquipmentInput(ApiModel):
    equipment_type: str
    title: str = Field(min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    year_made: int | None = Field(default=None, ge=1950, le=2100)
    condition: str = "new"
    description: str | None = Field(default=None, max_length=4000)
    for_sale: bool = False
    sale_price: float | None = Field(default=None, gt=0, le=1_000_000_000)
    for_rent: bool = False
    rent_rate: float | None = Field(default=None, gt=0, le=10_000_000)
    rent_unit: RentUnit | None = None
    quantity: int = Field(default=1, ge=1, le=100_000)
    with_operator: bool = False
    delivery: bool = False
    state_code: str = Field(min_length=1, max_length=8)
    district_code: str | None = Field(default=None, max_length=8)
    subdistrict_code: str | None = Field(default=None, max_length=8)
    status: Literal["active", "paused", "sold"] = "active"

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "brand", "model", "description", "district_code", "subdistrict_code", mode="before"
    )
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("equipment_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        return _check_code("equipment_types", value, "equipment type")  # type: ignore[return-value]

    @field_validator("condition")
    @classmethod
    def _known_condition(cls, value: str) -> str:
        return _check_code("equipment_conditions", value, "condition")  # type: ignore[return-value]

    @model_validator(mode="after")
    def _an_offer(self) -> "EquipmentInput":
        if not (self.for_sale or self.for_rent):
            raise ValueError("Say whether the machine is for sale, for rent, or both.")
        if self.for_sale and self.sale_price is None:
            raise ValueError("Enter the sale price.")
        if self.for_rent and (self.rent_rate is None or self.rent_unit is None):
            raise ValueError("Enter the rent and what it is charged per.")
        if not self.for_sale:
            self.sale_price = None
        if not self.for_rent:
            self.rent_rate = self.rent_unit = None
        return self


class EquipmentOut(ApiModel):
    id: str
    equipment_type: str
    title: str
    intro_video: VideoOut | None = None
    brand: str | None = None
    model: str | None = None
    year_made: int | None = None
    condition: str
    description: str | None = None
    for_sale: bool
    sale_price: float | None = None
    for_rent: bool
    rent_rate: float | None = None
    rent_unit: str | None = None
    quantity: int
    with_operator: bool
    delivery: bool
    state_code: str
    district_code: str | None = None
    subdistrict_code: str | None = None
    #: "Bangarapet, Kolar, Karnataka".
    place: str | None = None
    status: str
    visibility: Visibility
    shared_at: datetime | None = None
    photos: list[MediaOut] = Field(default_factory=list)
    seller: ProfileCardOut
    is_mine: bool = False
    #: The viewer's own enquiry, for anyone but the seller.
    my_enquiry: "EnquiryOut | None" = None
    #: All enquiries, for the seller.
    enquiries: list["EnquiryOut"] = Field(default_factory=list)
    enquiry_counts: dict[str, int] = Field(default_factory=dict)
    #: The viewer's partnership with this seller, if any.
    my_partnership: "PartnershipOut | None" = None
    origin: str
    created_at: datetime
    updated_at: datetime


class EnquiryInput(ApiModel):
    kind: Literal["rent", "buy"]
    quantity: int = Field(default=1, ge=1, le=100_000)
    start_date: date | None = None
    end_date: date | None = None
    area_acres: float | None = Field(default=None, gt=0, le=100_000)
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("message", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _dates(self) -> "EnquiryInput":
        if self.kind == "buy":
            self.start_date = self.end_date = None
            self.area_acres = None
        elif self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("The hire cannot end before it starts.")
        return self


class EnquiryOut(ApiModel):
    id: str
    listing_id: str
    kind: str
    quantity: int
    start_date: date | None = None
    end_date: date | None = None
    area_acres: float | None = None
    message: str | None = None
    status: InterestStatus
    enquirer: ProfileCardOut
    origin: str
    created_at: datetime
    responded_at: datetime | None = None


class ResponseUpdate(ApiModel):
    """accepted / declined by the one asked, withdrawn by the one asking."""

    status: Literal["accepted", "declined", "withdrawn"]


class PartnershipInput(ApiModel):
    """A seller adding a partner to their network."""

    partner_kind: PartnerKind
    partner_profile_id: str | None = Field(default=None, max_length=36)
    contact_name: str | None = Field(default=None, max_length=160)
    contact_phone: str | None = Field(default=None, max_length=20)
    state_code: str | None = Field(default=None, max_length=8)
    district_code: str | None = Field(default=None, max_length=8)
    subdistrict_code: str | None = Field(default=None, max_length=8)
    village_code: str | None = Field(default=None, max_length=12)
    role: str
    equipment_types: list[str] = Field(default_factory=list)
    commission_percent: float | None = Field(default=None, ge=0, le=100)
    message: str | None = Field(default=None, max_length=2000)

    @field_validator(
        "partner_profile_id",
        "contact_name",
        "contact_phone",
        "state_code",
        "district_code",
        "subdistrict_code",
        "village_code",
        "message",
        mode="before",
    )
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("role")
    @classmethod
    def _known_role(cls, value: str) -> str:
        return _check_code("partner_roles", value, "partner role")  # type: ignore[return-value]

    @field_validator("equipment_types")
    @classmethod
    def _known_types(cls, values: list[str]) -> list[str]:
        return _check_codes("equipment_types", values, "equipment types")

    @model_validator(mode="after")
    def _who_and_where(self) -> "PartnershipInput":
        if self.contact_phone:
            self.contact_phone = normalise_phone(self.contact_phone, "IN")
        if not self.partner_profile_id and not self.contact_name:
            raise ValueError("Choose a partner on the platform, or write the contact's name.")
        if self.partner_kind == "village" and not self.village_code:
            raise ValueError("Choose the village this partnership covers.")
        if self.partner_kind == "district" and not self.district_code:
            raise ValueError("Choose the district this partnership covers.")
        return self


class PartnershipAsk(ApiModel):
    """A farmer or distributor asking a seller to take them on as a partner."""

    role: str
    equipment_types: list[str] = Field(default_factory=list)
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("message", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("role")
    @classmethod
    def _known_role(cls, value: str) -> str:
        return _check_code("partner_roles", value, "partner role")  # type: ignore[return-value]

    @field_validator("equipment_types")
    @classmethod
    def _known_types(cls, values: list[str]) -> list[str]:
        return _check_codes("equipment_types", values, "equipment types")


class PartnershipUpdate(ApiModel):
    #: active (accept) | declined | ended
    status: Literal["active", "declined", "ended"]


class PartnershipOut(ApiModel):
    id: str
    partner_kind: str
    role: str
    equipment_types: list[str]
    commission_percent: float | None = None
    message: str | None = None
    initiated_by: str
    status: str
    #: "Rampur Bujurg, Pindra, Varanasi, Uttar Pradesh".
    area: str | None = None
    seller: ProfileCardOut
    partner: ProfileCardOut | None = None
    #: Off-platform partner, visible to the seller who recorded them.
    contact_name: str | None = None
    contact_phone: str | None = None
    #: True when the device owner is the seller.
    is_seller: bool
    origin: str
    created_at: datetime
    responded_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Timeline
# --------------------------------------------------------------------------- #


class LandShareOut(ApiModel):
    """A plot as the owner's connections see it."""

    id: str
    owner: ProfileCardOut
    is_mine: bool
    label: str
    place: str | None = None
    intro_video: VideoOut | None = None
    state_code: str | None = None
    area_value: float | None = None
    area_unit: str | None = None
    area_hectares: float | None = None
    soil_type: str | None = None
    water_sources: list[str] = Field(default_factory=list)
    water_type: str | None = None
    irrigation_type: str | None = None
    existing_crops: list[str] = Field(default_factory=list)
    photos: list[MediaOut] = Field(default_factory=list)
    visibility: Visibility
    shared_at: datetime | None = None
    #: Set when the plot's details changed after it was first shared.
    changed_at: datetime | None = None
    updates: int = 0
    origin: str


class FarmUpdateInput(ApiModel):
    body: str = Field(min_length=1, max_length=2000)
    #: A plot of the owner's that is shared with connections.
    land_share_id: str | None = Field(default=None, max_length=36)

    @field_validator("body", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class FarmUpdateOut(ApiModel):
    id: str
    owner: ProfileCardOut
    is_mine: bool
    body: str
    land_share_id: str | None = None
    land_label: str | None = None
    photos: list[MediaOut] = Field(default_factory=list)
    created_at: datetime
    origin: str


class TimelineItemOut(ApiModel):
    """One thing someone shared: a farm project, a machine, a plot or an update."""

    type: Literal["project", "equipment", "land", "update"]
    id: str
    shared_at: datetime | None = None
    project: InvestmentRequestOut | None = None
    equipment: EquipmentOut | None = None
    land: LandShareOut | None = None
    update: FarmUpdateOut | None = None


EquipmentOut.model_rebuild()



# --------------------------------------------------------------------------- #
# Notifications and messages
# --------------------------------------------------------------------------- #

MessageContext = Literal["interest", "enquiry", "partnership", "deal", "dispute", "group"]


class NotificationOut(ApiModel):
    id: str
    kind: str
    #: Names and figures for the app to put into its own sentence.
    params: dict[str, Any] = Field(default_factory=dict)
    link: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    read: bool
    created_at: datetime


class InboxCounts(ApiModel):
    notifications: int
    messages: int


class ReadInput(ApiModel):
    """Mark these notifications read; an empty list means all of them."""

    ids: list[str] = Field(default_factory=list)


class MessageInput(ApiModel):
    body: str = Field(min_length=1, max_length=4000)
    context_type: MessageContext | None = None
    context_id: str | None = Field(default=None, max_length=36)

    @field_validator("body", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class MessageOut(ApiModel):
    id: str
    body: str
    context_type: str | None = None
    context_id: str | None = None
    mine: bool
    read: bool
    created_at: datetime


class ConversationOut(ApiModel):
    other: ProfileCardOut
    last_message: MessageOut | None = None
    unread: int = 0


# --------------------------------------------------------------------------- #
# Trust: deals, milestones, disputes, ratings
# --------------------------------------------------------------------------- #

DealStatus = Literal["drafting", "active", "disputed", "completed", "cancelled"]
MilestoneStatus = Literal["planned", "submitted", "approved", "rejected"]


class MilestoneInput(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    amount: float = Field(gt=0, le=10_000_000_000)
    due_date: date | None = None

    @field_validator("title", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)


class DealPlanInput(ApiModel):
    terms: str | None = Field(default=None, max_length=4000)
    milestones: list[MilestoneInput] = Field(min_length=1, max_length=12)

    @field_validator("terms", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)


class DealInput(DealPlanInput):
    interest_id: str = Field(min_length=1, max_length=36)


class MilestoneSubmit(ApiModel):
    note: str = Field(min_length=1, max_length=4000)


class MilestoneReview(ApiModel):
    approved: bool
    note: str | None = Field(default=None, max_length=2000)
    #: The payment reference of the tranche the investor paid outside the app.
    release_reference: str | None = Field(default=None, max_length=120)

    @field_validator("note", "release_reference", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)


class MilestoneOut(ApiModel):
    id: str
    position: int
    title: str
    description: str | None = None
    amount: float
    due_date: date | None = None
    status: MilestoneStatus
    evidence_note: str | None = None
    submitted_at: datetime | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None
    released_at: datetime | None = None
    release_reference: str | None = None
    photos: list[MediaOut] = Field(default_factory=list)
    overdue: bool = False


class DisputeInput(ApiModel):
    deal_id: str = Field(min_length=1, max_length=36)
    milestone_id: str | None = Field(default=None, max_length=36)
    reason: str
    description: str = Field(min_length=1, max_length=4000)

    @field_validator("reason")
    @classmethod
    def _known_reason(cls, value: str) -> str:
        return _check_code("dispute_reasons", value, "dispute reason")  # type: ignore[return-value]


class DisputeUpdate(ApiModel):
    """propose a resolution, confirm the other side's, or withdraw your own."""

    action: Literal["propose", "confirm", "withdraw"]
    resolution: str | None = Field(default=None, max_length=4000)


class DisputeOut(ApiModel):
    id: str
    deal_id: str
    milestone_id: str | None = None
    opened_by_me: bool
    reason: str
    description: str
    status: Literal["open", "resolved", "withdrawn"]
    resolution: str | None = None
    resolution_proposed_by_me: bool | None = None
    can_confirm: bool = False
    created_at: datetime
    resolved_at: datetime | None = None


class RatingInput(ApiModel):
    context_type: Literal["deal", "enquiry", "partnership"]
    context_id: str = Field(min_length=1, max_length=36)
    stars: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("comment", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)


class RatingOut(ApiModel):
    id: str
    stars: int
    comment: str | None = None
    context_type: str
    rater: ProfileCardOut
    created_at: datetime


class RatingSummaryOut(ApiModel):
    average: float | None = None
    count: int = 0
    ratings: list[RatingOut] = Field(default_factory=list)


class DealOut(ApiModel):
    id: str
    interest_id: str
    request_id: str
    request_title: str
    farmer: ProfileCardOut
    investor: ProfileCardOut
    i_am: Literal["farmer", "investor"]
    amount_total: float
    amount_released: float
    mode: str | None = None
    terms: str | None = None
    status: DealStatus
    proposed_by_me: bool
    can_agree: bool
    milestones: list[MilestoneOut]
    disputes: list[DisputeOut] = Field(default_factory=list)
    can_rate: bool = False
    my_rating: RatingOut | None = None
    created_at: datetime
    agreed_at: datetime | None = None
    completed_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Farm diary
# --------------------------------------------------------------------------- #


class DiaryInput(ApiModel):
    activity: str
    entry_date: date
    crop: str | None = None
    notes: str | None = Field(default=None, max_length=4000)
    quantity: float | None = Field(default=None, ge=0, le=10_000_000)
    unit: str | None = None
    #: Rupees spent, or received for a sale.
    amount: float | None = Field(default=None, ge=0, le=1_000_000_000)
    product: str | None = Field(default=None, max_length=160)
    active_ingredient: str | None = Field(default=None, max_length=160)
    dose: str | None = Field(default=None, max_length=80)
    pre_harvest_days: int | None = Field(default=None, ge=0, le=365)

    @field_validator("notes", "product", "active_ingredient", "dose", "crop", "unit", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("activity")
    @classmethod
    def _known_activity(cls, value: str) -> str:
        return _check_code("diary_activities", value, "activity")  # type: ignore[return-value]

    @field_validator("crop")
    @classmethod
    def _known_crop(cls, value: str | None) -> str | None:
        return _check_code("crops", value, "crop")

    @field_validator("unit")
    @classmethod
    def _known_unit(cls, value: str | None) -> str | None:
        return _check_code("quantity_units", value, "unit")

    @model_validator(mode="after")
    def _entry_rules(self) -> "DiaryInput":
        if self.entry_date > date.today():
            raise ValueError("A diary entry records what was done; the date cannot be in the future.")
        if self.activity != "spray":
            self.pre_harvest_days = None
        if self.activity == "harvest" and not self.crop:
            raise ValueError("Say which crop was harvested.")
        return self


class DiaryOut(DiaryInput):
    id: str
    parcel_id: str
    lot_code: str | None = None
    photos: list[MediaOut] = Field(default_factory=list)
    #: For a spray: the first day its crop may safely be harvested.
    safe_to_harvest_on: date | None = None
    #: For a harvest: sprays whose waiting period had not passed.
    phi_warnings: list[str] = Field(default_factory=list)
    created_at: datetime


class DiarySummaryOut(ApiModel):
    entries: int
    spent: float
    received: float
    by_activity: dict[str, float]
    last_entry: date | None = None
    #: Crops with a spray still inside its waiting period today.
    not_safe_to_harvest: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Weather
# --------------------------------------------------------------------------- #


class WeatherDayOut(ApiModel):
    date: date
    temp_max: float | None = None
    temp_min: float | None = None
    rain_mm: float | None = None
    rain_chance: float | None = None
    wind_max_kmh: float | None = None


class AdvisoryOut(ApiModel):
    #: no_spray_rain | no_spray_wind | heavy_rain | heat | frost | dry_spell
    code: str
    severity: Literal["info", "warn", "alert"]
    day: date
    value: float | None = None


class WeatherOut(ApiModel):
    available: bool
    latitude: float | None = None
    longitude: float | None = None
    #: pin | state -- how precise the forecast position is.
    basis: str | None = None
    days: list[WeatherDayOut] = Field(default_factory=list)
    advisories: list[AdvisoryOut] = Field(default_factory=list)
    fetched_at: datetime | None = None
    #: The forecast is older than the refresh interval (the device is offline).
    stale: bool = False
    source: str | None = None
    attribution: str | None = None
    message: str | None = None


# --------------------------------------------------------------------------- #
# Market prices and exchange rates
# --------------------------------------------------------------------------- #


class PriceRowOut(ApiModel):
    market: str
    district_name: str
    state_name: str
    commodity: str
    variety: str | None = None
    arrival_date: date
    min_price: float | None = None
    max_price: float | None = None
    modal_price: float


class PricePointOut(ApiModel):
    date: date
    modal_average: float
    markets: int


class PriceSummaryOut(ApiModel):
    crop: str
    terms: list[str]
    latest: list[PriceRowOut]
    trend: list[PricePointOut]
    data_as_of: date | None = None
    rows: int
    source: str


class FxRateOut(ApiModel):
    currency: str
    inr_per_unit: float
    source: str
    as_of: date


class FxOut(ApiModel):
    rates: list[FxRateOut]
    refreshed: bool = False
    message: str | None = None


class FxManualInput(ApiModel):
    inr_per_unit: float = Field(gt=0, le=100_000)


# --------------------------------------------------------------------------- #
# Government schemes
# --------------------------------------------------------------------------- #

ApplicationStatus = Literal["planning", "documents_ready", "applied", "approved", "rejected"]


class SchemeApplicationInput(ApiModel):
    status: ApplicationStatus = "planning"
    documents_ready: list[str] = Field(default_factory=list)
    applied_on: date | None = None
    reference_number: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("reference_number", "notes", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)


class SchemeApplicationOut(SchemeApplicationInput):
    id: str
    scheme_code: str
    created_at: datetime
    updated_at: datetime


class SchemeOut(ApiModel):
    code: str
    name: dict[str, str]
    benefit: dict[str, str]
    cannot_check: dict[str, str]
    url: str
    documents: list[str]
    #: likely: everything the app can check is met. check: something it
    #: cannot check decides it. unlikely: something it can check is not met.
    status: Literal["likely", "check", "unlikely"]
    reasons: list[str] = Field(default_factory=list)
    #: Fits what the owner is actually doing (livestock, processing, ...).
    relevant: bool = False
    application: SchemeApplicationOut | None = None


# --------------------------------------------------------------------------- #
# Farmer groups
# --------------------------------------------------------------------------- #


class GroupInput(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str
    description: str | None = Field(default=None, max_length=4000)
    state_code: str = Field(min_length=1, max_length=8)
    district_code: str = Field(min_length=1, max_length=8)
    subdistrict_code: str | None = Field(default=None, max_length=8)
    crops: list[str] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", "subdistrict_code", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        return _check_code("group_kinds", value, "group kind")  # type: ignore[return-value]

    @field_validator("crops")
    @classmethod
    def _known_crops(cls, values: list[str]) -> list[str]:
        return _check_codes("crops", values, "crops")


class GroupMemberInput(ApiModel):
    """A member the group owner adds. Off-platform members are the common case."""

    name: str = Field(min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=20)
    village_code: str | None = Field(default=None, max_length=12)
    land_hectares: float = Field(ge=0, le=100_000)
    crops: list[str] = Field(default_factory=list)

    @field_validator("phone", "village_code", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("crops")
    @classmethod
    def _known_crops(cls, values: list[str]) -> list[str]:
        return _check_codes("crops", values, "crops")

    @model_validator(mode="after")
    def _phone(self) -> "GroupMemberInput":
        if self.phone:
            self.phone = normalise_phone(self.phone, "IN")
        return self


class GroupJoinInput(ApiModel):
    land_hectares: float = Field(ge=0, le=100_000)
    crops: list[str] = Field(default_factory=list)

    @field_validator("crops")
    @classmethod
    def _known_crops(cls, values: list[str]) -> list[str]:
        return _check_codes("crops", values, "crops")


class GroupMemberOut(ApiModel):
    id: str
    profile: ProfileCardOut | None = None
    name: str | None = None
    #: Only the group's owner sees members' phone numbers.
    phone: str | None = None
    village: str | None = None
    land_hectares: float
    crops: list[str]
    status: Literal["requested", "active", "left"]
    created_at: datetime


class GroupOut(ApiModel):
    id: str
    name: str
    kind: str
    description: str | None = None
    intro_video: VideoOut | None = None
    state_code: str
    district_code: str
    subdistrict_code: str | None = None
    place: str | None = None
    crops: list[str]
    visibility: Visibility
    shared_at: datetime | None = None
    owner: ProfileCardOut
    is_mine: bool
    member_count: int
    total_hectares: float
    #: Everyone for the owner; the viewer's own membership for anyone else.
    members: list[GroupMemberOut] = Field(default_factory=list)
    my_membership: GroupMemberOut | None = None
    request_ids: list[str] = Field(default_factory=list)
    origin: str
    created_at: datetime


class GroupRequestInput(ApiModel):
    """An investment request made by a group for its pooled land."""

    opportunity_code: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    amount_sought: float = Field(gt=0, le=10_000_000_000)
    own_contribution: float | None = Field(default=None, ge=0, le=10_000_000_000)
    seeking: list[Seeking] = Field(min_length=1)
    modes: list[str] = Field(default_factory=list)
    partnership_types: list[str] = Field(default_factory=list)
    open_to: list[str] = Field(min_length=1)
    insurance: list[InsuranceInput] = Field(default_factory=list)

    _known_modes = field_validator("modes")(InvestmentRequestInput._known_modes.__func__)  # type: ignore[attr-defined]
    _known_partnerships = field_validator("partnership_types")(
        InvestmentRequestInput._known_partnerships.__func__  # type: ignore[attr-defined]
    )
    _known_audience = field_validator("open_to")(InvestmentRequestInput._known_audience.__func__)  # type: ignore[attr-defined]
    _consistent = model_validator(mode="after")(InvestmentRequestInput._consistent)


# --------------------------------------------------------------------------- #
# Backup, export and erasure
# --------------------------------------------------------------------------- #


class BackupOut(ApiModel):
    name: str
    size_bytes: int
    created_at: datetime
    includes: list[str]
    download_path: str


class RestoreOut(ApiModel):
    staged: bool
    message: str


class EraseInput(ApiModel):
    #: Must be typed exactly, so a mis-tap never erases a farmer's records.
    confirm: str


# --------------------------------------------------------------------------- #
# Insights
# --------------------------------------------------------------------------- #


class CountBucket(ApiModel):
    code: str
    label: str | None = None
    count: int
    amount: float = 0.0


class InsightsOut(ApiModel):
    #: national | state | district | subdistrict -- what the numbers cover.
    scope: str
    place: str | None = None
    farmers: int
    requests_open: int
    amount_sought: float
    requests_by_kind: list[CountBucket]
    requests_by_state: list[CountBucket]
    interests: int
    matches: int
    deals_active: int
    deals_completed: int
    amount_released: float
    machines: int
    machines_by_type: list[CountBucket]
    rentals_agreed: int
    groups: int
    group_members: int
    group_hectares: float
    generated_at: datetime


# --------------------------------------------------------------------------- #
# Cloud sync
# --------------------------------------------------------------------------- #


class SyncConfigInput(ApiModel):
    #: The sync server, e.g. http://127.0.0.1:8900. None switches sync off.
    server_url: str | None = Field(default=None, max_length=300)

    @field_validator("server_url", mode="before")
    @classmethod
    def _url(cls, value: Any) -> Any:
        value = _blank_to_none(value)
        if value is None:
            return None
        value = str(value).rstrip("/")
        if not re.match(r"^https?://[^\s/]+(:\d+)?(/.*)?$", value):
            raise ValueError("Enter the sync server address, like http://127.0.0.1:8900")
        return value


class SyncStatusOut(ApiModel):
    enabled: bool
    server_url: str | None = None
    device_registered: bool = False
    pending: int = 0
    last_push_at: datetime | None = None
    last_pull_at: datetime | None = None
    last_error: str | None = None


class SyncRunOut(ApiModel):
    pushed: int
    pulled: int
    errors: list[str] = Field(default_factory=list)
    status: SyncStatusOut


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


# --------------------------------------------------------------------------- #
# Position and place suggestions
# --------------------------------------------------------------------------- #


class GeoFixOut(ApiModel):
    """Where the device believes it is, and how much to trust that."""

    latitude: float
    longitude: float
    accuracy_metres: float | None = None
    #: device_gps | os_location | network_ip | admin_centroid
    source: str
    label: str | None = None
    attribution: str | None = None


class PlaceSuggestionOut(ApiModel):
    """A coordinate matched back onto the LGD hierarchy, to be confirmed."""

    state_code: str | None = None
    state_name: str | None = None
    district_code: str | None = None
    district_name: str | None = None
    subdistrict_code: str | None = None
    subdistrict_name: str | None = None
    confidence: Literal["high", "medium", "low"] = "low"
    display_name: str | None = None
    source: str | None = None
    attribution: str | None = None


class GeoLocateOut(ApiModel):
    fix: GeoFixOut
    place: PlaceSuggestionOut | None = None
    #: Providers that were tried and came back empty, for the UI to explain.
    tried: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Business and farming options
# --------------------------------------------------------------------------- #


class MoneyBandOut(ApiModel):
    low: float
    mid: float
    high: float


class SignalOut(ApiModel):
    """One reason, already rendered in the requested language."""

    code: str
    text: str


class SizingOut(ApiModel):
    mode: Literal["area", "unit"]
    hectares: float
    units: float | None = None
    unit_label: str | None = None
    capped: bool = False


class EconomicsOut(ApiModel):
    capex: MoneyBandOut
    opex_per_year: MoneyBandOut
    revenue_per_year: MoneyBandOut
    net_per_year: MoneyBandOut
    working_capital: float
    total_project_cost: float
    gestation_months: int
    full_yield_year: int
    project_life_years: int
    risk_level: str
    risk_label: str
    labour_days_per_year: float
    payback_years: float | None = None


class ExportSummaryOut(ApiModel):
    potential: Literal["none", "emerging", "strong"]
    commodity: str | None = None
    label: str | None = None
    world_trade_usd: MoneyBandOut | None = None
    india_export_usd: MoneyBandOut | None = None
    confidence: str | None = None
    destinations: list[str] = Field(default_factory=list)
    note: str | None = None


class LinkOut(ApiModel):
    label: str
    url: str


class OpportunityOut(ApiModel):
    code: str
    kind: str
    kind_label: str
    #: A farming project (crops, livestock, fish) or a non-farming one
    #: (processing, storage, services). See knowledge.opportunity_sector.
    sector: Literal["farm", "nonfarm"]
    name: str
    summary: str
    score: int
    verdict: Literal["recommended", "possible", "unsuitable"]
    reasons: list[SignalOut] = Field(default_factory=list)
    cautions: list[SignalOut] = Field(default_factory=list)
    blockers: list[SignalOut] = Field(default_factory=list)
    sizing: SizingOut
    economics: EconomicsOut
    export: ExportSummaryOut
    schemes: list[LinkOut] = Field(default_factory=list)
    resources: list[LinkOut] = Field(default_factory=list)


class OpportunityListOut(ApiModel):
    parcel_id: str
    language: str
    data_as_of: str
    basis: str
    counts: dict[str, int]
    items: list[OpportunityOut]


# --------------------------------------------------------------------------- #
# Export market intelligence
# --------------------------------------------------------------------------- #


class TradeFigureOut(ApiModel):
    low: float
    high: float
    confidence: str
    source: str | None = None


class ExportMarketOut(ApiModel):
    commodity: str
    label: str
    india_export_usd: TradeFigureOut
    world_trade_usd: TradeFigureOut
    india_share_note: str
    destinations: list[LinkOut] = Field(default_factory=list)
    price_note: str
    barriers: str
    certifications: list[LinkOut] = Field(default_factory=list)
    resources: list[LinkOut] = Field(default_factory=list)


class ExportMarketListOut(ApiModel):
    language: str
    data_as_of: str
    disclaimer: str
    common_resources: list[LinkOut] = Field(default_factory=list)
    items: list[ExportMarketOut]


# --------------------------------------------------------------------------- #
# Project reports (DPR)
# --------------------------------------------------------------------------- #


class ReportLanguageOut(ApiModel):
    """A language the report can be written in, and whether it really can be."""

    code: str
    endonym: str
    label: str
    script: str
    rtl: bool = False
    #: Share of report strings translated into this language, 0 to 1.
    coverage: float = 0.0
    #: False when no font on this device can draw the script.
    font_available: bool = True
    #: Present when the font is missing: what to run to install it.
    font_hint: str | None = None


class DprRequest(ApiModel):
    opportunity_code: str = Field(min_length=1, max_length=64)
    language: str = Field(default="hi", min_length=2, max_length=8)
    promoter_name: str | None = Field(default=None, max_length=160)
    promoter_phone: str | None = Field(default=None, max_length=20)

    #: Loan terms. Left unset the report uses ordinary agricultural term-loan
    #: assumptions, which it states on its face.
    margin: float | None = Field(default=None, ge=0.05, le=0.9)
    interest_rate: float | None = Field(default=None, ge=0.01, le=0.36)
    repayment_years: int | None = Field(default=None, ge=3, le=15)


class ProjectReportOut(ApiModel):
    id: str
    parcel_id: str
    opportunity_code: str
    opportunity_name: str
    language: str
    language_label: str
    translation_coverage: float
    report_number: str
    promoter_name: str
    file_name: str
    file_size: int
    suitability_score: int
    total_project_cost: float
    term_loan: float
    net_per_year: float
    created_at: datetime
    download_path: str


# --------------------------------------------------------------------------- #
# Connections
# --------------------------------------------------------------------------- #


class ConnectionInput(ApiModel):
    profile_id: str = Field(min_length=1, max_length=36)
    message: str | None = Field(default=None, max_length=500)

    @field_validator("message", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)


class ConnectionAnswer(ApiModel):
    status: Literal["accepted", "declined"]


class ConnectionOut(ApiModel):
    id: str | None = None
    other: ProfileCardOut
    #: requested | accepted -- work links show as accepted with via=work.
    status: str
    via: Literal["request", "work"]
    #: For a request: whether the device owner sent it.
    sent_by_me: bool = False
    message: str | None = None
    #: What links two people who work together, e.g. ["deal", "partnership"].
    links: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class ConnectionsOut(ApiModel):
    connected: list[ConnectionOut]
    incoming: list[ConnectionOut]
    outgoing: list[ConnectionOut]
    #: Profiles shared online the owner is not yet connected to.
    suggestions: list[ProfileCardOut]


ProfileCardOut.model_rebuild()
LandParcelOut.model_rebuild()


# --------------------------------------------------------------------------- #
# Videos
# --------------------------------------------------------------------------- #


class VideoLinkInput(ApiModel):
    #: A YouTube link as copied from the app or the browser.
    url: str = Field(min_length=1, max_length=500)


class VideoUploadOut(ApiModel):
    """A subscriber's upload, as its owner follows it."""

    id: str
    target: str
    entity_id: str
    status: Literal["queued", "uploading", "processing", "ready", "failed"]
    size: int
    bytes_sent: int
    #: 0-100, over the upload itself; processing on Mux comes after.
    progress: int
    error: str | None = None
    created_at: datetime


class VideoPlanOut(ApiModel):
    """Whether this device's owner may upload videos directly."""

    subscribed: bool
    plan: str | None = None
    until: date | None = None
    #: Whether the server has video uploads switched on at all.
    uploads_available: bool = False
    #: Why the answer is unknown or no, in plain words -- e.g. sync is off.
    reason: str | None = None


# --------------------------------------------------------------------------- #
# Finding investors and farmers
# --------------------------------------------------------------------------- #


class InvestorListingOut(ApiModel):
    """An investor -- or a partner who invests -- as a farmer finds them."""

    profile: ProfileCardOut
    about: str | None = None
    intro_video: VideoOut | None = None
    sectors: list[str] = Field(default_factory=list)
    modes: list[str] = Field(default_factory=list)
    preferred_states: list[str] = Field(default_factory=list)
    ticket_min: float | None = None
    ticket_max: float | None = None
    #: INR for Indian investors and partners, USD for international ones.
    currency: str = "INR"
    #: How well they suit the farmer's own open requests; None with none open.
    fit: FitOut | None = None
    #: The farmer's requests this investor may see and has not yet been sent.
    sendable_request_ids: list[str] = Field(default_factory=list)
    invited_request_ids: list[str] = Field(default_factory=list)
    #: Projects they have already sent an interest on.
    answered_request_ids: list[str] = Field(default_factory=list)


class FarmerRequestBrief(ApiModel):
    id: str
    title: str
    amount_sought: float
    fit: FitOut | None = None
    invited_me: bool = False


class FarmerListingOut(ApiModel):
    """A farmer as an investor or partner finds them."""

    profile: ProfileCardOut
    about: str | None = None
    years_farming: int | None = None
    needs: list[str] = Field(default_factory=list)
    fpo_member: bool = False
    has_kcc: bool = False
    #: Their open requests the viewer may see, best fit first.
    requests: list[FarmerRequestBrief] = Field(default_factory=list)


class ProjectInviteInput(ApiModel):
    request_id: str
    message: str | None = Field(default=None, max_length=1000)

    @field_validator("message", mode="before")
    @classmethod
    def _blank(cls, value: Any) -> Any:
        return _blank_to_none(value)


class ProjectInviteAnswer(ApiModel):
    status: Literal["declined"]


class ProjectInviteOut(ApiModel):
    id: str
    request_id: str
    request_title: str | None = None
    farmer: ProfileCardOut
    investor: ProfileCardOut
    message: str | None = None
    status: Literal["sent", "declined", "answered"]
    #: Whether the device owner sent it.
    sent_by_me: bool
    created_at: datetime
