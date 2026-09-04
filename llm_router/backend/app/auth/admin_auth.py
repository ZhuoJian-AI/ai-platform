"""Admin JWT authentication — FastAPI dependency for protecting management API routes."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session_cookies import admin_csrf_cookie_name, admin_session_cookie_name
from app.config import settings
from app.database import get_db
from app.models.admin import Admin
from app.models.organization import Organization
from app.services.admin_service import decode_access_token, get_admin

PLATFORM_ROLE = "platform_super_admin"
ENTERPRISE_ROLE = "enterprise_admin"
ADMIN_ROLES: frozenset[str] = frozenset({PLATFORM_ROLE, ENTERPRISE_ROLE})
PLATFORM_ROLES: frozenset[str] = frozenset({PLATFORM_ROLE})


@dataclass
class CurrentAdmin:
    """已认证的管理员上下文。"""

    admin: Admin
    id: int
    username: str
    role: Literal["platform_super_admin", "enterprise_admin"]
    organization_id: UUID | None = None


def is_org_scoped(auth: CurrentAdmin) -> bool:
    """企业管理员始终绑定且仅绑定一个组织。"""
    return auth.role == ENTERPRISE_ROLE


def assert_org_access(auth: CurrentAdmin, org_id: UUID) -> None:
    """断言当前管理员可访问指定组织。

    - platform_super_admin 可访问所有组织
    - enterprise_admin 仅能访问其永久绑定的组织
    """
    if auth.role == PLATFORM_ROLE and auth.organization_id is None:
        return
    if auth.role == ENTERPRISE_ROLE and auth.organization_id == org_id:
        return
    raise HTTPException(
        status_code=403,
        detail="No access to this organization",
    )


def _valid_admin_shape(admin: Admin) -> bool:
    """Fail closed if a pre-migration or malformed row reaches authentication."""
    return (admin.role == PLATFORM_ROLE and admin.organization_id is None) or (
        admin.role == ENTERPRISE_ROLE and admin.organization_id is not None
    )


def assert_org_write_access(auth: CurrentAdmin, org_id: UUID) -> None:
    """断言对指定组织有访问权且具备写权限。供 id 型写路由复用。"""
    assert_org_access(auth, org_id)


def _browser_allowed_origins(request: Request) -> set[str]:
    configured = {
        value.strip().rstrip("/")
        for value in settings.browser_allowed_origins.split(",")
        if value.strip()
    }
    for value in (
        settings.normalized_oauth_public_base_url,
        settings.normalized_proxy_base_url or "",
    ):
        if value:
            configured.add(value.rstrip("/"))
    if settings.is_development:
        configured.add(f"{request.url.scheme}://{request.url.netloc}")
    return configured


def _validate_cookie_request(request: Request) -> None:
    """Require same-site browser evidence and a double-submit CSRF token."""
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in _browser_allowed_origins(request):
        raise HTTPException(status_code=403, detail="Untrusted browser origin")
    fetch_site = request.headers.get("sec-fetch-site", "")
    if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
        raise HTTPException(status_code=403, detail="Cross-site browser request rejected")
    cookie_value = request.cookies.get(admin_csrf_cookie_name(), "")
    header_value = request.headers.get("x-csrf-token", "")
    if not cookie_value or not header_value or not hmac.compare_digest(cookie_value, header_value):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token")


def _extract_admin_token(request: Request) -> tuple[str, bool]:
    """Return ``(JWT, came_from_cookie)`` with bearer compatibility."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip(), False
    cookie = request.cookies.get(admin_session_cookie_name(), "")
    if cookie:
        return cookie, True
    raise HTTPException(status_code=401, detail="Missing authorization token")


async def require_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CurrentAdmin:
    """FastAPI 依赖：要求已认证的管理员（任何角色）。"""
    token, from_cookie = _extract_admin_token(request)
    if from_cookie:
        _validate_cookie_request(request)
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    admin_id = int(payload["sub"])
    admin = await get_admin(db, admin_id)
    if admin is None or not admin.is_active or not _valid_admin_shape(admin):
        raise HTTPException(status_code=401, detail="Admin account disabled")
    if admin.organization_id is not None:
        organization = await db.get(Organization, admin.organization_id)
        if organization is None or organization.deleted_at is not None:
            raise HTTPException(status_code=401, detail="Organization is unavailable")
    if payload.get("auth_epoch") != admin.auth_epoch:
        raise HTTPException(status_code=401, detail="Admin session revoked")
    return CurrentAdmin(
        admin=admin,
        id=admin.id,
        username=admin.username,
        role=admin.role,
        organization_id=admin.organization_id,
    )


async def require_platform_super_admin(
    auth: CurrentAdmin = Depends(require_admin),
) -> CurrentAdmin:
    """FastAPI 依赖：要求平台超级管理员。"""
    if auth.role != PLATFORM_ROLE or auth.organization_id is not None:
        raise HTTPException(status_code=403, detail="Platform super admin required")
    return auth


# Compatibility name for existing route imports. Semantics are intentionally narrowed
# to the sole platform-wide role.
require_super_admin = require_platform_super_admin


async def require_admin_role(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CurrentAdmin:
    """平台级写操作依赖（创建/删除组织等）。"""
    auth = await require_admin(request, db)
    if auth.role != PLATFORM_ROLE or auth.organization_id is not None:
        raise HTTPException(status_code=403, detail="Platform super admin required")
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
