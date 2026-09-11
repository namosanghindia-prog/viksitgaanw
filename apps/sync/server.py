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

The same payments buy **promotions**: a farmer pays for days at the top of
others' lists for one of their shared projects -- optionally with a one-off
alert to the investors and partners it suits. The server alone records a
promotion and stamps it onto the project everyone pulls, so no device can
feature itself; every app labels it as promoted.

And it runs **identity checks** (identity.py). The villager signs in on
DigiLocker in the browser and agrees; DigiLocker tells this server their name
as registered, and a profile is verified while that name matches its own.
This server alone sets a profile's KYC status -- whatever a device pushes is
overwritten -- and keeps no Aadhaar number, date of birth or document.

It runs on SQLite on a laptop and on PostgreSQL in production (storage.py),
with rate limits, size limits, token rotation, device sign-out and profile
suspension (admin.py). TLS is the host's job; see "Running the sync service
in production" in the README.

> [!WARNING]
> Not yet security-reviewed or hosted. Until it has been, run it on your own
> machine or network only.
"""

from __future__ import annotations

import calendar
import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

import identity
from storage import Conn, IntegrityError, Row, Store, database_url


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

#: SQLite on a laptop (VG_SYNC_DB), PostgreSQL in production (VG_SYNC_DATABASE_URL). See storage.py.
DATABASE_URL = database_url(dict(os.environ), Path(__file__).parent / "data" / "sync.db")
store = Store(DATABASE_URL)

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


#: Abuse controls. Each can be set in the environment where the server runs.
#: Requests a device may make a minute (a sync run is a burst of them).
RATE_PER_MINUTE = _env_int("VG_SYNC_RATE_PER_MINUTE", 300)
#: New devices one network address may register an hour.
REGISTRATIONS_PER_HOUR = _env_int("VG_SYNC_REGISTRATIONS_PER_HOUR", 20)
#: Largest request body; pictures are 8 MB at most, videos never come here.
MAX_BODY_BYTES = _env_int("VG_SYNC_MAX_BODY_MB", 10) * 1024 * 1024
#: Largest single record a device may push.
MAX_RECORD_BYTES = _env_int("VG_SYNC_MAX_RECORD_KB", 256) * 1024
#: Behind a reverse proxy or a host's load balancer, the client's address is
#: in X-Forwarded-For. Trust it only when set: anyone can send the header.
TRUST_PROXY = os.environ.get("VG_SYNC_TRUST_PROXY", "") == "1"


class RateLimiter:
    """A token bucket per key: ``capacity`` requests at once, refilled over ``period`` seconds.

    Kept in this process's memory. With several server processes each keeps
    its own, so the real limit is that many times higher -- still a firm cap
    on a runaway or hostile client, which is what it is for.
    """

    def __init__(self, capacity: int, period: float) -> None:
        self.capacity = max(1, capacity)
        self.rate = self.capacity / period
        self._buckets: dict[str, tuple[float, float]] = {}
        self._guard = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._guard:
            tokens, last = self._buckets.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens < 1:
                wait = int((1 - tokens) / self.rate) + 1
                raise HTTPException(status_code=429, detail="Too many requests. Try again shortly.",
                                    headers={"Retry-After": str(wait)})
            self._buckets[key] = (tokens - 1, now)
            if len(self._buckets) > 20_000:
                # Forget clients whose buckets have refilled: they cost nothing.
                full = [k for k, (t, at) in self._buckets.items() if t + (now - at) * self.rate >= self.capacity]
                for k in full:
                    del self._buckets[k]


device_limiter = RateLimiter(RATE_PER_MINUTE, 60)
registration_limiter = RateLimiter(REGISTRATIONS_PER_HOUR, 3600)


def client_address(request: Request) -> str:
    if TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


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

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db():
    """One transaction: ``with db() as con: con.execute(sql, params)``."""
    return store.connect()


def init() -> None:
    store.create()


def _next_rev(con: Conn) -> int:
    con.execute("UPDATE counters SET value = value + 1 WHERE name = 'rev'")
    return con.execute("SELECT value FROM counters WHERE name = 'rev'").fetchone()[0]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


app = FastAPI(title="ViksitGaanw sync server", version="0.1.0")
init()


@app.middleware("http")
async def limit_body(request: Request, call_next):
    """Refuse an oversized request before reading it."""
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": "Request too large."})
    return await call_next(request)


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
        if row["revoked_at"]:
            raise HTTPException(status_code=401, detail="This device has been signed out by the server's operator.")
        if con.execute("SELECT 1 FROM suspensions WHERE profile_id = ?", (row["profile_id"],)).fetchone():
            raise HTTPException(status_code=403, detail="This profile is suspended. Contact the server's operator.")
        device_limiter.check(row["id"])
        con.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (_now(), row["id"]))
    return Device(id=row["id"], profile_id=row["profile_id"], segment=row["segment"])


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


class RegisterIn(BaseModel):
    profile_id: str = Field(min_length=1, max_length=36)
    segment: str = Field(min_length=1, max_length=32)


@app.post("/v1/devices")
def register(body: RegisterIn, request: Request) -> dict[str, str]:
    """Register a device for its owner's profile and hand back its token."""
    registration_limiter.check(client_address(request))
    token = secrets.token_urlsafe(32)
    device_id = secrets.token_hex(8)
    with db() as con:
        # The first device to register a profile owns it. Another device
        # claiming the same id is refused, so nobody can pull someone else's
        # private records by knowing their profile id. A device the operator
        # signed out still counts: a stolen phone cannot simply sign in again.
        # The owner's new device can, once the operator releases the profile.
        if con.execute("SELECT 1 FROM devices WHERE profile_id = ?", (body.profile_id,)).fetchone():
            raise HTTPException(status_code=409, detail="That profile is already registered to a device.")
        con.execute(
            "INSERT INTO devices (id, token_hash, profile_id, segment, created_at, token_issued_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (device_id, _hash(token), body.profile_id, body.segment, _now(), _now()),
        )
    return {"deviceId": device_id, "token": token}


