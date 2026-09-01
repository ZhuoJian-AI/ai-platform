"""Organization service — CRUD for orgs, departments, teams."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.models.department import Department
from app.models.organization import Organization
from app.models.team import Team
from app.schemas.organization import (
    DepartmentCreate,
    DepartmentUpdate,
    OrganizationCreate,
    OrganizationUpdate,
    TeamCreate,
    TeamUpdate,
)
from app.services.memory_lifecycle import (
    ensure_node_memory,
    soft_delete_node_memory,
)
from app.services.workspace_lifecycle import (
    ensure_node_workspace,
    soft_delete_node_workspace,
    sync_node_workspace,
)

# ── Organization ────────────────────────────────────────────────────────

async def create_organization(db: AsyncSession, data: OrganizationCreate) -> Organization:
    org = Organization(**data.model_dump())
    db.add(org)
    await db.flush()
    await ensure_node_workspace(db, org.id, "organization", None, org.name, org.slug)
    await ensure_node_memory(db, org.id, "organization", None, org_name=org.name)
    # 播种内置 DLP 规则作为组织级规则（无全局规则概念；组织管理员可启停）
    from app.services.dlp_rule_service import seed_builtin_dlp_rules
    await seed_builtin_dlp_rules(db, org.id)
    return org


async def list_organizations(db: AsyncSession) -> list[Organization]:
    result = await db.execute(select(Organization).where(Organization.deleted_at.is_(None)))
    return list(result.scalars().all())


async def get_organization(db: AsyncSession, org_id: UUID) -> Organization | None:
    result = await db.execute(
        select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_organization(db: AsyncSession, org: Organization, data: OrganizationUpdate) -> Organization:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(org, field, value)
    await db.flush()
    await db.refresh(org)
    if data.name is not None or data.slug is not None:
        await sync_node_workspace(db, org.id, "organization", None, org.name, org.slug)
        await ensure_node_memory(db, org.id, "organization", None, org_name=org.name)
    return org


async def soft_delete_organization(db: AsyncSession, org: Organization) -> None:
    from datetime import datetime
    org.deleted_at = datetime.now(UTC)
    # 默认组织被删除后不再有效，清除标记（部分唯一索引排除软删除行，
    # 但语义上不应残留 is_default=True 的已删除组织）
    org.is_default = False
    await soft_delete_node_workspace(db, org.id, "organization", None)
    await soft_delete_node_memory(db, org.id, "organization", None)
    await db.flush()


async def get_default_organization(db: AsyncSession) -> Organization | None:
    """返回当前平台默认组织（未软删除）。无则返回 None。"""
    result = await db.execute(
        select(Organization).where(
            Organization.is_default.is_(True),
            Organization.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_organization_by_slug(db: AsyncSession, slug: str) -> Organization | None:
    """按 slug 查询组织（未软删除）。

    用 noload('*') 禁用所有 selectin 关系，避免触发尚未建迁移的关系列
    （如 users.department_id），仅取标量字段。调用方按需访问 .id/.name/.slug 即可。
    """
    result = await db.execute(
        select(Organization).options(noload("*")).where(
            Organization.slug == slug,
            Organization.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_org_id_by_slug(db: AsyncSession, slug: str) -> UUID | None:
    """按 slug 解析组织 id（未软删除）。供组织门户登录解析使用，避免加载整张组织对象
    （及其 selectin 关系）。无则返回 None。"""
    result = await db.execute(
        select(Organization.id).where(
            Organization.slug == slug,
            Organization.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_org_public_by_slug(db: AsyncSession, slug: str) -> tuple[str, str] | None:
    """按 slug 取组织的 (name, slug)（未软删除），供登录页公开展示组织名。
    仅取两列，不加载组织关系。无则返回 None。"""
    result = await db.execute(
        select(Organization.name, Organization.slug).where(
            Organization.slug == slug,
            Organization.deleted_at.is_(None),
        )
    )
    row = result.one_or_none()
    return (row.name, row.slug) if row else None


async def get_org_name_slug_by_id(db: AsyncSession, org_id) -> tuple[str | None, str | None]:
    """按 id 取组织的 (name, slug)；不存在/为空时返回 (None, None)。
    仅取两列，避免 db.get(Organization) 触发 selectin 关系。"""
    if org_id is None:
        return None, None
    result = await db.execute(
        select(Organization.name, Organization.slug).where(Organization.id == org_id)
    )
    row = result.one_or_none()
    return (row.name, row.slug) if row else (None, None)


async def get_dept_name_by_id(db: AsyncSession, dept_id) -> str | None:
    """按 id 取部门名（未软删除）；不存在/为空时返回 None。仅取标量列。"""
    if dept_id is None:
        return None
    result = await db.execute(
        select(Department.name).where(
            Department.id == dept_id, Department.deleted_at.is_(None)
        )
    )
    return result.scalar_one_or_none()


async def get_team_name_by_id(db: AsyncSession, team_id) -> str | None:
    """按 id 取团队名（未软删除）；不存在/为空时返回 None。仅取标量列。"""
    if team_id is None:
        return None
    result = await db.execute(
        select(Team.name).where(Team.id == team_id, Team.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def set_default_organization(db: AsyncSession, org: Organization) -> Organization:
    """将指定组织设为平台默认组织；同时清除其它组织的默认标记。

    依赖迁移 0009 建立的部分唯一索引保证全平台至多一个默认组织，
    但显式清零可避免应用层并发写入触发唯一约束冲突。
    """
    await db.execute(
        Organization.__table__.update()
        .where(Organization.is_default.is_(True))
        .values(is_default=False)
    )
    org.is_default = True
    await db.flush()
    await db.refresh(org)
    return org


# ── Department ──────────────────────────────────────────────────────────

async def create_department(db: AsyncSession, org_id: UUID, data: DepartmentCreate) -> Department:
    if data.parent_id:
        parent = await get_department(db, data.parent_id)
        if parent is None or str(parent.organization_id) != str(org_id):
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="Parent department belongs to another organization")
    dept = Department(organization_id=org_id, **data.model_dump())
    db.add(dept)
    await db.flush()
    await ensure_node_workspace(db, org_id, "department", str(dept.id), dept.name, dept.slug)
    org_name, _ = await get_org_name_slug_by_id(db, org_id)
    await ensure_node_memory(db, org_id, "department", str(dept.id), org_name=org_name, dept_name=dept.name)
    return dept


async def list_departments(db: AsyncSession, org_id: UUID) -> list[Department]:
    result = await db.execute(
        select(Department).where(
            Department.organization_id == org_id, Department.deleted_at.is_(None)
        )
    )
    return list(result.scalars().all())


async def get_department(db: AsyncSession, dept_id: UUID) -> Department | None:
    result = await db.execute(
        select(Department).where(Department.id == dept_id, Department.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_department(db: AsyncSession, dept: Department, data: DepartmentUpdate) -> Department:
    if data.parent_id == dept.id:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Department cannot be its own parent")
    if data.parent_id:
        parent = await get_department(db, data.parent_id)
        if parent is None or str(parent.organization_id) != str(dept.organization_id):
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="Parent department belongs to another organization")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(dept, field, value)
    await db.flush()
    await db.refresh(dept)
    if data.name is not None or data.slug is not None:
        await sync_node_workspace(db, dept.organization_id, "department", str(dept.id), dept.name, dept.slug)
        org_name, _ = await get_org_name_slug_by_id(db, dept.organization_id)
        await ensure_node_memory(
            db, dept.organization_id, "department", str(dept.id),
            org_name=org_name, dept_name=dept.name,
        )
    return dept


async def soft_delete_department(db: AsyncSession, dept: Department) -> None:
    from datetime import datetime
    dept.deleted_at = datetime.now(UTC)
    await soft_delete_node_workspace(db, dept.organization_id, "department", str(dept.id))
    await soft_delete_node_memory(db, dept.organization_id, "department", str(dept.id))
    await db.flush()


# ── Team ────────────────────────────────────────────────────────────────

async def create_team(db: AsyncSession, dept_id: UUID, org_id: UUID, data: TeamCreate) -> Team:
    team = Team(department_id=dept_id, organization_id=org_id, **data.model_dump())
    db.add(team)
    await db.flush()
    await ensure_node_workspace(db, org_id, "team", str(team.id), team.name, str(team.id))
    org_name, _ = await get_org_name_slug_by_id(db, org_id)
    dept_name = await get_dept_name_by_id(db, team.department_id)
    await ensure_node_memory(
        db, org_id, "team", str(team.id),
        org_name=org_name, dept_name=dept_name, team_name=team.name,
    )
    return team


async def list_teams(db: AsyncSession, dept_id: UUID) -> list[Team]:
    result = await db.execute(
        select(Team).where(Team.department_id == dept_id, Team.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_team(db: AsyncSession, team_id: UUID) -> Team | None:
    result = await db.execute(
        select(Team).where(Team.id == team_id, Team.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_team(db: AsyncSession, team: Team, data: TeamUpdate) -> Team:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(team, field, value)
    await db.flush()
    await db.refresh(team)
    if data.name is not None:
        await sync_node_workspace(db, team.organization_id, "team", str(team.id), team.name)
        org_name, _ = await get_org_name_slug_by_id(db, team.organization_id)
        dept_name = await get_dept_name_by_id(db, team.department_id)
        await ensure_node_memory(
            db, team.organization_id, "team", str(team.id),
            org_name=org_name, dept_name=dept_name, team_name=team.name,
        )
    return team


async def soft_delete_team(db: AsyncSession, team: Team) -> None:
    from datetime import datetime
    team.deleted_at = datetime.now(UTC)
    await soft_delete_node_workspace(db, team.organization_id, "team", str(team.id))
    await soft_delete_node_memory(db, team.organization_id, "team", str(team.id))
    await db.flush()
