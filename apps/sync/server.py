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

It is also where **video uploads** go through. Subscribers may upload a video
file instead of linking one on YouTube; the file itself goes straight from the
device to Mux, but only this server holds the Mux keys (``MUX_TOKEN_ID`` and
``MUX_TOKEN_SECRET``, from the environment or ``apps/sync/.env``). It checks
the subscription, asks Mux for a one-off upload address, and later tells the
device the playback id.

And it is where **subscriptions are paid for**. A subscription is prepaid for
a number of months, through a Razorpay Payment Link that opens in the
browser: UPI, cards or netbanking, and nothing to install. The Razorpay keys
(``RAZORPAY_KEY_ID``, ``RAZORPAY_KEY_SECRET`` and, for its webhook,
``RAZORPAY_WEBHOOK_SECRET``) live here too. A payment counts once Razorpay
says so -- by its signed webhook, or when the device asks and this server
checks the link -- and it counts exactly once, whichever comes first. Plans
and their prices are set by whoever runs the server, with
``python apps/sync/admin.py``, which can also grant a subscription by hand.

> [!WARNING]
> Development server. It is meant to run on a laptop or a LAN while the
> platform is built. It has no rate limiting, no TLS of its own and no
> backups; do not expose it to the internet.
"""

from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from base64 import b64encode
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field


def _load_env_file(path: Path) -> None:
    """KEY=VALUE lines from ``apps/sync/.env``, for keys not already set.

    Keeps the Mux keys out of shell history on a Windows laptop. The file is
    git-ignored; never commit it.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(Path(__file__).parent / ".env")

DB_PATH = Path(os.environ.get("VG_SYNC_DB", Path(__file__).parent / "data" / "sync.db"))

