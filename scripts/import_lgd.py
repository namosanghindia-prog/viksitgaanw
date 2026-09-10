#!/usr/bin/env python
"""Import the Local Government Directory (LGD) dump into the offline database.

The LGD (https://lgdirectory.gov.in, mirrored on data.gov.in) is the official
state -> district -> sub-district -> village directory for India, and it is free
for commercial use. It ships as CSV exports whose headers vary between
downloads and between levels, so this importer identifies columns by matching
normalised header names rather than by position.

Two shapes of export are handled:

* **Per-level files** -- a states file, a districts file, and so on.
* **A single village file** that repeats the whole parent chain on every row.
  This is the common download, and the importer back-fills states, districts
  and sub-districts from it.

Usage
-----
    python scripts/import_lgd.py --sample              # bundled sample data
    python scripts/import_lgd.py --source data/lgd/dump
    python scripts/import_lgd.py --source villages.csv --replace

The import is idempotent: re-running it updates existing rows in place, so
refreshing to a newer LGD release never duplicates anything.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: E402

from app.db import engine, init_db, session_scope  # noqa: E402
from app.models import DatasetMeta, District, State, SubDistrict, Village  # noqa: E402
from app.services.text import clean_name, normalise_name  # noqa: E402

SAMPLE_DIR = REPO_ROOT / "data" / "lgd" / "sample"
BATCH_SIZE = 5000


# --------------------------------------------------------------------------- #
# Header handling
# --------------------------------------------------------------------------- #


def normalise_header(header: str) -> str:
    """``"Sub-District Name (In English)"`` -> ``"subdistrictnameinenglish"``."""
    return "".join(ch for ch in header.lower() if ch.isalnum())


#: Logical field -> accepted normalised header spellings, most specific first.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "state_code": ("statecode", "statelgdcode", "stcode", "statecodelgd"),
    "state_name": ("statenameinenglish", "statenameenglish", "statename", "stname"),
    "state_name_local": ("statenameinlocal", "statenamelocal", "statenamelocallanguage"),
    "state_census": ("statecensus2011code", "statecensuscode"),
    "district_code": ("districtcode", "districtlgdcode", "distcode"),
    "district_name": (
        "districtnameinenglish",
        "districtnameenglish",
        "districtname",
        "distname",
    ),
    "district_name_local": ("districtnameinlocal", "districtnamelocal"),
    "district_census": ("districtcensus2011code", "districtcensuscode"),
    "subdistrict_code": (
        "subdistrictcode",
        "subdistrictlgdcode",
        "subdistcode",
        "blockcode",
        "tehsilcode",
        "talukcode",
    ),
    "subdistrict_name": (
        "subdistrictnameinenglish",
        "subdistrictnameenglish",
        "subdistrictname",
        "subdistname",
        "blockname",
        "tehsilname",
        "talukname",
    ),
    "subdistrict_name_local": ("subdistrictnameinlocal", "subdistrictnamelocal"),
    "subdistrict_census": ("subdistrictcensus2011code", "subdistrictcensuscode"),
    "village_code": ("villagecode", "villagelgdcode"),
    "village_name": ("villagenameinenglish", "villagenameenglish", "villagename"),
    "village_name_local": ("villagenameinlocal", "villagenamelocal"),
    # A bare "Census 2011 Code" is resolved by the level-aware fallback in
    # map_columns rather than being claimed here by the village level.
    "village_census": ("villagecensus2011code", "villagecensuscode"),
}


def map_columns(fieldnames: list[str]) -> dict[str, str]:
    """Map logical field names onto the actual CSV headers present."""
    normalised = {normalise_header(name): name for name in fieldnames if name}
    mapping: dict[str, str] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalised:
                mapping[field] = normalised[alias]
                break

    # Per-level files label the census column plainly as "Census 2011 Code"
    # rather than "District Census 2011 Code". An unqualified census column
    # belongs to whatever the deepest level in the file is.
    level = detect_level(mapping)
    if level and f"{level}_census" not in mapping:
        for alias in ("census2011code", "census2011", "censuscode"):
            if alias in normalised:
                mapping[f"{level}_census"] = normalised[alias]
                break
    return mapping


def detect_level(mapping: dict[str, str]) -> str | None:
    """Deepest administrative level this file can populate."""
    for level in ("village", "subdistrict", "district", "state"):
        if f"{level}_code" in mapping and f"{level}_name" in mapping:
            return level
    return None


# --------------------------------------------------------------------------- #
# CSV reading
# --------------------------------------------------------------------------- #


def open_csv(path: Path):
    """Open an LGD export, coping with the encodings they ship in.

    Exports are usually UTF-8 with a BOM, but older ones are cp1252. Trying in
    that order avoids mangling Devanagari local-language names.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            handle = path.open("r", encoding=encoding, newline="")
            handle.read(8192)
            handle.seek(0)
            return handle, encoding
        except UnicodeDecodeError:
            handle.close()
    raise RuntimeError(f"Could not decode {path} with any known encoding.")


