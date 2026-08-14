"""MCP server —— 把归口用户 scope 内的五项能力暴露给第三方智能体终端。

第三方终端（Claude Code / Codex / WorkBuddy）通过 skills 包内 ``.mcp.json`` 指向
``/mcp``，带内嵌 Bearer（scoped API key，导出时即时轮换）。每个工具调用：
  Bearer → validate_api_key → McpPrincipal（归口用户 scope）→ db → dispatch 到
  ``capability_tools`` 实现函数。

工具集与 ``app/tools/capability_tools.py`` 的 StructuredTool 一一对应（同一份实现，
单源事实）：query_ontology / list_skills / call_skill / list_data_interfaces /
search_rag / read_memory / write_memory / list_agents / get_agent_config。
``list_agents`` + ``get_agent_config`` 为只读：拉取平台已设定的智能体配置内容
（system_prompt 即 L3 模板 persona/policy/输出骨架 + 绑定技能/RAG/模型），供第三方
终端的 agent 当指令用，**不触发平台 runtime 运行**。

挂载：``app/main.py`` 以 ``app.mount("/mcp", mcp.streamable_http_app())`` 暴露 ASGI 子应用。

> 注：mcp SDK 跨版本 API 有差异，本实现按 1.2+ streamable_http + Context 写就；
> 需在部署环境跑一次集成测试（见 plan §四 验证 2）确认 ``ctx.request_context.request``
> 取头路径与当前安装版本一致。
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.database import async_session_factory
from app.mcp.auth import resolve_principal
from app.tools.capability_tools import (
    _call_skill,
    _get_agent_config,
    _list_agents,
    _list_data_interfaces,
    _list_skills,
    _query_ontology,
    _read_memory,
    _search_rag,
    _write_memory,
)

# transport_security 显式禁用 DNS rebinding 保护：本服务部署在 nginx 后、对外公开，
# 鉴权由 skills 包内嵌的 scoped Bearer（app/mcp/auth.py）承担，Host 白名单（默认仅
# localhost）会拒绝 nginx 转发的 Host: infra.aievolve.org.cn → 421。禁用后 Host/Origin
# 校验跳过，仅保留 Content-Type 校验。
mcp = FastMCP(
    "ai-infra-capabilities",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# 内部 streamable 路由设为 ``/``：配合 main.py ``app.mount("/mcp", ...)`` 后，
# 外部端点落在干净的 ``/mcp/``（默认 ``/mcp`` 会导致 ``/mcp/mcp``）。
mcp.settings.streamable_http_path = "/"
# stateless 模式：每请求独立 transport，工具在当前 HTTP 请求的 async context 内执行，
# 故 ctx.request_context.request.headers 能取到本次调用的 Authorization（stateful 下
# request 上下文不携带逐次调用的头，鉴权取不到 key）。本服务工具均为单次调用返回，
# 无需会话连续性，stateless 更简单且 Claude Code 支持。
mcp.settings.stateless_http = True


@mcp.tool()
async def query_ontology(path: str | None = None, ctx: Context = None) -> str:  # type: ignore[assignment]
    """查询归口用户 scope 内本体（L2 identifiers：object/link/action-types + 标识符码空间）。"""
    async with async_session_factory() as db:
        principal = await resolve_principal(ctx, db)
        return await _query_ontology(db, principal, path)  # type: ignore[arg-type]


@mcp.tool()
async def list_skills(ctx: Context = None) -> str:  # type: ignore[assignment]
    """列出归口用户 scope 内全部技能及绑定的可调用端点。规划调用前先列出。"""
    async with async_session_factory() as db:
        principal = await resolve_principal(ctx, db)
        return await _list_skills(db, principal)  # type: ignore[arg-type]


@mcp.tool()
async def call_skill(
    skill_slug: str,
    endpoint_name: str,
    params: dict[str, Any] | None = None,
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """执行技能绑定的端点（数据接口调用入口）。标识符须来自 query_ontology 或接口返回，不得臆造。"""
    async with async_session_factory() as db:
        principal = await resolve_principal(ctx, db)
        return await _call_skill(db, principal, skill_slug, endpoint_name, params or {})  # type: ignore[arg-type]


@mcp.tool()
async def list_data_interfaces(ctx: Context = None) -> str:  # type: ignore[assignment]
    """列出归口用户 scope 内数据接口目录（name/method/path/参数提示）。仅规划用，执行走 call_skill。"""
    async with async_session_factory() as db:
        principal = await resolve_principal(ctx, db)
        return await _list_data_interfaces(db, principal)  # type: ignore[arg-type]


@mcp.tool()
async def search_rag(query: str, top_k: int = 5, ctx: Context = None) -> str:  # type: ignore[assignment]
    """跨归口用户 scope 内全部知识库做语义检索。提示词须含相关知识库名称字样以稳定命中。"""
    async with async_session_factory() as db:
        principal = await resolve_principal(ctx, db)
        return await _search_rag(db, principal, query, top_k)  # type: ignore[arg-type]


@mcp.tool()
async def read_memory(ctx: Context = None) -> str:  # type: ignore[assignment]
    """读取归口用户 4 级 scope（组织/部门/团队/个人）聚合的长期记忆。"""
    async with async_session_factory() as db:
        principal = await resolve_principal(ctx, db)
        return await _read_memory(db, principal)  # type: ignore[arg-type]


@mcp.tool()
async def write_memory(content: str, ctx: Context = None) -> str:  # type: ignore[assignment]
    """沉淀一条事实到归口用户个人级记忆（逐条追加、去重）。"""
    async with async_session_factory() as db:
        principal = await resolve_principal(ctx, db)
        result = await _write_memory(db, principal, content)  # type: ignore[arg-type]
        await db.commit()
        return result


@mcp.tool()
async def list_agents(ctx: Context = None) -> str:  # type: ignore[assignment]
    """列出归口用户 scope 内可见的智能体配置（slug/名称/模型/描述，只读不运行）。"""
    async with async_session_factory() as db:
        principal = await resolve_principal(ctx, db)
        return await _list_agents(db, principal)  # type: ignore[arg-type]


@mcp.tool()
async def get_agent_config(agent_slug: str, ctx: Context = None) -> str:  # type: ignore[assignment]
    """取某智能体完整配置（只读不运行）：system_prompt（L3 模板）+ 模型 + 绑定技能/RAG slug。
    把 system_prompt 当自身指令，再用 list_skills/call_skill/search_rag/read_memory 自主完成。"""
    async with async_session_factory() as db:
        principal = await resolve_principal(ctx, db)
        return await _get_agent_config(db, principal, agent_slug)  # type: ignore[arg-type]


def mcp_app():
    """返回 streamable HTTP ASGI 子应用，供 FastAPI mount。

    外包 BearerCaptureMiddleware：MCP transport 不把 Authorization 头透传到
    ctx.request_context.request，故在 ASGI 入口捕获写入 contextvar，stateless 模式下
    工具在同源子任务里读到（见 app/mcp/auth.py:_extract_bearer）。
    """
    from app.mcp.auth import BearerCaptureMiddleware

    return BearerCaptureMiddleware(mcp.streamable_http_app())
