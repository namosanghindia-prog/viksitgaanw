"""Ranking farming and agri-business options against one plot of land.

This is a transparent rules engine, not a model. Every point it awards or takes
away is attached to a reason the farmer can read and argue with, because a
suggestion a villager cannot interrogate is worth very little -- and because a
bank reading the resulting project report will ask why this crop and not
another.

The engine answers three questions in order:

1. **Is this possible at all here?** A blocker -- water the crop cannot
   tolerate, land far below the minimum viable size, soil the crop will not
   grow in -- marks the option unsuitable and it drops to the bottom.
2. **How well does it fit?** Weighted signals over soil, region, area, water,
   irrigation and the farmer's own experience produce a score out of 100.
3. **What would it actually earn on *this* plot?** The knowledge base holds
   per-hectare or per-unit ranges; this scales them to the recorded area and
   returns rupee figures for this specific piece of land.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from .. import knowledge

Verdict = Literal["recommended", "possible", "unsuitable"]

#: Everything starts here and moves up or down. Chosen so that an option with
#: no strong signal either way lands in the middle of "possible".
BASE_SCORE = 30

#: Signal weights below are *relative importance*, and a strongly-matched
#: option can accumulate well over a hundred of them. They are scaled by this
#: before being added to the base, so a genuinely excellent fit lands in the
#: mid-eighties and the top of the list stays meaningfully ordered instead of
#: a dozen options all pinned at 100.
SIGNAL_SCALE = 0.42

#: Score at or above which an option is presented as a recommendation.
RECOMMENDED_AT = 60

#: Water is treated as "deep" past this, where lifting cost starts to matter
#: to a crop that drinks heavily.
DEEP_WATER_METRES = 60.0

#: Irrigation entries that mean "there is no irrigation".
_NO_IRRIGATION = frozenset({"rainfed"})
_NO_WATER_SOURCE = frozenset({"rainfed", "other"})

#: Existing crops that indicate experience relevant to an opportunity. Keyed by
#: opportunity code; only where the link is real enough to tell a farmer about.
RELATED_CROPS: dict[str, frozenset[str]] = {
    "pomegranate_orchard": frozenset({"pomegranate", "grapes", "citrus"}),
    "banana_tissue_culture": frozenset({"banana"}),
    "mango_orchard_hd": frozenset({"mango"}),
    "guava_meadow": frozenset({"guava"}),
    "papaya_hybrid": frozenset({"papaya", "banana"}),
    "acid_lime": frozenset({"citrus"}),
    "coconut_garden": frozenset({"coconut", "arecanut"}),
    "black_pepper_intercrop": frozenset({"coconut", "arecanut"}),
    "turmeric_improved": frozenset({"turmeric", "ginger"}),
    "ginger_upland": frozenset({"ginger", "turmeric"}),
    "chilli_hybrid": frozenset({"chilli"}),
    "cumin_arid": frozenset({"cumin", "coriander", "mustard"}),
    "open_field_vegetables": frozenset(
        {"potato", "onion", "tomato", "brinjal", "okra", "cauliflower", "peas", "chilli"}
    ),
    "polyhouse_vegetables": frozenset({"tomato", "chilli", "brinjal"}),
    "baby_corn": frozenset({"maize"}),
    "basmati_export_paddy": frozenset({"rice"}),
    "seed_production_contract": frozenset(
        {"rice", "wheat", "maize", "chana", "moong", "mustard", "soybean"}
    ),
    "fodder_and_silage": frozenset({"berseem", "napier", "maize", "jowar", "bajra"}),
    "oil_expeller_unit": frozenset({"mustard", "groundnut", "sesame", "sunflower"}),
    "mini_dal_mill": frozenset({"tur", "chana", "moong", "urad", "masoor"}),
    "spice_grinding_unit": frozenset({"turmeric", "chilli", "coriander", "cumin"}),
    "makhana_foxnut": frozenset({"rice"}),
}


@dataclass(frozen=True)
class Signal:
    """One reason, ready to be rendered in the farmer's language."""

    key: str
    #: Placeholder values for the catalogue string; already human-readable.
    variables: dict[str, str] = field(default_factory=dict)
    weight: int = 0


