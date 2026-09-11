"""The sync server's abuse controls and sign-in hardening.

Rate limits, size limits, signing a lost device out, suspending an abusive
profile, and tokens that are swapped every few months. Run on SQLite by
default, and on PostgreSQL with VG_SYNC_TEST_DATABASE_URL (see test_sync).
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import session_scope
from app.services import sync_client

from .test_marketplace import make_owner
from .test_profiles import farmer_body
from .test_sync import SYNC_DIR, OtherDevice, ServerTransport, fresh_sync_module

FARMER = {"id": "d0000000-0000-0000-0000-000000000001", "segment": "farmer"}
INVESTOR = {"id": "d0000000-0000-0000-0000-000000000002", "segment": "investor_india"}


@pytest.fixture()
def sync(monkeypatch):
    module = fresh_sync_module(monkeypatch)
    yield module, TestClient(module.app)
    sys.path.remove(str(SYNC_DIR))


def _admin(module):
    sys.modules.pop("admin", None)
    admin = importlib.import_module("admin")
    admin.server = module
    return admin


def _profile(profile: dict, **payload) -> dict:
    return {"entity_type": "profile", "entity_id": profile["id"],
            "payload": {"id": profile["id"], "segment": profile["segment"], "display_name": "Ramesh",
                        "visibility": "online", **payload}}


# --------------------------------------------------------------------------- #
# Limits
# --------------------------------------------------------------------------- #


def test_a_device_that_floods_the_server_is_slowed_down(sync):
    module, server = sync
    module.device_limiter = module.RateLimiter(3, 60)
    farmer = OtherDevice(server, FARMER)
    for _ in range(3):
        assert server.get("/v1/pull", headers=farmer.headers).status_code == 200
    refused = server.get("/v1/pull", headers=farmer.headers)
    assert refused.status_code == 429 and int(refused.headers["Retry-After"]) >= 1


def test_one_address_cannot_register_devices_without_end(sync):
    module, server = sync
    module.registration_limiter = module.RateLimiter(2, 3600)
    for n in range(2):
        body = {"profile_id": f"d0000000-0000-0000-0000-00000000010{n}", "segment": "farmer"}
        assert server.post("/v1/devices", json=body).status_code == 200
    third = server.post("/v1/devices", json={"profile_id": "d0000000-0000-0000-0000-000000000109", "segment": "farmer"})
    assert third.status_code == 429


def test_oversized_requests_and_records_are_refused(sync):
    module, server = sync
    farmer = OtherDevice(server, FARMER)
    module.MAX_RECORD_BYTES = 200
    answer = farmer.push(_profile(FARMER, about="x" * 500))
    assert answer["accepted"] == 0 and answer["rejected"][0]["reason"] == "record too large"
    module.MAX_BODY_BYTES = 1000
    big = server.post("/v1/push", headers=farmer.headers, json={"records": [_profile(FARMER, about="y" * 5000)]})
    assert big.status_code == 413


# --------------------------------------------------------------------------- #
# A lost phone, and an abusive profile
# --------------------------------------------------------------------------- #


def test_a_lost_phone_is_signed_out_and_the_owner_comes_back(sync, capsys):
    module, server = sync
    admin = _admin(module)
    phone = OtherDevice(server, FARMER)
    with module.db() as con:
        device_id = con.execute("SELECT id FROM devices WHERE profile_id = ?", (FARMER["id"],)).fetchone()["id"]

    admin.sign_out(device_id)
    refused = server.get("/v1/pull", headers=phone.headers)
    assert refused.status_code == 401 and "signed out" in refused.json()["detail"]
    # Whoever has the phone cannot simply register the profile again.
    again = server.post("/v1/devices", json={"profile_id": FARMER["id"], "segment": "farmer"})
    assert again.status_code == 409

    admin.list_devices(FARMER["id"])
    assert "signed out" in capsys.readouterr().out
    admin.release(FARMER["id"])
    new_phone = OtherDevice(server, FARMER)
    assert server.get("/v1/pull", headers=new_phone.headers).status_code == 200


def test_release_refuses_while_a_device_is_still_active(sync):
    module, server = sync
    OtherDevice(server, FARMER)
    with pytest.raises(SystemExit):
        _admin(module).release(FARMER["id"])


def test_a_suspended_profile_is_refused_and_its_posts_stop_reaching_anyone(sync):
    module, server = sync
    admin = _admin(module)
    farmer = OtherDevice(server, FARMER)
    investor = OtherDevice(server, INVESTOR)
    farmer.push(_profile(FARMER))
    assert [r["entityId"] for r in investor.pull() if r["entityType"] == "profile"] == [FARMER["id"]]

    admin.suspend(FARMER["id"], "Fake investment offers")
    assert server.get("/v1/pull", headers=farmer.headers).status_code == 403
    investor.rev = 0
    assert not any(r["entityId"] == FARMER["id"] for r in investor.pull()), "hidden from everyone else"

    admin.unsuspend(FARMER["id"])
    investor.rev = 0
    assert any(r["entityId"] == FARMER["id"] for r in investor.pull())
    assert server.get("/v1/pull", headers=farmer.headers).status_code == 200


# --------------------------------------------------------------------------- #
# Tokens that do not last for ever
# --------------------------------------------------------------------------- #


def test_a_rotated_token_replaces_the_old_one(sync):
    _, server = sync
    phone = OtherDevice(server, FARMER)
    fresh = server.post("/v1/devices/rotate", headers=phone.headers)
    assert fresh.status_code == 200
    assert server.get("/v1/pull", headers=phone.headers).status_code == 401, "the old token stopped working"
    assert server.get("/v1/pull", headers={"Authorization": f"Bearer {fresh.json()['token']}"}).status_code == 200


def test_the_device_swaps_its_token_when_it_is_old(client, sync):
    _, server = sync
    transport = ServerTransport(server)
    make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    with session_scope() as session:
        sync_client.run(session, transport)
        first = sync_client._get(session, "token")
        assert sync_client._get(session, "token_issued_at"), "a new token is dated"
        # A quarter of a year later...
        sync_client._set(session, "token_issued_at",
                         (datetime.now(timezone.utc) - timedelta(days=100)).isoformat())
    with session_scope() as session:
        sync_client.run(session, transport)
        second = sync_client._get(session, "token")
    assert second != first
    with session_scope() as session:
        sync_client.run(session, transport)  # and it keeps working with the new one
        assert sync_client._get(session, "token") == second


# --------------------------------------------------------------------------- #
# Where the data lives
# --------------------------------------------------------------------------- #


def test_the_database_url_is_read_the_way_hosts_write_it(tmp_path):
    sys.path.insert(0, str(SYNC_DIR))
    try:
        import storage

        assert storage.database_url({"VG_SYNC_DATABASE_URL": "postgres://u:p@db.example:5432/vg"}, tmp_path) == \
            "postgresql+psycopg://u:p@db.example:5432/vg"
        assert storage.database_url({"VG_SYNC_DATABASE_URL": "postgresql://u:p@h/vg"}, tmp_path).startswith(
            "postgresql+psycopg://")
        sqlite = storage.database_url({"VG_SYNC_DB": str(tmp_path / "s.db")}, tmp_path / "default.db")
        assert sqlite.startswith("sqlite:///") and sqlite.endswith("/s.db")
    finally:
        sys.path.remove(str(SYNC_DIR))
