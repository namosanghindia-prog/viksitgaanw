"""ViksitGaanw sync server -- where shared items travel between devices.

    python -m uvicorn server:app --app-dir apps/sync --port 8900

Every device keeps its own database and works offline. When online, its sync
worker pushes what the owner has *shared* and pulls what the owner may *see*.
This server holds only that: shared profiles, projects, machines and groups;
cards of plots shared with connections, and farm updates; and the private
records two parties exchange (connection requests, interests, enquiries,
partnerships, messages, deals, disputes, ratings). The land parcels
themselves, diaries, reports and anything still offline never arrive here.

Privacy is enforced here, not trusted to clients:

* Each record has an **audience**: public items go to the kinds of profile
  their owner chose; shared land and farm updates go only to the owner's
  connections; private items go only to the parties named in them.
* A device may only write records its owner is entitled to write. The other
  party to an interest, an enquiry or a partnership may change its status and
  nothing else.
* Phone numbers, email addresses and insurance policy numbers are removed
  from what a device pulls unless its owner is actually connected to that
  person -- an accepted connection request, interest or enquiry, an active
  partnership, a deal, the same group.
* When two people become connected, what each had already shared is sent to
  the other on their next pull.

> [!WARNING]
> Development server. It is meant to run on a laptop or a LAN while the
> platform is built. It has no rate limiting, no TLS of its own and no
> backups; do not expose it to the internet.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

DB_PATH = Path(os.environ.get("VG_SYNC_DB", Path(__file__).parent / "data" / "sync.db"))

#: Records anyone in the audience may read.
PUBLIC_TYPES = {"profile", "investment_request", "equipment_listing", "farmer_group", "rating", "insurance_policy"}
#: Records only the parties named in them may read.
#: Records only the owner's connections may read.
CONNECTION_TYPES = {"land_share", "farm_update"}
PRIVATE_TYPES = {
    "connection",
    "investment_interest",
    "equipment_enquiry",
    "equipment_partnership",
    "message",
    "deal",
    "dispute",
    "group_member",
}
KNOWN_TYPES = PUBLIC_TYPES | PRIVATE_TYPES | CONNECTION_TYPES
#: Records that link two people, and the statuses at which they do.
LINKS = {
    "connection": {"accepted"},
    "investment_interest": {"accepted"},
    "equipment_enquiry": {"accepted"},
    "equipment_partnership": {"active"},
    "group_member": {"active"},
    "deal": {"drafting", "active", "disputed", "completed"},
}
#: What a newly connected person should now receive from the other.
RESEND_ON_CONNECT = ("profile", "land_share", "farm_update", "insurance_policy")
#: Fields the counterparty may change on a record someone else created.
COUNTERPARTY_FIELDS = {"status", "responded_at", "updated_at"}

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        with _lock:
            yield connection
            connection.commit()
    finally:
        connection.close()


def init() -> None:
    with db() as con:
        con.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                profile_id TEXT NOT NULL,
                segment TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen TEXT
            );
            CREATE TABLE IF NOT EXISTS records (
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                owner_profile_id TEXT NOT NULL,
                parties TEXT NOT NULL DEFAULT '[]',
                payload TEXT NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0,
                rev INTEGER NOT NULL,
                writer_device TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (entity_type, entity_id)
            );
            CREATE INDEX IF NOT EXISTS ix_records_rev ON records (rev);
            CREATE TABLE IF NOT EXISTS media (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                owner_profile_id TEXT NOT NULL,
                mime TEXT NOT NULL,
                body BLOB NOT NULL,
                meta TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
            INSERT OR IGNORE INTO counters VALUES ('rev', 0);
            """
        )


def _next_rev(con: sqlite3.Connection) -> int:
    con.execute("UPDATE counters SET value = value + 1 WHERE name = 'rev'")
    return con.execute("SELECT value FROM counters WHERE name = 'rev'").fetchone()[0]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


app = FastAPI(title="ViksitGaanw sync server", version="0.1.0")
init()


class Device(BaseModel):
    id: str
    profile_id: str
    segment: str


def device(authorization: str = Header(default="")) -> Device:
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing device token.")
    with db() as con:
        row = con.execute("SELECT * FROM devices WHERE token_hash = ?", (_hash(token),)).fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="Unknown device.")
        con.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (_now(), row["id"]))
    return Device(id=row["id"], profile_id=row["profile_id"], segment=row["segment"])


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


class RegisterIn(BaseModel):
    profile_id: str = Field(min_length=1, max_length=36)
    segment: str = Field(min_length=1, max_length=32)


