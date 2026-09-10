#!/usr/bin/env python
"""Download the Noto fonts needed to print project reports in Indian scripts.

Run once, while online:

    python scripts/fetch_fonts.py --all
    python scripts/fetch_fonts.py --script Deva Taml
    python scripts/fetch_fonts.py --language ur

Why this exists at all: a PDF carries its own glyphs, so a report in Odia needs
an Odia font embedded in it. On Windows the app already falls back to Nirmala
UI, which ships with the operating system and covers nine Indic scripts, so a
fresh install can print Hindi, Bengali, Tamil, Telugu, Kannada, Malayalam,
Gujarati, Gurmukhi and Odia with nothing downloaded. Everything else -- the
Perso-Arabic scripts used by Urdu, Kashmiri and Sindhi, Ol Chiki for Santali,
and every script on a machine that is not Windows -- needs the real font.

The fonts are Noto, published by Google under the SIL Open Font License, which
permits redistribution. They are fetched from the notofonts.github.io release
tree rather than vendored into the repository so that a clone stays small; a
packaged build should ship them.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = REPO_ROOT / "data" / "fonts"

#: The upstream tree is organised by script family, and each family ships
#: static instances of its variable font. These are the two weights the report
#: uses: regular for body text, bold for headings and table headers.
BASE_URL = "https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts"

#: ISO 15924 script -> (upstream family directory, font file stem).
SCRIPTS: dict[str, tuple[str, str]] = {
    "Latn": ("NotoSans", "NotoSans"),
    "Deva": ("NotoSansDevanagari", "NotoSansDevanagari"),
    "Beng": ("NotoSansBengali", "NotoSansBengali"),
    "Guru": ("NotoSansGurmukhi", "NotoSansGurmukhi"),
    "Gujr": ("NotoSansGujarati", "NotoSansGujarati"),
    "Orya": ("NotoSansOriya", "NotoSansOriya"),
    "Taml": ("NotoSansTamil", "NotoSansTamil"),
    "Telu": ("NotoSansTelugu", "NotoSansTelugu"),
    "Knda": ("NotoSansKannada", "NotoSansKannada"),
    "Mlym": ("NotoSansMalayalam", "NotoSansMalayalam"),
    "Arab": ("NotoNaskhArabic", "NotoNaskhArabic"),
    "Olck": ("NotoSansOlChiki", "NotoSansOlChiki"),
}

#: Language -> script, for the --language form. Mirrors
#: packages/shared/knowledge/languages.json.
LANGUAGE_SCRIPTS: dict[str, str] = {
    "en": "Latn",
    "hi": "Deva",
    "mr": "Deva",
    "ne": "Deva",
    "kok": "Deva",
    "mai": "Deva",
    "doi": "Deva",
    "sa": "Deva",
    "brx": "Deva",
    "bn": "Beng",
    "as": "Beng",
    "mni": "Beng",
    "pa": "Guru",
    "gu": "Gujr",
    "or": "Orya",
    "ta": "Taml",
    "te": "Telu",
    "kn": "Knda",
    "ml": "Mlym",
    "ur": "Arab",
    "ks": "Arab",
    "sd": "Arab",
    "sat": "Olck",
}

WEIGHTS = (("Regular", "Regular"), ("Bold", "Bold"))


def _urls(family: str, stem: str, weight: str) -> list[str]:
    """Candidate URLs for one face, most likely first.

    The upstream layout has moved over time and differs between families, so
    rather than pinning one path we try the known shapes and take the first
    that answers.
    """
    return [
        f"{BASE_URL}/{family}/hinted/ttf/{stem}-{weight}.ttf",
        f"{BASE_URL}/{family}/unhinted/ttf/{stem}-{weight}.ttf",
        f"{BASE_URL}/{family}/googlefonts/ttf/{stem}-{weight}.ttf",
        f"{BASE_URL}/{family}/full/ttf/{stem}-{weight}.ttf",
    ]


def download(url: str, target: Path, timeout: float) -> bool:
    request = urllib.request.Request(
        url, headers={"User-Agent": "ViksitGaanw font fetcher"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return False

    # A redirect to an HTML error page would sail past the status check, so
    # confirm the bytes really are a TrueType font before writing them.
    if len(payload) < 4096 or payload[:4] not in (b"\x00\x01\x00\x00", b"true", b"ttcf"):
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return True


def fetch_script(script: str, target_dir: Path, *, timeout: float, force: bool) -> bool:
    if script not in SCRIPTS:
        print(f"  {script}: unknown script code", file=sys.stderr)
        return False

    family, stem = SCRIPTS[script]
    ok = True
    for weight, suffix in WEIGHTS:
        target = target_dir / f"{stem}-{suffix}.ttf"
        if target.is_file() and not force:
            print(f"  {script} {weight}: already present")
            continue

        for url in _urls(family, stem, weight):
            if download(url, target, timeout):
                size = target.stat().st_size // 1024
                print(f"  {script} {weight}: {size} KB")
                break
        else:
            print(f"  {script} {weight}: could not be downloaded", file=sys.stderr)
            # A missing bold is survivable -- the report reuses regular for
            # headings. A missing regular is not.
            if weight == "Regular":
                ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Fetch every script.")
    parser.add_argument(
        "--script", nargs="*", default=[], help="ISO 15924 script codes, e.g. Deva Taml."
    )
    parser.add_argument(
        "--language", nargs="*", default=[], help="Language codes, e.g. ta ur."
    )
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--force", action="store_true", help="Re-download fonts already present."
    )
    args = parser.parse_args()

    wanted: set[str] = set(args.script)
    for language in args.language:
        script = LANGUAGE_SCRIPTS.get(language)
        if script is None:
            print(f"Unknown language: {language}", file=sys.stderr)
            return 2
        wanted.add(script)
    if args.all:
        wanted = set(SCRIPTS)

    if not wanted:
        parser.print_help()
        return 2

    print(f"Fetching {len(wanted)} script(s) into {args.target}")
    failed = [
        script
        for script in sorted(wanted)
        if not fetch_script(script, args.target, timeout=args.timeout, force=args.force)
    ]

    if failed:
        print(f"\nFailed: {', '.join(failed)}", file=sys.stderr)
        print(
            "Check the connection and try again. On Windows, reports in the nine "
            "scripts Nirmala UI covers will still print without these.",
            file=sys.stderr,
        )
        return 1

    print("\nDone. Restart the app so it picks up the new fonts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
