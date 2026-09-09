"""Health and reference endpoints.

The Electron shell polls ``/health`` while booting to know when the local
backend is ready, and the UI uses ``lgdLoaded`` to tell the user to run the
data import instead of showing an empty, confusing location selector.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import reference as reference_data
from ..config import get_settings
from ..db import get_session
from ..models import District, LandParcel, State, SubDistrict, Village
from ..schemas import DatabaseHealth, HealthOut, ReferenceOut

router = APIRouter(tags=["system"])

_COUNTED = {
    "states": State,
    "districts": District,
    "subdistricts": SubDistrict,
    "villages": Village,
    "land_parcels": LandParcel,
}


@router.get("/health", response_model=HealthOut)
def health(session: Session = Depends(get_session)) -> HealthOut:
    settings = get_settings()
    counts: dict[str, int] = {}
    ready = True
    try:
        for name, model in _COUNTED.items():
            counts[name] = session.scalar(select(func.count()).select_from(model)) or 0
    except Exception:
        # A missing table means the schema was never created. Report it rather
        # than returning a 500: the shell needs an answer to act on.
        ready = False

    lgd_loaded = counts.get("states", 0) > 0 and counts.get("districts", 0) > 0

    return HealthOut(
        status="ok" if ready and lgd_loaded else "degraded",
        version=settings.version,
        database=DatabaseHealth(
            path=str(settings.db_path),
            ready=ready,
            lgd_loaded=lgd_loaded,
            counts=counts,
        ),
    )


@router.get("/reference", response_model=ReferenceOut)
def get_reference() -> ReferenceOut:
    """Serve the shared bilingual reference lists.

    The desktop app bundles the same JSON at build time; this endpoint exists
    so other clients (and the eventual mobile shell) do not need their own copy.
    """
    return ReferenceOut(lists=reference_data.load_all())
