"""Introduction and biodata videos.

Every item people post -- a plot, a project request, a machine, a farmer group
-- can carry an **introduction video**, and every profile a **biodata video**:
the person telling their own story in their own words, which says more to a
reader who reads slowly than any form. An investor, or a partner who invests,
also gets a **listing video** about what they fund, shown under "Find
investors".

A video is a YouTube link, or -- for subscribers -- a file uploaded directly.

* **YouTube.** Only the 11-character video id is kept and synced, so a link
  costs nothing to store or send. It plays from YouTube when the device is
  online.
* **Direct upload (Mux).** The file goes to Mux, a video host, which encodes
  it for slow connections. The Mux keys live on the sync server, never on a
  villager's device: the server checks the subscription, asks Mux for an
  upload address, and later hands back the playback id. The file waits in the
  media folder and is sent in 8 MB pieces, so an upload cut off by a dropped
  connection carries on from where it stopped the next time the device is
  online. Other people only ever see the finished video -- the upload itself
  stays on the uploader's device (``VideoUpload``).

Either way the item stores ``{"provider": "youtube"|"mux", "id": ...}``.
"""

from __future__ import annotations

import http.client
import json
import logging
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import segments as seg
from ..models import (
    EquipmentListing,
    FarmerGroup,
    InvestmentRequest,
    LandParcel,
    Profile,
    VideoUpload,
)
from ..schemas import VideoOut, VideoPlanOut, VideoUploadOut
from . import media
from .events import EventType, enqueue_sync, record_event

logger = logging.getLogger("viksitgaanw.videos")


class VideoError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# What can carry a video
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Target:
    model: type
    column: str
    #: The sync entity that carries the column -- None for a plot, which never
    #: leaves the device; its shared card does (services/landshare).
    entity_type: str | None


TARGETS: dict[str, Target] = {
    "biodata": Target(Profile, "biodata_video", "profile"),
    "listing": Target(Profile, "intro_video", "profile"),
    "land": Target(LandParcel, "intro_video", None),
    "request": Target(InvestmentRequest, "intro_video", "investment_request"),
    "machine": Target(EquipmentListing, "intro_video", "equipment_listing"),
    "group": Target(FarmerGroup, "intro_video", "farmer_group"),
}


def lists_investments(profile: Profile) -> bool:
    """Whether the profile is an investor listing: an investor, or a partner who invests."""
    return "investment" in seg.interest_kinds(profile.segment, profile.details)


def owned(session: Session, owner: Profile, target: str, entity_id: str) -> Any:
    """The row a video goes on, if the owner may change it."""
    spec = TARGETS.get(target)
    if spec is None:
        raise VideoError("Videos cannot be added there.", 404)
    obj = session.get(spec.model, entity_id)
    if obj is None:
        raise VideoError("Not found.", 404)
    mine = {
        "biodata": lambda: obj.id == owner.id,
        "listing": lambda: obj.id == owner.id and lists_investments(owner),
        "land": lambda: not owner.farmer_id or obj.farmer_id == owner.farmer_id,
        "request": lambda: obj.profile_id == owner.id,
        "machine": lambda: obj.profile_id == owner.id,
        "group": lambda: obj.owner_profile_id == owner.id,
    }[target]()
    if not mine:
        raise VideoError("Only its owner can change this video.", 403)
    return obj


def out(value: dict | None) -> VideoOut | None:
    """A stored video as the API shows it; anything malformed shows as none."""
    if not value or value.get("provider") not in ("youtube", "mux") or not value.get("id"):
        return None
    return VideoOut(provider=value["provider"], id=value["id"])


def _changed(session: Session, target: str, obj: Any) -> None:
    """Send the change wherever the item goes."""
    from . import landshare  # noqa: PLC0415 - landshare imports media, as does this

    spec = TARGETS[target]
    if spec.entity_type is None:
        landshare.refresh(session, obj)
        return
    if getattr(obj, "sync_state", None) == "synced":
        obj.sync_state = "queued"
    # Held on the device while the item is offline, like any other change.
    enqueue_sync(session, entity_type=spec.entity_type, entity_id=obj.id, operation="update")


def _store(session: Session, target: str, obj: Any, value: dict | None) -> None:
    setattr(obj, TARGETS[target].column, value)
    session.flush()
    _changed(session, target, obj)


# --------------------------------------------------------------------------- #
# YouTube
# --------------------------------------------------------------------------- #

_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
}
#: Path forms that carry the id as their second segment: /shorts/<id>, ...
_ID_PATHS = {"shorts", "embed", "live", "v", "e"}


