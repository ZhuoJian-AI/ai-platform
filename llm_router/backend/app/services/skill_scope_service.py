"""Authorization and hierarchy validation for scoped Skill management."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.skill import ScopeManagerAssignment, SkillFile, SkillFolder, SkillVersion
from app.models.team import Team
from app.models.user import User
from app.schemas.user import ManagerScopeGrant

if TYPE_CHECKING:
    from app.auth.user_auth import CurrentUser

VALID_SCOPE_TYPES = {"organization", "department", "team", "user"}


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
    model = {"department": Department, "team": Team, "user": User}[scope_type]
    row = (await db.execute(select(model).where(
        model.id == UUID(sid), model.organization_id == UUID(org), model.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=422, detail=f"{scope_type} does not belong to this organization")
    return sid


async def validate_user_membership(
    db: AsyncSession, org_id: UUID | str, department_id: UUID | None, team_id: UUID | None,
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
    if team_id:
        team = (await db.execute(select(Team).where(
            Team.id == team_id,
            Team.organization_id == UUID(str(org_id)),
            Team.deleted_at.is_(None),
        ))).scalar_one_or_none()
        if team is None:
            raise HTTPException(status_code=422, detail="Team does not belong to this organization")
        if department_id is None or str(team.department_id) != str(department_id):
            raise HTTPException(status_code=422, detail="Team must belong to the selected department")


async def replace_manager_grants(
    db: AsyncSession, user: User, grants: list[ManagerScopeGrant], created_by_admin_id: int | None = None,
) -> None:
    if user.role == "admin" or not user.is_active or user.deleted_at is not None:
        if grants:
            raise HTTPException(status_code=422, detail="Only active terminal members can be scope managers")
    normalized: set[tuple[str, str]] = set()
    for grant in grants:
        sid = await validate_scope_target(db, user.organization_id, grant.scope_type, grant.scope_id)
        if grant.scope_type == "department" and str(user.department_id or "") != sid:
            raise HTTPException(status_code=422, detail="Department manager must belong to that department")
        if grant.scope_type == "team" and str(user.team_id or "") != sid:
            raise HTTPException(status_code=422, detail="Team manager must belong to that team")
        normalized.add((grant.scope_type, sid or ""))

    rows = list((await db.execute(select(ScopeManagerAssignment).where(
        ScopeManagerAssignment.user_id == user.id,
    ))).scalars().all())
    current = {(row.scope_type, row.scope_id): row for row in rows}
    now = datetime.now(UTC)
    for key, row in current.items():
        row.deleted_at = None if key in normalized else now
    for scope_type, sid in normalized - current.keys():
        db.add(ScopeManagerAssignment(
            organization_id=user.organization_id,
            user_id=user.id,
            scope_type=scope_type,
            scope_id=sid,
            created_by_admin_id=created_by_admin_id,
        ))
    await db.flush()
    await db.refresh(user, attribute_names=["manager_assignments"])


async def managed_scopes(db: AsyncSession, cu: CurrentUser) -> set[tuple[str, str | None]]:
    rows = list((await db.execute(select(ScopeManagerAssignment).where(
        ScopeManagerAssignment.user_id == UUID(str(cu.id)),
        ScopeManagerAssignment.organization_id == cu.organization_id,
        ScopeManagerAssignment.deleted_at.is_(None),
    ))).scalars().all())
    scopes: set[tuple[str, str | None]] = {("user", str(cu.id))}
    for row in rows:
        scopes.add((row.scope_type, row.scope_id))
        if row.scope_type == "department":
            teams = list((await db.execute(select(Team).where(
                Team.department_id == UUID(row.scope_id), Team.deleted_at.is_(None),
            ))).scalars().all())
            scopes.update(("team", str(team.id)) for team in teams)
    return scopes


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
        return bool(cu.department_id and folder.scope_id == cu.department_id)
    if folder.scope_type == "team":
        return bool(cu.team_id and folder.scope_id == cu.team_id)
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
