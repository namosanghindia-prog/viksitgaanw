"""Identity checks: DigiLocker through the sync server, and what others are told."""

from __future__ import annotations

import html
import importlib
import json
import re
import sys
import urllib.parse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.models import AppEvent, Profile
from app.services import sync_client
from app.services.events import EventType

from .test_marketplace import make_owner
from .test_profiles import farmer_body
from .test_sync import INVESTOR, SYNC_DIR, OtherDevice, ServerTransport, fresh_sync_module

KYC_ENV = (
    "VG_KYC_SANDBOX", "VG_KYC_SALT", "VG_SYNC_PUBLIC_URL",
    "VG_KYC_DIGILOCKER_CLIENT_ID", "VG_KYC_DIGILOCKER_CLIENT_SECRET", "VG_KYC_DIGILOCKER_REDIRECT_URI",
)
DIGILOCKER_ENV = {
    "VG_KYC_SALT": "pepper",
    "VG_KYC_DIGILOCKER_CLIENT_ID": "vg-client",
    "VG_KYC_DIGILOCKER_CLIENT_SECRET": "s3cret",
    "VG_KYC_DIGILOCKER_REDIRECT_URI": "https://sync.test/v1/kyc/digilocker/callback",
}


def start_server(monkeypatch, **env):
    """A fresh sync server with exactly these identity settings, and this device pointed at it."""
    for key in KYC_ENV:
        monkeypatch.setenv(key, env.get(key, ""))
    module = fresh_sync_module(monkeypatch)
    server = TestClient(module.app)
    monkeypatch.setattr(sync_client, "HttpTransport", lambda url: ServerTransport(server))
    return server, module


@pytest.fixture()
def cloud(monkeypatch):
    """The pretend identity provider switched on: it checks nothing, but walks every page."""
    yield start_server(monkeypatch, VG_KYC_SANDBOX="1")
    sys.path.remove(str(SYNC_DIR))


class FakeDigiLocker:
    """DigiLocker's token endpoint, answering as it does."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.name = "RAMESH KUMAR YADAV"

    def __call__(self, url: str, fields: dict) -> dict:
        self.calls.append((url, fields))
        return {
            "access_token": "tok", "token_type": "Bearer", "digilockerid": f"dl-{fields['code']}",
            "name": self.name, "dob": "01011980", "gender": "M", "eaadhaar": "Y",
        }


@pytest.fixture()
def digilocker(monkeypatch):
    server, module = start_server(monkeypatch, **DIGILOCKER_ENV)
    fake = FakeDigiLocker()
    module.digilocker.post = fake
    yield server, module, fake
    sys.path.remove(str(SYNC_DIR))


def ready(client, body: dict | None = None) -> dict:
    """This device's farmer, shared online, with sync on."""
    me = make_owner(client, body or farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    return me


def start(client, method: str = "sandbox") -> str:
    response = client.post("/api/v1/kyc/start", json={"method": method})
    assert response.status_code == 201, response.text
    return response.json()["url"]


def state_of(url: str) -> str:
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]


def approve(server, url: str, name: str = "Ramesh Yadav"):
    """Walk the pages as the person would: the server's own, then the pretend provider's."""
    page = server.get(url)
    assert page.status_code == 200, page.text
    assert server.get("/v1/kyc/sandbox/authorize", params={"state": state_of(url)}).status_code == 200
    return server.get("/v1/kyc/sandbox/callback", params={"state": state_of(url), "name": name, "code": "sandbox"})


def kyc(client) -> dict:
    response = client.get("/api/v1/kyc")
    assert response.status_code == 200, response.text
    return response.json()


def pulled_profile(device: OtherDevice, profile_id: str) -> dict:
    records = [r for r in device.pull() if r["entityType"] == "profile" and r["entityId"] == profile_id]
    assert records, f"{profile_id} not pulled"
    return records[-1]["payload"]


def events(kind: str) -> list[AppEvent]:
    with session_scope() as session:
        rows = list(session.scalars(select(AppEvent).where(AppEvent.event_type == kind)))
        session.expunge_all()
        return rows


def device_start(device: OtherDevice, method: str = "sandbox"):
    return device.server.post("/v1/kyc/start", json={"method": method}, headers=device.headers)


def other_farmer(server, profile_id: str, name: str) -> OtherDevice:
    device = OtherDevice(server, {"id": profile_id, "segment": "farmer"})
    device.push({"entity_type": "profile", "entity_id": profile_id,
                 "payload": {"id": profile_id, "segment": "farmer", "display_name": name, "visibility": "online"}})
    return device


# --------------------------------------------------------------------------- #
# Checking an identity
# --------------------------------------------------------------------------- #


