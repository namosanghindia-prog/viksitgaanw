"""Report translation and Indian-format number rendering.

A project report has to come out in the language the farmer actually reads, so
every string that appears in one is looked up here rather than written inline.
Three sources feed a lookup, in order:

1. the requested language's catalogue in ``packages/shared/knowledge/dpr``;
2. the shared reference and knowledge JSON, which carry English and Hindi
   labels natively;
3. Hindi, then English, as the fallback chain.

Nothing here raises for a missing translation. A report that comes out with
three headings in English is far more useful to a farmer than no report, and
:attr:`Translator.coverage` lets the report say honestly how complete it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .. import knowledge

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

#: Indian numbering: the last three digits group together, then pairs.
_LAKH = 100_000
_CRORE = 10_000_000


def group_indian(value: int) -> str:
    """Format an integer the way an Indian invoice does: 12,34,567."""
    negative = value < 0
    digits = str(abs(int(value)))
    if len(digits) <= 3:
        grouped = digits
    else:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        grouped = ",".join(parts) + "," + tail
    return f"-{grouped}" if negative else grouped


@dataclass(frozen=True)
class Translator:
    """Renders every piece of text a report needs, in one language."""

    language: str

    # ----------------------------------------------------------------- #
    # Strings
    # ----------------------------------------------------------------- #

    def s(self, key: str, **variables: Any) -> str:
        """A report heading or label, with ``{placeholders}`` substituted."""
        template = self._raw_string(key)
        if not variables:
            return template
        return _PLACEHOLDER.sub(
            lambda match: str(variables.get(match.group(1), match.group(0))),
            template,
        )

    def _raw_string(self, key: str) -> str:
        for language in self._chain():
            value = knowledge.load_catalogue(language).get("strings", {}).get(key)
            if value:
                return value
        # A key nobody has translated at all still has to render as something
        # a human can act on, so show the key rather than an empty cell.
        return key

    def _chain(self) -> tuple[str, ...]:
        chain = [self.language]
        chain.extend(
            language
            for language in knowledge.FALLBACK_CHAIN
            if language != self.language
        )
        return tuple(chain)

    # ----------------------------------------------------------------- #
    # Labels coming from the shared data
    # ----------------------------------------------------------------- #

    def label(self, label: dict[str, str] | None) -> str:
        """A bilingual label dict from the reference or knowledge JSON."""
        if not label:
            return ""
        for language in self._chain():
            value = label.get(language)
            if value:
                return value
        return next(iter(label.values()), "")

    def opportunity_name(self, opportunity: dict[str, Any]) -> str:
        """The option's name. Non-native languages get it from the catalogue."""
        override = (
            knowledge.load_catalogue(self.language)
            .get("opportunities", {})
            .get(opportunity["code"])
        )
        if override:
            return override
        return self.label(opportunity.get("label"))

    def reference(
        self,
        list_key: str,
        code: str | None,
        fallback: dict[str, str] | None = None,
    ) -> str:
        """A soil type, water source, crop and so on, by reference-list code.

        ``fallback`` is the label dict from wherever the caller found the code.
        It exists for the lists that are not in ``packages/shared/reference`` at
        all -- an option's kind, a risk level -- so those still resolve through
        the catalogue first and only then fall back to English.
        """
        if not code:
            return self.s("v.notStated")

        override = (
            knowledge.load_catalogue(self.language)
            .get("reference", {})
            .get(list_key, {})
            .get(code)
        )
        if override:
            return override

        from .. import reference as reference_data

        try:
            items = reference_data.get_list(list_key)["items"]
        except (KeyError, reference_data.ReferenceUnavailableError):
            # Not a shared reference list (or the directory is missing): use
            # whatever label the caller had, then the raw code.
            return self.label(fallback) or code
        for item in items:
            if item["code"] == code:
                return self.label(item.get("label")) or code
        return self.label(fallback) or code

    def summary(self, opportunity: dict[str, Any]) -> str:
        """An option's descriptive paragraph, in the farmer's language."""
        override = (
            knowledge.load_catalogue(self.language)
            .get("summaries", {})
            .get(opportunity["code"])
        )
        if override:
            return override
        return self.label(opportunity.get("summary"))

    def reference_list(self, list_key: str, codes: list[str] | None) -> str:
        if not codes:
            return self.s("v.none")
        return ", ".join(self.reference(list_key, code) for code in codes)

    # ----------------------------------------------------------------- #
    # Numbers and money
    # ----------------------------------------------------------------- #

    def money(self, rupees: float) -> str:
        """Full rupee figure: ``12,34,567``."""
        return group_indian(round(rupees))

    def money_words(self, rupees: float) -> str:
        """Compact rupee figure a farmer reads at a glance: ``12.35 lakh``."""
        amount = float(rupees)
        if abs(amount) >= _CRORE:
            return f"{amount / _CRORE:.2f} {self.s('v.crore')}"
        if abs(amount) >= _LAKH:
            return f"{amount / _LAKH:.2f} {self.s('v.lakh')}"
        return group_indian(round(amount))

    def money_range(self, low: float, high: float) -> str:
        return f"{self.money_words(low)} {self.s('v.to')} {self.money_words(high)}"

    def usd(self, amount: float) -> str:
        """World-trade figures, which are always quoted in dollars."""
        if abs(amount) >= 1_000_000_000:
            return f"{amount / 1_000_000_000:.1f} {self.s('v.billion')}"
        if abs(amount) >= 1_000_000:
            return f"{amount / 1_000_000:.0f} {self.s('v.million')}"
        return f"{amount:,.0f}"

    def usd_range(self, low: float, high: float) -> str:
        return f"US$ {self.usd(low)} {self.s('v.to')} {self.usd(high)}"

    def number(self, value: float, decimals: int = 2) -> str:
        """Indian grouping on the whole part, plain decimals after the point."""
        if decimals == 0:
            return group_indian(round(value))
        rounded = round(float(value), decimals)
        sign = "-" if rounded < 0 else ""
        whole, _, fraction = f"{abs(rounded):.{decimals}f}".partition(".")
        return f"{sign}{group_indian(int(whole))}.{fraction}"

    def percent(self, fraction: float, decimals: int = 1) -> str:
        return f"{fraction * 100:.{decimals}f}%"

    # ----------------------------------------------------------------- #
    # Honesty about the translation itself
    # ----------------------------------------------------------------- #

    @property
    def coverage(self) -> float:
        return knowledge.catalogue_coverage(self.language)

    @property
    def is_fully_translated(self) -> bool:
        # A report is only claimed as fully translated when nothing at all fell
        # back, because a farmer cannot tell a missing translation from a
        # deliberate English term.
        return self.coverage >= 0.999

    @property
    def script(self) -> str:
        entry = knowledge.get_language(self.language)
        return (entry or {}).get("script", "Latn")

    @property
    def is_rtl(self) -> bool:
        entry = knowledge.get_language(self.language)
        return bool((entry or {}).get("rtl", False))

    @property
    def endonym(self) -> str:
        entry = knowledge.get_language(self.language)
        return (entry or {}).get("endonym", self.language)
