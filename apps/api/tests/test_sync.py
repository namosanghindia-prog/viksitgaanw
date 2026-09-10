"""Cloud sync, end to end against the real sync server.

This device is the app under test. A second device is played by calling the
sync server directly, the way another phone's sync worker would.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.models import InvestmentInterest, Notification, Profile, SyncQueueEntry
from app.services import sync_client

from .test_marketplace import make_owner, request_body
from .test_profiles import farmer_body

SYNC_DIR = Path(__file__).resolve().parents[2] / "sync"


@pytest.fixture()
def server(monkeypatch):
    """A fresh sync server with its own throwaway database."""
    monkeypatch.setenv("VG_SYNC_DB", str(Path(tempfile.mkdtemp()) / "sync.db"))
    sys.path.insert(0, str(SYNC_DIR))
    module = importlib.reload(importlib.import_module("server"))
    yield TestClient(module.app)
    sys.path.remove(str(SYNC_DIR))


class ServerTransport:
    """The app's sync worker, talking to the TestClient instead of a socket."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    @staticmethod
    def _auth(token):
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _check(self, response):
        if response.status_code >= 400:
            raise sync_client.SyncError(response.text, response.status_code)
        return response

    def post(self, path, body, token=None):
        return self._check(self.client.post(path, json=body, headers=self._auth(token))).json()

    def get(self, path, params, token):
        return self._check(self.client.get(path, params=params, headers=self._auth(token))).json()

    def put_bytes(self, path, data, headers, token):
        return self._check(self.client.put(path, content=data, headers={**headers, **self._auth(token)})).json()

    def get_bytes(self, path, token):
        response = self._check(self.client.get(path, headers=self._auth(token)))
        return response.content, dict(response.headers)


class OtherDevice:
    """A second phone: registers, pushes and pulls through the server API."""

    def __init__(self, server: TestClient, profile: dict) -> None:
        self.server = server
        self.profile = profile
        answer = server.post("/v1/devices", json={"profile_id": profile["id"], "segment": profile["segment"]}).json()
        self.headers = {"Authorization": f"Bearer {answer['token']}"}
        self.rev = 0

    def push(self, *records) -> dict:
        return self.server.post("/v1/push", json={"records": list(records)}, headers=self.headers).json()

    def pull(self) -> list[dict]:
        answer = self.server.get("/v1/pull", params={"since": self.rev}, headers=self.headers).json()
        self.rev = answer["nextRev"]
        return answer["records"]


INVESTOR = {
    "id": "a0000000-0000-0000-0000-000000000001",
    "segment": "investor_india",
    "display_name": "Priya Sharma",
    "organisation_name": "Sharma Agri",
    "phone": "+919111111111",
    "email": "priya@example.com",
    "preferred_language": "en",
    "country_code": "IN",
    "details": {"investor_type": "family_office", "modes": ["revenue_share"]},
    "kyc_status": "unverified",
    "visibility": "online",
}


def run(client_transport) -> sync_client.RunResult:
    with session_scope() as session:
        return sync_client.run(session, client_transport)


def test_sync_is_off_until_configured(client):
    make_owner(client, farmer_body())
    status = client.get("/api/v1/sync/status").json()
    assert status["enabled"] is False
    assert client.post("/api/v1/sync/run").status_code == 409
    bad = client.put("/api/v1/sync/config", json={"serverUrl": "not a url"})
    assert bad.status_code == 422
    on = client.put("/api/v1/sync/config", json={"serverUrl": "http://127.0.0.1:8900/"}).json()
    assert on["enabled"] and on["serverUrl"] == "http://127.0.0.1:8900"


