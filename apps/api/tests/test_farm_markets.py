"""Farm diary and traceability, weather, mandi prices, exchange rates, schemes."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.db import session_scope
from app.models import WeatherCache
from app.services import net

from .test_marketplace import make_owner
from .test_profiles import farmer_body, investor_india_body, partner_national_body

TODAY = date.today()


def entry(**overrides) -> dict:
    body = {"activity": "sowing", "entryDate": (TODAY - timedelta(days=90)).isoformat(), "crop": "tomato"}
    body.update(overrides)
    return body


# --------------------------------------------------------------------------- #
# Diary
# --------------------------------------------------------------------------- #


def test_diary_and_harvest_lots(client, parcel_id):
    make_owner(client, farmer_body())
    base = f"/api/v1/land-parcels/{parcel_id}/diary"
    assert client.post(base, json=entry()).status_code == 201
    spray = client.post(
        base,
        json=entry(activity="spray", entryDate=(TODAY - timedelta(days=5)).isoformat(),
                   product="Imidacloprid 17.8 SL", dose="0.3 ml/litre", preHarvestDays=7, amount=450),
    ).json()
    assert spray["safeToHarvestOn"] == (TODAY + timedelta(days=2)).isoformat()

    harvest = client.post(
        base, json=entry(activity="harvest", entryDate=TODAY.isoformat(), quantity=12, unit="quintal")
    ).json()
    assert harvest["lotCode"].startswith(f"LOT-{TODAY:%Y%m%d}-")
    assert harvest["phiWarnings"] and "Imidacloprid" in harvest["phiWarnings"][0]

    client.post(base, json=entry(activity="sale", entryDate=TODAY.isoformat(), amount=18000))
    summary = client.get(f"{base}/summary").json()
    assert summary["entries"] == 4 and summary["spent"] == 450 and summary["received"] == 18000
    assert summary["notSafeToHarvest"] == ["tomato"]

    pdf = client.get(f"/api/v1/diary/{harvest['id']}/traceability.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    not_harvest = client.get(f"/api/v1/diary/{spray['id']}/traceability.pdf")
    assert not_harvest.status_code == 422


def test_diary_rules(client, parcel_id):
    make_owner(client, farmer_body())
    base = f"/api/v1/land-parcels/{parcel_id}/diary"
    future = client.post(base, json=entry(entryDate=(TODAY + timedelta(days=3)).isoformat()))
    assert future.status_code == 422
    no_crop = client.post(base, json=entry(activity="harvest", crop=None))
    assert no_crop.status_code == 422
    # A waiting period only means something on a spray.
    sowing = client.post(base, json=entry(preHarvestDays=10)).json()
    assert sowing["preHarvestDays"] is None


# --------------------------------------------------------------------------- #
# Weather
# --------------------------------------------------------------------------- #


FORECAST = {
    "daily": {
        "time": [(TODAY + timedelta(days=i)).isoformat() for i in range(7)],
        "temperature_2m_max": [36, 41, 35, 34, 33, 33, 32],
        "temperature_2m_min": [24, 26, 25, 3, 22, 22, 21],
        "precipitation_sum": [0, 12, 0, 0, 60, 0, 0],
        "precipitation_probability_max": [5, 80, 10, 10, 90, 10, 5],
        "wind_speed_10m_max": [18, 10, 9, 8, 30, 10, 10],
    }
}


def test_weather_forecast_advisories_and_offline_cache(client, parcel_id, monkeypatch):
    make_owner(client, farmer_body())
    calls = []
    monkeypatch.setattr("app.services.weather._fetch", lambda lat, lon: calls.append((lat, lon)) or FORECAST)
    body = client.get(f"/api/v1/land-parcels/{parcel_id}/weather").json()
    assert body["available"] and body["basis"] == "state" and len(body["days"]) == 7
    codes = {(a["code"], a["day"]) for a in body["advisories"]}
    assert ("no_spray_wind", TODAY.isoformat()) in codes
    assert ("no_spray_rain", (TODAY + timedelta(days=1)).isoformat()) in codes
    assert ("heat", (TODAY + timedelta(days=1)).isoformat()) in codes
    assert ("frost", (TODAY + timedelta(days=3)).isoformat()) in codes
    assert ("heavy_rain", (TODAY + timedelta(days=4)).isoformat()) in codes
    alerts = [n for n in client.get("/api/v1/notifications").json() if n["kind"] == "weather_alert"]
    assert alerts, "alerts reach the inbox"

    # Offline: the cached forecast is shown, marked stale once old.
    monkeypatch.setattr("app.services.weather._fetch", lambda lat, lon: None)
    with session_scope() as session:
        row = session.query(WeatherCache).one()
        row.fetched_at = datetime.now(timezone.utc) - timedelta(hours=10)
    offline = client.get(f"/api/v1/land-parcels/{parcel_id}/weather").json()
    assert offline["available"] and offline["stale"] is True
    assert len(calls) == 1


def test_weather_without_any_data(client, parcel_id, monkeypatch):
    make_owner(client, farmer_body())
    monkeypatch.setattr("app.services.weather._fetch", lambda lat, lon: None)
    body = client.get(f"/api/v1/land-parcels/{parcel_id}/weather").json()
    assert body["available"] is False and body["message"] == "offline"


# --------------------------------------------------------------------------- #
# Mandi prices
# --------------------------------------------------------------------------- #


def price_csv(day: date, onion_up: float = 1800, onion_mh: float = 1500) -> str:
    stamp = day.strftime("%d/%m/%Y")
    return (
        "State,District,Market,Commodity,Variety,Grade,Arrival_Date,Min_Price,Max_Price,Modal_Price\n"
        f"Uttar Pradesh,Varanasi,Varanasi,Onion,Red,FAQ,{stamp},1600,2000,{onion_up}\n"
        f"Maharashtra,Nashik,Lasalgaon,Onion,Red,FAQ,{stamp},1300,1700,{onion_mh}\n"
        f"Uttar Pradesh,Varanasi,Varanasi,Paddy(Dhan)(Common),Common,FAQ,{stamp},2100,2300,2200\n"
        f"Uttar Pradesh,Varanasi,Varanasi,Onion,Red,FAQ,not-a-date,1,2,3\n"
    )


def test_price_import_is_idempotent_and_state_first(client):
    make_owner(client, farmer_body())
    first = client.post("/api/v1/prices/import", content=price_csv(TODAY - timedelta(days=1)))
    assert first.json() == {"imported": 3}, "the bad row is skipped"
    client.post("/api/v1/prices/import", content=price_csv(TODAY - timedelta(days=1), onion_up=1900))
    client.post("/api/v1/prices/import", content=price_csv(TODAY, onion_up=2100))

    onion = client.get("/api/v1/prices/onion").json()
    assert onion["rows"] == 4, "re-importing a day replaces it"
    assert onion["latest"][0]["stateName"] == "Uttar Pradesh"
    assert onion["latest"][0]["modalPrice"] == 2100
    assert [p["modalAverage"] for p in onion["trend"]] == [1900, 2100]
    assert client.get("/api/v1/prices/rice").json()["latest"][0]["commodity"].startswith("Paddy")
    assert client.get("/api/v1/prices/tea").json()["rows"] == 0


def test_price_fetch_needs_a_key(client):
    make_owner(client, farmer_body())
    response = client.post("/api/v1/prices/fetch")
    assert response.status_code == 422
    assert "API key" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Exchange rates
# --------------------------------------------------------------------------- #


def test_exchange_rates_refresh_and_manual_override(client, monkeypatch):
    make_owner(client, investor_india_body())
    monkeypatch.setattr(
        net, "get_json",
        lambda url, params=None, timeout=None: {"date": "2026-09-09", "rates": {"USD": 0.0114, "EUR": 0.0102, "GBP": 0.0086}},
    )
    rates = {r["currency"]: r for r in client.post("/api/v1/fx/refresh").json()["rates"]}
    assert rates["USD"]["inrPerUnit"] == pytest.approx(87.7193, rel=1e-3)
    assert rates["USD"]["asOf"] == "2026-09-09"

    client.put("/api/v1/fx/USD", json={"inrPerUnit": 90})
    rates = {r["currency"]: r for r in client.post("/api/v1/fx/refresh").json()["rates"]}
    assert rates["USD"]["inrPerUnit"] == 90 and rates["USD"]["source"] == "manual"
    assert client.put("/api/v1/fx/XYZ", json={"inrPerUnit": 1}).status_code == 422

    monkeypatch.setattr(net, "get_json", lambda url, params=None, timeout=None: None)
    offline = client.post("/api/v1/fx/refresh").json()
    assert offline["refreshed"] is False and len(offline["rates"]) == 3


# --------------------------------------------------------------------------- #
# Schemes
# --------------------------------------------------------------------------- #


def schemes_by_code(client) -> dict:
    return {item["code"]: item for item in client.get("/api/v1/schemes").json()}


def test_scheme_eligibility_for_a_small_farmer(client, parcel_id):
    make_owner(client, farmer_body())
    schemes = schemes_by_code(client)
    # The fixture plot: 2.5 bigha owned, borewell and canal, flood irrigation.
    assert schemes["pm_kisan"]["status"] == "likely"
    assert schemes["pm_kmy"]["status"] == "likely", "well under 2 hectares"
    assert schemes["pmksy_pdmc"]["status"] == "likely"
    assert schemes["kcc"]["status"] == "unlikely", "the profile says a KCC is already held"
    assert "already_has" in schemes["kcc"]["reasons"]
    assert schemes["fpo_scheme"]["status"] == "unlikely"
    assert schemes["pm_kisan"]["cannotCheck"]["en"]


def test_scheme_eligibility_depends_on_tenure_and_size(client, parcel_id):
    make_owner(client, farmer_body())
    client.patch(f"/api/v1/land-parcels/{parcel_id}", json={"ownershipType": "leased", "areaValue": 12, "areaUnit": "acre"})
    schemes = schemes_by_code(client)
    assert schemes["pm_kisan"]["status"] == "unlikely" and "ownership" in schemes["pm_kisan"]["reasons"]
    assert schemes["pm_kmy"]["status"] == "unlikely" and "land_size" in schemes["pm_kmy"]["reasons"]
    assert schemes["pmfby"]["status"] == "likely", "tenants can take crop insurance"


def test_schemes_for_organisations_and_investors(client):
    make_owner(client, partner_national_body())
    schemes = schemes_by_code(client)
    assert schemes["fpo_scheme"]["status"] == "likely"
    assert schemes["pm_kisan"]["status"] == "unlikely"
    client.delete("/api/v1/profile")
    make_owner(client, investor_india_body())
    assert all(item["status"] == "unlikely" for item in client.get("/api/v1/schemes").json())


def test_scheme_application_tracker(client, parcel_id):
    make_owner(client, farmer_body())
    response = client.put(
        "/api/v1/schemes/pm_kisan/application",
        json={"status": "documents_ready", "documentsReady": ["aadhaar", "land_record"]},
    )
    assert response.status_code == 200, response.text
    first = client.get("/api/v1/schemes").json()[0]
    assert first["code"] == "pm_kisan" and first["application"]["status"] == "documents_ready"

    wrong = client.put("/api/v1/schemes/pm_kisan/application", json={"documentsReady": ["passport"]})
    assert wrong.status_code == 422
    assert client.delete("/api/v1/schemes/pm_kisan/application").status_code == 204
    assert client.put("/api/v1/schemes/nope/application", json={}).status_code == 404