@dataclass
class Sizing:
    """How much of this plot the option would occupy, and at what scale."""

    mode: Literal["area", "unit"]
    #: Hectares actually put to work.
    hectares: float
    #: Number of standard units, for unit-priced options such as a polyhouse.
    units: float | None = None
    unit_label: dict[str, str] | None = None
    #: True when the plot is bigger than this option can sensibly use.
    capped: bool = False


@dataclass
class Money:
    low: float
    mid: float
    high: float

    @classmethod
    def scaled(cls, band: dict[str, float], multiplier: float) -> "Money":
        low = float(band["low"]) * multiplier
        high = float(band["high"]) * multiplier
        return cls(low=low, mid=(low + high) / 2, high=high)


@dataclass
class Economics:
    """Rupee figures for this option on this plot, not per hectare."""

    capex: Money
    opex_per_year: Money
    revenue_per_year: Money
    #: Revenue less operating cost, once the option reaches full production.
    net_per_year: Money
    #: One year of operating cost, which is what a bank funds as working capital.
    working_capital: float
    total_project_cost: float
    gestation_months: int
    full_yield_year: int
    project_life_years: int
    risk_level: str
    labour_days_per_year: float
    payback_years: float | None


@dataclass
class Assessment:
    opportunity: dict[str, Any]
    score: int
    verdict: Verdict
    reasons: list[Signal]
    cautions: list[Signal]
    blockers: list[Signal]
    sizing: Sizing
    economics: Economics


@dataclass(frozen=True)
class LandProfile:
    """Everything the engine is allowed to look at. Built from a parcel row."""

    area_hectares: float
    state_code: str
    district_code: str | None = None
    soil_type: str | None = None
    water_sources: tuple[str, ...] = ()
    water_type: str | None = None
    water_depth_metres: float | None = None
    irrigation_type: str | None = None
    existing_crops: tuple[str, ...] = ()

    @property
    def is_irrigated(self) -> bool:
        """True when the plot has some way of watering a crop.

        A plot counts as irrigated if either the stated method is something
        other than rainfed, or a real source of water was recorded. Farmers
        often name the source without picking a method, and rejecting those
        plots would wrongly rule out most of the good options.
        """
        if self.irrigation_type and self.irrigation_type not in _NO_IRRIGATION:
            return True
        return bool(set(self.water_sources) - _NO_WATER_SOURCE)

    @property
    def has_salty_water(self) -> bool:
        return self.water_type == "salty"


# --------------------------------------------------------------------------- #
# Sizing
# --------------------------------------------------------------------------- #


def compute_sizing(opportunity: dict[str, Any], land: LandProfile) -> Sizing:
    sizing = opportunity["sizing"]

    if sizing["mode"] == "area":
        max_ha = float(sizing.get("maxHa") or land.area_hectares)
        hectares = min(land.area_hectares, max_ha)
        return Sizing(mode="area", hectares=hectares, capped=land.area_hectares > max_ha)

    land_per_unit = float(sizing["landHaPerUnit"])
    min_units = int(sizing.get("minUnits", 1))
    max_units = int(sizing.get("maxUnits", min_units))

    if not sizing.get("unitsFromLand"):
        # A dal mill, a cold room or a drone is one business. Owning ten
        # hectares is no reason to plan eight of them, and scaling by land
        # would put an absurd turnover in front of a smallholder.
        return Sizing(
            mode="unit",
            hectares=min_units * land_per_unit,
            units=min_units,
            unit_label=sizing.get("unitLabel"),
            capped=False,
        )

    # A polyhouse or a dairy shed genuinely is limited by available land. Units
    # are bought whole -- two thirds of a polyhouse is not a thing -- so round
    # down, but never below one, because these suit a small holding too.
    fits = math.floor(land.area_hectares / land_per_unit) if land_per_unit else min_units
    units = max(min_units, min(max_units, fits or min_units))

    return Sizing(
        mode="unit",
        hectares=units * land_per_unit,
        units=units,
        unit_label=sizing.get("unitLabel"),
        capped=fits > max_units,
    )


