"""Skill CRUD + test API（旧 definition 模型 dormant）+ 技能文件夹化存储 API。"""

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
from app.schemas.skill import (
    SkillCreate,
    SkillFileCreate,
    SkillFileRead,
    SkillFileReadMeta,
    SkillFileUpdate,
    SkillFolderCreate,
    SkillFolderRead,
    SkillFolderUpdate,
    SkillRead,
    SkillTestRequest,
    SkillUpdate,
)
from app.services.connector_service import get_endpoint
from app.services.skill_scope_service import validate_scope_target
from app.services.skill_service import (
    create_skill,
    get_skill,
    list_skills,
    soft_delete_skill,
    update_skill,
)
from app.services.skill_store_service import (
    create_folder as create_skill_folder,
)
from app.services.skill_store_service import (
    get_file as get_skill_file,
)
from app.services.skill_store_service import (
    get_folder as get_skill_folder,
)
from app.services.skill_store_service import (
    list_files as list_skill_files,
)
from app.services.skill_store_service import (
    list_folders as list_skill_folders,
)
from app.services.skill_store_service import (
    soft_delete_file as soft_delete_skill_file,
)
from app.services.skill_store_service import (
    soft_delete_folder as soft_delete_skill_folder,
)
from app.services.skill_store_service import (
    update_file as update_skill_file,
)
from app.services.skill_store_service import (
    update_folder as update_skill_folder,
)
from app.services.skill_store_service import (
    upsert_file as upsert_skill_file,
)
from app.tools.executor import execute_endpoint

router = APIRouter()


