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
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.api_key_service import validate_api_key

# 每请求 Bearer 捕获：MCP transport 的 ctx.request_context.request 不暴露 Authorization
# 头（跨版本实测为 null），故用 ASGI 中间件在请求入口把 Authorization 写入 contextvar，
# stateless 模式下 tool 在同源子任务里能读到。
_bearer_cv: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_bearer_token", default=None
)


class BearerCaptureMiddleware:
    """ASGI 中间件：从请求 scope 取 Authorization 头写入 contextvar，供工具取用。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            auth = None
            for k, v in scope.get("headers", []):
                if k.lower() == b"authorization":
                    auth = v.decode("latin-1")
                    break
            _bearer_cv.set(auth)
        return await self.app(scope, receive, send)


@dataclass
class McpPrincipal:
    """归口用户身份（从 scoped API key 解析）。字段对齐 ``CurrentUser`` 被 scope_service 读取的集合。"""

    id: str  # = api_key.created_by（导出 skills 包的归口用户）
    organization_id: UUID
    department_id: str | None
    team_id: str | None


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
    """从 MCP Context 解析归口用户 principal（打开 db 校验 key）。"""
    raw_key = _extract_bearer(ctx)
    return await resolve_principal_from_key(db, raw_key or "")
