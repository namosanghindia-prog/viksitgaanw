"""Generating a Detailed Project Report.

The report is the thing a farmer actually takes to a bank, so these tests care
about the properties that survive that trip: that it is a real PDF, that it is
written in the language that was asked for or says plainly that it is not, that
it refuses rather than printing empty boxes, and that generating one is
recorded as an event -- because generated reports are a billable unit and a
count that starts late can never be reconstructed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app import knowledge
from app.db import session_scope
from app.models import AppEvent, ProjectReport
from app.services import fonts as font_service
from app.services.events import EventType

PDF_MAGIC = b"%PDF-"


@pytest.fixture()
def report_request() -> dict:
    return {
        "opportunityCode": "guava_meadow",
        "language": "en",
        "promoterName": "Ram Prasad Yadav",
        "promoterPhone": "9876543210",
    }


# --------------------------------------------------------------------------- #
# The language list
# --------------------------------------------------------------------------- #


def test_every_scheduled_language_is_offered(client):
    body = client.get("/api/v1/report-languages", params={"lang": "en"}).json()
    codes = {entry["code"] for entry in body}
    # The twenty-two languages of the Eighth Schedule, plus English.
    assert len(codes) == 23
    assert {"hi", "en", "ta", "ml", "or", "as", "sat", "ks"} <= codes


def test_the_list_says_which_languages_can_actually_be_printed(client):
    body = client.get("/api/v1/report-languages", params={"lang": "en"}).json()
    for entry in body:
        assert isinstance(entry["fontAvailable"], bool)
        if not entry["fontAvailable"]:
            # Not just "no": the exact command that fixes it.
            assert "fetch_fonts" in (entry["fontHint"] or "")


def test_printable_languages_are_listed_first(client):
    body = client.get("/api/v1/report-languages", params={"lang": "en"}).json()
    available = [entry["fontAvailable"] for entry in body]
    assert available == sorted(available, reverse=True)


def test_coverage_is_reported_honestly(client):
    body = client.get("/api/v1/report-languages", params={"lang": "en"}).json()
    coverage = {entry["code"]: entry["coverage"] for entry in body}
    assert coverage["en"] == pytest.approx(1.0)
    assert coverage["hi"] == pytest.approx(1.0)
    for value in coverage.values():
        assert 0.0 <= value <= 1.0


# --------------------------------------------------------------------------- #
# Generating one
# --------------------------------------------------------------------------- #


def test_a_report_is_a_real_pdf_that_can_be_downloaded(client, parcel_id, report_request):
    created = client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request)
    assert created.status_code == 201, created.text
    body = created.json()

    assert body["reportNumber"].startswith("VG-")
    assert body["fileSize"] > 10_000
    assert body["totalProjectCost"] > 0
    assert body["termLoan"] > 0

    download = client.get(body["downloadPath"].replace("/reports", "/api/v1/reports", 1))
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(PDF_MAGIC)


def test_report_numbers_do_not_repeat(client, parcel_id, report_request):
    first = client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request).json()
    second = client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request).json()
    assert first["reportNumber"] != second["reportNumber"]


def test_generating_a_report_is_recorded_as_an_event(client, parcel_id, report_request):
    """The business model meters this, so the count starts on day one."""
    client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request)

    with session_scope() as session:
        events = session.scalars(
            select(AppEvent).where(AppEvent.event_type == EventType.REPORT_GENERATED)
        ).all()
        assert len(events) == 1
        assert events[0].payload["opportunity_code"] == "guava_meadow"
        assert events[0].payload["language"] == "en"


def test_a_report_is_queued_for_the_eventual_cloud_sync(client, parcel_id, report_request):
    from app.models import SyncQueueEntry

    client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request)
    with session_scope() as session:
        queued = session.scalars(
            select(SyncQueueEntry).where(SyncQueueEntry.entity_type == "project_report")
        ).all()
        assert len(queued) == 1
        assert queued[0].operation == "create"


@pytest.mark.parametrize("language", ["en", "hi"])
def test_the_fully_translated_languages_report_full_coverage(
    client, parcel_id, report_request, language
):
    report_request["language"] = language
    body = client.post(
        f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request
    ).json()
    assert body["translationCoverage"] == pytest.approx(1.0)


def _untranslated_language() -> str:
    """A language with no catalogue yet, so this test survives one being added."""
    for entry in knowledge.load_languages()["items"]:
        code = entry["code"]
        if knowledge.catalogue_coverage(code) == 0.0 and font_service.is_available(
            entry["script"]
        ):
            return code
    raise AssertionError("every printable language is now translated — delete this test")


def test_an_untranslated_language_still_produces_a_report_and_says_so(
    client, parcel_id, report_request
):
    """A farmer gets a usable English report, not a failure and not a lie."""
    language = _untranslated_language()
    report_request["language"] = language
    response = client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request)
    assert response.status_code == 201
    body = response.json()
    assert body["language"] == language
    assert body["translationCoverage"] < 1.0


@pytest.mark.parametrize("language", ["mr", "ta"])
def test_a_fully_translated_language_reports_full_coverage(
    client, parcel_id, report_request, language
):
    """Coverage counts option names and summaries too, not only the headings.

    A language with the headings alone still produces a report half in English,
    so claiming 100% for it would defeat the point of the figure.
    """
    report_request["language"] = language
    body = client.post(
        f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request
    ).json()
    assert body["translationCoverage"] == pytest.approx(1.0)


def test_loan_terms_change_the_numbers(client, parcel_id, report_request):
    light = client.post(
        f"/api/v1/land-parcels/{parcel_id}/reports",
        json={**report_request, "margin": 0.15},
    ).json()
    heavy = client.post(
        f"/api/v1/land-parcels/{parcel_id}/reports",
        json={**report_request, "margin": 0.50},
    ).json()
    assert heavy["termLoan"] < light["termLoan"]


# --------------------------------------------------------------------------- #
# Refusing rather than producing rubbish
# --------------------------------------------------------------------------- #


def test_a_language_with_no_font_is_refused_with_the_fix(
    client, parcel_id, report_request, monkeypatch
):
    """Empty boxes on a bank document would be worse than an error."""
    monkeypatch.setattr(font_service, "is_available", lambda _script: False)
    report_request["language"] = "sat"
    response = client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request)
    assert response.status_code == 503
    assert "fetch_fonts" in response.json()["detail"]


def test_an_unknown_option_is_rejected(client, parcel_id, report_request):
    report_request["opportunityCode"] = "moon_farming"
    response = client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request)
    assert response.status_code == 422


def test_an_unknown_language_is_rejected(client, parcel_id, report_request):
    report_request["language"] = "xx"
    response = client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request)
    assert response.status_code == 422


def test_a_report_for_a_missing_parcel_is_a_404(client, report_request):
    response = client.post("/api/v1/land-parcels/does-not-exist/reports", json=report_request)
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Listing and removing
# --------------------------------------------------------------------------- #


def test_reports_are_listed_newest_first(client, parcel_id, report_request):
    client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request)
    client.post(
        f"/api/v1/land-parcels/{parcel_id}/reports",
        json={**report_request, "opportunityCode": "acid_lime"},
    )
    listed = client.get(f"/api/v1/land-parcels/{parcel_id}/reports", params={"lang": "en"}).json()
    assert [entry["opportunityCode"] for entry in listed] == ["acid_lime", "guava_meadow"]


def test_deleting_a_report_removes_the_file_too(client, parcel_id, report_request):
    from pathlib import Path

    body = client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request).json()
    with session_scope() as session:
        path = Path(session.get(ProjectReport, body["id"]).file_path)
    assert path.is_file()

    assert client.delete(f"/api/v1/reports/{body['id']}").status_code == 204
    assert not path.is_file()


def test_a_report_whose_file_has_gone_says_so(client, parcel_id, report_request):
    """A farmer who deleted the PDF by hand needs to be told to make it again."""
    from pathlib import Path

    body = client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request).json()
    with session_scope() as session:
        Path(session.get(ProjectReport, body["id"]).file_path).unlink()

    response = client.get(f"/api/v1/reports/{body['id']}/file")
    assert response.status_code == 410


def test_deleting_a_parcel_takes_its_reports_with_it(client, parcel_id, report_request):
    client.post(f"/api/v1/land-parcels/{parcel_id}/reports", json=report_request)
    client.delete(f"/api/v1/land-parcels/{parcel_id}")
    with session_scope() as session:
        assert session.scalars(select(ProjectReport)).all() == []


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #


def test_every_script_the_app_offers_has_a_font_mapping():
    """A language offered with no route to a font would be a broken promise."""
    for entry in knowledge.load_languages()["items"]:
        assert entry["script"] in font_service.NOTO_FAMILY, entry["code"]
