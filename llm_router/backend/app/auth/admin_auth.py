"""Admin JWT authentication — FastAPI dependency for protecting management API routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.admin import Admin
from app.services.admin_service import decode_access_token, get_admin

# 平台级角色：不绑定组织，可跨组织操作
PLATFORM_ROLES: frozenset[str] = frozenset({"super_admin", "admin"})


@dataclass
class CurrentAdmin:
    """已认证的管理员上下文。"""
    admin: Admin
    id: int
    username: str
    role: Literal["super_admin", "admin", "org_admin"]
    organization_id: UUID | None = None


def is_org_scoped(auth: CurrentAdmin) -> bool:
    """该管理员是否被绑定到单个组织（org_admin 或任何带 organization_id 的账号）。"""
    return auth.organization_id is not None


def assert_org_access(auth: CurrentAdmin, org_id: UUID) -> None:
    """断言当前管理员可访问指定组织。

    - 平台级账号（无 organization_id）放行
    - 组织级账号仅能访问被指派的组织，否则 403
    """
    if auth.organization_id is not None and auth.organization_id != org_id:
        raise HTTPException(
            status_code=403,
            detail="No access to this organization",
        )


def assert_org_write_access(auth: CurrentAdmin, org_id: UUID) -> None:
    """断言对指定组织有访问权且具备写权限。供 id 型写路由复用。"""
    assert_org_access(auth, org_id)


def _extract_bearer_token(request: Request) -> str:
    """从 Authorization: Bearer <token> 中提取 JWT。"""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    raise HTTPException(status_code=401, detail="Missing authorization token")


async def require_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CurrentAdmin:
    """FastAPI 依赖：要求已认证的管理员（任何角色）。"""
    token = _extract_bearer_token(request)
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    admin_id = int(payload["sub"])
    admin = await get_admin(db, admin_id)
    if admin is None or not admin.is_active:
        raise HTTPException(status_code=401, detail="Admin account disabled")

    return CurrentAdmin(
        admin=admin,
        id=admin.id,
        username=admin.username,
        role=admin.role,
        organization_id=admin.organization_id,
    )


async def require_super_admin(
    auth: CurrentAdmin = Depends(require_admin),
) -> CurrentAdmin:
    """FastAPI 依赖：要求 super_admin 角色。"""
    if auth.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin required")
    return auth


async def require_admin_role(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CurrentAdmin:
    """FastAPI 依赖：要求 admin 或 super_admin 角色（排除 org_admin）。

    仅用于平台级写操作（创建/删除组织等）。组织级写操作请用 require_org_access_write。
    """
    auth = await require_admin(request, db)
    if auth.role == "org_admin":
        raise HTTPException(status_code=403, detail="Write access required")
    return auth


async def require_org_access(
    org_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
) -> CurrentAdmin:
    """FastAPI 依赖：要求已认证，且对路径中的 org_id 有访问权（组织越权隔离）。"""
    assert_org_access(auth, org_id)
    return auth


async def require_org_access_write(
    org_id: UUID,
    auth: CurrentAdmin = Depends(require_org_access),
) -> CurrentAdmin:
    """FastAPI 依赖：对 org_id 有访问权，且具备写权限。"""
    return auth
