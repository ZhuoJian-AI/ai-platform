"""Organization-scoped role management and effective data-scope resolution."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.department import Department
from app.models.enterprise_application import EnterpriseApplicationGrant
from app.models.role import Role, RoleDataDepartment, RolePermission, UserRole
from app.models.user import User
from app.schemas.role import RoleCreate, RoleDataScopeReplace, RoleUpdate

BUILTIN_ADMIN = "enterprise_admin"
BUILTIN_MEMBER = "employee"
BUILTIN_RUNTIME_DEVELOPER = "runtime_developer"
RUNTIME_DEVELOPER_CODE = "zj-runtime-developer"
RUNTIME_DEVELOPER_PERMISSION = "runtime.developer"


def merge_effective_data_scopes(scopes: list[dict]) -> dict:
    """Union already-resolved role scopes without inventing access for an empty set."""
    unrestricted = any(bool(scope.get("unrestricted")) for scope in scopes)
    include_self = any(bool(scope.get("include_self")) for scope in scopes) and not unrestricted
    department_ids = {
        str(department_id) for scope in scopes for department_id in (scope.get("department_ids") or ()) if department_id
    }
    return {
        "unrestricted": unrestricted,
        "include_self": include_self,
        "own_only": include_self and not department_ids,
        "department_ids": tuple(sorted(department_ids)),
    }


async def touch_users_for_role_ids(db: AsyncSession, role_ids: set[str | UUID]) -> None:
    """Invalidate user tokens after a role assignment, scope or permission change."""
    normalized = {UUID(str(role_id)) for role_id in role_ids if role_id}
    if not normalized:
        return
    user_ids = select(UserRole.user_id).where(UserRole.role_id.in_(normalized))
    await db.execute(
        update(User)
        .where(User.id.in_(user_ids))
        .values(
            updated_at=datetime.now(UTC),
            auth_epoch=User.auth_epoch + 1,
        )
    )


def _role_options():
    return (
        selectinload(Role.permissions),
        selectinload(Role.data_departments),
    )


async def ensure_builtin_roles(db: AsyncSession, org_id: UUID | str) -> dict[str, Role]:
    rows = list(
        (
            await db.execute(
                select(Role)
                .options(*_role_options())
                .where(
                    Role.organization_id == UUID(str(org_id)),
                    or_(
                        Role.system_key.in_([
                            BUILTIN_ADMIN,
                            BUILTIN_MEMBER,
                            BUILTIN_RUNTIME_DEVELOPER,
                        ]),
                        Role.code.in_([
                            BUILTIN_ADMIN,
                            BUILTIN_MEMBER,
                            RUNTIME_DEVELOPER_CODE,
                        ]),
                    ),
                    Role.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_key = {
        row.system_key or (
            BUILTIN_RUNTIME_DEVELOPER
            if row.code == RUNTIME_DEVELOPER_CODE
            else row.code
        ): row
        for row in rows
    }
    defaults = {
        BUILTIN_ADMIN: ("企业管理员", BUILTIN_ADMIN, "all", ["*"]),
        BUILTIN_MEMBER: ("普通员工", BUILTIN_MEMBER, "self", []),
        BUILTIN_RUNTIME_DEVELOPER: (
            "系统研发者",
            RUNTIME_DEVELOPER_CODE,
            "all",
            [RUNTIME_DEVELOPER_PERMISSION],
        ),
    }
    for system_key, (name, code, data_scope, permissions) in defaults.items():
        if system_key in by_key:
            # 内置角色是登录与兜底授权的基础设施，不能保持在历史误停用状态。
            role = by_key[system_key]
            role.system_key = system_key
            role.is_active = True
            if system_key == BUILTIN_RUNTIME_DEVELOPER:
                # This role is policy, not customer-authored configuration.
                role.name = name
                role.code = code
                role.description = "系统托管：查看和调试本企业 Runtime 发布的业务系统"
                role.data_scope = data_scope
                role.is_builtin = True
                if set(role.permission_codes) != set(permissions):
                    await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
                    for permission in permissions:
                        db.add(RolePermission(role_id=role.id, permission_code=permission))
            continue
        role = Role(
            organization_id=UUID(str(org_id)),
            name=name,
            code=code,
            system_key=system_key,
            description=(
                "系统托管：查看和调试本企业 Runtime 发布的业务系统"
                if system_key == BUILTIN_RUNTIME_DEVELOPER else None
            ),
            data_scope=data_scope,
            is_builtin=True,
            is_active=True,
        )
        db.add(role)
        await db.flush()
        for permission in permissions:
            db.add(RolePermission(role_id=role.id, permission_code=permission))
        by_key[system_key] = role
    await db.flush()
    return by_key


async def list_roles(db: AsyncSession, org_id: UUID | str) -> list[Role]:
    await ensure_builtin_roles(db, org_id)
    result = await db.execute(
        select(Role)
        .options(*_role_options())
        .where(
            Role.organization_id == UUID(str(org_id)),
            Role.deleted_at.is_(None),
        )
        .order_by(Role.is_builtin.desc(), Role.name)
    )
    return list(result.scalars().unique().all())


async def get_role(db: AsyncSession, role_id: UUID | str) -> Role | None:
    return (
        await db.execute(
            select(Role)
            .options(*_role_options())
            .where(
                Role.id == UUID(str(role_id)),
                Role.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def create_role(db: AsyncSession, org_id: UUID, data: RoleCreate) -> Role:
    row = Role(organization_id=org_id, **data.model_dump())
    db.add(row)
    await db.flush()
    return await get_role(db, row.id)  # type: ignore[return-value]


async def update_role(db: AsyncSession, row: Role, data: RoleUpdate) -> Role:
    if row.system_key == BUILTIN_RUNTIME_DEVELOPER and data.model_fields_set:
        raise HTTPException(status_code=422, detail="系统研发者角色由平台托管，只能绑定或解绑员工")
    active_changed = "is_active" in data.model_fields_set and data.is_active != row.is_active
    if data.is_active is False and row.is_active:
        if row.is_builtin:
            raise HTTPException(status_code=422, detail="内置角色不能停用")
        active_user_count = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(UserRole)
                    .join(User, User.id == UserRole.user_id)
                    .where(
                        UserRole.role_id == row.id,
                        User.deleted_at.is_(None),
                        User.is_active.is_(True),
                    )
                )
            ).scalar_one()
        )
        if active_user_count:
            raise HTTPException(
                status_code=409,
                detail=f"该角色仍分配给 {active_user_count} 名在职员工，请先移除员工角色后再停用",
            )
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    if active_changed:
        await touch_users_for_role_ids(db, {row.id})
    await db.flush()
    return await get_role(db, row.id)  # type: ignore[return-value]


async def delete_role(db: AsyncSession, row: Role) -> None:
    if row.is_builtin:
        raise HTTPException(status_code=422, detail="Built-in roles cannot be deleted")
    deleted_at = datetime.now(UTC)
    row.deleted_at = deleted_at
    await touch_users_for_role_ids(db, {row.id})
    await db.execute(
        update(EnterpriseApplicationGrant)
        .where(
            EnterpriseApplicationGrant.organization_id == row.organization_id,
            EnterpriseApplicationGrant.scope_type == "role",
            EnterpriseApplicationGrant.scope_id == str(row.id),
            EnterpriseApplicationGrant.deleted_at.is_(None),
        )
        .values(deleted_at=deleted_at)
    )
    await db.execute(delete(UserRole).where(UserRole.role_id == row.id))
    await db.flush()


async def replace_permissions(db: AsyncSession, row: Role, codes: list[str]) -> Role:
    if row.system_key == BUILTIN_RUNTIME_DEVELOPER:
        raise HTTPException(status_code=422, detail="系统研发者角色权限由平台托管")
    if row.is_builtin and row.code == BUILTIN_ADMIN and "*" not in codes:
        raise HTTPException(status_code=422, detail="Enterprise administrator must retain wildcard permission")
    await db.execute(delete(RolePermission).where(RolePermission.role_id == row.id))
    for code in dict.fromkeys(codes):
        db.add(RolePermission(role_id=row.id, permission_code=code))
    await touch_users_for_role_ids(db, {row.id})
    await db.flush()
    return await get_role(db, row.id)  # type: ignore[return-value]


async def replace_data_scope(db: AsyncSession, row: Role, data: RoleDataScopeReplace) -> Role:
    if row.system_key == BUILTIN_RUNTIME_DEVELOPER:
        raise HTTPException(status_code=422, detail="系统研发者角色数据范围由平台托管")
    department_ids = list(dict.fromkeys(data.department_ids))
    if data.data_scope == "custom_departments" and not department_ids:
        raise HTTPException(status_code=422, detail="Custom data scope requires at least one department")
    if data.data_scope != "custom_departments" and department_ids:
        raise HTTPException(status_code=422, detail="Department ids are only valid for custom data scope")
    if department_ids:
        found = set(
            (
                await db.execute(
                    select(Department.id).where(
                        Department.id.in_(department_ids),
                        Department.organization_id == row.organization_id,
                        Department.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if found != set(department_ids):
            raise HTTPException(status_code=422, detail="A department belongs to another organization")
    row.data_scope = data.data_scope
    await db.execute(delete(RoleDataDepartment).where(RoleDataDepartment.role_id == row.id))
    for department_id in department_ids:
        db.add(RoleDataDepartment(role_id=row.id, department_id=department_id))
    await touch_users_for_role_ids(db, {row.id})
    await db.flush()
    return await get_role(db, row.id)  # type: ignore[return-value]


async def replace_user_roles(
    db: AsyncSession,
    user: User,
    role_ids: list[UUID],
    *,
    invalidate_tokens: bool = True,
) -> None:
    normalized = list(dict.fromkeys(role_ids))
    if normalized:
        roles = list(
            (
                await db.execute(
                    select(Role).where(
                        Role.id.in_(normalized),
                        Role.organization_id == user.organization_id,
                        Role.is_active.is_(True),
                        Role.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if {role.id for role in roles} != set(normalized):
            raise HTTPException(status_code=422, detail="A role is inactive or belongs to another organization")
    await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    for role_id in normalized:
        db.add(UserRole(user_id=user.id, role_id=role_id))
    if invalidate_tokens:
        user.updated_at = datetime.now(UTC)
        user.auth_epoch += 1
    await db.flush()
    await db.refresh(user, attribute_names=["role_assignments"])


async def ensure_legacy_user_role(db: AsyncSession, user: User) -> None:
    if user.role_assignments:
        return
    builtins = await ensure_builtin_roles(db, user.organization_id)
    selected = builtins[BUILTIN_MEMBER]
    # Compatibility repair for a pre-RBAC employee; administrators live in
    # the independent Admin model and are never inferred from an employee row.
    await replace_user_roles(db, user, [selected.id], invalidate_tokens=False)


async def rbac_for_user(db: AsyncSession, user: User) -> dict:
    await ensure_legacy_user_role(db, user)
    roles = [
        assignment.role
        for assignment in user.role_assignments
        if assignment.role.is_active and assignment.role.deleted_at is None
    ]
    permission_codes = sorted({permission.permission_code for role in roles for permission in role.permissions})
    all_departments = list(
        (
            await db.execute(
                select(Department).where(
                    Department.organization_id == user.organization_id,
                    Department.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
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

    role_data_scopes: dict[str, dict] = {}
    for role in roles:
        department_ids: set[str] = set()
        unrestricted = False
        include_self = False
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
            include_self = True
        role_data_scopes[str(role.id)] = {
            "unrestricted": unrestricted,
            "include_self": include_self and not unrestricted,
            "own_only": include_self and not unrestricted and not department_ids,
            "department_ids": tuple(sorted(department_ids)),
        }
    effective_data_scopes = merge_effective_data_scopes(list(role_data_scopes.values()))
    return {
        "roles": roles,
        "role_ids": tuple(str(role.id) for role in roles),
        "permission_codes": tuple(permission_codes),
        "effective_data_scopes": effective_data_scopes,
        "role_data_scopes": role_data_scopes,
    }