def test_a_farmer_verifies_and_everyone_sees_the_tick(client, cloud):
    server, _ = cloud
    me = ready(client)
    watcher = OtherDevice(server, INVESTOR)

    before = kyc(client)
    assert before["status"] == "unverified"
    assert before["methods"] == [{"code": "digilocker", "available": False}, {"code": "sandbox", "available": True}]
    assert before["sandbox"] is True
    assert before["planned"] == ["aadhaar_ekyc", "digilocker"]

    url = start(client)
    assert kyc(client)["status"] == "pending"
    # The server's own page comes first, naming whose profile is being checked.
    page = server.get(url)
    assert "Ramesh Yadav" in page.text and "Continue only if" in page.text
    assert "/v1/kyc/sandbox/authorize?state=" in page.text

    done = approve(server, url)
    assert done.status_code == 200 and "Verified" in done.text

    after = kyc(client)
    assert after["status"] == "verified" and after["method"] == "sandbox"
    assert after["registeredName"] == "Ramesh Yadav" and after["nameMatches"] is True
    assert client.get("/api/v1/profile").json()["kycStatus"] == "verified"
    assert len(events(EventType.KYC_STARTED)) == 1
    assert len(events(EventType.KYC_VERIFIED)) == 1
    kyc(client)
    assert len(events(EventType.KYC_VERIFIED)) == 1  # counted once, not on every look

    seen = pulled_profile(watcher, me["id"])
    assert seen["kyc_status"] == "verified" and seen["kyc_method"] == "sandbox"
    assert "kyc_reference" not in seen


def test_a_device_cannot_verify_itself(cloud):
    server, _ = cloud
    liar = OtherDevice(server, {"id": "a0000000-0000-0000-0000-0000000000f1", "segment": "farmer"})
    liar.push({"entity_type": "profile", "entity_id": liar.profile["id"], "payload": {
        "id": liar.profile["id"], "segment": "farmer", "display_name": "Mohan Lal",
        "kyc_status": "verified", "kyc_method": "aadhaar_ekyc", "kyc_reference": "made-up",
    }})
    seen = pulled_profile(OtherDevice(server, INVESTOR), liar.profile["id"])
    assert seen["kyc_status"] == "unverified" and seen["kyc_method"] is None
    assert "kyc_reference" not in seen


def test_a_name_that_does_not_match_is_explained_to_its_owner_only(client, cloud):
    server, _ = cloud
    me = ready(client)
    watcher = OtherDevice(server, INVESTOR)
    done = approve(server, start(client), name="Suresh Patel")
    assert done.status_code == 400 and "Name does not match" in done.text

    mine = kyc(client)
    assert mine["status"] == "rejected"
    assert mine["registeredName"] == "Suresh Patel" and mine["nameMatches"] is False
    # To everyone else it is simply not verified: a misspelt name is not a failed check.
    assert pulled_profile(watcher, me["id"])["kyc_status"] == "unverified"


def test_renaming_the_profile_to_someone_else_loses_the_tick(cloud):
    server, _ = cloud
    ramesh = other_farmer(server, "a0000000-0000-0000-0000-0000000000f2", "Ramesh Yadav")
    watcher = OtherDevice(server, INVESTOR)
    url = device_start(ramesh).json()["url"]
    # The registered name may be longer: every word of the shorter one must be in it.
    assert approve(server, url, name="RAMESH KUMAR YADAV").status_code == 200
    assert pulled_profile(watcher, ramesh.profile["id"])["kyc_status"] == "verified"

    for name, expected in (("Mahesh Yadav", "unverified"), ("Ramesh Yadav", "verified")):
        ramesh.push({"entity_type": "profile", "entity_id": ramesh.profile["id"], "payload": {
            "id": ramesh.profile["id"], "segment": "farmer", "display_name": name}})
        assert pulled_profile(watcher, ramesh.profile["id"])["kyc_status"] == expected


def test_one_identity_verifies_one_profile_until_that_profile_is_deleted(cloud):
    server, _ = cloud
    first = other_farmer(server, "a0000000-0000-0000-0000-0000000000f3", "Ramesh Yadav")
    second = other_farmer(server, "a0000000-0000-0000-0000-0000000000f4", "Ramesh Yadav")
    assert approve(server, device_start(first).json()["url"]).status_code == 200

    refused = approve(server, device_start(second).json()["url"])
    assert refused.status_code == 400 and "Already used" in refused.text
    assert server.get("/v1/kyc", headers=second.headers).json()["status"] == "unverified"

    # Deleting the first profile frees the identity, and keeps no registered name.
    first.push({"entity_type": "profile", "entity_id": first.profile["id"], "deleted": True})
    assert approve(server, device_start(second).json()["url"]).status_code == 200
    assert server.get("/v1/kyc", headers=second.headers).json()["status"] == "verified"


