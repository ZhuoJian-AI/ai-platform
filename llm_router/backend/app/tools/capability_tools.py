"""能力共享工具层 —— 把归口用户 scope 内的五项能力各包成 LangChain StructuredTool。

设计目的（见 demo plan「归口用户 Skills 包」）：
- **单一事实源**：同一份工具定义，对外经 MCP（langchain-mcp-adapters）暴露给第三方智能体
  终端（Claude Code / Codex / WorkBuddy），对内可被现有 LangGraph runtime 消费
  （`_build_tools` 改造后 `as_openai_function` 喂 agent）。
- **零新业务逻辑**：每个工具内部只转发到既有 service（scope_service / execute_endpoint
  / rag_service / memory_service），鉴权边界由 `CurrentClient` 透传给 `scope_service`
  天然复用——MCP 侧与平台内部走同一套 scope 过滤。

每个工具在构造时绑定 `CurrentClient`（归口用户身份）与 `db` 会话，故用工厂
`build_capability_tools(db, cu)` 按请求即时产出，而非模块级单例。

五项能力 ↔ 工具映射：
- 本体        → query_ontology
- 技能/数据接口 → list_skills / call_skill / list_data_interfaces
- 知识库 RAG   → search_rag
- 记忆        → read_memory / write_memory
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_auth import CurrentUser
from app.database import async_session_factory
from app.models.connector import ToolConnector, ToolEndpoint
from app.models.rag import RagCollection
from app.models.skill import SkillFolder
from app.schemas.multimodal import AudioTranscriptionCreate, SpeechCreate
from app.schemas.rag import RagRetrieveRequest
from app.services import memory_service, multimodal_audio_service, scope_service
from app.services.rag_service import retrieve as rag_retrieve
from app.services.skill_store_service import SKILL_MANIFEST_PATH
from app.services.skill_store_service import get_file_by_path as get_skill_file_by_path
from app.tools.executor import execute_endpoint
from app.tools.skill_manifest import parse_skill_manifest

# ── 入参 schema（Pydantic）──────────────────────────────────────────────


class QueryOntologyArgs(BaseModel):
    path: str | None = Field(
        default=None,
        description=(
            "可选：只取该路径的本体文件（如 README.md / identifiers.md）。"
            "不传则返回用户 scope 内全部本体文件摘要。"
        ),
    )


class CallSkillArgs(BaseModel):
    skill_slug: str = Field(description="技能 slug（如 starclothing-plm-query），须在当前用户 scope 内")
    endpoint_name: str = Field(description="技能绑定的端点名（见 list_skills 返回的 bound_endpoints）")
    params: dict[str, Any] = Field(default_factory=dict, description="端点入参，键名见端点 params_schema")


class SearchRagArgs(BaseModel):
    query: str = Field(description="检索 query（语义匹配，中文长文亦可）")
    top_k: int = Field(default=5, ge=1, le=50, description="每个 RAG 集合取 top-k 命中")


class WriteMemoryArgs(BaseModel):
    content: str = Field(description="待沉淀的事实/记忆条目（逐条追加进该用户个人级记忆，自动去重）")


class GetAgentConfigArgs(BaseModel):
    agent_slug: str = Field(description="智能体 slug（见 list_agents 返回），须在当前用户 scope 内")


class TranscribeAudioArgs(BaseModel):
    workspace_file_id: UUID = Field(description="当前用户有权访问的工作空间音频文件 ID")
    language: str = Field(default="auto", description="识别语言：auto、zh 或 en")


class UnderstandAudioArgs(BaseModel):
    workspace_file_id: UUID = Field(description="当前用户有权访问的工作空间音频文件 ID")
    question: str = Field(description="希望模型基于音频回答的问题")


class SynthesizeSpeechArgs(BaseModel):
    text: str = Field(description="需要朗读的文字")
    voice_profile_id: UUID = Field(description="当前用户获授权的企业音色 ID")
    style: str | None = Field(default=None, description="可选的语气或情绪")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="语速")


# ── 工具实现（闭包绑定 db + cu）─────────────────────────────────────────


async def _query_ontology(db: AsyncSession, cu: CurrentUser, path: str | None) -> str:
    """返回用户 scope 内本体文件（L2 identifiers），content 即 Markdown 正文。"""
    files = await scope_service.list_ontologies_for_user(db, cu)
    if path:
        files = [f for f in files if f.path == path or f.path.endswith("/" + path)]
    if not files:
        return "（用户 scope 内无本体文件）"
    parts = [f"[本体 {f.path}]\n{(f.content or '').strip()}" for f in files if (f.content or "").strip()]
    return "\n\n".join(parts) or "（本体文件内容为空）"


async def _list_skills(db: AsyncSession, cu: CurrentUser) -> str:
    """列出用户 scope 内技能及其绑定的可调用端点（供第三方 agent 规划调用）。"""
    folders = await scope_service.list_skills_for_user(db, cu)
    if not folders:
        return "（用户 scope 内无技能）"
    lines: list[str] = []
    for folder in folders:
        manifest_file = await get_skill_file_by_path(db, folder.id, SKILL_MANIFEST_PATH)
        manifest = parse_skill_manifest(manifest_file.content if manifest_file else None)
        if manifest is None:
            lines.append(f"- {folder.slug}：{folder.name}（manifest 缺失，不可调用）")
            continue
        eps: list[str] = []
        for eid in manifest.bound_endpoint_ids:
            ep = await db.get(ToolEndpoint, UUID(eid)) if eid else None
            if ep and ep.is_active:
                eps.append(f"{ep.name}({ep.method} {ep.path})")
        bound = ", ".join(eps) or "（无活跃端点）"
        lines.append(f"- {folder.slug}：{manifest.description or folder.name} → [{bound}]")
    return "\n".join(lines)


async def _call_skill(db: AsyncSession, cu: CurrentUser, skill_slug: str, endpoint_name: str, params: dict) -> str:
    """按技能 slug 解析 manifest → 命中端点 → execute_endpoint 执行（复用 runtime 同款路径）。"""
    folders = await scope_service.list_skills_for_user(db, cu)
    folder = next((f for f in folders if f.slug == skill_slug), None)
    if folder is None:
        return f"error: skill '{skill_slug}' 不在当前用户 scope 内"
    manifest_file = await get_skill_file_by_path(db, folder.id, SKILL_MANIFEST_PATH)
    manifest = parse_skill_manifest(manifest_file.content if manifest_file else None)
    if manifest is None:
        return f"error: skill '{skill_slug}' manifest 缺失或非法"
    # 找到对应 endpoint（命名空间：manifest.name__ep.name，这里按 ep.name 匹配）
    ep: ToolEndpoint | None = None
    for eid in manifest.bound_endpoint_ids:
        cand = await db.get(ToolEndpoint, UUID(eid)) if eid else None
        if cand and cand.is_active and cand.name == endpoint_name:
            ep = cand
            break
    if ep is None:
        bound = [await db.get(ToolEndpoint, UUID(eid)) for eid in manifest.bound_endpoint_ids]
        names = [e.name for e in bound if e and e.is_active]
        return f"error: endpoint '{endpoint_name}' 未绑定到 skill '{skill_slug}'；可用：{names}"
    conn = await db.get(ToolConnector, ep.connector_id)
    if conn is None:
        return "error: connector not found"
    result = await execute_endpoint(
        db, org_id=UUID(str(cu.organization_id)), connector=conn, endpoint=ep,
        params=params, skill_id=folder.id,
    )
    import json as _json
    body = _json.dumps(result.body, ensure_ascii=False) if result.body is not None else (result.error or "")
    ok = 200 <= int(result.status_code or 0) < 400
    return f"status={result.status_code} ok={ok} latency_ms={result.latency_ms}\n{body[:4000]}"


async def _list_data_interfaces(db: AsyncSession, cu: CurrentUser) -> str:
    """数据接口目录（注入用规划面）：name / method / path / 参数提示。执行请走 call_skill。"""
    dis = await scope_service.list_data_interfaces_for_user(db, cu)
    if not dis:
        return "（用户 scope 内无数据接口）"
    lines: list[str] = []
    for di in dis:
        schema = di.params_schema or {}
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = set(schema.get("required") or [])
        hint = ", ".join(
            f"{n}{'!' if n in required else ''}({(p or {}).get('type', 'any')})"
            for n, p in props.items()
        )
        lines.append(f"- {di.name} {di.method or ''} {di.path or ''}" + (f"  参数: {hint}" if hint else ""))
    return "\n".join(lines)


async def _search_rag(db: AsyncSession, cu: CurrentUser, query: str, top_k: int) -> str:
    """跨用户 scope 内全部 RAG 集合检索 top-k，合并返回（复用 rag_service.retrieve）。"""
    colls = await scope_service.list_rags_for_user(db, cu)
    if not colls:
        return "（用户 scope 内无 RAG 知识库）"
    req = RagRetrieveRequest(query=query, top_k=top_k)
    out: list[str] = []
    for coll in colls:
        try:
            hits = await rag_retrieve(
                db,
                coll,
                UUID(str(cu.organization_id)),
                req,
                department_id=cu.department_id,
                team_id=cu.team_id,
            )
        except Exception as exc:  # noqa: BLE001 — 检索失败不阻断其余集合
            out.append(f"[{coll.name}] 检索失败：{exc}")
            continue
        if not hits:
            continue
        out.append(f"[{coll.name}] 命中 {len(hits)} 条：")
        for h in hits:
            content = str(h.get("content") or "").strip().replace("\n", " ")
            out.append(f"  - score={h.get('score')} {content[:200]}")
    return "\n".join(out) or "（未命中）"


async def _read_memory(db: AsyncSession, cu: CurrentUser) -> str:
    """4 级（org/dept/team/user）scope 聚合的长期记忆（复用 memory_service.list_memory_for_user）。"""
    scopes = scope_service.effective_scope_set(cu)
    mems = await memory_service.list_memory_for_user(db, UUID(str(cu.organization_id)), scopes)
    if not mems:
        return "（无长期记忆）"
    parts = [
        f"[{m.scope_type}{('/' + m.category) if m.category else ''}]\n{(m.content or '').strip()}"
        for m in mems
    ]
    return "\n\n".join(parts)


async def _write_memory(db: AsyncSession, cu: CurrentUser, content: str) -> str:
    """沉淀一条事实到当前用户个人级记忆（复用 memory_service.add_user_memory）。"""
    mem = await memory_service.add_user_memory(
        db, UUID(str(cu.organization_id)), cu.id, content,
    )
    return f"ok: 已沉淀到个人记忆 {mem.id}"


async def _list_agents(db: AsyncSession, cu: CurrentUser) -> str:
    """列出归口用户 scope 内可见的智能体配置（只读，不运行）。

    返回 slug / name / description / model_alias，供第三方终端选用 `get_agent_config`
    取完整 system_prompt（L3 模板）当自身指令用。不触发平台 runtime。
    """
    agents = await scope_service.list_agents_for_user(db, cu)
    if not agents:
        return "（用户 scope 内无智能体配置）"
    lines = [
        f"- {a.slug}：{a.name}"
        f"（model={a.model_alias}）"
        f"{(' — ' + a.description) if a.description else ''}"
        for a in agents
    ]
    return "\n".join(lines)


async def _get_agent_config(db: AsyncSession, cu: CurrentUser, agent_slug: str) -> str:
    """取某个智能体的完整配置内容（只读，不运行）：system_prompt（L3 模板）+
    模型 + 绑定技能（slug）+ 绑定 RAG（slug）+ workflow/memory_config。

    第三方终端的 agent 可把 system_prompt 当自身 persona/policy/输出骨架指令，
    再用 list_skills/call_skill/search_rag/read_memory 自主完成——不需平台 runtime 执行。
    """
    import json as _json
    agents = await scope_service.list_agents_for_user(db, cu)
    agent = next((a for a in agents if a.slug == agent_slug), None)
    if agent is None:
        return f"error: agent '{agent_slug}' 不在当前用户 scope 内"

    # 解析 skill_ids（SkillFolder id 列表）→ slug/name
    skills: list[dict] = []
    for sid in agent.skill_ids or []:
        try:
            folder = await db.get(SkillFolder, UUID(str(sid))) if sid else None
        except (ValueError, TypeError):
            folder = None
        if folder:
            skills.append({"slug": folder.slug, "name": folder.name})

    # 解析 rag_collection_ids → slug/name
    rags: list[dict] = []
    for rid in agent.rag_collection_ids or []:
        try:
            coll = await db.get(RagCollection, UUID(str(rid))) if rid else None
        except (ValueError, TypeError):
            coll = None
        if coll:
            rags.append({"slug": coll.slug, "name": coll.name})

    payload = {
        "slug": agent.slug,
        "name": agent.name,
        "description": agent.description,
        "model_alias": agent.model_alias,
        "system_prompt": agent.system_prompt or "",
        "skills": skills,
        "rag_collections": rags,
        "workflow": agent.workflow or [],
        "memory_config": agent.memory_config or {},
    }
    return _json.dumps(payload, ensure_ascii=False, indent=2)


async def _transcribe_audio(
    db: AsyncSession, cu: CurrentUser, workspace_file_id: UUID, language: str,
) -> str:
    # Keep the agent's request transaction isolated while making the durable
    # job immediately visible to the worker.
    _ = db
    async with async_session_factory() as job_db:
        job = await multimodal_audio_service.queue_transcription(
            job_db,
            cu,
            AudioTranscriptionCreate(workspace_file_id=workspace_file_id, language=language),
        )
        job_id = job.id
        request_id = job.request_id
        await job_db.commit()
    for _attempt in range(150):
        async with async_session_factory() as poll_db:
            current = await multimodal_audio_service.get_job(poll_db, cu, job_id)
            if current.status == "succeeded":
                text = str((current.result or {}).get("text") or "").strip()
                return text or f"job_id={job_id} request_id={request_id} status=succeeded"
            if current.status in {"failed", "cancelled"}:
                return (
                    f"job_id={job_id} request_id={request_id} status={current.status} "
                    f"error={current.error_category or 'audio_processing_failed'}"
                )
        await asyncio.sleep(2)
    return f"job_id={job_id} request_id={request_id} status=processing"


async def _understand_audio(
    db: AsyncSession, cu: CurrentUser, workspace_file_id: UUID, question: str,
) -> str:
    result = await multimodal_audio_service.understand_file(
        db, cu, workspace_file_id, question, "default",
    )
    return str(result["content"])


async def _synthesize_speech(
    db: AsyncSession,
    cu: CurrentUser,
    text: str,
    voice_profile_id: UUID,
    style: str | None,
    speed: float,
) -> str:
    job = await multimodal_audio_service.queue_speech(
        db,
        cu,
        SpeechCreate(
            text=text,
            voice_profile_id=voice_profile_id,
            style=style,
            speed=speed,
            format="wav",
        ),
    )
    return f"job_id={job.id} request_id={job.request_id} status={job.status}"


# ── 工厂：按请求绑定 db + cu 产出 StructuredTool 列表 ────────────────────


def build_capability_tools(db: AsyncSession, cu: CurrentUser) -> list[StructuredTool]:
    """构造归口用户 scope 内的五项能力 StructuredTool。

    返回的 StructuredTool：
    - 对外：langchain-mcp-adapters 直接暴露为 MCP tool；
    - 对内：`tool.as_openai_function()` 喂现有 LangGraph agent（runtime 收敛后）。

    注意：StructuredTool.from_function 用 ``inspect.iscoroutinefunction`` 判定异步，
    故这里用真正的 ``async def`` 闭包绑定 ``db``/``cu``，而非 lambda（lambda 返回
    coroutine 会被当同步函数处理而失败）。
    """

    async def _t_query_ontology(path: str | None = None) -> str:
        return await _query_ontology(db, cu, path)

    async def _t_list_skills() -> str:
        return await _list_skills(db, cu)

    async def _t_call_skill(skill_slug: str, endpoint_name: str, params: dict[str, Any] | None = None) -> str:
        return await _call_skill(db, cu, skill_slug, endpoint_name, params or {})

    async def _t_list_data_interfaces() -> str:
        return await _list_data_interfaces(db, cu)

    async def _t_search_rag(query: str, top_k: int = 5) -> str:
        return await _search_rag(db, cu, query, top_k)

    async def _t_read_memory() -> str:
        return await _read_memory(db, cu)

    async def _t_write_memory(content: str) -> str:
        return await _write_memory(db, cu, content)

    async def _t_list_agents() -> str:
        return await _list_agents(db, cu)

    async def _t_get_agent_config(agent_slug: str) -> str:
        return await _get_agent_config(db, cu, agent_slug)

    async def _t_transcribe_audio(workspace_file_id: UUID, language: str = "auto") -> str:
        return await _transcribe_audio(db, cu, workspace_file_id, language)

    async def _t_understand_audio(workspace_file_id: UUID, question: str) -> str:
        return await _understand_audio(db, cu, workspace_file_id, question)

    async def _t_synthesize_speech(
        text: str,
        voice_profile_id: UUID,
        style: str | None = None,
        speed: float = 1.0,
    ) -> str:
        return await _synthesize_speech(db, cu, text, voice_profile_id, style, speed)

    return [
        StructuredTool.from_function(
            func=_t_query_ontology,
            name="query_ontology",
            description=(
                "查询当前归口用户 scope 内的本体（L2 identifiers：object/link/action-types + 标识符码空间）。"
                "调用前先了解可用标识符，避免臆造 ID。"
            ),
            args_schema=QueryOntologyArgs,
        ),
        StructuredTool.from_function(
            func=_t_list_skills,
            name="list_skills",
            description=(
                "列出当前归口用户 scope 内全部技能及其绑定的可调用端点。"
                "规划调用前先列出，确认 skill_slug 与 endpoint_name。"
            ),
        ),
        StructuredTool.from_function(
            func=_t_call_skill,
            name="call_skill",
            description=(
                "执行技能绑定的端点（数据接口调用入口）。须先 list_skills 取 skill_slug 与 endpoint_name，"
                "入参键名见端点 params_schema。不要臆造参数值，标识符须来自 query_ontology 或接口返回。"
            ),
            args_schema=CallSkillArgs,
        ),
        StructuredTool.from_function(
            func=_t_list_data_interfaces,
            name="list_data_interfaces",
            description=(
                "列出当前归口用户 scope 内数据接口目录（name/method/path/参数提示）。"
                "仅用于规划，执行请走 call_skill。"
            ),
        ),
        StructuredTool.from_function(
            func=_t_search_rag,
            name="search_rag",
            description=(
                "跨当前归口用户 scope 内全部知识库做语义检索（中文长文亦可）。返回命中片段与 score。"
                "提示词须含相关知识库字样以稳定命中。"
            ),
            args_schema=SearchRagArgs,
        ),
        StructuredTool.from_function(
            func=_t_read_memory,
            name="read_memory",
            description="读取当前归口用户 4 级 scope（组织/部门/团队/个人）聚合的长期记忆。",
        ),
        StructuredTool.from_function(
            func=_t_write_memory,
            name="write_memory",
            description="沉淀一条事实到当前归口用户个人级记忆（逐条追加、去重）。",
            args_schema=WriteMemoryArgs,
        ),
        StructuredTool.from_function(
            func=_t_list_agents,
            name="list_agents",
            description=(
                "列出归口用户 scope 内可见的智能体配置（slug/名称/模型/描述，只读不运行）。"
                "取完整 system_prompt 用 get_agent_config。"
            ),
        ),
        StructuredTool.from_function(
            func=_t_get_agent_config,
            name="get_agent_config",
            description=(
                "取某个智能体的完整配置内容（只读不运行）：system_prompt（L3 模板 persona/policy/输出骨架）"
                "+ 模型 + 绑定技能 slug + 绑定 RAG slug。把 system_prompt 当自身指令，"
                "再用 list_skills/call_skill/search_rag/read_memory 自主完成。"
            ),
            args_schema=GetAgentConfigArgs,
        ),
        StructuredTool.from_function(
            func=_t_transcribe_audio,
            name="transcribe_audio",
            description="把当前用户有权访问的工作空间音频转成文字。返回持久任务 ID；不可直接访问文件或绕过权限。",
            args_schema=TranscribeAudioArgs,
        ),
        StructuredTool.from_function(
            func=_t_understand_audio,
            name="understand_audio",
            description="理解当前用户有权访问的音频并回答问题。文件通过短期签名 URL 发送，模型不会获得 OSS 密钥。",
            args_schema=UnderstandAudioArgs,
        ),
        StructuredTool.from_function(
            func=_t_synthesize_speech,
            name="synthesize_speech",
            description="使用当前用户获授权的企业音色生成语音。返回持久任务 ID；音色设计和克隆不在此工具中开放。",
            args_schema=SynthesizeSpeechArgs,
        ),
    ]
