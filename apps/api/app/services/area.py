"""Area conversion.

Farmers speak in bigha, guntha, kanal and acre depending on where they are; a
bank's project report needs hectares. Every stored parcel keeps both: the
number the farmer actually said, and the normalised hectare figure that all
downstream maths uses.
"""

from __future__ import annotations

from .. import reference

HECTARES_PER_ACRE = 0.40468564224


class UnknownAreaUnitError(ValueError):
    def __init__(self, unit: str) -> None:
        super().__init__(f"Unknown area unit: {unit!r}")
        self.unit = unit


def to_hectares(value: float, unit: str) -> float:
    """Convert ``value`` in ``unit`` to hectares.

    Raises :class:`UnknownAreaUnitError` rather than guessing, because a silent
    fallback here would put a wrong plot size on an investment report.
    """
    factor = reference.area_unit_factor(unit)
    if factor is None:
        raise UnknownAreaUnitError(unit)
    return value * factor


def hectares_to_acres(hectares: float) -> float:
    return hectares / HECTARES_PER_ACRE


def is_regional_unit(unit: str) -> bool:
    """True for units whose real-world size varies by state (bigha, katha)."""
    for item in reference.get_list("area_units")["items"]:
        if item["code"] == unit:
            return bool(item.get("regional", False))
    return False
