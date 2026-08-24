"""Super-admin APIs for reviewed platform extensions and immutable releases."""

from __future__ import annotations

import hmac
from collections import Counter
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dsh.client import runtime_health
from app.auth.admin_auth import CurrentAdmin, require_super_admin
from app.config import settings
from app.database import get_db
from app.models.platform_extension import (
    PlatformExtensionRelease,
    PlatformExtensionReleaseEvent,
    PlatformExtensionSource,
)
from app.schemas.platform_extension import (
    ExtensionApproveRequest,
    ExtensionArtifactSign,
    ExtensionCatalogItem,
    ExtensionImportGithub,
    ExtensionImportNpm,
    ExtensionOverview,
    ExtensionReleaseCreate,
    ExtensionReleaseEventRead,
    ExtensionReleaseRead,
    ExtensionSourceRead,
)
from app.services import platform_extension_service, storage_gateway_service

router = APIRouter(prefix="/platform/extensions")


@router.post("/internal/artifacts/sign", include_in_schema=False)
async def sign_builder_artifact(
    data: ExtensionArtifactSign,
    authorization: str = Header(default=""),
):
    expected = f"Bearer {settings.extension_builder_token}"
    if not settings.extension_builder_token or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Invalid extension builder token")
    signed = await storage_gateway_service.sign_service_upload(
        filename=data.filename,
        content_type="application/gzip",
        size_bytes=data.size_bytes,
        max_bytes=settings.extension_artifact_max_bytes,
    )
    return {**signed, "sha256": data.sha256}


async def _source(db: AsyncSession, source_id: UUID) -> PlatformExtensionSource:
    row = await db.get(PlatformExtensionSource, source_id)
    if not row:
        raise HTTPException(status_code=404, detail="Extension source not found")
    return row


async def _release(db: AsyncSession, release_id: UUID) -> PlatformExtensionRelease:
    row = await db.get(PlatformExtensionRelease, release_id)
    if not row:
        raise HTTPException(status_code=404, detail="Extension release not found")
    return row