def test_two_devices_meet_through_the_server(client, server, parcel_id):
    transport = ServerTransport(server)
    farmer = make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})

    # Private things stay home: a diary entry, and a request not yet shared.
    client.post(f"/api/v1/land-parcels/{parcel_id}/diary", json={"activity": "sowing", "entryDate": "2026-06-01"})
    request = client.post("/api/v1/investment-requests", json=request_body(parcel_id)).json()
    first = run(transport)
    assert first.errors == []
    with session_scope() as session:
        held = session.scalars(select(SyncQueueEntry.entity_type).where(SyncQueueEntry.status == "held")).all()
    assert "diary_entry" in held and "land_parcel" in held and "investment_request" in held

    # Now it is shared, and reaches another device -- without the phone number.
    client.post(f"/api/v1/investment-requests/{request['id']}/share")
    assert run(transport).pushed >= 1

    investor = OtherDevice(server, INVESTOR)
    investor.push({"entity_type": "profile", "entity_id": INVESTOR["id"], "payload": INVESTOR})
    seen = investor.pull()
    types = {r["entityType"] for r in seen}
    assert {"profile", "investment_request"} <= types and "diary_entry" not in types
    farmer_record = next(r for r in seen if r["entityType"] == "profile")
    assert farmer_record["payload"]["phone"] is None, "no contact before a match"
    assert "parcel_id" not in next(r for r in seen if r["entityType"] == "investment_request")["payload"]

    # The investor may not rewrite the farmer's request.
    tampered = dict(next(r for r in seen if r["entityType"] == "investment_request")["payload"], title="Mine now")
    answer = investor.push({"entity_type": "investment_request", "entity_id": request["id"], "payload": tampered})
    assert answer["rejected"] and answer["accepted"] == 0

    # The investor answers; it arrives here as an interest and a notification.
    interest_id = "b0000000-0000-0000-0000-000000000002"
    answer = investor.push({
        "entity_type": "investment_interest",
        "entity_id": interest_id,
        "payload": {
            "id": interest_id, "request_id": request["id"], "profile_id": INVESTOR["id"], "kind": "investment",
            "amount_offered": 300000, "mode": "revenue_share", "message": "Keen to fund this.", "status": "sent",
            "created_at": "2026-09-10T08:00:00+00:00", "updated_at": "2026-09-10T08:00:00+00:00",
        },
    })
    assert answer["accepted"] == 1, answer
    assert run(transport).pulled >= 2
    with session_scope() as session:
        interest = session.get(InvestmentInterest, interest_id)
        assert interest is not None and interest.origin == "synced"
        kinds = list(session.scalars(select(Notification.kind)))
        synced_investor = session.get(Profile, INVESTOR["id"])
    assert "interest_received" in kinds
    assert synced_investor.phone is None

    # The farmer accepts; the investor's device learns it -- and only now
    # sees the farmer's phone number.
    client.patch(f"/api/v1/investment-interests/{interest_id}", json={"status": "accepted"})
    run(transport)
    after = investor.pull()
    status = next(r for r in after if r["entityType"] == "investment_interest")["payload"]["status"]
    assert status == "accepted"
    investor.rev = 0
    everything = investor.pull()
    farmer_card = next(r for r in everything if r["entityType"] == "profile" and r["entityId"] == farmer["id"])
    assert farmer_card["payload"]["phone"] == "+919876543210"


def test_taking_an_item_offline_withdraws_it(client, server, parcel_id):
    transport = ServerTransport(server)
    make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    request = client.post("/api/v1/investment-requests", json=request_body(parcel_id)).json()
    client.post(f"/api/v1/investment-requests/{request['id']}/share")
    run(transport)

    investor = OtherDevice(server, INVESTOR)
    investor.push({"entity_type": "profile", "entity_id": INVESTOR["id"], "payload": INVESTOR})
    assert any(r["entityType"] == "investment_request" for r in investor.pull())

    client.post(f"/api/v1/investment-requests/{request['id']}/unshare")
    run(transport)
    tombstone = [r for r in investor.pull() if r["entityType"] == "investment_request"]
    assert tombstone and tombstone[0]["deleted"] is True


def test_a_profile_cannot_be_claimed_twice(server):
    OtherDevice(server, INVESTOR)
    again = server.post("/v1/devices", json={"profile_id": INVESTOR["id"], "segment": "investor_india"})
    assert again.status_code == 409


def test_requests_reach_only_the_audiences_chosen(client, server, parcel_id):
    transport = ServerTransport(server)
    make_owner(client, farmer_body())
    client.put("/api/v1/sync/config", json={"serverUrl": "http://sync.test"})
    request = client.post(
        "/api/v1/investment-requests",
        json=request_body(parcel_id, openTo=["investor_india", "partner_national"]),
    ).json()
    client.post(f"/api/v1/investment-requests/{request['id']}/share")
    run(transport)

    abroad = dict(INVESTOR, id="c0000000-0000-0000-0000-000000000003", segment="investor_international", country_code="GB")
    device = OtherDevice(server, abroad)
    assert not any(r["entityType"] == "investment_request" for r in device.pull())


def teardown_module(_module):
    os.environ.pop("VG_SYNC_DB", None)
