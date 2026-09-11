#!/usr/bin/env python
"""Load Agmarknet mandi prices into the local database.

    python scripts/import_mandi_prices.py --csv prices.csv
    python scripts/import_mandi_prices.py --fetch                 # needs VG_DATA_GOV_API_KEY
    python scripts/import_mandi_prices.py --fetch --state "Uttar Pradesh"

The CSV is the one data.gov.in offers for download from "Current Daily Price
of Various Commodities from Various Markets (Mandi)" -- columns State,
District, Market, Commodity, Variety, Grade, Arrival_Date, Min_Price,
Max_Price, Modal_Price. Importing the same day twice replaces those rows.

Run it on a machine with internet and copy the database, or run --fetch on a
schedule where there is a connection: the app itself only ever reads what is
stored, so prices stay available offline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.db import init_db, session_scope  # noqa: E402
from app.services import prices  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=Path, help="a CSV downloaded from data.gov.in")
    source.add_argument("--fetch", action="store_true", help="pull from the data.gov.in API")
    parser.add_argument("--state", help="only this state (with --fetch)")
    parser.add_argument("--commodity", help="only this commodity (with --fetch)")
    parser.add_argument("--api-key", help="data.gov.in key; defaults to VG_DATA_GOV_API_KEY")
    args = parser.parse_args(argv)

    init_db()
    with session_scope() as session:
        try:
            if args.csv:
                count = prices.import_csv(session, args.csv.read_text(encoding="utf-8-sig"))
            else:
                count = prices.fetch_agmarknet(
                    session, api_key=args.api_key, state=args.state, commodity=args.commodity
                )
        except prices.PriceError as exc:
            print(f"Could not import: {exc}", file=sys.stderr)
            return 1
    print(f"Imported {count} price rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
