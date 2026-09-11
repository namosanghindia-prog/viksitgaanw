"""Backups, restore, and a person's rights over their own data.

**Backup.** The device holds the only copy of a farmer's records. A laptop
that dies, is stolen or floods takes years of farm diary and every project
report with it, so a backup is one tap: the database, the pictures and the
reports in a single zip, for a USB stick or a phone.

**Restore** cannot swap the database under a running server, so it is staged
beside it and applied the next time the app starts.

**Export and erasure.** India's Digital Personal Data Protection Act gives a
person the right to a copy of their data and to have it erased. Export is a
readable JSON file of everything this device holds about its owner; erasure
removes it, keeping only the government location directory and anything
that belongs to other people.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, inspect, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    AppEvent,
    Connection,
    Deal,
    DiaryEntry,
    EquipmentEnquiry,
    EquipmentListing,
    EquipmentPartnership,
    FarmUpdate,
    Farmer,
    FarmerGroup,
    InsurancePolicy,
    InvestmentInterest,
    InvestmentRequest,
    LandParcel,
    LandShare,
    Message,
    Milestone,
    Notification,
    Profile,
    ProjectInvite,
    ProjectReport,
    Rating,
    SchemeApplication,
    SubscriptionPayment,
    VideoUpload,
    LoanApplication,
    LoanProduct,
)
from ..schemas import BackupOut
from . import media
from .events import EventType, enqueue_sync, record_event

BACKUP_NAME = re.compile(r"^viksitgaanw-backup-\d{8}-\d{6}\.zip$")
ERASE_PHRASE = "DELETE MY DATA"
PENDING_DIR = "restore-pending"


class DataError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def backups_dir() -> Path:
    directory = get_settings().backups_dir
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _out(path: Path) -> BackupOut:
    includes: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
        includes = sorted({name.split("/")[0] for name in names})
    except zipfile.BadZipFile:
        pass
    return BackupOut(
        name=path.name,
        size_bytes=path.stat().st_size,
        created_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
        includes=includes,
        download_path=f"/backups/{path.name}",
    )


def create_backup(session: Session, engine: Engine) -> BackupOut:
    settings = get_settings()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups_dir() / f"viksitgaanw-backup-{stamp}.zip"

    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "database.sqlite"
        # The SQLite backup API copies a consistent snapshot even mid-write,
        # which a plain file copy of a WAL database does not.
        raw = engine.raw_connection()
        try:
            destination = sqlite3.connect(copy)
            raw.driver_connection.backup(destination)
            destination.close()
        finally:
            raw.close()

        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(copy, "database.sqlite")
            for folder, prefix in ((settings.media_dir, "media"), (settings.reports_dir, "reports")):
                if folder.is_dir():
                    for path in folder.rglob("*"):
                        if path.is_file():
                            archive.write(path, f"{prefix}/{path.relative_to(folder).as_posix()}")
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "app": "ViksitGaanw",
                        "version": settings.version,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                    indent=2,
                ),
            )

    record_event(session, EventType.BACKUP_CREATED, entity_type="backup", entity_id=target.name,
                 payload={"bytes": target.stat().st_size})
    return _out(target)


def list_backups() -> list[BackupOut]:
    return [_out(path) for path in sorted(backups_dir().glob("viksitgaanw-backup-*.zip"), reverse=True)]


def backup_path(name: str) -> Path:
    if not BACKUP_NAME.match(name):
        raise DataError("Backup not found.", 404)
    path = backups_dir() / name
    if not path.is_file():
        raise DataError("Backup not found.", 404)
    return path


def stage_restore(data: bytes) -> str:
    """Check an uploaded backup and put it where the next start-up will apply it."""
    settings = get_settings()
    pending = settings.db_path.parent / PENDING_DIR
    with tempfile.TemporaryDirectory() as scratch:
        archive_path = Path(scratch) / "upload.zip"
        archive_path.write_bytes(data)
        try:
            archive = zipfile.ZipFile(archive_path)
        except zipfile.BadZipFile as exc:
            raise DataError("That file is not a ViksitGaanw backup.") from exc
        with archive:
            names = archive.namelist()
            if "database.sqlite" not in names or "manifest.json" not in names:
                raise DataError("That file is not a ViksitGaanw backup.")
            for name in names:
                if name.startswith("/") or ".." in Path(name).parts:
                    raise DataError("That backup contains unsafe paths.")
            extracted = Path(scratch) / "extracted"
            archive.extractall(extracted)

        check = sqlite3.connect(extracted / "database.sqlite")
        try:
            ok = check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            has_profiles = check.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='land_parcels'"
            ).fetchone()
        finally:
            check.close()
        if not ok or not has_profiles:
            raise DataError("That backup's database is damaged and cannot be restored.")

        if pending.exists():
            shutil.rmtree(pending)
        shutil.copytree(extracted, pending)
    return "The backup will be restored the next time the app starts. Close and reopen it now."


def apply_pending_restore(engine: Engine) -> bool:
    """Called at start-up, before anything opens the database."""
    settings = get_settings()
    pending = settings.db_path.parent / PENDING_DIR
    if not (pending / "database.sqlite").is_file():
        return False
    engine.dispose()
    for suffix in ("", "-wal", "-shm"):
        Path(f"{settings.db_path}{suffix}").unlink(missing_ok=True)
    shutil.copyfile(pending / "database.sqlite", settings.db_path)
    for folder, name in ((settings.media_dir, "media"), (settings.reports_dir, "reports")):
        source = pending / name
        if source.is_dir():
            if folder.exists():
                shutil.rmtree(folder)
            shutil.copytree(source, folder)
    shutil.rmtree(pending)
    return True


# --------------------------------------------------------------------------- #
# Export and erasure
# --------------------------------------------------------------------------- #


def _row(obj: Any) -> dict[str, Any]:
    out = {}
    for column in inspect(obj).mapper.column_attrs:
        value = getattr(obj, column.key)
        out[column.key] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


def export(session: Session, owner: Profile) -> dict[str, Any]:
    """Everything this device holds about its owner, readable by a person."""
    parcels = (
        list(session.scalars(select(LandParcel).where(LandParcel.farmer_id == owner.farmer_id)))
        if owner.farmer_id
        else []
    )
    parcel_ids = [p.id for p in parcels]
    request_ids = list(session.scalars(select(InvestmentRequest.id).where(InvestmentRequest.profile_id == owner.id)))
    listing_ids = list(session.scalars(select(EquipmentListing.id).where(EquipmentListing.profile_id == owner.id)))

    def rows(model, *conditions) -> list[dict[str, Any]]:
        return [_row(obj) for obj in session.scalars(select(model).where(or_(*conditions)))] if conditions else []

    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "about": "Everything ViksitGaanw holds about you on this device.",
        "profile": _row(owner),
        "land_parcels": [_row(p) for p in parcels],
        "project_reports": rows(ProjectReport, ProjectReport.parcel_id.in_(parcel_ids)) if parcel_ids else [],
        "diary": rows(DiaryEntry, DiaryEntry.parcel_id.in_(parcel_ids)) if parcel_ids else [],
        "insurance": rows(
            InsurancePolicy,
            InsurancePolicy.profile_id == owner.id,
            InsurancePolicy.parcel_id.in_(parcel_ids),
            InsurancePolicy.request_id.in_(request_ids),
        ),
        "investment_requests": rows(InvestmentRequest, InvestmentRequest.profile_id == owner.id),
        "interests_sent": rows(InvestmentInterest, InvestmentInterest.profile_id == owner.id),
        "interests_received": rows(InvestmentInterest, InvestmentInterest.request_id.in_(request_ids)),
        "deals": rows(Deal, Deal.farmer_profile_id == owner.id, Deal.investor_profile_id == owner.id),
        "equipment": rows(EquipmentListing, EquipmentListing.profile_id == owner.id),
        "enquiries": rows(
            EquipmentEnquiry, EquipmentEnquiry.profile_id == owner.id, EquipmentEnquiry.listing_id.in_(listing_ids)
        ),
        "partnerships": rows(
            EquipmentPartnership,
            EquipmentPartnership.seller_profile_id == owner.id,
            EquipmentPartnership.partner_profile_id == owner.id,
        ),
        "groups": rows(FarmerGroup, FarmerGroup.owner_profile_id == owner.id),
        "messages": rows(Message, Message.sender_profile_id == owner.id, Message.recipient_profile_id == owner.id),
        "ratings_given": rows(Rating, Rating.rater_profile_id == owner.id),
        "ratings_received": rows(Rating, Rating.rated_profile_id == owner.id),
        "scheme_applications": rows(SchemeApplication, SchemeApplication.profile_id == owner.id),
        "notifications": rows(Notification, Notification.profile_id == owner.id),
        "connections": rows(
            Connection, Connection.requester_profile_id == owner.id, Connection.addressee_profile_id == owner.id
        ),
        "shared_land": rows(LandShare, LandShare.profile_id == owner.id),
        "farm_updates": rows(FarmUpdate, FarmUpdate.profile_id == owner.id),
        "project_invites": rows(
            ProjectInvite, ProjectInvite.farmer_profile_id == owner.id, ProjectInvite.investor_profile_id == owner.id
        ),
        "video_uploads": rows(VideoUpload, VideoUpload.id.isnot(None)),
        "subscription_payments": rows(SubscriptionPayment, SubscriptionPayment.id.isnot(None)),
        "loan_products": rows(LoanProduct, LoanProduct.profile_id == owner.id),
        "loan_applications": rows(
            LoanApplication, LoanApplication.profile_id == owner.id, LoanApplication.lender_profile_id == owner.id
        ),
    }
    record_event(session, EventType.DATA_EXPORTED, entity_type="profile", entity_id=owner.id)
    return data


def erase(session: Session, owner: Profile, confirm: str) -> dict[str, int]:
    """Remove the owner and everything that is theirs. Irreversible by design."""
    if confirm.strip() != ERASE_PHRASE:
        raise DataError(f'Type "{ERASE_PHRASE}" exactly to confirm.')
    settings = get_settings()
    counts: dict[str, int] = {}

    farmer = session.get(Farmer, owner.farmer_id) if owner.farmer_id else None
    parcel_ids = [p.id for p in farmer.parcels] if farmer else []
    listing_ids = list(session.scalars(select(EquipmentListing.id).where(EquipmentListing.profile_id == owner.id)))
    diary_ids = list(session.scalars(select(DiaryEntry.id).where(DiaryEntry.parcel_id.in_(parcel_ids)))) if parcel_ids else []
    deal_ids = list(session.scalars(select(Deal.id).where(or_(Deal.farmer_profile_id == owner.id, Deal.investor_profile_id == owner.id))))

    update_ids = list(session.scalars(select(FarmUpdate.id).where(FarmUpdate.profile_id == owner.id)))
    # The cards of shared plots, and updates, are taken down everywhere.
    for share_id in session.scalars(select(LandShare.id).where(LandShare.profile_id == owner.id)):
        enqueue_sync(session, entity_type="land_share", entity_id=share_id, operation="delete")
    for update_id in update_ids:
        enqueue_sync(session, entity_type="farm_update", entity_id=update_id, operation="delete")
    # A lender's loans and an applicant's applications go from the cloud too.
    for product_id in session.scalars(select(LoanProduct.id).where(LoanProduct.profile_id == owner.id)):
        enqueue_sync(session, entity_type="loan_product", entity_id=product_id, operation="delete")
    for application_id in session.scalars(select(LoanApplication.id).where(LoanApplication.profile_id == owner.id)):
        enqueue_sync(session, entity_type="loan_application", entity_id=application_id, operation="delete")

    # Pictures and PDFs live on disk, not in the rows the cascade removes.
    for entity_type, ids in (
        ("profile", [owner.id]),
        ("equipment", listing_ids),
        ("diary", diary_ids),
        ("land", parcel_ids),
        ("update", update_ids),
    ):
        for entity_id in ids:
            media.remove_all(session, entity_type, entity_id)
    milestone_ids = (
        list(session.scalars(select(Milestone.id).where(Milestone.deal_id.in_(deal_ids)))) if deal_ids else []
    )
    for milestone_id in milestone_ids:
        media.remove_all(session, "milestone", milestone_id)
    # Videos still waiting to upload are files in the media folder.
    from . import videos  # noqa: PLC0415

    for upload in session.scalars(select(VideoUpload)):
        videos.upload_path(upload).unlink(missing_ok=True)
        session.delete(upload)
    # The receipts go; the sync server keeps its own record of what was paid.
    for receipt in session.scalars(select(SubscriptionPayment)):
        session.delete(receipt)
    if parcel_ids:
        for report in session.scalars(select(ProjectReport).where(ProjectReport.parcel_id.in_(parcel_ids))):
            try:
                (settings.reports_dir / Path(report.file_path).name).unlink(missing_ok=True)
                Path(report.file_path).unlink(missing_ok=True)
            except OSError:
                pass
    counts["deals"] = len(deal_ids)
    counts["parcels"] = len(parcel_ids)

    for message in session.scalars(
        select(Message).where(or_(Message.sender_profile_id == owner.id, Message.recipient_profile_id == owner.id))
    ):
        session.delete(message)
    for deal_id in deal_ids:
        deal = session.get(Deal, deal_id)
        if deal:
            session.delete(deal)

    # The cloud copy of anything shared has to go too.
    enqueue_sync(session, entity_type="profile", entity_id=owner.id, operation="delete")
    session.delete(owner)
    if farmer:
        session.delete(farmer)
    # Events are kept for metering, but stripped of anything about the person.
    for event in session.scalars(select(AppEvent).where(AppEvent.entity_id == owner.id)):
        event.payload = {}
    session.flush()
    return counts
