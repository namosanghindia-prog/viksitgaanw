"""Glue between a stored land parcel and the suggestion engine.

Keeps the routers thin: they hand over a parcel row and a language, and get
back scored options already rendered into the wire schema. The scoring engine
itself stays free of SQLAlchemy and of Pydantic, which is what makes it
straightforward to test.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from .. import knowledge
from ..models import LandParcel, State
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

#: Reference list key used by the engine for state names, which do not live in
#: the reference JSON at all -- they come out of the imported LGD tables.
STATE_LIST_KEY = "states"


def land_profile(parcel: LandParcel) -> LandProfile:
    return LandProfile(
        area_hectares=float(parcel.area_hectares),
        state_code=parcel.state_code,
        district_code=parcel.district_code,
        soil_type=parcel.soil_type,
        water_sources=tuple(parcel.water_sources or []),
        water_type=parcel.water_type,
        water_depth_metres=parcel.water_depth_metres,
        irrigation_type=parcel.irrigation_type,
        existing_crops=tuple(parcel.existing_crops or []),
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
