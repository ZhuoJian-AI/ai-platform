"""Workspace & workspace files CRUD API."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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
from app.database import get_db
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceFileCreate,
    WorkspaceFilePreviewRead,
    WorkspaceFileRead,
    WorkspaceFileUpdate,
    WorkspaceFolderCreate,
    WorkspaceFolderRead,
    WorkspaceRead,
    WorkspaceUpdate,
)
from app.services.organization_service import list_organizations
from app.services.workspace_service import (
    WorkspaceFileUploadError,
    build_workspace_tree,
    create_folder,
    create_workspace,
    get_file,
    get_folder,
    get_workspace,
    ingest_uploaded_file,
    list_files,
    list_folders,
    list_workspaces,
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
    return await upsert_file(db, ws, data)


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
    raw = await file.read()
    try:
        return await ingest_uploaded_file(
            db, ws, path=path or file.filename or "upload.bin",
            filename=file.filename or "upload.bin", content_type=file.content_type, raw=raw,
        )
    except WorkspaceFileUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/workspaces/{ws_id}/files", response_model=list[WorkspaceFileRead])
async def list_files_endpoint(
    ws_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    assert_org_access(auth, ws.organization_id)
    return await list_files(db, ws.id)


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
    await soft_delete_file(db, f)


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
