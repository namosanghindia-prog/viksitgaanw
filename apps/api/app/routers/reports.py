"""Generating and serving Detailed Project Reports.

A report is a real artefact: a PDF written to the device's disk, indexed by a
row, and recorded as an event -- because generated reports are one of the two
things the business model meters, and retrofitting that count later would mean
inventing history.

Report generation is the one place in the app that can legitimately refuse: if
no font on the device can draw the script the farmer asked for, producing a
page of empty boxes would be worse than saying so and naming the one command
that fixes it.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import knowledge
from ..config import get_settings
from ..db import get_session
from ..models import DatasetMeta, LandParcel, ProjectReport
from ..schemas import DprRequest, ProjectReportOut, ReportLanguageOut
from ..services import financials as financials_service
from ..services import fonts as font_service
from ..services import planning
from ..services.dpr import ReportInput, render
from ..services.events import EventType, enqueue_sync, record_event
from ..services.farmers import get_or_create_default_farmer
from ..services.hierarchy import resolve_location
from ..services.i18n import Translator
from ..services.opportunities import assess

logger = logging.getLogger("viksitgaanw.reports")

router = APIRouter(tags=["reports"])

ENTITY = "project_report"

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


@router.get("/report-languages", response_model=list[ReportLanguageOut])
def report_languages(
    language: str = Query(default="hi", alias="lang"),
) -> list[ReportLanguageOut]:
    """Every language a report can be written in, and whether it truly can.

    ``fontAvailable`` is the honest part: the list offers all twenty-two
    scheduled languages plus English, but a script with no font on this device
    is flagged rather than quietly producing an unreadable PDF.
    """
    ui = Translator(language=language if knowledge.get_language(language) else "en")

    languages: list[ReportLanguageOut] = []
    for entry in knowledge.load_languages()["items"]:
        script = entry.get("script", "Latn")
        available = font_service.is_available(script)
        hint = None
        if not available:
            hint = f"python scripts/fetch_fonts.py --script {script}"
        languages.append(
            ReportLanguageOut(
                code=entry["code"],
                endonym=entry.get("endonym", entry["code"]),
                label=ui.label(entry.get("label")),
                script=script,
                rtl=bool(entry.get("rtl", False)),
                coverage=round(knowledge.catalogue_coverage(entry["code"]), 4),
                font_available=available,
                font_hint=hint,
            )
        )

    # Languages that will render, best translated first, then the rest.
    languages.sort(key=lambda item: (not item.font_available, -item.coverage, item.code))
    return languages


def _next_report_number(session: Session) -> str:
    year = datetime.now(timezone.utc).year
    used = session.scalar(select(func.count()).select_from(ProjectReport)) or 0
    return f"VG-{year}-{used + 1:04d}"


def _file_name(report_number: str, language: str) -> str:
    return _UNSAFE.sub("-", f"{report_number}-{language}.pdf")


def _serialise(report: ProjectReport, translator: Translator) -> ProjectReportOut:
    opportunity = knowledge.get_opportunity(report.opportunity_code) or {}
    entry = knowledge.get_language(report.language) or {}
    return ProjectReportOut(
        id=report.id,
        parcel_id=report.parcel_id,
        opportunity_code=report.opportunity_code,
        opportunity_name=(
            translator.opportunity_name(opportunity) if opportunity else report.opportunity_code
        ),
        language=report.language,
        language_label=entry.get("endonym", report.language),
        translation_coverage=report.translation_coverage,
        report_number=report.report_number,
        promoter_name=report.promoter_name,
        file_name=report.file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
        file_size=report.file_size,
        suitability_score=report.suitability_score,
        total_project_cost=report.total_project_cost,
        term_loan=report.term_loan,
        net_per_year=report.net_per_year,
        created_at=report.created_at,
        download_path=f"/reports/{report.id}/file",
    )


@router.post(
    "/land-parcels/{parcel_id}/reports",
    response_model=ProjectReportOut,
    status_code=status.HTTP_201_CREATED,
)
def create_report(
    parcel_id: str,
    payload: DprRequest,
    session: Session = Depends(get_session),
) -> ProjectReportOut:
    """Build a DPR for one plot and one chosen option, in one language."""
    parcel = session.get(LandParcel, parcel_id)
    if parcel is None:
        raise HTTPException(status_code=404, detail="Land parcel not found.")

    opportunity = knowledge.get_opportunity(payload.opportunity_code)
    if opportunity is None:
        raise HTTPException(
            status_code=422, detail=f"Unknown option: {payload.opportunity_code}"
        )

    entry = knowledge.get_language(payload.language)
    if entry is None:
        raise HTTPException(status_code=422, detail=f"Unknown language: {payload.language}")

    translator = Translator(language=payload.language)
    if not font_service.is_available(translator.script):
        raise HTTPException(
            status_code=503,
            detail=(
                f"No font on this device can print {entry.get('endonym', payload.language)}. "
                f"Run `python scripts/fetch_fonts.py --script {translator.script}` once "
                "while online, then try again."
            ),
        )

    labels = planning.label_resolver(session, translator)
    profile = planning.land_profile(parcel)
    assessment = assess(opportunity, profile, labels=labels)

    terms = financials_service.LoanTerms(
        margin=payload.margin if payload.margin is not None else financials_service.DEFAULT_MARGIN,
        interest_rate=(
            payload.interest_rate
            if payload.interest_rate is not None
            else financials_service.DEFAULT_INTEREST_RATE
        ),
        repayment_years=payload.repayment_years,
    )
    money = financials_service.build(assessment.economics, terms)

    farmer = get_or_create_default_farmer(session)
    promoter_name = (payload.promoter_name or "").strip() or farmer.name

    location = resolve_location(
        session,
        village_code=parcel.village_code,
        subdistrict_code=parcel.subdistrict_code,
        district_code=parcel.district_code,
        state_code=parcel.state_code,
    )
    place_names = {
        level: getattr(location, level).name
        for level in ("state", "district", "subdistrict", "village")
        if getattr(location, level) is not None
    }

    lgd = session.get(DatasetMeta, "lgd")
    report_number = _next_report_number(session)

    try:
        pdf_bytes = render(
            ReportInput(
                parcel=parcel,
                location=location,
                land=profile,
                assessment=assessment,
                financials=money,
                translator=translator,
                promoter_name=promoter_name,
                promoter_phone=payload.promoter_phone or farmer.phone,
                report_number=report_number,
                generated_at=datetime.now(timezone.utc),
                lgd_imported_at=(
                    lgd.imported_at.strftime("%d %B %Y") if lgd and lgd.imported_at else None
                ),
                place_names=place_names,
            )
        )
    except font_service.FontUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:  # pragma: no cover - defensive
        logger.exception("Report generation failed")
        raise HTTPException(
            status_code=500, detail=f"The report could not be produced: {error}"
        ) from error

    directory = get_settings().reports_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _file_name(report_number, payload.language)
    path.write_bytes(pdf_bytes)

    report = ProjectReport(
        parcel_id=parcel.id,
        farmer_id=parcel.farmer_id,
        opportunity_code=opportunity["code"],
        language=payload.language,
        translation_coverage=round(translator.coverage, 4),
        report_number=report_number,
        promoter_name=promoter_name,
        file_path=str(path),
        file_size=len(pdf_bytes),
        suitability_score=assessment.score,
        total_project_cost=money.total_project_cost,
        term_loan=money.term_loan,
        net_per_year=assessment.economics.net_per_year.mid,
    )
    session.add(report)
    session.flush()

    record_event(
        session,
        EventType.REPORT_GENERATED,
        entity_type=ENTITY,
        entity_id=report.id,
        payload={
            "parcel_id": parcel.id,
            "opportunity_code": opportunity["code"],
            "language": payload.language,
            "total_project_cost": money.total_project_cost,
            "suitability_score": assessment.score,
        },
    )
    enqueue_sync(session, entity_type=ENTITY, entity_id=report.id, operation="create")
    session.commit()
    session.refresh(report)

    return _serialise(report, translator)


@router.get("/land-parcels/{parcel_id}/reports", response_model=list[ProjectReportOut])
def list_parcel_reports(
    parcel_id: str,
    language: str = Query(default="hi", alias="lang"),
    session: Session = Depends(get_session),
) -> list[ProjectReportOut]:
    translator = Translator(language=language)
    rows = session.scalars(
        select(ProjectReport)
        .where(ProjectReport.parcel_id == parcel_id)
        .order_by(ProjectReport.created_at.desc())
    )
    return [_serialise(row, translator) for row in rows]


@router.get("/reports", response_model=list[ProjectReportOut])
def list_reports(
    language: str = Query(default="hi", alias="lang"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[ProjectReportOut]:
    translator = Translator(language=language)
    rows = session.scalars(
        select(ProjectReport).order_by(ProjectReport.created_at.desc()).limit(limit)
    )
    return [_serialise(row, translator) for row in rows]


@router.get("/reports/{report_id}/file")
def download_report(report_id: str, session: Session = Depends(get_session)) -> FileResponse:
    report = session.get(ProjectReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")

    from pathlib import Path

    path = Path(report.file_path)
    if not path.is_file():
        raise HTTPException(
            status_code=410,
            detail="The report file is no longer on this device. Generate it again.",
        )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        # Inline so the desktop shell can show it without a round trip to disk.
        content_disposition_type="inline",
    )


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report_id: str, session: Session = Depends(get_session)) -> None:
    report = session.get(ProjectReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")

    from pathlib import Path

    path = Path(report.file_path)
    if path.is_file():
        path.unlink(missing_ok=True)

    enqueue_sync(session, entity_type=ENTITY, entity_id=report.id, operation="delete")
    session.delete(report)
    session.commit()
