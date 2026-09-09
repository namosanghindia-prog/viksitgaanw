"""Text normalisation shared by the LGD importer and the search endpoints.

Village names in the LGD dump are messy: inconsistent case, stray punctuation,
bracketed qualifiers like ``Rampur (Bujurg)``, and double spaces. Both the
importer and the query path run names through :func:`normalise_name` so that a
farmer typing "rampur bujurg" finds "Rampur  (Bujurg)".
"""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^0-9a-zऀ-ॿ]+")


def normalise_name(value: str | None) -> str:
    """Fold a place name into a searchable key.

    Lowercases, strips accents from Latin text, and collapses every run of
    punctuation or whitespace into a single space. Devanagari codepoints are
    preserved so Hindi names stay searchable.
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    # Drop Latin combining marks but keep Devanagari matras, which are
    # meaningful rather than decorative.
    text = "".join(
        ch for ch in text if not (unicodedata.combining(ch) and ord(ch) < 0x0900)
    )
    text = text.casefold()
    text = _NON_ALNUM.sub(" ", text)
    return text.strip()


def clean_name(value: str | None) -> str:
    """Tidy a display name without destroying its original spelling."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()
