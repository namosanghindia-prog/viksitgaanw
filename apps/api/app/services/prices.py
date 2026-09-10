"""Mandi prices, and rupees in the currencies international investors use.

**Prices** come from Agmarknet, the government's daily mandi price feed,
published on data.gov.in. They are imported -- by the script, or on demand
when a data.gov.in API key is configured -- and kept locally, so a farmer can
look up last week's onion price with no signal. Nothing here is invented: a
crop with no imported rows shows no price.

**Exchange rates** are the European Central Bank reference rates, via the
free Frankfurter service, cached with their date, and overridable by hand.
They exist so an investor in London reads "about GBP 5,800" beside "Rs 6.5
lakh" -- as an indication, never a quote.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from .. import knowledge
from ..config import get_settings
from ..models import FxRate, MandiPrice
from ..schemas import FxOut, FxRateOut, PricePointOut, PriceRowOut, PriceSummaryOut
from . import net

AGMARKNET_URL = "https://api.data.gov.in/resource/{resource}"
AGMARKNET_SOURCE = "Agmarknet (data.gov.in)"
FX_URL = "https://api.frankfurter.dev/v1/latest"
FX_SOURCE = "frankfurter"
#: Currencies offered to international profiles. All are in the ECB set.
FX_CURRENCIES = ("USD", "EUR", "GBP", "JPY", "SGD", "AUD", "CAD", "CHF")


class PriceError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- #
# Importing
# --------------------------------------------------------------------------- #


def _date(value: Any) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _number(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _normalise(record: dict[str, Any]) -> dict[str, Any] | None:
    """One Agmarknet record, whatever its column capitalisation, or None if unusable."""
    row = {str(key).strip().lower().replace(" ", "_"): value for key, value in record.items()}
    arrival = _date(row.get("arrival_date"))
    modal = _number(row.get("modal_price"))
    commodity = str(row.get("commodity") or "").strip()
    market = str(row.get("market") or "").strip()
    if not (arrival and modal and commodity and market):
        return None
    return {
        "state_name": str(row.get("state") or "").strip(),
        "district_name": str(row.get("district") or "").strip(),
        "market": market,
        "commodity": commodity,
        # Empty rather than NULL: SQLite treats NULLs as distinct in a unique
        # key, so a re-import of rows without a variety would double them.
        "variety": str(row.get("variety") or "").strip(),
        "grade": str(row.get("grade") or "").strip(),
        "arrival_date": arrival,
        "min_price": _number(row.get("min_price")),
        "max_price": _number(row.get("max_price")),
        "modal_price": modal,
    }


def store(session: Session, records: Iterable[dict[str, Any]], source: str = AGMARKNET_SOURCE) -> int:
    """Upsert price rows; a re-import of the same day replaces rather than doubles."""
    count = 0
    for record in records:
        row = _normalise(record)
        if row is None:
            continue
        statement = insert(MandiPrice).values(**row, source=source)
        statement = statement.on_conflict_do_update(
            index_elements=["market", "commodity", "variety", "grade", "arrival_date"],
            set_={
                "min_price": statement.excluded.min_price,
                "max_price": statement.excluded.max_price,
                "modal_price": statement.excluded.modal_price,
                "state_name": statement.excluded.state_name,
                "district_name": statement.excluded.district_name,
                "source": statement.excluded.source,
            },
        )
        session.execute(statement)
        count += 1
    return count


def import_csv(session: Session, text: str) -> int:
    return store(session, csv.DictReader(io.StringIO(text)), source=f"{AGMARKNET_SOURCE} CSV")


def fetch_agmarknet(
    session: Session,
    *,
    api_key: str | None = None,
    state: str | None = None,
    commodity: str | None = None,
    limit: int = 2000,
) -> int:
    """Pull today's published prices from data.gov.in. Needs an API key."""
    key = api_key or get_settings().data_gov_api_key
    if not key:
        raise PriceError(
            "No data.gov.in API key is configured. Get a free key at data.gov.in and set VG_DATA_GOV_API_KEY.",
            422,
        )
    resource = knowledge.load_mandi_commodities()["resourceId"]
    params: dict[str, Any] = {"api-key": key, "format": "json", "limit": limit, "offset": 0}
    if state:
        params["filters[state]"] = state
    if commodity:
        params["filters[commodity]"] = commodity
    try:
        payload = net.get_json(AGMARKNET_URL.format(resource=resource), params, timeout=30)
    except net.NetworkDisabled as exc:
        raise PriceError(str(exc), 503) from exc
    if not payload or "records" not in payload:
        raise PriceError("data.gov.in did not answer. Try again when online.", 503)
    return store(session, payload["records"])


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def terms_for(crop: str) -> list[str]:
    return list(knowledge.load_mandi_commodities().get("crops", {}).get(crop, []))


