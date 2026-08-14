"""Proxy Router — registers /v1/messages, /v1/chat/completions, /v1/models endpoints.

请求处理流水线已迁移至 LangGraph StateGraph（见 :mod:`app.graph`）。本模块仅保留
HTTP 入口：鉴权（FastAPI 依赖）→ 解析请求体 → 调用 ``run_proxy`` / ``stream_proxy``
驱动图执行。原过程式流水线（权限/DLP/路由/上游/审计）现为图节点。

每个请求经图的节点流转：
1. resolve_permissions（鉴权后加载作用域、级联权限、模型访问校验）
2. dlp_request（请求侧 DLP 安全围栏）
3. resolve_route（模型别名解析 + 提供商路由）
4. proxy_upstream（httpx 字节透传上游，流式经 stream_writer 下发）
5. write_audit（审计落库，含 token 用量）
异常分支经 build_error 格式化为协议特定错误响应。
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key_auth import AuthenticatedKey, authenticate_request
from app.auth.permission_resolver import resolve_effective_permissions
from app.database import get_db
from app.graph import get_proxy_graph, run_proxy, stream_proxy
from app.models.department import Department
from app.models.llm_provider import LlmProvider
from app.models.organization import Organization
from app.models.team import Team
from app.proxy.anthropic_adapter import make_anthropic_error
from app.proxy.openai_adapter import make_openai_error

logger = structlog.get_logger()
proxy_router = APIRouter()


@proxy_router.post("/v1/messages")
async def anthropic_messages(
    request: Request,
    auth: AuthenticatedKey = Depends(authenticate_request),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Anthropic /v1/messages 代理入口。"""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return make_anthropic_error(400, "invalid_request_error", "Invalid JSON body")

    is_stream = bool(body.get("stream", False))
    graph = get_proxy_graph()
    if is_stream:
        return await stream_proxy(graph, request=request, auth=auth, db=db, body=body, protocol="anthropic")
    return await run_proxy(graph, request=request, auth=auth, db=db, body=body, protocol="anthropic")


@proxy_router.post("/v1/chat/completions")
async def openai_chat_completions(
    request: Request,
    auth: AuthenticatedKey = Depends(authenticate_request),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """OpenAI /v1/chat/completions 代理入口。"""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return make_openai_error(400, "invalid_request_error", "Invalid JSON body")

    is_stream = bool(body.get("stream", False))
    graph = get_proxy_graph()
    if is_stream:
        return await stream_proxy(graph, request=request, auth=auth, db=db, body=body, protocol="openai")
    return await run_proxy(graph, request=request, auth=auth, db=db, body=body, protocol="openai")


@proxy_router.get("/v1/models")
async def list_models(
    request: Request,
    auth: AuthenticatedKey = Depends(authenticate_request),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """列出当前 API Key 可访问的模型列表（OpenAI 格式）。"""
    org = await db.get(Organization, auth.organization_id)
    dept = await db.get(Department, auth.department_id) if auth.department_id else None
    team = await db.get(Team, auth.team_id) if auth.team_id else None

    perms = resolve_effective_permissions(auth.api_key, org, dept, team)

    result = await db.execute(
        select(LlmProvider).where(
            LlmProvider.organization_id == auth.organization_id,
            LlmProvider.is_active.is_(True),
            LlmProvider.deleted_at.is_(None),
        )
    )

    providers = list(result.scalars().all())
    models_data: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 优先选 openai 类型 provider（/v1/models 本身就是 OpenAI 协议端点）
    preferred_type = "openai"
    typed_providers = [p for p in providers if p.provider_type == preferred_type]
    if not typed_providers:
        typed_providers = providers  # 回退：没有任何 openai 类型 provider，用全部

    for provider in typed_providers:
        for model_id in provider.supported_models:
            if model_id in seen:
                continue
            if "*" not in perms.allowed_models and model_id not in perms.allowed_models:
                continue
            seen.add(model_id)
            models_data.append({
                "id": model_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": provider.provider_type,
            })

    return Response(
        content=json.dumps({"object": "list", "data": models_data}),
        status_code=200,
        media_type="application/json",
    )
