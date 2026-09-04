"""终端用户 JWT 鉴权 — FastAPI 依赖，保护 /terminal 路由。

与管理员 JWT（``admin_auth``）分离：用户 token payload 含 ``type='user'``（见
``user_service._create_user_access_token``）。``CurrentUser`` 携带 organization_id /
department_ids / 主 department_id / team_id，供资源 scope 过滤与 4 级记忆载入使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models.organization import Organization
from app.models.role import Role, UserRole
from app.models.user import User
from app.services.user_service import get_user


@dataclass
class CurrentUser:
    """已认证的终端用户上下文。"""

    user: User
    id: str
    email: str
    role: str
    organization_id: UUID
    department_id: str | None = None
    department_ids: tuple[str, ...] = ()
    team_id: str | None = None
    role_ids: tuple[str, ...] = ()
    permission_codes: tuple[str, ...] = ()
    effective_data_scopes: dict | None = None
    # Per-role resolved scopes let application authorization merge only roles
    # that independently grant the current app/module/page/action.
    role_data_scopes: dict[str, dict] | None = None


def decode_user_token(token: str) -> dict | None:
    """解码用户 JWT；非用户 token 或过期返回 None。"""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            audience="ai-infra-user-api",
            issuer="ai-infra-user",
            options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "user":
        return None
    return payload


def _extract_bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    raise HTTPException(status_code=401, detail="Missing authorization token")


async def require_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """FastAPI 依赖：要求已认证的终端用户（type=user token）。"""
    token = _extract_bearer_token(request)
    payload = decode_user_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired user token")
    try:
        user_id = UUID(str(payload["sub"]))
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid user token subject")
    user = await get_user(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User account disabled")
    if int(payload.get("auth_epoch", -1)) != user.auth_epoch:
        raise HTTPException(status_code=401, detail="User session has been revoked")
    organization = await db.get(Organization, user.organization_id)
    if organization is None or organization.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Organization is unavailable")
    if user.must_change_password and request.url.path != "/api/v1/users/change-password":
        raise HTTPException(status_code=403, detail="PASSWORD_CHANGE_REQUIRED")
    return await current_user_for_user(db, user)


async def current_user_for_user(db: AsyncSession, user: User) -> CurrentUser:
    """Build the same effective terminal principal for login and admin previews."""
    from app.services.role_service import rbac_for_user

    organization = await db.get(Organization, user.organization_id)
    if organization is None or organization.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Organization is unavailable")

    fresh = (
        await db.execute(
            select(User)
            .options(
                selectinload(User.role_assignments).selectinload(UserRole.role).selectinload(Role.permissions),
                selectinload(User.role_assignments).selectinload(UserRole.role).selectinload(Role.data_departments),
            )
            .where(User.id == user.id, User.deleted_at.is_(None))
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    # This helper is also used after long-running Agent/Office/storage work.
    # Never fall back to the caller's stale ORM object: a deleted or disabled
    # account must lose all effective permissions before the final write.
    if fresh is None or not fresh.is_active:
        raise HTTPException(status_code=401, detail="User account disabled")
    user = fresh
    rbac = await rbac_for_user(db, user)
    return CurrentUser(
        user=user,
        id=str(user.id),
        email=user.username,
        role=user.role,
        organization_id=user.organization_id,
        department_id=str(user.department_id) if user.department_id else None,
        department_ids=tuple(str(value) for value in user.department_ids),
        team_id=str(user.team_id) if user.team_id else None,
        role_ids=rbac["role_ids"],
        permission_codes=rbac["permission_codes"],
        effective_data_scopes=rbac["effective_data_scopes"],
        role_data_scopes=rbac["role_data_scopes"],
    )


def assert_user_org_access(cu: CurrentUser, org_id: UUID) -> None:
    """断言用户属于该组织。终端用户始终绑定单组织。"""
    if cu.organization_id != org_id:
        raise HTTPException(status_code=403, detail="No access to this organization")


def assert_user_write(cu: CurrentUser) -> None:
    """终端用户写权限断言钩子。

    已取消「只读 viewer」角色，当前所有终端用户均具备写权限；此函数保留为
    占位以便未来按角色细分写权限。terminal.py 各写端点统一调用它。
    """
    return None