def youtube_id(text: str) -> str:
    """The video id in any of the links YouTube hands out, or an error.

    Accepts watch links, youtu.be short links, Shorts, embeds and live links,
    with or without https:// -- whatever a farmer copies from the YouTube app.
    """
    text = text.strip()
    if _YOUTUBE_ID.match(text):
        return text
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        raise VideoError("Paste a YouTube link, like https://youtu.be/abc123XYZ_0")

    candidate: str | None = None
    if host.endswith("youtu.be"):
        candidate = next((part for part in parts.path.split("/") if part), None)
    else:
        query = parse_qs(parts.query)
        if query.get("v"):
            candidate = query["v"][0]
        else:
            segments = [part for part in parts.path.split("/") if part]
            if len(segments) >= 2 and segments[0] in _ID_PATHS:
                candidate = segments[1]
    if not candidate or not _YOUTUBE_ID.match(candidate):
        raise VideoError("That link does not point to one YouTube video.")
    return candidate


def set_youtube(session: Session, owner: Profile, target: str, entity_id: str, url: str) -> Any:
    obj = owned(session, owner, target, entity_id)
    video_id = youtube_id(url)
    _cancel_uploads(session, target, entity_id)
    _store(session, target, obj, {"provider": "youtube", "id": video_id})
    record_event(session, EventType.VIDEO_SET, entity_type=target, entity_id=entity_id,
                 payload={"provider": "youtube"})
    return obj


def remove(session: Session, owner: Profile, target: str, entity_id: str) -> Any:
    obj = owned(session, owner, target, entity_id)
    _cancel_uploads(session, target, entity_id)
    if getattr(obj, TARGETS[target].column) is not None:
        _store(session, target, obj, None)
        record_event(session, EventType.VIDEO_REMOVED, entity_type=target, entity_id=entity_id)
    return obj


# --------------------------------------------------------------------------- #
# Subscription
# --------------------------------------------------------------------------- #

PLAN_KEY = "video_plan"


def _cached_plan(session: Session) -> dict[str, Any]:
    from .sync_client import _get  # noqa: PLC0415

    raw = _get(session, PLAN_KEY)
    return json.loads(raw) if raw else {}


def _plan_out(data: dict[str, Any], reason: str | None = None) -> VideoPlanOut:
    until = date.fromisoformat(data["until"]) if data.get("until") else None
    subscribed = bool(data.get("active")) and (until is None or until >= date.today())
    if reason is None and not subscribed:
        reason = "not_subscribed"
    if reason is None and not data.get("uploads"):
        reason = "server_off"
    return VideoPlanOut(
        subscribed=subscribed,
        plan=data.get("plan"),
        until=until,
        uploads_available=bool(data.get("uploads")),
        reason=reason,
    )


def plan(session: Session, transport: Any = None) -> VideoPlanOut:
    """Ask the sync server whether the owner is subscribed, and remember it.

    The server is the only source of truth -- a device cannot switch itself
    on. Offline, the last answer stands.
    """
    from . import sync_client  # noqa: PLC0415 - sync_client imports this module
    from .profiles import get_owner  # noqa: PLC0415

    url = sync_client._get(session, "server_url")
    if not url:
        return VideoPlanOut(subscribed=False, reason="sync_off")
    owner = get_owner(session)
    if owner is None:
        return VideoPlanOut(subscribed=False, reason="no_profile")
    transport = transport or sync_client.HttpTransport(url)
    try:
        token = sync_client._register(session, transport, owner)
        answer = transport.get("/v1/me", {}, token)
    except sync_client.SyncError:
        cached = _cached_plan(session)
        return _plan_out(cached, reason="offline") if not cached.get("active") else _plan_out(cached)
    subscription = answer.get("subscription") or {}
    data = {
        "active": bool(subscription.get("active")),
        "plan": subscription.get("plan"),
        "until": subscription.get("until"),
        "uploads": bool(answer.get("videoUploads")),
    }
    sync_client._set(session, PLAN_KEY, json.dumps(data))
    return _plan_out(data)


# --------------------------------------------------------------------------- #
# Direct uploads
# --------------------------------------------------------------------------- #

#: Largest file accepted. Mux takes far more; a village connection does not.
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
ACCEPTED_VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/3gpp": ".3gp",
    "video/x-msvideo": ".avi",
}
#: Size of each piece sent to Mux. Must be a multiple of 256 KiB.
CHUNK_BYTES = 8 * 1024 * 1024
#: The worker runs on its own thread in the app; tests drive it directly.
BACKGROUND = True
#: Mux says so for a whole second at least; no point asking more often.
CHECK_EVERY_SECONDS = 5


def _video_dir() -> Path:
    path = media.media_dir() / "videos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def upload_path(upload: VideoUpload) -> Path:
    return _video_dir() / upload.file_name


