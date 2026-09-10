"""Serving stored pictures back to the app."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import MediaFile
from ..services import media

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/{media_id}")
def get_media(media_id: str, session: Session = Depends(get_session)) -> FileResponse:
    file = session.get(MediaFile, media_id)
    if file is None or not media.path_for(file).is_file():
        raise HTTPException(status_code=404, detail="Picture not found.")
    # The id is random and never reused, so a picture never changes under it.
    return FileResponse(
        media.path_for(file),
        media_type=file.mime_type,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
