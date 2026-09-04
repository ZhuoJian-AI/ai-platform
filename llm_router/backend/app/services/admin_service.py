"""Admin authentication service — JWT tokens, password hashing, login."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password, verify_password
from app.config import settings
from app.models.admin import Admin
from app.schemas.admin import AdminCreate, AdminRead, AdminUpdate, LoginResponse

PLATFORM_ROLE = "platform_super_admin"
ENTERPRISE_ROLE = "enterprise_admin"
ADMIN_ROLES = frozenset({PLATFORM_ROLE, ENTERPRISE_ROLE})

# 向后兼容的薄封装（历史调用方仍可用私有名）
_hash_password = hash_password
_verify_password = verify_password


def create_access_token(admin: Admin) -> str:
    """生成 JWT access token。"""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(admin.id),
        "username": admin.username,
        "role": admin.role,
        "auth_epoch": admin.auth_epoch,
        "type": "admin",
        "iss": "ai-infra-admin",
        "aud": "ai-infra-admin-api",
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(hours=24),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any] | None:
    """解码并验证 JWT token。返回 payload 或 None。"""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            audience="ai-infra-admin-api",
            issuer="ai-infra-admin",
            options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
        )
        if payload.get("type") != "admin":
            return None
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


async def login(
    db: AsyncSession,
    username: str,
    password: str,
    slug: str | None = None,
) -> LoginResponse | None:
    """管理员登录，返回 JWT token 或 None。

    - slug 非空：仅匹配该组织的 enterprise_admin。
    - slug 为空：仅匹配 platform_super_admin。
    """
    stmt = select(Admin).where(Admin.username == username, Admin.is_active.is_(True))
    if slug:
        # 延迟导入避免循环依赖
        from app.services.organization_service import get_org_id_by_slug

        org_id = await get_org_id_by_slug(db, slug)
        if org_id is None:
            return None
        stmt = stmt.where(Admin.organization_id == org_id, Admin.role == ENTERPRISE_ROLE)
    else:
        stmt = stmt.where(Admin.organization_id.is_(None), Admin.role == PLATFORM_ROLE)

    result = await db.execute(stmt)
    admin = result.scalar_one_or_none()
    if admin is None or not _verify_password(password, admin.password_hash):
        return None

    token = create_access_token(admin)
    return LoginResponse(
        access_token=token,
        must_change_password=False,
        admin=await admin_read_with_org(db, admin),
    )


def _valid_role_organization(role: str, organization_id: UUID | None) -> bool:
    return (role == PLATFORM_ROLE and organization_id is None) or (
        role == ENTERPRISE_ROLE and organization_id is not None
    )


def _assert_valid_actor(actor: Admin) -> None:
    if not actor.is_active or not _valid_role_organization(actor.role, actor.organization_id):
        raise HTTPException(status_code=403, detail="Administrator role is invalid")


def assert_can_manage_admin(actor: Admin, target: Admin) -> None:
    """Apply administrator-manager isolation without leaking cross-tenant accounts."""
    _assert_valid_actor(actor)
    if actor.role == PLATFORM_ROLE:
        return
    if (
        target.role == ENTERPRISE_ROLE
        and actor.organization_id is not None
        and target.organization_id == actor.organization_id
    ):
        return
    raise HTTPException(status_code=404, detail="Admin not found")


async def create_admin(db: AsyncSession, data: AdminCreate, *, actor: Admin) -> Admin:
    """Create one of the two administrator types within the actor's authority."""
    _assert_valid_actor(actor)
    if not _valid_role_organization(data.role, data.organization_id):
        raise HTTPException(status_code=422, detail="Administrator role and organization do not match")
    if actor.role == ENTERPRISE_ROLE and (
        data.role != ENTERPRISE_ROLE or data.organization_id != actor.organization_id
    ):
        raise HTTPException(status_code=403, detail="Enterprise admins can only create admins in their organization")
    admin = Admin(
        username=data.username,
        password_hash=_hash_password(data.password),
        display_name=data.display_name,
        role=data.role,
        organization_id=data.organization_id,
        must_change_password=False,
    )
    db.add(admin)
    await db.flush()
    return admin


async def ensure_super_admin(db: AsyncSession) -> Admin:
    """Return the existing platform administrator; never create a default."""
    result = await db.execute(
        select(Admin)
        .where(
            Admin.role == PLATFORM_ROLE,
            Admin.organization_id.is_(None),
            Admin.is_active.is_(True),
        )
        .order_by(Admin.id)
        .limit(1)
    )
    admin = result.scalar_one_or_none()
    if admin is not None:
        return admin
    raise RuntimeError(
        "No active platform administrator. Run scripts/bootstrap_platform_admin.py on the server."
    )


