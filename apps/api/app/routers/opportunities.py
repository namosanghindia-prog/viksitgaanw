"""Business and farming options for a plot of land.

This is the step the whole land-intake form exists to reach: once a farmer has
told the app where the land is, how big it is, what the soil is and what water
it has, the app should be able to say what could profitably be done with it and
roughly what that would earn.

Everything answers from the device's own knowledge base, so it works with the
phone in aeroplane mode. Only the export-market figures describe anything
outside India, and those are curated data files rather than live lookups.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import knowledge
from ..db import get_session
from ..models import LandParcel
from ..schemas import (
    ExportMarketListOut,
    ExportMarketOut,
    LinkOut,
    OpportunityListOut,
    TradeFigureOut,
)
from ..services import planning
from ..services.i18n import Translator
from ..services.opportunities import rank

router = APIRouter(tags=["opportunities"])


def _translator(language: str) -> Translator:
    if knowledge.get_language(language) is None:
        raise HTTPException(status_code=422, detail=f"Unknown language: {language}")
    return Translator(language=language)


@router.get("/land-parcels/{parcel_id}/opportunities", response_model=OpportunityListOut)
def parcel_opportunities(
    parcel_id: str,
    language: str = Query(default="hi", alias="lang"),
    include_unsuitable: bool = Query(default=True, alias="includeUnsuitable"),
    kind: str | None = Query(default=None),
    export_only: bool = Query(default=False, alias="exportOnly"),
    session: Session = Depends(get_session),
) -> OpportunityListOut:
    """Rank every option in the knowledge base against this plot."""
    parcel = session.get(LandParcel, parcel_id)
    if parcel is None:
        raise HTTPException(status_code=404, detail="Land parcel not found.")

    translator = _translator(language)
    profile = planning.land_profile(parcel)
    labels = planning.label_resolver(session, translator)

    assessments = rank(profile, labels=labels, include_unsuitable=include_unsuitable)

    if kind:
        assessments = [a for a in assessments if a.opportunity["kind"] == kind]
    if export_only:
        assessments = [
            a
            for a in assessments
            if (a.opportunity.get("export") or {}).get("potential", "none") != "none"
        ]

    items = [planning.to_schema(translator, assessment) for assessment in assessments]

    counts: dict[str, int] = {"recommended": 0, "possible": 0, "unsuitable": 0}
    for item in items:
        counts[item.verdict] += 1

    meta = knowledge.opportunity_meta()
    return OpportunityListOut(
        parcel_id=parcel.id,
        language=language,
        data_as_of=meta.get("dataAsOf", ""),
        basis=translator.label(meta.get("basis")),
        counts=counts,
        items=items,
    )


@router.get("/export-markets", response_model=ExportMarketListOut)
def export_markets(
    language: str = Query(default="hi", alias="lang"),
    commodity: str | None = Query(default=None),
) -> ExportMarketListOut:
    """The foreign-market picture for every commodity the app knows about.

    Deliberately available without a parcel: a farmer browsing what the world
    buys is a legitimate way to arrive at a decision, not only the tail end of
    filling in a form.
    """
    translator = _translator(language)
    data = knowledge.load_export_markets()
    countries = data.get("countries", {})
    certificates = {entry["code"]: entry for entry in data.get("certifications", [])}

    def figure(raw: dict) -> TradeFigureOut:
        return TradeFigureOut(
            low=float(raw.get("low", 0)),
            high=float(raw.get("high", 0)),
            confidence=raw.get("confidence", "estimate"),
            source=raw.get("source"),
        )

    items = []
    for entry in data.get("items", []):
        if commodity and entry["commodity"] != commodity:
            continue
        items.append(
            ExportMarketOut(
                commodity=entry["commodity"],
                label=translator.label(entry.get("label")),
                india_export_usd=figure(entry.get("indiaExportUsd", {})),
                world_trade_usd=figure(entry.get("worldTradeUsd", {})),
                india_share_note=translator.label(entry.get("indiaShareNote")),
                destinations=[
                    LinkOut(label=translator.label(countries.get(code)) or code, url="")
                    for code in entry.get("destinations", [])
                ],
                price_note=translator.label(entry.get("priceNote")),
                barriers=translator.label(entry.get("barriers")),
                certifications=[
                    LinkOut(
                        label=translator.label(certificates[code].get("label")),
                        url=certificates[code].get("url", ""),
                    )
                    for code in entry.get("certifications", [])
                    if code in certificates
                ],
                resources=[
                    LinkOut(label=translator.label(link.get("label")), url=link["url"])
                    for link in entry.get("resources", [])
                    if link.get("url")
                ],
            )
        )

    if commodity and not items:
        raise HTTPException(status_code=404, detail=f"Unknown commodity: {commodity}")

    return ExportMarketListOut(
        language=language,
        data_as_of=data.get("dataAsOf", ""),
        disclaimer=translator.label(data.get("disclaimer")),
        common_resources=[
            LinkOut(label=translator.label(link.get("label")), url=link["url"])
            for link in data.get("commonResources", [])
        ],
        items=items,
    )
