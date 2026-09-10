"""Additive schema migrations for the local database.

``Base.metadata.create_all`` creates missing *tables* but never alters an
existing one, so a new column would be silently absent on any device that has
already run the app. That matters here more than in a normal web app: the
database lives on the villager's own machine, it holds the only copy of their
farm records, and re-importing the ~100 MB LGD dataset to pick up a schema
change is not something to ask of a rural connection.

This applies additive changes only -- new columns and new tables. Anything
destructive (dropping or retyping a column, backfilling data) needs a real
migration tool.

> [!NOTE]
> This is a deliberate stopgap for phase 1. Bring in Alembic before the first
> real user installs the app; a hand-rolled list stops being safe as soon as
> migrations need ordering, data backfills, or a downgrade path.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, inspect, text

logger = logging.getLogger("viksitgaanw.migrations")

#: table -> column -> SQLite column definition, applied when the column is
#: missing. Keep entries forever: a device may be upgrading from any version.
ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "land_parcels": {
        # Added when water quality and depth were introduced to land intake.
        "water_type": "VARCHAR(32)",
        "water_depth_value": "FLOAT",
        "water_depth_unit": "VARCHAR(16)",
        "water_depth_metres": "FLOAT",
    },
}


def apply_additive_migrations(engine: Engine) -> list[str]:
    """Add any missing columns. Returns what was applied, for logging/tests."""
    applied: list[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table, columns in ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                # create_all will build it complete; nothing to patch.
                continue
            present = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name in present:
                    continue
                # Table and column names here are developer-authored constants,
                # never user input, so the interpolation is not a injection path.
                connection.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                )
                applied.append(f"{table}.{name}")
                logger.info("Added column %s.%s", table, name)

    return applied
