"""Test fixtures.

The database path is redirected to a temp directory *before* ``app`` is
imported, because the SQLAlchemy engine is built at import time from settings.
A developer running the suite must never touch their real local farm data.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]

sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

_TEST_DIR = Path(tempfile.mkdtemp(prefix="viksitgaanw-tests-"))
os.environ["VG_DB_PATH"] = str(_TEST_DIR / "test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.db import init_db, session_scope  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AppEvent, Farmer, LandParcel, SyncQueueEntry  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded_database() -> None:
    """Create the schema once and load the bundled LGD sample into it."""
    init_db()
    import import_lgd

    import_lgd.main(["--sample", "--replace", "--quiet"])


@pytest.fixture(autouse=True)
def clean_user_data() -> None:
    """Reset user-owned tables between tests; reference data is left alone."""
    yield
    with session_scope() as session:
        session.execute(delete(SyncQueueEntry))
        session.execute(delete(AppEvent))
        session.execute(delete(LandParcel))
        session.execute(delete(Farmer))


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# Codes from the bundled sample (see scripts/generate_sample_lgd.py).
UP = "9"
VARANASI = "990901"
PINDRA = "99090101"
RAMPUR_BUJURG = "9909010103"
NASHIK = "992701"


@pytest.fixture()
def parcel_payload() -> dict:
    return {
        "label": "Ganga side plot",
        "stateCode": UP,
        "districtCode": VARANASI,
        "subdistrictCode": PINDRA,
        "villageCode": RAMPUR_BUJURG,
        "surveyNumber": "123/4",
        "ownershipType": "owned",
        "areaValue": 2.5,
        "areaUnit": "bigha",
        "soilType": "alluvial",
        "waterSources": ["borewell", "canal"],
        "irrigationType": "flood",
        "existingCrops": ["wheat", "rice"],
    }
