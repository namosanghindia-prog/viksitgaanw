"""Seven-day forecast for a plot, and the advice that follows from it.

Forecasts come from Open-Meteo (free, no key, attribution required). The last
answer for each spot is kept, so a device that goes offline still shows the
forecast it last had -- marked with its age -- rather than nothing.

The advisories are the handful a farmer acts on this week: do not spray
before rain or in wind, get ready for heavy rain, protect crops and animals
from heat or frost, and irrigate through a dry spell.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import LandParcel, WeatherCache
from ..schemas import AdvisoryOut, WeatherDayOut, WeatherOut
from . import net

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SOURCE = "Open-Meteo"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"
#: Refetch after this long; older answers are shown as stale.
FRESH_FOR = timedelta(hours=3)

# Thresholds, in the units the forecast uses.
RAIN_NO_SPRAY_MM = 5.0
HEAVY_RAIN_MM = 50.0
WIND_NO_SPRAY_KMH = 15.0
HEAT_C = 40.0
FROST_C = 4.0
DRY_DAYS = 6


@lru_cache(maxsize=1)
def _centroids() -> dict:
    path: Path = get_settings().knowledge_dir / "admin-centroids.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle).get("states", {})


def position(parcel: LandParcel) -> tuple[float, float, str] | None:
    """The plot's pin, or its state's centre when no pin was dropped."""
    if parcel.latitude is not None and parcel.longitude is not None:
        return parcel.latitude, parcel.longitude, "pin"
    centre = _centroids().get(parcel.state_code)
    if centre and "lat" in centre and "lon" in centre:
        return float(centre["lat"]), float(centre["lon"]), "state"
    return None


def _key(lat: float, lon: float) -> str:
    # 0.05 degrees is about 5 km: plots in one village share a forecast.
    return f"{round(lat * 20) / 20:.2f},{round(lon * 20) / 20:.2f}"


def _fetch(lat: float, lon: float) -> dict | None:
    return net.get_json(
        FORECAST_URL,
        {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,"
            "precipitation_probability_max,wind_speed_10m_max",
            "timezone": "auto",
            "forecast_days": 7,
        },
    )


def _days(payload: dict) -> list[WeatherDayOut]:
    daily = payload.get("daily") or {}
    days = daily.get("time") or []

    def pick(name: str, index: int) -> float | None:
        values = daily.get(name) or []
        return values[index] if index < len(values) else None

    return [
        WeatherDayOut(
            date=date.fromisoformat(day),
            temp_max=pick("temperature_2m_max", i),
            temp_min=pick("temperature_2m_min", i),
            rain_mm=pick("precipitation_sum", i),
            rain_chance=pick("precipitation_probability_max", i),
            wind_max_kmh=pick("wind_speed_10m_max", i),
        )
        for i, day in enumerate(days)
    ]


def advisories(days: list[WeatherDayOut], today: date | None = None) -> list[AdvisoryOut]:
    today = today or date.today()
    out: list[AdvisoryOut] = []
    upcoming = [day for day in days if day.date >= today]
    for index, day in enumerate(upcoming):
        rain = day.rain_mm or 0.0
        if rain >= HEAVY_RAIN_MM:
            out.append(AdvisoryOut(code="heavy_rain", severity="alert", day=day.date, value=rain))
        # Spraying the day before rain washes it off; only the next two days matter.
        if index < 2 and rain >= RAIN_NO_SPRAY_MM:
            out.append(AdvisoryOut(code="no_spray_rain", severity="warn", day=day.date, value=rain))
        if index < 2 and (day.wind_max_kmh or 0) >= WIND_NO_SPRAY_KMH:
            out.append(AdvisoryOut(code="no_spray_wind", severity="warn", day=day.date, value=day.wind_max_kmh))
        if day.temp_max is not None and day.temp_max >= HEAT_C:
            out.append(AdvisoryOut(code="heat", severity="alert", day=day.date, value=day.temp_max))
        if day.temp_min is not None and day.temp_min <= FROST_C:
            out.append(AdvisoryOut(code="frost", severity="alert", day=day.date, value=day.temp_min))
    dry = [day for day in upcoming if (day.rain_mm or 0) < 1]
    if len(upcoming) >= DRY_DAYS and len(dry) >= DRY_DAYS:
        out.append(AdvisoryOut(code="dry_spell", severity="info", day=upcoming[0].date, value=float(len(dry))))
    return out


def forecast(session: Session, parcel: LandParcel, *, refresh: bool = False) -> WeatherOut:
    where = position(parcel)
    if where is None:
        return WeatherOut(available=False, message="no_position")
    lat, lon, basis = where
    key = _key(lat, lon)
    cached = session.get(WeatherCache, key)
    now = datetime.now(timezone.utc)

    def age(row: WeatherCache) -> timedelta:
        fetched = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=timezone.utc)
        return now - fetched

    if cached is None or refresh or age(cached) > FRESH_FOR:
        try:
            payload = _fetch(lat, lon)
        except net.NetworkDisabled:
            payload = None
        if payload and payload.get("daily"):
            if cached is None:
                cached = WeatherCache(key=key, latitude=lat, longitude=lon, source=SOURCE)
                session.add(cached)
            cached.payload = payload
            cached.fetched_at = now
            session.flush()

    if cached is None:
        return WeatherOut(available=False, latitude=lat, longitude=lon, basis=basis, message="offline")

    days = _days(cached.payload)
    return WeatherOut(
        available=True,
        latitude=lat,
        longitude=lon,
        basis=basis,
        days=days,
        advisories=advisories(days),
        fetched_at=cached.fetched_at,
        stale=age(cached) > FRESH_FOR,
        source=SOURCE,
        attribution=ATTRIBUTION,
    )