def test_a_link_works_once_and_not_after_it_is_replaced_or_expired(client, cloud):
    server, module = cloud
    ready(client)
    url = start(client)
    assert approve(server, url).status_code == 200
    again = server.get("/v1/kyc/sandbox/callback", params={"state": state_of(url), "name": "Ramesh Yadav", "code": "x"})
    assert again.status_code == 400 and "Link expired" in again.text

    old, new = start(client), start(client)
    assert "Link expired" in server.get(old).text  # starting again cancels the last link
    assert server.get(new).status_code == 200

    with module.db() as con:
        con.execute("UPDATE kyc_sessions SET expires_at = '2000-01-01T00:00:00+00:00' WHERE state = ?",
                    (state_of(new),))
    assert "Link expired" in server.get(new).text


def test_declining_checks_nothing(client, cloud):
    server, _ = cloud
    ready(client)
    url = start(client)
    server.get(url)
    declined = server.get("/v1/kyc/sandbox/callback", params={"state": state_of(url), "error": "declined"})
    assert declined.status_code == 400 and "Not verified" in declined.text
    assert kyc(client)["status"] == "unverified"


def test_a_check_finished_after_the_app_closed_shows_at_the_next_sync(client, cloud):
    server, _ = cloud
    ready(client)
    url = start(client)
    approve(server, url)
    with session_scope() as session:
        assert session.scalars(select(Profile.kyc_status)).one() == "pending"  # nobody has looked yet
    assert client.post("/api/v1/sync/run").status_code == 200
    with session_scope() as session:
        assert session.scalars(select(Profile.kyc_status)).one() == "verified"


# --------------------------------------------------------------------------- #
# DigiLocker itself
# --------------------------------------------------------------------------- #


def test_digilocker_signs_in_with_pkce_and_keeps_only_a_fingerprint(client, digilocker):
    server, module, fake = digilocker
    ready(client)
    assert kyc(client)["methods"] == [{"code": "digilocker", "available": True}]
    assert kyc(client)["sandbox"] is False
    assert server.get("/v1/kyc/sandbox/authorize", params={"state": "x"}).status_code == 404

    url = start(client, "digilocker")
    page = server.get(url).text
    target = html.unescape(re.search(r"href='([^']+)'", page).group(1))
    parts = urllib.parse.urlsplit(target)
    query = dict(urllib.parse.parse_qsl(parts.query))
    assert parts.netloc == "digilocker.meripehchaan.gov.in"
    assert query["client_id"] == "vg-client" and query["response_type"] == "code"
    assert query["redirect_uri"] == DIGILOCKER_ENV["VG_KYC_DIGILOCKER_REDIRECT_URI"]
    assert query["state"] == state_of(url) and query["code_challenge_method"] == "S256"
    with module.db() as con:
        verifier = con.execute("SELECT verifier FROM kyc_sessions WHERE state = ?", (state_of(url),)).fetchone()[0]
    assert query["code_challenge"] == module.identity.pkce_challenge(verifier)

    done = server.get("/v1/kyc/digilocker/callback", params={"state": state_of(url), "code": "abc"})
    assert done.status_code == 200 and "Verified" in done.text
    token_url, fields = fake.calls[0]
    assert token_url.endswith("/token")
    assert fields["code_verifier"] == verifier and fields["grant_type"] == "authorization_code"

    mine = kyc(client)
    assert mine["status"] == "verified" and mine["method"] == "digilocker" and mine["aadhaarBacked"] is True
    with module.db() as con:
        row = con.execute("SELECT * FROM verifications").fetchone()
    kept = json.dumps([row[key] for key in row.keys()])
    # Not the DigiLocker id itself, nor the date of birth or gender.
    assert "dl-abc" not in kept and "01011980" not in kept and '"M"' not in kept


def test_a_digilocker_failure_checks_nothing(client, digilocker):
    server, module, _ = digilocker
    ready(client)
    url = start(client, "digilocker")

    def broken(url, fields):
        raise module.identity.IdentityError("DigiLocker said 400: invalid_grant")

    module.digilocker.post = broken
    failed = server.get("/v1/kyc/digilocker/callback", params={"state": state_of(url), "code": "abc"})
    assert failed.status_code == 400 and "Could not check" in failed.text
    assert kyc(client)["status"] == "unverified"


