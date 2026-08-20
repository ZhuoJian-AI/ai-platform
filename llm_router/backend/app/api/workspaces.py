"""Workspace & workspace files CRUD API."""

import asyncio
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
from fastapi.responses import RedirectResponse
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
from app.models.workspace import WorkspaceUploadSession
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceFileCreate,
    WorkspaceFilePage,
    WorkspaceFilePreviewRead,
    WorkspaceFileRead,
    WorkspaceFileUpdate,
    WorkspaceFolderCreate,
    WorkspaceFolderRead,
    WorkspaceRead,
    WorkspaceUpdate,
    WorkspaceUploadComplete,
    WorkspaceUploadInitiate,
    WorkspaceUploadSessionRead,
)
from app.services import storage_gateway_service, workspace_governance_service
from app.services.organization_service import list_organizations
from app.services.workspace_preview_service import (
    OriginalPreviewError,
    build_original_preview,
)
from app.services.workspace_service import (
    WorkspaceFileUploadError,
    build_workspace_tree,
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
    saved = await upsert_file(db, ws, data, created_by_admin_id=auth.id)
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
            raise HTTPException(status_code=413, detail="10MB 以上文件请使用 OSS 直传")
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
    except WorkspaceFileUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/workspaces/{ws_id}/uploads/initiate", response_model=WorkspaceUploadSessionRead, status_code=201,
)
async def initiate_admin_upload_endpoint(
    ws_id: UUID, data: WorkspaceUploadInitiate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_write_access(auth, ws.organization_id)
    session = await workspace_governance_service.initiate_admin_direct_upload(db, ws, auth, data)
    return WorkspaceUploadSessionRead(
        id=session.id, url=str(session.upload_url), headers=dict(session.upload_headers or {}),
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
    return await workspace_governance_service.complete_direct_upload(
        db, session, auth, client_etag=data.etag,
    )


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
    return WorkspaceFilePage(items=items, total=total, page=page, page_size=page_size)


@router.get("/files/{file_id}", response_model=WorkspaceFileRead)
async def get_file_endpoint(
    file_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    return f


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
    file_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    ws = await get_workspace(db, f.workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_access(auth, ws.organization_id)
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


@router.get("/files/{file_id}/download")
async def download_file_endpoint(
    file_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, await _ws_org_id(db, f.workspace_id))
    if storage_gateway_service.is_object_ref(f.content_ref):
        try:
            signed = await storage_gateway_service.get_signed_download(str(f.content_ref))
        except storage_gateway_service.StorageGatewayError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return RedirectResponse(str(signed["url"]), status_code=307)
    try:
        raw = await load_file_bytes(f)
    except WorkspaceFileUploadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    metadata = f.metadata_ or {}
    filename = str(metadata.get("name") or f.path.rsplit("/", 1)[-1])
    media_type = str(metadata.get("mime") or "application/octet-stream")
    return Response(content=raw, media_type=media_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/files/{file_id}/reparse", response_model=WorkspaceFileRead)
async def reparse_file_endpoint(
    file_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_write_access(auth, await _ws_org_id(db, f.workspace_id))
    return await reparse_file(db, f)


@router.patch("/files/{file_id}", response_model=WorkspaceFileRead)
async def update_file_endpoint(
    file_id: UUID, data: WorkspaceFileUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_write_access(auth, await _ws_org_id(db, f.workspace_id))
    return await update_file(db, f, data)


@router.delete("/files/{file_id}", status_code=204)
async def delete_file_endpoint(
    file_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_write_access(auth, await _ws_org_id(db, f.workspace_id))
    await soft_delete_file(db, f, admin_id=auth.id)


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
    await soft_delete_folder(db, folder)
