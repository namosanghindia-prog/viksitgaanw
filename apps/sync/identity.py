"""Identity checks, run by the sync server -- never on a villager's device.

**DigiLocker** is the one route that works without a commercial contract: a
government OAuth service (Authorized Partner API v2.2). The villager signs in
on DigiLocker's own site in their browser and agrees; DigiLocker sends them
back to this server with a one-time code, and exchanging it returns their
DigiLocker id, their name as registered, and whether the account is backed
by Aadhaar. That is enough to say the person is who their profile says.

What is kept, and what is not:

* a salted hash of the DigiLocker id -- enough to spot one identity behind
  two profiles, useless to anyone else;
* the registered name, shown only to its owner, compared with the profile
  name: a profile counts as verified only while the two match, so nobody
  can verify with a relative's account;
* whether the account is Aadhaar-backed.

Never the Aadhaar number, the date of birth, the gender or any document.

**Aadhaar eKYC** needs a UIDAI-licensed KUA (directly or through an
aggregator such as a KYC API provider), and PAN, passport and organisation
checks need their own providers; each is a :class:`Provider` to add here once
an agreement is signed. **Police verification** is a later, partnership-based
tier.

``VG_KYC_SANDBOX=1`` adds a pretend provider for development: it walks the
same pages and callback but checks nothing, and everything it verifies is
marked ``sandbox``. Never set it where real people sign up.

Configuration, in the environment or ``apps/sync/.env``:

* ``VG_KYC_DIGILOCKER_CLIENT_ID``, ``VG_KYC_DIGILOCKER_CLIENT_SECRET`` and
  ``VG_KYC_DIGILOCKER_REDIRECT_URI`` -- the last exactly as registered on the
  partner portal: ``https://<this server>/v1/kyc/digilocker/callback``;
* ``VG_KYC_SALT`` -- any long random string, set once and never changed;
* ``VG_SYNC_PUBLIC_URL`` -- this server's address as people's browsers reach
  it, when it sits behind a proxy that hides it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

AUTHORIZE_URL = "https://digilocker.meripehchaan.gov.in/public/oauth2/1/authorize"
TOKEN_URL = "https://digilocker.meripehchaan.gov.in/public/oauth2/1/token"


class IdentityError(Exception):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def pkce_verifier() -> str:
    """A fresh code verifier: 43 to 128 unreserved characters, as the spec asks."""
    return secrets.token_urlsafe(64)[:96]


def pkce_challenge(verifier: str) -> str:
    """The S256 challenge for a verifier."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def reference(salt: str, identity_id: str) -> str:
    """A stable, salted fingerprint of a provider's id for a person."""
    return hashlib.sha256(f"{salt}:{identity_id}".encode()).hexdigest()


def _words(name: str) -> list[str]:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return [word for word in re.split(r"[^a-zऀ-෿]+", text) if len(word) > 1]


def names_match(registered: str | None, profile_name: str | None) -> bool:
    """Whether a profile name plausibly belongs to the registered person.

    Every word of the shorter name must be in the longer, so "Ramesh Yadav"
    matches "RAMESH KUMAR YADAV" but not "Suresh Yadav". Initials of one
    letter are ignored -- but a surname alone is not enough: at least two words
    must match unless both names are one word, or "Yadav" would match every
    Yadav.
    """
    a, b = _words(registered or ""), _words(profile_name or "")
    if not a or not b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < min(2, len(longer)):
        return False
    return all(word in longer for word in shorter)


class Provider(Protocol):
    method: str

    @property
    def configured(self) -> bool: ...

    def authorize_url(self, state: str, challenge: str) -> str: ...

    def exchange(self, code: str, verifier: str) -> dict[str, Any]:
        """Return {"id", "name", "aadhaar_backed"} for the person who agreed."""
        ...


def _post_form(url: str, fields: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise IdentityError(f"DigiLocker said {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IdentityError(f"DigiLocker not reachable: {exc}", 503) from exc


class DigiLocker:
    """DigiLocker's authorization-code flow with PKCE."""

    method = "digilocker"

    def __init__(self, env: dict[str, str] | None = None) -> None:
        env = env if env is not None else dict(os.environ)
        self.client_id = env.get("VG_KYC_DIGILOCKER_CLIENT_ID", "")
        self.client_secret = env.get("VG_KYC_DIGILOCKER_CLIENT_SECRET", "")
        #: This server's own callback, exactly as registered on the DigiLocker partner portal.
        self.redirect_uri = env.get("VG_KYC_DIGILOCKER_REDIRECT_URI", "")
        self.authorize_endpoint = env.get("VG_KYC_DIGILOCKER_AUTHORIZE_URL", AUTHORIZE_URL)
        self.token_endpoint = env.get("VG_KYC_DIGILOCKER_TOKEN_URL", TOKEN_URL)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    def authorize_url(self, state: str, challenge: str) -> str:
        return self.authorize_endpoint + "?" + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })

    #: Replaced in tests.
    post = staticmethod(_post_form)

    def exchange(self, code: str, verifier: str) -> dict[str, Any]:
        answer = self.post(self.token_endpoint, {
            "code": code,
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "code_verifier": verifier,
        })
        if not answer.get("digilockerid"):
            raise IdentityError("DigiLocker did not say who signed in.")
        # Only these three leave this function: not the date of birth or gender.
        return {
            "id": answer["digilockerid"],
            "name": answer.get("name") or "",
            "aadhaar_backed": answer.get("eaadhaar") == "Y",
        }


class Sandbox:
    """A pretend provider for development. It checks nothing."""

    method = "sandbox"

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    @property
    def configured(self) -> bool:
        return self.enabled

    def authorize_url(self, state: str, challenge: str) -> str:
        # Its pages are on this same server, so a relative address will do.
        return "/v1/kyc/sandbox/authorize?" + urllib.parse.urlencode({"state": state})

    def exchange(self, code: str, verifier: str) -> dict[str, Any]:
        # The code carries the name the tester typed on the pretend page.
        name = urllib.parse.unquote(code.split(":", 1)[1]) if ":" in code else "Sandbox Person"
        return {"id": f"sandbox-{hashlib.sha256(name.encode()).hexdigest()[:12]}", "name": name,
                "aadhaar_backed": False}