def test_digilocker_needs_the_salt_first(client, monkeypatch):
    start_server(monkeypatch, **{**DIGILOCKER_ENV, "VG_KYC_SALT": ""})
    try:
        ready(client)
        refused = client.post("/api/v1/kyc/start", json={"method": "digilocker"})
        assert refused.status_code == 503 and "VG_KYC_SALT" in refused.json()["detail"]
    finally:
        sys.path.remove(str(SYNC_DIR))


def test_nothing_to_take_on_a_server_without_providers(client, monkeypatch):
    start_server(monkeypatch)
    try:
        ready(client)
        assert kyc(client)["methods"] == [{"code": "digilocker", "available": False}]
        refused = client.post("/api/v1/kyc/start", json={"method": "digilocker"})
        assert refused.status_code == 503
        assert client.post("/api/v1/kyc/start", json={"method": "passport"}).status_code == 422
    finally:
        sys.path.remove(str(SYNC_DIR))


# --------------------------------------------------------------------------- #
# Before it can start
# --------------------------------------------------------------------------- #


def test_without_sync_or_offline_the_last_known_status_shows(client, cloud, monkeypatch):
    make_owner(client, farmer_body())
    off = kyc(client)
    assert off["reason"] == "sync_off" and off["status"] == "unverified" and off["planned"]
    assert client.post("/api/v1/kyc/start", json={"method": "sandbox"}).status_code == 409

    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})

    class Down(ServerTransport):
        def get(self, *args, **kwargs):
            raise sync_client.SyncError("Sync server not reachable: no route", 503)

        post = get

    monkeypatch.setattr(sync_client, "HttpTransport", lambda url: Down(None))
    assert kyc(client)["reason"] == "offline"


def test_a_profile_is_shared_before_it_is_checked(client, cloud):
    assert client.post("/api/v1/profile", json=farmer_body()).status_code == 201
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    refused = client.post("/api/v1/kyc/start", json={"method": "sandbox"})
    assert refused.status_code == 409 and "Share your profile" in refused.json()["detail"]


def test_sharing_and_checking_at_once_pushes_the_profile_first(client, cloud):
    """Share, then press Verify before any sync ran: the server must already hold the profile."""
    server, _ = cloud
    ready(client)
    with session_scope() as session:
        assert session.scalars(select(Profile.sync_state)).one() != "synced"
    assert approve(server, start(client)).status_code == 200
    assert kyc(client)["status"] == "verified"


# --------------------------------------------------------------------------- #
# The small print
# --------------------------------------------------------------------------- #


def test_pages_escape_what_they_are_given(cloud):
    server, _ = cloud
    hostile = "'><script>alert(1)</script>"
    page = server.get("/v1/kyc/sandbox/authorize", params={"state": hostile}).text
    assert "<script>" not in page and "&lt;script&gt;" in page

    device = other_farmer(server, "a0000000-0000-0000-0000-0000000000f5", "<b>Ramesh</b> Yadav")
    page = server.get(device_start(device).json()["url"]).text
    assert "<b>Ramesh</b>" not in page and "&lt;b&gt;Ramesh&lt;/b&gt;" in page


def test_names_match_word_for_word(cloud):
    _, module = cloud
    match = module.identity.names_match
    assert match("RAMESH KUMAR YADAV", "Ramesh Yadav")
    assert match("Ramesh Yadav", "Shri Ramesh Kumar Yadav")
    assert match("Ramesh Yadav", "Suresh Yadav") is False
    # A surname alone, or one left after dropping initials, would match every Yadav.
    assert match("RAMESH KUMAR YADAV", "Yadav") is False
    assert match("R. K. Yadav", "Suresh Yadav") is False
    assert match("Ramesh", "RAMESH")
    assert match("Ramesh Yadav", "") is False and match(None, "Ramesh") is False
    assert match("रमेश यादव", "रमेश कुमार यादव")
    assert match("Ramésh Yadav", "Ramesh Yadav")


def test_the_operator_can_take_a_tick_away(cloud, capsys):
    server, module = cloud
    ramesh = other_farmer(server, "a0000000-0000-0000-0000-0000000000f6", "Ramesh Yadav")
    watcher = OtherDevice(server, INVESTOR)
    approve(server, device_start(ramesh).json()["url"])
    assert pulled_profile(watcher, ramesh.profile["id"])["kyc_status"] == "verified"

    sys.modules.pop("admin", None)
    admin = importlib.import_module("admin")
    admin.server = module
    admin.unverify(ramesh.profile["id"])
    assert "no longer verified" in capsys.readouterr().out
    assert pulled_profile(watcher, ramesh.profile["id"])["kyc_status"] == "unverified"
    with pytest.raises(SystemExit):
        admin.unverify(ramesh.profile["id"])
