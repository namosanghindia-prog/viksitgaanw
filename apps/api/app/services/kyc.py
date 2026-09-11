"""Identity verification: the integration point, not yet the integration.

Phase 1 of the brief calls for Aadhaar eKYC through a UIDAI-authorised KUA plus
DigiLocker for documents, and leaves police verification for a later phase
with a Gram Panchayat partnership. None of those can be switched on from here:
each needs a signed agreement and credentials this codebase does not have.

What this module fixes now is the shape, so that wiring in a provider later
touches this file and nothing else:

* which methods apply to which segment (an NRI cannot do Aadhaar eKYC; a
  company is verified by its registration, not a person's biometrics);
* the rule that an Aadhaar number is **never** stored -- a KUA returns a
  reference for the transaction, and that reference is what a profile keeps;
* a single ``begin`` entry point that says plainly it is not configured,
  rather than a button that pretends to work.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Verification routes, in the order the UI should offer them.
#:
#: aadhaar_ekyc  -- OTP or biometric eKYC through a KUA
#: digilocker    -- documents pulled from the holder's DigiLocker
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


@dataclass(frozen=True)
class KycNotConfigured(Exception):
    method: str

    def __str__(self) -> str:
        return (
            f"Identity verification by {self.method} is not available yet. "
            "It needs an agreement with an authorised provider."
        )


def methods_for(segment: str) -> list[str]:
    return list(METHODS_BY_SEGMENT.get(segment, ()))


def begin(segment: str, method: str) -> None:
    """Start verification. Always refuses until a provider is configured.

    A provider implementation should return the redirect or OTP handle here,
    and a callback should set ``kyc_status``, ``kyc_method``,
    ``kyc_reference`` and ``kyc_verified_at`` on the profile.
    """
    if method not in METHODS_BY_SEGMENT.get(segment, ()):
        raise ValueError(f"{method} does not apply to a {segment} profile.")
    raise KycNotConfigured(method)