@app.post("/v1/devices/rotate")
def rotate_token(me: Device = Depends(device)) -> dict[str, str]:
    """Swap this device's token for a new one; the old one stops working at once.

    Devices do this every few months, so a token copied off an old backup or
    a lost phone does not stay good for ever.
    """
    token = secrets.token_urlsafe(32)
    with db() as con:
        con.execute("UPDATE devices SET token_hash = ?, token_issued_at = ? WHERE id = ?",
                    (_hash(token), _now(), me.id))
    return {"token": token}


# --------------------------------------------------------------------------- #
# Who may write, and who may read
# --------------------------------------------------------------------------- #


def _stored(con: Conn, entity_type: str, entity_id: str | None) -> Row | None:
    if not entity_id:
        return None
    return con.execute(
        "SELECT * FROM records WHERE entity_type=? AND entity_id=?", (entity_type, entity_id)
    ).fetchone()


def _owner_of(con: Conn, entity_type: str, entity_id: str | None) -> str | None:
    row = _stored(con, entity_type, entity_id)
    return row["owner_profile_id"] if row else None


#: What a rating may be about: the record it names, and the states in which
#: the two sides have actually worked together.
RATABLE = {
    "deal": ("deal", {"completed"}),
    "enquiry": ("equipment_enquiry", {"completed"}),
    "partnership": ("equipment_partnership", {"active", "ended"}),
}


def _check_rating(con: Conn, p: dict[str, Any]) -> None:
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


def _rules(con: Conn, entity_type: str, payload: dict[str, Any]) -> tuple[str, list[str]]:
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


def _links(con: Conn, a: str) -> set[str]:
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


def _connected(con: Conn, a: str, b: str) -> bool:
    """Whether profiles a and b are connected."""
    return a == b or b in _links(con, a)


def _resend(con: Conn, parties: list[str]) -> None:
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


def _visible(con: Conn, row: Row, puller: Device) -> bool:
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


def _redact(con: Conn, row: Row, puller: Device) -> dict[str, Any]:
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
                if len(json.dumps(record.payload)) > MAX_RECORD_BYTES:
                    raise HTTPException(status_code=413, detail="record too large")
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
                    if record.entity_type == "profile":
                        _forget_kyc(con, record.entity_id)
                    accepted += 1
                    continue

                payload = dict(record.payload)
                if record.entity_type == "profile":
                    payload = _with_kyc(con, payload)
                elif record.entity_type in PROMOTABLE:
                    payload = _with_promotion(con, record.entity_type, payload)
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
        # What a suspended profile shared stops reaching anyone but itself.
        suspended = {row[0] for row in con.execute("SELECT profile_id FROM suspensions")}
        for row in rows:
            last = row["rev"]
            if row["writer_device"] == me.id or not _visible(con, row, me):
                continue
            if row["owner_profile_id"] in suspended and row["owner_profile_id"] != me.profile_id:
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
            "INSERT INTO media (id, entity_type, entity_id, owner_profile_id, mime, body, meta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET entity_type = excluded.entity_type, "
            "entity_id = excluded.entity_id, owner_profile_id = excluded.owner_profile_id, mime = excluded.mime, "
            "body = excluded.body, meta = excluded.meta",
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


def subscription(con: Conn, profile_id: str) -> dict[str, Any] | None:
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


class SandboxPayments:
    """A pretend Razorpay for development: ``VG_PAYMENTS_SANDBOX=1`` with no keys set.

    Its payment page is on this server and says plainly that it is a test;
    pressing Pay marks the link paid, and everything after that -- crediting,
    receipts, promotions -- runs as it would for real. Links live in this
    process's memory. Never set it where real people pay.
    """

    configured = True
    webhook_secret = ""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.links: dict[str, dict] = {}

    def create_link(self, *, amount_paise: int, reference_id: str, description: str, expire_by: int,
                    notes: dict[str, str]) -> dict:
        link_id = f"plink_test_{secrets.token_hex(6)}"
        self.links[link_id] = {
            "id": link_id, "short_url": f"{self.base_url}/v1/sandbox/pay/{link_id}", "status": "created",
            "amount": amount_paise, "amount_paid": 0, "reference_id": reference_id, "description": description,
            "expire_by": expire_by, "notes": notes, "payments": None,
        }
        return self.links[link_id]

    def get_link(self, link_id: str) -> dict:
        link = self.links.get(link_id)
        if link is None:  # the server restarted: the pretend link is gone
            return {"id": link_id, "status": "expired", "amount_paid": 0}
        return link

    def signature_ok(self, body: bytes, signature: str) -> bool:
        return False


