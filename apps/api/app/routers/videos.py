"""Introduction and biodata videos: YouTube links, and uploads for subscribers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Profile, VideoUpload
from ..schemas import VideoLinkInput, VideoOut, VideoPlanOut, VideoUploadOut
from ..services import videos
from ..services.videos import VideoError
from .deps import fail, owner

router = APIRouter(prefix="/videos", tags=["videos"])


@router.get("/plan", response_model=VideoPlanOut)
def video_plan(session: Session = Depends(get_session)) -> VideoPlanOut:
    """Whether the owner may upload videos directly, as the sync server says."""
    result = videos.plan(session)
    session.commit()
    return result


@router.get("/uploads", response_model=list[VideoUploadOut])
def list_uploads(session: Session = Depends(get_session)) -> list[VideoUploadOut]:
    """The owner's uploads. Asking also nudges any that are waiting along."""
    rows = videos.uploads(session)
    if any(row.status in ("queued", "uploading", "processing") for row in rows):
        videos.kick()
    return rows


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_upload(upload_id: str, session: Session = Depends(get_session)) -> None:
    upload = session.get(VideoUpload, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if upload.status in ("queued", "uploading", "processing"):
        upload.status, upload.error = "failed", "Cancelled."
        videos.upload_path(upload).unlink(missing_ok=True)
    session.commit()


@router.put("/{target}/{entity_id}", response_model=VideoOut)
def set_youtube(
    target: str,
    entity_id: str,
    payload: VideoLinkInput,
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> VideoOut:
    """Set an item's video to a YouTube link."""
    try:
        obj = videos.set_youtube(session, me, target, entity_id, payload.url)
    except VideoError as exc:
        raise fail(exc) from exc
    session.commit()
    return videos.out(getattr(obj, videos.TARGETS[target].column))  # type: ignore[return-value]


@router.delete("/{target}/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_video(
    target: str, entity_id: str, me: Profile = Depends(owner), session: Session = Depends(get_session)
) -> None:
    try:
        videos.remove(session, me, target, entity_id)
    except VideoError as exc:
        raise fail(exc) from exc
    session.commit()


@router.post("/{target}/{entity_id}/upload", response_model=VideoUploadOut, status_code=201)
async def upload_video(
    target: str,
    entity_id: str,
    request: Request,
    me: Profile = Depends(owner),
    session: Session = Depends(get_session),
) -> VideoUploadOut:
    """Take a video file for a subscriber and send it on in the background.

    The body is the file itself. It is written to disk as it arrives, so a
    large video never sits in memory, and the answer comes back as soon as it
    is saved -- the slow part, reaching Mux, happens afterwards.
    """
    mime = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    try:
        upload = videos.start_upload(session, me, target, entity_id, mime)
    except VideoError as exc:
        raise fail(exc) from exc

    path = videos.upload_path(upload)
    size = 0
    try:
        with path.open("wb") as file:
            async for chunk in request.stream():
                size += len(chunk)
                if size > videos.MAX_VIDEO_BYTES:
                    raise VideoError("Videos can be up to 2 GB.", 413)
                file.write(chunk)
        videos.finish_upload(session, upload, size)
    except VideoError as exc:
        path.unlink(missing_ok=True)
        raise fail(exc) from exc
    session.commit()
    videos.kick()
    return videos.serialise(upload)