def revenue_factor(year: int, gestation_months: int, full_yield_year: int) -> float:
    """Share of full income earned in ``year`` (1-based).

    Nil until the gestation period is over, then a straight ramp to the year
    the knowledge base says full production is reached. Lives here rather than
    in the financials module because the payback figure quoted in a suggestion
    and the one printed in the project report have to be the same number.
    """
    first_earning_year = gestation_months // 12 + 1
    if year < first_earning_year:
        return 0.0
    if year >= full_yield_year:
        return 1.0
    span = full_yield_year - first_earning_year
    if span <= 0:
        return 1.0
    return (year - first_earning_year + 1) / (span + 1)


def _payback_years(
    total_cost: float,
    net_at_full: float,
    gestation_months: int,
    full_yield_year: int,
    *,
    horizon: int,
) -> float | None:
    """Years until cumulative surplus covers the cost, honouring the gestation.

    Dividing cost by full-yield income would claim an orchard pays for itself
    before it has fruited, which is exactly the kind of number a farmer would
    act on and later regret.
    """
    if net_at_full <= 0:
        return None
    cumulative = 0.0
    for year in range(1, horizon + 1):
        earned = net_at_full * revenue_factor(year, gestation_months, full_yield_year)
        if earned <= 0:
            continue
        if cumulative + earned >= total_cost:
            return (year - 1) + (total_cost - cumulative) / earned
        cumulative += earned
    return None


def compute_economics(opportunity: dict[str, Any], sizing: Sizing) -> Economics:
    figures = opportunity["economics"]
    multiplier = sizing.units if sizing.mode == "unit" else sizing.hectares

    capex = Money.scaled(figures["capex"], multiplier)
    opex = Money.scaled(figures["opexPerYear"], multiplier)
    revenue = Money.scaled(figures["revenuePerYear"], multiplier)

    # Pair worst revenue with worst cost and best with best, so the reported
    # band is the actual range of outcomes rather than a narrower blend.
    net = Money(
        low=revenue.low - opex.high,
        mid=revenue.mid - opex.mid,
        high=revenue.high - opex.low,
    )

    working_capital = opex.mid
    total_project_cost = capex.mid + working_capital

    project_life = int(figures["projectLifeYears"])
    payback = _payback_years(
        total_project_cost,
        net.mid,
        int(figures["gestationMonths"]),
        int(figures["fullYieldYear"]),
        horizon=max(project_life, 15),
    )

    return Economics(
        capex=capex,
        opex_per_year=opex,
        revenue_per_year=revenue,
        net_per_year=net,
        working_capital=working_capital,
        total_project_cost=total_project_cost,
        gestation_months=int(figures["gestationMonths"]),
        full_yield_year=int(figures["fullYieldYear"]),
        project_life_years=int(figures["projectLifeYears"]),
        risk_level=figures["riskLevel"],
        labour_days_per_year=float(figures["labourDaysPerYear"]) * multiplier,
        payback_years=payback,
    )


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def _serves_state(fit: dict[str, Any], state_code: str) -> bool:
    regions = fit.get("regions") or []
    if not regions or "all_india" in regions:
        return True
    by_region = knowledge.region_states()
    for region in regions:
        codes = by_region.get(region)
        if codes and state_code in codes:
            return True
    return state_code in set(fit.get("alsoStates") or [])