@app.post("/v1/devices")
def register(body: RegisterIn) -> dict[str, str]:
    """Register a device for its owner's profile and hand back its token."""
    token = secrets.token_urlsafe(32)
    device_id = secrets.token_hex(8)
    with db() as con:
        # The first device to register a profile owns it. Another device
        # claiming the same id is refused, so nobody can pull someone else's
        # private records by knowing their profile id.
        if con.execute("SELECT 1 FROM devices WHERE profile_id = ?", (body.profile_id,)).fetchone():
            raise HTTPException(status_code=409, detail="That profile is already registered to a device.")
        con.execute(
            "INSERT INTO devices (id, token_hash, profile_id, segment, created_at) VALUES (?, ?, ?, ?, ?)",
            (device_id, _hash(token), body.profile_id, body.segment, _now()),
        )
    return {"deviceId": device_id, "token": token}


# --------------------------------------------------------------------------- #
# Who may write, and who may read
# --------------------------------------------------------------------------- #


def _stored(con: sqlite3.Connection, entity_type: str, entity_id: str | None) -> sqlite3.Row | None:
    if not entity_id:
        return None
    return con.execute(
        "SELECT * FROM records WHERE entity_type=? AND entity_id=?", (entity_type, entity_id)
    ).fetchone()


def _owner_of(con: sqlite3.Connection, entity_type: str, entity_id: str | None) -> str | None:
    row = _stored(con, entity_type, entity_id)
    return row["owner_profile_id"] if row else None


def _rules(con: sqlite3.Connection, entity_type: str, payload: dict[str, Any]) -> tuple[str, list[str]]:
    """(owner profile, parties) for a record, from its own content."""
    p = payload
    if entity_type == "profile":
        return p["id"], []
    if entity_type in ("investment_request", "equipment_listing", "land_share", "farm_update"):
        return p["profile_id"], []
    if entity_type == "connection":
        return p["requester_profile_id"], [p["requester_profile_id"], p["addressee_profile_id"]]
    if entity_type == "farmer_group":
        return p["owner_profile_id"], []
    if entity_type == "rating":
        return p["rater_profile_id"], []
    if entity_type == "insurance_policy":
        owner = _owner_of(con, "investment_request", p.get("request_id"))
        if owner is None:
            raise HTTPException(status_code=422, detail="Insurance syncs only with a shared request.")
        return owner, []
    if entity_type == "investment_interest":
        return p["profile_id"], [p["profile_id"], _owner_of(con, "investment_request", p["request_id"]) or ""]
    if entity_type == "equipment_enquiry":
        return p["profile_id"], [p["profile_id"], _owner_of(con, "equipment_listing", p["listing_id"]) or ""]
    if entity_type == "equipment_partnership":
        first = p["seller_profile_id"] if p.get("initiated_by") == "seller" else p["partner_profile_id"]
        return first, [p["seller_profile_id"], p.get("partner_profile_id") or ""]
    if entity_type == "message":
        return p["sender_profile_id"], [p["sender_profile_id"], p["recipient_profile_id"]]
    if entity_type == "deal":
        return p["proposed_by"], [p["farmer_profile_id"], p["investor_profile_id"]]
    if entity_type == "dispute":
        deal = _stored(con, "deal", p["deal_id"])
        parties = json.loads(deal["parties"]) if deal else []
        return p["opened_by_profile_id"], parties
    if entity_type == "group_member":
        group_owner = _owner_of(con, "farmer_group", p["group_id"]) or ""
        return p.get("profile_id") or group_owner, [p.get("profile_id") or "", group_owner]
    raise HTTPException(status_code=422, detail=f"Unknown record type {entity_type}.")


def _links(con: sqlite3.Connection, a: str) -> set[str]:
    """Everyone profile a is connected to: agreed, or working together."""
    out: set[str] = set()
    active_groups: set[str] = set()
    members: list[tuple[str, set[str]]] = []
    placeholders = ",".join("?" * len(LINKS))
    for row in con.execute(
        f"SELECT entity_type, payload, parties FROM records WHERE deleted = 0 AND entity_type IN ({placeholders})",
        tuple(LINKS),
    ):
        parties = set(json.loads(row["parties"]))
        payload = json.loads(row["payload"])
        linked = payload.get("status") in LINKS[row["entity_type"]]
        if row["entity_type"] == "group_member" and linked:
            members.append((payload.get("group_id"), parties))
            if a in parties:
                active_groups.add(payload.get("group_id"))
        if a in parties and linked:
            out |= parties
    # Members of the same group are connected to each other, not only to its organiser.
    for group_id, parties in members:
        if group_id in active_groups:
            out |= parties
    out.discard("")
    out.discard(a)
    return out


