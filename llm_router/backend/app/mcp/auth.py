"""MCP 鉴权 —— 从 MCP 请求头解析 scoped API key → 归口用户 principal。

复用 ``api_key_service.validate_api_key``：与平台内部 ``require_user`` 走同一套 scope
模型（org/dept/team + created_by 作为 user id），故 MCP 侧调 ``scope_service`` 时
权限边界与终端 runtime 完全一致——第三方智能体终端的调用被限定在归口用户 scope 内。

principal 是 duck-typed：``scope_service`` 的 ``effective_scope_set`` / ``scope_filter``
只读 ``organization_id`` / ``department_id`` / ``team_id`` / ``id`` 四字段，故用
``McpPrincipal`` dataclass 即可（无需构造完整 ``User``）。
"""

from __future__ import annotations

import contextvars
import json
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import async_session_factory
from app.models.organization import Organization
from app.models.user import User
from app.services.api_key_service import validate_api_key
from app.services.oauth_service import OAuthProtocolError, decode_mcp_access_token

# 每请求 Bearer 捕获：MCP transport 的 ctx.request_context.request 不暴露 Authorization
# 头（跨版本实测为 null），故用 ASGI 中间件在请求入口把 Authorization 写入 contextvar，
# stateless 模式下 tool 在同源子任务里能读到。
_bearer_cv: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_bearer_token", default=None
)
_oauth_principal_cv: contextvars.ContextVar[McpPrincipal | None] = contextvars.ContextVar(
    "mcp_oauth_principal", default=None
)


