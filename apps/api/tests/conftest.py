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
# Generated reports go to the same throwaway directory, so a suite run never
# leaves PDFs beside a developer's real ones.
os.environ["VG_REPORTS_DIR"] = str(_TEST_DIR / "reports")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.db import init_db, session_scope  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AppEvent,
    Deal,
    DiaryEntry,
    Dispute,
    EquipmentEnquiry,
    EquipmentListing,
    EquipmentPartnership,
    Farmer,
    FarmerGroup,
    FxRate,
    InsurancePolicy,
    MandiPrice,
    MediaFile,
    Message,
    Notification,
    Rating,
    SchemeApplication,
    SyncSetting,
    WeatherCache,
    InvestmentInterest,
    InvestmentRequest,
    LandParcel,
    Profile,
    ProjectReport,
    SyncQueueEntry,
)


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
        # Newer platform tables first: they point at everything else.
        for model in (
            Message,
            Notification,
            Dispute,
            Rating,
            Deal,
            DiaryEntry,
            WeatherCache,
            MandiPrice,
            FxRate,
            SchemeApplication,
            SyncSetting,
        ):
            session.execute(delete(model))
        session.execute(delete(InvestmentRequest).where(InvestmentRequest.group_id.is_not(None)))
        session.execute(delete(FarmerGroup))
        # The marketplace hangs off profiles, parcels and reports.
        session.execute(delete(MediaFile))
        session.execute(delete(EquipmentEnquiry))
        session.execute(delete(EquipmentPartnership))
        session.execute(delete(EquipmentListing))
        session.execute(delete(InsurancePolicy))
        session.execute(delete(InvestmentInterest))
        session.execute(delete(InvestmentRequest))
        session.execute(delete(Profile))
        # Reports hang off a parcel, so they go first.
        session.execute(delete(ProjectReport))
        session.execute(delete(LandParcel))
        session.execute(delete(Farmer))


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def become(profile_id: str) -> None:
    """Make ``profile_id`` the device owner.

    One device is one person, so a test of a two-sided flow (a deal, a group
    join) takes turns being each side -- as two devices would, through sync.
    """
    from app.models import Profile

    with session_scope() as session:
        for profile in session.query(Profile).filter(Profile.is_device_owner.is_(True)):
            profile.is_device_owner = False
        session.flush()
        session.get(Profile, profile_id).is_device_owner = True


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


@pytest.fixture()
def parcel_id(client, parcel_payload) -> str:
    """A saved parcel, for the tests that start from one existing."""
    response = client.post("/api/v1/land-parcels", json=parcel_payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture()
def land_profile():
    """Build a LandProfile without going through the database.

    The scoring engine deliberately knows nothing about SQLAlchemy, so most of
    its tests should not need a parcel row either.
    """
    from app.services.opportunities import LandProfile

    def build(**overrides):
        defaults = dict(
            area_hectares=1.2,
            state_code=UP,
            soil_type="alluvial",
            water_sources=("borewell",),
            water_type="sweet",
            water_depth_metres=27.0,
            irrigation_type="drip",
            existing_crops=("wheat", "rice"),
        )
        defaults.update(overrides)
        return LandProfile(**defaults)

    return build


@pytest.fixture()
def labels():
    """The name resolver the engine expects, without a database session."""

    def resolve(list_key: str, code: str | None) -> str:
        return code or "not stated"

    return resolve


@pytest.fixture()
def db_session():
    """A plain session, for services that take one directly."""
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
