"""Generating the Detailed Project Report as a PDF, in an Indian language.

The report is deliberately tabular. A bank's credit officer reads project cost,
means of finance, profitability and DSCR as tables, and a table survives
translation far better than paragraphs do -- which matters when the same
document has to come out in Tamil, Odia or Marathi from one template.

Two things are treated as non-negotiable here:

* **Honesty about the numbers.** Every figure comes from a stated planning
  range, the report says so on its face, and the disclaimer is not buried.
  Nobody should be able to read this document and mistake it for a valuation.
* **Honesty about the translation.** When the chosen language's catalogue is
  incomplete, the report says which parts fell back to English rather than
  quietly mixing languages and hoping nobody notices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from fpdf import FPDF, FontFace
from fpdf.enums import XPos, YPos

from .. import knowledge
from . import fonts as font_service
from .financials import Financials
from .i18n import Translator
from .opportunities import Assessment, LandProfile, Signal

logger = logging.getLogger("viksitgaanw.dpr")

# fpdf2 subsets the embedded font, and fontTools warns once per report that it
# does not know how to subset a table it then simply drops (MERG in Nirmala UI,
# used for emoji-style ligatures a project report has no use for). It is not
# actionable and it buries the API's real log lines, so quiet just that logger.
logging.getLogger("fontTools.subset").setLevel(logging.ERROR)

PAGE_FORMAT = "A4"
MARGIN_MM = 16.0
BODY_SIZE = 9.5
SMALL_SIZE = 8.0
HEADING_SIZE = 12.0
TITLE_SIZE = 20.0

INK = (26, 32, 28)
MUTED = (104, 112, 106)
RULE = (198, 205, 197)
BAND = (238, 242, 234)
ACCENT = (33, 87, 50)
WARN_BG = (253, 245, 226)
PAPER = (255, 255, 255)


@dataclass
class ReportInput:
    """Everything the renderer needs. Assembled by the router, not fetched here."""

    parcel: Any
    location: Any
    land: LandProfile
    assessment: Assessment
    financials: Financials
    translator: Translator
    promoter_name: str
    promoter_phone: str | None
    report_number: str
    generated_at: datetime
    lgd_imported_at: str | None = None
    place_names: dict[str, str] | None = None


class _Pdf(FPDF):
    """A4 report with a running header and a page footer."""

    def __init__(self, translator: Translator, title: str) -> None:
        super().__init__(orientation="P", unit="mm", format=PAGE_FORMAT)
        self._translator = translator
        self._doc_title = title
        #: Read once here so every layout helper can ask the page, not the
        #: translator, which way round it is. An RTL language with no
        #: translation yet prints an English report, and an English report
        #: laid out right to left would read backwards to everyone.
        self.rtl = translator.is_rtl and translator.coverage > 0
        #: Characters no embedded face could draw. With shaping on, fpdf2
        #: prints these as blank boxes without a word, so they are counted here.
        self.unprintable: set[str] = set()
        #: Faces borrowed from when "body" lacks a glyph, and the face the page
        #: footer is set in. Both are decided in :func:`_register_fonts`.
        self.fallback_families: list[str] = []
        self.footer_family = "body"
        self.set_margins(MARGIN_MM, MARGIN_MM, MARGIN_MM)
        self.set_auto_page_break(auto=True, margin=20)
        self.set_title(title)
        self.set_creator("ViksitGaanw")
        # Suppressed on the cover, which carries its own masthead.
        self.show_running_header = False

    def header(self) -> None:
        if not self.show_running_header:
            return
        self.set_font("body", "", SMALL_SIZE)
        self.set_text_color(*MUTED)
        self.cell(
            0,
            5,
            self._doc_title,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            align="R" if self.rtl else "L",
        )
        self.set_draw_color(*RULE)
        self.set_line_width(0.2)
        self.line(MARGIN_MM, self.get_y(), self.w - MARGIN_MM, self.get_y())
        self.ln(3)
        self.set_text_color(*INK)

    def footer(self) -> None:
        self.set_y(-14)
        borrowed = self.footer_family != "body"
        self.set_font(self.footer_family, "", SMALL_SIZE)
        if borrowed:
            # Set in a borrowed face, the footer's own words come back from
            # the body face -- the reverse of everywhere else in the report.
            self.set_fallback_fonts(["body"], exact_match=False)
        self.set_text_color(*MUTED)
        self.cell(
            0,
            5,
            self._translator.s("doc.page", n=self.page_no(), total="{nb}"),
            align="C",
        )
        self.set_text_color(*INK)
        if borrowed:
            self.set_fallback_fonts(self.fallback_families, exact_match=False)

    def get_fallback_font(self, char: str, style: str = "") -> str | None:
        # fpdf2 asks this only once the current face has failed, so a None here
        # means the character is about to print as an empty box.
        font = super().get_fallback_font(char, style)
        if font is None:
            self.unprintable.add(char)
        return font


def _register_fonts(pdf: _Pdf, translator: Translator) -> font_service.FontSet:
    """Embed a face that can draw this language, and switch shaping on."""
    try:
        font_set = font_service.resolve(translator.script)
    except font_service.FontUnavailableError as error:
        raise font_service.FontUnavailableError(
            translator.script, translator.endonym
        ) from error

    pdf.add_font("body", "", str(font_set.regular))
    pdf.add_font("body", "B", str(font_set.bold or font_set.regular))

    families = []
    for index, fallback in enumerate(font_service.fallbacks(font_set)):
        family = f"fallback{index}"
        pdf.add_font(family, "", str(fallback.regular))
        pdf.add_font(family, "B", str(fallback.bold or fallback.regular))
        families.append(family)
    if families:
        pdf.set_fallback_fonts(families, exact_match=False)
    pdf.fallback_families = families

    # fpdf2 fills in the page total ({nb}) in whatever face is current, and
    # never looks at the fallbacks for it. Noto Sans Ol Chiki has no 0-9, so
    # a Santali footer printed "Page 4 of" and stopped. Such a footer is set
    # in the first face that has the digits.
    digits = [ord(digit) for digit in "0123456789"]
    pdf.footer_family = next(
        (
            family
            for family in ("body", *families)
            if all(point in pdf.fonts[family].cmap for point in digits)
        ),
        "body",
    )

    pdf.set_font("body", "", BODY_SIZE)
    # Indic scripts reorder and join; without shaping every matra lands in the
    # wrong place and the report is unreadable to the person it is written for.
    pdf.set_text_shaping(True)
    return font_set


# --------------------------------------------------------------------------- #
# Layout helpers
# --------------------------------------------------------------------------- #


def _text_align(pdf: _Pdf) -> str:
    """Which edge body text hangs from.

    Urdu, Kashmiri and Sindhi read right to left. HarfBuzz already shapes and
    orders the glyphs within a line correctly; what it cannot do is decide that
    the paragraph itself belongs against the other margin.
    """
    return "R" if pdf.rtl else "L"


def _column_aligns(pdf: _Pdf, aligns: tuple[str, ...]) -> tuple[str, ...]:
    """Mirror a row of column alignments for a right-to-left report.

    Numbers stay hard against the column edge they are read from, so a LEFT
    label becomes RIGHT and vice versa. Centred columns are unaffected.
    """
    if not pdf.rtl:
        return aligns
    flip = {"LEFT": "RIGHT", "RIGHT": "LEFT"}
    return tuple(flip.get(align, align) for align in aligns)


def _heading(pdf: _Pdf, text: str) -> None:
    if pdf.get_y() > pdf.h - 60:
        pdf.add_page()
    pdf.ln(3)
    pdf.set_font("body", "B", HEADING_SIZE)
    pdf.set_text_color(*ACCENT)
    pdf.multi_cell(
        0, 6.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align=_text_align(pdf)
    )
    pdf.set_text_color(*INK)
    pdf.set_draw_color(*RULE)
    pdf.line(MARGIN_MM, pdf.get_y() + 0.5, pdf.w - MARGIN_MM, pdf.get_y() + 0.5)
    pdf.ln(3)
    pdf.set_font("body", "", BODY_SIZE)


def _para(pdf: _Pdf, text: str, *, muted: bool = False, size: float = BODY_SIZE) -> None:
    if not text:
        return
    pdf.set_font("body", "", size)
    pdf.set_text_color(*(MUTED if muted else INK))
    pdf.multi_cell(
        0, 4.8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align=_text_align(pdf)
    )
    pdf.set_text_color(*INK)
    pdf.ln(1.8)


def _bullets(pdf: _Pdf, lines: list[str], *, marker: str = "•") -> None:
    pdf.set_font("body", "", BODY_SIZE)
    for line in lines:
        if not line:
            continue
        pdf.set_x(MARGIN_MM + 2)
        # Marker first in logical order for every language: fpdf2's bidi pass
        # already carries it to the right-hand edge of an Urdu line.
        pdf.multi_cell(
            pdf.w - 2 * MARGIN_MM - 2,
            4.6,
            f"{marker}  {line}",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            align=_text_align(pdf),
        )
        pdf.ln(0.6)
    pdf.ln(1.5)


def _headings_face() -> FontFace:
    return FontFace(emphasis="BOLD", color=INK, fill_color=BAND)


def _facts(pdf: _Pdf, rows: list[tuple[str, str]]) -> None:
    """A two-column label/value block -- the shape most of this report takes."""
    rows = [(label, value) for label, value in rows if value not in (None, "")]
    if not rows:
        return
    usable = pdf.w - 2 * MARGIN_MM
    with pdf.table(
        col_widths=(38, 62) if not pdf.rtl else (62, 38),
        width=usable,
        text_align=_column_aligns(pdf, ("LEFT", "LEFT")),
        first_row_as_headings=False,
        borders_layout="HORIZONTAL_LINES",
        line_height=5.8,
        padding=(1.4, 1.8, 1.4, 1.8),
    ) as table:
        for label, value in rows:
            row = table.row()
            # Label first in reading order: on the right for a RTL report.
            if pdf.rtl:
                row.cell(str(value))
                row.cell(label, style=FontFace(color=MUTED))
            else:
                row.cell(label, style=FontFace(color=MUTED))
                row.cell(str(value))
    pdf.ln(2.5)


def _grid(
    pdf: _Pdf,
    headers: list[str],
    rows: list[list[str]],
    *,
    widths: tuple[float, ...] | None = None,
    aligns: tuple[str, ...] | None = None,
) -> None:
    if not rows:
        return
    usable = pdf.w - 2 * MARGIN_MM
    columns = len(headers)
    if pdf.rtl:
        # Mirror the whole grid: first column on the right, and every row with it.
        headers = list(reversed(headers))
        rows = [list(reversed(values)) for values in rows]
        widths = tuple(reversed(widths)) if widths else None
        aligns = tuple(reversed(aligns)) if aligns else None

    with pdf.table(
        col_widths=widths or tuple([1] * columns),
        width=usable,
        text_align=_column_aligns(pdf, aligns or tuple(["RIGHT"] * columns)),
        headings_style=_headings_face(),
        borders_layout="HORIZONTAL_LINES",
        line_height=5.4,
        padding=(1.2, 1.4, 1.2, 1.4),
    ) as table:
        head = table.row()
        for label in headers:
            head.cell(label)
        for values in rows:
            row = table.row()
            for value in values:
                row.cell(str(value))
    pdf.ln(2.5)


def _notice(pdf: _Pdf, text: str) -> None:
    """A boxed caution. Used for the disclaimer and the translation notice."""
    pdf.set_font("body", "", SMALL_SIZE)
    pdf.set_fill_color(*WARN_BG)
    pdf.set_draw_color(*RULE)
    pdf.multi_cell(
        0,
        4.4,
        text,
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        align=_text_align(pdf),
        fill=True,
        border=1,
        padding=(2, 2.5, 2, 2.5),
    )
    pdf.ln(2)
    pdf.set_font("body", "", BODY_SIZE)
    # fpdf2 keeps the fill colour on the document, so leaving it set here would
    # tint every table drawn afterwards.
    pdf.set_fill_color(*PAPER)


def _signal_lines(translator: Translator, signals: list[Signal]) -> list[str]:
    return [translator.s(signal.key, **signal.variables) for signal in signals]


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #


def _cover(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    pdf.add_page()

    pdf.ln(28)
    align = _text_align(pdf)
    pdf.set_font("body", "B", TITLE_SIZE)
    pdf.set_text_color(*ACCENT)
    pdf.multi_cell(
        0, 10, t.s("doc.title"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align=align
    )
    pdf.set_text_color(*INK)
    pdf.ln(1)

    pdf.set_font("body", "", 11)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        0, 5.4, t.s("doc.subtitle"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align=align
    )
    pdf.set_text_color(*INK)
    pdf.ln(8)

    pdf.set_font("body", "B", 15)
    pdf.multi_cell(
        0,
        7,
        t.opportunity_name(data.assessment.opportunity),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        align=align,
    )
    pdf.ln(4)

    place = _place_line(data)
    _facts(
        pdf,
        [
            (t.s("doc.preparedFor"), data.promoter_name),
            (t.s("f.parcelLabel"), data.parcel.label),
            (t.s("f.district"), place),
            (t.s("f.areaHectares"), f"{data.parcel.area_hectares:.3f}"),
            (t.s("doc.reportNumber"), data.report_number),
            (t.s("doc.preparedOn"), data.generated_at.strftime("%d %B %Y")),
        ],
    )

    # Kept out of the table above: at Devanagari and Malayalam line heights it
    # wraps to two lines, and a wrapped cell fights the row rule.
    _para(pdf, t.s("doc.generatedBy"), muted=True, size=SMALL_SIZE)
    pdf.ln(3)
    if not t.is_fully_translated and t.language != "en":
        _notice(pdf, t.s("doc.languageNotice", language=t.endonym))

    _notice(pdf, t.s("t.disclaimerBody"))

    pdf.show_running_header = True


def _place_line(data: ReportInput) -> str:
    names = data.place_names or {}
    parts = [
        names.get("village"),
        names.get("subdistrict"),
        names.get("district"),
        names.get("state"),
    ]
    return ", ".join(part for part in parts if part)


def _section_promoter(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    parcel = data.parcel
    names = data.place_names or {}

    pdf.add_page()
    _heading(pdf, t.s("sec.promoter"))

    depth = (
        f"{parcel.water_depth_value:g} "
        f"{t.reference('depth_units', parcel.water_depth_unit)}"
        f" ({parcel.water_depth_metres:.1f} {t.s('v.metre')})"
        if parcel.water_depth_value and parcel.water_depth_unit
        else t.s("v.notStated")
    )
    coordinates = (
        f"{parcel.latitude:.5f}, {parcel.longitude:.5f}"
        if parcel.latitude is not None and parcel.longitude is not None
        else t.s("t.noCoordinates")
    )
    codes = " / ".join(
        code
        for code in (
            parcel.state_code,
            parcel.district_code,
            parcel.subdistrict_code,
            parcel.village_code,
        )
        if code
    )

    _facts(
        pdf,
        [
            (t.s("f.promoterName"), data.promoter_name),
            (t.s("f.promoterPhone"), data.promoter_phone or t.s("v.notStated")),
            (t.s("f.parcelLabel"), parcel.label),
            (t.s("f.village"), names.get("village") or t.s("v.notStated")),
            (t.s("f.subdistrict"), names.get("subdistrict") or t.s("v.notStated")),
            (t.s("f.district"), names.get("district") or t.s("v.notStated")),
            (t.s("f.state"), names.get("state") or t.s("v.notStated")),
            (t.s("f.lgdCodes"), codes),
            (t.s("f.surveyNumber"), parcel.survey_number or t.s("v.notStated")),
            (t.s("f.coordinates"), coordinates),
            (
                t.s("f.landArea"),
                f"{parcel.area_value:g} {t.reference('area_units', parcel.area_unit)}",
            ),
            (t.s("f.areaHectares"), t.number(parcel.area_hectares, 3)),
            (t.s("f.areaAcres"), t.number(parcel.area_hectares / 0.40468564224, 3)),
            (t.s("f.ownership"), t.reference("ownership_types", parcel.ownership_type)),
            (t.s("f.soil"), t.reference("soil_types", parcel.soil_type)),
            (t.s("f.waterSources"), t.reference_list("water_sources", parcel.water_sources)),
            (t.s("f.waterQuality"), t.reference("water_types", parcel.water_type)),
            (t.s("f.waterDepth"), depth),
            (t.s("f.irrigation"), t.reference("irrigation_types", parcel.irrigation_type)),
            (
                t.s("f.existingCrops"),
                t.reference_list("crops", parcel.existing_crops),
            ),
            (t.s("f.notes"), parcel.notes or t.s("v.notStated")),
        ],
    )


def _section_project(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    assessment = data.assessment
    economics = assessment.economics
    opportunity = assessment.opportunity

    _heading(pdf, t.s("sec.project"))
    _para(pdf, t.summary(opportunity))

    kind = knowledge.kind_index().get(opportunity["kind"], {})
    if assessment.sizing.mode == "unit":
        size = (
            f"{assessment.sizing.units:g} × "
            f"{t.label(assessment.sizing.unit_label)} "
            f"({t.number(assessment.sizing.hectares, 2)} {t.s('v.hectare')})"
        )
    else:
        size = f"{t.number(assessment.sizing.hectares, 3)} {t.s('v.hectare')}"

    risk_source = next(
        (
            entry.get("label")
            for entry in knowledge.opportunity_meta().get("riskLevels", [])
            if entry["code"] == economics.risk_level
        ),
        None,
    )
    risk_label = t.reference("risk", economics.risk_level, risk_source)

    _facts(
        pdf,
        [
            (t.s("f.projectName"), t.opportunity_name(opportunity)),
            (t.s("f.projectType"), t.reference("kinds", opportunity["kind"], kind.get("label"))),
            (t.s("f.projectSize"), size),
            (
                t.s("f.gestation"),
                f"{economics.gestation_months} {t.s('v.months')}",
            ),
            (t.s("f.fullYield"), str(economics.full_yield_year)),
            (
                t.s("f.projectLife"),
                f"{economics.project_life_years} {t.s('v.years')}",
            ),
            (t.s("f.riskLevel"), risk_label),
            (
                t.s("f.labourDays"),
                f"{t.number(economics.labour_days_per_year, 0)} {t.s('v.personDays')}",
            ),
        ],
    )


def _section_suitability(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    assessment = data.assessment

    _heading(pdf, t.s("sec.suitability"))
    _para(pdf, t.s("t.suitabilityScore", score=str(assessment.score)))

    reasons = _signal_lines(t, assessment.reasons)
    if reasons:
        _para(pdf, t.s("f.reasons") + ":")
        _bullets(pdf, reasons)

    cautions = _signal_lines(t, assessment.cautions + assessment.blockers)
    if cautions:
        _para(pdf, t.s("f.cautions") + ":")
        _bullets(pdf, cautions, marker="!")


def _section_cost(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    money = data.financials

    _heading(pdf, t.s("sec.cost"))
    _para(pdf, t.s("t.costIntro"), muted=True, size=SMALL_SIZE)

    _grid(
        pdf,
        [t.s("f.item"), f"{t.s('f.amount')} ({t.s('v.rupees')})"],
        [
            [t.s("f.capitalCost"), t.money(money.capital_cost)],
            [t.s("f.contingency"), t.money(money.contingency)],
            [t.s("f.workingCapital"), t.money(money.working_capital)],
            [t.s("f.totalProjectCost"), t.money(money.total_project_cost)],
        ],
        widths=(62, 38),
        aligns=("LEFT", "RIGHT"),
    )

    economics = data.assessment.economics
    _para(
        pdf,
        f"{t.s('f.capitalCost')}: {t.money_range(economics.capex.low, economics.capex.high)} · "
        f"{t.s('f.operatingCost')}: "
        f"{t.money_range(economics.opex_per_year.low, economics.opex_per_year.high)} "
        f"{t.s('v.perYear')} · {t.s('f.revenue')}: "
        f"{t.money_range(economics.revenue_per_year.low, economics.revenue_per_year.high)} "
        f"{t.s('v.perYear')}",
        muted=True,
        size=SMALL_SIZE,
    )


def _section_finance(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    money = data.financials

    _heading(pdf, t.s("sec.finance"))
    _para(pdf, t.s("t.financeIntro"), muted=True, size=SMALL_SIZE)

    _grid(
        pdf,
        [t.s("f.item"), f"{t.s('f.amount')} ({t.s('v.rupees')})"],
        [
            [t.s("f.promoterContribution"), t.money(money.promoter_contribution)],
            [t.s("f.termLoan"), t.money(money.term_loan)],
            [t.s("f.total"), t.money(money.total_project_cost)],
        ],
        widths=(62, 38),
        aligns=("LEFT", "RIGHT"),
    )

    _facts(
        pdf,
        [
            (t.s("f.marginPercent"), t.percent(money.margin, 0)),
            (t.s("f.interestRate"), t.percent(money.interest_rate, 1)),
            (
                t.s("f.repaymentYears"),
                f"{money.repayment_years} {t.s('v.years')}",
            ),
            (
                t.s("f.moratorium"),
                f"{money.moratorium_years} {t.s('v.years')}",
            ),
        ],
    )


def _section_profitability(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    money = data.financials

    _heading(pdf, t.s("sec.profitability"))
    _para(pdf, t.s("t.profitabilityIntro"), muted=True, size=SMALL_SIZE)

    _grid(
        pdf,
        [
            t.s("f.year"),
            t.s("f.revenue"),
            t.s("f.operatingCost"),
            t.s("f.grossSurplus"),
            t.s("f.interest"),
            t.s("f.depreciation"),
            t.s("f.netProfit"),
        ],
        [
            [
                str(row.year),
                t.money(row.revenue),
                t.money(row.operating_cost),
                t.money(row.gross_surplus),
                t.money(row.interest),
                t.money(row.depreciation),
                t.money(row.net_surplus),
            ]
            for row in money.projection
        ],
        widths=(10, 15, 15, 15, 13, 15, 17),
        aligns=("CENTER", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"),
    )
    _para(pdf, f"({t.s('v.rupees')})", muted=True, size=SMALL_SIZE)


def _section_repayment(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    money = data.financials

    _heading(pdf, t.s("sec.repayment"))
    _para(pdf, t.s("t.repaymentIntro"), muted=True, size=SMALL_SIZE)

    _grid(
        pdf,
        [
            t.s("f.year"),
            t.s("f.openingBalance"),
            t.s("f.interest"),
            t.s("f.principal"),
            t.s("f.closingBalance"),
            t.s("f.debtService"),
            t.s("f.dscr"),
        ],
        [
            [
                str(row.year),
                t.money(row.opening_balance),
                t.money(row.interest),
                t.money(row.principal_repaid),
                t.money(row.closing_balance),
                t.money(row.debt_service),
                f"{row.dscr:.2f}" if row.dscr is not None else "—",
            ]
            for row in money.projection
        ],
        widths=(10, 18, 13, 15, 18, 15, 11),
        aligns=("CENTER", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"),
    )


def _section_indicators(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    money = data.financials
    economics = data.assessment.economics

    _heading(pdf, t.s("sec.indicators"))
    _facts(
        pdf,
        [
            (
                t.s("f.averageDscr"),
                f"{money.average_dscr:.2f}" if money.average_dscr else t.s("v.notStated"),
            ),
            (
                t.s("f.breakEven"),
                t.percent(money.break_even_capacity)
                if money.break_even_capacity
                else t.s("v.notStated"),
            ),
            (
                t.s("f.payback"),
                f"{money.payback_years:.1f} {t.s('v.years')}"
                if money.payback_years
                else t.s("v.notStated"),
            ),
            (
                t.s("f.netAtFullYield"),
                f"{t.money(money.net_at_full_yield)} {t.s('v.perYear')}",
            ),
            (
                t.s("f.returnOnCost"),
                t.percent(money.return_on_cost) if money.return_on_cost else t.s("v.notStated"),
            ),
            (
                t.s("f.labourDays"),
                f"{t.number(economics.labour_days_per_year, 0)} {t.s('v.personDays')}",
            ),
        ],
    )


def _section_market(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    _heading(pdf, t.s("sec.market"))
    _para(pdf, t.s("t.marketIntro"))

    for resource in data.assessment.opportunity.get("resources", []):
        _para(pdf, f"{t.label(resource.get('label'))} — {resource['url']}", size=SMALL_SIZE)


def _section_export(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    export = data.assessment.opportunity.get("export") or {}
    market = knowledge.get_export_market(export.get("commodity"))
    if export.get("potential") == "none" or market is None:
        return

    _heading(pdf, t.s("sec.export"))
    _para(pdf, t.s("t.exportIntro"), muted=True, size=SMALL_SIZE)

    india = market.get("indiaExportUsd", {})
    world = market.get("worldTradeUsd", {})
    countries = knowledge.load_export_markets().get("countries", {})
    destinations = ", ".join(
        t.label(countries.get(code)) or code for code in market.get("destinations", [])
    )
    certificates = {
        entry["code"]: entry
        for entry in knowledge.load_export_markets().get("certifications", [])
    }

    confidence_key = (
        "v.reported" if india.get("confidence") == "reported" else "v.estimate"
    )

    _facts(
        pdf,
        [
            (t.s("f.projectName"), t.label(market.get("label"))),
            (
                t.s("f.exportPotential"),
                t.s("v.strong" if export.get("potential") == "strong" else "v.emerging"),
            ),
            (
                t.s("f.worldTrade"),
                t.usd_range(world.get("low", 0), world.get("high", 0)),
            ),
            (
                t.s("f.indiaExports"),
                t.usd_range(india.get("low", 0), india.get("high", 0)),
            ),
            (t.s("f.dataConfidence"), t.s(confidence_key)),
            (t.s("f.topDestinations"), destinations),
        ],
    )

    _para(pdf, t.label(market.get("indiaShareNote")))
    _para(pdf, f"{t.s('f.pricingNote')}: {t.label(market.get('priceNote'))}")
    _para(pdf, f"{t.s('f.barriers')}: {t.label(market.get('barriers'))}")

    needed = [
        f"{t.label(certificates[code].get('label'))} — {certificates[code].get('url', '')}"
        for code in market.get("certifications", [])
        if code in certificates
    ]
    if needed:
        _para(pdf, t.s("f.certifications") + ":")
        _bullets(pdf, needed)

    links = market.get("resources", []) + knowledge.load_export_markets().get(
        "commonResources", []
    )
    if links:
        _bullets(
            pdf,
            [f"{t.label(link.get('label'))} — {link['url']}" for link in links],
            # Not an arrow: Nirmala UI has none. Bidi mirrors this one, so it
            # still points the reading way in an Urdu report.
            marker="›",
        )

    _notice(pdf, t.label(knowledge.load_export_markets().get("disclaimer")))


def _section_schemes(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    index = knowledge.scheme_index()
    entries = [
        index[code]
        for code in data.assessment.opportunity.get("schemes", [])
        if code in index
    ]
    if not entries:
        return

    _heading(pdf, t.s("sec.schemes"))
    _para(pdf, t.s("t.schemesIntro"), muted=True, size=SMALL_SIZE)
    _bullets(
        pdf,
        [f"{t.label(entry.get('label'))} — {entry.get('url', '')}" for entry in entries],
    )


def _section_risks(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    economics = data.assessment.economics

    _heading(pdf, t.s("sec.risks"))
    _para(pdf, t.s("t.riskIntro"))

    risks = [
        t.s("t.riskGeneric1"),
        t.s("t.riskGeneric2"),
        t.s("t.riskGeneric3"),
    ]
    if economics.gestation_months >= 12:
        risks.append(t.s("t.riskGestation", months=str(economics.gestation_months)))
    if data.financials.total_project_cost > 1_000_000:
        risks.append(t.s("t.riskHighCapex"))
    risks.extend(_signal_lines(t, data.assessment.cautions))

    _bullets(pdf, risks)


def _section_assumptions(pdf: _Pdf, data: ReportInput) -> None:
    t = data.translator
    meta = knowledge.opportunity_meta()
    as_of = meta.get("dataAsOf", "")

    _heading(pdf, t.s("sec.assumptions"))
    _para(pdf, t.s("t.assumptionsIntro"))
    _bullets(
        pdf,
        [
            t.s(
                "t.assumptionArea",
                area=f"{t.number(data.assessment.sizing.hectares, 3)} {t.s('v.hectare')}",
            ),
            t.s("t.assumptionPrices", dataAsOf=as_of),
            t.s("t.assumptionSubsidy"),
            t.s("t.assumptionLabour"),
            t.s("t.assumptionTitle"),
        ],
    )
    _para(pdf, t.label(meta.get("basis")), muted=True, size=SMALL_SIZE)


def _section_disclaimer(pdf: _Pdf, data: ReportInput, font_set) -> None:
    t = data.translator
    _heading(pdf, t.s("sec.disclaimer"))
    _notice(pdf, t.s("t.disclaimerBody"))

    _para(
        pdf,
        t.s(
            "t.dataProvenance",
            importedAt=data.lgd_imported_at or "—",
            dataAsOf=knowledge.opportunity_meta().get("dataAsOf", "—"),
        ),
        muted=True,
        size=SMALL_SIZE,
    )
    _para(pdf, f"Typeface: {font_set.source}", muted=True, size=SMALL_SIZE)

    pdf.ln(10)
    _facts(
        pdf,
        [
            (t.s("t.place"), ""),
            (t.s("t.date"), date.today().strftime("%d-%m-%Y")),
            (t.s("t.signature"), ""),
        ],
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def render(data: ReportInput) -> bytes:
    """Draw the whole report and return the PDF bytes."""
    translator = data.translator
    pdf = _Pdf(translator, translator.s("doc.title"))
    pdf.alias_nb_pages()
    font_set = _register_fonts(pdf, translator)

    _cover(pdf, data)
    _section_promoter(pdf, data)
    _section_project(pdf, data)
    _section_suitability(pdf, data)
    _section_cost(pdf, data)
    _section_finance(pdf, data)
    _section_profitability(pdf, data)
    _section_repayment(pdf, data)
    _section_indicators(pdf, data)
    _section_market(pdf, data)
    _section_export(pdf, data)
    _section_schemes(pdf, data)
    _section_risks(pdf, data)
    _section_assumptions(pdf, data)
    _section_disclaimer(pdf, data, font_set)

    # Output draws the last page's footer, so it has to happen before counting.
    document = bytes(pdf.output())
    if pdf.unprintable:
        logger.warning(
            "The %s report could not print %d character(s): %s",
            translator.language,
            len(pdf.unprintable),
            " ".join(f"U+{ord(char):04X}" for char in sorted(pdf.unprintable)),
        )
    return document


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
