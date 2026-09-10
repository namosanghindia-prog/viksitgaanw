"""Finding out where the device is, without depending on Google.

The browser's own ``navigator.geolocation`` is the right first choice on a
phone or tablet, and the frontend tries it first. It is *not* reliable inside
the Electron desktop shell: Chromium resolves a position through Google's
network location service, which needs a ``GOOGLE_API_KEY`` compiled into the
build. Electron ships without a usable key, so on a laptop the browser call
fails with POSITION_UNAVAILABLE no matter what permissions are granted. That is
why "use my location" appeared to do nothing on the desktop app.

This module is the answer to that. It asks, in order:

1. **The operating system.** On Windows the platform location service answers
   through ``System.Device.Location``, which needs no key and uses whatever
   the machine actually has -- a GPS radio, or Microsoft's Wi-Fi positioning.
2. **The network.** A keyless IP-geolocation lookup. This is coarse -- it
   often returns the district town where the ISP terminates -- but it is
   enough to open the map in the right part of the country.
3. **The chosen state.** Purely offline: the centroid of the state the farmer
   already picked in the location selector.

Every fix carries its source and an honest accuracy figure, and the UI shows
both, because a farmer must never be led to believe a 25 km IP guess is where
their field is. Dropping the pin by hand remains the authoritative way to mark
a plot; this only saves the farmer from starting that at zoom 4 over the
Arabian Sea.
"""

from __future__ import annotations

import json
import logging
import math
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from ..config import get_settings

logger = logging.getLogger("viksitgaanw.geolocation")

FixSource = Literal["device_gps", "os_location", "network_ip", "admin_centroid"]

#: Sent on every outbound call. The OpenStreetMap Nominatim usage policy
#: requires an identifying agent, and it is simply good manners on the others.
USER_AGENT = "ViksitGaanw/0.1 (offline-first village agri OS; contact via repository)"

#: Keyless IP-geolocation endpoints, tried in order. Both are free for the
#: occasional manual lookup this makes; neither is on a hot path.
_IP_ENDPOINTS = (
    ("https://ipapi.co/json/", ("latitude", "longitude", "city", "region")),
    ("http://ip-api.com/json/", ("lat", "lon", "city", "regionName")),
)

_NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"

#: An IP fix is typically no better than the district town. Say so rather than
#: reporting whatever optimistic radius the service claims.
IP_ACCURACY_METRES = 25_000.0

#: How deep inside a state's box a point must sit before an offline guess is
#: called anything better than "low". Below this it is hugging a border.
_CONFIDENT_DEPTH = 0.08

#: How long the Windows location service is given to produce a fix. A cold GPS
#: can take a while; beyond this the farmer is better served by the fallback.
_OS_TIMEOUT_SECONDS = 12


class GeolocationUnavailable(RuntimeError):
    """No provider could produce a position."""


@dataclass(frozen=True)
class Fix:
    latitude: float
    longitude: float
    accuracy_metres: float | None
    source: FixSource
    #: A short human description of where the fix came from, e.g. a city name.
    label: str | None = None
    #: Attribution required by whichever service answered.
    attribution: str | None = None


