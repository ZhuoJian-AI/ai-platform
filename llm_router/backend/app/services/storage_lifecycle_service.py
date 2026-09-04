"""Unified retention, physical purge and storage migration lifecycle.

Business services must call :func:`mark_deleted` instead of assigning
``deleted_at`` directly for governed content.  Physical removal is deliberately
separate and idempotent: an OSS failure keeps the database tombstone so the
hourly worker can retry safely.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.ontology import Ontology, OntologyFile, OntologyFolder
from app.models.platform_extension import PlatformExtensionSource
from app.models.rag import RagChunk, RagCollection, RagDocument, RagFolder
from app.models.skill import SkillFile, SkillFolder, SkillVersion
from app.models.workspace import (
    OfficeEditRoom,
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
    """Apply the common 30-day tombstone to one or more ORM rows."""
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
    """Trash a workspace and explicitly invalidate every active edit room."""
    now = datetime.now(UTC)
    deadline = retention_deadline(now)
    files = list((await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.workspace_id == workspace.id,
        WorkspaceFile.deleted_at.is_(None),
    ).order_by(WorkspaceFile.id).with_for_update())).scalars().all())
    if files:
        rooms = list((await db.execute(select(OfficeEditRoom).where(
            OfficeEditRoom.workspace_file_id.in_([file.id for file in files]),
            OfficeEditRoom.status.in_(("open", "closing")),
        ).with_for_update())).scalars().all())
        for room in rooms:
            room.status = "expired"
            room.expires_at = now
            room.closed_at = room.closed_at or now
            room.last_error = "工作空间已删除，编辑会话已失效"
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


async def mark_skill_deleted(db: AsyncSession, folder: SkillFolder) -> datetime:
    now = datetime.now(UTC)
    deadline = retention_deadline(now)
    mark_deleted(folder, now=now)
    files = list((await db.execute(select(SkillFile).where(
        SkillFile.skill_folder_id == folder.id,
        SkillFile.deleted_at.is_(None),
    ))).scalars().all())
    versions = list((await db.execute(select(SkillVersion).where(
        SkillVersion.skill_folder_id == folder.id,
        SkillVersion.archive_purged_at.is_(None),
    ))).scalars().all())
    mark_deleted(*files, now=now)
    for version in versions:
        version.purge_after = deadline
        if version.archive_ref or version.archive:
            version.storage_status = "purge_pending"
    folder.active_version_id = None
    folder.is_active = False
    await db.flush()
    return deadline


async def mark_rag_collection_deleted(db: AsyncSession, collection: RagCollection) -> datetime:
    now = datetime.now(UTC)
    deadline = retention_deadline(now)
    mark_deleted(collection, now=now)
    documents = list((await db.execute(select(RagDocument).where(
        RagDocument.collection_id == collection.id,
        RagDocument.deleted_at.is_(None),
    ))).scalars().all())
    folders = list((await db.execute(select(RagFolder).where(
        RagFolder.collection_id == collection.id,
        RagFolder.deleted_at.is_(None),
    ))).scalars().all())
    mark_deleted(*documents, *folders, now=now)
    await db.flush()
    return deadline


async def mark_ontology_deleted(db: AsyncSession, ontology: Ontology) -> datetime:
    mark_deleted(ontology)
    await db.flush()
    return ontology.purge_after


async def backfill_missing_deadlines(db: AsyncSession) -> int:
    models = (
        Workspace, WorkspaceFile, WorkspaceFolder,
        SkillFolder, SkillFile,
        RagCollection, RagDocument, RagFolder,
        Ontology, OntologyFolder, OntologyFile,
    )
    updated = 0
    for model in models:
        rows = list((await db.execute(select(model).where(
            model.deleted_at.is_not(None), model.purge_after.is_(None),
        ).limit(500))).scalars().all())
        for row in rows:
            row.purge_after = row.deleted_at + timedelta(days=RETENTION_DAYS)
        updated += len(rows)
    deleted_skills = list((await db.execute(select(SkillFolder).where(
        SkillFolder.deleted_at.is_not(None),
    ).limit(500))).scalars().all())
    for folder in deleted_skills:
        deadline = folder.purge_after or retention_deadline(folder.deleted_at)
        versions = list((await db.execute(select(SkillVersion).where(
            SkillVersion.skill_folder_id == folder.id,
            SkillVersion.purge_after.is_(None),
            SkillVersion.archive_purged_at.is_(None),
        ))).scalars().all())
        for version in versions:
            version.purge_after = deadline
            version.storage_status = "purge_pending"
        updated += len(versions)
    await db.flush()
    return updated


async def migrate_inline_skill_packages(db: AsyncSession, *, limit: int = 10) -> dict[str, int]:
    """Move legacy package blobs to OSS; clear the blob only after verification."""
    if not settings.workspace_object_storage_configured:
        return {"migrated": 0, "failed": 0}
    versions = list((await db.execute(select(SkillVersion, SkillFolder.organization_id).join(
        SkillFolder, SkillFolder.id == SkillVersion.skill_folder_id,
    ).where(
        SkillVersion.archive.is_not(None),
        SkillVersion.archive_ref.is_(None),
        SkillVersion.archive_purged_at.is_(None),
    ).limit(limit))).all())
    migrated = failed = 0
    for version, organization_id in versions:
        raw = bytes(version.archive or b"")
        try:
            ref = await storage_gateway_service.upload_skill_archive(
                raw, organization_id=str(organization_id), package_hash=version.package_hash,
            )
            actual = await storage_gateway_service.download_bytes(ref)
            if actual != raw:
                raise storage_gateway_service.StorageGatewayError("Skill package verification failed")
            version.archive_ref = ref
            version.archive_size = len(raw)
            version.archive = None
            version.storage_status = "stored"
            migrated += 1
        except storage_gateway_service.StorageGatewayError:
            version.storage_status = "failed"
            failed += 1
    await db.flush()
    return {"migrated": migrated, "failed": failed}


async def _purge_skill_versions(db: AsyncSession, now: datetime) -> tuple[int, int]:
    versions = list((await db.execute(select(SkillVersion).where(
        SkillVersion.purge_after <= now,
        SkillVersion.archive_purged_at.is_(None),
    ).limit(50))).scalars().all())
    purged = failed = 0
    for version in versions:
        try:
            if version.archive_ref:
                await storage_gateway_service.delete_object(version.archive_ref)
        except storage_gateway_service.StorageGatewayError:
            version.storage_status = "failed"
            failed += 1
            continue
        version.archive = None
        version.archive_ref = None
        version.archive_size = 0
        version.archive_purged_at = now
        version.storage_status = "purged"
        # Cache cleanup is best-effort. The Runner also enforces 7-day/LRU GC.
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.delete(
                    f"{settings.skill_runner_url.rstrip('/')}/cache/{version.package_hash}",
                    headers={"X-Skill-Runner-Token": settings.skill_runner_token},
                )
        except httpx.HTTPError:
            pass
        purged += 1
    return purged, failed


async def _finalize_skill_folders(db: AsyncSession, now: datetime) -> int:
    """Remove expanded package content only after every immutable package is gone."""
    folders = list((await db.execute(select(SkillFolder).where(
        SkillFolder.deleted_at.is_not(None), SkillFolder.purge_after <= now,
    ).limit(50))).scalars().all())
    finalized = 0
    for folder in folders:
        remaining = int((await db.scalar(select(func.count()).select_from(SkillVersion).where(
            SkillVersion.skill_folder_id == folder.id,
            SkillVersion.archive_purged_at.is_(None),
        ))) or 0)
        if remaining:
            continue
        await db.execute(delete(SkillFile).where(SkillFile.skill_folder_id == folder.id))
        folder.purge_after = None
        folder.is_active = False
        folder.active_version_id = None
        finalized += 1
    return finalized


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


async def _purge_rag(db: AsyncSession, now: datetime) -> int:
    documents = list((await db.execute(select(RagDocument).where(
        RagDocument.purge_after <= now,
        RagDocument.deleted_at.is_not(None),
    ).limit(100))).scalars().all())
    purged = 0
    for document in documents:
        await db.execute(delete(RagChunk).where(RagChunk.document_id == document.id))
        document.content = ""
        document.metadata_ = {"physically_purged_at": now.isoformat()}
        document.parse_error = None
        document.status = "purged"
        document.progress = 100
        document.purge_after = None
        purged += 1
    collections = list((await db.execute(select(RagCollection).where(
        RagCollection.purge_after <= now,
        RagCollection.deleted_at.is_not(None),
    ).limit(50))).scalars().all())
    for collection in collections:
        await db.execute(delete(RagChunk).where(RagChunk.collection_id == collection.id))
        collection.description = None
        collection.metadata_ = {"physically_purged_at": now.isoformat()}
        collection.purge_after = None
    await db.execute(delete(RagFolder).where(
        RagFolder.purge_after <= now, RagFolder.deleted_at.is_not(None),
    ))
    return purged


async def _purge_ontology(db: AsyncSession, now: datetime) -> int:
    ontologies = list((await db.execute(select(Ontology).where(
        Ontology.purge_after <= now, Ontology.deleted_at.is_not(None),
    ).limit(50))).scalars().all())
    files = list((await db.execute(select(OntologyFile).where(
        OntologyFile.purge_after <= now, OntologyFile.deleted_at.is_not(None),
    ).limit(100))).scalars().all())
    for ontology in ontologies:
        ontology.entities = []
        ontology.relations = []
        ontology.description = None
        ontology.purge_after = None
    for file in files:
        file.content = None
        file.size = 0
        file.metadata_ = {"physically_purged_at": now.isoformat()}
        file.purge_after = None
    await db.execute(delete(OntologyFolder).where(
        OntologyFolder.purge_after <= now, OntologyFolder.deleted_at.is_not(None),
    ))
    return len(ontologies) + len(files)


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
    """Collect every OSS key that still has a durable database owner."""
    columns = (
        WorkspaceFile.content_ref,
        WorkspaceFileVersion.content_ref,
        WorkspaceUploadSession.content_ref,
        WorkspacePreviewJob.output_ref,
        SkillVersion.archive_ref,
        PlatformExtensionSource.artifact_ref,
    )
    refs: set[str] = set()
    for column in columns:
        values = (await db.execute(select(column).where(column.is_not(None)))).scalars().all()
        for value in values:
            if storage_gateway_service.is_object_ref(value):
                refs.add(storage_gateway_service.object_key_from_ref(str(value)))
    return refs


async def reconcile_orphan_objects(
    db: AsyncSession, *, now: datetime | None = None, max_objects: int = 10_000,
) -> dict[str, int]:
    """Delete unreferenced objects older than seven days, if Gateway supports listing."""
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
            return {"orphan_scan_supported": 0, "orphans_scanned": 0, "orphans_deleted": 0, "orphan_failures": 0}
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
    skill_versions, skill_failures = await _purge_skill_versions(db, now)
    skill_folders = await _finalize_skill_folders(db, now)
    rag_items = await _purge_rag(db, now)
    ontology_items = await _purge_ontology(db, now)
    migrated = await migrate_inline_skill_packages(db)
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
        "skill_versions": skill_versions,
        "skill_failures": skill_failures,
        "skill_folders": skill_folders,
        "rag_items": rag_items,
        "ontology_items": ontology_items,
        "migrated_skill_versions": migrated["migrated"],
        "migration_failures": migrated["failed"],
        "expired_file_events": int(outbox_result.rowcount or 0),
    }


async def overview(db: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    governed: Iterable[type[Any]] = (
        Workspace, WorkspaceFile, WorkspaceFolder, SkillFolder, SkillFile,
        RagCollection, RagDocument, RagFolder, Ontology, OntologyFolder, OntologyFile,
    )
    pending = 0
    for model in governed:
        pending += int((await db.scalar(select(func.count()).select_from(model).where(
            model.deleted_at.is_not(None), model.purge_after.is_not(None),
        ))) or 0)
    overdue = 0
    for model in governed:
        overdue += int((await db.scalar(select(func.count()).select_from(model).where(
            model.deleted_at.is_not(None), model.purge_after <= now,
        ))) or 0)
    pending_versions = int((await db.scalar(select(func.count()).select_from(SkillVersion).where(
        SkillVersion.purge_after.is_not(None), SkillVersion.archive_purged_at.is_(None),
    ))) or 0)
    pending += pending_versions
    overdue += int((await db.scalar(select(func.count()).select_from(SkillVersion).where(
        SkillVersion.purge_after <= now, SkillVersion.archive_purged_at.is_(None),
    ))) or 0)
    failed = int((await db.scalar(select(func.count()).select_from(SkillVersion).where(
        SkillVersion.storage_status == "failed",
    ))) or 0)
    reclaimable = int((await db.scalar(select(func.coalesce(func.sum(WorkspaceFile.size), 0)).where(
        WorkspaceFile.deleted_at.is_not(None), WorkspaceFile.purge_after.is_not(None),
    ))) or 0)
    reclaimable += int((await db.scalar(select(func.coalesce(func.sum(SkillVersion.archive_size), 0)).where(
        SkillVersion.purge_after.is_not(None), SkillVersion.archive_purged_at.is_(None),
    ))) or 0)
    runner_cache_bytes = runner_cache_limit_bytes = -1
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{settings.skill_runner_url.rstrip('/')}/health")
            response.raise_for_status()
            cache = response.json().get("cache") or {}
            runner_cache_bytes = int(cache.get("cache_bytes", -1))
            runner_cache_limit_bytes = int(cache.get("max_bytes", -1))
    except (httpx.HTTPError, TypeError, ValueError):
        pass
    return {
        "pending_items": pending,
        "overdue_items": overdue,
        "failed_items": failed,
        "reclaimable_bytes": reclaimable,
        "runner_cache_bytes": runner_cache_bytes,
        "runner_cache_limit_bytes": runner_cache_limit_bytes,
    }