async def bootstrap_platform_admin(db: AsyncSession, *, username: str, password: str) -> Admin:
    """Create the first platform administrator from an interactive server task."""
    username = username.strip()
    if not username or len(username) > 320:
        raise ValueError("username must contain 1 to 320 characters")
    if not password or len(password) > 128:
        raise ValueError("initial password must contain 1 to 128 characters")
    existing = (
        await db.execute(
            select(Admin.id)
            .where(
                Admin.role == PLATFORM_ROLE,
                Admin.organization_id.is_(None),
                Admin.is_active.is_(True),
            )
            .limit(1)
            .with_for_update()
        )
    ).first()
    if existing is not None:
        raise RuntimeError("An active platform administrator already exists; bootstrap is closed")
    admin = Admin(
        username=username,
        password_hash=_hash_password(password),
        display_name=username,
        role=PLATFORM_ROLE,
        must_change_password=False,
    )
    db.add(admin)
    await db.flush()
    return admin


async def list_admins(db: AsyncSession, *, actor: Admin) -> list[Admin]:
    _assert_valid_actor(actor)
    stmt = select(Admin).where(
        or_(
            (Admin.role == PLATFORM_ROLE) & Admin.organization_id.is_(None),
            (Admin.role == ENTERPRISE_ROLE) & Admin.organization_id.is_not(None),
        )
    )
    if actor.role == ENTERPRISE_ROLE:
        stmt = stmt.where(
            Admin.role == ENTERPRISE_ROLE,
            Admin.organization_id == actor.organization_id,
        )
    result = await db.execute(stmt.order_by(Admin.id))
    return list(result.scalars().all())


async def get_admin(db: AsyncSession, admin_id: int) -> Admin | None:
    return await db.get(Admin, admin_id)


async def _assert_not_last_active_admin(db: AsyncSession, admin: Admin) -> None:
    filters = [Admin.role == admin.role, Admin.is_active.is_(True)]
    if admin.role == ENTERPRISE_ROLE:
        filters.append(Admin.organization_id == admin.organization_id)
    else:
        filters.append(Admin.organization_id.is_(None))
    active = list((await db.execute(select(Admin.id).where(*filters).with_for_update())).scalars().all())
    if len(active) <= 1:
        label = "enterprise" if admin.role == ENTERPRISE_ROLE else "platform super"
        raise HTTPException(status_code=409, detail=f"Cannot disable the last active {label} admin")


async def update_admin(
    db: AsyncSession,
    admin: Admin,
    data: AdminUpdate,
    *,
    actor: Admin,
) -> Admin:
    assert_can_manage_admin(actor, admin)
    fields = data.model_fields_set
    if "role" in fields and data.role != admin.role:
        raise HTTPException(status_code=409, detail="Administrator role is immutable")
    if "organization_id" in fields and data.organization_id != admin.organization_id:
        raise HTTPException(status_code=409, detail="Administrator organization is immutable")
    if data.is_active is False and admin.is_active:
        if admin.id == actor.id:
            raise HTTPException(status_code=409, detail="Cannot disable yourself")
        await _assert_not_last_active_admin(db, admin)

    session_sensitive_change = False
    if "display_name" in fields:
        admin.display_name = data.display_name
    if "is_active" in fields and data.is_active is not None and data.is_active != admin.is_active:
        admin.is_active = data.is_active
        session_sensitive_change = True
    if "password" in fields and data.password is not None:
        admin.password_hash = _hash_password(data.password)
        admin.must_change_password = False
        session_sensitive_change = True
    if session_sensitive_change:
        admin.auth_epoch += 1
    await db.flush()
    await db.refresh(admin)
    return admin


async def resolve_org_info(db: AsyncSession, organization_id) -> tuple[str | None, str | None]:
    """按 organization_id 解析组织名与 slug；不存在/为空时返回 (None, None)。"""
    from app.services.organization_service import get_org_name_slug_by_id

    return await get_org_name_slug_by_id(db, organization_id)


# 向后兼容：仅返回组织名
async def resolve_org_name(db: AsyncSession, organization_id) -> str | None:
    name, _ = await resolve_org_info(db, organization_id)
    return name


async def admin_read_with_org(db: AsyncSession, admin: Admin) -> AdminRead:
    """构造 AdminRead 并填充 organization_name / organization_slug。"""
    read = AdminRead.model_validate(admin)
    name, slug = await resolve_org_info(db, admin.organization_id)
    read.organization_name = name
    read.organization_slug = slug
    return read


async def delete_admin(db: AsyncSession, admin: Admin, *, actor: Admin) -> None:
    """Recoverably delete an administrator by disabling it and revoking sessions."""
    assert_can_manage_admin(actor, admin)
    if admin.id == actor.id:
        raise HTTPException(status_code=409, detail="Cannot delete yourself")
    if admin.is_active:
        await _assert_not_last_active_admin(db, admin)
        admin.is_active = False
        admin.auth_epoch += 1
    await db.flush()


async def change_password(db: AsyncSession, admin: Admin, old_password: str, new_password: str) -> bool:
    """修改密码，返回是否成功。修改后清除 must_change_password 标记。"""
    if not _verify_password(old_password, admin.password_hash):
        return False
    admin.password_hash = _hash_password(new_password)
    admin.must_change_password = False
    admin.auth_epoch += 1
    await db.flush()
    return True