def start_upload(session: Session, owner: Profile, target: str, entity_id: str, mime_type: str) -> VideoUpload:
    """Check an upload may begin; the router then streams the file to disk."""
    owned(session, owner, target, entity_id)
    if mime_type not in ACCEPTED_VIDEO_TYPES:
        raise VideoError("Choose a video file: MP4, MOV, WebM, MKV, 3GP or AVI.", 415)
    cached = _plan_out(_cached_plan(session))
    if not cached.subscribed:
        raise VideoError("Uploading videos directly is for subscribers. Add a YouTube link instead.", 402)
    upload_id = str(uuid.uuid4())
    return VideoUpload(
        id=upload_id,
        target=target,
        entity_id=entity_id,
        file_name=f"{upload_id}{ACCEPTED_VIDEO_TYPES[mime_type]}",
        mime_type=mime_type,
        size=0,
    )


def finish_upload(session: Session, upload: VideoUpload, size: int) -> VideoUpload:
    """The file is on disk: queue it, replacing anything still pending for that item."""
    if size == 0:
        upload_path(upload).unlink(missing_ok=True)
        raise VideoError("The file was empty.")
    _cancel_uploads(session, upload.target, upload.entity_id)
    upload.size = size
    session.add(upload)
    session.flush()
    record_event(session, EventType.VIDEO_UPLOAD_STARTED, entity_type=upload.target,
                 entity_id=upload.entity_id, payload={"bytes": size})
    return upload


def _cancel_uploads(session: Session, target: str, entity_id: str) -> None:
    for upload in session.scalars(
        select(VideoUpload).where(
            VideoUpload.target == target,
            VideoUpload.entity_id == entity_id,
            VideoUpload.status.in_(("queued", "uploading", "processing")),
        )
    ):
        upload.status = "failed"
        upload.error = "Replaced by a newer video."
        upload_path(upload).unlink(missing_ok=True)


def serialise(upload: VideoUpload) -> VideoUploadOut:
    progress = 100 if upload.status in ("processing", "ready") else (
        int(upload.bytes_sent * 100 / upload.size) if upload.size else 0
    )
    return VideoUploadOut(
        id=upload.id,
        target=upload.target,
        entity_id=upload.entity_id,
        status=upload.status,  # type: ignore[arg-type]
        size=upload.size,
        bytes_sent=upload.bytes_sent,
        progress=progress,
        error=upload.error,
        created_at=upload.created_at,
    )


def uploads(session: Session) -> list[VideoUploadOut]:
    """Uploads still under way, and ones that finished or failed in the last day."""
    rows = session.scalars(select(VideoUpload).order_by(VideoUpload.created_at.desc()).limit(50))
    return [serialise(row) for row in rows]


# ---- sending the file ------------------------------------------------------ #


def _http_put(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, dict[str, str]]:
    """One PUT to the upload address Mux gave. 308 means "keep going"."""
    parts = urlsplit(url)
    connection_class = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    connection = connection_class(parts.netloc, timeout=120)
    try:
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        connection.request("PUT", path, body=body, headers=headers)
        response = connection.getresponse()
        response.read()
        return response.status, {key.lower(): value for key, value in response.getheaders()}
    finally:
        connection.close()


#: Replaced in tests, where Mux's upload address is not a real server.
put_chunk: Callable[[str, bytes, dict[str, str]], tuple[int, dict[str, str]]] = _http_put


def _received(headers: dict[str, str]) -> int | None:
    """Bytes the upload address already holds, from a 308's Range header."""
    match = re.match(r"bytes=0-(\d+)", headers.get("range", ""))
    return int(match.group(1)) + 1 if match else None


def _send(upload: VideoUpload, save: Callable[[], None]) -> None:
    """Send the rest of the file, a piece at a time, saving progress as it goes."""
    from .sync_client import SyncError  # noqa: PLC0415

    path = upload_path(upload)
    if not path.is_file():
        raise VideoError("The video file is no longer on this device. Choose it again.")
    total = upload.size
    if upload.bytes_sent:
        # Resuming: ask how much really arrived before the connection dropped.
        status, headers = put_chunk(upload.upload_url or "", b"", {"Content-Range": f"bytes */{total}"})
        if status in (200, 201):
            upload.bytes_sent = total
            return
        upload.bytes_sent = _received(headers) or 0
    with path.open("rb") as file:
        while upload.bytes_sent < total:
            file.seek(upload.bytes_sent)
            piece = file.read(CHUNK_BYTES)
            end = upload.bytes_sent + len(piece) - 1
            try:
                status, headers = put_chunk(
                    upload.upload_url or "",
                    piece,
                    {"Content-Type": upload.mime_type, "Content-Length": str(len(piece)),
                     "Content-Range": f"bytes {upload.bytes_sent}-{end}/{total}"},
                )
            except OSError as exc:
                raise SyncError(f"Upload interrupted: {exc}", 503) from exc
            if status in (200, 201):
                upload.bytes_sent = total
            elif status == 308:
                upload.bytes_sent = _received(headers) or end + 1
            elif 400 <= status < 500:
                # The address expired (Mux keeps it for a week) or was refused:
                # ask for a new one and start again.
                raise VideoError(f"The upload address was refused ({status}).", 410)
            else:
                raise SyncError(f"Video host said {status}.", 503)
            save()


