"""The few calls that leave the device: weather, exchange rates, mandi prices.

Each one fails quietly. The app works with the radio off, so an unreachable
service is an ordinary state -- the caller shows the last cached answer and
says how old it is -- never an error screen. VG_ALLOW_NETWORK=false forbids
all of them outright.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..config import get_settings

logger = logging.getLogger("viksitgaanw.net")

USER_AGENT = "ViksitGaanw/0.1 (offline-first farm planning; contact via project repository)"


class NetworkDisabled(RuntimeError):
    """The device is configured not to use the network."""


def get_json(url: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any | None:
    """GET ``url`` and parse JSON, or return None if anything goes wrong."""
    settings = get_settings()
    if not settings.allow_network:
        raise NetworkDisabled("Network access is switched off on this device.")
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout or settings.network_timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        logger.info("Network call failed for %s: %s", url.split("?")[0], error)
        return None