def assess(opportunity: dict[str, Any], land: LandProfile, *, labels) -> Assessment:
    """Score one option against one plot.

    ``labels`` is a callable ``(list_key, code) -> str`` used only to put
    readable names into reason variables, so this module never has to know
    which language the caller wants.
    """
    fit = opportunity["fit"]
    sizing = compute_sizing(opportunity, land)
    economics = compute_economics(opportunity, sizing)

    reasons: list[Signal] = []
    cautions: list[Signal] = []
    blockers: list[Signal] = []
    raw = 0

    def add(bucket: list[Signal], key: str, weight: int, **variables: str) -> None:
        nonlocal raw
        bucket.append(Signal(key=key, variables=variables, weight=weight))
        raw += weight

    # -- Region ------------------------------------------------------------ #
    state_name = labels("states", land.state_code)
    if land.state_code in set(fit.get("excludeStates") or []):
        blockers.append(
            Signal("fit.regionExcluded", {"state": state_name}, -40)
        )
    elif not (fit.get("regions") or []) or "all_india" in (fit.get("regions") or []):
        add(reasons, "fit.regionAnywhere", 8)
    elif _serves_state(fit, land.state_code):
        add(reasons, "fit.regionMatch", 18, state=state_name)
    else:
        add(cautions, "fit.regionOutside", -10, state=state_name)

    # -- Soil -------------------------------------------------------------- #
    soil_name = labels("soil_types", land.soil_type)
    if land.soil_type in set(fit.get("avoidSoilTypes") or []):
        blockers.append(Signal("fit.soilAvoid", {"soil": soil_name}, -40))
    elif not land.soil_type or land.soil_type == "unknown":
        add(cautions, "fit.soilUnknown", 0)
    elif not fit.get("soilTypes"):
        add(reasons, "fit.soilAny", 6)
    elif land.soil_type in set(fit["soilTypes"]):
        add(reasons, "fit.soilMatch", 16, soil=soil_name)
    else:
        add(cautions, "fit.soilWeak", -8, soil=soil_name)

    # -- Area -------------------------------------------------------------- #
    area_text = f"{land.area_hectares:.2f}"
    if fit.get("landless"):
        add(reasons, "fit.landless", 10)
    elif opportunity["sizing"]["mode"] == "area":
        min_ha = float(opportunity["sizing"].get("minHa") or 0)
        if land.area_hectares < min_ha:
            blockers.append(
                Signal(
                    "fit.areaTooSmall",
                    {"min": f"{min_ha:.2f}", "area": area_text},
                    -40,
                )
            )
        else:
            add(reasons, "fit.areaFits", 12, area=area_text)
            if sizing.capped:
                add(cautions, "fit.areaCapped", -4, area=f"{sizing.hectares:.2f}")
    elif opportunity["sizing"].get("unitsFromLand"):
        add(reasons, "fit.unitScale", 8, units=f"{sizing.units:g}")
        if sizing.capped:
            add(cautions, "fit.areaCapped", -4, area=f"{sizing.hectares:.2f}")
    else:
        # Scale here is set by capital and by the market, not by the holding,
        # so say that plainly rather than implying more land means more units.
        add(reasons, "fit.unitStandalone", 6, unit=f"{sizing.units:g}")

    # -- Water and irrigation ---------------------------------------------- #
    if fit.get("requiresIrrigation") and not land.is_irrigated:
        blockers.append(Signal("fit.irrigationMissing", {}, -40))
    elif land.is_irrigated:
        preferred = set(fit.get("preferredIrrigation") or [])
        if land.irrigation_type and land.irrigation_type in preferred:
            add(
                reasons,
                "fit.irrigationMatch",
                12,
                irrigation=labels("irrigation_types", land.irrigation_type),
            )
        elif preferred and preferred - _NO_IRRIGATION:
            wanted = sorted(preferred - _NO_IRRIGATION)[0]
            add(
                cautions,
                "fit.irrigationUpgrade",
                -3,
                irrigation=labels("irrigation_types", wanted),
            )
        else:
            add(reasons, "fit.irrigationPresent", 6)
    elif not fit.get("requiresIrrigation"):
        add(reasons, "fit.rainfedOk", 10)

    preferred_sources = set(fit.get("preferredWaterSources") or [])
    if preferred_sources:
        shared = preferred_sources & set(land.water_sources)
        if shared:
            add(
                reasons,
                "fit.waterSourceMatch",
                8,
                source=labels("water_sources", sorted(shared)[0]),
            )
        else:
            add(cautions, "fit.waterSourceMissing", -6)

    water_need = fit.get("waterNeed", "medium")
    if water_need == "low":
        add(reasons, "fit.waterLowNeed", 8)
    elif water_need == "high":
        if (
            land.water_depth_metres is not None
            and land.water_depth_metres > DEEP_WATER_METRES
        ):
            add(
                cautions,
                "fit.waterDeepAndThirsty",
                -10,
                depth=f"{land.water_depth_metres:.0f}",
            )
        else:
            add(cautions, "fit.waterHighNeed", -3)

    tolerance = fit.get("salinityTolerance", "low")
    if land.has_salty_water:
        if tolerance == "low":
            blockers.append(Signal("fit.salinityRisk", {}, -40))
        elif tolerance == "high":
            add(reasons, "fit.salinityTolerant", 12)
        else:
            add(cautions, "fit.salinityCaution", -4)

    if land.water_depth_metres is not None and land.water_depth_metres > 150:
        add(cautions, "fit.waterVeryDeep", -4, depth=f"{land.water_depth_metres:.0f}")

    # -- What the farmer already grows -------------------------------------- #
    required = set(fit.get("requiresExistingCrops") or [])
    if required:
        shared = required & set(land.existing_crops)
        if shared:
            add(
                reasons,
                "fit.requiresExistingMet",
                14,
                crops=labels("crops", sorted(shared)[0]),
            )
        else:
            blockers.append(
                Signal(
                    "fit.requiresExistingMissing",
                    {"crops": labels("crops", sorted(required)[0])},
                    -40,
                )
            )

    related = RELATED_CROPS.get(opportunity["code"], frozenset())
    familiar = related & set(land.existing_crops)
    if familiar:
        add(
            reasons,
            "fit.cropExperience",
            9,
            crops=labels("crops", sorted(familiar)[0]),
        )

    # -- Money and time ----------------------------------------------------- #
    risk = economics.risk_level
    if risk == "low":
        add(reasons, "fit.lowRisk", 8)
    elif risk == "high":
        add(cautions, "fit.highRisk", -7)

    months = economics.gestation_months
    if months <= 6:
        add(reasons, "fit.quickReturn", 8, months=str(months))
    elif months >= 36:
        add(cautions, "fit.longGestation", -6, months=str(months))

    if economics.net_per_year.mid > 0 and economics.payback_years is not None:
        if economics.payback_years <= 3:
            add(reasons, "fit.fastPayback", 6, years=f"{economics.payback_years:.1f}")
        elif economics.payback_years >= 8:
            add(cautions, "fit.slowPayback", -5, years=f"{economics.payback_years:.1f}")

    # A large ticket on a small holding is the most common way one of these
    # plans quietly becomes unaffordable, so say it rather than only scoring it.
    if economics.total_project_cost > 1_500_000 and land.area_hectares < 1.0:
        add(cautions, "fit.highCapex", -6)

    potential = (opportunity.get("export") or {}).get("potential", "none")
    if potential == "strong":
        add(reasons, "fit.exportStrong", 6)
    elif potential == "emerging":
        add(reasons, "fit.exportEmerging", 3)

    score = BASE_SCORE + raw * SIGNAL_SCALE

    if blockers:
        # A blocked option keeps a score only so the list has a stable order
        # inside the "does not suit" group; it must never rival a real answer.
        verdict: Verdict = "unsuitable"
        final = min(score, 25.0)
    elif score >= RECOMMENDED_AT:
        verdict = "recommended"
        final = score
    else:
        verdict = "possible"
        final = score

    return Assessment(
        opportunity=opportunity,
        score=max(0, min(100, int(round(final)))),
        verdict=verdict,
        reasons=sorted(reasons, key=lambda signal: -signal.weight),
        cautions=sorted(cautions, key=lambda signal: signal.weight),
        blockers=blockers,
        sizing=sizing,
        economics=economics,
    )


_VERDICT_ORDER = {"recommended": 0, "possible": 1, "unsuitable": 2}


def rank(land: LandProfile, *, labels, include_unsuitable: bool = True) -> list[Assessment]:
    """Score every option in the knowledge base against one plot."""
    assessments = [
        assess(opportunity, land, labels=labels)
        for opportunity in knowledge.opportunity_items()
    ]
    if not include_unsuitable:
        assessments = [a for a in assessments if a.verdict != "unsuitable"]

    # Sort by verdict first so a merely-high-scoring blocked option can never
    # appear above a genuine recommendation, then by score, then by expected
    # earnings so two equally-good fits are separated by what they actually pay.
    return sorted(
        assessments,
        key=lambda a: (
            _VERDICT_ORDER[a.verdict],
            -a.score,
            -a.economics.net_per_year.mid,
            a.opportunity["code"],
        ),
    )
