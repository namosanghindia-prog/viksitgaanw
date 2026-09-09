"""Additive migrations.

The database sits on the villager's own device and holds the only copy of their
records, next to a ~100 MB LGD import. A schema change must never mean asking
them to start over.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.migrations import ADDITIVE_COLUMNS, apply_additive_migrations


@pytest.fixture()
def legacy_engine(tmp_path: Path):
    """A database as it looked before the water columns existed."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE land_parcels (
                    id VARCHAR(36) PRIMARY KEY,
                    farmer_id VARCHAR(36) NOT NULL,
                    label VARCHAR(160) NOT NULL,
                    state_code VARCHAR(8) NOT NULL,
                    district_code VARCHAR(8) NOT NULL,
                    area_value FLOAT NOT NULL,
                    area_unit VARCHAR(24) NOT NULL,
                    area_hectares FLOAT NOT NULL,
                    sync_state VARCHAR(16) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO land_parcels VALUES "
                "('p1', 'f1', 'Old plot', '9', '640', 2.0, 'acre', 0.809, 'local_only')"
            )
        )
    return engine


def test_missing_columns_are_added(legacy_engine):
    applied = apply_additive_migrations(legacy_engine)

    assert set(applied) == {
        f"land_parcels.{name}" for name in ADDITIVE_COLUMNS["land_parcels"]
    }
    columns = {c["name"] for c in inspect(legacy_engine).get_columns("land_parcels")}
    assert {"water_type", "water_depth_value", "water_depth_unit", "water_depth_metres"} <= columns


def test_existing_rows_survive_the_migration(legacy_engine):
    apply_additive_migrations(legacy_engine)

    with legacy_engine.connect() as connection:
        row = connection.execute(
            text("SELECT label, area_hectares, water_type FROM land_parcels WHERE id = 'p1'")
        ).one()
    assert row.label == "Old plot"
    assert row.area_hectares == 0.809
    assert row.water_type is None


def test_running_twice_changes_nothing(legacy_engine):
    apply_additive_migrations(legacy_engine)
    assert apply_additive_migrations(legacy_engine) == []


def test_a_missing_table_is_left_to_create_all(tmp_path: Path):
    """An empty database is built by create_all, not patched column by column."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    assert apply_additive_migrations(engine) == []