def clean_code(value: Any) -> str | None:
    """Normalise a code cell.

    LGD codes are numeric but arrive as ``"9"``, ``"09"``, ``" 9 "`` or
    ``"9.0"`` depending on whether the file has been through a spreadsheet.
    They are stored as the canonical unpadded integer string so that a code
    from one export always matches the same code from another.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NULL", "-"}:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    if text.isdigit():
        return str(int(text))
    return text


# --------------------------------------------------------------------------- #
# Upserts
# --------------------------------------------------------------------------- #


def upsert(connection, model, rows: list[dict[str, Any]]) -> int:
    """Insert or update a batch, keyed on the primary-key ``code``."""
    if not rows:
        return 0
    stmt = sqlite_insert(model.__table__)
    updatable = {
        column.name: getattr(stmt.excluded, column.name)
        for column in model.__table__.columns
        if column.name != "code"
    }
    stmt = stmt.on_conflict_do_update(index_elements=["code"], set_=updatable)
    connection.execute(stmt, rows)
    return len(rows)


class Importer:
    """Streams CSV rows into the four hierarchy tables.

    Parent rows are remembered in memory so a 660k-row village file does not
    re-write the same 36 states 660k times.
    """

    def __init__(self, connection) -> None:
        self.connection = connection
        self.seen: dict[str, set[str]] = {
            "state": set(),
            "district": set(),
            "subdistrict": set(),
        }
        self.pending: dict[str, list[dict[str, Any]]] = {
            "state": [],
            "district": [],
            "subdistrict": [],
            "village": [],
        }
        self.counts: dict[str, int] = dict.fromkeys(self.pending, 0)
        self.skipped: dict[str, int] = {"no_code": 0, "no_parent": 0}

    def _queue(self, level: str, row: dict[str, Any]) -> None:
        self.pending[level].append(row)
        if len(self.pending[level]) >= BATCH_SIZE:
            # Flush every level, parents first -- not just this one. A village
            # batch can reference a sub-district that is still sitting in the
            # pending list, which a foreign key would reject. Parent lists are
            # deduplicated and therefore almost always empty here, so this
            # costs nothing in the common case.
            self.flush()

    def flush(self, level: str | None = None) -> None:
        # Parents before children, so foreign keys always resolve.
        order = ["state", "district", "subdistrict", "village"]
        levels = order if level is None else [level]
        models = {
            "state": State,
            "district": District,
            "subdistrict": SubDistrict,
            "village": Village,
        }
        for name in levels:
            rows = self.pending[name]
            if rows:
                self.counts[name] += upsert(self.connection, models[name], rows)
                self.pending[name] = []

    def ingest_row(self, record: dict[str, Any], mapping: dict[str, str], level: str) -> None:
        def cell(field: str) -> Any:
            column = mapping.get(field)
            return record.get(column) if column else None

        state_code = clean_code(cell("state_code"))
        district_code = clean_code(cell("district_code"))
        subdistrict_code = clean_code(cell("subdistrict_code"))
        village_code = clean_code(cell("village_code"))

        # --- state -------------------------------------------------------- #
        if state_code and state_code not in self.seen["state"]:
            name = clean_name(cell("state_name"))
            if name:
                self.seen["state"].add(state_code)
                self._queue(
                    "state",
                    {
                        "code": state_code,
                        "name": name,
                        "name_local": clean_name(cell("state_name_local")) or None,
                        "name_norm": normalise_name(name),
                        "census_code": clean_code(cell("state_census")),
                        "is_active": True,
                    },
                )

        # --- district ----------------------------------------------------- #
        if district_code and district_code not in self.seen["district"]:
            name = clean_name(cell("district_name"))
            if name and state_code:
                self.seen["district"].add(district_code)
                self._queue(
                    "district",
                    {
                        "code": district_code,
                        "state_code": state_code,
                        "name": name,
                        "name_local": clean_name(cell("district_name_local")) or None,
                        "name_norm": normalise_name(name),
                        "census_code": clean_code(cell("district_census")),
                        "is_active": True,
                    },
                )

        # --- sub-district -------------------------------------------------- #
        if subdistrict_code and subdistrict_code not in self.seen["subdistrict"]:
            name = clean_name(cell("subdistrict_name"))
            if name and district_code and state_code:
                self.seen["subdistrict"].add(subdistrict_code)
                self._queue(
                    "subdistrict",
                    {
                        "code": subdistrict_code,
                        "district_code": district_code,
                        "state_code": state_code,
                        "name": name,
                        "name_local": clean_name(cell("subdistrict_name_local")) or None,
                        "name_norm": normalise_name(name),
                        "census_code": clean_code(cell("subdistrict_census")),
                        "is_active": True,
                    },
                )

        # --- village ------------------------------------------------------- #
        if level == "village":
            if not village_code:
                self.skipped["no_code"] += 1
                return
            name = clean_name(cell("village_name"))
            if not name:
                self.skipped["no_code"] += 1
                return
            if not (subdistrict_code and district_code and state_code):
                # A village with a broken parent chain would be unreachable in
                # the cascading selector, so it is counted and dropped rather
                # than silently stored.
                self.skipped["no_parent"] += 1
                return
            self._queue(
                "village",
                {
                    "code": village_code,
                    "subdistrict_code": subdistrict_code,
                    "district_code": district_code,
                    "state_code": state_code,
                    "name": name,
                    "name_local": clean_name(cell("village_name_local")) or None,
                    "name_norm": normalise_name(name),
                    "census_code": clean_code(cell("village_census")),
                    "is_active": True,
                },
            )


# --------------------------------------------------------------------------- #
# Driving the import
# --------------------------------------------------------------------------- #


def discover_files(sources: list[Path]) -> list[Path]:
    files: list[Path] = []
    for source in sources:
        if source.is_dir():
            files.extend(sorted(p for p in source.rglob("*.csv")))
        elif source.is_file():
            files.append(source)
        else:
            raise FileNotFoundError(f"No such file or directory: {source}")
    return files


def import_file(importer: Importer, path: Path, verbose: bool = True) -> tuple[str | None, int]:
    handle, encoding = open_csv(path)
    try:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            print(f"  ! {path.name}: empty file, skipped")
            return None, 0

        mapping = map_columns(list(reader.fieldnames))
        level = detect_level(mapping)
        if level is None:
            print(f"  ! {path.name}: no recognisable LGD columns, skipped")
            print(f"      headers seen: {', '.join(reader.fieldnames[:8])}")
            return None, 0

        if verbose:
            print(f"  + {path.name} [{encoding}] -> {level} level")

        rows_read = 0
        started = time.monotonic()
        for record in reader:
            importer.ingest_row(record, mapping, level)
            rows_read += 1
            if verbose and rows_read % 100_000 == 0:
                elapsed = time.monotonic() - started
                print(f"      {rows_read:,} rows ({rows_read / max(elapsed, 0.001):,.0f}/s)")
        importer.flush()
        return level, rows_read
    finally:
        handle.close()


def truncate_hierarchy(connection) -> None:
    """Wipe the reference hierarchy. User data is never touched."""
    for model in (Village, SubDistrict, District, State):
        connection.execute(delete(model))


def summarise() -> dict[str, int]:
    with session_scope() as session:
        return {
            "states": session.scalar(select(func.count()).select_from(State)) or 0,
            "districts": session.scalar(select(func.count()).select_from(District)) or 0,
            "subdistricts": session.scalar(select(func.count()).select_from(SubDistrict)) or 0,
            "villages": session.scalar(select(func.count()).select_from(Village)) or 0,
        }


def record_provenance(sources: list[Path], counts: dict[str, int], notes: str | None) -> None:
    with session_scope() as session:
        meta = session.get(DatasetMeta, "lgd")
        if meta is None:
            meta = DatasetMeta(key="lgd")
            session.add(meta)
        meta.source = "; ".join(str(p) for p in sources)
        meta.row_count = counts.get("villages", 0)
        meta.notes = notes
        from datetime import datetime, timezone

        meta.imported_at = datetime.now(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source",
        nargs="+",
        type=Path,
        help="CSV file(s) or directory containing the LGD export.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help=f"Import the bundled development sample from {SAMPLE_DIR.relative_to(REPO_ROOT)}.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete the existing hierarchy first (user data is untouched).",
    )
    parser.add_argument(
        "--no-optimise",
        action="store_true",
        help="Skip the VACUUM/ANALYZE pass that runs after the import.",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not args.source and not args.sample:
        parser.error("Pass --source <path> or --sample.")

    sources: list[Path] = list(args.source or [])
    if args.sample:
        sources.append(SAMPLE_DIR)

    files = discover_files(sources)
    if not files:
        print("No CSV files found.")
        return 1

    init_db()
    verbose = not args.quiet
    print(f"Importing LGD data from {len(files)} file(s)...")

    started = time.monotonic()
    total_rows = 0
    with engine.begin() as connection:
        if args.replace:
            print("  - clearing existing hierarchy")
            truncate_hierarchy(connection)
        importer = Importer(connection)
        for path in files:
            _, rows = import_file(importer, path, verbose=verbose)
            total_rows += rows
        importer.flush()

    # After a bulk load the file carries free pages from the --replace delete
    # and the planner has no statistics for the new row counts. Both matter:
    # this database ships on a low-end village laptop.
    if not args.no_optimise:
        print("  - compacting and analysing")
        with engine.connect() as connection:
            connection.exec_driver_sql("VACUUM")
            connection.exec_driver_sql("ANALYZE")

    counts = summarise()
    record_provenance(
        sources,
        counts,
        notes="Bundled development sample." if args.sample and not args.source else None,
    )

    elapsed = time.monotonic() - started
    print(f"\nDone in {elapsed:.1f}s. Read {total_rows:,} rows.")
    print("Database now holds:")
    for name, value in counts.items():
        print(f"  {name:14} {value:,}")
    if importer.skipped["no_parent"]:
        print(f"  (skipped {importer.skipped['no_parent']:,} villages with an incomplete parent chain)")
    if importer.skipped["no_code"]:
        print(f"  (skipped {importer.skipped['no_code']:,} rows with no usable code or name)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
