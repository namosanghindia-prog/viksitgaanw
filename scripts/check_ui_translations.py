"""Report how far the app's own screens are translated, and catch translation mistakes.

    python scripts/check_ui_translations.py                 # coverage for every language
    python scripts/check_ui_translations.py --lang bn       # one language, listing what is missing
    python scripts/check_ui_translations.py --export out/   # write en.json and hi.json for translators

English (``apps/desktop/src/i18n/strings.ts``) is the source. Hindi lives there
too; the other languages are plain JSON in ``apps/desktop/src/i18n/locales/``,
and their dropdown and chip labels in ``packages/shared/reference/i18n/``.
A missing string or label is shown in English, so it is reported, not fatal.
These are errors, and make the exit status non-zero:

* a key English does not have (a renamed string, silently never shown);
* a ``{placeholder}`` English does not use (it would print as literal braces);
* a letter from another script (one stray glyph renders as a box or the wrong
  letter in the middle of a word).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRINGS = ROOT / "apps" / "desktop" / "src" / "i18n" / "strings.ts"
LOCALES = ROOT / "apps" / "desktop" / "src" / "i18n" / "locales"
REFERENCE = ROOT / "packages" / "shared" / "reference"
META = ROOT / "packages" / "shared" / "knowledge" / "opportunities" / "_meta.json"

#: Unicode blocks each language is written in (Devanagari's danda is shared).
SCRIPTS = {
    "bn": (0x0980, 0x09FF),
    "mr": (0x0900, 0x097F),
    "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F),
    "kn": (0x0C80, 0x0CFF),
}
DANDA = {0x0964, 0x0965}
PLACEHOLDER = re.compile(r"\{(\w+)\}")
_ENTRY = re.compile(
    r"""^\s*'([A-Za-z0-9_.]+)':\s*((?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")(?:\s*\+\s*(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"))*)\s*,""",
    re.M | re.S,
)


def _unquote(literal: str) -> str:
    parts = re.findall(r"""'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)\"""", literal)
    text = "".join(a or b for a, b in parts)
    return text.replace("\\'", "'").replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")


def source_dictionaries() -> dict[str, dict[str, str]]:
    """English and Hindi as written in strings.ts."""
    text = STRINGS.read_text(encoding="utf-8")
    en_start = text.index("export const en = {")
    hi_start = text.index("export const hi")
    end = text.index("export const DICTIONARIES")
    out = {}
    for code, block in (("en", text[en_start:hi_start]), ("hi", text[hi_start:end])):
        out[code] = {key: _unquote(value) for key, value in _ENTRY.findall(block)}
    return out


def reference_codes() -> dict[str, list[str]]:
    """Every list a screen shows labels from, and its codes."""
    lists: dict[str, list[str]] = {}
    for path in sorted(REFERENCE.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        key = data.get("key") or path.stem.replace("-", "_")
        lists[key] = [item["code"] for item in data.get("items", [])]
        if key == "crops":
            lists["crop_categories"] = [c["code"] if isinstance(c, dict) else c for c in data.get("categories", [])]
    meta = json.loads(META.read_text(encoding="utf-8"))
    lists["opportunity_kinds"] = [kind["code"] for kind in meta["kinds"]]
    return lists


def _foreign_letters(lang: str, text: str) -> set[str]:
    low, high = SCRIPTS[lang]
    bad = set()
    for char in text:
        if not unicodedata.category(char).startswith(("L", "M")):
            continue
        point = ord(char)
        if low <= point <= high or point in DANDA or char.isascii():
            continue
        bad.add(char)
    return bad


def check(lang: str, english: dict[str, str], lists: dict[str, list[str]], verbose: bool) -> tuple[str, int]:
    path = LOCALES / f"{lang}.json"
    strings = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    errors: list[str] = []
    for key, value in strings.items():
        if key not in english:
            errors.append(f"{lang}: '{key}' is not an English key")
            continue
        extra = set(PLACEHOLDER.findall(value)) - set(PLACEHOLDER.findall(english[key]))
        if extra:
            errors.append(f"{lang}: '{key}' has placeholders English lacks: {sorted(extra)}")
        foreign = _foreign_letters(lang, value)
        if foreign:
            errors.append(f"{lang}: '{key}' has letters from another script: {''.join(sorted(foreign))}")
        if not value.strip():
            errors.append(f"{lang}: '{key}' is empty")
    missing = [key for key in english if key not in strings]

    overlay_path = REFERENCE / "i18n" / f"{lang}.json"
    overlay = json.loads(overlay_path.read_text(encoding="utf-8")) if overlay_path.is_file() else {}
    total_labels = sum(len(codes) for codes in lists.values())
    have_labels = 0
    missing_labels: list[str] = []
    for key, codes in lists.items():
        for code in codes:
            label = (overlay.get(key) or {}).get(code)
            if label:
                have_labels += 1
                foreign = _foreign_letters(lang, label)
                if foreign:
                    errors.append(f"{lang}: label {key}.{code} has letters from another script: {''.join(sorted(foreign))}")
            else:
                missing_labels.append(f"{key}.{code}")
    for key in overlay:
        if key not in lists:
            errors.append(f"{lang}: labels for unknown list '{key}'")

    for line in errors:
        print("ERROR", line)
    if verbose:
        for key in missing:
            print(f"missing string {key}")
        for label in missing_labels:
            print(f"missing label {label}")
    row = (f"{lang:4} strings {len(english) - len(missing):5}/{len(english):<5} "
           f"labels {have_labels:4}/{total_labels:<4} errors {len(errors)}")
    return row, len(errors)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lang", choices=sorted(SCRIPTS), help="one language, listing what is missing")
    parser.add_argument("--export", type=Path, help="write en.json and hi.json here for translators")
    args = parser.parse_args()

    sources = source_dictionaries()
    english = sources["en"]
    if args.export:
        args.export.mkdir(parents=True, exist_ok=True)
        for code, strings in sources.items():
            (args.export / f"{code}.json").write_text(json.dumps(strings, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {len(english)} English and {len(sources['hi'])} Hindi strings to {args.export}")
        return

    lists = reference_codes()
    failures = 0
    for lang in [args.lang] if args.lang else sorted(SCRIPTS):
        row, errors = check(lang, english, lists, verbose=bool(args.lang))
        print(row)
        failures += errors
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
