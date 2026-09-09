#!/usr/bin/env python
"""Download the full Local Government Directory dump into ``data/lgd/dump``.

The authoritative source is https://lgdirectory.gov.in, but its download page
is session-based and not scriptable. This pulls the same files from a public
daily mirror of that site which publishes them as dated CSV archives, so the
fetch is reproducible and can be pinned to a date.

Usage
-----
    python scripts/fetch_lgd.py                    # latest available
    python scripts/fetch_lgd.py --date 09Sep2026   # a specific snapshot
    python scripts/fetch_lgd.py --levels states districts

Then import what was downloaded:

    python scripts/import_lgd.py --source data/lgd/dump --replace

Requires network access and ``py7zr`` (in requirements-dev.txt). If this
machine has no internet, download the archives by hand from the mirror's
releases page and drop the CSVs into ``data/lgd/dump``; the importer does not
care how they got there.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DUMP_DIR = REPO_ROOT / "data" / "lgd" / "dump"

RELEASES_API = "https://api.github.com/repos/ramSeraph/opendata/releases"
MIRROR_HOME = "https://ramseraph.github.io/opendata/lgd/"

LEVELS = ("states", "districts", "subdistricts", "villages")

#: e.g. "districts.09Sep2026.csv.7z"
ASSET_RE = re.compile(r"^(?P<level>[a-z_]+)\.(?P<date>\d{2}[A-Za-z]{3}\d{4})\.csv\.7z$")

USER_AGENT = "ViksitGaanw-LGD-fetch/0.1 (+offline agri OS setup script)"


def _get(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def list_assets() -> dict[str, dict[str, str]]:
    """Return ``{level: {date: download_url}}`` for every LGD archive found."""
    payload = json.loads(_get(RELEASES_API))
    found: dict[str, dict[str, str]] = {level: {} for level in LEVELS}
    for release in payload:
        for asset in release.get("assets", []):
            match = ASSET_RE.match(asset["name"])
            if not match:
                continue
            level = match.group("level")
            if level in found:
                found[level][match.group("date")] = asset["browser_download_url"]
    return found


def _sort_key(date_token: str) -> datetime:
    return datetime.strptime(date_token, "%d%b%Y").replace(tzinfo=timezone.utc)


def pick_date(assets: dict[str, dict[str, str]], levels: list[str]) -> str:
    """Newest snapshot for which *every* requested level exists."""
    common: set[str] | None = None
    for level in levels:
        dates = set(assets.get(level, {}))
        common = dates if common is None else (common & dates)
    if not common:
        raise SystemExit(
            "No single date has all of: "
            + ", ".join(levels)
            + f".\nBrowse what is available at {MIRROR_HOME}"
        )
    return max(common, key=_sort_key)


def download(url: str, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _get(url, timeout=600)
    target.write_bytes(data)
    return len(data)


def extract(archive: Path) -> list[Path]:
    try:
        import py7zr
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "py7zr is required to unpack the LGD archives.\n"
            "  pip install py7zr   (or: pip install -r apps/api/requirements-dev.txt)"
        ) from exc

    with py7zr.SevenZipFile(archive, "r") as bundle:
        names = bundle.getnames()
        bundle.extractall(path=archive.parent)
    return [archive.parent / name for name in names]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--date", help="Snapshot to fetch, e.g. 09Sep2026. Default: newest.")
    parser.add_argument(
        "--levels",
        nargs="+",
        choices=LEVELS,
        default=list(LEVELS),
        help="Which levels to download. Default: all four.",
    )
    parser.add_argument(
        "--keep-archives",
        action="store_true",
        help="Keep the .7z files after extracting them.",
    )
    args = parser.parse_args(argv)

    print(f"Querying available LGD snapshots...\n  mirror: {MIRROR_HOME}")
    try:
        assets = list_assets()
    except urllib.error.URLError as exc:
        print(f"\nCould not reach the mirror: {exc.reason}", file=sys.stderr)
        print(
            "This machine may be offline. Download the archives manually and put\n"
            f"the CSVs in {DUMP_DIR}, then run scripts/import_lgd.py.",
            file=sys.stderr,
        )
        return 1

    date = args.date or pick_date(assets, args.levels)
    print(f"  snapshot: {date}\n")

    extracted: list[Path] = []
    for level in args.levels:
        url = assets.get(level, {}).get(date)
        if not url:
            print(f"  ! {level}: not published for {date}, skipped")
            continue
        archive = DUMP_DIR / f"{level}.{date}.csv.7z"
        size = download(url, archive)
        print(f"  + {level:14} {size / 1048576:6.1f} MB downloaded", end="")
        files = extract(archive)
        extracted.extend(files)
        print(f" -> {files[0].name}")
        if not args.keep_archives:
            archive.unlink(missing_ok=True)

    if not extracted:
        print("\nNothing downloaded.")
        return 1

    total = sum(path.stat().st_size for path in extracted if path.exists())
    print(f"\nDone. {len(extracted)} CSV file(s), {total / 1048576:.1f} MB in {DUMP_DIR}")
    print("\nNext:")
    print("  python scripts/import_lgd.py --source data/lgd/dump --replace")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