class BearerCaptureMiddleware:
    """ASGI 中间件：从请求 scope 取 Authorization 头写入 contextvar，供工具取用。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = None
        if scope.get("type") == "http":
            auth = None
            for k, v in scope.get("headers", []):
                if k.lower() == b"authorization":
                    auth = v.decode("latin-1")
                    break
            token = _bearer_cv.set(auth)
        try:
            return await self.app(scope, receive, send)
        finally:
            if token is not None:
                _bearer_cv.reset(token)


@dataclass
class McpPrincipal:
    """归口用户身份（从 scoped API key 解析）。字段对齐 ``CurrentUser`` 被 scope_service 读取的集合。"""

    id: str  # = api_key.created_by（导出 skills 包的归口用户）
    organization_id: UUID
    department_id: str | None
    team_id: str | None
    department_ids: tuple[str, ...] = ()
    role_ids: tuple[str, ...] = ()
    permission_codes: tuple[str, ...] = ()
    effective_data_scopes: dict | None = None
    role_data_scopes: dict[str, dict] | None = None


async def _send_json(send, status: int, body: dict, headers: list[tuple[bytes, bytes]] | None = None):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    response_headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(payload)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    response_headers.extend(headers or [])
    await send({"type": "http.response.start", "status": status, "headers": response_headers})
    await send({"type": "http.response.body", "body": payload})


class OrganizationOAuthMiddleware:
    """Tenant-aware OAuth resource server in front of the MCP transport.

    The app is mounted at ``/mcp/organizations``.  The first remaining path
    segment is the organization UUID and is also part of the token audience.
    Generic platform API keys are deliberately rejected on this route.
    """

    def __init__(self, app):
        self.app = app

    @staticmethod
    def _relative_path(scope) -> str:
        path = str(scope.get("path", ""))
        root = str(scope.get("root_path", ""))
        if root and path.startswith(root):
            return path[len(root):]
        return path

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        request = Request(scope, receive=receive)
        parts = [part for part in self._relative_path(scope).split("/") if part]
        if len(parts) != 1:
            return await _send_json(send, 404, {"detail": "Organization MCP resource not found"})
        try:
            organization_id = UUID(parts[0])
        except ValueError:
            return await _send_json(send, 404, {"detail": "Organization MCP resource not found"})

        from app.services.oauth_service import resource_for_org

        try:
            expected_resource = resource_for_org(organization_id, request)
        except RuntimeError:
            return await _send_json(send, 503, {"detail": "OAuth resource server is not configured"})
        metadata_url = (
            expected_resource.split("/mcp/organizations/", 1)[0]
            + f"/.well-known/oauth-protected-resource/mcp/organizations/{organization_id}"
        )
        challenge = f'Bearer resource_metadata="{metadata_url}"'.encode("latin-1")
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            return await _send_json(
                send, 401, {"error": "invalid_token", "error_description": "Bearer token required"},
                [(b"www-authenticate", challenge)],
            )
        raw_token = authorization[7:].strip()
        try:
            claims = decode_mcp_access_token(
                raw_token, expected_resource=expected_resource, request=request,
            )
            if claims.get("org") != str(organization_id):
                raise OAuthProtocolError("invalid_token", "organization audience mismatch", 401)
            user_id = UUID(str(claims["sub"]))
            async with async_session_factory() as db:
                user = await db.get(User, user_id)
                organization = await db.get(Organization, organization_id)
                if (
                    user is None
                    or organization is None
                    or organization.deleted_at is not None
                    or not user.is_active
                    or user.deleted_at is not None
                    or user.organization_id != organization_id
                    or int(claims.get("auth_epoch", -1)) != user.auth_epoch
                ):
                    raise OAuthProtocolError("invalid_token", "user authorization is inactive", 401)
                # Resolve departments, team and business roles from current DB
                # state on every request; a revoked grant is never trusted from
                # old token claims.
                from app.auth.user_auth import current_user_for_user

                current = await current_user_for_user(db, user)
                principal = McpPrincipal(
                    id=current.id,
                    organization_id=current.organization_id,
                    department_id=current.department_id,
                    team_id=current.team_id,
                    department_ids=current.department_ids,
                    role_ids=current.role_ids,
                    permission_codes=current.permission_codes,
                    effective_data_scopes=current.effective_data_scopes,
                    role_data_scopes=current.role_data_scopes,
                )
        except (OAuthProtocolError, KeyError, ValueError) as exc:
            status = exc.status_code if isinstance(exc, OAuthProtocolError) else 401
            error = exc.error if isinstance(exc, OAuthProtocolError) else "invalid_token"
            description = exc.description if isinstance(exc, OAuthProtocolError) else "access token is invalid"
            scope_header = b', scope="mcp:tools"' if status == 403 else b""
            return await _send_json(
                send,
                status,
                {"error": error, "error_description": description},
                [(b"www-authenticate", challenge + scope_header)],
            )

        principal_token = _oauth_principal_cv.set(principal)
        # The mounted FastMCP app owns a single '/' route.  Strip the tenant
        # segment only after its audience has been validated.
        child_scope = dict(scope)
        child_scope["path"] = "/"
        child_scope["raw_path"] = b"/"
        child_scope["root_path"] = ""
        try:
            return await self.app(child_scope, receive, send)
        finally:
            _oauth_principal_cv.reset(principal_token)


async def resolve_principal_from_key(db: AsyncSession, raw_key: str) -> McpPrincipal:
    """Bearer 明文 → validate → McpPrincipal。"""
    if not raw_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    api_key = await validate_api_key(db, raw_key)
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    user_id = api_key.created_by or str(api_key.id)  # skills-pack key 必有 created_by
    return McpPrincipal(
        id=user_id,
        organization_id=api_key.organization_id,
        department_id=str(api_key.department_id) if api_key.department_id else None,
        team_id=str(api_key.team_id) if api_key.team_id else None,
    )


def _extract_bearer(ctx) -> str | None:
    """取本次调用的 Bearer：优先 contextvar（BearerCaptureMiddleware 写入，可靠），
    兜底 ctx.request_context.request.headers（部分 mcp 版本可用）。"""
    cv = _bearer_cv.get()
    if cv and cv.startswith("Bearer "):
        return cv[7:].strip()
    if cv:
        return cv.strip()
    # 兜底：ctx 上的 starlette Request（跨版本可能为 null）
    rc = getattr(ctx, "request_context", None)
    req = getattr(rc, "request", None) if rc is not None else None
    headers = getattr(req, "headers", None)
    if headers is None and hasattr(ctx, "get_http_request"):
        try:
            r = ctx.get_http_request()
            if r is not None:
                headers = getattr(r, "headers", None)
        except Exception:  # noqa: BLE001
            headers = None
    if headers is None:
        return None
    auth = headers.get("authorization", "") if hasattr(headers, "get") else ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


async def resolve_principal(ctx, db: AsyncSession) -> McpPrincipal:
    """Resolve the OAuth principal, with a time-limited legacy key fallback."""
    oauth_principal = _oauth_principal_cv.get()
    if oauth_principal is not None:
        return oauth_principal
    raw_key = _extract_bearer(ctx)
    return await resolve_principal_from_key(db, raw_key or "")