def _payments_client() -> Any:
    if os.environ.get("VG_PAYMENTS_SANDBOX", "") == "1" and not RazorpayClient().configured:
        return SandboxPayments(os.environ.get("VG_SYNC_PUBLIC_URL", "") or "http://127.0.0.1:8900")
    return RazorpayClient()


#: Replaced in tests.
razorpay = _payments_client()


@app.get("/v1/sandbox/pay/{link_id}", response_class=HTMLResponse)
def sandbox_pay_page(link_id: str, action: str = "") -> HTMLResponse:
    """The pretend payment page. Pay or cancel; nothing real happens."""
    if not isinstance(razorpay, SandboxPayments) or link_id not in razorpay.links:
        raise HTTPException(status_code=404, detail="Not found.")
    link = razorpay.links[link_id]
    if action == "pay" and link["status"] == "created":
        link.update(status="paid", amount_paid=link["amount"],
                    payments=[{"payment_id": f"pay_test_{secrets.token_hex(6)}", "status": "captured",
                               "amount": link["amount"]}])
    elif action == "cancel" and link["status"] == "created":
        link["status"] = "cancelled"
    rupees = f"Rs {link['amount'] // 100}" + (f".{link['amount'] % 100:02d}" if link["amount"] % 100 else "")
    if link["status"] == "created":
        body = (f"<p><strong>{html.escape(link['description'])}</strong></p><p style='font-size:2rem'>{rupees}</p>"
                "<p><a href='?action=pay' style='background:#2f7d4f;color:#fff;padding:12px 20px;border-radius:8px;"
                "text-decoration:none'>Pay (test)</a> &nbsp; <a href='?action=cancel'>Cancel</a></p>")
    else:
        body = (f"<p>This test payment is <strong>{html.escape(link['status'])}</strong>. "
                "Go back to the app; it checks by itself.</p>")
    return _html("Test payment", "<h1>Test payment</h1><p style='background:#fff4e5;padding:12px;border-radius:8px'>"
                 "<strong>TEST — no money moves.</strong> This server is in payments sandbox mode.</p>" + body)


def _add_months(day: date, months: int) -> date:
    """The same day ``months`` later, or the month's last day if it has none (31 Jan + 1 = 28 Feb)."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _credit(con: Conn, payment: Row, provider_payment_id: str | None) -> bool:
    """Count a paid payment towards its owner's subscription -- once.

    The webhook and a device asking can both see the same payment, possibly
    in two server processes at once. The payment is claimed with one guarded
    update -- only a row not yet paid changes -- so whichever comes second
    finds nothing to claim and changes nothing; on PostgreSQL it waits for the
    first to commit, then sees the row already paid. The subscription row is
    locked while its new last day is worked out, so two different payments
    for one person both count. Months are added after the current last day
    when it is still running, so paying early loses nothing.
    """
    claimed = con.execute(
        "UPDATE payments SET status = 'paid', paid_at = ?, provider_payment_id = ? WHERE id = ? AND status <> 'paid'",
        (_now(), provider_payment_id, payment["id"]),
    ).rowcount
    if claimed != 1:
        return False
    if payment["kind"] == "promotion":
        until = _extend_promotion(
            con, payment["target_type"], payment["target_id"], payment["profile_id"],
            payment["days"], bool(payment["alert"]),
        )
        con.execute("UPDATE payments SET until_after = ? WHERE id = ?", (until, payment["id"]))
        return True
    current = con.execute(
        "SELECT until FROM subscriptions WHERE profile_id = ?" + con.for_update, (payment["profile_id"],)
    ).fetchone()
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
    con.execute("UPDATE payments SET until_after = ? WHERE id = ?", (until, payment["id"]))
    return True


def _link_paid(con: Conn, payment: Row, link: dict, provider_payment_id: str | None) -> None:
    """Razorpay says a link is paid: credit it if the full amount arrived."""
    if int(link.get("amount_paid") or 0) >= payment["amount_paise"]:
        _credit(con, payment, provider_payment_id)


def _payment_out(row: Row) -> dict[str, Any]:
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
        "kind": row["kind"],
        "days": row["days"],
        "alert": bool(row["alert"]),
        "targetType": row["target_type"],
        "targetId": row["target_id"],
    }


def _plan_out(row: Row) -> dict[str, Any]:
    return {
        "code": row["code"], "name": row["name"], "amountPaise": row["amount_paise"], "months": row["months"],
        "kind": row["kind"], "days": row["days"], "alert": bool(row["alert"]),
    }


@app.get("/v1/plans")
def list_plans(kind: str | None = None, me: Device = Depends(device)) -> dict[str, Any]:
    """What is on sale -- subscriptions, promotions, or both -- and the owner's subscription."""
    query, params = "SELECT * FROM plans WHERE active = 1", ()
    if kind:
        query, params = query + " AND kind = ?", (kind,)
    with db() as con:
        rows = con.execute(query + " ORDER BY kind, months, days, amount_paise", params).fetchall()
        return {
            "paymentsAvailable": razorpay.configured,
            "plans": [_plan_out(row) for row in rows],
            "subscription": subscription(con, me.profile_id),
        }


