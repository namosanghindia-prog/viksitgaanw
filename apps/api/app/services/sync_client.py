"""The device side of cloud sync.

Every write in the app already lands in ``sync_queue``. This worker drains it
to the sync server (``apps/sync``) and pulls back what other devices shared,
applying it to the local database as ``origin = synced`` rows -- the same rows
the demo seed used to fake. From there the rest of the app needs no special
case: a synced request is browsed like any other.

What leaves the device, and what does not:

* **Pushed:** the owner's profile, projects, machines and groups *while they
  are shared online*; the card of a plot shared with connections, and farm
  updates (the server shows both only to connections); and the records they
  exchange with others -- connection requests, interests, enquiries,
  partnerships, messages, deals, disputes, ratings.
* **Never pushed:** the land parcels themselves (survey number, pin, notes),
  the farm diary, project reports, scheme applications, notifications -- and
  anything still offline. Their queue entries are marked ``held`` and stay on
  the device.

Sync is off until a server address is set, and only runs when asked (the app
asks every few minutes while it is on).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import Date, DateTime, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    Connection,
    Deal,
    Dispute,
    EquipmentEnquiry,
    EquipmentListing,
    EquipmentPartnership,
    FarmerGroup,
    FarmUpdate,
    GroupMember,
    InsurancePolicy,
    InvestmentInterest,
    InvestmentRequest,
    LandShare,
    MediaFile,
    Message,
    Milestone,
    Profile,
    ProjectInvite,
    Rating,
    SyncQueueEntry,
    SyncSetting,
)
from ..schemas import SyncStatusOut
from . import media as media_service
from .notify import notify
from .profiles import get_owner

logger = logging.getLogger("viksitgaanw.sync")

MODELS: dict[str, type] = {
    "profile": Profile,
    "investment_request": InvestmentRequest,
    "investment_interest": InvestmentInterest,
    "insurance_policy": InsurancePolicy,
    "equipment_listing": EquipmentListing,
    "equipment_enquiry": EquipmentEnquiry,
    "equipment_partnership": EquipmentPartnership,
    "message": Message,
    "deal": Deal,
    "dispute": Dispute,
    "rating": Rating,
    "farmer_group": FarmerGroup,
    "group_member": GroupMember,
    "connection": Connection,
    "land_share": LandShare,
    "farm_update": FarmUpdate,
    "project_invite": ProjectInvite,
}
#: Records that leave the device only while their owner has them online.
PUBLIC = {"profile", "investment_request", "equipment_listing", "farmer_group", "land_share", "farm_update"}
#: Columns that describe this device, not the record.
LOCAL_ONLY = {"sync_state", "is_device_owner", "origin", "farmer_id", "parcel_id", "report_id"}
#: Order to apply a pulled page in, parents before children.
APPLY_ORDER = [
    "profile", "connection", "land_share", "farm_update",
    "farmer_group", "group_member", "investment_request", "equipment_listing",
    "insurance_policy", "investment_interest", "project_invite", "equipment_enquiry", "equipment_partnership",
    "deal", "dispute", "rating", "message",
]
#: On a record the owner created, the other side may only change these.
COUNTERPARTY_FIELDS = ("status", "responded_at")
MEDIA_ENTITY = {"profile": "profile", "equipment_listing": "equipment", "land_share": "land", "farm_update": "update"}


class SyncError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- #
# Transport: HTTP in the app, the server's TestClient in tests
# --------------------------------------------------------------------------- #


class Transport(Protocol):
    def post(self, path: str, body: dict, token: str | None = None) -> dict: ...
    def get(self, path: str, params: dict, token: str) -> dict: ...
    def put_bytes(self, path: str, data: bytes, headers: dict, token: str) -> dict: ...
    def get_bytes(self, path: str, token: str) -> tuple[bytes, dict]: ...


class HttpTransport:
    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _open(self, request: urllib.request.Request) -> tuple[bytes, dict]:
        if not get_settings().allow_network:
            raise SyncError("Network access is switched off on this device.", 503)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise SyncError(f"Sync server said {exc.code}: {detail}", exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SyncError(f"Sync server not reachable: {exc}", 503) from exc

    def _headers(self, token: str | None, extra: dict | None = None) -> dict:
        headers = {"Accept": "application/json", **(extra or {})}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def post(self, path: str, body: dict, token: str | None = None) -> dict:
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers=self._headers(token, {"Content-Type": "application/json"}),
            method="POST",
        )
        return json.loads(self._open(request)[0])

    def get(self, path: str, params: dict, token: str) -> dict:
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        return json.loads(self._open(urllib.request.Request(url, headers=self._headers(token)))[0])

    def put_bytes(self, path: str, data: bytes, headers: dict, token: str) -> dict:
        request = urllib.request.Request(
            self.base + path, data=data, headers=self._headers(token, headers), method="PUT"
        )
        return json.loads(self._open(request)[0])

    def get_bytes(self, path: str, token: str) -> tuple[bytes, dict]:
        return self._open(urllib.request.Request(self.base + path, headers=self._headers(token)))


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


def _get(session: Session, key: str) -> str | None:
    row = session.get(SyncSetting, key)
    return row.value if row else None


def _set(session: Session, key: str, value: str | None) -> None:
    row = session.get(SyncSetting, key)
    if row is None:
        session.add(SyncSetting(key=key, value=value))
        # Pending rows are not in the identity map; without autoflush a
        # second _set of the same key would insert it twice.
        session.flush()
    else:
        row.value = value


def _when(session: Session, key: str) -> datetime | None:
    value = _get(session, key)
    return datetime.fromisoformat(value) if value else None


def status(session: Session) -> SyncStatusOut:
    url = _get(session, "server_url")
    pending = session.query(SyncQueueEntry).filter(SyncQueueEntry.status == "pending").count()
    return SyncStatusOut(
        enabled=bool(url),
        server_url=url,
        device_registered=bool(_get(session, "token")),
        pending=pending,
        last_push_at=_when(session, "last_push_at"),
        last_pull_at=_when(session, "last_pull_at"),
        last_error=_get(session, "last_error"),
    )


def configure(session: Session, server_url: str | None) -> SyncStatusOut:
    if server_url != _get(session, "server_url"):
        # A different server knows nothing of this device: start again there.
        for key in ("server_url", "device_id", "token", "token_issued_at", "device_profile_id", "pull_rev",
                    "last_error"):
            _set(session, key, None)
        _set(session, "server_url", server_url)
    return status(session)


# --------------------------------------------------------------------------- #
# Serialising records
# --------------------------------------------------------------------------- #


def _jsonable(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _columns(obj: Any) -> dict[str, Any]:
    return {
        column.key: _jsonable(getattr(obj, column.key))
        for column in inspect(obj).mapper.column_attrs
        if column.key not in LOCAL_ONLY
    }


def _media_list(session: Session, entity_type: str, entity_id: str) -> list[dict]:
    return [
        {"id": f.id, "entity_type": f.entity_type, "entity_id": f.entity_id,
         "position": f.position, "width": f.width, "height": f.height}
        for f in media_service.for_entity(session, entity_type, entity_id)
    ]


def payload_for(session: Session, entity_type: str, obj: Any) -> dict[str, Any]:
    payload = _columns(obj)
    if entity_type in MEDIA_ENTITY:
        payload["media"] = _media_list(session, MEDIA_ENTITY[entity_type], obj.id)
    if entity_type == "deal":
        payload["milestones"] = []
        for milestone in obj.milestones:
            item = _columns(milestone)
            item["media"] = _media_list(session, "milestone", milestone.id)
            payload["milestones"].append(item)
    return payload


def _shareable(session: Session, entity_type: str, obj: Any, owner: Profile) -> bool:
    """Whether this record may leave the device right now."""
    if entity_type in PUBLIC:
        return getattr(obj, "visibility", "offline") == "online"
    if entity_type == "insurance_policy":
        request = session.get(InvestmentRequest, obj.request_id) if obj.request_id else None
        return bool(request and request.visibility == "online")
    if entity_type == "group_member":
        return True
    return entity_type in MODELS


# --------------------------------------------------------------------------- #
# Push
# --------------------------------------------------------------------------- #


@dataclass
class RunResult:
    pushed: int = 0
    pulled: int = 0
    errors: list[str] = field(default_factory=list)


def _register(session: Session, transport: Transport, owner: Profile) -> str:
    token = _get(session, "token")
    if token and _get(session, "device_profile_id") == owner.id:
        return token
    answer = transport.post("/v1/devices", {"profile_id": owner.id, "segment": owner.segment})
    _set(session, "device_id", answer["deviceId"])
    _set(session, "token", answer["token"])
    _set(session, "token_issued_at", datetime.now(timezone.utc).isoformat())
    _set(session, "device_profile_id", owner.id)
    _set(session, "pull_rev", "0")
    return answer["token"]


def _records_for_entry(session: Session, entry: SyncQueueEntry, owner: Profile) -> list[dict] | None:
    """What one queue entry sends, or None if it stays on the device."""
    entity_type = entry.entity_type
    if entity_type not in MODELS:
        return None
    if entry.operation in ("delete", "unshare"):
        return [{"entity_type": entity_type, "entity_id": entry.entity_id, "deleted": True, "payload": {}}]

    obj = session.get(MODELS[entity_type], entry.entity_id)
    if obj is None or not _shareable(session, entity_type, obj, owner):
        return None
    records = [{"entity_type": entity_type, "entity_id": obj.id, "payload": payload_for(session, entity_type, obj)}]

    if entity_type == "investment_request" and entry.operation == "share":
        # The cover travels with the request it belongs to.
        for policy in session.scalars(select(InsurancePolicy).where(InsurancePolicy.request_id == obj.id)):
            records.append({"entity_type": "insurance_policy", "entity_id": policy.id,
                            "payload": payload_for(session, "insurance_policy", policy)})
    if entity_type == "farmer_group":
        mine = obj.owner_profile_id == owner.id
        for member in obj.members:
            if mine or member.profile_id == owner.id:
                records.append({"entity_type": "group_member", "entity_id": member.id,
                                "payload": payload_for(session, "group_member", member)})
        if not mine:
            records = records[1:]  # a member may not write the group itself
    return records


def _upload_media(session: Session, transport: Transport, token: str, records: list[dict]) -> None:
    uploaded = set(json.loads(_get(session, "uploaded_media") or "[]"))
    wanted: list[dict] = []
    for record in records:
        payload = record.get("payload") or {}
        wanted += payload.get("media", [])
        for milestone in payload.get("milestones", []):
            wanted += milestone.get("media", [])
    for item in wanted:
        if item["id"] in uploaded:
            continue
        file = session.get(MediaFile, item["id"])
        if file is None or file.origin != "local":
            continue
        path = media_service.path_for(file)
        if not path.is_file():
            continue
        transport.put_bytes(
            f"/v1/media/{file.id}",
            path.read_bytes(),
            {
                "Content-Type": file.mime_type,
                "X-Entity-Type": file.entity_type,
                "X-Entity-Id": file.entity_id,
                "X-Media-Meta": json.dumps({"position": file.position, "width": file.width, "height": file.height}),
            },
            token,
        )
        uploaded.add(file.id)
    _set(session, "uploaded_media", json.dumps(sorted(uploaded)))


def push(session: Session, transport: Transport, token: str, owner: Profile) -> RunResult:
    result = RunResult()
    entries = list(
        session.scalars(select(SyncQueueEntry).where(SyncQueueEntry.status == "pending").order_by(SyncQueueEntry.id))
    )
    batch: list[dict] = []
    sent: list[SyncQueueEntry] = []
    for entry in entries:
        records = _records_for_entry(session, entry, owner)
        if records is None:
            entry.status = "held"
            continue
        batch += records
        sent.append(entry)

    for start in range(0, len(batch), 400):
        chunk = batch[start : start + 400]
        answer = transport.post("/v1/push", {"records": chunk}, token)
        result.pushed += answer.get("accepted", 0)
        for rejection in answer.get("rejected", []):
            result.errors.append(f"{rejection['entityType']} {rejection['entityId'][:8]}: {rejection['reason']}")
        _upload_media(session, transport, token, chunk)

    rejected_ids = {e.split(" ")[1] for e in result.errors if " " in e}
    for entry in sent:
        entry.attempts += 1
        if entry.entity_id[:8] in rejected_ids:
            entry.status = "failed"
            entry.last_error = next((e for e in result.errors if entry.entity_id[:8] in e), None)
        else:
            entry.status = "done"
            obj = session.get(MODELS.get(entry.entity_type, Profile), entry.entity_id) if entry.entity_type in MODELS else None
            if obj is not None and hasattr(obj, "sync_state"):
                obj.sync_state = "synced"
    _set(session, "last_push_at", datetime.now(timezone.utc).isoformat())
    return result


# --------------------------------------------------------------------------- #
# Pull
# --------------------------------------------------------------------------- #


def _convert(model: type, payload: dict[str, Any]) -> dict[str, Any]:
    columns = {c.key: c for c in inspect(model).mapper.column_attrs}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        column = columns.get(key)
        if column is None or key in LOCAL_ONLY:
            continue
        kind = column.columns[0].type
        if isinstance(value, str) and isinstance(kind, DateTime):
            value = datetime.fromisoformat(value)
        elif isinstance(value, str) and isinstance(kind, Date):
            value = date.fromisoformat(value)
        out[key] = value
    return out


def _snapshot(obj: Any) -> dict[str, Any]:
    data = _columns(obj)
    if isinstance(obj, Deal):
        data["milestones"] = [{"id": m.id, "status": m.status} for m in obj.milestones]
    return data


def _apply_one(session: Session, entity_type: str, entity_id: str, payload: dict, deleted: bool, owner: Profile):
    model = MODELS[entity_type]
    row = session.get(model, entity_id)
    before = _snapshot(row) if row is not None else None

    if deleted:
        if row is None or getattr(row, "origin", "synced") == "local":
            return None, before
        if hasattr(row, "visibility"):
            row.visibility = "offline"  # hide; keep what others' records point at
        else:
            session.delete(row)
        return row, before

    values = _convert(model, payload)
    if row is not None and getattr(row, "origin", None) == "local":
        # The owner made this record; the other side can only answer it.
        if entity_type == "deal":
            for key, value in values.items():
                if key not in ("id", "origin"):
                    setattr(row, key, value)
            _apply_milestones(session, row, payload.get("milestones", []))
        else:
            for key in COUNTERPARTY_FIELDS:
                if key in values:
                    setattr(row, key, values[key])
        return row, before

    if row is None:
        row = model(**values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    if hasattr(row, "origin"):
        row.origin = "synced"
    if hasattr(row, "sync_state"):
        row.sync_state = "synced"
    if entity_type == "profile":
        row.is_device_owner = False
    if entity_type == "land_share":
        row.parcel_id = None
    if entity_type == "deal":
        _apply_milestones(session, row, payload.get("milestones", []))
    session.flush()
    return row, before


def _apply_milestones(session: Session, deal: Deal, items: list[dict]) -> None:
    existing = {m.id: m for m in deal.milestones}
    keep = set()
    for item in items:
        values = _convert(Milestone, item)
        values.pop("deal_id", None)
        milestone = existing.get(item["id"])
        if milestone is None:
            milestone = Milestone(deal_id=deal.id, **values)
            deal.milestones.append(milestone)
        else:
            for key, value in values.items():
                setattr(milestone, key, value)
        keep.add(item["id"])
    for milestone_id, milestone in existing.items():
        if milestone_id not in keep:
            deal.milestones.remove(milestone)


def _fetch_media(session: Session, transport: Transport, token: str, entity_type: str, payload: dict) -> None:
    if entity_type in MEDIA_ENTITY and "media" in payload and payload.get("id"):
        # Pictures the owner has since removed go here too.
        keep = {item["id"] for item in payload["media"]}
        for file in media_service.for_entity(session, MEDIA_ENTITY[entity_type], payload["id"]):
            if file.origin != "local" and file.id not in keep:
                media_service.remove(session, file)
    items = list(payload.get("media", []))
    for milestone in payload.get("milestones", []):
        items += milestone.get("media", [])
    for item in items:
        if session.get(MediaFile, item["id"]) is not None:
            continue
        try:
            body, _headers = transport.get_bytes(f"/v1/media/{item['id']}", token)
        except SyncError as exc:
            logger.info("Picture %s not fetched: %s", item["id"], exc)
            continue
        file_name = f"{item['entity_type']}-{item['id']}.jpg"
        (media_service.media_dir() / file_name).write_bytes(body)
        session.add(
            MediaFile(
                id=item["id"], entity_type=item["entity_type"], entity_id=item["entity_id"],
                position=item.get("position", 0), file_name=file_name, mime_type="image/jpeg",
                width=item.get("width", 0), height=item.get("height", 0), size_bytes=len(body), origin="synced",
            )
        )


def _name(session: Session, profile_id: str | None) -> str:
    profile = session.get(Profile, profile_id) if profile_id else None
    return (profile.organisation_name or profile.display_name) if profile else ""


#: A promoted project alerts only those it suits better than an even match: a
#: viewer who stated no preferences scores exactly 50, and is not alerted.
ALERT_MIN_FIT = 51


def _promotion_alert(session: Session, request: InvestmentRequest, before: dict | None, owner: Profile) -> None:
    """An alerting promotion that is new to this device: tell its owner, once, if the project suits them."""
    from . import marketplace  # noqa: PLC0415

    def moment(value: datetime | str | None) -> datetime | None:
        # The snapshot before a pull holds text; SQLite hands times back without
        # a zone. Either way they were written in UTC.
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value

    alert_at = moment(request.promotion_alert_at)
    if alert_at is None or moment((before or {}).get("promotion_alert_at")) == alert_at:
        return
    if not marketplace.is_featured(request) or not marketplace.visible_to(request, owner):
        return
    match = marketplace.fit(request, owner)
    if match is None or match.score < ALERT_MIN_FIT:
        return
    place = ((request.listing or {}).get("location") or {}).get("district") or {}
    notify(session, owner.id, "project_featured",
           params={"title": request.title, "place": place.get("name", ""), "score": match.score},
           link="/", entity_type="investment_request", entity_id=request.id)


def _hooks(session: Session, entity_type: str, row: Any, before: dict | None, owner: Profile) -> None:
    """Turn what the other side did into a notification for the owner."""
    from . import connections, directory  # noqa: PLC0415
    from .groups import on_join_request  # noqa: PLC0415
    from .messages import receive  # noqa: PLC0415
    from .trust import on_incoming_deal  # noqa: PLC0415

    was = (before or {}).get("status")
    if entity_type == "connection":
        connections.on_incoming(session, row, before, owner)
    elif entity_type == "project_invite":
        directory.on_incoming(session, row, before, owner)
    elif entity_type == "land_share" and row.visibility == "online" and row.profile_id != owner.id:
        if before is None or (before or {}).get("visibility") != "online":
            notify(session, owner.id, "land_shared",
                   params={"name": _name(session, row.profile_id), "plot": (row.snapshot or {}).get("label", "")},
                   link="/timeline", entity_type=entity_type, entity_id=row.id)
    elif entity_type == "farm_update" and before is None and row.profile_id != owner.id:
        notify(session, owner.id, "update_posted",
               params={"name": _name(session, row.profile_id), "text": row.body[:80]},
               link="/timeline", entity_type=entity_type, entity_id=row.id)
    elif entity_type == "investment_request" and row.profile_id != owner.id:
        _promotion_alert(session, row, before, owner)
    elif entity_type == "investment_interest":
        request = session.get(InvestmentRequest, row.request_id)
        if before is None and request and request.profile_id == owner.id:
            notify(session, owner.id, "interest_received",
                   params={"name": _name(session, row.profile_id), "title": request.title},
                   link="/requests", entity_type=entity_type, entity_id=row.id)
        elif was != row.status and row.profile_id == owner.id and row.status in ("accepted", "declined"):
            notify(session, owner.id, f"interest_{row.status}",
                   params={"title": request.title if request else ""},
                   link="/interests", entity_type=entity_type, entity_id=row.id)
    elif entity_type == "equipment_enquiry":
        listing = session.get(EquipmentListing, row.listing_id)
        if before is None and listing and listing.profile_id == owner.id:
            notify(session, owner.id, "enquiry_received",
                   params={"name": _name(session, row.profile_id), "title": listing.title, "kind": row.kind},
                   link="/my-machines", entity_type=entity_type, entity_id=row.id)
        elif was != row.status and row.status == "completed" and listing:
            # The other side marked the hire or sale done: time to rate them.
            enquirer = row.profile_id == owner.id
            if enquirer or listing.profile_id == owner.id:
                other = listing.profile_id if enquirer else row.profile_id
                notify(session, owner.id, "enquiry_completed",
                       params={"title": listing.title, "name": _name(session, other)},
                       link="/machines" if enquirer else "/my-machines", entity_type=entity_type, entity_id=row.id)
        elif was != row.status and row.profile_id == owner.id and row.status in ("accepted", "declined"):
            notify(session, owner.id, f"enquiry_{row.status}",
                   params={"title": listing.title if listing else ""},
                   link="/machines", entity_type=entity_type, entity_id=row.id)
    elif entity_type == "equipment_partnership":
        if owner.id not in (row.seller_profile_id, row.partner_profile_id):
            return
        other = row.partner_profile_id if owner.id == row.seller_profile_id else row.seller_profile_id
        if before is None:
            notify(session, owner.id, "partnership_requested", params={"name": _name(session, other)},
                   link="/partners" if owner.id == row.seller_profile_id else "/machines",
                   entity_type=entity_type, entity_id=row.id)
        elif was != row.status:
            notify(session, owner.id, "partnership_answered",
                   params={"name": _name(session, other), "status": row.status},
                   link="/partners" if owner.id == row.seller_profile_id else "/machines",
                   entity_type=entity_type, entity_id=row.id)
    elif entity_type == "message" and before is None:
        receive(session, row)
    elif entity_type == "deal":
        on_incoming_deal(session, row, before)
    elif entity_type == "dispute":
        deal = session.get(Deal, row.deal_id)
        if deal and owner.id in (deal.farmer_profile_id, deal.investor_profile_id):
            if before is None:
                notify(session, owner.id, "dispute_opened", params={"reason": row.reason},
                       link=f"/deals/{deal.id}", entity_type=entity_type, entity_id=row.id)
            elif was != row.status or (before or {}).get("resolution") != row.resolution:
                notify(session, owner.id, "dispute_updated", params={"status": row.status},
                       link=f"/deals/{deal.id}", entity_type=entity_type, entity_id=row.id)
    elif entity_type == "rating" and before is None and row.rated_profile_id == owner.id:
        notify(session, owner.id, "rating_received",
               params={"name": _name(session, row.rater_profile_id), "stars": row.stars},
               link="/profile", entity_type=entity_type, entity_id=row.id)
    elif entity_type == "group_member":
        group = session.get(FarmerGroup, row.group_id)
        if group is None:
            return
        if before is None and row.status == "requested" and group.owner_profile_id == owner.id:
            on_join_request(session, group, row)
        elif was != row.status and row.profile_id == owner.id:
            notify(session, owner.id, "group_join_answered", params={"group": group.name, "status": row.status},
                   link=f"/groups/{group.id}", entity_type=entity_type, entity_id=row.id)


def pull(session: Session, transport: Transport, token: str, owner: Profile) -> RunResult:
    result = RunResult()
    since = int(_get(session, "pull_rev") or 0)
    retry = json.loads(_get(session, "retry_inbound") or "[]")
    while True:
        answer = transport.get("/v1/pull", {"since": since, "limit": 500}, token)
        page = retry + answer.get("records", [])
        retry = []
        page.sort(key=lambda r: (APPLY_ORDER.index(r["entityType"]) if r["entityType"] in APPLY_ORDER else 99, r.get("rev", 0)))
        for record in page:
            entity_type = record["entityType"]
            if entity_type not in MODELS:
                continue
            savepoint = session.begin_nested()
            try:
                row, before = _apply_one(
                    session, entity_type, record["entityId"], record.get("payload") or {},
                    record.get("deleted", False), owner,
                )
                savepoint.commit()
            except IntegrityError as exc:
                savepoint.rollback()
                # A parent has not arrived yet; try again next time.
                retry.append(record)
                logger.info("Holding %s %s: %s", entity_type, record["entityId"], exc.orig)
                continue
            result.pulled += 1
            if row is not None and not record.get("deleted"):
                _fetch_media(session, transport, token, entity_type, record.get("payload") or {})
                _hooks(session, entity_type, row, before, owner)
        since = answer.get("nextRev", since)
        if not answer.get("more"):
            break
    _set(session, "pull_rev", str(since))
    _set(session, "retry_inbound", json.dumps(retry[-500:]))
    _set(session, "last_pull_at", datetime.now(timezone.utc).isoformat())
    return result


# --------------------------------------------------------------------------- #
# One run
# --------------------------------------------------------------------------- #


#: A device swaps its sync token for a new one this often, so a token copied
#: off an old backup or a lost phone does not stay good for ever.
TOKEN_LIFETIME = timedelta(days=90)


def _fresh_token(session: Session, transport: Transport, token: str) -> str:
    """The token to sync with: the same one, or a new one once it is old."""
    issued = _when(session, "token_issued_at")
    now = datetime.now(timezone.utc)
    if issued is None:
        # Issued before tokens were dated: start its clock now.
        _set(session, "token_issued_at", now.isoformat())
        return token
    if now - (issued if issued.tzinfo else issued.replace(tzinfo=timezone.utc)) < TOKEN_LIFETIME:
        return token
    try:
        answer = transport.post("/v1/devices/rotate", {}, token)
    except SyncError as exc:
        if exc.status == 404:  # a server from before rotation
            return token
        raise
    _set(session, "token", answer["token"])
    _set(session, "token_issued_at", now.isoformat())
    return answer["token"]


def run(session: Session, transport: Transport | None = None) -> RunResult:
    url = _get(session, "server_url")
    if not url:
        raise SyncError("Sync is off. Set a sync server first.", 409)
    owner = get_owner(session)
    if owner is None:
        raise SyncError("Set up your profile first.", 409)
    transport = transport or HttpTransport(url)
    try:
        token = _fresh_token(session, transport, _register(session, transport, owner))
        pushed = push(session, transport, token, owner)
        pulled = pull(session, transport, token, owner)
    except SyncError as exc:
        _set(session, "last_error", str(exc))
        raise
    errors = pushed.errors + pulled.errors
    _set(session, "last_error", "; ".join(errors)[:1000] if errors else None)
    return RunResult(pushed=pushed.pushed, pulled=pulled.pulled, errors=errors)
