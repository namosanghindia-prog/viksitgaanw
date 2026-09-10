"""Finding a font that can actually draw the language the farmer chose.

A PDF is not like a web page: it carries its own glyphs, so a report in Tamil
needs a Tamil font embedded in it. Indic scripts also need real shaping --
reordering a matra in front of the consonant it follows, joining conjuncts --
which is why the report is drawn with HarfBuzz shaping switched on rather than
by placing one glyph per codepoint.

Fonts are found in this order:

1. **A downloaded Noto face** in ``data/fonts``, put there by
   ``scripts/fetch_fonts.py``. This is the portable answer and the one a
   packaged build should ship.
2. **Nirmala UI**, which is part of Windows and covers nine Indic scripts plus
   Latin in a single file. It means a fresh install on a village laptop can
   print a Hindi or Kannada report immediately, with nothing downloaded. It is
   a collection file, so the face is extracted once into a cache directory
   that fpdf2 can open.
3. Nothing -- in which case the caller is told which script is missing and how
   to install it, rather than being handed a PDF full of empty boxes.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..config import get_settings

logger = logging.getLogger("viksitgaanw.fonts")

#: ISO 15924 script code -> the Noto family that covers it. These are the file
#: stems scripts/fetch_fonts.py writes into data/fonts.
NOTO_FAMILY: dict[str, str] = {
    "Latn": "NotoSans",
    "Deva": "NotoSansDevanagari",
    "Beng": "NotoSansBengali",
    "Guru": "NotoSansGurmukhi",
    "Gujr": "NotoSansGujarati",
    "Orya": "NotoSansOriya",
    "Taml": "NotoSansTamil",
    "Telu": "NotoSansTelugu",
    "Knda": "NotoSansKannada",
    "Mlym": "NotoSansMalayalam",
    "Arab": "NotoNaskhArabic",
    "Olck": "NotoSansOlChiki",
}

#: Scripts the Windows-bundled Nirmala UI covers. Checked against the font's
#: own character map at runtime rather than trusted blindly.
NIRMALA_SCRIPTS = frozenset(
    {"Latn", "Deva", "Beng", "Guru", "Gujr", "Orya", "Taml", "Telu", "Knda", "Mlym"}
)

#: One representative codepoint per script, used to confirm a candidate font
#: really covers it before we commit to drawing a whole report with it.
_PROBE: dict[str, int] = {
    "Latn": 0x0041,
    "Deva": 0x0915,
    "Beng": 0x0995,
    "Guru": 0x0A15,
    "Gujr": 0x0A95,
    "Orya": 0x0B15,
    "Taml": 0x0B95,
    "Telu": 0x0C15,
    "Knda": 0x0C95,
    "Mlym": 0x0D15,
    "Arab": 0x0627,
    "Olck": 0x1C5A,
}

_WINDOWS_NIRMALA = Path(r"C:\Windows\Fonts\Nirmala.ttc")
#: Face indices inside Nirmala.ttc: 0 is regular, 1 is bold.
_NIRMALA_FACES = {"regular": 0, "bold": 1}


@dataclass(frozen=True)
class FontSet:
    """The faces a report will be drawn with."""

    name: str
    regular: Path
    bold: Path | None
    #: Where it came from, for the report's own provenance line.
    source: str

    @property
    def has_bold(self) -> bool:
        return self.bold is not None


class FontUnavailableError(RuntimeError):
    """No font on this device can draw the requested script."""

    def __init__(self, script: str, language: str | None = None) -> None:
        family = NOTO_FAMILY.get(script, "the required")
        subject = f"the {language} report" if language else f"script {script}"
        super().__init__(
            f"No font on this device can draw {subject}. "
            f"Run `python scripts/fetch_fonts.py --script {script}` once while "
            f"online to install {family}, then try again."
        )
        self.script = script
        self.language = language


def _cache_dir() -> Path:
    directory = get_settings().fonts_dir / ".cache"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _covers(path: Path, script: str) -> bool:
    """Does this font file actually contain a glyph for the script?"""
    probe = _PROBE.get(script)
    if probe is None:
        return True
    try:
        from fontTools.ttLib import TTFont

        with TTFont(str(path), lazy=True) as font:
            return probe in font.getBestCmap()
    except Exception as error:  # pragma: no cover - depends on the font file
        logger.info("Could not inspect %s: %s", path, error)
        return False


def _extract_nirmala_face(style: str) -> Path | None:
    """Pull one face out of Nirmala.ttc into a plain .ttf fpdf2 can embed.

    Cached on disk and re-extracted only when the system font changes, which
    in practice means a Windows update.
    """
    if not _WINDOWS_NIRMALA.is_file():
        return None

    index = _NIRMALA_FACES[style]
    stamp = int(_WINDOWS_NIRMALA.stat().st_mtime)
    target = _cache_dir() / f"Nirmala-{style}-{stamp}.ttf"
    if target.is_file():
        return target

    try:
        from fontTools.ttLib import TTCollection

        collection = TTCollection(str(_WINDOWS_NIRMALA))
        if index >= len(collection.fonts):
            return None
        collection.fonts[index].save(str(target))
    except Exception as error:  # pragma: no cover - depends on the system font
        logger.info("Could not extract Nirmala face %s: %s", style, error)
        return None

    return target if target.is_file() else None


def _downloaded(script: str, style: str) -> Path | None:
    family = NOTO_FAMILY.get(script)
    if not family:
        return None
    suffix = "Regular" if style == "regular" else "Bold"
    for extension in (".ttf", ".otf"):
        candidate = get_settings().fonts_dir / f"{family}-{suffix}{extension}"
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=16)
def resolve(script: str) -> FontSet:
    """Find a usable font for ``script``, or raise :class:`FontUnavailableError`."""
    regular = _downloaded(script, "regular")
    if regular and _covers(regular, script):
        bold = _downloaded(script, "bold")
        return FontSet(
            name=f"noto-{script.lower()}",
            regular=regular,
            bold=bold if bold and _covers(bold, script) else None,
            source=f"{NOTO_FAMILY[script]} (SIL Open Font License)",
        )

    if sys.platform == "win32" and script in NIRMALA_SCRIPTS:
        nirmala = _extract_nirmala_face("regular")
        if nirmala and _covers(nirmala, script):
            bold = _extract_nirmala_face("bold")
            return FontSet(
                name="nirmala",
                regular=nirmala,
                bold=bold if bold and _covers(bold, script) else None,
                source="Nirmala UI (bundled with Windows)",
            )

    raise FontUnavailableError(script)


def is_available(script: str) -> bool:
    try:
        resolve(script)
        return True
    except FontUnavailableError:
        return False


def clear_cache() -> None:
    resolve.cache_clear()
