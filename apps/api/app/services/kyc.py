"""Identity verification, from the device.

Phase 1 of the brief calls for Aadhaar eKYC through a UIDAI-authorised KUA plus
DigiLocker, and leaves police verification for a later phase with a Gram
Panchayat partnership.

**DigiLocker** works now, through the sync server (``apps/sync/identity.py``):
it alone holds the DigiLocker keys and alone decides that a profile is
verified -- a device cannot mark itself verified, and whatever it pushes is
overwritten there. The device asks the server for an address, opens it in the
browser, where the villager signs in on DigiLocker and agrees, then asks the
server how it went until it is done. Asking again on every sync catches a
check finished after the app was closed.

The other routes wait for an agreement with a provider. What this module fixes
for them is the shape:

* which methods apply to which segment (an NRI cannot do Aadhaar eKYC; a
  company is verified by its registration, not a person's biometrics);
* the rule that an Aadhaar number is **never** stored -- not here, and not on
  the server, which keeps only a salted fingerprint of the provider's id.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import Profile
from ..schemas import KycMethodOut, KycOut, KycStartOut
from .events import EventType, record_event

#: Verification routes, in the order the UI should offer them.
#:
#: aadhaar_ekyc  -- OTP or biometric eKYC through a KUA
#: digilocker    -- sign-in on DigiLocker, run by the sync server
#: pan           -- PAN verification through an NSDL/UTIITSL-authorised API
#: passport      -- document check by a video-KYC provider, for people abroad
#: organisation  -- CIN / GSTIN / registration certificate, via DigiLocker or MCA
#: official      -- government email domain plus nomination by the department
#: police        -- phase 2+: partnership-based police verification tier
METHODS_BY_SEGMENT: dict[str, tuple[str, ...]] = {
    "farmer": ("aadhaar_ekyc", "digilocker"),
    "investor_india": ("aadhaar_ekyc", "digilocker", "pan"),
    "investor_international": ("passport",),
    "partner_national": ("organisation", "digilocker"),
    "partner_international": ("organisation", "passport"),
    "government": ("official",),
}

KYC_STATUSES = ("unverified", "pending", "verified", "rejected")


class KycError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def methods_for(segment: str) -> list[str]:
    return list(METHODS_BY_SEGMENT.get(segment, ()))


def _call(session: Session, transport: Any, method: str, path: str, body: dict | None = None) -> dict:
    """One call to the sync server, as this device."""
    from . import sync_client  # noqa: PLC0415 - sync_client imports profiles, which imports this
    from .profiles import get_owner  # noqa: PLC0415
    from .subscription import _detail  # noqa: PLC0415

    url = sync_client._get(session, "server_url")
    owner = get_owner(session)
    if not url or owner is None:
        raise KycError("Identity checks go through the sync server: switch sync on first (More → My data & sync).")
    transport = transport or sync_client.HttpTransport(url)
    try:
        token = sync_client._register(session, transport, owner)
        if method == "POST":
            return transport.post(path, body or {}, token)
        return transport.get(path, {}, token)
    except sync_client.SyncError as exc:
        raise KycError(_detail(exc), exc.status) from exc


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _apply(session: Session, owner: Profile, answer: dict[str, Any]) -> None:
    """Keep the server's word on the owner's profile, and note a new tick."""
    was = owner.kyc_status
    owner.kyc_status = answer["status"]
    owner.kyc_method = answer.get("method")
    owner.kyc_verified_at = _when(answer.get("verifiedAt"))
    if owner.kyc_status == "verified" and was != "verified":
        record_event(
            session, EventType.KYC_VERIFIED, entity_type="profile", entity_id=owner.id,
            payload={"method": owner.kyc_method, "segment": owner.segment},
        )
    session.flush()


def _owner(session: Session) -> Profile:
    from .profiles import get_owner  # noqa: PLC0415

    owner = get_owner(session)
    if owner is None:
        raise KycError("Set up your profile first.")
    return owner


def status(session: Session, transport: Any = None) -> KycOut:
    """The owner's identity check as the server sees it -- or as last known, when it cannot be reached."""
    owner = _owner(session)
    planned = methods_for(owner.segment)
    try:
        answer = _call(session, transport, "GET", "/v1/kyc")
    except KycError as exc:
        return KycOut(
            status=owner.kyc_status if owner.kyc_status in KYC_STATUSES else "unverified",
            method=owner.kyc_method,
            verified_at=owner.kyc_verified_at,
            planned=planned,
            reason="sync_off" if exc.status == 409 else "offline",
        )
    _apply(session, owner, answer)
    return KycOut(
        status=answer["status"],
        method=answer.get("method"),
        verified_at=_when(answer.get("verifiedAt")),
        registered_name=answer.get("registeredName"),
        name_matches=answer.get("nameMatches"),
        aadhaar_backed=answer.get("aadhaarBacked"),
        methods=[KycMethodOut(code=m["code"], available=bool(m["available"])) for m in answer.get("methods") or []],
        planned=planned,
        sandbox=bool(answer.get("sandbox")),
    )


def start(session: Session, method: str, transport: Any = None) -> KycStartOut:
    """An address for the browser, where the owner signs in with the provider and agrees."""
    from . import sync_client  # noqa: PLC0415

    owner = _owner(session)
    if owner.visibility != "online":
        raise KycError("Share your profile online first, then check your identity.")
    if owner.sync_state != "synced":
        # The server checks the profile it holds: make sure it holds this one.
        try:
            sync_client.run(session, transport)
        except sync_client.SyncError as exc:
            raise KycError(str(exc), exc.status) from exc
    answer = _call(session, transport, "POST", "/v1/kyc/start", {"method": method})
    if owner.kyc_status != "verified":
        owner.kyc_status = "pending"
    record_event(
        session, EventType.KYC_STARTED, entity_type="profile", entity_id=owner.id, payload={"method": method}
    )
    return KycStartOut(url=answer["url"], expires_at=_when(answer["expiresAt"]))


def check_pending(session: Session, transport: Any = None) -> None:
    """While a check is open, ask how it went. Quietly does nothing offline."""
    from .profiles import get_owner  # noqa: PLC0415

    owner = get_owner(session)
    if owner is not None and owner.kyc_status == "pending":
        status(session, transport)