def _connected(con: sqlite3.Connection, a: str, b: str) -> bool:
    """Whether profiles a and b are connected."""
    return a == b or b in _links(con, a)


def _resend(con: sqlite3.Connection, parties: list[str]) -> None:
    """Two people just connected: put what each shared back in the feed.

    Pull is incremental, so a plot shared last month would otherwise never
    reach someone who connected today -- nor would the phone number the
    connection now reveals.
    """
    placeholders = ",".join("?" * len(RESEND_ON_CONNECT))
    for owner in parties:
        rows = con.execute(
            f"SELECT entity_type, entity_id FROM records WHERE owner_profile_id = ? AND deleted = 0 "
            f"AND entity_type IN ({placeholders})",
            (owner, *RESEND_ON_CONNECT),
        ).fetchall()
        for row in rows:
            con.execute(
                "UPDATE records SET rev = ? WHERE entity_type = ? AND entity_id = ?",
                (_next_rev(con), row["entity_type"], row["entity_id"]),
            )


def _visible(con: sqlite3.Connection, row: sqlite3.Row, puller: Device) -> bool:
    if row["entity_type"] in PRIVATE_TYPES:
        return puller.profile_id in json.loads(row["parties"])
    if row["deleted"]:
        return True
    payload = json.loads(row["payload"])
    if row["entity_type"] == "investment_request":
        return puller.profile_id == row["owner_profile_id"] or puller.segment in payload.get("open_to", [])
    if row["entity_type"] == "insurance_policy":
        request = _stored(con, "investment_request", payload.get("request_id"))
        return bool(request) and _visible(con, request, puller)
    if row["entity_type"] in CONNECTION_TYPES:
        return _connected(con, puller.profile_id, row["owner_profile_id"])
    return True


def _redact(con: sqlite3.Connection, row: sqlite3.Row, puller: Device) -> dict[str, Any]:
    payload = json.loads(row["payload"])
    if row["deleted"]:
        return {"id": row["entity_id"]}
    if row["entity_type"] == "profile" and not _connected(con, puller.profile_id, row["entity_id"]):
        payload["phone"] = None
        payload["email"] = None
    if row["entity_type"] == "insurance_policy" and not _connected(con, puller.profile_id, row["owner_profile_id"]):
        number = payload.get("policy_number")
        payload["policy_number"] = f"••••{number[-4:]}" if number and len(number) > 4 else None
        payload["premium"] = None
        payload["notes"] = None
    if row["entity_type"] == "equipment_partnership" and puller.profile_id != payload.get("seller_profile_id"):
        payload["contact_name"] = None
        payload["contact_phone"] = None
    return payload


# --------------------------------------------------------------------------- #
# Push and pull
# --------------------------------------------------------------------------- #


class RecordIn(BaseModel):
    entity_type: str
    entity_id: str
    deleted: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


class PushIn(BaseModel):
    records: list[RecordIn] = Field(max_length=500)


