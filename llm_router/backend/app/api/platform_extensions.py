"""Super-admin APIs for reviewed platform extensions and immutable releases."""

from __future__ import annotations

import hmac
import re
from collections import Counter
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dsh.client import runtime_health
from app.auth.admin_auth import CurrentAdmin, require_super_admin
from app.config import settings
from app.database import get_db
from app.models.platform_extension import (
    PlatformExtensionCatalogEntry,
    PlatformExtensionRelease,
    PlatformExtensionReleaseEvent,
    PlatformExtensionSource,
)
from app.schemas.platform_extension import (
    ExtensionApproveRequest,
    ExtensionArtifactSign,
    ExtensionCatalogImportRequest,
    ExtensionCatalogItem,
    ExtensionCatalogPage,
    ExtensionImportGithub,
    ExtensionImportNpm,
    ExtensionOverview,
    ExtensionReleaseCreate,
    ExtensionReleaseEventRead,
    ExtensionReleaseRead,
    ExtensionSourceRead,
)
from app.services import platform_extension_service, storage_gateway_service
from app.services.platform_extension_discovery import sync_discovery_catalog

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
        core_plugins=[row for row in catalog if row["source"] == "official" and row["kind"] != "system_tool"],
        system_tools=[row for row in catalog if row["source"] == "official" and row["kind"] == "system_tool"],
    )


@router.get("/catalog", response_model=list[ExtensionCatalogItem])
async def catalog(
    q: str | None = Query(None, max_length=200),
    source: str | None = Query(None, max_length=30),
    layer: str | None = Query(None, max_length=50),
    compatibility: str | None = Query(None, max_length=30),
    offset: int = Query(0, ge=0),
    limit: int = Query(3000, ge=1, le=3000),
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await platform_extension_service.list_catalog(
        db, auth.id, query=q, source_filter=source, layer=layer,
        compatibility=compatibility, offset=offset, limit=limit,
    )


@router.get("/catalog/page", response_model=ExtensionCatalogPage)
async def catalog_page(
    q: str | None = Query(None, max_length=200),
    source: str | None = Query(None, max_length=30),
    layer: str | None = Query(None, max_length=50),
    state: str = Query("all", pattern="^(compatible|adapter|all|installed)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=48),
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await platform_extension_service.catalog_page(
        db,
        auth.id,
        query=q,
        source_filter=source,
        layer=layer,
        state=state,
        page=page,
        page_size=page_size,
    )


@router.post("/catalog/sync")
async def sync_catalog(
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await sync_discovery_catalog(db)
    await platform_extension_service.record_event(
        db,
        event_type="catalog_synced",
        actor_admin_id=auth.id,
        status="ok" if result["status"] == "ok" else result["status"],
        details=result,
    )
    await db.commit()
    return result


async def _catalog_entry(db: AsyncSession, entry_id: UUID) -> PlatformExtensionCatalogEntry:
    row = await db.get(PlatformExtensionCatalogEntry, entry_id)
    if not row or not row.is_active:
        raise HTTPException(status_code=404, detail="Catalog entry not found")
    return row


@router.get("/catalog/{entry_id}", response_model=ExtensionCatalogItem)
async def catalog_detail(
    entry_id: UUID,
    _: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return platform_extension_service.catalog_entry_to_item(await _catalog_entry(db, entry_id))


@router.post("/catalog/{entry_id}/import", response_model=ExtensionSourceRead, status_code=202)
async def import_catalog_entry(
    entry_id: UUID,
    data: ExtensionCatalogImportRequest,
    background: BackgroundTasks,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    entry = await _catalog_entry(db, entry_id)
    if entry.compatibility_status == "incompatible":
        raise HTTPException(status_code=409, detail="This catalog entry is not publishable on the SaaS runtime")
    selected_source = data.source or ("npm" if entry.package_name else "github")
    if selected_source == "npm":
        if not entry.package_name:
            raise HTTPException(status_code=422, detail="Catalog entry has no npm package")
        if not data.version or not re.fullmatch(
            r"v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", data.version
        ):
            raise HTTPException(status_code=422, detail="An exact npm semantic version is required")
        source_type, locator, requested_version = "npm", entry.package_name, data.version
    elif selected_source == "github":
        if not entry.repository:
            raise HTTPException(status_code=422, detail="Catalog entry has no GitHub repository")
        parsed_host = (urlparse(entry.repository).hostname or "").lower()
        if parsed_host not in {"github.com", "www.github.com"}:
            raise HTTPException(status_code=422, detail="Only github.com catalog repositories are importable")
        if not data.ref:
            raise HTTPException(status_code=422, detail="A GitHub branch, tag or commit is required")
        source_type, locator, requested_version = "github", entry.repository, data.ref
    row = await platform_extension_service.create_source(
        db,
        source_type=source_type,
        locator=locator,
        requested_version=requested_version,
        admin_id=auth.id,
    )
    row.build_report = {**(row.build_report or {}), "catalog_entry_id": str(entry.id)}
    await db.commit()
    await db.refresh(row)
    background.add_task(platform_extension_service.process_source_build, row.id)
    return row


@router.post("/catalog/{entry_id}/adaptation-brief")
async def adaptation_brief(
    entry_id: UUID,
    _: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    entry = await _catalog_entry(db, entry_id)
    reasons = "\n".join(f"- {reason}" for reason in entry.compatibility_reasons) or "- 尚无自动判断结果"
    brief = f"""# AI Platform DSH扩展适配任务：{entry.name}

## 固定来源

- 目录来源：{entry.provider}
- npm：{entry.package_name or '无'}
- GitHub：{entry.repository or '无'}
- 目标能力层：{entry.layer}
- 操作类型：{entry.operation}
- 当前平台：DSH 0.1.0-rc.5 / Node 22.19.0

## 当前兼容性结论

{reasons}

## 必须完成

1. 阅读并固定插件精确npm版本或Git Commit，不使用latest、分支浮动版本或未锁定依赖。
2. 按仓库 `extension-sdk/manifest.schema.json` 提供 `ai-platform.extension.json`。
3. Runtime插件导出Cordis插件；系统工具导出与声明Schema一一对应的handler。
4. 不直接访问PostgreSQL、OSS长期密钥或租户数据，只通过AI Platform能力桥接。
5. 提供health_check和smoke_test，验证加载、释放、失败清理及重复装配。
6. 运行隔离构建和候选Context验证；只提交适配器、清单、锁文件和测试。

## 验收

- 导入后状态不得为“需要适配器”或“不兼容”。
- 候选发布必须保持恰好一个协调器，且不得覆盖平台受保护工具名。
- 候选失败不得影响当前活动Runtime，发布失败必须能够回滚。
"""
    filename = re.sub(r"[^a-zA-Z0-9._-]+", "-", entry.slug).strip("-") or "extension"
    return Response(
        brief,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="adapt-{filename}.md"'},
    )


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
