"""Backups, restore, export and erasure, and the insights dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from ..db import engine, get_session
from ..models import Profile
from ..schemas import BackupOut, EraseInput, InsightsOut, RestoreOut
from ..services import datacare, insights
from .deps import fail, owner

router = APIRouter(tags=["data"])


@router.get("/backups", response_model=list[BackupOut])
def list_backups() -> list[BackupOut]:
    return datacare.list_backups()


@router.post("/backups", response_model=BackupOut, status_code=status.HTTP_201_CREATED)
def create_backup(session: Session = Depends(get_session)) -> BackupOut:
    """Database, pictures and reports in one zip, for a USB stick."""
    backup = datacare.create_backup(session, engine)
    session.commit()
    return backup


@router.get("/backups/{name}")
def download_backup(name: str) -> FileResponse:
    try:
        path = datacare.backup_path(name)
    except datacare.DataError as exc:
        raise fail(exc) from exc
    return FileResponse(path, media_type="application/zip", filename=name)


@router.post("/backups/restore", response_model=RestoreOut)
async def restore(request: Request) -> RestoreOut:
    """Stage a backup (the body is the zip) to be applied at the next start."""
    try:
        message = datacare.stage_restore(await request.body())
    except datacare.DataError as exc:
        raise fail(exc) from exc
    return RestoreOut(staged=True, message=message)


@router.get("/my-data")
def export_my_data(me: Profile = Depends(owner), session: Session = Depends(get_session)) -> JSONResponse:
    """A copy of everything this device holds about its owner."""
    data = datacare.export(session, me)
    session.commit()
    return JSONResponse(
        data,
        headers={"Content-Disposition": 'attachment; filename="viksitgaanw-my-data.json"'},
    )


@router.post("/my-data/erase")
def erase_my_data(payload: EraseInput, me: Profile = Depends(owner), session: Session = Depends(get_session)) -> dict:
    """Erase the owner and everything that is theirs. Irreversible."""
    try:
        counts = datacare.erase(session, me, payload.confirm)
    except datacare.DataError as exc:
        raise fail(exc) from exc
    session.commit()
    return {"erased": True, **counts}


@router.get("/insights", response_model=InsightsOut)
def get_insights(me: Profile = Depends(owner), session: Session = Depends(get_session)) -> InsightsOut:
    """Activity across the area the owner is responsible for."""
    return insights.compute(session, me)