def _step(session: Session, upload: VideoUpload, transport: Any, token: str, owner: Profile) -> None:
    from .notify import notify  # noqa: PLC0415

    spec = TARGETS[upload.target]
    obj = session.get(spec.model, upload.entity_id)
    if obj is None:
        upload.status, upload.error = "failed", "The item was deleted."
        upload_path(upload).unlink(missing_ok=True)
        return

    if upload.status == "queued":
        answer = transport.post(
            "/v1/videos/uploads",
            {"target": upload.target, "entity_id": upload.entity_id, "size": upload.size},
            token,
        )
        upload.mux_upload_id, upload.upload_url = answer["uploadId"], answer["url"]
        upload.status, upload.bytes_sent, upload.error = "uploading", 0, None
        session.commit()

    if upload.status == "uploading":
        try:
            _send(upload, session.commit)
        except VideoError as exc:
            if exc.status == 410:
                upload.status, upload.bytes_sent, upload.upload_url = "queued", 0, None
                upload.error = str(exc)
                return
            raise
        upload.status = "processing"
        upload_path(upload).unlink(missing_ok=True)
        session.commit()

    if upload.status == "processing":
        if upload.updated_at and (_now() - _aware(upload.updated_at)).total_seconds() < CHECK_EVERY_SECONDS:
            return
        answer = transport.get(f"/v1/videos/uploads/{upload.mux_upload_id}", {}, token)
        upload.updated_at = _now()
        state = answer.get("status")
        if state == "ready" and answer.get("playbackId"):
            upload.status, upload.playback_id, upload.error = "ready", answer["playbackId"], None
            _store(session, upload.target, obj, {"provider": "mux", "id": answer["playbackId"]})
            record_event(session, EventType.VIDEO_UPLOADED, entity_type=upload.target,
                         entity_id=upload.entity_id, payload={"bytes": upload.size})
            notify(session, owner.id, "video_ready", link=_link_for(upload), entity_type="video_upload",
                   entity_id=upload.id)
        elif state in ("errored", "cancelled"):
            upload.status, upload.error = "failed", answer.get("error") or "The video could not be processed."
        elif state == "timed_out":
            upload.status, upload.bytes_sent, upload.upload_url = "queued", 0, None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _link_for(upload: VideoUpload) -> str:
    return {
        "biodata": "/profile", "listing": "/profile", "land": "/", "request": "/requests",
        "machine": "/my-machines", "group": f"/groups/{upload.entity_id}",
    }.get(upload.target, "/")


def work(session: Session, transport: Any = None) -> int:
    """Move every pending upload as far as it will go now. Returns how many are left."""
    from . import sync_client  # noqa: PLC0415
    from .profiles import get_owner  # noqa: PLC0415

    url = sync_client._get(session, "server_url")
    owner = get_owner(session)
    pending = list(
        session.scalars(
            select(VideoUpload)
            .where(VideoUpload.status.in_(("queued", "uploading", "processing")))
            .order_by(VideoUpload.created_at)
        )
    )
    if not pending or not url or owner is None:
        return len(pending)
    transport = transport or sync_client.HttpTransport(url)
    try:
        token = sync_client._register(session, transport, owner)
    except sync_client.SyncError:
        return len(pending)
    for upload in pending:
        try:
            _step(session, upload, transport, token, owner)
        except sync_client.SyncError as exc:
            upload.error = str(exc)
            if exc.status in (401, 402, 403, 404, 413, 422):
                upload.status = "failed"
                upload_path(upload).unlink(missing_ok=True)
                continue
            break  # offline: try again later
        except VideoError as exc:
            upload.status, upload.error = "failed", str(exc)
        session.commit()
    return sum(1 for upload in pending if upload.status in ("queued", "uploading", "processing"))


_lock = threading.Lock()


def kick() -> None:
    """Carry on with pending uploads in the background, if not already doing so."""
    if not BACKGROUND or not _lock.acquire(blocking=False):
        return

    def run() -> None:
        from ..db import session_scope  # noqa: PLC0415

        try:
            with session_scope() as session:
                work(session)
        except Exception:  # noqa: BLE001 - a background thread must not die loudly
            logger.exception("Video upload worker stopped")
        finally:
            _lock.release()

    threading.Thread(target=run, name="video-uploads", daemon=True).start()
