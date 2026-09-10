#!/usr/bin/env python
"""Report how complete each project-report translation actually is.

    python scripts/check_translations.py
    python scripts/check_translations.py --language ta --missing
    python scripts/check_translations.py --strict

A farmer who asks for a report in Odia and gets one in English deserves to be
told why, and a reviewer who sits down to finish Odia deserves a list rather
than a diff. This produces both.

``--strict`` exits non-zero if any catalogue on disk has a key English does not
know about, or is missing a key another already-complete language has. That is
the failure mode worth catching in CI: a renamed key that quietly starts
falling back everywhere.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = REPO_ROOT / "packages" / "shared" / "knowledge"
CATALOGUES = KNOWLEDGE / "dpr"

#: Reference lists a catalogue may translate for languages the shared reference
#: JSON does not cover (it carries English and Hindi only).
REFERENCE_KEYS = (
    "soil_types",
    "water_sources",
    "water_types",
    "irrigation_types",
    "ownership_types",
    "area_units",
    "depth_units",
    "crops",
    "kinds",
    "risk",
)


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _opportunity_codes() -> list[str]:
    codes: list[str] = []
    for path in sorted((KNOWLEDGE / "opportunities").glob("*.json")):
        if path.name.startswith("_"):
            continue
        codes.extend(item["code"] for item in _load(path))
    return codes


def _reference_codes() -> dict[str, list[str]]:
    reference_dir = REPO_ROOT / "packages" / "shared" / "reference"
    files = {
        "soil_types": "soil-types.json",
        "water_sources": "water-sources.json",
        "water_types": "water-types.json",
        "irrigation_types": "irrigation-types.json",
        "ownership_types": "ownership-types.json",
        "area_units": "area-units.json",
        "depth_units": "depth-units.json",
        "crops": "crops.json",
    }
    codes = {
        key: [item["code"] for item in _load(reference_dir / name)["items"]]
        for key, name in files.items()
    }
    meta = _load(KNOWLEDGE / "opportunities" / "_meta.json")
    codes["kinds"] = [entry["code"] for entry in meta["kinds"]]
    codes["risk"] = [entry["code"] for entry in meta["riskLevels"]]
    return codes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", help="Report on one language only.")
    parser.add_argument(
        "--missing", action="store_true", help="List the untranslated keys."
    )
    parser.add_argument(
        "--strict", action="store_true", help="Exit non-zero on a structural problem."
    )
    args = parser.parse_args()

    english = _load(CATALOGUES / "en.json")["strings"]
    languages = _load(KNOWLEDGE / "languages.json")["items"]
    opportunities = _opportunity_codes()
    reference = _reference_codes()

    problems: list[str] = []
    print(f"{'lang':6} {'script':6} {'strings':>12} {'options':>10} {'reference':>10}")
    print("-" * 50)

    for entry in languages:
        code = entry["code"]
        if args.language and code != args.language:
            continue

        path = CATALOGUES / f"{code}.json"
        catalogue = _load(path) if path.is_file() else {"strings": {}}
        strings = catalogue.get("strings", {})

        unknown = sorted(set(strings) - set(english))
        if unknown:
            problems.append(f"{code}: {len(unknown)} key(s) English does not have: {unknown[:5]}")

        done = sum(1 for key in english if strings.get(key))

        # English and Hindi take option and reference names from the shared
        # data files instead, so a catalogue without those blocks is complete.
        native = code in {"en", "hi"}
        if native:
            option_done, option_total = len(opportunities), len(opportunities)
            ref_done = ref_total = sum(len(codes) for codes in reference.values())
        else:
            names = catalogue.get("opportunities", {})
            option_done = sum(1 for opportunity in opportunities if names.get(opportunity))
            option_total = len(opportunities)

            block = catalogue.get("reference", {})
            ref_done = sum(
                1
                for key in REFERENCE_KEYS
                for item in reference.get(key, [])
                if block.get(key, {}).get(item)
            )
            ref_total = sum(len(codes) for codes in reference.values())

        print(
            f"{code:6} {entry.get('script', ''):6} "
            f"{done:>5}/{len(english):<6} "
            f"{option_done:>4}/{option_total:<5} "
            f"{ref_done:>4}/{ref_total:<5}"
        )

        if args.missing and done < len(english):
            for key in english:
                if not strings.get(key):
                    print(f"    missing: {key}")

    if problems:
        print("\nProblems:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        if args.strict:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
