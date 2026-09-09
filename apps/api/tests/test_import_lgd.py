"""Importer behaviour that only shows up on a real-sized dump.

The bundled sample is 72 villages, which fits inside a single write batch. The
real LGD village file is ~677,000 rows, so these tests shrink the batch size
instead of shipping a huge fixture.
"""

from __future__ import annotations

import csv

import import_lgd
import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import District, State, SubDistrict, Village

SAMPLE_VILLAGES = import_lgd.SAMPLE_DIR / "02-villages.csv"


@pytest.fixture()
def restore_hierarchy():
    """These tests rewrite the shared hierarchy, so put the sample back after."""
    yield
    import_lgd.main(["--sample", "--replace", "--quiet"])


def test_village_only_import_backfills_every_parent_level(restore_hierarchy):
    """The documented single-file path: one village CSV, four tables filled."""
    import_lgd.main(["--source", str(SAMPLE_VILLAGES), "--replace", "--quiet"])

    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(State)) == 3
        assert session.scalar(select(func.count()).select_from(District)) == 6
        assert session.scalar(select(func.count()).select_from(SubDistrict)) == 12
        assert session.scalar(select(func.count()).select_from(Village)) == 72


def test_children_are_never_written_before_their_parents(monkeypatch, restore_hierarchy):
    """Regression: a batch flush used to write only the level that triggered it.

    Once a village file exceeded the batch size, villages could be inserted
    while their sub-district was still queued in memory, tripping the foreign
    key. It stayed hidden because the 72-row sample never fills a batch.
    """
    monkeypatch.setattr(import_lgd, "BATCH_SIZE", 5)

    import_lgd.main(["--source", str(SAMPLE_VILLAGES), "--replace", "--quiet"])

    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(Village)) == 72
        # Every village resolves to a real sub-district, district and state.
        orphans = session.execute(
            select(func.count())
            .select_from(Village)
            .outerjoin(SubDistrict, Village.subdistrict_code == SubDistrict.code)
            .where(SubDistrict.code.is_(None))
        ).scalar()
        assert orphans == 0


def test_reimport_updates_rows_rather_than_duplicating(restore_hierarchy):
    import_lgd.main(["--source", str(SAMPLE_VILLAGES), "--replace", "--quiet"])
    import_lgd.main(["--source", str(SAMPLE_VILLAGES), "--quiet"])

    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(Village)) == 72


def test_a_bare_census_column_binds_to_the_deepest_level(tmp_path):
    """Per-level LGD files label it "Census 2011 Code" with no level prefix."""
    path = tmp_path / "districts.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "State Code",
                "State Name (In English)",
                "District Code",
                "District Name(In English)",
                "Census 2011 Code",
            ]
        )
        writer.writerow(["09", "Uttar Pradesh", "640", "Varanasi", "182"])

    with path.open(encoding="utf-8", newline="") as handle:
        fieldnames = csv.DictReader(handle).fieldnames

    mapping = import_lgd.map_columns(list(fieldnames))
    assert import_lgd.detect_level(mapping) == "district"
    assert mapping["district_census"] == "Census 2011 Code"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("09", "9"),
        (" 9 ", "9"),
        ("9.0", "9"),
        ("", None),
        ("NA", None),
        ("Not Available", "Not Available"),
    ],
)
def test_codes_are_canonicalised(raw, expected):
    """Codes from different exports must join to each other."""
    assert import_lgd.clean_code(raw) == expected


@pytest.mark.parametrize(
    ("header", "field"),
    [
        ("Sub-District Code", "subdistrict_code"),
        ("Sub District Code", "subdistrict_code"),
        ("Sub-district Code", "subdistrict_code"),
        ("Village Name (In English)", "village_name"),
        ("Village Name(In English)", "village_name"),
        ("District Name(In English)", "district_name"),
    ],
)
def test_header_spellings_resolve_to_the_same_field(header, field):
    """LGD exports are not consistent between downloads."""
    mapping = map_of(header)
    assert mapping.get(field) == header


def map_of(header: str) -> dict[str, str]:
    """Map `header` alongside just enough context for detect_level to work.

    Padding columns whose normalised form collides with the header under test
    are dropped, so the test asserts against the spelling it actually passed.
    """
    fields = [header]
    seen = {import_lgd.normalise_header(header)}
    for padding in ("Village Code", "Village Name (In English)"):
        key = import_lgd.normalise_header(padding)
        if key not in seen:
            seen.add(key)
            fields.append(padding)
    return import_lgd.map_columns(fields)