@app.post("/v1/push")
def push(body: PushIn, me: Device = Depends(device)) -> dict[str, Any]:
    accepted, rejected = 0, []
    with db() as con:
        for record in body.records:
            try:
                if record.entity_type not in KNOWN_TYPES:
                    raise HTTPException(status_code=422, detail="unknown type")
                existing = _stored(con, record.entity_type, record.entity_id)
                if record.deleted:
                    if existing is None:
                        accepted += 1
                        continue
                    if existing["owner_profile_id"] != me.profile_id:
                        raise HTTPException(status_code=403, detail="not yours to delete")
                    con.execute(
                        "UPDATE records SET deleted=1, payload='{}', rev=?, writer_device=?, updated_at=? "
                        "WHERE entity_type=? AND entity_id=?",
                        (_next_rev(con), me.id, _now(), record.entity_type, record.entity_id),
                    )
                    accepted += 1
                    continue

                payload = dict(record.payload)
                owner, parties = _rules(con, record.entity_type, payload)
                parties = [p for p in parties if p]
                if existing is not None and existing["owner_profile_id"] != me.profile_id:
                    # The counterparty may only answer: change the status.
                    if me.profile_id not in json.loads(existing["parties"]):
                        raise HTTPException(status_code=403, detail="not yours to change")
                    merged = json.loads(existing["payload"])
                    for field in COUNTERPARTY_FIELDS:
                        if field in payload:
                            merged[field] = payload[field]
                    if record.entity_type == "deal":
                        # Both sides of a deal legitimately edit it.
                        merged = payload
                    payload, owner = merged, existing["owner_profile_id"]
                elif existing is None and owner != me.profile_id and me.profile_id not in parties:
                    raise HTTPException(status_code=403, detail="not yours to create")
                elif (
                    existing is None
                    and record.entity_type in PUBLIC_TYPES | CONNECTION_TYPES
                    and owner != me.profile_id
                ):
                    raise HTTPException(status_code=403, detail="not yours to create")

                was = json.loads(existing["payload"]).get("status") if existing is not None else None

                con.execute(
                    "INSERT INTO records (entity_type, entity_id, owner_profile_id, parties, payload, deleted, "
                    "rev, writer_device, updated_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?) "
                    "ON CONFLICT (entity_type, entity_id) DO UPDATE SET payload=excluded.payload, "
                    "parties=excluded.parties, deleted=0, rev=excluded.rev, writer_device=excluded.writer_device, "
                    "updated_at=excluded.updated_at",
                    (
                        record.entity_type,
                        record.entity_id,
                        owner,
                        json.dumps(sorted(set(parties))),
                        json.dumps(payload),
                        _next_rev(con),
                        me.id,
                        _now(),
                    ),
                )
                status = payload.get("status")
                if record.entity_type in LINKS and status in LINKS[record.entity_type] and status != was:
                    _resend(con, parties)
                accepted += 1
            except HTTPException as exc:
                rejected.append({"entityType": record.entity_type, "entityId": record.entity_id, "reason": exc.detail})
            except (KeyError, TypeError) as exc:
                rejected.append({"entityType": record.entity_type, "entityId": record.entity_id, "reason": f"missing {exc}"})
    return {"accepted": accepted, "rejected": rejected}


@app.get("/v1/pull")
def pull(since: int = 0, limit: int = 500, me: Device = Depends(device)) -> dict[str, Any]:
    """Records changed since ``since`` that this device may see, oldest first.

    A device's own writes are not sent back to it.
    """
    limit = max(1, min(limit, 1000))
    out: list[dict[str, Any]] = []
    last = since
    with db() as con:
        rows = con.execute(
            "SELECT * FROM records WHERE rev > ? ORDER BY rev LIMIT ?", (since, limit)
        ).fetchall()
        for row in rows:
            last = row["rev"]
            if row["writer_device"] == me.id or not _visible(con, row, me):
                continue
            out.append(
                {
                    "entityType": row["entity_type"],
                    "entityId": row["entity_id"],
                    "deleted": bool(row["deleted"]),
                    "payload": _redact(con, row, me),
                    "rev": row["rev"],
                }
            )
    return {"records": out, "nextRev": last, "more": len(rows) == limit}


# --------------------------------------------------------------------------- #
# Pictures
# --------------------------------------------------------------------------- #


@app.put("/v1/media/{media_id}")
async def put_media(
    media_id: str,
    request: Request,
    x_entity_type: str = Header(),
    x_entity_id: str = Header(),
    x_media_meta: str = Header(default="{}"),
    me: Device = Depends(device),
) -> dict[str, str]:
    body = await request.body()
    if not body or len(body) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Picture missing or too large.")
    with db() as con:
        con.execute(
            "INSERT OR REPLACE INTO media (id, entity_type, entity_id, owner_profile_id, mime, body, meta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (media_id, x_entity_type, x_entity_id, me.profile_id,
             request.headers.get("content-type", "image/jpeg"), body, x_media_meta),
        )
    return {"id": media_id}


@app.get("/v1/media/{media_id}")
def get_media(media_id: str, me: Device = Depends(device)) -> Response:
    with db() as con:
        row = con.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Picture not found.")
        record_type = {
            "profile": "profile",
            "equipment": "equipment_listing",
            "milestone": "deal",
            "land": "land_share",
            "update": "farm_update",
        }.get(row["entity_type"])
        if record_type == "deal":
            owner_row = con.execute(
                "SELECT * FROM records WHERE entity_type='deal' AND payload LIKE ?", (f'%{row["entity_id"]}%',)
            ).fetchone()
        else:
            owner_row = _stored(con, record_type, row["entity_id"]) if record_type else None
        if owner_row is None or not _visible(con, owner_row, me):
            raise HTTPException(status_code=404, detail="Picture not found.")
    return Response(content=row["body"], media_type=row["mime"], headers={"X-Media-Meta": row["meta"]})


@app.get("/v1/health")
def health() -> dict[str, Any]:
    with db() as con:
        records = con.execute("SELECT COUNT(*) FROM records WHERE deleted = 0").fetchone()[0]
        devices = con.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    return {"status": "ok", "records": records, "devices": devices}
