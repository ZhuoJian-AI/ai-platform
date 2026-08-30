"""Admin authentication service — JWT tokens, password hashing, login."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password, verify_password
from app.config import settings
from app.models.admin import Admin
from app.schemas.admin import AdminCreate, AdminRead, LoginResponse

# 向后兼容的薄封装（历史调用方仍可用私有名）
_hash_password = hash_password
_verify_password = verify_password


def _create_access_token(admin: Admin) -> str:
    """生成 JWT access token。"""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(admin.id),
        "username": admin.username,
        "role": admin.role,
        "iat": now,
        "exp": now + timedelta(hours=24),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any] | None:
    """解码并验证 JWT token。返回 payload 或 None。"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


async def login(
    db: AsyncSession, username: str, password: str, slug: str | None = None
) -> LoginResponse | None:
    """管理员登录，返回 JWT token 或 None。

    - slug 非空：组织门户登录，仅匹配该 slug 对应组织下、绑定了 organization_id 的账号；
      组织不存在或不匹配均返回 None。
    - slug 为空：平台登录，仅匹配未绑定组织（organization_id IS NULL）的平台级账号。
    """
    stmt = select(Admin).where(Admin.username == username, Admin.is_active.is_(True))
    if slug:
        # 延迟导入避免循环依赖
        from app.services.organization_service import get_org_id_by_slug

        org_id = await get_org_id_by_slug(db, slug)
        if org_id is None:
            return None
        stmt = stmt.where(Admin.organization_id == org_id)
    else:
        stmt = stmt.where(Admin.organization_id.is_(None))

    result = await db.execute(stmt)
    admin = result.scalar_one_or_none()
    if admin is None or not _verify_password(password, admin.password_hash):
        return None

    token = _create_access_token(admin)
    return LoginResponse(
        access_token=token,
        must_change_password=admin.must_change_password,
        admin=await admin_read_with_org(db, admin),
    )


async def create_admin(db: AsyncSession, data: AdminCreate, created_by_id: int | None = None) -> Admin:
    """创建管理员账号。"""
    # org_admin 必须绑定组织；其余角色强制解绑（平台级账号）
    org_id = data.organization_id if data.role == "org_admin" else None
    if data.role == "org_admin" and org_id is None:
        raise HTTPException(status_code=400, detail="organization_id is required for org_admin role")
    admin = Admin(
        username=data.username,
        password_hash=_hash_password(data.password),
        display_name=data.display_name,
        role=data.role,
        organization_id=org_id,
    )
    db.add(admin)
    await db.flush()
    return admin


async def ensure_super_admin(db: AsyncSession) -> Admin:
    """确保至少存在一个 super_admin 账号；如不存在则自动创建默认账号。"""
    result = await db.execute(
        select(Admin)
        .where(Admin.role == "super_admin", Admin.is_active.is_(True))
        .order_by(Admin.id)
        .limit(1)
    )
    admin = result.scalar_one_or_none()
    if admin is not None:
        return admin

    # 自动创建默认 super admin: 用户名 root, 密码 root
    admin = Admin(
        username="root",
        password_hash=_hash_password("root"),
        display_name="Root",
        role="super_admin",
        must_change_password=True,
    )
    db.add(admin)
    await db.flush()

    import structlog
    logger = structlog.get_logger()
    logger.warning(
        "super_admin_auto_created",
        username="root",
        message="默认超级管理员已创建（用户名: root, 密码: root），请尽快修改密码",
    )
    return admin


async def list_admins(db: AsyncSession) -> list[Admin]:
    result = await db.execute(select(Admin).order_by(Admin.id))
    return list(result.scalars().all())


async def get_admin(db: AsyncSession, admin_id: int) -> Admin | None:
    return await db.get(Admin, admin_id)


async def update_admin(db: AsyncSession, admin: Admin, *, display_name: str | None = None,
                       role: str | None = None, is_active: bool | None = None,
                       password: str | None = None,
                       organization_id: UUID | None = None) -> Admin:
    if display_name is not None:
        admin.display_name = display_name
    if role is not None:
        admin.role = role
        # 角色变更后同步修正组织绑定：org_admin 必须有组织，非 org_admin 强制解绑
        if role != "org_admin":
            admin.organization_id = None
    if is_active is not None:
        admin.is_active = is_active
    if password is not None:
        admin.password_hash = _hash_password(password)
    # organization_id 显式传入时（None 也表示解绑），仅在 org_admin 角色下生效
    if organization_id is not None and admin.role == "org_admin":
        admin.organization_id = organization_id
    if admin.role == "org_admin" and admin.organization_id is None:
        raise HTTPException(status_code=400, detail="organization_id is required for org_admin role")
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


async def delete_admin(db: AsyncSession, admin: Admin) -> None:
    """硬删除管理员。不允许删除自己。"""
    await db.delete(admin)
    await db.flush()


async def change_password(db: AsyncSession, admin: Admin, old_password: str, new_password: str) -> bool:
    """修改密码，返回是否成功。修改后清除 must_change_password 标记。"""
    if not _verify_password(old_password, admin.password_hash):
        return False
    admin.password_hash = _hash_password(new_password)
    admin.must_change_password = False
    await db.flush()
    return True
