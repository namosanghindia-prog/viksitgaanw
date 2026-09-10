"""The farm diary, and the traceability record export buyers ask for.

A buyer in Rotterdam or Dubai does not ask "is it good"; they ask "what was
sprayed on it, and when". Maximum residue limits are enforced at the port,
and a rejected container is a season's income. So every spray records its
pre-harvest interval, every harvest gets a lot code, and a harvest that came
too soon after a spray is flagged -- to the farmer, before anyone else sees it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fpdf import FPDF
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import reference
from ..models import DiaryEntry, InsurancePolicy, LandParcel, Profile
from ..schemas import DiaryInput, DiaryOut, DiarySummaryOut, MediaOut
from . import fonts as font_service
from . import media
from .events import EventType, enqueue_sync, record_event
from .hierarchy import resolve_location

ENTITY = "diary_entry"
#: How far back before a harvest a spray can still matter.
LOOKBACK_DAYS = 240


class DiaryError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _fields(entry: DiaryEntry, data: DiaryInput) -> None:
    for field in (
        "activity", "entry_date", "crop", "notes", "quantity", "unit", "amount",
        "product", "active_ingredient", "dose", "pre_harvest_days",
    ):
        setattr(entry, field, getattr(data, field))


def _lot_code(session: Session, parcel: LandParcel, when: date) -> str:
    same_day = session.scalar(
        select(func.count()).select_from(DiaryEntry).where(
            DiaryEntry.lot_code.like(f"LOT-{when:%Y%m%d}-%")
        )
    ) or 0
    return f"LOT-{when:%Y%m%d}-{parcel.id[:4].upper()}-{same_day + 1:02d}"


def safe_on(entry: DiaryEntry) -> date | None:
    if entry.activity != "spray" or entry.pre_harvest_days is None:
        return None
    return entry.entry_date + timedelta(days=entry.pre_harvest_days)


def phi_warnings(session: Session, harvest: DiaryEntry) -> list[str]:
    """Sprays on the same plot and crop whose waiting period ran past the harvest."""
    if harvest.activity != "harvest":
        return []
    sprays = session.scalars(
        select(DiaryEntry).where(
            DiaryEntry.parcel_id == harvest.parcel_id,
            DiaryEntry.activity == "spray",
            DiaryEntry.entry_date <= harvest.entry_date,
            DiaryEntry.entry_date >= harvest.entry_date - timedelta(days=LOOKBACK_DAYS),
        )
    )
    warnings = []
    for spray in sprays:
        if spray.crop and harvest.crop and spray.crop != harvest.crop:
            continue
        clear = safe_on(spray)
        if clear and clear > harvest.entry_date:
            name = spray.product or spray.active_ingredient or "spray"
            warnings.append(f"{name} on {spray.entry_date.isoformat()} (safe from {clear.isoformat()})")
    return warnings


def serialise(session: Session, entry: DiaryEntry) -> DiaryOut:
    return DiaryOut(
        id=entry.id,
        parcel_id=entry.parcel_id,
        activity=entry.activity,
        entry_date=entry.entry_date,
        crop=entry.crop,
        notes=entry.notes,
        quantity=entry.quantity,
        unit=entry.unit,
        amount=entry.amount,
        product=entry.product,
        active_ingredient=entry.active_ingredient,
        dose=entry.dose,
        pre_harvest_days=entry.pre_harvest_days,
        lot_code=entry.lot_code,
        photos=[
            MediaOut(id=f.id, url=media.url_for(f), width=f.width, height=f.height, position=f.position)
            for f in media.for_entity(session, "diary", entry.id)
        ],
        safe_to_harvest_on=safe_on(entry),
        phi_warnings=phi_warnings(session, entry),
        created_at=entry.created_at,
    )


def owned_parcel(session: Session, owner: Profile | None, parcel_id: str) -> LandParcel:
    parcel = session.get(LandParcel, parcel_id)
    if parcel is None or (owner and owner.farmer_id and parcel.farmer_id != owner.farmer_id):
        raise DiaryError("Land parcel not found.", 404)
    return parcel


def add(session: Session, parcel: LandParcel, data: DiaryInput) -> DiaryEntry:
    entry = DiaryEntry(parcel_id=parcel.id, origin="local")
    _fields(entry, data)
    if entry.activity == "harvest":
        entry.lot_code = _lot_code(session, parcel, entry.entry_date)
    session.add(entry)
    session.flush()
    record_event(
        session, EventType.DIARY_RECORDED, entity_type=ENTITY, entity_id=entry.id,
        payload={"activity": entry.activity, "crop": entry.crop},
    )
    enqueue_sync(session, entity_type=ENTITY, entity_id=entry.id, operation="create")
    return entry


def update(session: Session, entry: DiaryEntry, data: DiaryInput) -> DiaryEntry:
    was_harvest = entry.activity == "harvest"
    _fields(entry, data)
    if entry.activity == "harvest" and not was_harvest:
        entry.lot_code = _lot_code(session, session.get(LandParcel, entry.parcel_id), entry.entry_date)
    elif entry.activity != "harvest":
        entry.lot_code = None
    enqueue_sync(session, entity_type=ENTITY, entity_id=entry.id, operation="update")
    return entry


def remove(session: Session, entry: DiaryEntry) -> None:
    media.remove_all(session, "diary", entry.id)
    enqueue_sync(session, entity_type=ENTITY, entity_id=entry.id, operation="delete")
    session.delete(entry)


def entries(session: Session, parcel: LandParcel) -> list[DiaryEntry]:
    return list(
        session.scalars(
            select(DiaryEntry)
            .where(DiaryEntry.parcel_id == parcel.id)
            .order_by(DiaryEntry.entry_date.desc(), DiaryEntry.created_at.desc())
        )
    )


def summary(session: Session, parcel: LandParcel, today: date | None = None) -> DiarySummaryOut:
    today = today or date.today()
    rows = entries(session, parcel)
    by_activity: dict[str, float] = {}
    spent = received = 0.0
    for row in rows:
        if row.amount is None:
            continue
        if row.activity == "sale":
            received += row.amount
        else:
            spent += row.amount
            by_activity[row.activity] = by_activity.get(row.activity, 0.0) + row.amount
    not_safe = sorted(
        {
            row.crop or "all"
            for row in rows
            if row.activity == "spray" and (clear := safe_on(row)) and clear > today
        }
    )
    return DiarySummaryOut(
        entries=len(rows),
        spent=round(spent, 2),
        received=round(received, 2),
        by_activity={key: round(value, 2) for key, value in by_activity.items()},
        last_entry=rows[0].entry_date if rows else None,
        not_safe_to_harvest=not_safe,
    )


# --------------------------------------------------------------------------- #
# Traceability report
# --------------------------------------------------------------------------- #


def _font(pdf: FPDF) -> str:
    """A face that draws Latin and Devanagari (farmers write notes in Hindi)."""
    for script in ("Deva", "Latn"):
        try:
            face = font_service.resolve(script)
        except font_service.FontUnavailableError:
            continue
        pdf.add_font("body", "", str(face.regular))
        pdf.add_font("body", "B", str(face.bold or face.regular))
        pdf.set_text_shaping(True)
        return "body"
    return "helvetica"


def traceability_pdf(session: Session, harvest: DiaryEntry, owner: Profile | None) -> bytes:
    """One harvest lot's record: what was done to the crop, and when."""
    if harvest.activity != "harvest":
        raise DiaryError("A traceability record is made for a harvest.", 422)
    parcel = session.get(LandParcel, harvest.parcel_id)
    path = resolve_location(
        session,
        village_code=parcel.village_code,
        subdistrict_code=parcel.subdistrict_code,
        district_code=parcel.district_code,
        state_code=parcel.state_code,
    )
    place = ", ".join(u.name for u in (path.village, path.subdistrict, path.district, path.state) if u)
    crop = reference.label_of("crops", harvest.crop) or harvest.crop or ""
    since = harvest.entry_date - timedelta(days=LOOKBACK_DAYS)
    history = list(
        session.scalars(
            select(DiaryEntry)
            .where(
                DiaryEntry.parcel_id == parcel.id,
                DiaryEntry.entry_date >= since,
                DiaryEntry.entry_date <= harvest.entry_date,
                (DiaryEntry.crop == harvest.crop) | DiaryEntry.crop.is_(None),
            )
            .order_by(DiaryEntry.entry_date)
        )
    )
    warnings = phi_warnings(session, harvest)
    cover = session.scalars(
        select(InsurancePolicy).where(
            InsurancePolicy.parcel_id == parcel.id, InsurancePolicy.category == "crop"
        )
    ).all()

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    family = _font(pdf)

    def line(text: str, size: float = 10, bold: bool = False, gap: float = 1.5) -> None:
        pdf.set_font(family, "B" if bold else "", size)
        pdf.multi_cell(0, size * 0.5, text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(gap)

    line("Traceability record / उत्पाद अनुरेखण रिकॉर्ड", 16, bold=True, gap=3)
    line(f"Lot: {harvest.lot_code}", 12, bold=True)
    line(f"Crop: {crop}    Harvested: {harvest.entry_date.isoformat()}"
         + (f"    Quantity: {harvest.quantity:g} {reference.label_of('quantity_units', harvest.unit) or ''}"
            if harvest.quantity else ""))
    line(f"Grower: {owner.display_name if owner else ''}    Plot: {parcel.label} ({parcel.area_hectares:.2f} ha)")
    line(f"Place: {place}", gap=3)

    line("Pre-harvest interval check", 12, bold=True)
    if warnings:
        line("NOT CLEAR. These sprays had not completed their waiting period at harvest:", bold=True)
        for text in warnings:
            line(f"  - {text}")
    else:
        line("Clear: every recorded spray had completed its pre-harvest interval before harvest.")
    pdf.ln(2)

    line(f"Activities from {since.isoformat()} to harvest", 12, bold=True)
    pdf.set_font(family, "B", 9)
    widths = (24, 46, 52, 38, 24)
    for width, head in zip(widths, ("Date", "Activity", "Product / ingredient", "Dose / quantity", "Wait (days)")):
        pdf.cell(width, 7, head, border=1)
    pdf.ln()
    pdf.set_font(family, "", 9)

    def fit(text: str, width: float) -> str:
        """Shorten text to its column, so a long label never runs into the next."""
        room = width - 2 * pdf.c_margin
        if pdf.get_string_width(text) <= room:
            return text
        while text and pdf.get_string_width(text + "...") > room:
            text = text[:-1]
        return text.rstrip(" ,(") + "..."

    for row in history:
        product = " / ".join(part for part in (row.product, row.active_ingredient) if part) or (row.notes or "")[:40]
        amount = row.dose or (f"{row.quantity:g} {row.unit or ''}" if row.quantity else "")
        cells = (
            row.entry_date.isoformat(),
            reference.label_of("diary_activities", row.activity) or row.activity,
            product[:40],
            amount[:28],
            "" if row.pre_harvest_days is None else str(row.pre_harvest_days),
        )
        for width, text in zip(widths, cells):
            pdf.cell(width, 7, fit(text, width), border=1)
        pdf.ln()
    pdf.ln(3)

    if cover:
        line("Crop insurance on this plot", 12, bold=True)
        for policy in cover:
            scheme = reference.label_of("insurance_schemes", policy.scheme) or policy.insurer or ""
            season = f" {policy.season} {policy.season_year}" if policy.season else ""
            line(f"  - {scheme}{season} {policy.policy_number or ''}".rstrip())
        pdf.ln(2)

    pdf.set_font(family, "", 8)
    pdf.multi_cell(
        0,
        4,
        "This record is declared by the grower from their own farm diary kept in ViksitGaanw. It is not a "
        "laboratory residue test or a certification. Generated "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
    )
    return bytes(pdf.output())
