"""Authorization and hierarchy validation for scoped Skill management."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.role import Role
from app.models.skill import SkillFile, SkillFolder, SkillVersion
from app.models.user import User

if TYPE_CHECKING:
    from app.auth.user_auth import CurrentUser

VALID_SCOPE_TYPES = {"organization", "department", "user", "role"}


def _user_department_ids(user: User | CurrentUser) -> set[str]:
    values = {str(value) for value in (getattr(user, "department_ids", ()) or ()) if value}
    primary = getattr(user, "department_id", None)
    if primary:
        values.add(str(primary))
    return values


async def validate_scope_target(
    db: AsyncSession, org_id: UUID | str, scope_type: str, scope_id: str | UUID | None,
) -> str | None:
    """Validate target existence and tenant membership; return normalized string id."""
    if scope_type not in VALID_SCOPE_TYPES:
        raise HTTPException(status_code=422, detail="Invalid scope_type")
    org = str(org_id)
    sid = str(scope_id) if scope_id else None
    if scope_type == "organization":
        if sid:
            raise HTTPException(status_code=422, detail="organization scope_id must be empty")
        return None
    if not sid:
        raise HTTPException(status_code=422, detail=f"{scope_type} scope_id is required")
    model = {"department": Department, "user": User, "role": Role}[scope_type]
    row = (await db.execute(select(model).where(
        model.id == UUID(sid), model.organization_id == UUID(org), model.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=422, detail=f"{scope_type} does not belong to this organization")
    return sid


async def validate_user_membership(
    db: AsyncSession, org_id: UUID | str, department_id: UUID | None,
) -> None:
    dept = None
    if department_id:
        dept = (await db.execute(select(Department).where(
            Department.id == department_id,
            Department.organization_id == UUID(str(org_id)),
            Department.deleted_at.is_(None),
        ))).scalar_one_or_none()
        if dept is None:
            raise HTTPException(status_code=422, detail="Department does not belong to this organization")


async def validate_user_departments(
    db: AsyncSession, org_id: UUID | str, department_ids: list[UUID],
) -> None:
    """Validate every department membership."""
    unique_ids = set(department_ids)
    if unique_ids:
        rows = list((await db.execute(select(Department.id).where(
            Department.id.in_(unique_ids),
            Department.organization_id == UUID(str(org_id)),
            Department.deleted_at.is_(None),
        ))).scalars().all())
        if set(rows) != unique_ids:
            raise HTTPException(status_code=422, detail="A department does not belong to this organization")


async def managed_scopes(db: AsyncSession, cu: CurrentUser) -> set[tuple[str, str | None]]:
    """Return the only scope an employee may manage: their personal Skill scope.

    Organization, role and department Skill packages remain administrator-managed.
    ``db`` stays in the signature for one compatibility release so existing API
    callers do not need a parallel code path.
    """
    del db
    return {("user", str(cu.id))}


async def assert_user_can_manage_scope(
    db: AsyncSession, cu: CurrentUser, scope_type: str, scope_id: str | UUID | None,
) -> str | None:
    sid = await validate_scope_target(db, cu.organization_id, scope_type, scope_id)
    if (scope_type, sid) not in await managed_scopes(db, cu):
        raise HTTPException(status_code=403, detail="No Skill management permission for this scope")
    return sid


async def assert_user_can_manage_folder(db: AsyncSession, cu: CurrentUser, folder: SkillFolder) -> None:
    if str(folder.organization_id) != str(cu.organization_id):
        raise HTTPException(status_code=404, detail="Skill not found")
    await assert_user_can_manage_scope(db, cu, folder.scope_type, folder.scope_id)


def user_can_use_folder(cu: CurrentUser, folder: SkillFolder) -> bool:
    if str(folder.organization_id) != str(cu.organization_id) or folder.deleted_at is not None:
        return False
    if folder.scope_type == "organization":
        return True
    if folder.scope_type == "department":
        return folder.scope_id in _user_department_ids(cu)
    if folder.scope_type == "role":
        return folder.scope_id in set(getattr(cu, "role_ids", ()) or ())
    return folder.scope_type == "user" and folder.scope_id == cu.id


async def assert_bound_skills_visible(
    db: AsyncSession, cu: CurrentUser, skill_ids: list[str], *, require_ready: bool = True,
) -> list[SkillFolder]:
    if not skill_ids:
        return []
    try:
        uuids = [UUID(str(value)) for value in skill_ids]
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid Skill id") from exc
    rows = list((await db.execute(select(SkillFolder).where(
        SkillFolder.id.in_(uuids), SkillFolder.deleted_at.is_(None),
    ))).scalars().all())
    by_id = {str(row.id): row for row in rows}
    ordered: list[SkillFolder] = []
    for raw in skill_ids:
        folder = by_id.get(str(raw))
        if folder is None or not user_can_use_folder(cu, folder):
            raise HTTPException(status_code=403, detail="Skill is not available to this user")
        if not folder.is_active:
            raise HTTPException(status_code=422, detail=f"Skill '{folder.name}' is disabled")
        if require_ready:
            if folder.active_version_id:
                version = await db.get(SkillVersion, folder.active_version_id)
                if version is None or version.install_status != "ready":
                    raise HTTPException(status_code=422, detail=f"Skill '{folder.name}' is not ready")
            else:
                legacy = (await db.execute(select(SkillFile.id).where(
                    SkillFile.skill_folder_id == folder.id,
                    SkillFile.path == "skill.md",
                    SkillFile.deleted_at.is_(None),
                ))).first()
                if legacy is None:
                    raise HTTPException(status_code=422, detail=f"Skill '{folder.name}' is not installed")
        ordered.append(folder)
    return ordered


async def assert_admin_bound_skills(
    db: AsyncSession, org_id: UUID | str, skill_ids: list[str], *, require_ready: bool = True,
) -> list[SkillFolder]:
    if not skill_ids:
        return []
    try:
        uuids = [UUID(str(value)) for value in skill_ids]
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid Skill id") from exc
    rows = list((await db.execute(select(SkillFolder).where(
        SkillFolder.id.in_(uuids), SkillFolder.deleted_at.is_(None),
    ))).scalars().all())
    by_id = {str(row.id): row for row in rows}
    ordered = []
    for value in skill_ids:
        folder = by_id.get(str(value))
        if folder is None or str(folder.organization_id) != str(org_id):
            raise HTTPException(status_code=403, detail="Skill belongs to another organization")
        if not folder.is_active:
            raise HTTPException(status_code=422, detail=f"Skill '{folder.name}' is disabled")
        if require_ready:
            if folder.active_version_id:
                version = await db.get(SkillVersion, folder.active_version_id)
                if version is None or version.install_status != "ready":
                    raise HTTPException(status_code=422, detail=f"Skill '{folder.name}' is not ready")
            else:
                legacy = (await db.execute(select(SkillFile.id).where(
                    SkillFile.skill_folder_id == folder.id,
                    SkillFile.path == "skill.md",
                    SkillFile.deleted_at.is_(None),
                ))).first()
                if legacy is None:
                    raise HTTPException(status_code=422, detail=f"Skill '{folder.name}' is not installed")
        ordered.append(folder)
    return ordered
