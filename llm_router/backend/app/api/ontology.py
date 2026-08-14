"""本体 CRUD + validate API（旧 JSONB 模型 dormant）+ 本体文件化存储 API（Markdown 文件/文件夹）。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.schemas.ontology import (
    OntologyCreate,
    OntologyFileCreate,
    OntologyFileRead,
    OntologyFileUpdate,
    OntologyFolderCreate,
    OntologyFolderRead,
    OntologyFolderRename,
    OntologyRead,
    OntologyUpdate,
    OntologyValidateResponse,
)
from app.services.ontology_service import (
    create_ontology,
    get_ontology,
    list_ontologies,
    soft_delete_ontology,
    update_ontology,
    validate,
)
from app.services.ontology_store_service import (
    create_folder,
    get_file,
    get_folder,
    list_files,
    list_folders,
    rename_folder,
    soft_delete_file,
    soft_delete_folder,
    update_file,
    upsert_file,
)

router = APIRouter()


@router.post("/organizations/{org_id}/ontologies", response_model=OntologyRead, status_code=201)
async def create_ontology_endpoint(
    org_id: UUID, data: OntologyCreate,
    _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    try:
        return await create_ontology(db, org_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists")


@router.get("/organizations/{org_id}/ontologies", response_model=list[OntologyRead])
async def list_ontologies_endpoint(
    org_id: UUID, _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    return await list_ontologies(db, org_id)


@router.get("/ontologies/{o_id}", response_model=OntologyRead)
async def get_ontology_endpoint(
    o_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    o = await get_ontology(db, o_id)
    if not o:
        raise HTTPException(status_code=404, detail="本体 not found")
    assert_org_access(auth, o.organization_id)
    return o


@router.patch("/ontologies/{o_id}", response_model=OntologyRead)
async def update_ontology_endpoint(
    o_id: UUID, data: OntologyUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    o = await get_ontology(db, o_id)
    if not o:
        raise HTTPException(status_code=404, detail="本体 not found")
    assert_org_write_access(auth, o.organization_id)
    return await update_ontology(db, o, data)


@router.delete("/ontologies/{o_id}", status_code=204)
async def delete_ontology_endpoint(
    o_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    o = await get_ontology(db, o_id)
    if not o:
        raise HTTPException(status_code=404, detail="本体 not found")
    assert_org_write_access(auth, o.organization_id)
    await soft_delete_ontology(db, o)


@router.post("/ontologies/{o_id}/validate", response_model=OntologyValidateResponse)
async def validate_ontology_endpoint(
    o_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    o = await get_ontology(db, o_id)
    if not o:
        raise HTTPException(status_code=404, detail="本体 not found")
    assert_org_access(auth, o.organization_id)
    ok, errors = validate(o)
    return OntologyValidateResponse(ok=ok, errors=errors)


# ── 本体文件化存储（Markdown 文件 / 文件夹，节点作用域）──────────────────
# 作用域由 query 传 scope_type / scope_id（organization 级 scope_id 为 None）。

def _scope_params(scope_type: str, scope_id: str | None) -> tuple[str, str | None]:
    return scope_type, scope_id or None


@router.get("/organizations/{org_id}/ontology-folders", response_model=list[OntologyFolderRead])
async def list_ontology_folders_endpoint(
    org_id: UUID,
    scope_type: str = Query("organization"),
    scope_id: str | None = Query(None),
    _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    st, sid = _scope_params(scope_type, scope_id)
    return await list_folders(db, org_id, st, sid)


@router.post("/organizations/{org_id}/ontology-folders", response_model=OntologyFolderRead, status_code=201)
async def create_ontology_folder_endpoint(
    org_id: UUID, data: OntologyFolderCreate,
    _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    return await create_folder(db, org_id, data.scope_type, data.scope_id, data.path)


@router.patch("/ontology-folders/{folder_id}", response_model=OntologyFolderRead)
async def rename_ontology_folder_endpoint(
    folder_id: UUID, data: OntologyFolderRename,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    folder = await get_folder(db, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    assert_org_write_access(auth, folder.organization_id)
    return await rename_folder(db, folder, data.path)


@router.delete("/ontology-folders/{folder_id}", status_code=204)
async def delete_ontology_folder_endpoint(
    folder_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    folder = await get_folder(db, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    assert_org_write_access(auth, folder.organization_id)
    await soft_delete_folder(db, folder)


@router.get("/organizations/{org_id}/ontology-files", response_model=list[OntologyFileRead])
async def list_ontology_files_endpoint(
    org_id: UUID,
    scope_type: str = Query("organization"),
    scope_id: str | None = Query(None),
    _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    st, sid = _scope_params(scope_type, scope_id)
    return await list_files(db, org_id, st, sid)


@router.post("/organizations/{org_id}/ontology-files", response_model=OntologyFileRead, status_code=201)
async def upsert_ontology_file_endpoint(
    org_id: UUID, data: OntologyFileCreate,
    _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    return await upsert_file(db, org_id, data.scope_type, data.scope_id, data)


@router.get("/ontology-files/{file_id}", response_model=OntologyFileRead)
async def get_ontology_file_endpoint(
    file_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_access(auth, f.organization_id)
    return f


@router.patch("/ontology-files/{file_id}", response_model=OntologyFileRead)
async def update_ontology_file_endpoint(
    file_id: UUID, data: OntologyFileUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_write_access(auth, f.organization_id)
    return await update_file(db, f, data)


@router.delete("/ontology-files/{file_id}", status_code=204)
async def delete_ontology_file_endpoint(
    file_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_file(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    assert_org_write_access(auth, f.organization_id)
    await soft_delete_file(db, f)
