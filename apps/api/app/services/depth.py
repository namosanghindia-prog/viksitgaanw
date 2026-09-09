"""Depth-to-water conversion.

Farmers quote borewell and well depth in feet almost everywhere in India, but
a project report and any pumping-cost calculation need one unit. As with area,
the parcel keeps both the number the farmer said and the normalised metres.
"""

from __future__ import annotations

from .. import reference

METRES_PER_FOOT = 0.3048

#: Deepest borewells in India run past 1,000 ft. Anything beyond this is a
#: typo rather than a well, and a wrong depth would distort a cost estimate.
MAX_DEPTH_METRES = 1500.0


class UnknownDepthUnitError(ValueError):
    def __init__(self, unit: str) -> None:
        super().__init__(f"Unknown depth unit: {unit!r}")
        self.unit = unit


def to_metres(value: float, unit: str) -> float:
    """Convert ``value`` in ``unit`` to metres."""
    factor = reference.depth_unit_factor(unit)
    if factor is None:
        raise UnknownDepthUnitError(unit)
    return value * factor


def metres_to_feet(metres: float) -> float:
    return metres / METRES_PER_FOOT
