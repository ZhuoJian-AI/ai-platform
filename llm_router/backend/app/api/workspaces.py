"""Workspace & workspace files CRUD API."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import (
    CurrentAdmin,
    assert_org_access,
    assert_org_write_access,
    require_admin,
    require_org_access,
    require_org_access_write,
)
from app.config import settings
from app.database import get_db
from app.models.organization import Organization
from app.models.workspace import WorkspaceFileVersion, WorkspaceUploadSession
from app.schemas.workspace import (
    WorkspaceAuditEventRead,
    WorkspaceBulkDeleteRequest,
    WorkspaceBulkDeleteResult,
    WorkspaceCreate,
    WorkspaceDownloadTicketRead,
    WorkspaceEditRoomStatusRead,
    WorkspaceEditSessionClose,
    WorkspaceEditSessionCreate,
    WorkspaceFallbackPreviewRead,
    WorkspaceFileCreate,
    WorkspaceFileDeleteRequest,
    WorkspaceFilePage,
    WorkspaceFilePreviewRead,
    WorkspaceFileRead,
    WorkspaceFileRestoreRequest,
    WorkspaceFileUpdate,
    WorkspaceFileVersionRead,
    WorkspaceFolderCreate,
    WorkspaceFolderRead,
    WorkspaceOriginalPreviewSourceRead,
    WorkspacePreviewSessionCreate,
    WorkspacePreviewSessionRead,
    WorkspacePreviewSessionRefresh,
    WorkspaceRead,
    WorkspaceSpreadsheetPageRead,
    WorkspaceSpreadsheetPreviewRead,
    WorkspaceUpdate,
    WorkspaceUploadComplete,
    WorkspaceUploadInitiate,
    WorkspaceUploadMultipartStatus,
    WorkspaceUploadPartSigned,
    WorkspaceUploadSessionRead,
)
from app.services import (
    storage_gateway_service,
    workspace_governance_service,
    workspace_office_edit_service,
    workspace_pdf_preview_service,
    workspace_preview_session_service,
    workspace_service,
)
from app.services.organization_service import list_organizations
from app.services.workspace_preview_service import (
    OriginalPreviewError,
    build_original_preview,
    source_metadata,
)
from app.services.workspace_service import (
    WorkspaceFileInvalidPath,
    WorkspaceFilePathConflict,
    WorkspaceFileUnsupportedTextUpdate,
    WorkspaceFileUploadError,
    build_workspace_tree,
    bulk_soft_delete_items,
    create_folder,
    create_workspace,
    get_file,
    get_folder,
    get_workspace,
    ingest_uploaded_file,
    list_files_page,
    list_folders,
    list_workspaces,
    load_file_bytes,
    reparse_file,
    soft_delete_file,
    soft_delete_folder,
    soft_delete_folder_path,
    soft_delete_workspace,
    update_file,
    update_workspace,
    upsert_file,
)

router = APIRouter()


async def _ws_org_id(db: AsyncSession, ws_id: UUID) -> UUID:
    """取 workspace 所属组织 id；不存在则 404。"""
    ws = await get_workspace(db, ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws.organization_id


async def _admin_file_read(db: AsyncSession, ws, file) -> WorkspaceFileRead:
    version_numbers = await workspace_service.current_version_numbers(db, [file.id])
    _, previous_version_id = await workspace_service.version_lineage(db, file)
    caps = {"read": True, "create": True, "update": True, "delete": True}
    return WorkspaceFileRead.model_validate(file).model_copy(update={
        "workspace_name": ws.name,
        "workspace_slug": ws.slug,
        "canonical_path": f"{ws.name}:/{str(file.path).lstrip('/')}",
        "current_version_no": version_numbers.get(str(file.id)),
        "previous_version_id": previous_version_id,
        "mutation_result_version_id": getattr(file, "mutation_result_version_id", None),
        "capabilities": caps,
        "effective_capabilities": caps,
        "internal_url": f"/f/{file.id}",
        "office_edit_enabled": workspace_service.office_edit_enabled(file, can_update=True),
    })


async def _admin_file_version_read(
    db: AsyncSession, ws, file, version: WorkspaceFileVersion,
) -> WorkspaceFileRead:
    current_numbers = await workspace_service.current_version_numbers(db, [file.id])
    _, previous_version_id = await workspace_service.version_lineage(db, file)
    caps = {"read": True, "create": False, "update": False, "delete": False}
    return WorkspaceFileRead(
        id=file.id,
        workspace_id=file.workspace_id,
        path=file.path,
        size=version.size,
        content_hash=version.content_hash,
        content=version.content,
        extracted_text=version.extracted_text,
        parse_status=version.parse_status,
        parse_kind=version.parse_kind,
        parse_error=version.parse_error,
        metadata=dict(version.metadata_ or {}),
        created_at=file.created_at,
        updated_at=version.created_at,
        current_version_id=file.current_version_id,
        previous_version_id=previous_version_id,
        resolved_version_id=version.id,
        resolved_version_no=int(version.version_no),
        is_historical=str(version.id) != str(file.current_version_id),
        workspace_name=ws.name,
        workspace_slug=ws.slug,
        canonical_path=f"{ws.name}:/{str(file.path).lstrip('/')}",
        current_version_no=current_numbers.get(str(file.id)),
        capabilities=caps,
        effective_capabilities=caps,
        internal_url=f"/f/{file.id}?version={version.id}",
        office_edit_enabled=False,
    )


async def _admin_file_snapshot_at_version(
    db: AsyncSession, file, version_id: UUID | None,
):
    try:
        return await workspace_service.file_snapshot_at_version(db, file, version_id)
    except workspace_service.WorkspaceFileVersionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Workspace Tree（随组织架构逐级嵌套）──

@router.get("/workspaces/tree")
async def workspace_tree_endpoint(
    organization_id: UUID | None = None,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    """工作空间文件夹树：组织 → 部门 → 团队 → 用户，每节点携带同名绑定工作空间。

    - 指定 ``organization_id`` 时仅返回该组织子树（须有访问权）；
    - 组织级管理员未指定时返回其组织子树；
    - 平台级账号（超管）未指定时返回全部组织。
    """
    if organization_id is not None:
        assert_org_access(auth, organization_id)
        org_ids = [organization_id]
    elif auth.organization_id is not None:
        org_ids = [auth.organization_id]
    else:
        org_ids = [o.id for o in await list_organizations(db)]
    return await build_workspace_tree(db, org_ids)


# ── Workspace ──

@router.post("/organizations/{org_id}/workspaces", response_model=WorkspaceRead, status_code=201)
async def create_ws_endpoint(
    org_id: UUID, data: WorkspaceCreate,
    _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    try:
        return await create_workspace(db, org_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists")


@router.get("/organizations/{org_id}/workspaces", response_model=list[WorkspaceRead])
async def list_ws_endpoint(
    org_id: UUID, _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    return await list_workspaces(db, org_id)


@router.get("/workspaces/{ws_id}", response_model=WorkspaceRead)
async def get_ws_endpoint(
    ws_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_access(auth, ws.organization_id)
    return ws


@router.patch("/workspaces/{ws_id}", response_model=WorkspaceRead)
async def update_ws_endpoint(
    ws_id: UUID, data: WorkspaceUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    return await update_workspace(db, ws, data)


@router.delete("/workspaces/{ws_id}", status_code=204)
async def delete_ws_endpoint(
    ws_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    await soft_delete_workspace(db, ws)


# ── Workspace Files ──

@router.post("/workspaces/{ws_id}/files", response_model=WorkspaceFileRead, status_code=201)
async def upsert_file_endpoint(
    ws_id: UUID, data: WorkspaceFileCreate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    try:
        saved = await upsert_file(db, ws, data, created_by_admin_id=auth.id)
    except WorkspaceFileInvalidPath as exc:
        raise HTTPException(status_code=422, detail={
            "code": "workspace_file_invalid_path",
            "message": str(exc),
        }) from exc
    except WorkspaceFileUnsupportedTextUpdate as exc:
        raise HTTPException(status_code=422, detail={
            "code": "workspace_file_unsupported_text_create",
            "message": str(exc),
        }) from exc
    except WorkspaceFilePathConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_path_conflict",
            "message": str(exc),
            "file_id": exc.file_id,
            "current_version_id": exc.current_version_id,
        }) from exc
    await workspace_governance_service.audit(
        db,
        ws,
        "file_written",
        admin_id=auth.id,
        file=saved,
        version_id=saved.current_version_id,
    )
    return saved


@router.post("/workspaces/{ws_id}/files/upload", response_model=WorkspaceFileRead, status_code=201)
async def upload_file_endpoint(
    ws_id: UUID,
    file: UploadFile = File(...),
    path: str | None = Form(default=None),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    raw = bytearray()
    while chunk := await file.read(1024 * 1024):
        raw.extend(chunk)
        if len(raw) > settings.workspace_proxy_upload_max_bytes:
            raise HTTPException(status_code=413, detail="文件超过平台代理阈值，请使用 OSS 直传")
    try:
        saved = await ingest_uploaded_file(
            db, ws, path=path or file.filename or "upload.bin",
            filename=file.filename or "upload.bin", content_type=file.content_type, raw=bytes(raw),
            created_by_admin_id=auth.id,
        )
        await workspace_governance_service.audit(
            db,
            ws,
            "upload_completed",
            admin_id=auth.id,
            file=saved,
            version_id=saved.current_version_id,
            metadata={"size": saved.size, "transport": "backend_proxy"},
        )
        return saved
    except WorkspaceFilePathConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_path_conflict",
            "message": str(exc),
            "file_id": exc.file_id,
            "current_version_id": exc.current_version_id,
        }) from exc
    except WorkspaceFileUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/workspaces/{ws_id}/uploads/initiate", response_model=WorkspaceUploadSessionRead, status_code=201,
)
async def initiate_admin_upload_endpoint(
    ws_id: UUID, data: WorkspaceUploadInitiate, response: Response,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    ws = await get_workspace(db, ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    session = await workspace_governance_service.initiate_admin_direct_upload(db, ws, auth, data)
    upload_meta = dict(session.upload_headers or {})
    upload_auth = workspace_governance_service.transient_upload_authorization(session)
    return WorkspaceUploadSessionRead(
        id=session.id,
        method=str(upload_meta.get("transport") or "put").upper(),
        url=str(upload_auth.get("url")) if upload_auth.get("url") else None,
        fallback_url=(
            str(upload_auth.get("fallback_url"))
            if upload_auth.get("fallback_url") else None
        ),
        headers=dict(upload_auth.get("headers") or {}),
        part_size=upload_meta.get("part_size"),
        expected_parts=upload_meta.get("expected_parts"),
        expires_at=session.expires_at, max_file_bytes=settings.workspace_max_file_bytes,
    )


@router.post("/workspace-uploads/{session_id}/complete", response_model=WorkspaceFileRead)
async def complete_admin_upload_endpoint(
    session_id: UUID, data: WorkspaceUploadComplete,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    session = await db.get(WorkspaceUploadSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="上传会话不存在")
    assert_org_write_access(auth, session.organization_id)
    file = await workspace_governance_service.complete_direct_upload(
        db,
        session,
        auth,
        client_etag=data.etag,
        parts=[part.model_dump() for part in data.parts],
    )
    await db.commit()
    return file


@router.get("/workspace-uploads/{session_id}", response_model=WorkspaceUploadMultipartStatus)
async def status_admin_upload_endpoint(
    session_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    session = await db.get(WorkspaceUploadSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="上传会话不存在")
    assert_org_write_access(auth, session.organization_id)
    return await workspace_governance_service.multipart_upload_status(session, auth)


@router.post(
    "/workspace-uploads/{session_id}/parts/{part_number}/sign",
    response_model=WorkspaceUploadPartSigned,
)
async def sign_admin_upload_part_endpoint(
    session_id: UUID,
    part_number: int,
    response: Response,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    session = await db.get(WorkspaceUploadSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="上传会话不存在")
    assert_org_write_access(auth, session.organization_id)
    return await workspace_governance_service.sign_upload_part(session, auth, part_number)


@router.delete("/workspace-uploads/{session_id}", status_code=204)
async def cancel_admin_upload_endpoint(
    session_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    session = await db.get(WorkspaceUploadSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="上传会话不存在")
    assert_org_write_access(auth, session.organization_id)
    await workspace_governance_service.cancel_upload(db, session, auth)


@router.get("/workspaces/{ws_id}/files", response_model=WorkspaceFilePage)
async def list_files_endpoint(
    ws_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_access(auth, ws.organization_id)
    items, total = await list_files_page(db, ws.id, page=page, page_size=page_size)
    version_numbers = await workspace_service.current_version_numbers(
        db, [item.id for item in items],
    )
    enriched = [item.model_copy(update={
        "workspace_name": ws.name,
        "workspace_slug": ws.slug,
        "canonical_path": f"{ws.name}:/{str(item.path).lstrip('/')}",
        "current_version_no": version_numbers.get(str(item.id)),
        "capabilities": {"read": True, "create": True, "update": True, "delete": True},
        "effective_capabilities": {"read": True, "create": True, "update": True, "delete": True},
        "internal_url": f"/f/{item.id}",
        "office_edit_enabled": bool(item.office_edit_enabled),
    }) for item in items]
    return WorkspaceFilePage(items=enriched, total=total, page=page, page_size=page_size)


@router.get("/files/{file_id}", response_model=WorkspaceFileRead)
async def get_file_endpoint(
    file_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await get_workspace(db, f.workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_access(auth, ws.organization_id)
    return await _admin_file_read(db, ws, f)


@router.get("/files/{file_id}/preview", response_model=WorkspaceFilePreviewRead)
async def preview_file_endpoint(
    file_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    return f


@router.get("/files/{file_id}/original-preview")
async def original_preview_file_endpoint(
    file_id: UUID, version_id: UUID | None = Query(None),
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await get_workspace(db, f.workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_access(auth, ws.organization_id)
    f, _ = await _admin_file_snapshot_at_version(db, f, version_id)
    organization = await db.get(Organization, ws.organization_id)
    if organization is None or not settings.original_preview_enabled_for(organization.slug):
        raise HTTPException(status_code=404, detail="Original preview is not enabled")
    try:
        raw = await load_file_bytes(f)
        content, media_type, filename = await asyncio.to_thread(build_original_preview, f, raw)
    except WorkspaceFileUploadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except OriginalPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    })


@router.get(
    "/files/{file_id}/original-preview-source",
    response_model=WorkspaceOriginalPreviewSourceRead,
)
async def original_preview_source_endpoint(
    file_id: UUID, response: Response, version_id: UUID | None = Query(None),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a browser-safe source without proxying a large object twice."""
    response.headers["Cache-Control"] = "private, no-store"
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await get_workspace(db, f.workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_access(auth, ws.organization_id)
    f, version = await _admin_file_snapshot_at_version(db, f, version_id)
    organization = await db.get(Organization, ws.organization_id)
    if organization is None or not settings.original_preview_enabled_for(organization.slug):
        raise HTTPException(status_code=404, detail="Original preview is not enabled")
    try:
        filename, mime_type = source_metadata(f)
        if storage_gateway_service.is_object_ref(f.content_ref):
            signed = await storage_gateway_service.get_browser_signed_download(
                str(f.content_ref), version_id=workspace_service.storage_version_id(f, version),
            )
            return WorkspaceOriginalPreviewSourceRead(
                mode="url",
                url=str(signed["url"]),
                fallback_url=str(signed.get("fallback_url")) if signed.get("fallback_url") else None,
                headers={str(k): str(v) for k, v in (signed.get("headers") or {}).items()},
                filename=filename,
                mime_type=mime_type,
            )
        return WorkspaceOriginalPreviewSourceRead(
            mode="blob", filename=filename, mime_type=mime_type,
        )
    except OriginalPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/files/{file_id}/pdf-preview/info")
async def pdf_preview_info_endpoint(
    file_id: UUID, version_id: UUID | None = Query(None),
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    f, _ = await _admin_file_snapshot_at_version(db, f, version_id)
    try:
        return await workspace_pdf_preview_service.get_pdf_info(db, f)
    except workspace_pdf_preview_service.WorkspacePdfPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/files/{file_id}/preview-session", response_model=WorkspacePreviewSessionRead)
async def preview_session_endpoint(
    file_id: UUID, data: WorkspacePreviewSessionCreate, response: Response,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    f, _ = await _admin_file_snapshot_at_version(db, f, data.version_id)
    try:
        actor = hashlib.sha256(f"admin:{auth.id}".encode()).hexdigest()[:15]
        result = await workspace_preview_session_service.create_preview_session(
            db, f, weboffice_user_id=actor, client_open_id=data.client_open_id,
            preferred_mode=data.preferred_mode,
        )
        await db.commit()
        return WorkspacePreviewSessionRead(**result)
    except OriginalPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/files/{file_id}/preview-session/refresh", response_model=WorkspacePreviewSessionRead,
)
async def refresh_preview_session_endpoint(
    file_id: UUID, data: WorkspacePreviewSessionRefresh, response: Response,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    try:
        actor = hashlib.sha256(f"admin:{auth.id}".encode()).hexdigest()[:15]
        token = await workspace_preview_session_service.refresh_preview_session(
            f, access_token=data.access_token, refresh_token=data.refresh_token,
            refresh_context=data.refresh_context, weboffice_user_id=actor,
        )
        filename, mime_type = source_metadata(f)
        return WorkspacePreviewSessionRead(
            mode="weboffice", filename=filename, mime_type=mime_type,
            size=int(f.size or 0), **token,
        )
    except OriginalPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/files/{file_id}/edit-session", response_model=WorkspacePreviewSessionRead)
async def edit_session_endpoint(
    file_id: UUID,
    data: WorkspaceEditSessionCreate,
    response: Response,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    f = await get_file(db, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await get_workspace(db, f.workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    try:
        result = await workspace_office_edit_service.create_edit_session(
            db,
            f,
            actor_type="admin",
            actor_id=str(auth.id),
            client_open_id=data.client_open_id,
        )
        await db.commit()
        return WorkspacePreviewSessionRead(**result)
    except OriginalPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/files/{file_id}/edit-session/refresh",
    response_model=WorkspacePreviewSessionRead,
)
async def refresh_edit_session_endpoint(
    file_id: UUID,
    data: WorkspacePreviewSessionRefresh,
    response: Response,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    f = await get_file(db, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await get_workspace(db, f.workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    if data.room_id is None:
        raise HTTPException(status_code=422, detail="room_id is required for edit refresh")
    try:
        result = await workspace_office_edit_service.refresh_edit_session(
            db,
            f,
            actor_type="admin",
            actor_id=str(auth.id),
            access_token=data.access_token,
            refresh_token=data.refresh_token,
            refresh_context=data.refresh_context,
            room_id=data.room_id,
        )
        await db.commit()
        return WorkspacePreviewSessionRead(**result)
    except OriginalPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/files/{file_id}/edit-session/{room_id}",
    response_model=WorkspaceEditRoomStatusRead,
)
async def edit_session_status_endpoint(
    file_id: UUID,
    room_id: UUID,
    response: Response,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    f = await get_file(db, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await get_workspace(db, f.workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    room = await workspace_office_edit_service.get_edit_room(
        db, f, room_id=room_id, actor_type="admin", actor_id=str(auth.id),
    )
    if room is None:
        raise HTTPException(status_code=404, detail="Edit session not found")
    return WorkspaceEditRoomStatusRead(
        **await workspace_office_edit_service.edit_room_status_payload(db, f, room)
    )


@router.post(
    "/files/{file_id}/edit-session/close",
    response_model=WorkspaceEditRoomStatusRead,
)
async def close_edit_session_endpoint(
    file_id: UUID,
    data: WorkspaceEditSessionClose,
    response: Response,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    f = await get_file(db, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await get_workspace(db, f.workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    room = await workspace_office_edit_service.close_edit_session(
        db,
        f,
        actor_type="admin",
        actor_id=str(auth.id),
        client_open_id=data.client_open_id,
    )
    if room is None:
        raise HTTPException(status_code=404, detail="Edit session not found")
    await db.commit()
    return WorkspaceEditRoomStatusRead(
        **await workspace_office_edit_service.edit_room_status_payload(db, f, room)
    )


async def _fallback_preview(
    file_id: UUID, response: Response, auth: CurrentAdmin, db: AsyncSession, *,
    create: bool, version_id: UUID | None = None,
):
    response.headers["Cache-Control"] = "private, no-store"
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    f, _ = await _admin_file_snapshot_at_version(db, f, version_id)
    try:
        result = await workspace_preview_session_service.fallback_status(db, f, create=create)
        if create:
            await db.commit()
        return WorkspaceFallbackPreviewRead(**result)
    except OriginalPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/files/{file_id}/fallback-preview", response_model=WorkspaceFallbackPreviewRead)
async def start_fallback_preview_endpoint(
    file_id: UUID, response: Response, version_id: UUID | None = Query(None),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _fallback_preview(
        file_id, response, auth, db, create=True, version_id=version_id,
    )


@router.get("/files/{file_id}/fallback-preview", response_model=WorkspaceFallbackPreviewRead)
async def get_fallback_preview_endpoint(
    file_id: UUID, response: Response, version_id: UUID | None = Query(None),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _fallback_preview(
        file_id, response, auth, db, create=False, version_id=version_id,
    )


async def _spreadsheet_preview(
    file_id: UUID, response: Response, auth: CurrentAdmin, db: AsyncSession, *,
    create: bool, version_id: UUID | None = None,
):
    response.headers["Cache-Control"] = "private, no-store"
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    f, _ = await _admin_file_snapshot_at_version(db, f, version_id)
    try:
        result = await workspace_preview_session_service.spreadsheet_status(db, f, create=create)
        if create:
            await db.commit()
        return WorkspaceSpreadsheetPreviewRead(**result)
    except OriginalPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/files/{file_id}/spreadsheet-preview", response_model=WorkspaceSpreadsheetPreviewRead)
async def start_spreadsheet_preview_endpoint(
    file_id: UUID, response: Response, version_id: UUID | None = Query(None),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _spreadsheet_preview(
        file_id, response, auth, db, create=True, version_id=version_id,
    )


@router.get("/files/{file_id}/spreadsheet-preview", response_model=WorkspaceSpreadsheetPreviewRead)
async def get_spreadsheet_preview_endpoint(
    file_id: UUID, response: Response, version_id: UUID | None = Query(None),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _spreadsheet_preview(
        file_id, response, auth, db, create=False, version_id=version_id,
    )


@router.get(
    "/files/{file_id}/spreadsheet-preview/sheets/{sheet}/pages/{page}",
    response_model=WorkspaceSpreadsheetPageRead,
)
async def spreadsheet_preview_page_endpoint(
    file_id: UUID, sheet: str, page: int, response: Response,
    version_id: UUID | None = Query(None),
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    f, _ = await _admin_file_snapshot_at_version(db, f, version_id)
    try:
        return WorkspaceSpreadsheetPageRead(**await workspace_preview_session_service.spreadsheet_page(
            db, f, sheet_name=sheet, page=page,
        ))
    except OriginalPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/files/{file_id}/pdf-preview/pages/{page_number}")
async def pdf_preview_page_endpoint(
    file_id: UUID, page_number: int, version_id: UUID | None = Query(None),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    f, _ = await _admin_file_snapshot_at_version(db, f, version_id)
    try:
        content, media_type = await workspace_pdf_preview_service.get_pdf_page(db, f, page_number)
    except workspace_pdf_preview_service.WorkspacePdfPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=content, media_type=media_type, headers={
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/files/{file_id}/download")
async def download_file_endpoint(
    file_id: UUID, version_id: UUID | None = Query(None),
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    f, version = await _admin_file_snapshot_at_version(db, f, version_id)
    metadata = f.metadata_ or {}
    filename = str(metadata.get("name") or f.path.rsplit("/", 1)[-1])
    media_type = str(metadata.get("mime") or "application/octet-stream")
    if storage_gateway_service.is_object_ref(f.content_ref):
        try:
            signed = await storage_gateway_service.get_signed_download(
                str(f.content_ref), version_id=workspace_service.storage_version_id(f, version),
            )
        except storage_gateway_service.StorageGatewayError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return StreamingResponse(
            storage_gateway_service.stream_signed_download(
                str(signed["url"]),
                headers={str(k): str(v) for k, v in (signed.get("headers") or {}).items()},
                max_bytes=settings.workspace_max_file_bytes,
            ),
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
                "X-Content-Type-Options": "nosniff",
            },
        )
    try:
        raw = await load_file_bytes(f)
    except WorkspaceFileUploadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=raw, media_type=media_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/files/{file_id}/download-ticket", response_model=WorkspaceDownloadTicketRead)
async def download_ticket_endpoint(
    file_id: UUID, response: Response, version_id: UUID | None = Query(None),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    f, version = await _admin_file_snapshot_at_version(db, f, version_id)
    if not storage_gateway_service.is_object_ref(f.content_ref):
        raise HTTPException(status_code=409, detail="该历史文件尚未迁移到 OSS，请使用兼容下载")
    try:
        filename, mime_type = source_metadata(f)
        signed = await storage_gateway_service.get_browser_signed_download(
            str(f.content_ref), expires_in_seconds=15 * 60, filename=filename,
            version_id=workspace_service.storage_version_id(f, version),
        )
    except OriginalPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    metadata = dict(f.metadata_ or {})
    expires_in = min(15 * 60, int(signed.get("expires_in") or 15 * 60))
    return WorkspaceDownloadTicketRead(
        url=str(signed["url"]),
        fallback_url=str(signed.get("fallback_url")) if signed.get("fallback_url") else None,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        filename=filename,
        mime_type=mime_type,
        etag=str(metadata.get("etag") or "") or None,
        size=int(f.size or 0),
        headers={str(k): str(v) for k, v in (signed.get("headers") or {}).items()},
    )


@router.post("/files/{file_id}/reparse", response_model=WorkspaceFileRead)
async def reparse_file_endpoint(
    file_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_write_access(auth, await _ws_org_id(db, f.workspace_id))
    return await reparse_file(db, f)


@router.post("/files/{file_id}/versions", response_model=WorkspaceFileRead)
@router.patch("/files/{file_id}", response_model=WorkspaceFileRead)
async def update_file_endpoint(
    file_id: UUID, data: WorkspaceFileUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await get_workspace(db, f.workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    if data.base_version_id is None or not data.idempotency_key:
        raise HTTPException(
            status_code=422,
            detail="base_version_id and idempotency_key are required",
        )
    try:
        updated = await update_file(db, f, data, created_by_admin_id=auth.id)
    except workspace_service.WorkspaceFileVersionConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_version_conflict",
            "message": str(exc),
            "current_version_id": exc.current_version_id,
            "latest_version_id": exc.current_version_id,
        }) from exc
    except WorkspaceFileUnsupportedTextUpdate as exc:
        raise HTTPException(status_code=422, detail={
            "code": "workspace_file_unsupported_text_update",
            "message": str(exc),
        }) from exc
    except workspace_service.WorkspaceFileMetadataConflict as exc:
        raise HTTPException(status_code=422, detail={
            "code": "workspace_file_reserved_metadata",
            "message": str(exc),
        }) from exc
    except workspace_service.WorkspaceFileIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_idempotency_conflict",
            "message": str(exc),
            "current_version_id": str(f.current_version_id) if f.current_version_id else None,
            "latest_version_id": str(f.current_version_id) if f.current_version_id else None,
        }) from exc
    except workspace_service.WorkspaceFileActiveEditConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_active_edit_conflict",
            "message": str(exc),
            "room_id": exc.room_id,
            "current_version_id": exc.current_version_id,
            "latest_version_id": exc.current_version_id,
        }) from exc
    except WorkspaceFileUploadError as exc:
        raise HTTPException(status_code=502, detail={
            "code": "workspace_file_storage_write_failed",
            "message": str(exc),
        }) from exc
    return await _admin_file_read(db, ws, updated)


@router.delete("/files/{file_id}", status_code=204)
async def delete_file_endpoint(
    file_id: UUID,
    data: WorkspaceFileDeleteRequest,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    f = await workspace_service.get_file_including_deleted(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_write_access(auth, await _ws_org_id(db, f.workspace_id))
    try:
        await soft_delete_file(
            db,
            f,
            admin_id=auth.id,
            base_version_id=data.base_version_id,
            idempotency_key=data.idempotency_key,
            mutation_actor_type="admin",
            mutation_actor_id=str(auth.id),
        )
    except workspace_service.WorkspaceFileVersionConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_version_conflict",
            "message": str(exc),
            "current_version_id": exc.current_version_id,
            "latest_version_id": exc.current_version_id,
        }) from exc
    except workspace_service.WorkspaceFileIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_idempotency_conflict", "message": str(exc),
        }) from exc
    except workspace_service.WorkspaceFileActiveEditConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_active_edit_conflict",
            "message": str(exc),
            "room_id": exc.room_id,
            "current_version_id": exc.current_version_id,
            "latest_version_id": exc.current_version_id,
        }) from exc


@router.get("/files/{file_id}/versions", response_model=list[WorkspaceFileVersionRead])
async def list_file_versions_endpoint(
    file_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    versions = await workspace_governance_service.list_versions(db, f)
    return [
        WorkspaceFileVersionRead.model_validate(version).model_copy(update={
            "internal_url": f"/f/{f.id}?version={version.id}",
        })
        for version in versions
    ]


@router.get("/files/{file_id}/versions/{version_id}", response_model=WorkspaceFileRead)
async def get_file_version_endpoint(
    file_id: UUID,
    version_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    file = await get_file(db, file_id)
    version = await db.get(WorkspaceFileVersion, version_id)
    if file is None or version is None or str(version.workspace_file_id) != str(file.id):
        raise HTTPException(status_code=404, detail="文件版本不存在")
    ws = await get_workspace(db, file.workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_access(auth, ws.organization_id)
    return await _admin_file_version_read(db, ws, file, version)


@router.post(
    "/files/{file_id}/versions/{version_id}/restore",
    response_model=WorkspaceFileRead,
)
async def restore_file_version_endpoint(
    file_id: UUID,
    version_id: UUID,
    data: WorkspaceFileRestoreRequest,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    version = await db.get(WorkspaceFileVersion, version_id)
    if not f or version is None:
        raise HTTPException(status_code=404, detail="文件版本不存在")
    ws = await get_workspace(db, f.workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    try:
        restored = await workspace_service.restore_file_version(
            db, f, version,
            base_version_id=data.base_version_id,
            idempotency_key=data.idempotency_key,
            created_by_admin_id=auth.id,
        )
    except workspace_service.WorkspaceFileVersionConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_version_conflict", "message": str(exc),
            "current_version_id": exc.current_version_id,
            "latest_version_id": exc.current_version_id,
        }) from exc
    except workspace_service.WorkspaceFileIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_idempotency_conflict", "message": str(exc),
        }) from exc
    except workspace_service.WorkspaceFileActiveEditConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_active_edit_conflict", "message": str(exc),
            "room_id": exc.room_id, "current_version_id": exc.current_version_id,
        }) from exc
    await workspace_governance_service.audit(
        db, ws, "version_restored", admin_id=auth.id, file=restored,
        version_id=restored.current_version_id,
        metadata={"restored_from": str(version.id)},
    )
    return await _admin_file_read(db, ws, restored)


@router.get("/workspaces/{ws_id}/trash", response_model=list[WorkspaceFileRead])
async def list_trash_endpoint(
    ws_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_access(auth, ws.organization_id)
    return await workspace_governance_service.list_trash(db, ws)


@router.get("/workspaces/{ws_id}/audit", response_model=list[WorkspaceAuditEventRead])
async def list_workspace_audit_endpoint(
    ws_id: UUID,
    limit: int = Query(200, ge=1, le=500),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_access(auth, ws.organization_id)
    return await workspace_governance_service.list_audit_events(db, ws, limit=limit)


@router.post("/workspaces/{ws_id}/trash/{file_id}/restore", response_model=WorkspaceFileRead)
async def restore_trash_endpoint(
    ws_id: UUID,
    file_id: UUID,
    data: WorkspaceFileRestoreRequest,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    return await workspace_governance_service.restore_from_trash_admin(
        db,
        ws,
        file_id,
        auth,
        base_version_id=data.base_version_id,
        idempotency_key=data.idempotency_key,
    )


@router.delete("/workspaces/{ws_id}/folder-path")
async def delete_folder_path_endpoint(
    ws_id: UUID,
    path: str = Query(..., min_length=1, max_length=1024),
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    try:
        deleted = await soft_delete_folder_path(db, ws.id, path, admin_id=auth.id)
    except workspace_service.WorkspaceFileActiveEditConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_active_edit_conflict",
            "message": str(exc),
            "room_id": exc.room_id,
            "current_version_id": exc.current_version_id,
        }) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await workspace_governance_service.audit(
        db, ws, "folder_deleted", admin_id=auth.id, metadata={"path": path, **deleted},
    )
    return deleted


@router.post(
    "/workspaces/{ws_id}/items/bulk-delete",
    response_model=WorkspaceBulkDeleteResult,
)
async def bulk_delete_items_endpoint(
    ws_id: UUID,
    data: WorkspaceBulkDeleteRequest,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    try:
        deleted = await bulk_soft_delete_items(
            db,
            ws.id,
            file_ids=data.file_ids,
            folder_paths=data.folder_paths,
            admin_id=auth.id,
        )
    except workspace_service.WorkspaceFileActiveEditConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_active_edit_conflict",
            "message": str(exc),
            "room_id": exc.room_id,
            "current_version_id": exc.current_version_id,
        }) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await workspace_governance_service.audit(
        db,
        ws,
        "items_bulk_deleted",
        admin_id=auth.id,
        metadata={**deleted, "folder_paths": data.folder_paths, "file_count": len(data.file_ids)},
    )
    return deleted


# ── Workspace Folders ──

@router.post("/workspaces/{ws_id}/folders", response_model=WorkspaceFolderRead, status_code=201)
async def create_folder_endpoint(
    ws_id: UUID, data: WorkspaceFolderCreate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    return await create_folder(db, ws, data)


@router.get("/workspaces/{ws_id}/folders", response_model=list[WorkspaceFolderRead])
async def list_folders_endpoint(
    ws_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_access(auth, ws.organization_id)
    return await list_folders(db, ws.id)


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder_endpoint(
    folder_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    folder = await get_folder(db, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    assert_org_write_access(auth, await _ws_org_id(db, folder.workspace_id))
    try:
        await soft_delete_folder(db, folder, admin_id=auth.id)
    except workspace_service.WorkspaceFileActiveEditConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_active_edit_conflict",
            "message": str(exc),
            "room_id": exc.room_id,
            "current_version_id": exc.current_version_id,
        }) from exc
    ws = await get_workspace(db, folder.workspace_id)
    if ws is not None:
        await workspace_governance_service.audit(
            db, ws, "folder_deleted", admin_id=auth.id, metadata={"path": folder.path},
        )
    WorkspaceDownloadTicketRead,
    WorkspaceFallbackPreviewRead,
