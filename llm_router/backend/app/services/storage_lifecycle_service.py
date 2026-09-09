"""Retention and physical purge lifecycle for workspace storage.

Workspace data and generated artifacts keep the existing 30-day tombstone model.
The retired RAG and user-Skill products are intentionally absent from this service.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.workspace import (
    Workspace,
    WorkspaceFile,
    WorkspaceFileEventOutbox,
    WorkspaceFileVersion,
    WorkspaceFolder,
    WorkspacePreviewJob,
    WorkspaceUploadSession,
)
from app.services import storage_gateway_service

RETENTION_DAYS = 30


def retention_deadline(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + timedelta(days=RETENTION_DAYS)


def mark_deleted(*rows: Any, now: datetime | None = None) -> datetime:
    """Apply the common tombstone to one or more governed workspace rows."""
    deleted_at = now or datetime.now(UTC)
    purge_after = retention_deadline(deleted_at)
    for row in rows:
        row.deleted_at = deleted_at
        if hasattr(row, "purge_after"):
            row.purge_after = purge_after
    return purge_after


def restore(*rows: Any) -> None:
    for row in rows:
        row.deleted_at = None
        if hasattr(row, "purge_after"):
            row.purge_after = None


async def mark_workspace_deleted(db: AsyncSession, workspace: Workspace) -> datetime:
    """Trash a workspace and its live folders/files in one transaction."""
    now = datetime.now(UTC)
    deadline = retention_deadline(now)
    files = list((await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.workspace_id == workspace.id,
        WorkspaceFile.deleted_at.is_(None),
    ).order_by(WorkspaceFile.id).with_for_update())).scalars().all())
    folders = list((await db.execute(select(WorkspaceFolder).where(
        WorkspaceFolder.workspace_id == workspace.id,
        WorkspaceFolder.deleted_at.is_(None),
    ).order_by(WorkspaceFolder.id).with_for_update())).scalars().all())
    mark_deleted(workspace, now=now)
    mark_deleted(*files, *folders, now=now)
    for file in files:
        db.add(WorkspaceFileEventOutbox(
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            workspace_file_id=file.id,
            version_id=file.current_version_id,
            event_type="file_deleted",
        ))
    await db.flush()
    return deadline


async def backfill_missing_deadlines(db: AsyncSession) -> int:
    updated = 0
    for model in (Workspace, WorkspaceFile, WorkspaceFolder):
        rows = list((await db.execute(select(model).where(
            model.deleted_at.is_not(None), model.purge_after.is_(None),
        ).limit(500))).scalars().all())
        for row in rows:
            row.purge_after = row.deleted_at + timedelta(days=RETENTION_DAYS)
        updated += len(rows)
    await db.flush()
    return updated


async def _purge_workspace_containers(db: AsyncSession, now: datetime) -> dict[str, int]:
    """Delete empty folder/workspace tombstones after their files were safely purged."""
    folders = list((await db.execute(select(WorkspaceFolder).where(
        WorkspaceFolder.deleted_at.is_not(None), WorkspaceFolder.purge_after <= now,
    ).limit(200))).scalars().all())
    deleted_folders = 0
    for folder in sorted(folders, key=lambda item: len(item.path), reverse=True):
        remaining = int((await db.scalar(select(func.count()).select_from(WorkspaceFile).where(
            WorkspaceFile.workspace_id == folder.workspace_id,
            WorkspaceFile.path.startswith(f"{folder.path}/"),
        ))) or 0)
        if remaining:
            continue
        await db.delete(folder)
        deleted_folders += 1
    await db.flush()

    workspaces = list((await db.execute(select(Workspace).where(
        Workspace.deleted_at.is_not(None), Workspace.purge_after <= now,
    ).limit(50))).scalars().all())
    deleted_workspaces = 0
    for workspace in workspaces:
        remaining_files = int((await db.scalar(select(func.count()).select_from(WorkspaceFile).where(
            WorkspaceFile.workspace_id == workspace.id,
        ))) or 0)
        remaining_folders = int((await db.scalar(select(func.count()).select_from(WorkspaceFolder).where(
            WorkspaceFolder.workspace_id == workspace.id,
        ))) or 0)
        if remaining_files or remaining_folders:
            continue
        await db.delete(workspace)
        deleted_workspaces += 1
    return {"workspace_folders": deleted_folders, "workspaces": deleted_workspaces}


async def expire_upload_sessions(db: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    sessions = list((await db.execute(select(WorkspaceUploadSession).where(
        WorkspaceUploadSession.status == "pending",
        WorkspaceUploadSession.expires_at <= now,
    ).limit(100))).scalars().all())
    expired = failed = 0
    for session in sessions:
        try:
            if session.content_ref:
                await storage_gateway_service.delete_object(session.content_ref)
        except storage_gateway_service.StorageGatewayError:
            failed += 1
            continue
        session.status = "expired"
        session.content_ref = None
        session.upload_url = None
        session.upload_headers = {}
        expired += 1
    return {"expired": expired, "failed": failed}


async def _referenced_object_keys(db: AsyncSession) -> set[str]:
    """Collect every OSS key that still has a durable workspace owner."""
    columns = (
        WorkspaceFile.content_ref,
        WorkspaceFileVersion.content_ref,
        WorkspaceUploadSession.content_ref,
        WorkspacePreviewJob.output_ref,
    )
    refs: set[str] = set()
    for column in columns:
        values = (await db.execute(select(column).where(column.is_not(None)))).scalars().all()
        for value in values:
            if storage_gateway_service.is_object_ref(value):
                refs.add(storage_gateway_service.object_key_from_ref(str(value)))
    return refs


async def reconcile_orphan_objects(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    max_objects: int = 10_000,
) -> dict[str, int]:
    """Delete unreferenced objects older than the configured grace period."""
    now = now or datetime.now(UTC)
    referenced = await _referenced_object_keys(db)
    cursor: str | None = None
    scanned = deleted = failed = 0
    while scanned < max_objects:
        page = await storage_gateway_service.list_project_objects(
            older_than=now - timedelta(days=settings.storage_orphan_grace_days),
            cursor=cursor,
            limit=min(500, max_objects - scanned),
        )
        if page is None:
            return {
                "orphan_scan_supported": 0,
                "orphans_scanned": 0,
                "orphans_deleted": 0,
                "orphan_failures": 0,
            }
        items = page["items"]
        if not items:
            break
        scanned += len(items)
        for item in items:
            key = str(item["object_key"])
            if key in referenced:
                continue
            try:
                await storage_gateway_service.delete_object(f"oss://{key}")
            except storage_gateway_service.StorageGatewayError:
                failed += 1
            else:
                deleted += 1
        cursor = str(page.get("next_cursor") or "") or None
        if not cursor:
            break
    return {
        "orphan_scan_supported": 1,
        "orphans_scanned": scanned,
        "orphans_deleted": deleted,
        "orphan_failures": failed,
    }


async def run_cleanup(db: AsyncSession) -> dict[str, int]:
    from app.services import workspace_governance_service

    now = datetime.now(UTC)
    backfilled = await backfill_missing_deadlines(db)
    uploads = await expire_upload_sessions(db, now)
    workspace_files = await workspace_governance_service.purge_expired(db)
    workspace_containers = await _purge_workspace_containers(db, now)
    outbox_result = await db.execute(delete(WorkspaceFileEventOutbox).where(
        WorkspaceFileEventOutbox.created_at < now - timedelta(days=7),
    ))
    await db.flush()
    return {
        "backfilled": backfilled,
        "expired_uploads": uploads["expired"],
        "upload_failures": uploads["failed"],
        "workspace_files": workspace_files,
        **workspace_containers,
        "expired_file_events": int(outbox_result.rowcount or 0),
    }


async def overview(db: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    governed: Iterable[type[Any]] = (Workspace, WorkspaceFile, WorkspaceFolder)
    pending = overdue = 0
    for model in governed:
        pending += int((await db.scalar(select(func.count()).select_from(model).where(
            model.deleted_at.is_not(None), model.purge_after.is_not(None),
        ))) or 0)
        overdue += int((await db.scalar(select(func.count()).select_from(model).where(
            model.deleted_at.is_not(None), model.purge_after <= now,
        ))) or 0)
    reclaimable = int((await db.scalar(select(func.coalesce(func.sum(WorkspaceFile.size), 0)).where(
        WorkspaceFile.deleted_at.is_not(None), WorkspaceFile.purge_after.is_not(None),
    ))) or 0)
    executor_active = executor_waiting = -1
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{settings.tool_executor_url.rstrip('/')}/health")
            response.raise_for_status()
            capacity = response.json().get("capacity") or {}
            executor_active = int(capacity.get("active", -1))
            executor_waiting = int(capacity.get("waiting", -1))
    except (httpx.HTTPError, TypeError, ValueError):
        pass
    return {
        "pending_items": pending,
        "overdue_items": overdue,
        "failed_items": 0,
        "reclaimable_bytes": reclaimable,
        "tool_executor_active": executor_active,
        "tool_executor_waiting": executor_waiting,
    }