@router.get("/overview", response_model=ExtensionOverview)
async def overview(
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    active = await platform_extension_service.ensure_baseline(db, auth.id)
    sources = list((await db.execute(select(PlatformExtensionSource))).scalars().all())
    releases = list((await db.execute(select(PlatformExtensionRelease))).scalars().all())
    catalog = await platform_extension_service.list_catalog(db, auth.id)
    return ExtensionOverview(
        active_release=active,
        runtime_health=await runtime_health(),
        source_counts=dict(Counter(row.status for row in sources)),
        release_counts=dict(Counter(row.status for row in releases)),
        core_plugins=[row for row in catalog if row["source"] == "core" and row["kind"] != "system_tool"],
        system_tools=[row for row in catalog if row["kind"] == "system_tool"],
    )


@router.get("/catalog", response_model=list[ExtensionCatalogItem])
async def catalog(
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await platform_extension_service.list_catalog(db, auth.id)


@router.get("/sources", response_model=list[ExtensionSourceRead])
async def sources(
    _: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return list(
        (await db.execute(select(PlatformExtensionSource).order_by(PlatformExtensionSource.created_at.desc())))
        .scalars()
        .all()
    )


@router.post("/import/npm", response_model=ExtensionSourceRead, status_code=202)
async def import_npm(
    data: ExtensionImportNpm,
    background: BackgroundTasks,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await platform_extension_service.create_source(
        db,
        source_type="npm",
        locator=data.package,
        requested_version=data.version,
        admin_id=auth.id,
    )
    await db.commit()
    background.add_task(platform_extension_service.process_source_build, row.id)
    return row


@router.post("/import/github", response_model=ExtensionSourceRead, status_code=202)
async def import_github(
    data: ExtensionImportGithub,
    background: BackgroundTasks,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    if (data.repository.host or "").lower() not in {"github.com", "www.github.com"}:
        raise HTTPException(status_code=422, detail="Only github.com repositories are accepted")
    row = await platform_extension_service.create_source(
        db,
        source_type="github",
        locator=str(data.repository),
        requested_version=data.ref,
        admin_id=auth.id,
    )
    await db.commit()
    background.add_task(platform_extension_service.process_source_build, row.id)
    return row


@router.post("/import/archive", response_model=ExtensionSourceRead, status_code=202)
async def import_archive(
    background: BackgroundTasks,
    archive: UploadFile = File(...),
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    filename = archive.filename or "extension.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="Only ZIP extension packages are accepted")
    raw = await archive.read(settings.extension_archive_max_bytes + 1)
    if not raw.startswith(b"PK\x03\x04") or len(raw) > settings.extension_archive_max_bytes:
        raise HTTPException(status_code=422, detail="Invalid or oversized ZIP extension package")
    if not settings.workspace_object_storage_configured:
        raise HTTPException(status_code=503, detail="OSS storage gateway is required for platform extensions")
    input_ref = await storage_gateway_service.upload_bytes(
        raw,
        filename=f"extension-source-{filename}",
        content_type="application/zip",
    )
    row = await platform_extension_service.create_source(
        db,
        source_type="archive",
        locator=filename,
        requested_version=None,
        admin_id=auth.id,
        input_ref=input_ref,
    )
    await db.commit()
    background.add_task(platform_extension_service.process_source_build, row.id)
    return row


@router.get("/sources/{source_id}", response_model=ExtensionSourceRead)
async def source_detail(
    source_id: UUID,
    _: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _source(db, source_id)


@router.post("/sources/{source_id}/retry", response_model=ExtensionSourceRead, status_code=202)
async def retry_source(
    source_id: UUID,
    background: BackgroundTasks,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _source(db, source_id)
    if row.status in {"importing", "building"}:
        raise HTTPException(status_code=409, detail="Build is already running")
    row.status = "importing"
    row.error = None
    row.review_status = "pending"
    await platform_extension_service.record_event(
        db,
        event_type="build_retry_requested",
        actor_admin_id=auth.id,
        source_id=row.id,
    )
    await db.commit()
    background.add_task(platform_extension_service.process_source_build, row.id)
    return row


@router.post("/sources/{source_id}/approve", response_model=ExtensionSourceRead)
async def approve_source(
    source_id: UUID,
    data: ExtensionApproveRequest,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await platform_extension_service.approve_source(
        db,
        await _source(db, source_id),
        admin_id=auth.id,
        approved=data.approved,
        note=data.note,
    )


@router.get("/releases", response_model=list[ExtensionReleaseRead])
async def releases(
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    await platform_extension_service.ensure_baseline(db, auth.id)
    return list(
        (await db.execute(select(PlatformExtensionRelease).order_by(PlatformExtensionRelease.version_no.desc())))
        .scalars()
        .all()
    )


@router.post("/releases", response_model=ExtensionReleaseRead, status_code=201)
async def create_release(
    data: ExtensionReleaseCreate,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await platform_extension_service.create_release(
        db,
        name=data.name,
        source_ids=data.source_ids,
        config=data.config,
        admin_id=auth.id,
    )


@router.post("/releases/{release_id}/validate", response_model=ExtensionReleaseRead)
async def validate_release(
    release_id: UUID,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _release(db, release_id)
    if row.is_active:
        raise HTTPException(status_code=409, detail="Active release does not need candidate validation")
    return await platform_extension_service.validate_release(db, row, auth.id)


@router.post("/releases/{release_id}/publish", response_model=ExtensionReleaseRead)
async def publish_release(
    release_id: UUID,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await platform_extension_service.publish_release(db, await _release(db, release_id), auth.id)
    if row.status != "active":
        raise HTTPException(status_code=502, detail=row.error or "Runtime activation failed")
    return row


@router.post("/releases/{release_id}/rollback", response_model=ExtensionReleaseRead, status_code=201)
async def rollback_release(
    release_id: UUID,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await platform_extension_service.rollback_release(db, await _release(db, release_id), admin_id=auth.id)


@router.get("/events", response_model=list[ExtensionReleaseEventRead])
async def events(
    limit: int = 200,
    _: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    safe_limit = max(1, min(limit, 1000))
    return list(
        (
            await db.execute(
                select(PlatformExtensionReleaseEvent)
                .order_by(PlatformExtensionReleaseEvent.id.desc())
                .limit(safe_limit)
            )
        )
        .scalars()
        .all()
    )