# --------------------------------------------------------------------------- #
# Offline: state centroids
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _centroids() -> dict[str, Any]:
    path: Path = get_settings().knowledge_dir / "admin-centroids.json"
    if not path.is_file():
        return {"states": {}, "accuracyMetres": 150_000}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def state_centroid(state_code: str | None) -> Fix | None:
    """The centre of a state, from data that ships with the app."""
    if not state_code:
        return None
    entry = _centroids().get("states", {}).get(str(state_code))
    if not entry:
        return None
    return Fix(
        latitude=float(entry["lat"]),
        longitude=float(entry["lon"]),
        accuracy_metres=float(_centroids().get("accuracyMetres", 150_000)),
        source="admin_centroid",
        label=entry.get("name"),
        attribution="ViksitGaanw offline reference data",
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _box_depth(latitude: float, longitude: float, bbox: list[float]) -> float:
    """How far inside its own box a point sits, as a fraction of the box.

    Bounding boxes for Indian states overlap heavily -- Bengaluru falls inside
    both Karnataka's box and Tamil Nadu's. Distance to the centroid is the
    wrong tie-break there, because a long thin state can have its centre closer
    to a point that is plainly inside its neighbour. How deep the point sits in
    each box, scaled by that box's own size, picks the right one.
    """
    west, south, east, north = bbox
    width, height = east - west, north - south
    if width <= 0 or height <= 0:
        return 0.0
    horizontal = min(longitude - west, east - longitude) / width
    vertical = min(latitude - south, north - latitude) / height
    return min(horizontal, vertical)


def state_for_point(latitude: float, longitude: float) -> tuple[str, str, str] | None:
    """Guess the state a point falls in, entirely offline.

    Returns ``(state_code, state_name, confidence)``. This is a rectangle test
    against hand-entered boxes, not a polygon lookup, so a point near a border
    can be wrong. A caller must present it as a suggestion to confirm and never
    as a determination -- which is what the confidence is for.
    """
    states: dict[str, Any] = _centroids().get("states", {})
    inside: list[tuple[float, str, str]] = []
    nearest: tuple[float, str, str] | None = None

    for code, entry in states.items():
        distance = _haversine_km(latitude, longitude, entry["lat"], entry["lon"])
        if nearest is None or distance < nearest[0]:
            nearest = (distance, code, entry["name"])
        west, south, east, north = entry["bbox"]
        if west <= longitude <= east and south <= latitude <= north:
            inside.append((_box_depth(latitude, longitude, entry["bbox"]), code, entry["name"]))

    if inside:
        inside.sort(reverse=True)
        best = inside[0]
        if len(inside) == 1:
            confidence = "medium"
        else:
            # Worth something only when the point is clearly deeper inside one
            # box *and* not hugging the edge of it. Chennai sits in the corner
            # of both the Tamil Nadu and Andhra Pradesh boxes; that deserves
            # "low", however the arithmetic falls.
            runner_up = inside[1][0]
            clear = best[0] >= runner_up * 1.8
            confidence = "medium" if clear and best[0] >= _CONFIDENT_DEPTH else "low"
        return best[1], best[2], confidence

    if nearest and nearest[0] < 300:
        return nearest[1], nearest[2], "low"
    return None


# --------------------------------------------------------------------------- #
# Operating-system location
# --------------------------------------------------------------------------- #

# Windows PowerShell reaching the platform location service. GeoCoordinateWatcher
# is part of the .NET Framework that ships with Windows, so this needs nothing
# installed and no API key. It returns DENIED when the user or an administrator
# has turned location off, which we surface rather than retrying.
_WINDOWS_LOCATION_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try { Add-Type -AssemblyName System.Device } catch { 'UNAVAILABLE'; exit 0 }
$watcher = New-Object System.Device.Location.GeoCoordinateWatcher('High')
$watcher.Start()
$deadline = (Get-Date).AddSeconds({timeout})
while ($watcher.Status -ne 'Ready' -and (Get-Date) -lt $deadline) {
    if ($watcher.Permission -eq 'Denied') { 'DENIED'; $watcher.Stop(); exit 0 }
    Start-Sleep -Milliseconds 250
}
if ($watcher.Permission -eq 'Denied') { 'DENIED'; $watcher.Stop(); exit 0 }
$location = $watcher.Position.Location
if ($location -eq $null -or $location.IsUnknown) { 'NOFIX'; $watcher.Stop(); exit 0 }
'{0},{1},{2}' -f $location.Latitude, $location.Longitude, $location.HorizontalAccuracy
$watcher.Stop()
"""


def os_fix() -> Fix | None:
    """Ask the operating system where it is. Windows only for now."""
    if sys.platform != "win32":
        # macOS CoreLocation and Linux GeoClue are both reachable, but neither
        # is wired up yet. Returning None keeps the chain honest instead of
        # pretending the platform was asked.
        logger.debug("OS location not implemented for platform %s", sys.platform)
        return None

    script = _WINDOWS_LOCATION_SCRIPT.replace("{timeout}", str(_OS_TIMEOUT_SECONDS))
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=_OS_TIMEOUT_SECONDS + 8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as error:
        logger.info("OS location call failed: %s", error)
        return None

    output = (completed.stdout or "").strip().splitlines()
    answer = output[-1].strip() if output else ""

    if answer in {"", "UNAVAILABLE", "NOFIX"}:
        logger.info("OS location gave no fix (%s)", answer or "empty")
        return None
    if answer == "DENIED":
        logger.info("OS location denied by Windows location settings")
        return None

    try:
        latitude, longitude, accuracy = (part.strip() for part in answer.split(",", 2))
        return Fix(
            latitude=float(latitude),
            longitude=float(longitude),
            accuracy_metres=float(accuracy) if accuracy else None,
            source="os_location",
            label=None,
            attribution="Windows location service",
        )
    except ValueError:
        logger.info("OS location returned something unparseable: %r", answer)
        return None


# --------------------------------------------------------------------------- #
# Network: coarse position from the IP address
# --------------------------------------------------------------------------- #


def _get_json(url: str, timeout: float) -> Any | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        logger.info("Network lookup failed for %s: %s", url, error)
        return None


def network_fix() -> Fix | None:
    """Coarse position from the device's public IP address.

    This leaves the device: the request itself reveals the IP address to the
    service answering it. It only runs when the farmer presses the button and
    the earlier providers came back empty, and never on startup.
    """
    settings = get_settings()
    if not settings.allow_network:
        return None

    for url, (lat_key, lon_key, city_key, region_key) in _IP_ENDPOINTS:
        payload = _get_json(url, settings.network_timeout_seconds)
        if not isinstance(payload, dict):
            continue
        latitude, longitude = payload.get(lat_key), payload.get(lon_key)
        if latitude is None or longitude is None:
            continue
        try:
            latitude, longitude = float(latitude), float(longitude)
        except (TypeError, ValueError):
            continue

        place = ", ".join(
            str(payload[key]) for key in (city_key, region_key) if payload.get(key)
        )
        return Fix(
            latitude=latitude,
            longitude=longitude,
            accuracy_metres=IP_ACCURACY_METRES,
            source="network_ip",
            label=place or None,
            attribution=urllib.parse.urlparse(url).netloc,
        )
    return None


# --------------------------------------------------------------------------- #
# Reverse geocoding a dropped pin
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReversePlace:
    """What a coordinate resolves to, before it is matched against the LGD."""

    state: str | None
    district: str | None
    subdistrict: str | None
    village: str | None
    display_name: str | None
    source: Literal["nominatim", "offline_bbox"]
    confidence: Literal["high", "medium", "low"]
    attribution: str | None = None


def reverse_online(latitude: float, longitude: float) -> ReversePlace | None:
    """Turn a coordinate into place names using OpenStreetMap Nominatim.

    The public Nominatim instance is rate-limited and explicitly not meant for
    production traffic; this is acceptable because it fires once, when a farmer
    presses a button. The project brief already plans a self-hosted instance,
    and only this function's URL changes when that lands.
    """
    settings = get_settings()
    if not settings.allow_network:
        return None

    query = urllib.parse.urlencode(
        {
            "format": "jsonv2",
            "lat": f"{latitude:.6f}",
            "lon": f"{longitude:.6f}",
            "zoom": "14",
            "addressdetails": "1",
            "accept-language": "en",
        }
    )
    payload = _get_json(f"{_NOMINATIM_REVERSE}?{query}", settings.network_timeout_seconds)
    if not isinstance(payload, dict):
        return None

    address = payload.get("address") or {}
    if not address:
        return None

    # Nominatim's Indian coverage puts the district under county or
    # state_district depending on the region, and a village may arrive as
    # village, hamlet or suburb. Take the first that is present.
    def first(*keys: str) -> str | None:
        for key in keys:
            value = address.get(key)
            if value:
                return str(value)
        return None

    return ReversePlace(
        state=first("state"),
        district=first("state_district", "county", "district"),
        subdistrict=first("county", "city_district", "municipality", "town"),
        village=first("village", "hamlet", "suburb", "neighbourhood", "city"),
        display_name=payload.get("display_name"),
        source="nominatim",
        confidence="high",
        attribution="© OpenStreetMap contributors (Nominatim)",
    )


def reverse_offline(latitude: float, longitude: float) -> ReversePlace | None:
    """Best guess from the bundled bounding boxes, with no network at all."""
    guess = state_for_point(latitude, longitude)
    if guess is None:
        return None
    _code, name, confidence = guess
    return ReversePlace(
        state=name,
        district=None,
        subdistrict=None,
        village=None,
        display_name=name,
        source="offline_bbox",
        confidence=confidence,  # type: ignore[arg-type]
        attribution="ViksitGaanw offline reference data",
    )


# --------------------------------------------------------------------------- #
# The chain
# --------------------------------------------------------------------------- #


def locate(*, state_code: str | None = None, allow_network: bool = True) -> Fix:
    """Run every provider in order and return the first fix.

    Raises :class:`GeolocationUnavailable` only when nothing at all worked --
    which, once a state has been chosen, cannot happen.
    """
    fix = os_fix()
    if fix is not None:
        return fix

    if allow_network:
        fix = network_fix()
        if fix is not None:
            return fix

    fix = state_centroid(state_code)
    if fix is not None:
        return fix

    raise GeolocationUnavailable(
        "No position could be found. Choose your state first, or tap the map."
    )
