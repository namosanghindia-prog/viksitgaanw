"""Expanding LGD codes into a full administrative path.

Shared by the locations router and the land-parcel serialiser so a stored
parcel and a live selector always describe a location the same way.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import District, State, SubDistrict, Village
from ..schemas import AdminUnitOut, LocationPathOut


def to_admin_unit(row, level: str, parent_code: str | None) -> AdminUnitOut:
    return AdminUnitOut(
        code=row.code,
        name=row.name,
        name_local=row.name_local,
        level=level,
        parent_code=parent_code,
    )


class UnknownLocationError(LookupError):
    def __init__(self, level: str, code: str) -> None:
        super().__init__(f"Unknown {level} code: {code}")
        self.level = level
        self.code = code


def location_error(
    session: Session,
    *,
    state_code: str | None,
    district_code: str | None = None,
    subdistrict_code: str | None = None,
    village_code: str | None = None,
) -> str | None:
    """Why this set of codes is not a real place, or None when it is.

    Each code must exist in the imported LGD dataset and sit under the one
    above it. A land parcel or a government jurisdiction pointing at a place
    that does not exist would print an address on a bank document that nobody
    could verify, so callers reject rather than store it.
    """
    if state_code and session.get(State, state_code) is None:
        return f"Unknown state code: {state_code}"

    if district_code:
        district = session.get(District, district_code)
        if district is None:
            return f"Unknown district code: {district_code}"
        if district.state_code != state_code:
            return f"District {district_code} does not belong to state {state_code}."

    if subdistrict_code:
        subdistrict = session.get(SubDistrict, subdistrict_code)
        if subdistrict is None:
            return f"Unknown sub-district code: {subdistrict_code}"
        if subdistrict.district_code != district_code:
            return (
                f"Sub-district {subdistrict_code} does not belong to "
                f"district {district_code}."
            )

    if village_code:
        if not subdistrict_code:
            return "A village cannot be set without its sub-district."
        village = session.get(Village, village_code)
        if village is None:
            return f"Unknown village code: {village_code}"
        if village.subdistrict_code != subdistrict_code:
            return (
                f"Village {village_code} does not belong to "
                f"sub-district {subdistrict_code}."
            )

    return None


def resolve_location(
    session: Session,
    *,
    village_code: str | None = None,
    subdistrict_code: str | None = None,
    district_code: str | None = None,
    state_code: str | None = None,
    strict: bool = False,
) -> LocationPathOut:
    """Walk upwards from the most specific code supplied.

    With ``strict`` the caller gets an :class:`UnknownLocationError` for a code
    that is not in the imported dataset; otherwise missing levels come back as
    ``None`` so a partially-imported LGD dump still renders something useful.
    """
    village = subdistrict = district = state = None

    if village_code:
        village = session.get(Village, village_code)
        if village is None:
            if strict:
                raise UnknownLocationError("village", village_code)
        else:
            subdistrict_code = village.subdistrict_code
            district_code = village.district_code
            state_code = village.state_code

    if subdistrict_code:
        subdistrict = session.get(SubDistrict, subdistrict_code)
        if subdistrict is None:
            if strict:
                raise UnknownLocationError("subdistrict", subdistrict_code)
        else:
            district_code = district_code or subdistrict.district_code
            state_code = state_code or subdistrict.state_code

    if district_code:
        district = session.get(District, district_code)
        if district is None:
            if strict:
                raise UnknownLocationError("district", district_code)
        else:
            state_code = state_code or district.state_code

    if state_code:
        state = session.get(State, state_code)
        if state is None and strict:
            raise UnknownLocationError("state", state_code)

    return LocationPathOut(
        state=to_admin_unit(state, "state", None) if state else None,
        district=(
            to_admin_unit(district, "district", district.state_code) if district else None
        ),
        subdistrict=(
            to_admin_unit(subdistrict, "subdistrict", subdistrict.district_code)
            if subdistrict
            else None
        ),
        village=(
            to_admin_unit(village, "village", village.subdistrict_code) if village else None
        ),
    )
