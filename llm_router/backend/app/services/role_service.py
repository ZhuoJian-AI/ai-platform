"""Organization-scoped role management and effective data-scope resolution."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.department import Department
from app.models.role import Role, RoleDataDepartment, RolePermission, UserRole
from app.models.user import User
from app.schemas.role import RoleCreate, RoleDataScopeReplace, RoleUpdate

BUILTIN_ADMIN = "enterprise_admin"
BUILTIN_MEMBER = "employee"


def _role_options():
    return (
        selectinload(Role.permissions),
        selectinload(Role.data_departments),
    )


async def ensure_builtin_roles(db: AsyncSession, org_id: UUID | str) -> dict[str, Role]:
    rows = list((await db.execute(select(Role).options(*_role_options()).where(
        Role.organization_id == UUID(str(org_id)),
        Role.code.in_([BUILTIN_ADMIN, BUILTIN_MEMBER]),
        Role.deleted_at.is_(None),
    ))).scalars().all())
    by_code = {row.code: row for row in rows}
    defaults = {
        BUILTIN_ADMIN: ("企业管理员", "all", ["*"]),
        BUILTIN_MEMBER: ("普通员工", "self", []),
    }
    for code, (name, data_scope, permissions) in defaults.items():
        if code in by_code:
            continue
        role = Role(
            organization_id=UUID(str(org_id)), name=name, code=code,
            data_scope=data_scope, is_builtin=True, is_active=True,
        )
        db.add(role)
        await db.flush()
        for permission in permissions:
            db.add(RolePermission(role_id=role.id, permission_code=permission))
        by_code[code] = role
    await db.flush()
    return by_code


async def list_roles(db: AsyncSession, org_id: UUID | str) -> list[Role]:
    await ensure_builtin_roles(db, org_id)
    result = await db.execute(select(Role).options(*_role_options()).where(
        Role.organization_id == UUID(str(org_id)), Role.deleted_at.is_(None),
    ).order_by(Role.is_builtin.desc(), Role.name))
    return list(result.scalars().unique().all())


async def get_role(db: AsyncSession, role_id: UUID | str) -> Role | None:
    return (await db.execute(select(Role).options(*_role_options()).where(
        Role.id == UUID(str(role_id)), Role.deleted_at.is_(None),
    ))).scalar_one_or_none()


async def create_role(db: AsyncSession, org_id: UUID, data: RoleCreate) -> Role:
    row = Role(organization_id=org_id, **data.model_dump())
    db.add(row)
    await db.flush()
    return await get_role(db, row.id)  # type: ignore[return-value]


async def update_role(db: AsyncSession, row: Role, data: RoleUpdate) -> Role:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await db.flush()
    return await get_role(db, row.id)  # type: ignore[return-value]


async def delete_role(db: AsyncSession, row: Role) -> None:
    if row.is_builtin:
        raise HTTPException(status_code=422, detail="Built-in roles cannot be deleted")
    row.deleted_at = datetime.now(UTC)
    await db.execute(delete(UserRole).where(UserRole.role_id == row.id))
    await db.flush()


async def replace_permissions(db: AsyncSession, row: Role, codes: list[str]) -> Role:
    if row.is_builtin and row.code == BUILTIN_ADMIN and "*" not in codes:
        raise HTTPException(status_code=422, detail="Enterprise administrator must retain wildcard permission")
    await db.execute(delete(RolePermission).where(RolePermission.role_id == row.id))
    for code in dict.fromkeys(codes):
        db.add(RolePermission(role_id=row.id, permission_code=code))
    await db.flush()
    return await get_role(db, row.id)  # type: ignore[return-value]


async def replace_data_scope(db: AsyncSession, row: Role, data: RoleDataScopeReplace) -> Role:
    department_ids = list(dict.fromkeys(data.department_ids))
    if data.data_scope == "custom_departments" and not department_ids:
        raise HTTPException(status_code=422, detail="Custom data scope requires at least one department")
    if data.data_scope != "custom_departments" and department_ids:
        raise HTTPException(status_code=422, detail="Department ids are only valid for custom data scope")
    if department_ids:
        found = set((await db.execute(select(Department.id).where(
            Department.id.in_(department_ids),
            Department.organization_id == row.organization_id,
            Department.deleted_at.is_(None),
        ))).scalars().all())
        if found != set(department_ids):
            raise HTTPException(status_code=422, detail="A department belongs to another organization")
    row.data_scope = data.data_scope
    await db.execute(delete(RoleDataDepartment).where(RoleDataDepartment.role_id == row.id))
    for department_id in department_ids:
        db.add(RoleDataDepartment(role_id=row.id, department_id=department_id))
    await db.flush()
    return await get_role(db, row.id)  # type: ignore[return-value]


async def replace_user_roles(db: AsyncSession, user: User, role_ids: list[UUID]) -> None:
    normalized = list(dict.fromkeys(role_ids))
    if normalized:
        roles = list((await db.execute(select(Role).where(
            Role.id.in_(normalized), Role.organization_id == user.organization_id,
            Role.is_active.is_(True), Role.deleted_at.is_(None),
        ))).scalars().all())
        if {role.id for role in roles} != set(normalized):
            raise HTTPException(status_code=422, detail="A role is inactive or belongs to another organization")
    await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    for role_id in normalized:
        db.add(UserRole(user_id=user.id, role_id=role_id))
    await db.flush()
    await db.refresh(user, attribute_names=["role_assignments"])


async def ensure_legacy_user_role(db: AsyncSession, user: User) -> None:
    if user.role_assignments:
        return
    builtins = await ensure_builtin_roles(db, user.organization_id)
    selected = builtins[BUILTIN_ADMIN if user.role == "admin" else BUILTIN_MEMBER]
    await replace_user_roles(db, user, [selected.id])


async def rbac_for_user(db: AsyncSession, user: User) -> dict:
    await ensure_legacy_user_role(db, user)
    roles = [
        assignment.role for assignment in user.role_assignments
        if assignment.role.is_active and assignment.role.deleted_at is None
    ]
    permission_codes = sorted({
        permission.permission_code for role in roles for permission in role.permissions
    })
    all_departments = list((await db.execute(select(Department).where(
        Department.organization_id == user.organization_id,
        Department.deleted_at.is_(None),
    ))).scalars().all())
    children: dict[str, set[str]] = {}
    for department in all_departments:
        if department.parent_id:
            children.setdefault(str(department.parent_id), set()).add(str(department.id))

    def descendants(root: str) -> set[str]:
        found: set[str] = set()
        pending = [root]
        while pending:
            current = pending.pop()
            for child in children.get(current, set()):
                if child not in found:
                    found.add(child)
                    pending.append(child)
        return found

    department_ids: set[str] = set()
    unrestricted = False
    own_only = False
    for role in roles:
        if role.data_scope == "all":
            unrestricted = True
        elif role.data_scope == "custom_departments":
            department_ids.update(str(item.department_id) for item in role.data_departments)
        elif role.data_scope == "department" and user.department_id:
            department_ids.add(str(user.department_id))
        elif role.data_scope == "department_and_children" and user.department_id:
            root = str(user.department_id)
            department_ids.add(root)
            department_ids.update(descendants(root))
        elif role.data_scope == "self":
            own_only = True
    return {
        "roles": roles,
        "role_ids": tuple(str(role.id) for role in roles),
        "permission_codes": tuple(permission_codes),
        "effective_data_scopes": {
            "unrestricted": unrestricted,
            "include_self": own_only and not unrestricted,
            "own_only": own_only and not unrestricted and not department_ids,
            "department_ids": tuple(sorted(department_ids)),
        },
    }
