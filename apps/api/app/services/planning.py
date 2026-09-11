"""Glue between a stored land parcel and the suggestion engine.

Keeps the routers thin: they hand over a parcel row and a language, and get
back scored options already rendered into the wire schema. The scoring engine
itself stays free of SQLAlchemy and of Pydantic, which is what makes it
straightforward to test.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import knowledge, reference
from ..models import District, FarmerGroup, InvestmentRequest, LandParcel, MandiPrice, State, SubDistrict, Village
from ..schemas import (
    EconomicsOut,
    ExportSummaryOut,
    LinkOut,
    MoneyBandOut,
    OpportunityOut,
    SignalOut,
    SizingOut,
)
from .i18n import Translator
from .opportunities import Assessment, LandProfile, Money, Signal
from .profiles import get_owner

#: Reference list key used by the engine for state names, which do not live in
#: the reference JSON at all -- they come out of the imported LGD tables.
STATE_LIST_KEY = "states"


def land_profile(parcel: LandParcel, session: Session | None = None) -> LandProfile:
    """The plot as the engine sees it.

    With a session it also carries what a non-farming project is judged on:
    the family's crops across all its plots, what other farms in the district
    grow, and how many villages are in the tehsil. The suggestions and the
    report both pass one, so the two always agree.

    A soil, water source or crop the farmer typed themselves is left out: the
    engine knows nothing about it, so it counts as not stated rather than as
    a mismatch.
    """
    return LandProfile(
        area_hectares=float(parcel.area_hectares),
        state_code=parcel.state_code,
        district_code=parcel.district_code,
        soil_type=_known(parcel.soil_type),
        water_sources=_known_all(parcel.water_sources),
        water_type=_known(parcel.water_type),
        water_depth_metres=parcel.water_depth_metres,
        irrigation_type=_known(parcel.irrigation_type),
        existing_crops=_known_all(parcel.existing_crops),
        **(_surroundings(session, parcel) if session is not None else {}),
    )


def _known(code: str | None) -> str | None:
    return None if reference.is_custom(code) else code


def _known_all(codes: list[str] | None) -> tuple[str, ...]:
    return tuple(code for code in codes or [] if not reference.is_custom(code))


def _surroundings(session: Session, parcel: LandParcel) -> dict[str, Any]:
    household: set[str] = set()
    if parcel.farmer_id:
        for crops in session.scalars(select(LandParcel.existing_crops).where(LandParcel.farmer_id == parcel.farmer_id)):
            household.update(_known_all(crops))

    # Other farms nearby: open projects and farmer groups in the district this
    # device can see. Sample data and the owner's own records do not count.
    owner = get_owner(session)
    mine = owner.id if owner else ""
    nearby: list[frozenset[str]] = []
    if parcel.district_code:
        by_farmer: dict[str, set[str]] = {}
        for request in session.scalars(
            select(InvestmentRequest).where(
                InvestmentRequest.district_code == parcel.district_code,
                InvestmentRequest.status == "open",
                InvestmentRequest.origin != "demo",
                InvestmentRequest.profile_id != mine,
            )
        ):
            crops = ((request.listing or {}).get("land") or {}).get("existingCrops") or []
            by_farmer.setdefault(request.profile_id, set()).update(crops)
        nearby.extend(frozenset(crops) for crops in by_farmer.values() if crops)
        for group in session.scalars(
            select(FarmerGroup).where(
                FarmerGroup.district_code == parcel.district_code,
                FarmerGroup.origin != "demo",
                FarmerGroup.owner_profile_id != mine,
            )
        ):
            if group.crops:
                nearby.append(frozenset(group.crops))

    tehsil = session.get(SubDistrict, parcel.subdistrict_code) if parcel.subdistrict_code else None
    villages = (
        session.scalar(
            select(func.count()).select_from(Village).where(
                Village.subdistrict_code == parcel.subdistrict_code, Village.is_active.is_(True)
            )
        )
        if tehsil
        else None
    )
    district = session.get(District, parcel.district_code) if parcel.district_code else None
    state = session.get(State, parcel.state_code)
    return {
        "household_crops": tuple(sorted(household)),
        "nearby_farms": tuple(nearby),
        "subdistrict_name": tehsil.name if tehsil else None,
        # An empty directory says nothing about the catchment; leave it unknown.
        "catchment_villages": villages or None,
        "district_name": district.name if district else None,
        "mandi_crops": _mandi_crops(session, district, state),
    }


def _mandi_crops(session: Session, district: District | None, state: State | None) -> tuple[str, ...]:
    """Crops the district's own mandis have traded, as crop codes.

    Agmarknet names districts in plain English, as the LGD does, so the two
    are matched by name within the state. Nothing is fetched here: this only
    reads prices already imported on the device.
    """
    if district is None or state is None:
        return ()
    commodities = [
        name
        for name in session.scalars(
            select(func.lower(MandiPrice.commodity))
            .where(func.lower(MandiPrice.district_name) == district.name.lower())
            .where(func.lower(MandiPrice.state_name) == state.name.lower())
            .distinct()
        )
    ]
    if not commodities:
        return ()
    mapping = knowledge.load_mandi_commodities().get("crops", {})
    return tuple(
        sorted(crop for crop, terms in mapping.items() if any(term in name for name in commodities for term in terms))
    )


def label_resolver(session: Session, translator: Translator) -> Callable[[str, str | None], str]:
    """A ``(list_key, code) -> name`` function the engine can call.

    States are looked up in the database; everything else comes from the
    shared reference lists through the translator, so a reason sentence and a
    dropdown option always agree.
    """
    cache: dict[tuple[str, str | None], str] = {}

    def resolve(list_key: str, code: str | None) -> str:
        if code is None:
            return translator.s("v.notStated")
        key = (list_key, code)
        if key in cache:
            return cache[key]

        if list_key == STATE_LIST_KEY:
            row = session.get(State, code)
            value = row.name if row is not None else code
        else:
            value = translator.reference(list_key, code)

        cache[key] = value
        return value

    return resolve


def _band(money: Money) -> MoneyBandOut:
    return MoneyBandOut(low=money.low, mid=money.mid, high=money.high)


def _signals(translator: Translator, signals: list[Signal]) -> list[SignalOut]:
    return [
        SignalOut(code=signal.key, text=translator.s(signal.key, **signal.variables))
        for signal in signals
    ]


def _links(translator: Translator, entries: list[dict[str, Any]]) -> list[LinkOut]:
    return [
        LinkOut(label=translator.label(entry.get("label")), url=entry.get("url", ""))
        for entry in entries
        if entry.get("url")
    ]


def _export_summary(translator: Translator, opportunity: dict[str, Any]) -> ExportSummaryOut:
    export = opportunity.get("export") or {}
    potential = export.get("potential", "none")
    market = knowledge.get_export_market(export.get("commodity"))

    if potential == "none" or market is None:
        return ExportSummaryOut(potential="none", commodity=export.get("commodity"))

    countries = knowledge.load_export_markets().get("countries", {})
    world = market.get("worldTradeUsd", {})
    india = market.get("indiaExportUsd", {})

    def band(figures: dict[str, Any]) -> MoneyBandOut | None:
        if not figures:
            return None
        low, high = float(figures.get("low", 0)), float(figures.get("high", 0))
        return MoneyBandOut(low=low, mid=(low + high) / 2, high=high)

    return ExportSummaryOut(
        potential=potential,
        commodity=export.get("commodity"),
        label=translator.label(market.get("label")),
        world_trade_usd=band(world),
        india_export_usd=band(india),
        confidence=india.get("confidence"),
        destinations=[
            translator.label(countries.get(code)) or code
            for code in market.get("destinations", [])
        ],
        note=translator.label(market.get("indiaShareNote")),
    )


def to_schema(translator: Translator, assessment: Assessment) -> OpportunityOut:
    opportunity = assessment.opportunity
    economics = assessment.economics
    sizing = assessment.sizing

    kind = knowledge.kind_index().get(opportunity["kind"], {})
    risk_source = next(
        (
            entry.get("label")
            for entry in knowledge.opportunity_meta().get("riskLevels", [])
            if entry["code"] == economics.risk_level
        ),
        None,
    )
    risk_label = translator.reference("risk", economics.risk_level, risk_source)
    scheme_index = knowledge.scheme_index()

    return OpportunityOut(
        code=opportunity["code"],
        kind=opportunity["kind"],
        kind_label=translator.reference("kinds", opportunity["kind"], kind.get("label")),
        sector=knowledge.opportunity_sector(opportunity),
        name=translator.opportunity_name(opportunity),
        summary=translator.summary(opportunity),
        score=assessment.score,
        verdict=assessment.verdict,
        reasons=_signals(translator, assessment.reasons),
        cautions=_signals(translator, assessment.cautions),
        blockers=_signals(translator, assessment.blockers),
        sizing=SizingOut(
            mode=sizing.mode,
            hectares=sizing.hectares,
            units=sizing.units,
            unit_label=translator.label(sizing.unit_label) or None,
            capped=sizing.capped,
        ),
        economics=EconomicsOut(
            capex=_band(economics.capex),
            opex_per_year=_band(economics.opex_per_year),
            revenue_per_year=_band(economics.revenue_per_year),
            net_per_year=_band(economics.net_per_year),
            working_capital=economics.working_capital,
            total_project_cost=economics.total_project_cost,
            gestation_months=economics.gestation_months,
            full_yield_year=economics.full_yield_year,
            project_life_years=economics.project_life_years,
            risk_level=economics.risk_level,
            risk_label=risk_label,
            labour_days_per_year=economics.labour_days_per_year,
            payback_years=economics.payback_years,
        ),
        export=_export_summary(translator, opportunity),
        schemes=_links(
            translator,
            [
                scheme_index[code]
                for code in opportunity.get("schemes", [])
                if code in scheme_index
            ],
        ),
        resources=_links(translator, opportunity.get("resources", [])),
    )