@router.post("/organizations/{org_id}/skills", response_model=SkillRead, status_code=201)
async def create_skill_endpoint(
    org_id: UUID, data: SkillCreate,
    _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    try:
        return await create_skill(db, org_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists")


@router.get("/organizations/{org_id}/skills", response_model=list[SkillRead])
async def list_skills_endpoint(
    org_id: UUID, _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    return await list_skills(db, org_id)


@router.get("/skills/{skill_id}", response_model=SkillRead)
async def get_skill_endpoint(
    skill_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    s = await get_skill(db, skill_id)
    if not s:
        raise HTTPException(status_code=404, detail="Skill not found")
    assert_org_access(auth, s.organization_id)
    return s


@router.patch("/skills/{skill_id}", response_model=SkillRead)
async def update_skill_endpoint(
    skill_id: UUID, data: SkillUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    s = await get_skill(db, skill_id)
    if not s:
        raise HTTPException(status_code=404, detail="Skill not found")
    assert_org_write_access(auth, s.organization_id)
    return await update_skill(db, s, data)


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill_endpoint(
    skill_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    s = await get_skill(db, skill_id)
    if not s:
        raise HTTPException(status_code=404, detail="Skill not found")
    assert_org_write_access(auth, s.organization_id)
    await soft_delete_skill(db, s)


@router.post("/skills/{skill_id}/test")
async def test_skill_endpoint(
    skill_id: UUID, data: SkillTestRequest,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    """测试技能：取第一个绑定端点执行调用。"""
    s = await get_skill(db, skill_id)
    if not s:
        raise HTTPException(status_code=404, detail="Skill not found")
    assert_org_write_access(auth, s.organization_id)
    if not s.bound_endpoint_ids:
        raise HTTPException(status_code=400, detail="Skill has no bound endpoint")
    ep_id = s.bound_endpoint_ids[0]
    ep = await get_endpoint(db, UUID(ep_id))
    if not ep:
        raise HTTPException(status_code=404, detail="Bound endpoint not found")
    from app.services.connector_service import get_connector
    conn = await get_connector(db, ep.connector_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connector not found")
    result = await execute_endpoint(
        db, org_id=s.organization_id, connector=conn, endpoint=ep,
        params=data.params, skill_id=s.id,
    )
    return {
        "status_code": result.status_code,
        "latency_ms": result.latency_ms,
        "body": result.body,
        "error": result.error,
    }


# ── 技能文件夹化存储（SkillFolder + SkillFile，节点作用域）──────────────

def _scope_params(scope_type: str, scope_id: str | None) -> tuple[str, str | None]:
    return scope_type, scope_id or None


@router.get("/organizations/{org_id}/skill-folders", response_model=list[SkillFolderRead])
async def list_skill_folders_endpoint(
    org_id: UUID,
    scope_type: str = Query("organization"),
    scope_id: str | None = Query(None),
    _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    st, sid = _scope_params(scope_type, scope_id)
    return await list_skill_folders(db, org_id, st, sid)


@router.post("/organizations/{org_id}/skill-folders", response_model=SkillFolderRead, status_code=201)
async def create_skill_folder_endpoint(
    org_id: UUID, data: SkillFolderCreate,
    _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    normalized_scope_id = await validate_scope_target(db, org_id, data.scope_type, data.scope_id)
    data = data.model_copy(update={"scope_id": normalized_scope_id})
    try:
        return await create_skill_folder(db, org_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists in this scope")


@router.patch("/skill-folders/{folder_id}", response_model=SkillFolderRead)
async def update_skill_folder_endpoint(
    folder_id: UUID, data: SkillFolderUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_skill_folder(db, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Skill folder not found")
    assert_org_write_access(auth, f.organization_id)
    try:
        return await update_skill_folder(db, f, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Slug already exists in this scope")


@router.delete("/skill-folders/{folder_id}", status_code=204)
async def delete_skill_folder_endpoint(
    folder_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_skill_folder(db, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Skill folder not found")
    assert_org_write_access(auth, f.organization_id)
    await soft_delete_skill_folder(db, f)


@router.get("/skill-folders/{folder_id}/files", response_model=list[SkillFileReadMeta])
async def list_skill_files_endpoint(
    folder_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_skill_folder(db, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Skill folder not found")
    assert_org_access(auth, f.organization_id)
    return await list_skill_files(db, f.id)


@router.post("/skill-folders/{folder_id}/files", response_model=SkillFileRead, status_code=201)
async def upsert_skill_file_endpoint(
    folder_id: UUID, data: SkillFileCreate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    f = await get_skill_folder(db, folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Skill folder not found")
    assert_org_write_access(auth, f.organization_id)
    if f.active_version_id:
        raise HTTPException(status_code=409, detail="Versioned Skill files are immutable; import a new package version")
    return await upsert_skill_file(db, f, data)


@router.get("/skill-files/{file_id}", response_model=SkillFileRead)
async def get_skill_file_endpoint(
    file_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    fl = await get_skill_file(db, file_id)
    if not fl:
        raise HTTPException(status_code=404, detail="Skill file not found")
    f = await get_skill_folder(db, fl.skill_folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Skill folder not found")
    assert_org_access(auth, f.organization_id)
    return fl


@router.patch("/skill-files/{file_id}", response_model=SkillFileRead)
async def update_skill_file_endpoint(
    file_id: UUID, data: SkillFileUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    fl = await get_skill_file(db, file_id)
    if not fl:
        raise HTTPException(status_code=404, detail="Skill file not found")
    f = await get_skill_folder(db, fl.skill_folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Skill folder not found")
    assert_org_write_access(auth, f.organization_id)
    if f.active_version_id:
        raise HTTPException(status_code=409, detail="Versioned Skill files are immutable; import a new package version")
    return await update_skill_file(db, fl, data)


@router.delete("/skill-files/{file_id}", status_code=204)
async def delete_skill_file_endpoint(
    file_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    fl = await get_skill_file(db, file_id)
    if not fl:
        raise HTTPException(status_code=404, detail="Skill file not found")
    f = await get_skill_folder(db, fl.skill_folder_id)
    if not f:
        raise HTTPException(status_code=404, detail="Skill folder not found")
    assert_org_write_access(auth, f.organization_id)
    if f.active_version_id:
        raise HTTPException(status_code=409, detail="Versioned Skill files are immutable; import a new package version")
    await soft_delete_skill_file(db, fl)
