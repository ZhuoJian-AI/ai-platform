"""Versioned Skill package import, lifecycle, scopes, and execution audit APIs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import CurrentAdmin, assert_org_access, require_admin, require_org_access_write
from app.auth.user_auth import CurrentUser, require_user
from app.database import get_db
from app.models.department import Department
from app.models.organization import Organization
from app.models.skill import SkillExecution, SkillFolder, SkillVersion
from app.models.team import Team
from app.schemas.skill import (
    SkillExecutionRead,
    SkillImportRead,
    SkillScopeNode,
    SkillVersionRead,
)
from app.services import skill_import_service, skill_runner_client
from app.services.skill_scope_service import (
    assert_user_can_manage_folder,
    assert_user_can_manage_scope,
    managed_scopes,
    user_can_use_folder,
    validate_scope_target,
)

router = APIRouter()


async def _folder(db: AsyncSession, folder_id: UUID) -> SkillFolder:
    row = await db.get(SkillFolder, folder_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return row


async def _import_response(
    db: AsyncSession, folder: SkillFolder, version: SkillVersion,
) -> SkillImportRead:
    """Reload server-generated/updated fields before Pydantic reads the ORM rows."""
    await db.refresh(folder)
    await db.refresh(folder, attribute_names=["files"])
    await db.refresh(version)
    return SkillImportRead(folder=folder, version=version)


@router.post("/terminal/skills/import", response_model=SkillImportRead, status_code=202)
async def terminal_import_skill(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    scope_type: str = Form("user"),
    scope_id: str | None = Form(None),
    cu: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    sid = cu.id if scope_type == "user" and not scope_id else scope_id
    sid = await assert_user_can_manage_scope(db, cu, scope_type, sid)
    folder, version = await skill_import_service.import_package(
        db, org_id=cu.organization_id, scope_type=scope_type, scope_id=sid,
        upload=file, created_by=cu.id,
    )
    await db.commit()
    if version.install_status == "pending":
        background.add_task(skill_runner_client.install_version, version.id)
    return await _import_response(db, folder, version)


@router.post("/organizations/{org_id}/skill-folders/import", response_model=SkillImportRead, status_code=202)
async def admin_import_skill(
    org_id: UUID,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    scope_type: str = Form("organization"),
    scope_id: str | None = Form(None),
    _: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    sid = await validate_scope_target(db, org_id, scope_type, scope_id)
    folder, version = await skill_import_service.import_package(
        db, org_id=org_id, scope_type=scope_type, scope_id=sid, upload=file, created_by=None,
    )
    await db.commit()
    if version.install_status == "pending":
        background.add_task(skill_runner_client.install_version, version.id)
    return await _import_response(db, folder, version)


@router.get("/terminal/skill-scopes", response_model=list[SkillScopeNode])
async def terminal_skill_scopes(
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    grants = await managed_scopes(db, cu)
    org = await db.get(Organization, cu.organization_id)
    nodes = [SkillScopeNode(
        scope_type="organization", scope_id=None, name=org.name if org else "组织",
        can_import=("organization", None) in grants, can_manage=("organization", None) in grants,
    )]
    department_ids = {sid for st, sid in grants if st == "department" and sid}
    if cu.department_id:
        department_ids.add(cu.department_id)
    departments = list((await db.execute(select(Department).where(
        Department.organization_id == cu.organization_id,
        Department.id.in_([UUID(value) for value in department_ids]) if department_ids else False,
        Department.deleted_at.is_(None),
    ))).scalars().all()) if department_ids else []
    for row in departments:
        key = ("department", str(row.id))
        nodes.append(SkillScopeNode(
            scope_type="department", scope_id=str(row.id), name=row.name,
            can_import=key in grants, can_manage=key in grants,
        ))
    team_ids = {sid for st, sid in grants if st == "team" and sid}
    if cu.team_id:
        team_ids.add(cu.team_id)
    teams = list((await db.execute(select(Team).where(
        Team.organization_id == cu.organization_id,
        Team.id.in_([UUID(value) for value in team_ids]) if team_ids else False,
        Team.deleted_at.is_(None),
    ))).scalars().all()) if team_ids else []
    for row in teams:
        key = ("team", str(row.id))
        nodes.append(SkillScopeNode(
            scope_type="team", scope_id=str(row.id), name=row.name,
            can_import=key in grants, can_manage=key in grants,
        ))
    nodes.append(SkillScopeNode(
        scope_type="user", scope_id=cu.id, name=cu.user.display_name or cu.user.username,
        can_import=True, can_manage=True,
    ))
    return nodes


@router.get("/terminal/skills/{folder_id}/versions", response_model=list[SkillVersionRead])
async def terminal_versions(
    folder_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    folder = await _folder(db, folder_id)
    can_manage = (folder.scope_type, folder.scope_id) in await managed_scopes(db, cu)
    if not user_can_use_folder(cu, folder) and not can_manage:
        raise HTTPException(status_code=404, detail="Skill not found")
    return await skill_import_service.list_versions(db, folder.id)


@router.get("/skill-folders/{folder_id}/versions", response_model=list[SkillVersionRead])
async def admin_versions(
    folder_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    folder = await _folder(db, folder_id)
    assert_org_access(auth, folder.organization_id)
    return await skill_import_service.list_versions(db, folder.id)


@router.post("/terminal/skill-versions/{version_id}/retry", response_model=SkillVersionRead, status_code=202)
async def terminal_retry(
    version_id: UUID, background: BackgroundTasks,
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    version = await db.get(SkillVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Skill version not found")
    folder = await _folder(db, UUID(str(version.skill_folder_id)))
    await assert_user_can_manage_folder(db, cu, folder)
    version.install_status = "pending"
    version.install_error = None
    await db.commit()
    background.add_task(skill_runner_client.install_version, version.id)
    await db.refresh(version)
    return version


@router.post("/terminal/skill-versions/{version_id}/activate", response_model=SkillVersionRead)
async def terminal_activate(
    version_id: UUID, cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    version = await db.get(SkillVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Skill version not found")
    folder = await _folder(db, UUID(str(version.skill_folder_id)))
    await assert_user_can_manage_folder(db, cu, folder)
    await skill_import_service.activate_version(db, folder, version)
    await db.commit()
    await db.refresh(version)
    return version


@router.post("/skill-versions/{version_id}/retry", response_model=SkillVersionRead, status_code=202)
async def admin_retry(
    version_id: UUID, background: BackgroundTasks,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    version = await db.get(SkillVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Skill version not found")
    folder = await _folder(db, UUID(str(version.skill_folder_id)))
    assert_org_access(auth, folder.organization_id)
    version.install_status = "pending"
    version.install_error = None
    await db.commit()
    background.add_task(skill_runner_client.install_version, version.id)
    await db.refresh(version)
    return version


@router.post("/skill-versions/{version_id}/activate", response_model=SkillVersionRead)
async def admin_activate(
    version_id: UUID,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    version = await db.get(SkillVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Skill version not found")
    folder = await _folder(db, UUID(str(version.skill_folder_id)))
    assert_org_access(auth, folder.organization_id)
    await skill_import_service.activate_version(db, folder, version)
    await db.commit()
    await db.refresh(version)
    return version


@router.get("/terminal/skill-executions", response_model=list[SkillExecutionRead])
async def terminal_executions(
    cu: CurrentUser = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    return list((await db.execute(select(SkillExecution).where(
        SkillExecution.organization_id == cu.organization_id,
        SkillExecution.user_id == UUID(cu.id),
    ).order_by(SkillExecution.id.desc()).limit(100))).scalars().all())


@router.get("/organizations/{org_id}/skill-executions", response_model=list[SkillExecutionRead])
async def admin_executions(
    org_id: UUID, _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    return list((await db.execute(select(SkillExecution).where(
        SkillExecution.organization_id == org_id,
    ).order_by(SkillExecution.id.desc()).limit(500))).scalars().all())
