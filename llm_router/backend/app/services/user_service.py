"""User service — org-scoped CRUD for end users (members of an organization)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password, verify_password
from app.config import settings
from app.models.user import User
from app.schemas.user import UserCreate, UserLoginResponse, UserRead, UserUpdate
from app.services.memory_lifecycle import soft_delete_node_memory
from app.services.memory_service import consolidate_user_memory, upsert_user_profile_memory
from app.services.organization_service import (
    get_dept_name_by_id,
    get_org_name_slug_by_id,
    get_team_name_by_id,
)
from app.services.skill_scope_service import replace_manager_grants, validate_user_membership
from app.services.workspace_lifecycle import (
    ensure_node_workspace,
    soft_delete_node_workspace,
    sync_node_workspace,
)


def _user_ws_name(user: User) -> str:
    """用户工作空间展示名：优先 display_name，回退 username。"""
    return user.display_name or user.username


def _create_user_access_token(user: User) -> str:
    """生成组织用户 JWT access token（type=user 以区别于管理员 token）。"""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "org": str(user.organization_id),
        "type": "user",
        "iat": now,
        "exp": now + timedelta(hours=24),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


async def _sync_user_profile_memory(db: AsyncSession, user: User) -> None:
    """同步用户个人档案记忆：姓名 / 组织 / 部门 / 团队。

    新建用户时创建，编辑用户（姓名/部门/团队变更）时更新。组织名取自
    ``get_org_name_slug_by_id``，部门/团队名取自 ``get_dept_name_by_id`` /
    ``get_team_name_by_id``，均为标量查询，避免触发 selectin 关系。
    """
    org_name, _ = await get_org_name_slug_by_id(db, user.organization_id)
    dept_name = await get_dept_name_by_id(db, user.department_id)
    team_name = await get_team_name_by_id(db, user.team_id)
    await upsert_user_profile_memory(
        db,
        user.organization_id,
        str(user.id),
        user.display_name or user.username,
        org_name,
        dept_name,
        team_name,
    )


async def consolidate_user_profile_memory(db: AsyncSession, user: User) -> dict:
    """一次性迁移：把某用户存量多条个人记忆合并为一条 markdown 分节记录。

    供 ``scripts/backfill_user_memory.py`` 调用。运行时增改用户仍走
    ``_sync_user_profile_memory``（分节 upsert，不再产生多行）。
    """
    org_name, _ = await get_org_name_slug_by_id(db, user.organization_id)
    dept_name = await get_dept_name_by_id(db, user.department_id)
    team_name = await get_team_name_by_id(db, user.team_id)
    return await consolidate_user_memory(
        db,
        user.organization_id,
        str(user.id),
        user.display_name or user.username,
        org_name,
        dept_name,
        team_name,
    )


async def create_user(
    db: AsyncSession, org_id: UUID, data: UserCreate, *, created_by_admin_id: int | None = None,
) -> User:
    await validate_user_membership(db, org_id, data.department_id, data.team_id)
    user = User(
        organization_id=org_id,
        username=data.username,
        display_name=data.display_name,
        role=data.role,
        is_active=data.is_active,
        department_id=data.department_id,
        team_id=data.team_id,
        password_hash=hash_password(data.password),
        must_change_password=True,
    )
    db.add(user)
    await db.flush()
    await replace_manager_grants(db, user, data.manager_scopes, created_by_admin_id)
    # 组织管理员（role='admin'）非终端用户：不持有工作空间，也不沉淀个人档案记忆。
    if user.role != "admin":
        await ensure_node_workspace(db, org_id, "user", str(user.id), _user_ws_name(user), str(user.id))
        # 为终端用户创建个人档案记忆（姓名/组织/部门/团队默认存入）
        await _sync_user_profile_memory(db, user)
    return user


async def list_users(db: AsyncSession, org_id: UUID) -> list[User]:
    result = await db.execute(
        select(User).where(User.organization_id == org_id, User.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_user(db: AsyncSession, user_id: UUID) -> User | None:
    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_user(
    db: AsyncSession, user: User, data: UserUpdate, *, created_by_admin_id: int | None = None,
) -> User:
    values = data.model_dump(exclude_unset=True)
    # password 不是列，需单独哈希处理
    password = values.pop("password", None)
    requested_manager_scopes = values.pop("manager_scopes", None)
    next_department_id = values.get("department_id", user.department_id)
    next_team_id = values.get("team_id", user.team_id)
    await validate_user_membership(db, user.organization_id, next_department_id, next_team_id)
    role_changed = "role" in values
    prev_role = user.role
    for field, value in values.items():
        setattr(user, field, value)
    if password is not None:
        user.password_hash = hash_password(password)
        user.must_change_password = True
    await db.flush()
    await db.refresh(user)

    if requested_manager_scopes is not None:
        await replace_manager_grants(db, user, requested_manager_scopes, created_by_admin_id)
    elif role_changed or {"department_id", "team_id", "is_active"} & values.keys():
        # 调岗/停用/角色变化时只保留仍与新成员关系一致的授权。
        surviving = []
        for grant in user.manager_assignments or []:
            if grant.deleted_at is not None:
                continue
            if grant.scope_type == "department" and str(user.department_id or "") == grant.scope_id:
                surviving.append({"scope_type": "department", "scope_id": grant.scope_id})
            if grant.scope_type == "team" and str(user.team_id or "") == grant.scope_id:
                surviving.append({"scope_type": "team", "scope_id": grant.scope_id})
        from app.schemas.user import ManagerScopeGrant
        await replace_manager_grants(
            db, user, [ManagerScopeGrant(**item) for item in surviving], created_by_admin_id,
        )

    is_admin = user.role == "admin"
    # 工作空间：组织管理员不持有。角色变更时按新角色补建/移除；仅普通用户重命名时同步。
    if role_changed:
        if is_admin:
            await soft_delete_node_workspace(db, user.organization_id, "user", str(user.id))
            # 降为组织管理员：同步软删其个人记忆
            await soft_delete_node_memory(db, user.organization_id, "user", str(user.id))
        else:
            await ensure_node_workspace(
                db, user.organization_id, "user", str(user.id), _user_ws_name(user), str(user.id)
            )
    elif not is_admin and (data.username is not None or data.display_name is not None):
        await sync_node_workspace(db, user.organization_id, "user", str(user.id), _user_ws_name(user))

    # 个人档案记忆：仅终端用户（非管理员）。姓名/部门/团队变更，或由管理员降为普通用户时同步。
    if not is_admin and (
        {"display_name", "department_id", "team_id"} & values.keys()
        or (role_changed and prev_role == "admin")
    ):
        await _sync_user_profile_memory(db, user)
    return user


async def reset_password(db: AsyncSession, user: User, password: str) -> User:
    """重置用户密码，并强制下次登录改密。"""
    user.password_hash = hash_password(password)
    user.must_change_password = True
    await db.flush()
    await db.refresh(user)
    return user


async def login_user(
    db: AsyncSession, org_id: UUID, username: str, password: str
) -> UserLoginResponse | None:
    """组织用户登录，返回 JWT token 或 None。"""
    result = await db.execute(
        select(User).where(
            User.organization_id == org_id,
            User.username == username,
            User.deleted_at.is_(None),
            User.is_active.is_(True),
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not user.password_hash or not verify_password(password, user.password_hash):
        return None

    token = _create_user_access_token(user)
    return UserLoginResponse(
        access_token=token,
        must_change_password=user.must_change_password,
        user=UserRead.model_validate(user),
    )


async def soft_delete_user(db: AsyncSession, user: User) -> None:
    user.deleted_at = datetime.now(UTC)
    await replace_manager_grants(db, user, [])
    # 组织管理员本就不持有工作空间/个人记忆，跳过；仅普通用户软删其绑定工作空间与个人记忆。
    if user.role != "admin":
        await soft_delete_node_workspace(db, user.organization_id, "user", str(user.id))
        await soft_delete_node_memory(db, user.organization_id, "user", str(user.id))
    await db.flush()