def summary(
    session: Session,
    crop: str,
    *,
    state_name: str | None = None,
    days: int = 30,
    today: date | None = None,
) -> PriceSummaryOut:
    terms = terms_for(crop)
    if not terms:
        return PriceSummaryOut(crop=crop, terms=[], latest=[], trend=[], rows=0, source=AGMARKNET_SOURCE)

    match = or_(*[func.lower(MandiPrice.commodity).contains(term) for term in terms])
    newest = session.scalar(select(func.max(MandiPrice.arrival_date)).where(match))
    if newest is None:
        return PriceSummaryOut(crop=crop, terms=terms, latest=[], trend=[], rows=0, source=AGMARKNET_SOURCE)

    since = newest - timedelta(days=days)
    rows = list(
        session.scalars(
            select(MandiPrice)
            .where(match, MandiPrice.arrival_date >= since)
            .order_by(MandiPrice.arrival_date.desc())
        )
    )

    # Latest price at each market; the viewer's own state first.
    latest_by_market: dict[str, MandiPrice] = {}
    for row in rows:
        latest_by_market.setdefault(f"{row.state_name}|{row.market}|{row.variety}", row)
    wanted = (state_name or "").lower()
    latest = sorted(
        latest_by_market.values(),
        key=lambda row: (row.state_name.lower() != wanted, -row.arrival_date.toordinal(), row.market),
    )[:25]

    by_day: dict[date, list[float]] = defaultdict(list)
    for row in rows:
        if not wanted or row.state_name.lower() == wanted:
            by_day[row.arrival_date].append(row.modal_price)
    if not by_day:  # nothing in the viewer's state: show the national trend
        for row in rows:
            by_day[row.arrival_date].append(row.modal_price)

    return PriceSummaryOut(
        crop=crop,
        terms=terms,
        latest=[
            PriceRowOut(
                market=row.market,
                district_name=row.district_name,
                state_name=row.state_name,
                commodity=row.commodity,
                variety=row.variety or None,
                arrival_date=row.arrival_date,
                min_price=row.min_price,
                max_price=row.max_price,
                modal_price=row.modal_price,
            )
            for row in latest
        ],
        trend=[
            PricePointOut(date=day, modal_average=round(sum(values) / len(values), 2), markets=len(values))
            for day, values in sorted(by_day.items())
        ],
        data_as_of=newest,
        rows=len(rows),
        source=AGMARKNET_SOURCE,
    )


# --------------------------------------------------------------------------- #
# Exchange rates
# --------------------------------------------------------------------------- #


def _rates(session: Session) -> list[FxRateOut]:
    return [
        FxRateOut(currency=row.currency, inr_per_unit=row.inr_per_unit, source=row.source, as_of=row.as_of)
        for row in session.scalars(select(FxRate).order_by(FxRate.currency))
    ]


def rates(session: Session) -> FxOut:
    return FxOut(rates=_rates(session))


def refresh_rates(session: Session) -> FxOut:
    """Fetch today's ECB reference rates. Hand-entered rates are left alone."""
    try:
        payload = net.get_json(FX_URL, {"base": "INR", "symbols": ",".join(FX_CURRENCIES)})
    except net.NetworkDisabled:
        payload = None
    if not payload or "rates" not in payload:
        return FxOut(rates=_rates(session), refreshed=False, message="offline")

    as_of = _date(payload.get("date")) or date.today()
    for currency, per_inr in payload["rates"].items():
        if not per_inr:
            continue
        row = session.get(FxRate, currency)
        if row is not None and row.source == "manual":
            continue
        if row is None:
            row = FxRate(currency=currency)
            session.add(row)
        # The API answers "units per rupee"; the app thinks in "rupees per unit".
        row.inr_per_unit = round(1 / float(per_inr), 4)
        row.source = FX_SOURCE
        row.as_of = as_of
    session.flush()
    return FxOut(rates=_rates(session), refreshed=True)


def set_manual(session: Session, currency: str, inr_per_unit: float) -> FxOut:
    currency = currency.upper()
    if currency not in FX_CURRENCIES:
        raise PriceError(f"Rates are kept for {', '.join(FX_CURRENCIES)}.", 422)
    row = session.get(FxRate, currency) or FxRate(currency=currency)
    row.inr_per_unit = inr_per_unit
    row.source = "manual"
    row.as_of = date.today()
    session.merge(row)
    session.flush()
    return FxOut(rates=_rates(session))


def clear_manual(session: Session, currency: str) -> FxOut:
    row = session.get(FxRate, currency.upper())
    if row is not None and row.source == "manual":
        session.delete(row)
        session.flush()
    return FxOut(rates=_rates(session))
