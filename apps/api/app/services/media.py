"""Profile photos, organisation logos and pictures of machines.

Pictures are stored on the device, in the media directory beside the
database, and follow the same offline-first rule as everything else: nothing
leaves the device until its owner shares the profile or listing online.

Every upload is re-encoded rather than stored as sent. That does three jobs:
it proves the bytes really are an image, it drops EXIF -- which on a phone
photo carries the GPS position of wherever it was taken, very often a
farmer's own house -- and it shrinks a 12-megapixel camera photo to
something a shared village laptop can show quickly.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import MediaFile

#: Largest upload accepted, before re-encoding.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
#: Longest side after resizing. A profile photo never shows larger than a card.
MAX_SIDE = {"profile": 512, "equipment": 1280, "milestone": 1280, "diary": 1280, "land": 1280, "update": 1280}
#: Pictures each kind of thing may carry. Milestone photos are evidence.
MAX_PER_ENTITY = {"profile": 1, "equipment": 4, "milestone": 6, "diary": 4, "land": 4, "update": 2}
ACCEPTED_TYPES = {"image/jpeg", "image/png", "image/webp"}


class MediaError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def media_dir() -> Path:
    directory = get_settings().media_dir
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def url_for(media: MediaFile) -> str:
    return f"/media/{media.id}"


def path_for(media: MediaFile) -> Path:
    return media_dir() / media.file_name


def for_entity(session: Session, entity_type: str, entity_id: str) -> list[MediaFile]:
    return list(
        session.scalars(
            select(MediaFile)
            .where(MediaFile.entity_type == entity_type, MediaFile.entity_id == entity_id)
            .order_by(MediaFile.position, MediaFile.created_at)
        )
    )


def first_url(session: Session, entity_type: str, entity_id: str) -> str | None:
    files = for_entity(session, entity_type, entity_id)
    return url_for(files[0]) if files else None


def _encode(data: bytes, max_side: int) -> tuple[bytes, int, int]:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise MediaError("That file is not a picture the app can read.") from exc

    # Phones store "which way up" in EXIF; apply it before EXIF is dropped,
    # or every portrait photo ends up on its side.
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        alpha = image.convert("RGBA")
        background.paste(alpha, mask=alpha.split()[-1])
        image = background
    image.thumbnail((max_side, max_side))

    out = io.BytesIO()
    # Saving without an ``exif=`` argument writes no EXIF at all.
    image.convert("RGB").save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue(), image.width, image.height


def save(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    data: bytes,
    content_type: str | None,
    replace: bool = False,
) -> MediaFile:
    if entity_type not in MAX_SIDE:
        raise MediaError(f"Pictures cannot be attached to {entity_type}.")
    if content_type and content_type.split(";")[0].strip() not in ACCEPTED_TYPES:
        raise MediaError("Upload a JPEG, PNG or WebP picture.", 415)
    if not data:
        raise MediaError("The picture is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise MediaError("The picture is larger than 8 MB.", 413)

    existing = for_entity(session, entity_type, entity_id)
    if replace:
        for media in existing:
            remove(session, media)
        existing = []
    elif len(existing) >= MAX_PER_ENTITY[entity_type]:
        raise MediaError(
            f"At most {MAX_PER_ENTITY[entity_type]} pictures can be added here.", 409
        )

    encoded, width, height = _encode(data, MAX_SIDE[entity_type])
    file_name = f"{entity_type}-{uuid.uuid4().hex}.jpg"
    (media_dir() / file_name).write_bytes(encoded)

    media = MediaFile(
        entity_type=entity_type,
        entity_id=entity_id,
        position=(max((m.position for m in existing), default=-1) + 1),
        file_name=file_name,
        mime_type="image/jpeg",
        width=width,
        height=height,
        size_bytes=len(encoded),
    )
    session.add(media)
    session.flush()
    return media


def remove(session: Session, media: MediaFile) -> None:
    try:
        path_for(media).unlink(missing_ok=True)
    except OSError:
        # A locked file on Windows is not worth failing the request over; the
        # row goes, and an orphaned JPEG in the media folder is harmless.
        pass
    session.delete(media)


def remove_all(session: Session, entity_type: str, entity_id: str) -> None:
    for media in for_entity(session, entity_type, entity_id):
        remove(session, media)