class CheckoutIn(BaseModel):
    plan: str = Field(min_length=1, max_length=32)
    #: For a promotion: what to promote.
    target_type: str | None = Field(default=None, max_length=32)
    target_id: str | None = Field(default=None, max_length=36)


@app.post("/v1/payments")
def create_payment(body: CheckoutIn, me: Device = Depends(device)) -> dict[str, Any]:
    """A payment link for one plan, to open in the browser."""
    if not razorpay.configured:
        raise HTTPException(status_code=503, detail="Payments are not switched on on this server.")
    with db() as con:
        plan = con.execute("SELECT * FROM plans WHERE code = ? AND active = 1", (body.plan,)).fetchone()
        if plan is None:
            raise HTTPException(status_code=404, detail="That plan is not on sale.")
        if plan["kind"] == "promotion":
            _check_promotable(con, me.profile_id, body.target_type, body.target_id)
            target_type, target_id = body.target_type, body.target_id
        else:
            target_type = target_id = None
            current = con.execute("SELECT until FROM subscriptions WHERE profile_id = ?", (me.profile_id,)).fetchone()
            if current is not None and current["until"] is None:
                raise HTTPException(status_code=409, detail="Your subscription has no end date: there is nothing to pay.")
        # Pressing Pay twice hands back the link already open, not a second
        # one that could be paid as well.
        still_open = con.execute(
            "SELECT * FROM payments WHERE profile_id = ? AND plan = ? AND amount_paise = ? AND status = 'created' "
            "AND expires_at > ? AND COALESCE(target_id, '') = ? ORDER BY created_at DESC LIMIT 1",
            (me.profile_id, plan["code"], plan["amount_paise"], _now(), target_id or ""),
        ).fetchone()
        if still_open is not None:
            return _payment_out(still_open)

    payment_id = f"vg_{secrets.token_hex(10)}"  # also Razorpay's reference_id: 40 characters at most
    expire_by = int(time.time()) + LINK_LIFETIME_SECONDS
    notes = {"profile_id": me.profile_id, "plan": plan["code"]}
    if target_id:
        notes["promotes"] = f"{target_type}:{target_id}"
    link = razorpay.create_link(
        amount_paise=plan["amount_paise"],
        reference_id=payment_id,
        description=f"ViksitGaanw: {plan['name']}",
        expire_by=expire_by,
        notes=notes,
    )
    with db() as con:
        con.execute(
            "INSERT INTO payments (id, profile_id, plan, plan_name, amount_paise, months, link_id, url, status, "
            "expires_at, created_at, kind, days, alert, target_type, target_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, ?, ?, ?, ?, ?, ?)",
            (payment_id, me.profile_id, plan["code"], plan["name"], plan["amount_paise"], plan["months"],
             link["id"], link["short_url"], datetime.fromtimestamp(expire_by, timezone.utc).isoformat(), _now(),
             plan["kind"], plan["days"], plan["alert"], target_type, target_id),
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
        promotion = _promotion_out(con, row["target_type"], row["target_id"]) if row["kind"] == "promotion" else None
        return {**_payment_out(row), "subscription": subscription(con, me.profile_id), "promotion": promotion}


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
        # Razorpay retries; the first delivery to record its id handles it.
        if event_id and con.execute(
            "INSERT INTO webhook_events (id, received_at) VALUES (?, ?) ON CONFLICT DO NOTHING", (event_id, _now())
        ).rowcount != 1:
            return {"status": "duplicate"}
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


# --------------------------------------------------------------------------- #
# Promotions: a paid place at the top of others' lists
# --------------------------------------------------------------------------- #

#: What may be promoted. The records are public already; promotion only moves
#: them up, labels them, and -- for an alerting promotion -- tells those they
#: suit, once.
PROMOTABLE = {"investment_request"}


def _check_promotable(con: Conn, profile_id: str, target_type: str | None, target_id: str | None) -> None:
    """Refuse a promotion of anything but the payer's own open, shared project."""
    if target_type not in PROMOTABLE or not target_id:
        raise HTTPException(status_code=422, detail="Say which of your shared projects to promote.")
    row = _stored(con, target_type, target_id)
    if row is None or row["deleted"]:
        raise HTTPException(status_code=409, detail="Share the project online first, then promote it.")
    if row["owner_profile_id"] != profile_id:
        raise HTTPException(status_code=403, detail="You can promote only your own projects.")
    if json.loads(row["payload"]).get("status") != "open":
        raise HTTPException(status_code=409, detail="Only an open project can be promoted.")


def _promotion_out(con: Conn, entity_type: str | None, entity_id: str | None) -> dict[str, Any] | None:
    row = con.execute(
        "SELECT * FROM promotions WHERE entity_type = ? AND entity_id = ?", (entity_type, entity_id)
    ).fetchone()
    if row is None:
        return None
    return {"entityType": row["entity_type"], "entityId": row["entity_id"], "until": row["until"],
            "alertAt": row["alert_at"], "active": row["until"] >= date.today().isoformat()}


def _extend_promotion(con: Conn, entity_type: str, entity_id: str, profile_id: str, days: int,
                      alert: bool) -> str:
    """Add ``days`` after the current last day (or from today), and stamp the record. Returns the last day.

    The row is locked while its new last day is worked out, as a subscription's
    is, so two payments for one project both count.
    """
    row = con.execute(
        "SELECT * FROM promotions WHERE entity_type = ? AND entity_id = ?" + con.for_update, (entity_type, entity_id)
    ).fetchone()
    today = date.today()
    start = today
    if row is not None and date.fromisoformat(row["until"]) >= today:
        start = date.fromisoformat(row["until"]) + timedelta(days=1)
    until = (start + timedelta(days=max(1, days) - 1)).isoformat()
    alert_at = _now() if alert else (row["alert_at"] if row is not None else None)
    con.execute(
        "INSERT INTO promotions (entity_type, entity_id, profile_id, until, alert_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (entity_type, entity_id) DO UPDATE SET "
        "until = excluded.until, alert_at = excluded.alert_at, updated_at = excluded.updated_at",
        (entity_type, entity_id, profile_id, until, alert_at, _now()),
    )
    _stamp_promotion(con, entity_type, entity_id)
    return until


def _with_promotion(con: Conn, entity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """A pushed record with the server's own promotion fields, whatever the device said."""
    out = {key: value for key, value in payload.items() if key not in ("promoted_until", "promotion_alert_at")}
    row = con.execute(
        "SELECT until, alert_at FROM promotions WHERE entity_type = ? AND entity_id = ?",
        (entity_type, payload.get("id", "")),
    ).fetchone()
    out["promoted_until"] = row["until"] if row is not None else None
    out["promotion_alert_at"] = row["alert_at"] if row is not None else None
    return out


def _stamp_promotion(con: Conn, entity_type: str, entity_id: str) -> None:
    """Re-stamp a stored record after its promotion changed, so every device pulls it."""
    row = _stored(con, entity_type, entity_id)
    if row is None or row["deleted"]:
        return
    payload = _with_promotion(con, entity_type, json.loads(row["payload"]))
    con.execute(
        "UPDATE records SET payload = ?, rev = ?, updated_at = ? WHERE entity_type = ? AND entity_id = ?",
        (json.dumps(payload), _next_rev(con), _now(), entity_type, entity_id),
    )


@app.get("/v1/promotions")
def my_promotions(me: Device = Depends(device)) -> dict[str, Any]:
    """This owner's promotions -- paid, or granted by the operator."""
    with db() as con:
        rows = con.execute(
            "SELECT entity_type, entity_id FROM promotions WHERE profile_id = ? ORDER BY until DESC", (me.profile_id,)
        ).fetchall()
        return {"promotions": [_promotion_out(con, row["entity_type"], row["entity_id"]) for row in rows]}


# --------------------------------------------------------------------------- #
# Identity checks
# --------------------------------------------------------------------------- #

#: How long someone has to finish signing in with the provider.
KYC_SESSION_SECONDS = 15 * 60
#: This server's address as browsers reach it. Unset, it is taken from each
#: request -- right on a laptop, wrong behind a proxy that hides the host.
PUBLIC_URL = os.environ.get("VG_SYNC_PUBLIC_URL", "").rstrip("/")
#: Salts the fingerprint kept of each person's provider id. Set it once and
#: never change it, or one person could verify two profiles.
KYC_SALT = os.environ.get("VG_KYC_SALT", "")

digilocker = identity.DigiLocker()
sandbox = identity.Sandbox(os.environ.get("VG_KYC_SANDBOX", "") == "1")

#: The checks this server can run for each kind of profile. Aadhaar eKYC, PAN,
#: passport and organisation checks wait for an agreement with a provider;
#: international profiles have no DigiLocker.
KYC_METHODS: dict[str, tuple[str, ...]] = {
    "farmer": ("digilocker",),
    "investor_india": ("digilocker",),
    "partner_national": ("digilocker",),
}


def _providers() -> dict[str, Any]:
    return {provider.method: provider for provider in (digilocker, sandbox) if provider.configured}


def _methods_for(segment: str) -> tuple[str, ...]:
    return KYC_METHODS.get(segment, ()) + (("sandbox",) if sandbox.configured else ())


def _verification(con: Conn, profile_id: str) -> Row | None:
    return con.execute("SELECT * FROM verifications WHERE profile_id = ?", (profile_id,)).fetchone()


def _kyc_fields(con: Conn, profile_id: str, display_name: str | None) -> dict[str, Any]:
    """What everyone else is told about a profile's identity check.

    Verified only while the registered name matches the profile's name: a
    profile renamed to someone else loses the tick until checked again. To
    others it is then simply not verified -- a misspelt name is not a failed
    check, and only the owner is told why (``/v1/kyc``).
    """
    row = _verification(con, profile_id)
    if row is None or not identity.names_match(row["registered_name"], display_name):
        return {"kyc_status": "unverified", "kyc_method": None, "kyc_verified_at": None}
    return {"kyc_status": "verified", "kyc_method": row["method"], "kyc_verified_at": row["verified_at"]}


def _with_kyc(con: Conn, payload: dict[str, Any]) -> dict[str, Any]:
    """A pushed profile with the server's own KYC fields, whatever the device said."""
    out = {key: value for key, value in payload.items() if key != "kyc_reference"}
    out.update(_kyc_fields(con, payload.get("id", ""), payload.get("display_name")))
    return out


def _stamp_profile(con: Conn, profile_id: str) -> None:
    """Re-stamp a stored profile after a check, so every device pulls the new status."""
    row = _stored(con, "profile", profile_id)
    if row is None or row["deleted"]:
        return
    payload = _with_kyc(con, json.loads(row["payload"]))
    con.execute(
        "UPDATE records SET payload = ?, rev = ?, updated_at = ? WHERE entity_type = 'profile' AND entity_id = ?",
        (json.dumps(payload), _next_rev(con), _now(), profile_id),
    )


def _forget_kyc(con: Conn, profile_id: str) -> None:
    """A deleted profile keeps no registered name, and frees its identity for a new one."""
    con.execute("DELETE FROM verifications WHERE profile_id = ?", (profile_id,))
    con.execute("DELETE FROM kyc_sessions WHERE profile_id = ?", (profile_id,))


def _display_name(con: Conn, profile_id: str) -> str | None:
    row = _stored(con, "profile", profile_id)
    if row is None or row["deleted"]:
        return None
    return json.loads(row["payload"]).get("display_name")


@app.get("/v1/kyc")
def kyc_status(me: Device = Depends(device)) -> dict[str, Any]:
    """This profile's identity check, and which checks it can take here."""
    providers = _providers()
    with db() as con:
        row = _verification(con, me.profile_id)
        name = _display_name(con, me.profile_id)
        fields = _kyc_fields(con, me.profile_id, name)
        waiting = con.execute(
            "SELECT 1 FROM kyc_sessions WHERE profile_id = ? AND status = 'waiting' AND expires_at > ?",
            (me.profile_id, _now()),
        ).fetchone()
    matches = identity.names_match(row["registered_name"], name) if row else None
    status = fields["kyc_status"]
    if row is not None and not matches:
        status = "rejected"  # to its owner only: the name needs fixing
    elif status == "unverified" and waiting:
        status = "pending"
    return {
        "status": status,
        "method": row["method"] if row else None,
        "verifiedAt": row["verified_at"] if row else None,
        # The registered name is the owner's to see, so they can fix a mismatch.
        "registeredName": row["registered_name"] if row else None,
        "nameMatches": matches,
        "aadhaarBacked": bool(row["aadhaar_backed"]) if row else None,
        "methods": [{"code": method, "available": method in providers} for method in _methods_for(me.segment)],
        "sandbox": sandbox.configured,
    }


class KycStartIn(BaseModel):
    method: str = Field(min_length=1, max_length=32)


def _public_url(request: Request) -> str:
    return PUBLIC_URL or str(request.base_url).rstrip("/")


@app.post("/v1/kyc/start")
def kyc_start(body: KycStartIn, request: Request, me: Device = Depends(device)) -> dict[str, str]:
    """An address to open in the browser, where the person signs in and agrees.

    It is this server's own page first (``/v1/kyc/go``), which says whose
    profile is being checked before sending the browser on to the provider.
    """
    if body.method not in _methods_for(me.segment):
        raise HTTPException(status_code=422, detail="That check does not apply to this profile.")
    if body.method not in _providers():
        raise HTTPException(status_code=503, detail="This identity check is not switched on on this server yet.")
    if body.method != "sandbox" and not KYC_SALT:
        raise HTTPException(status_code=503, detail="The server's operator must set VG_KYC_SALT first.")
    with db() as con:
        if _display_name(con, me.profile_id) is None:
            raise HTTPException(status_code=409, detail="Share your profile online first, then check your identity.")
        # Attempts are kept a day past their end, to see what went wrong; then dropped.
        day_ago = datetime.fromtimestamp(time.time() - 86400, timezone.utc).isoformat()
        con.execute("DELETE FROM kyc_sessions WHERE expires_at < ?", (day_ago,))
        # One attempt at a time: starting again cancels the last one's link.
        con.execute(
            "UPDATE kyc_sessions SET status = 'failed', error = 'replaced' WHERE profile_id = ? AND status = 'waiting'",
            (me.profile_id,),
        )
        state = secrets.token_urlsafe(24)
        expires = datetime.fromtimestamp(time.time() + KYC_SESSION_SECONDS, timezone.utc).isoformat()
        con.execute(
            "INSERT INTO kyc_sessions (state, profile_id, method, verifier, status, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, 'waiting', ?, ?)",
            (state, me.profile_id, body.method, identity.pkce_verifier(), _now(), expires),
        )
    return {"url": f"{_public_url(request)}/v1/kyc/go?" + urllib.parse.urlencode({"state": state}),
            "expiresAt": expires}


def _html(title: str, body: str, status: int = 200) -> HTMLResponse:
    """A short page for a browser, in Hindi as well as English. ``body`` must already be escaped."""
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        f"<title>{html.escape(title)}</title></head><body style='font-family:system-ui,sans-serif;"
        f"max-width:560px;margin:40px auto;padding:0 16px;line-height:1.6'>{body}</body></html>",
        status_code=status,
    )


def _page(title: str, english: str, hindi: str, ok: bool) -> HTMLResponse:
    """Where the browser ends up: what happened, and to go back to the app."""
    colour = "#2f7d4f" if ok else "#b3261e"
    return _html(
        title,
        f"<h1 style='color:{colour}'>{html.escape(title)}</h1>"
        f"<p>{html.escape(english)}</p><p lang='hi'>{html.escape(hindi)}</p>",
        200 if ok else 400,
    )


def _expired() -> HTMLResponse:
    return _page("Link expired", "This check has expired or was already used. Start again from the app.",
                 "यह जाँच पुरानी हो गई या पहले ही इस्तेमाल हो चुकी। ऐप से फिर शुरू करें।", ok=False)


def _waiting_session(con: Conn, state: str, method: str | None = None) -> Row | None:
    session = con.execute("SELECT * FROM kyc_sessions WHERE state = ?", (state,)).fetchone()
    if session is None or session["status"] != "waiting" or session["expires_at"] <= _now():
        return None
    if method is not None and session["method"] != method:
        return None
    return session


@app.get("/v1/kyc/go", response_class=HTMLResponse)
def kyc_go(state: str = "") -> HTMLResponse:
    """Say whose profile is about to be checked, then go on to the provider.

    Anyone could start a check for their own profile and send the link to
    someone else, hoping they sign in and lend it their identity. This page
    names the profile and tells them to stop unless they started it
    themselves, on their own device, just now.
    """
    with db() as con:
        session = _waiting_session(con, state)
        name = _display_name(con, session["profile_id"]) if session else None
    provider = _providers().get(session["method"]) if session else None
    if session is None or provider is None:
        return _expired()
    target = provider.authorize_url(state, identity.pkce_challenge(session["verifier"]))
    label = "a sandbox test (nothing is checked)" if session["method"] == "sandbox" else "DigiLocker"
    who = html.escape(name or "")
    return _html(
        "Check your identity",
        "<h1>Check your identity</h1>"
        f"<p>You are about to confirm that the ViksitGaanw profile <strong>{who}</strong> is you, through "
        f"{html.escape(label)}. Only your name, and whether the account is linked to Aadhaar, will be kept -- "
        "not your Aadhaar number, date of birth or documents.</p>"
        f"<p lang='hi'>आप पुष्टि करने जा रहे हैं कि विकसितगाँव प्रोफ़ाइल <strong>{who}</strong> आपकी है। "
        "सिर्फ़ आपका नाम और यह कि खाता आधार से जुड़ा है या नहीं, रखा जाएगा — आधार नंबर, जन्मतिथि या दस्तावेज़ नहीं।</p>"
        "<p style='background:#fff4e5;padding:12px;border-radius:8px'><strong>Continue only if you pressed the "
        "button in your own ViksitGaanw app just now.</strong> If someone sent you this link, close this page.<br>"
        "<span lang='hi'><strong>आगे तभी बढ़ें जब आपने अभी अपने विकसितगाँव ऐप में बटन दबाया हो।</strong> "
        "अगर यह लिंक किसी ने आपको भेजा है, तो यह पेज बंद कर दें।</span></p>"
        f"<p><a href='{html.escape(target)}' style='display:inline-block;background:#2f7d4f;color:#fff;"
        "padding:12px 20px;border-radius:8px;text-decoration:none'>Continue · आगे बढ़ें</a></p>",
    )


def _fail_session(state: str, error: str) -> None:
    with db() as con:
        con.execute("UPDATE kyc_sessions SET status = 'failed', error = ? WHERE state = ?", (error[:300], state))


def _finish(method: str, state: str, code: str, error: str) -> HTMLResponse:
    """The provider sent the person back, with a one-time code: find out who they are."""
    with db() as con:
        session = _waiting_session(con, state, method)
    if session is None:
        return _expired()
    if error or not code:
        _fail_session(state, error or "no code")
        return _page("Not verified", "You did not agree, so nothing was checked. You can try again from the app.",
                     "आपने सहमति नहीं दी, इसलिए कुछ नहीं जाँचा गया। ऐप से फिर कोशिश कर सकते हैं।", ok=False)
    provider = _providers().get(method)
    if provider is None:
        return _page("Not available", "This check is not switched on on this server.",
                     "यह जाँच इस सर्वर पर चालू नहीं है।", ok=False)
    try:
        person = provider.exchange(code, session["verifier"])
    except identity.IdentityError as exc:
        _fail_session(state, str(exc))
        return _page("Could not check", "The identity service did not answer properly. Try again later.",
                     "पहचान सेवा ने ठीक से जवाब नहीं दिया। थोड़ी देर बाद फिर कोशिश करें।", ok=False)

    fingerprint = identity.reference(KYC_SALT or "sandbox", f"{method}:{person['id']}")
    already_used = _page("Already used", "This identity already verifies another profile.",
                         "यह पहचान पहले से किसी दूसरी प्रोफ़ाइल की पुष्टि करती है।", ok=False)
    try:
        with db() as con:
            # The code is spent either way; a second visit to this page finds nothing.
            if con.execute("UPDATE kyc_sessions SET status = 'done' WHERE state = ? AND status = 'waiting'",
                           (state,)).rowcount == 0:
                return _expired()
            # One person vouches for one profile: the same identity cannot verify two.
            other = con.execute(
                "SELECT profile_id FROM verifications WHERE reference = ? AND profile_id <> ?",
                (fingerprint, session["profile_id"]),
            ).fetchone()
            if other is not None:
                con.execute("UPDATE kyc_sessions SET status = 'failed', error = 'identity used by another profile' "
                            "WHERE state = ?", (state,))
                return already_used
            con.execute(
                "INSERT INTO verifications (profile_id, method, reference, registered_name, aadhaar_backed, "
                "verified_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (profile_id) DO UPDATE SET "
                "method = excluded.method, reference = excluded.reference, "
                "registered_name = excluded.registered_name, aadhaar_backed = excluded.aadhaar_backed, "
                "verified_at = excluded.verified_at",
                (session["profile_id"], method, fingerprint, person["name"], int(person["aadhaar_backed"]), _now()),
            )
            _stamp_profile(con, session["profile_id"])
            matches = identity.names_match(person["name"], _display_name(con, session["profile_id"]))
    except IntegrityError:
        # Another profile took the same identity a moment ago (the unique index caught it).
        _fail_session(state, "identity used by another profile")
        return already_used
    if not matches:
        return _page("Name does not match",
                     "The name registered there is not the name on your profile. Go back to the app to see it, "
                     "change your profile name to match, and the tick will show.",
                     "वहाँ पंजीकृत नाम आपकी प्रोफ़ाइल के नाम से नहीं मिलता। ऐप में देखें, प्रोफ़ाइल का नाम उसके जैसा "
                     "कर दें, तो सत्यापन दिखेगा।",
                     ok=False)
    return _page("Verified", "Your identity is checked. Go back to the app; it will show the tick.",
                 "आपकी पहचान की जाँच हो गई। ऐप में वापस जाएँ; वहाँ सत्यापित दिखेगा।", ok=True)


@app.get("/v1/kyc/digilocker/callback", response_class=HTMLResponse)
def kyc_digilocker_callback(state: str = "", code: str = "", error: str = "") -> HTMLResponse:
    """Where DigiLocker sends the person back. Register exactly this address on its partner portal."""
    return _finish("digilocker", state, code, error)


@app.get("/v1/kyc/sandbox/authorize", response_class=HTMLResponse)
def kyc_sandbox_page(state: str = "") -> HTMLResponse:
    """The pretend provider's sign-in page, for development only."""
    if not sandbox.configured:
        raise HTTPException(status_code=404, detail="Not found.")
    return _html(
        "Sandbox identity check",
        "<h1>Sandbox identity check</h1><p><strong>For testing only. Nothing is checked.</strong></p>"
        "<form action='/v1/kyc/sandbox/callback' method='get'>"
        f"<input type='hidden' name='state' value='{html.escape(state)}'>"
        "<label>Name as it would be registered<br><input name='name' required></label> "
        "<button name='code' value='sandbox'>Approve</button> "
        "<button name='error' value='declined' formnovalidate>Decline</button></form>",
    )


@app.get("/v1/kyc/sandbox/callback", response_class=HTMLResponse)
def kyc_sandbox_callback(state: str = "", name: str = "", code: str = "", error: str = "") -> HTMLResponse:
    if not sandbox.configured:
        raise HTTPException(status_code=404, detail="Not found.")
    return _finish("sandbox", state, f"sandbox:{urllib.parse.quote(name)}" if code else "", error)


@app.get("/v1/health")
def health() -> dict[str, Any]:
    with db() as con:
        records = con.execute("SELECT COUNT(*) FROM records WHERE deleted = 0").fetchone()[0]
        devices = con.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    return {"status": "ok", "records": records, "devices": devices}