#: Records anyone in the audience may read.
PUBLIC_TYPES = {"profile", "investment_request", "equipment_listing", "farmer_group", "rating", "insurance_policy"}
#: Records only the owner's connections may read.
CONNECTION_TYPES = {"land_share", "farm_update"}
#: Records only the parties named in them may read.
PRIVATE_TYPES = {
    "connection",
    "project_invite",
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
    "equipment_enquiry": {"accepted", "completed"},
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
            CREATE TABLE IF NOT EXISTS subscriptions (
                profile_id TEXT PRIMARY KEY,
                plan TEXT NOT NULL,
                until TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS video_uploads (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                target TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                asset_id TEXT,
                playback_id TEXT,
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plans (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                amount_paise INTEGER NOT NULL,
                months INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            -- Amount and months are copied from the plan when the link is
            -- made, so a later price change never alters a link already out.
            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                plan TEXT NOT NULL,
                plan_name TEXT NOT NULL,
                amount_paise INTEGER NOT NULL,
                months INTEGER NOT NULL,
                link_id TEXT UNIQUE,
                url TEXT,
                status TEXT NOT NULL,
                provider_payment_id TEXT,
                until_after TEXT,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                paid_at TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_payments_profile ON payments (profile_id);
            CREATE TABLE IF NOT EXISTS webhook_events (id TEXT PRIMARY KEY, received_at TEXT NOT NULL);
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


#: What a rating may be about: the record it names, and the states in which
#: the two sides have actually worked together.
RATABLE = {
    "deal": ("deal", {"completed"}),
    "enquiry": ("equipment_enquiry", {"completed"}),
    "partnership": ("equipment_partnership", {"active", "ended"}),
}


def _check_rating(con: sqlite3.Connection, p: dict[str, Any]) -> None:
    """A rating is public, so it must be about real work the two did together.

    Without this, anyone could push stars for anyone. The work itself -- the
    deal, the hire, the partnership -- is on this server with both people
    named in it, and must have reached a state where rating makes sense.
    """
    kind = RATABLE.get(p.get("context_type"))
    if kind is None:
        raise HTTPException(status_code=422, detail="A rating must be about a deal, a hire or sale, or a partnership.")
    if not 1 <= int(p.get("stars") or 0) <= 5:
        raise HTTPException(status_code=422, detail="Stars are 1 to 5.")
    rater, rated = p.get("rater_profile_id"), p.get("rated_profile_id")
    work = _stored(con, kind[0], p.get("context_id"))
    if work is None or not rater or not rated or rater == rated:
        raise HTTPException(status_code=403, detail="not a rating for work this server knows of")
    parties = set(json.loads(work["parties"]))
    if not {rater, rated} <= parties or json.loads(work["payload"]).get("status") not in kind[1]:
        raise HTTPException(status_code=403, detail="not a rating for work the two finished together")


def _rules(con: sqlite3.Connection, entity_type: str, payload: dict[str, Any]) -> tuple[str, list[str]]:
    """(owner profile, parties) for a record, from its own content."""
    p = payload
    if entity_type == "profile":
        return p["id"], []
    if entity_type in ("investment_request", "equipment_listing", "land_share", "farm_update"):
        return p["profile_id"], []
    if entity_type == "connection":
        return p["requester_profile_id"], [p["requester_profile_id"], p["addressee_profile_id"]]
    if entity_type == "project_invite":
        # The farmer sends it; the investor may only answer it.
        return p["farmer_profile_id"], [p["farmer_profile_id"], p["investor_profile_id"]]
    if entity_type == "farmer_group":
        return p["owner_profile_id"], []
    if entity_type == "rating":
        _check_rating(con, p)
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


# --------------------------------------------------------------------------- #
# Subscriptions and video uploads
# --------------------------------------------------------------------------- #

#: Largest video a device may send, matching the app's own limit.
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
#: How long Mux keeps an upload address open: a week, so a village upload cut
#: off for days can still finish.
UPLOAD_TIMEOUT_SECONDS = 7 * 24 * 60 * 60
VIDEO_TARGETS = {"biodata", "listing", "land", "request", "machine", "group"}


def _api_call(service: str, url: str, user: str, password: str, method: str, body: dict | None) -> dict:
    """One JSON call to a provider's API with HTTP Basic auth; its errors as HTTP errors."""
    auth = b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise HTTPException(status_code=502, detail=f"{service} said {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=503, detail=f"{service} not reachable: {exc}") from exc


class MuxClient:
    """The few Mux Video API calls direct uploads need.

    https://www.mux.com/docs/guides/upload-files-directly
    """

    base = "https://api.mux.com"

    def __init__(self) -> None:
        self.token_id = os.environ.get("MUX_TOKEN_ID", "")
        self.token_secret = os.environ.get("MUX_TOKEN_SECRET", "")

    @property
    def configured(self) -> bool:
        return bool(self.token_id and self.token_secret)

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        return _api_call("Mux", self.base + path, self.token_id, self.token_secret, method, body)["data"]

    def create_upload(self, passthrough: str) -> dict:
        return self._call("POST", "/video/v1/uploads", {
            # The file comes from the villager's device, not from a web page.
            "cors_origin": "*",
            "timeout": UPLOAD_TIMEOUT_SECONDS,
            "new_asset_settings": {
                "playback_policy": ["public"],
                "video_quality": "basic",
                "passthrough": passthrough[:255],
            },
        })

    def get_upload(self, upload_id: str) -> dict:
        return self._call("GET", f"/video/v1/uploads/{upload_id}")

    def get_asset(self, asset_id: str) -> dict:
        return self._call("GET", f"/video/v1/assets/{asset_id}")


#: Replaced in tests.
mux = MuxClient()


def subscription(con: sqlite3.Connection, profile_id: str) -> dict[str, Any] | None:
    row = con.execute("SELECT * FROM subscriptions WHERE profile_id = ?", (profile_id,)).fetchone()
    if row is None:
        return None
    active = row["until"] is None or date.fromisoformat(row["until"]) >= date.today()
    return {"plan": row["plan"], "until": row["until"], "active": active}


@app.get("/v1/me")
def me_info(me: Device = Depends(device)) -> dict[str, Any]:
    """What this device's owner may do here: their subscription, and whether uploads are on."""
    with db() as con:
        return {
            "profileId": me.profile_id,
            "subscription": subscription(con, me.profile_id),
            "videoUploads": mux.configured,
        }


class VideoUploadIn(BaseModel):
    target: str
    entity_id: str = Field(min_length=1, max_length=36)
    size: int = Field(ge=1)


@app.post("/v1/videos/uploads")
def create_video_upload(body: VideoUploadIn, me: Device = Depends(device)) -> dict[str, str]:
    """A one-off address the device sends its video file to, for subscribers."""
    if not mux.configured:
        raise HTTPException(status_code=503, detail="Video uploads are not switched on on this server.")
    if body.target not in VIDEO_TARGETS:
        raise HTTPException(status_code=422, detail="Videos cannot be added there.")
    if body.size > MAX_VIDEO_BYTES:
        raise HTTPException(status_code=413, detail="Videos can be up to 2 GB.")
    with db() as con:
        plan = subscription(con, me.profile_id)
    if not plan or not plan["active"]:
        raise HTTPException(status_code=402, detail="Uploading videos directly is for subscribers.")
    upload = mux.create_upload(f"{me.profile_id}:{body.target}:{body.entity_id}")
    with db() as con:
        con.execute(
            "INSERT INTO video_uploads (id, profile_id, target, entity_id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'waiting', ?, ?)",
            (upload["id"], me.profile_id, body.target, body.entity_id, _now(), _now()),
        )
    return {"uploadId": upload["id"], "url": upload["url"]}


@app.get("/v1/videos/uploads/{upload_id}")
def video_upload_status(upload_id: str, me: Device = Depends(device)) -> dict[str, Any]:
    """Where an upload has got to: waiting, processing, ready (with a playback id), errored or timed_out."""
    with db() as con:
        row = con.execute(
            "SELECT * FROM video_uploads WHERE id = ? AND profile_id = ?", (upload_id, me.profile_id)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if row["status"] in ("ready", "errored"):
        return {"status": row["status"], "playbackId": row["playback_id"], "error": row["error"]}

    status, asset_id, playback_id, error = "waiting", row["asset_id"], None, None
    if not asset_id:
        upload = mux.get_upload(upload_id)
        asset_id = upload.get("asset_id")
        if upload.get("status") in ("errored", "cancelled"):
            status = "errored"
            error = (upload.get("error") or {}).get("message")
        elif upload.get("status") == "timed_out":
            status = "timed_out"
    if asset_id:
        asset = mux.get_asset(asset_id)
        if asset.get("status") == "ready":
            playback_id = next(
                (p["id"] for p in asset.get("playback_ids", []) if p.get("policy") == "public"), None
            )
            status = "ready" if playback_id else "errored"
        elif asset.get("status") == "errored":
            status = "errored"
            error = "; ".join((asset.get("errors") or {}).get("messages", [])) or None
        else:
            status = "processing"
    with db() as con:
        con.execute(
            "UPDATE video_uploads SET asset_id = ?, playback_id = ?, status = ?, error = ?, updated_at = ? "
            "WHERE id = ?",
            (asset_id, playback_id, status, error, _now(), upload_id),
        )
    return {"status": status, "playbackId": playback_id, "error": error}


# --------------------------------------------------------------------------- #
# Paying for a subscription
# --------------------------------------------------------------------------- #

#: How long a payment link stays open. Razorpay wants at least 15 minutes; two
#: days lets someone borrow a phone with UPI tomorrow.
LINK_LIFETIME_SECONDS = 2 * 24 * 60 * 60


class RazorpayClient:
    """Razorpay Payment Links: the few calls a prepaid subscription needs.

    https://razorpay.com/docs/api/payments/payment-links/
    """

    base = "https://api.razorpay.com"

    def __init__(self) -> None:
        self.key_id = os.environ.get("RAZORPAY_KEY_ID", "")
        self.key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
        self.webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

    @property
    def configured(self) -> bool:
        return bool(self.key_id and self.key_secret)

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        return _api_call("Razorpay", self.base + path, self.key_id, self.key_secret, method, body)

    def create_link(self, *, amount_paise: int, reference_id: str, description: str, expire_by: int,
                    notes: dict[str, str]) -> dict:
        return self._call("POST", "/v1/payment_links", {
            "amount": amount_paise,
            "currency": "INR",
            "accept_partial": False,
            "reference_id": reference_id,
            "description": description[:2048],
            "expire_by": expire_by,
            "notes": notes,
            "reminder_enable": False,
        })

    def get_link(self, link_id: str) -> dict:
        return self._call("GET", f"/v1/payment_links/{link_id}")

    def signature_ok(self, body: bytes, signature: str) -> bool:
        """Whether a webhook really came from Razorpay: HMAC-SHA256 of the raw body."""
        if not self.webhook_secret or not signature:
            return False
        expected = hmac.new(self.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


#: Replaced in tests.
razorpay = RazorpayClient()


def _add_months(day: date, months: int) -> date:
    """The same day ``months`` later, or the month's last day if it has none (31 Jan + 1 = 28 Feb)."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _credit(con: sqlite3.Connection, payment: sqlite3.Row, provider_payment_id: str | None) -> bool:
    """Count a paid payment towards its owner's subscription -- once.

    The webhook and a device asking can both see the same payment; whichever
    comes second finds it already paid and changes nothing. (Both run under
    ``db()``'s lock, so they cannot interleave.) Months are added after the
    current subscription's last day when it is still running, so paying early
    loses nothing.
    """
    if payment["status"] == "paid":
        return False
    current = con.execute("SELECT until FROM subscriptions WHERE profile_id = ?", (payment["profile_id"],)).fetchone()
    today = date.today()
    if current is not None and current["until"] is None:
        until = None  # granted with no end date; a payment cannot improve on it
    else:
        start = today
        if current is not None and date.fromisoformat(current["until"]) >= today:
            start = date.fromisoformat(current["until"])
        until = _add_months(start, payment["months"]).isoformat()
    con.execute(
        "INSERT INTO subscriptions (profile_id, plan, until, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (profile_id) DO UPDATE SET plan = excluded.plan, until = excluded.until",
        (payment["profile_id"], payment["plan"], until, _now()),
    )
    con.execute(
        "UPDATE payments SET status = 'paid', paid_at = ?, provider_payment_id = ?, until_after = ? WHERE id = ?",
        (_now(), provider_payment_id, until, payment["id"]),
    )
    return True


def _link_paid(con: sqlite3.Connection, payment: sqlite3.Row, link: dict, provider_payment_id: str | None) -> None:
    """Razorpay says a link is paid: credit it if the full amount arrived."""
    if int(link.get("amount_paid") or 0) >= payment["amount_paise"]:
        _credit(con, payment, provider_payment_id)


def _payment_out(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "plan": row["plan"],
        "planName": row["plan_name"],
        "amountPaise": row["amount_paise"],
        "months": row["months"],
        "url": row["url"],
        "status": row["status"],
        "until": row["until_after"],
        "expiresAt": row["expires_at"],
        "createdAt": row["created_at"],
        "paidAt": row["paid_at"],
    }


def _plan_out(row: sqlite3.Row) -> dict[str, Any]:
    return {"code": row["code"], "name": row["name"], "amountPaise": row["amount_paise"], "months": row["months"]}


@app.get("/v1/plans")
def list_plans(me: Device = Depends(device)) -> dict[str, Any]:
    """What is on sale, whether payments are switched on, and the owner's subscription."""
    with db() as con:
        rows = con.execute("SELECT * FROM plans WHERE active = 1 ORDER BY months, amount_paise").fetchall()
        return {
            "paymentsAvailable": razorpay.configured,
            "plans": [_plan_out(row) for row in rows],
            "subscription": subscription(con, me.profile_id),
        }


class CheckoutIn(BaseModel):
    plan: str = Field(min_length=1, max_length=32)


@app.post("/v1/payments")
def create_payment(body: CheckoutIn, me: Device = Depends(device)) -> dict[str, Any]:
    """A payment link for one plan, to open in the browser."""
    if not razorpay.configured:
        raise HTTPException(status_code=503, detail="Payments are not switched on on this server.")
    with db() as con:
        plan = con.execute("SELECT * FROM plans WHERE code = ? AND active = 1", (body.plan,)).fetchone()
        if plan is None:
            raise HTTPException(status_code=404, detail="That plan is not on sale.")
        current = con.execute("SELECT until FROM subscriptions WHERE profile_id = ?", (me.profile_id,)).fetchone()
        if current is not None and current["until"] is None:
            raise HTTPException(status_code=409, detail="Your subscription has no end date: there is nothing to pay.")
        # Pressing Pay twice hands back the link already open, not a second
        # one that could be paid as well.
        still_open = con.execute(
            "SELECT * FROM payments WHERE profile_id = ? AND plan = ? AND amount_paise = ? AND status = 'created' "
            "AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
            (me.profile_id, plan["code"], plan["amount_paise"], _now()),
        ).fetchone()
        if still_open is not None:
            return _payment_out(still_open)

    payment_id = f"vg_{secrets.token_hex(10)}"  # also Razorpay's reference_id: 40 characters at most
    expire_by = int(time.time()) + LINK_LIFETIME_SECONDS
    link = razorpay.create_link(
        amount_paise=plan["amount_paise"],
        reference_id=payment_id,
        description=f"ViksitGaanw: {plan['name']}",
        expire_by=expire_by,
        notes={"profile_id": me.profile_id, "plan": plan["code"]},
    )
    with db() as con:
        con.execute(
            "INSERT INTO payments (id, profile_id, plan, plan_name, amount_paise, months, link_id, url, status, "
            "expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, ?)",
            (payment_id, me.profile_id, plan["code"], plan["name"], plan["amount_paise"], plan["months"],
             link["id"], link["short_url"], datetime.fromtimestamp(expire_by, timezone.utc).isoformat(), _now()),
        )
        return _payment_out(con.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone())


@app.get("/v1/payments")
def list_payments(me: Device = Depends(device)) -> dict[str, Any]:
    with db() as con:
        rows = con.execute(
            "SELECT * FROM payments WHERE profile_id = ? ORDER BY created_at DESC LIMIT 20", (me.profile_id,)
        ).fetchall()
        return {"payments": [_payment_out(row) for row in rows]}


@app.get("/v1/payments/{payment_id}")
def payment_status(payment_id: str, me: Device = Depends(device)) -> dict[str, Any]:
    """Where a payment has got to, asking Razorpay while it is still open.

    Asking matters: a server on a laptop or a LAN cannot receive Razorpay's
    webhook, and this is then the only way a payment is ever seen.
    """
    with db() as con:
        row = con.execute("SELECT * FROM payments WHERE id = ? AND profile_id = ?", (payment_id, me.profile_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if row["status"] == "created" and razorpay.configured:
        link = razorpay.get_link(row["link_id"])
        with db() as con:
            row = con.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
            state = link.get("status")
            if state == "paid":
                captured = next((p for p in link.get("payments") or [] if p.get("status") == "captured"), {})
                _link_paid(con, row, link, captured.get("payment_id"))
            elif state in ("expired", "cancelled"):
                con.execute("UPDATE payments SET status = ? WHERE id = ? AND status = 'created'", (state, payment_id))
    with db() as con:
        row = con.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        return {**_payment_out(row), "subscription": subscription(con, me.profile_id)}


@app.post("/v1/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> dict[str, str]:
    """Razorpay telling us a payment link was paid, expired or cancelled.

    Point a Razorpay webhook at this address, with the payment_link events,
    once the server has a public address. Only the signature is trusted.
    """
    body = await request.body()
    if not razorpay.signature_ok(body, request.headers.get("x-razorpay-signature", "")):
        raise HTTPException(status_code=400, detail="Bad signature.")
    event = json.loads(body)
    event_id = request.headers.get("x-razorpay-event-id")
    with db() as con:
        if event_id:
            if con.execute("SELECT 1 FROM webhook_events WHERE id = ?", (event_id,)).fetchone():
                return {"status": "duplicate"}
            con.execute("INSERT INTO webhook_events (id, received_at) VALUES (?, ?)", (event_id, _now()))
        payload = event.get("payload") or {}
        link = (payload.get("payment_link") or {}).get("entity") or {}
        row = con.execute("SELECT * FROM payments WHERE link_id = ?", (link.get("id"),)).fetchone() if link else None
        if row is None:
            return {"status": "ignored"}
        kind = event.get("event")
        if kind == "payment_link.paid":
            payment = (payload.get("payment") or {}).get("entity") or {}
            _link_paid(con, row, link, payment.get("id"))
        elif kind in ("payment_link.expired", "payment_link.cancelled"):
            con.execute(
                "UPDATE payments SET status = ? WHERE id = ? AND status = 'created'", (kind.split(".")[1], row["id"])
            )
    return {"status": "ok"}


@app.get("/v1/health")
def health() -> dict[str, Any]:
    with db() as con:
        records = con.execute("SELECT COUNT(*) FROM records WHERE deleted = 0").fetchone()[0]
        devices = con.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    return {"status": "ok", "records": records, "devices": devices}
