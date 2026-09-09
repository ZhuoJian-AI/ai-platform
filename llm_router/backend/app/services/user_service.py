"""User service — org-scoped CRUD for end users (members of an organization)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password, verify_password
from app.config import settings
from app.models.enterprise_application import EnterpriseApplicationGrant
from app.models.organization import Organization
from app.models.user import User
from app.schemas.user import UserCreate, UserLoginResponse, UserRead, UserUpdate
from app.services.memory_lifecycle import soft_delete_node_memory
from app.services.memory_service import consolidate_user_memory, upsert_user_profile_memory
from app.services.organization_service import (
    get_dept_name_by_id,
    get_org_name_slug_by_id,
)
from app.services.role_service import BUILTIN_MEMBER, ensure_builtin_roles, replace_user_roles
from app.services.scope_service import validate_user_departments, validate_user_membership
from app.services.workspace_lifecycle import (
    ensure_node_workspace,
    soft_delete_node_workspace,
    sync_node_workspace,
)


def _user_ws_name(user: User) -> str:
    """用户工作空间展示名：优先 display_name，回退 username。"""
    return user.display_name or user.username


def _archived_username(username: str, user_id: UUID) -> str:
    """Release a soft-deleted login name while keeping the tombstone auditable."""
    suffix = f"~deleted~{user_id}"
    return f"{username[: 320 - len(suffix)]}{suffix}"


async def _release_legacy_deleted_username(
    db: AsyncSession,
    org_id: UUID,
    username: str,
) -> None:
    """Repair legacy tombstones that still occupy an organization's username."""
    result = await db.execute(
        select(User)
        .where(
            User.organization_id == org_id,
            User.username == username,
            User.deleted_at.is_not(None),
        )
        .with_for_update()
    )
    deleted_user = result.scalar_one_or_none()
    if deleted_user is None:
        return
    deleted_user.username = _archived_username(username, deleted_user.id)
    await db.flush()


def _normalize_department_ids(
    department_ids: list[UUID] | None,
    primary_department_id: UUID | None,
) -> list[UUID]:
    """Return the user's one organizational department in compatibility-list form."""
    selected = primary_department_id or (department_ids[0] if department_ids else None)
    return [selected] if selected else []


def _create_user_access_token(user: User) -> str:
    """生成组织用户 JWT access token（type=user 以区别于管理员 token）。"""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "username": user.username,
        "role": "member",
        "org": str(user.organization_id),
        "type": "user",
        "auth_epoch": user.auth_epoch,
        "iss": "ai-infra-user",
        "aud": "ai-infra-user-api",
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(hours=24),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


async def _sync_user_profile_memory(db: AsyncSession, user: User) -> None:
    """同步用户个人档案记忆：姓名 / 组织 / 部门。

    新建用户时创建，编辑用户（姓名/部门变更）时更新。组织名取自
    ``get_org_name_slug_by_id``，部门名取自 ``get_dept_name_by_id``。
    """
    org_name, _ = await get_org_name_slug_by_id(db, user.organization_id)
    dept_name = await get_dept_name_by_id(db, user.department_id)
    await upsert_user_profile_memory(
        db,
        user.organization_id,
        str(user.id),
        user.display_name or user.username,
        org_name,
        dept_name,
    )


async def consolidate_user_profile_memory(db: AsyncSession, user: User) -> dict:
    """一次性迁移：把某用户存量多条个人记忆合并为一条 markdown 分节记录。

    供 ``scripts/backfill_user_memory.py`` 调用。运行时增改用户仍走
    ``_sync_user_profile_memory``（分节 upsert，不再产生多行）。
    """
    org_name, _ = await get_org_name_slug_by_id(db, user.organization_id)
    dept_name = await get_dept_name_by_id(db, user.department_id)
    return await consolidate_user_memory(
        db,
        user.organization_id,
        str(user.id),
        user.display_name or user.username,
        org_name,
        dept_name,
    )


