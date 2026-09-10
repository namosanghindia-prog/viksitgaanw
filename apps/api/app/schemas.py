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

    @field_validator("partnership_types")
    @classmethod
    def _known_partnerships(cls, values: list[str]) -> list[str]:
        return _check_codes("partnership_types", values, "partnership types")

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
    contact: ContactOut | None = None


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
    origin: str
    created_at: datetime
    updated_at: datetime


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
