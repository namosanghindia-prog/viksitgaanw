"""Government schemes a profile may qualify for, and the owner's applications.

Every answer is "you may be eligible", never a decision. The app checks what
it actually knows -- the kind of profile, the land recorded, its size, tenure
and water, what the owner is building -- and each scheme names what it cannot
check. The official page is always one tap away and is the only final word.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import knowledge
from .. import segments as seg
from ..models import InvestmentRequest, LandParcel, ProjectReport, Profile, SchemeApplication
from ..schemas import SchemeApplicationInput, SchemeApplicationOut, SchemeOut
from .events import EventType, record_event


class SchemeError(Exception):
    def __init__(self, message: str, status: int = 404) -> None:
        super().__init__(message)
        self.status = status


def catalogue() -> dict:
    return knowledge.load_schemes()


def _scheme(code: str) -> dict:
    for item in catalogue()["items"]:
        if item["code"] == code:
            return item
    raise SchemeError("Scheme not found.")


def _owner_kinds(session: Session, owner: Profile) -> set[str]:
    """What the owner is working on, as opportunity kinds."""
    kinds = {
        kind
        for kind in session.scalars(
            select(InvestmentRequest.opportunity_kind).where(InvestmentRequest.profile_id == owner.id)
        )
        if kind
    }
    if owner.farmer_id:
        codes = session.scalars(
            select(ProjectReport.opportunity_code).where(ProjectReport.farmer_id == owner.farmer_id)
        )
        for code in codes:
            item = knowledge.get_opportunity(code)
            if item:
                kinds.add(item["kind"])
    kinds.update((owner.details or {}).get("sectors") or [])
    return kinds


def evaluate(scheme: dict, owner: Profile, parcels: list[LandParcel], kinds: set[str]) -> tuple[str, list[str], bool]:
    rules = scheme.get("eligibility", {})
    reasons: list[str] = []
    unlikely = unknown = False

    relevant_kinds = set(rules.get("relevantKinds") or [])
    # Only a scheme aimed at particular work (livestock, processing, ...) can
    # "fit your plans"; a general one fits everyone and would say nothing.
    relevant = bool(relevant_kinds & kinds)

    if owner.segment == seg.GOVERNMENT:
        # An officer reads the catalogue to help farmers; nothing to judge.
        return "check", [], relevant

    if owner.segment not in rules.get("segments", []):
        return "unlikely", ["segment"], relevant

    details = owner.details or {}
    if owner.segment in seg.PARTNERS:
        allowed = rules.get("organisationTypes")
        if allowed and details.get("organisation_type") not in allowed:
            return "unlikely", ["organisation_type"], relevant

    if owner.segment == seg.FARMER and rules.get("requiresLand"):
        if not parcels:
            unknown = True
            reasons.append("land_not_recorded")
        else:
            tenures = [parcel.ownership_type for parcel in parcels]
            wanted = rules.get("ownershipTypes")
            if wanted:
                if any(tenure in wanted for tenure in tenures):
                    pass
                elif all(tenures):
                    unlikely = True
                    reasons.append("ownership")
                else:
                    unknown = True
                    reasons.append("ownership_unknown")
            limit = rules.get("maxHectares")
            if limit is not None and sum(parcel.area_hectares for parcel in parcels) > limit:
                unlikely = True
                reasons.append("land_size")
            sources = [source for parcel in parcels for source in (parcel.water_sources or [])]
            if rules.get("requiresWater") and not [s for s in sources if s != "rainfed"]:
                unlikely = True
                reasons.append("water")
            wanted_sources = rules.get("waterSources")
            if wanted_sources and not set(sources) & set(wanted_sources):
                unknown = True
                reasons.append("water_source")
            not_if = rules.get("notIf") or {}
            irrigation = not_if.get("irrigation")
            if irrigation and all(parcel.irrigation_type in irrigation for parcel in parcels):
                unlikely = True
                reasons.append("already_has")

    not_if = rules.get("notIf") or {}
    if not_if.get("detail") == "has_kcc" and details.get("has_kcc"):
        unlikely = True
        reasons.append("already_has")

    status = "unlikely" if unlikely else "check" if unknown else "likely"
    return status, reasons, relevant


def _application_out(row: SchemeApplication) -> SchemeApplicationOut:
    return SchemeApplicationOut(
        id=row.id,
        scheme_code=row.scheme_code,
        status=row.status,
        documents_ready=list(row.documents_ready or []),
        applied_on=row.applied_on,
        reference_number=row.reference_number,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def for_owner(session: Session, owner: Profile) -> list[SchemeOut]:
    parcels = (
        list(session.scalars(select(LandParcel).where(LandParcel.farmer_id == owner.farmer_id)))
        if owner.farmer_id
        else []
    )
    kinds = _owner_kinds(session, owner)
    applications = {
        row.scheme_code: row
        for row in session.scalars(select(SchemeApplication).where(SchemeApplication.profile_id == owner.id))
    }
    rank = {"likely": 0, "check": 1, "unlikely": 2}
    out = []
    for scheme in catalogue()["items"]:
        status, reasons, relevant = evaluate(scheme, owner, parcels, kinds)
        application = applications.get(scheme["code"])
        out.append(
            SchemeOut(
                code=scheme["code"],
                name=scheme["name"],
                benefit=scheme["benefit"],
                cannot_check=scheme.get("cannotCheck", {}),
                url=scheme["url"],
                documents=list(scheme.get("documents", [])),
                status=status,
                reasons=reasons,
                relevant=relevant,
                application=_application_out(application) if application else None,
            )
        )
    # Applications in progress first, then what fits best.
    out.sort(key=lambda item: (item.application is None, rank[item.status], not item.relevant))
    return out


def save_application(
    session: Session, owner: Profile, code: str, data: SchemeApplicationInput
) -> SchemeApplicationOut:
    scheme = _scheme(code)
    known = set(scheme.get("documents", []))
    unknown = [doc for doc in data.documents_ready if doc not in known]
    if unknown:
        raise SchemeError(f"Not a document this scheme asks for: {', '.join(unknown)}", 422)
    row = session.scalars(
        select(SchemeApplication).where(
            SchemeApplication.profile_id == owner.id, SchemeApplication.scheme_code == code
        )
    ).first()
    if row is None:
        row = SchemeApplication(profile_id=owner.id, scheme_code=code)
        session.add(row)
    row.status = data.status
    row.documents_ready = list(dict.fromkeys(data.documents_ready))
    row.applied_on = data.applied_on
    row.reference_number = data.reference_number
    row.notes = data.notes
    session.flush()
    record_event(
        session,
        EventType.SCHEME_APPLICATION_UPDATED,
        entity_type="scheme_application",
        entity_id=row.id,
        payload={"scheme": code, "status": row.status},
    )
    return _application_out(row)


def delete_application(session: Session, owner: Profile, code: str) -> None:
    row = session.scalars(
        select(SchemeApplication).where(
            SchemeApplication.profile_id == owner.id, SchemeApplication.scheme_code == code
        )
    ).first()
    if row is None:
        raise SchemeError("No application for this scheme.")
    session.delete(row)