async def create_user(
    db: AsyncSession, org_id: UUID, data: UserCreate, *, created_by_admin_id: int | None = None,
) -> User:
    department_ids = _normalize_department_ids(data.department_ids, data.department_id)
    primary_department_id = data.department_id or (department_ids[0] if department_ids else None)
    await validate_user_departments(db, org_id, department_ids)
    await validate_user_membership(db, org_id, primary_department_id)
    # 历史版本软删员工时没有释放登录名，导致列表中已不存在的用户名仍返回 409。
    # 创建前仅修复已软删的同名记录；在职员工的唯一约束保持不变。
    await _release_legacy_deleted_username(db, org_id, data.username)
    user = User(
        organization_id=org_id,
        username=data.username,
        display_name=data.display_name,
        is_active=data.is_active,
        department_id=primary_department_id,
        password_hash=hash_password(data.password),
        must_change_password=True,
    )
    db.add(user)
    await db.flush()
    builtins = await ensure_builtin_roles(db, org_id)
    selected_role_ids = data.role_ids
    if selected_role_ids is None:
        selected_role_ids = [builtins[BUILTIN_MEMBER].id]
    await replace_user_roles(db, user, selected_role_ids)
    await ensure_node_workspace(db, org_id, "user", str(user.id), _user_ws_name(user), str(user.id))
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
    requested_role_ids = values.pop("role_ids", None)
    department_ids_were_set = "department_ids" in data.model_fields_set
    requested_department_ids = values.pop("department_ids", None)
    primary_department_was_set = "department_id" in data.model_fields_set
    if department_ids_were_set:
        requested = _normalize_department_ids(requested_department_ids, None)
        if primary_department_was_set:
            primary_candidate = values.get("department_id")
            next_department_ids = _normalize_department_ids(requested, primary_candidate)
        else:
            current_primary = UUID(str(user.department_id)) if user.department_id else None
            primary_candidate = (
                current_primary if current_primary in requested else (requested[0] if requested else None)
            )
            next_department_ids = _normalize_department_ids(requested, primary_candidate)
        next_department_id = primary_candidate
        values["department_id"] = next_department_id
    elif primary_department_was_set:
        next_department_id = values.get("department_id")
        next_department_ids = _normalize_department_ids([], next_department_id)
    else:
        next_department_id = user.department_id
        next_department_ids = [UUID(value) for value in user.department_ids]
    await validate_user_departments(db, user.organization_id, next_department_ids)
    await validate_user_membership(db, user.organization_id, next_department_id)
    values.pop("role", None)
    for field, value in values.items():
        setattr(user, field, value)
    if password is not None:
        user.password_hash = hash_password(password)
        user.must_change_password = True
    await db.flush()
    await db.refresh(user)
    if requested_role_ids is not None:
        await replace_user_roles(db, user, requested_role_ids)
    if data.username is not None or data.display_name is not None:
        await sync_node_workspace(db, user.organization_id, "user", str(user.id), _user_ws_name(user))

    if {"display_name", "department_id"} & values.keys() or department_ids_were_set:
        await _sync_user_profile_memory(db, user)
    auth_affecting = bool(
        password is not None
        or requested_role_ids is not None
        or department_ids_were_set
        or {"department_id", "is_active"} & values.keys()
    )
    if auth_affecting:
        user.auth_epoch += 1
        await db.flush()
        # ``updated_at`` is populated by the database on UPDATE.  A flush
        # expires that attribute, so returning the ORM object immediately
        # would make response-model serialization perform async I/O outside
        # SQLAlchemy's greenlet context (MissingGreenlet).
        await db.refresh(user)
    return user


async def reset_password(db: AsyncSession, user: User, password: str) -> User:
    """重置用户密码，并强制下次登录改密。"""
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.auth_epoch += 1
    await db.flush()
    await db.refresh(user)
    return user


async def login_user(
    db: AsyncSession, org_id: UUID, username: str, password: str
) -> UserLoginResponse | None:
    """组织用户登录，返回 JWT token 或 None。"""
    result = await db.execute(
        select(User).join(Organization, Organization.id == User.organization_id).where(
            User.organization_id == org_id,
            User.username == username,
            User.deleted_at.is_(None),
            User.is_active.is_(True),
            Organization.deleted_at.is_(None),
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


async def change_own_password(
    db: AsyncSession,
    user: User,
    old_password: str,
    new_password: str,
) -> UserLoginResponse | None:
    """Replace an employee's temporary password and revoke every old grant."""
    if not user.password_hash or not verify_password(old_password, user.password_hash):
        return None
    if verify_password(new_password, user.password_hash):
        raise ValueError("New password must be different from the current password")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.auth_epoch += 1
    await db.flush()
    await db.refresh(user)
    return UserLoginResponse(
        access_token=_create_user_access_token(user),
        must_change_password=False,
        user=UserRead.model_validate(user),
    )


async def soft_delete_user(db: AsyncSession, user: User) -> None:
    deleted_at = datetime.now(UTC)
    # 登录名只要求在职员工唯一。软删记录保留 UUID 后缀供审计，同时释放原登录名。
    user.username = _archived_username(user.username, user.id)
    user.auth_epoch += 1
    user.deleted_at = deleted_at
    await db.execute(
        update(EnterpriseApplicationGrant)
        .where(
            EnterpriseApplicationGrant.organization_id == user.organization_id,
            EnterpriseApplicationGrant.scope_type == "user",
            EnterpriseApplicationGrant.scope_id == str(user.id),
            EnterpriseApplicationGrant.deleted_at.is_(None),
        )
        .values(deleted_at=deleted_at)
    )
    await soft_delete_node_workspace(db, user.organization_id, "user", str(user.id))
    await soft_delete_node_memory(db, user.organization_id, "user", str(user.id))
    await db.flush()
