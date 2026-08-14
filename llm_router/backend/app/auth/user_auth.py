"""终端用户 JWT 鉴权 — FastAPI 依赖，保护 /terminal 路由。

与管理员 JWT（``admin_auth``）分离：用户 token payload 含 ``type='user'``（见
``user_service._create_user_access_token``）。``CurrentUser`` 携带 organization_id /
department_id / team_id，供资源 scope 过滤与 4 级记忆载入使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
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
    team_id: str | None = None


def decode_user_token(token: str) -> dict | None:
    """解码用户 JWT；非用户 token 或过期返回 None。"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
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
    user_id = UUID(payload["sub"])
    user = await get_user(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User account disabled")
    return CurrentUser(
        user=user,
        id=str(user.id),
        email=user.username,
        role=user.role,
        organization_id=user.organization_id,
        department_id=str(user.department_id) if user.department_id else None,
        team_id=str(user.team_id) if user.team_id else None,
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
