"""Agent graph nodes — load_config / retrieve_rag / load_memory / agent_loop /
save_memory / extract_memory / judge / write_run_log.

图拓扑（线性，节点内按配置 no-op）：

    START → load_config → retrieve_rag → load_memory → agent_loop
          → save_memory → extract_memory → judge → write_run_log → END

agent_loop 内部完成 LLM ↔ 工具 多步循环（非图循环边），逐步经 stream_writer 下发事件。

两种模式（state["mode"]）：
- ``agent``：管理端测试广场，load_config 读预配置 ``Agent`` 行（单 RAG / session 记忆）。
- ``general``：终端通用智能体，按任务配置动态装配（多 RAG / 多 Ontology / 内置工作空间文件
  工具 / 4 级长期记忆 / 个人记忆沉淀），不创建 ``Agent`` 行。
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

import structlog

from app.agents import llm_client
from app.agents.graph.context import get_deps, get_stream_writer
from app.agents.graph.state import AgentState
from app.config import settings
from app.models.agent import Agent
from app.models.agent_run import AgentRun
from app.models.audit_log import AuditLog
from app.models.connector import ToolConnector, ToolEndpoint
from app.models.ontology import OntologyFile
from app.models.organization import Organization
from app.models.skill import SkillExecution, SkillFolder, SkillVersion
from app.schemas.rag import RagRetrieveRequest
from app.schemas.workspace import WorkspaceFileCreate
from app.services import (
    memory_service,
    scope_service,
    skill_import_service,
    skill_runner_client,
    skill_scope_service,
    workspace_service,
)
from app.services.rag_service import retrieve as rag_retrieve
from app.services.skill_store_service import SKILL_MANIFEST_PATH
from app.services.skill_store_service import get_file_by_path as get_skill_file_by_path
from app.tools.executor import execute_endpoint
from app.tools.skill_manifest import parse_skill_manifest

logger = structlog.get_logger()

MAX_STEPS = 8

GENERAL_SYSTEM_PROMPT = (
    "你是组织智能助手。你可以：调用已授权的技能（外部工具）完成业务操作；读写当前工作空间中的"
    "文件（list/read/write/delete）；参考注入的知识库检索结果、组织本体与四级长期记忆。"
    "请基于上述上下文完成用户任务，必要时分步调用工具，最终给出清晰的结果。"
)

# ── 执行模式（exec_mode）prompt 注入 ────────────────────────────────────
# Craft：自主多步执行（默认，挂全量工具）。Ask / Plan：不挂工具，单轮输出。
ASK_PROMPT = (
    "\n\n[执行模式：Ask 问答]\n当前为问答模式：仅依据上方上下文（长期记忆 / 组织本体 / 知识库检索）"
    "与对话历史直接回答用户问题。禁止调用任何工具、禁止读写或创建文件、禁止执行业务操作。"
    "信息不足时如实说明，不要编造。"
)
PLAN_PROMPT = (
    "\n\n[执行模式：Plan 规划]\n当前为规划模式：为用户需求产出一份可执行的分步计划，但不要真正执行、"
    "不要调用工具、不要读写文件。计划须包含：① 目标 ② 分步动作（每步说明做什么、会读写哪些工作空间"
    "文件、调用哪些技能/工具）③ 所需资源与前置条件 ④ 风险与验收标准。以结构化清单输出。"
)

# ── 工具调用策略（Craft 挂工具时注入）────────────────────────────────────
# 约束 agent「先分析再调用」：结合本体与数据接口目录确定最少的端点集合与入参，
# 而非把所有端点都试一遍；失败后据返回信息修正而非无差别重试。
TOOL_STRATEGY_PROMPT = (
    "\n\n[工具调用策略] 调用任何技能/端点前，请先按以下原则规划：\n"
    "1. 结合上方[组织本体]与[数据接口]目录，分析任务到底需要哪些数据或操作，确定**最少且最直接可达**"
    "的端点集合——不要把所有端点都试一遍，只调用与当前步骤真正相关的。\n"
    "2. 对每个选定端点，按其参数清单（名称/是否必填/类型）准备入参：优先使用任务上下文里已有的具体"
    "标识（款号、工单号、编码等），不要省略必填参数，也不要臆造值。\n"
    "3. 同一数据若可由「详情端点(path 参数)」或「列表端点(query 参数)」获取时按需选择——已知具体编码"
    "用详情端点，需筛选或枚举时用列表端点，避免对每个对象都先试详情再降级到列表。\n"
    "4. 调用失败时不要无差别重试：先据返回信息判断是参数缺失、值不存在还是路径错误，修正入参或换端点"
    "后再试；连续失败则停止并向用户说明，不要继续盲目调用。\n"
    "5. 若上方[已解析的文件引用]已经提供文件内容，直接使用该内容完成任务；不要为了确认 UUID 再调用"
    "`workspace_list_files` 或 `workspace_read_file`，也不要自行读取、分析用户未引用的其他文件。只有用户明确"
    "要求比较/遍历工作空间，或引用内容明确标记为不可用时，才调用文件工具。\n"
    "6. 对话历史中的[历史消息附件]只提供持久文件引用：用户要求继续分析时，使用其中 status=available 的"
    "准确 file_id 调用 workspace_read_file，并按 has_more/next_offset 继续分页。存在多个候选且用户指代不清时"
    "必须先询问，不得擅自读取全部文件；status=unavailable 时明确告知文件已删除或无权访问。"
)

# ── 输出协议（Craft 模式注入，场景无关 boilerplate，避免每个任务提示词重复）────
# 约束 agent「先输出完整分析，仅在任务明确要求时生成附件」+「不要臆造数据」。
# 任务提示词只需写业务目标、对象和期望交付物，不必重复这两段。
OUTPUT_PROTOCOL_PROMPT = (
    "\n\n[输出协议]\n"
    "1. 先在文本里流式输出完整分析。仅当用户请求或智能体任务说明明确要求生成、导出、下载、归档报告/附件时，"
    "才在分析完成后调用 `generate_docx`；普通问答、解释或文件分析不得擅自生成附件。需要生成时，不要直接"
    "跳到 docx，让屏幕只显示一句\"现在生成报告文档\"。\n"
    "2. 不要臆造数据：所有编码 / 工单号 / 款号 / 数值 / 结论必须来自已注入的数据接口返回、"
    "本体、知识库检索命中或用户给定，不可拼凑不存在的标识符。"
)



def _emit(event: dict) -> None:
    """经 stream_writer 下发事件（流式分支；非流式分支 writer 为 no-op）。"""
    try:
        writer = get_stream_writer()
        writer(json.dumps(event, ensure_ascii=False))
    except Exception:  # noqa: BLE001 — 非流式分支无 writer，忽略
        pass


# ── 内置工作空间文件工具 ─────────────────────────────────────────────────

BUILTIN_TOOL_NAMES = {"workspace_list_files", "workspace_read_file",
                       "workspace_write_file", "workspace_delete_file",
                       "generate_docx"}


def _builtin_tool_defs() -> list[dict]:
    """内置工作空间文件工具的 OpenAI function-tool 定义。"""
    return [
        {"type": "function", "function": {
            "name": "workspace_list_files",
            "description": (
                "列出当前工作空间中全部文件，返回每个文件的 file_id 与 path。"
                "仅在用户要求浏览、比较或遍历工作空间时调用。"
            ),
            "parameters": {"type": "object", "properties": {}},
        }},
        {"type": "function", "function": {
            "name": "workspace_read_file",
            "description": (
                "读取当前工作空间中的一个文件，可传 file_id 或 path。用户消息含 @UUID 时直接把 UUID 作为 file_id；"
                "若[已解析的文件引用]已经注入内容，无需重复调用。大文件结果包含 has_more 与 next_offset，"
                "必须按 next_offset 继续读取，不能把当前页当作完整文件。"
            ),
            "parameters": {"type": "object", "properties": {
                "file_id": {"type": "string", "description": "工作空间文件 UUID"},
                "path": {"type": "string", "description": "相对工作空间根的 POSIX 路径"},
                "offset": {"type": "integer", "minimum": 1,
                           "description": "从第几行开始读取（1-based，默认 1）"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000,
                          "description": "最多读取多少行（默认 200，最大 1000）"}},
            },
        }},
        {"type": "function", "function": {
            "name": "workspace_write_file",
            "description": "向当前工作空间写入（创建或覆盖）一个文件。",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"]},
        }},
        {"type": "function", "function": {
            "name": "workspace_delete_file",
            "description": "删除当前工作空间中指定路径的文件。",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"}}, "required": ["path"]},
        }},
        {"type": "function", "function": {
            "name": "generate_docx",
            "description": (
                "生成一份真正的 Word(.docx) 二进制文档并写入当前工作空间（可下载）。"
                "需要产出 Word 文档时务必用此工具，不要用 workspace_write_file 写 HTML 冒充 .docx。"
                "正文用 markdown：# / ## / ### 为标题，段落可含 **加粗**，- 无序列表，1. 有序列表，"
                "| a | b | 为表格。"
            ),
            "parameters": {"type": "object", "properties": {
                "filename": {"type": "string", "description": "文件名，含 .docx 后缀，如 请假条.docx"},
                "markdown": {"type": "string", "description": "文档正文 markdown"}},
                "required": ["filename", "markdown"]},
        }},
    ]


async def _execute_builtin_tool(state: AgentState, name: str, params: dict) -> str:
    """执行内置工作空间文件工具，返回结果文本。"""
    deps = get_deps()
    db = deps["db"]
    ws_id = state.get("workspace_id")
    if not ws_id:
        return "no workspace bound to this task"
    ws = await workspace_service.get_workspace(db, UUID(ws_id))
    if ws is None:
        return "workspace not found"
    user = deps.get("user")
    if user is not None and not scope_service.is_workspace_visible(ws, user):
        return "workspace out of your scope"

    # 用 SAVEPOINT 隔离本轮工具的 DB 写入：若 flush 失败（如唯一约束冲突），
    # 只回滚保存点，不污染 run 主事务。否则主事务进入 PendingRollback 态，
    # 后续 save_memory / write_run_log 的 flush 全部抛 PendingRollbackError，
    # _finalize_bg_error 又用独立会话收口、不提交主事务 → 本轮 assistant 消息
    # （仅在 save_memory 里 flush 未提交）被一并回滚，「任务回复消失」。
    try:
        async with db.begin_nested():
            if name == "workspace_list_files":
                files = await workspace_service.list_files(db, ws.id)
                return json.dumps(
                    [{"file_id": str(f.id), "path": f.path} for f in files],
                    ensure_ascii=False,
                )
            if name == "workspace_read_file":
                file_id = str(params.get("file_id") or "").strip()
                path = str(params.get("path") or "").strip()
                f = None
                if file_id:
                    try:
                        f = await workspace_service.get_file(db, UUID(file_id))
                    except (ValueError, AttributeError):
                        f = None
                    # 内置工具始终受当前任务绑定工作空间约束；不能借 file_id 跨工作空间读取。
                    if f is not None and str(f.workspace_id) != str(ws.id):
                        f = None
                elif path:
                    f = await workspace_service.get_file_by_path(db, ws.id, path)
                else:
                    return "file_id or path is required"
                if f is None:
                    return "file not found"
                try:
                    offset = int(params.get("offset", 1))
                    limit = int(params.get("limit", 200))
                except (TypeError, ValueError):
                    return json.dumps(
                        {"status": "error", "error": "offset and limit must be integers"},
                        ensure_ascii=False,
                    )
                return json.dumps(
                    workspace_service.paginate_file_content(f, offset=offset, limit=limit),
                    ensure_ascii=False,
                )
            if name == "workspace_write_file":
                # 标记产出文件归属的任务，供删除任务时一并清理工作空间输出。
                meta: dict = {}
                task_id = state.get("task_id")
                if task_id:
                    meta["task_id"] = task_id
                await workspace_service.upsert_file(db, ws, WorkspaceFileCreate(
                    path=params.get("path", ""), content=params.get("content", ""),
                    metadata=meta))
                return f"wrote {params.get('path', '')}"
            if name == "workspace_delete_file":
                f = await workspace_service.get_file_by_path(db, ws.id, params.get("path", ""))
                if f is None:
                    return "file not found"
                await workspace_service.soft_delete_file(db, f)
                return f"deleted {params.get('path', '')}"
            if name == "generate_docx":
                import base64 as _b64

                from app.tools.docx_builder import markdown_to_docx_bytes
                filename = (params.get("filename") or "document.docx").strip()
                if not filename.lower().endswith(".docx"):
                    filename += ".docx"
                raw = markdown_to_docx_bytes(params.get("markdown") or "")
                b64 = _b64.b64encode(raw).decode()
                meta: dict = {
                    "binary": True,
                    "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }
                task_id = state.get("task_id")
                if task_id:
                    meta["task_id"] = task_id
                await workspace_service.upsert_file(db, ws, WorkspaceFileCreate(
                    path=filename, content=b64, metadata=meta))
                return f"generated {filename} ({len(raw)} bytes)"
    except Exception as exc:  # noqa: BLE001
        logger.warning("builtin_tool_failed", tool=name, error=str(exc))
        return f"tool error: {exc}"
    return f"unknown builtin tool {name}"


# ── load_config ────────────────────────────────────────────────────────

async def load_config(state: AgentState) -> dict:
    """加载配置，创建 AgentRun（status=running），注入首轮 user 消息。

    agent 模式读 ``Agent`` 行；general 模式从任务配置装配并按用户权限解析自动匹配的资源。
    """
    deps = get_deps()
    db = deps["db"]

    if state.get("mode") == "general":
        return await _load_config_general(state, deps, db)

    # ── agent 模式 ──
    agent = await db.get(Agent, UUID(state["agent_id"]))
    if agent is None:
        return {"error": "agent not found"}

    run = AgentRun(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        session_id=state["session_id"],
        request=state.get("request", ""),
        exec_mode="craft",
        status="running",
    )
    db.add(run)
    await db.flush()

    messages: list[dict] = [{"role": "user", "content": state.get("request", "")}]

    _emit({"type": "step", "step": "load_config", "agent": agent.name})
    return {
        "run_id": run.id,
        "system_prompt": agent.system_prompt,
        "model_alias": agent.model_alias,
        "memory_config": agent.memory_config or {},
        "judge_config": agent.judge_config or {},
        "judge_template_id": str(agent.judge_template_id) if agent.judge_template_id else None,
        "skill_ids": list(agent.skill_ids or []),
        "temperature": agent.temperature,
        "max_tokens": agent.max_tokens,
        "workspace_id": str(agent.workspace_id) if agent.workspace_id else None,
        "rag_collection_id": str(agent.rag_collection_id) if agent.rag_collection_id else None,
        "messages": messages,
        "steps": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "tool_results": [],
        "traces": [],
        "org_id": str(agent.organization_id),
    }


async def _load_config_general(state: AgentState, deps, db) -> dict:
    """General mode: assemble only capabilities explicitly bound to the selected Agent."""
    user = deps.get("user")
    org_id = state["org_id"]

    # 可选「场景模板」：引用一个 Agent 行，其 system_prompt 作为 persona/policy 前缀
    # 拼到 GENERAL_SYSTEM_PROMPT 之前。承载场景 persona + 不可由本体/数据接口目录
    # 推导的业务规则 + 输出骨架。用户 composer 只写目标+对象，不必复制整套提示词。
    base_prompt = GENERAL_SYSTEM_PROMPT
    tpl_id = state.get("template_agent_id")
    tpl_traces: list[dict] = []
    if tpl_id:
        try:
            tpl = await db.get(Agent, UUID(str(tpl_id)))
        except Exception:  # noqa: BLE001
            tpl = None
        if tpl is not None and tpl.system_prompt:
            base_prompt = f"{tpl.system_prompt.rstrip()}\n\n{GENERAL_SYSTEM_PROMPT}"
            tpl_traces.append({"category": "template", "title": "场景模板注入",
                                "slug": tpl.slug, "chars": len(tpl.system_prompt)})
            if not state.get("model_alias") or state.get("model_alias") == "default":
                if tpl.model_alias and tpl.model_alias != "default":
                    state["model_alias"] = tpl.model_alias

    # Skills and RAG are capabilities explicitly bound to the selected Agent.
    # A general/unbound Agent intentionally receives neither.
    skill_ids = [str(s) for s in (tpl.skill_ids or [])] if tpl_id and tpl is not None else []
    ontology_ids = list(state.get("ontology_ids") or [])
    rag_ids = [str(r) for r in (tpl.rag_collection_ids or [])] if tpl_id and tpl is not None else []
    referenced_skills: list[dict] = []
    # 结构化附件优先进入 state；正文中的历史 @UUID 再补充，按出现顺序去重。
    referenced_file_ids: list[str] = []

    if user is not None:
        bound_skills = await skill_scope_service.assert_bound_skills_visible(db, user, skill_ids)
        skill_ids = [str(s.id) for s in bound_skills]
        bound_rags = await scope_service.assert_bound_rags_visible(db, user, rag_ids)
        rag_ids = [str(r.id) for r in bound_rags]
        if not ontology_ids:
            ontology_ids = [str(o.id) for o in await scope_service.list_ontologies_for_user(db, user)]
        # /slug can only force a Skill already bound to this Agent.
        slug_to_skill = {s.slug: s for s in bound_skills}
        seen_slugs: set[str] = set()
        for m in re.finditer(r'(?<![\w/])/([a-z0-9][a-z0-9-]*)', state.get("request", "") or ""):
            slug = m.group(1)
            s = slug_to_skill.get(slug)
            if s and slug not in seen_slugs:
                seen_slugs.add(slug)
                referenced_skills.append({"name": s.name, "slug": s.slug})
        # 解析用户消息中 @<file_id> 引用的工作空间文件（精确 UUID，避免误命中邮件等）。
        # agent_loop 读取这些文件内容注入 system prompt；越权文件在 agent_loop 校验时跳过。
        seen_fids: set[str] = set()
        for raw_fid in state.get("referenced_file_ids") or []:
            fid = str(raw_fid)
            if fid not in seen_fids:
                seen_fids.add(fid)
                referenced_file_ids.append(fid)
        for m in re.finditer(
            r'(?<![\w])@([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
            state.get("request", "") or "",
        ):
            fid = m.group(1)
            if fid not in seen_fids:
                seen_fids.add(fid)
                referenced_file_ids.append(fid)

    run = AgentRun(
        organization_id=org_id,
        agent_id=None,
        task_id=state.get("task_id"),
        user_id=state.get("user_id"),
        session_id=state["session_id"],
        request=state.get("request", ""),
        exec_mode=state.get("exec_mode") or "craft",
        status="running",
    )
    db.add(run)
    await db.flush()
    # 提前提交 run 行：让 agent_runs 行立即对其他会话可见（崩溃收口 _finalize_bg_error 能据此
    # 置 status=error；事件落库的独立会话也能满足 run_id 外键）。后台 runner 不再在此会话上
    # 提交事件——见 runner._run_graph_bg（避免与图节点 DB 调用并发争用同一 asyncpg 连接）。
    await db.commit()

    messages: list[dict] = [{"role": "user", "content": state.get("request", "")}]

    _emit({"type": "step", "step": "load_config", "mode": "general",
           "skills": len(skill_ids), "ontologies": len(ontology_ids), "rags": len(rag_ids),
           "referenced_skills": len(referenced_skills),
           "referenced_files": len(referenced_file_ids),
           "template": bool(tpl_traces),
           "run_id": run.id})
    for t in tpl_traces:
        _emit({"type": "trace", **t})
    return {
        "run_id": run.id,
        "system_prompt": base_prompt,
        "model_alias": state.get("model_alias") or "default",
        "memory_config": {"enabled": True},
        "judge_config": {},
        "judge_template_id": None,
        "skill_ids": skill_ids,
        "ontology_ids": ontology_ids,
        "rag_collection_ids": rag_ids,
        "referenced_skills": referenced_skills,
        "referenced_file_ids": referenced_file_ids,
        "workspace_id": state.get("workspace_id"),
        "temperature": None,
        "max_tokens": None,
        "messages": messages,
        "steps": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "tool_results": [],
        "traces": list(tpl_traces),
        "org_id": org_id,
    }


# ── retrieve_rag ───────────────────────────────────────────────────────

async def retrieve_rag(state: AgentState) -> dict:
    """检索 RAG 命中注入 rag_context。

    general 模式遍历多个 ``rag_collection_ids`` 合并 top-k；agent 模式维持单 ``rag_collection_id``。
    """
    deps = get_deps()
    db = deps["db"]
    from app.models.rag import RagCollection

    coll_ids: list[str] = []
    if state.get("mode") == "general":
        coll_ids = list(state.get("rag_collection_ids") or [])
    else:
        single = state.get("rag_collection_id")
        if single:
            coll_ids = [single]
    if not coll_ids:
        return {}

    merged: list[dict] = []
    for cid in coll_ids:
        coll = await db.get(RagCollection, UUID(cid))
        if coll is None:
            continue
        try:
            req = RagRetrieveRequest(query=state.get("request", ""), top_k=5)
            hits = await rag_retrieve(db, coll, UUID(state["org_id"]), req)
            for h in hits:
                merged.append({"content": h["content"], "score": h["score"],
                               "document_id": h["document_id"], "collection_id": cid,
                               "metadata": h.get("metadata") or {}})
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent_rag_retrieve_failed", coll=str(cid), error=str(exc))

    merged.sort(key=lambda h: h.get("score", 0.0), reverse=True)
    merged = merged[:8]
    preview = [h["content"][:120] for h in merged[:3]]
    # 命中 metadata.retriever='keyword_fallback' 说明向量通道不可用、走了关键词兜底
    retriever = next(
        (h.get("metadata", {}).get("retriever") for h in merged
         if isinstance(h.get("metadata"), dict) and h["metadata"].get("retriever")),
        "vector",
    )
    title = "知识库检索" if retriever == "vector" else "知识库检索（关键词兜底）"
    trace = {"category": "rag", "title": title, "retriever": retriever,
             "collections": len(coll_ids), "hits": len(merged), "preview": preview}
    _emit({"type": "trace", **trace})
    return {
        "rag_context": merged,
        "steps": [*state.get("steps", []), {"step": "rag", "hits": len(merged),
                                            "collections": len(coll_ids)}],
        "traces": [*state.get("traces", []), trace],
    }


# ── load_memory ────────────────────────────────────────────────────────

async def load_memory(state: AgentState) -> dict:
    """载入记忆前置到 messages。

    agent 模式：按 session 加载最近 N 条 ``AgentMessage`` 历史。
    general 模式：① 按 task 加载 ``TaskMessage`` 对话历史前置；② 按用户权限聚合 4 级 ``Memory``
    长期记忆填入 ``memory_context``（供 agent_loop 注入 system_prompt）。
    """
    deps = get_deps()
    db = deps["db"]
    from sqlalchemy import select

    if state.get("mode") == "general":
        return await _load_memory_general(state, deps, db, select)

    # ── agent 模式 ──
    mem_cfg = state.get("memory_config") or {}
    if not mem_cfg.get("enabled", False):
        return {}
    from app.models.agent_memory import AgentMessage

    limit = int(mem_cfg.get("max_messages", 10))
    rows = await db.execute(
        select(AgentMessage)
        .where(AgentMessage.agent_id == UUID(state["agent_id"]), AgentMessage.session_id == state["session_id"])
        .order_by(AgentMessage.created_at.desc())
        .limit(limit)
    )
    history = list(rows.scalars().all())
    history.reverse()
    current = state.get("messages", [])
    past = [{"role": m.role, "content": m.content} for m in history if m.role in ("user", "assistant")]
    return {"messages": past + current}


async def _load_memory_general(state: AgentState, deps, db, select) -> dict:
    from app.models.task import TaskMessage
    from app.models.workspace import WorkspaceFile

    task_id = state.get("task_id")
    current = state.get("messages", [])
    past: list[dict] = []
    if task_id:
        rows = await db.execute(
            select(TaskMessage)
            .where(TaskMessage.task_id == UUID(task_id))
            .order_by(TaskMessage.created_at.desc())
            .limit(20)
        )
        history = list(rows.scalars().all())
        history.reverse()
        attachment_ids: set[UUID] = set()
        for message in history:
            if message.role != "user":
                continue
            for attachment in (message.metadata_ or {}).get("attachments", []):
                try:
                    attachment_ids.add(UUID(str(attachment.get("file_id") or "")))
                except (ValueError, TypeError, AttributeError):
                    continue

        available_files: dict[str, WorkspaceFile] = {}
        bound_workspace_id = str(state.get("workspace_id") or "")
        user = deps.get("user")
        workspace_visible = False
        if bound_workspace_id and user is not None:
            try:
                workspace = await workspace_service.get_workspace(db, UUID(bound_workspace_id))
            except (ValueError, TypeError, AttributeError):
                workspace = None
            workspace_visible = bool(
                workspace is not None and scope_service.is_workspace_visible(workspace, user)
            )
        if attachment_ids and workspace_visible:
            file_rows = await db.execute(
                select(WorkspaceFile).where(
                    WorkspaceFile.id.in_(attachment_ids),
                    WorkspaceFile.deleted_at.is_(None),
                )
            )
            available_files = {str(f.id): f for f in file_rows.scalars().all()}

        past = []
        for message in history:
            if message.role not in ("user", "assistant"):
                continue
            content = message.content
            if message.role == "user":
                refs: list[dict] = []
                for attachment in (message.metadata_ or {}).get("attachments", []):
                    file_id = str(attachment.get("file_id") or "")
                    if not file_id:
                        continue
                    expected_workspace_id = str(attachment.get("workspace_id") or "")
                    file = available_files.get(file_id)
                    available = bool(
                        file is not None
                        and str(file.workspace_id) == bound_workspace_id
                        and expected_workspace_id == bound_workspace_id
                    )
                    refs.append({
                        "file_id": file_id,
                        "name": str(attachment.get("name") or attachment.get("path") or file_id),
                        "status": "available" if available else "unavailable",
                    })
                if refs:
                    content += "\n\n[历史消息附件]\n" + json.dumps(refs, ensure_ascii=False)
            past.append({"role": message.role, "content": content})

    # 4 级长期记忆：按用户权限自动载入全集（组织 + 部门 + 团队 + 个人），无需任务配置。
    user = deps.get("user")
    mem_context: list[dict] = []
    if user is not None:
        scopes = scope_service.effective_scope_set(user)  # [(type, id|None)]
        try:
            mem_context = await memory_service.load_memory_for_scopes(
                db, UUID(state["org_id"]), scopes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("load_memory_failed", error=str(exc))

    trace = {"category": "memory", "subtype": "load", "title": "长期记忆载入",
             "history": len(past), "facts": len(mem_context)}
    _emit({"type": "trace", **trace})
    return {
        "messages": past + current,
        "memory_context": mem_context,
        "steps": [*state.get("steps", []), {"step": "memory", "history": len(past),
                                            "facts": len(mem_context)}],
        "traces": [*state.get("traces", []), trace],
    }


# ── agent_loop ─────────────────────────────────────────────────────────

async def _build_tools(
    db, skill_ids: list[str], workspace_id: str | None, user=None,
) -> tuple[list[dict], dict[str, dict]]:
    """加载技能文件夹 → 读取 skill.md manifest → OpenAI tools 列表 + name→(folder, endpoint) 映射。

    技能已文件夹化：每个 SkillFolder 的 ``skill.md`` 含 ```skill JSON 块定义
    （name / description / parameters / bound_endpoint_ids）。一个技能可绑定多个端点，
    这里为**每个绑定端点各发一个 function-tool**，让 LLM 直接按端点名/描述选用，
    避免"只调 endpoints[0]"导致其余端点永远不可达。manifest 缺失或非法则跳过。
    """
    tools: list[dict] = []
    registry: dict[str, dict] = {}
    agent_skills: dict[str, dict] = {}
    for sid in skill_ids:
        folder = await db.get(SkillFolder, UUID(sid))
        if folder is None or folder.deleted_at is not None or not folder.is_active:
            continue
        if user is not None and not skill_scope_service.user_can_use_folder(user, folder):
            continue
        version = await db.get(SkillVersion, folder.active_version_id) if folder.active_version_id else None
        if version is not None and version.install_status != "ready":
            continue
        platform = (
            version.manifest.get("_platform")
            if version is not None and isinstance(version.manifest, dict) else None
        )
        if isinstance(platform, dict) and platform.get("package_format") == "agent_skill":
            organization = await db.get(Organization, folder.organization_id)
            if organization is None or not settings.agent_skills_enabled_for(organization.slug):
                continue
            try:
                skill_path = next(
                    item["path"] for item in platform.get("resources", [])
                    if PurePosixPath(str(item.get("path") or "")).name.lower() == "skill.md"
                )
                skill_content = skill_import_service.read_version_resource(version, skill_path).decode("utf-8")
            except (StopIteration, UnicodeDecodeError, KeyError):
                logger.warning("agent_skill_manifest_unavailable", skill_folder=str(folder.id), slug=folder.slug)
                continue
            agent_skills[folder.slug] = {
                "folder": folder, "version": version, "content": skill_content,
                "platform": platform,
            }
            continue
        manifest_file = await get_skill_file_by_path(db, folder.id, SKILL_MANIFEST_PATH)
        manifest = parse_skill_manifest(manifest_file.content if manifest_file else None)
        if manifest is None:
            logger.warning("skill_manifest_missing_or_invalid", skill_folder=str(folder.id), slug=folder.slug)
            continue
        if version is not None and version.is_executable:
            if not settings.code_skills_enabled:
                continue
            tool_name = re.sub(r"[^a-zA-Z0-9_-]", "_", manifest.command or folder.slug)[:64]
            params = dict(manifest.parameters or {"type": "object", "properties": {}})
            params.setdefault("type", "object")
            properties = dict(params.get("properties") or {})
            properties.setdefault("input_file_ids", {
                "type": "array", "items": {"type": "string"},
                "description": "工作空间输入文件 UUID；未传时使用本轮聊天附件",
            })
            params["properties"] = properties
            tools.append({"type": "function", "function": {
                "name": tool_name,
                "description": manifest.description or folder.name,
                "parameters": params,
            }})
            registry[tool_name] = {"kind": "code", "folder": folder, "version": version}
            continue
        if version is not None and not manifest.bound_endpoint_ids:
            tool_name = f"load_{re.sub(r'[^a-zA-Z0-9_-]', '_', folder.slug)[:55]}"
            tools.append({"type": "function", "function": {
                "name": tool_name,
                "description": manifest.description or f"载入技能 {folder.name} 的详细操作说明",
                "parameters": {"type": "object", "properties": {}},
            }})
            registry[tool_name] = {
                "kind": "prompt", "folder": folder,
                "content": manifest_file.content or "",
            }
            continue
        for eid in manifest.bound_endpoint_ids:
            try:
                ep = await db.get(ToolEndpoint, UUID(eid))
            except (ValueError, AttributeError):
                ep = None
            if not (ep and ep.is_active):
                continue
            # 命名空间防碰撞：manifest.name 跨技能唯一，ep.name 技能内唯一。
            tool_name = f"{manifest.name}__{ep.name}"
            # manifest.parameters 含手工策划的 properties 时优先；否则用端点自带 params_schema。
            # 注意 `{"type":"object","properties":{}}` 是 seed 脚本的占位空 schema，
            # 真值判定会把这种占位当成"有手工 schema"，导致端点 schema 被覆盖、LLM 不传参。
            mp = manifest.parameters or {}
            mp_props = mp.get("properties") if isinstance(mp, dict) else None
            if mp_props:
                params = mp
            else:
                params = ep.params_schema or {"type": "object", "properties": {}}
            tools.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": ep.description or manifest.description or "",
                    "parameters": params,
                },
            })
            registry[tool_name] = {"folder": folder, "endpoint": ep}
    if agent_skills:
        summaries = "; ".join(
            f"{slug}: {entry['version'].manifest.get('description') or entry['folder'].name}"
            for slug, entry in agent_skills.items()
        )
        slug_schema = {"type": "string", "enum": sorted(agent_skills)}
        tools.extend([
            {"type": "function", "function": {
                "name": "load_skill",
                "description": "按需载入已绑定标准 Skill 的完整 SKILL.md。可用技能：" + summaries,
                "parameters": {"type": "object", "properties": {
                    "skill_slug": {**slug_schema, "description": "要载入的技能 slug"},
                }, "required": ["skill_slug"]},
            }},
            {"type": "function", "function": {
                "name": "read_skill_resource",
                "description": "读取已载入 Skill 中 references/、assets/ 或脚本说明等文本资源。",
                "parameters": {"type": "object", "properties": {
                    "skill_slug": slug_schema,
                    "path": {"type": "string", "description": "资源索引中显示的相对路径"},
                }, "required": ["skill_slug", "path"]},
            }},
        ])
        if any(entry["version"].is_executable for entry in agent_skills.values()):
            tools.append({"type": "function", "function": {
                "name": "run_skill_script",
                "description": (
                    "在隔离 Runner 中执行已绑定 Skill 的 scripts/ 内 Python、Node 或 Bash 脚本。"
                    "先调用 load_skill 并遵循其说明。"
                ),
                "parameters": {"type": "object", "properties": {
                    "skill_slug": slug_schema,
                    "script_path": {"type": "string", "description": "load_skill 返回的 scripts/ 相对路径"},
                    "args": {
                        "type": "array", "items": {"type": "string"},
                        "description": "直接传给脚本的参数数组，不是 Shell 命令",
                    },
                    "input_file_ids": {
                        "type": "array", "items": {"type": "string"},
                        "description": "工作空间输入文件 UUID；省略时使用本轮附件",
                    },
                }, "required": ["skill_slug", "script_path"]},
            }})
        tool_names = ["load_skill", "read_skill_resource"]
        if any(entry["version"].is_executable for entry in agent_skills.values()):
            tool_names.append("run_skill_script")
        for name in tool_names:
            registry[name] = {"kind": name, "skills": agent_skills}
    if workspace_id:
        tools.extend(_builtin_tool_defs())
    return tools, registry


async def _execute_code_skill(
    state: AgentState, entry: dict, params: dict, *,
    script_path: str | None = None, script_args: list[str] | None = None,
) -> str:
    deps = get_deps()
    db = deps["db"]
    user = deps.get("user")
    folder: SkillFolder = entry["folder"]
    version: SkillVersion = entry["version"]
    if user is None or not skill_scope_service.user_can_use_folder(user, folder):
        return json.dumps({"status": "error", "error": "Skill is outside the current user scope"})
    # Re-check mutable authorization/lifecycle state immediately before each
    # execution. A Skill may be disabled, upgraded, or revoked after the LLM
    # received its tool schema but before it returns the tool call.
    await db.refresh(folder)
    await db.refresh(version)
    if not folder.is_active or str(folder.active_version_id or "") != str(version.id):
        return json.dumps({"status": "error", "error": "Skill is disabled or its active version changed"})
    if version.install_status != "ready" or not version.is_executable:
        return json.dumps({"status": "error", "error": "Skill version is not executable"})
    if version.runtime == "agent_skill":
        organization = await db.get(Organization, folder.organization_id)
        if organization is None or not settings.agent_skills_enabled_for(organization.slug):
            return json.dumps({"status": "error", "error": "Agent Skills are not enabled for this organization"})
    if state.get("exec_mode") != "craft":
        return json.dumps({"status": "error", "error": "请切换到 Craft 模式执行代码 Skill"}, ensure_ascii=False)
    ws_id = state.get("workspace_id")
    if not ws_id:
        return json.dumps({"status": "error", "error": "请先绑定工作空间"}, ensure_ascii=False)
    ws = await workspace_service.get_workspace(db, UUID(ws_id))
    if ws is None or not scope_service.is_workspace_visible(ws, user):
        return json.dumps({"status": "error", "error": "Workspace is unavailable"})
    params = dict(params)
    requested_ids = params.pop("input_file_ids", None) or state.get("referenced_file_ids") or []
    if script_path is not None:
        platform = version.manifest.get("_platform") if isinstance(version.manifest, dict) else None
        allowed_scripts = {
            str(item.get("path")) for item in (platform.get("scripts") if isinstance(platform, dict) else [])
            if isinstance(item, dict) and item.get("path")
        }
        if script_path not in allowed_scripts:
            return json.dumps({"status": "error", "error": "Script is not declared in this Skill version"})
    inputs: list[dict] = []
    valid_ids: list[str] = []
    for value in requested_ids:
        try:
            file = await workspace_service.get_file(db, UUID(str(value)))
        except (ValueError, TypeError, AttributeError):
            file = None
        if file is None or str(file.workspace_id) != str(ws.id):
            return json.dumps({"status": "error", "error": f"Input file {value} is unavailable"})
        meta = file.metadata_ or {}
        if meta.get("binary"):
            raw = await workspace_service.load_file_bytes(file)
            content = base64.b64encode(raw).decode("ascii")
        else:
            content = base64.b64encode((file.content or "").encode("utf-8")).decode("ascii")
        inputs.append({
            "file_id": str(file.id),
            "name": str(meta.get("name") or PurePosixPath(file.path).name),
            "content_base64": content,
        })
        valid_ids.append(str(file.id))

    execution = SkillExecution(
        organization_id=UUID(state["org_id"]),
        user_id=UUID(user.id),
        task_id=UUID(state["task_id"]) if state.get("task_id") else None,
        agent_id=UUID(state["template_agent_id"]) if state.get("template_agent_id") else None,
        skill_folder_id=folder.id,
        skill_version_id=version.id,
        input_file_ids=valid_ids,
        params=params,
        status="running",
    )
    db.add(execution)
    await db.flush()
    try:
        result, latency = await skill_runner_client.execute_version(
            version, params=params, inputs=inputs, execution_id=execution.id,
            script_path=script_path, args=script_args,
        )
        output_ids: list[str] = []
        output_items: list[dict] = []
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        task_part = state.get("task_id") or "playground"
        for item in result.get("outputs") or []:
            raw = base64.b64decode(item.get("content_base64") or "", validate=True)
            original = PurePosixPath(str(item.get("name") or "output.bin")).name
            path = f"技能输出/{task_part}/{stamp}-{uuid4().hex[:8]}-{original}"
            saved = await workspace_service.ingest_uploaded_file(
                db, ws, path=path, filename=original,
                content_type=mimetypes.guess_type(original)[0], raw=raw,
            )
            output_ids.append(str(saved.id))
            output_items.append({
                "file_id": str(saved.id), "name": original, "path": saved.path,
                "parse_status": saved.parse_status,
            })
        execution.status = "success"
        execution.latency_ms = latency
        execution.output_file_ids = output_ids
        await db.flush()
        return json.dumps({
            "status": "success", "skill": folder.name,
            "summary": result.get("stdout") or "执行完成", "outputs": output_items,
        }, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        execution.status = "failed"
        execution.error = str(exc)[:2000]
        await db.flush()
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)


async def _resolve_agent_skill(state: AgentState, entry: dict, slug: str) -> tuple[dict | None, str | None]:
    selected = entry.get("skills", {}).get(slug)
    if selected is None:
        return None, "Skill is not bound to the current agent"
    deps = get_deps()
    db = deps["db"]
    user = deps.get("user")
    folder: SkillFolder = selected["folder"]
    version: SkillVersion = selected["version"]
    if user is None or not skill_scope_service.user_can_use_folder(user, folder):
        return None, "Skill is outside the current user scope"
    await db.refresh(folder)
    await db.refresh(version)
    if not folder.is_active or str(folder.active_version_id or "") != str(version.id):
        return None, "Skill is disabled or its active version changed"
    if version.install_status != "ready":
        return None, "Skill version is not ready"
    organization = await db.get(Organization, folder.organization_id)
    if organization is None or not settings.agent_skills_enabled_for(organization.slug):
        return None, "Agent Skills are not enabled for this organization"
    return selected, None


async def _execute_agent_skill_tool(state: AgentState, entry: dict, name: str, params: dict) -> str:
    slug = str(params.get("skill_slug") or "")
    selected, error = await _resolve_agent_skill(state, entry, slug)
    if error or selected is None:
        return json.dumps({"status": "error", "error": error or "Skill unavailable"}, ensure_ascii=False)
    platform = selected["platform"]
    if name == "load_skill":
        return json.dumps({
            "status": "success",
            "skill": {"name": selected["folder"].name, "slug": slug},
            "instructions": selected["content"],
            "scripts": platform.get("scripts") or [],
            "resources": platform.get("resources") or [],
            "compatibility_warnings": platform.get("compatibility_warnings") or [],
            "execution_contract": {
                "input_dir": "SKILL_INPUT_DIR", "output_dir": "SKILL_OUTPUT_DIR",
                "skill_dir": "SKILL_DIR", "params_json": "SKILL_PARAMS_JSON",
                "argument_placeholders": ["{input_file}", "{input_dir}", "{output_dir}", "{params_json}"],
            },
        }, ensure_ascii=False)
    if name == "read_skill_resource":
        path = str(params.get("path") or "")
        indexed = {str(item.get("path")) for item in platform.get("resources") or [] if isinstance(item, dict)}
        if path not in indexed:
            return json.dumps({"status": "error", "error": "Resource is not part of this Skill version"})
        try:
            raw = skill_import_service.read_version_resource(selected["version"], path)
            if len(raw) > 200_000:
                return json.dumps({"status": "error", "error": "Text resource exceeds 200KB"})
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            return json.dumps({"status": "error", "error": "Binary assets cannot be injected into the model"})
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"status": "error", "error": str(exc)})
        return json.dumps({"status": "success", "path": path, "content": content}, ensure_ascii=False)
    if name == "run_skill_script":
        raw_args = params.get("args") or []
        if not isinstance(raw_args, list) or not all(isinstance(value, str) for value in raw_args):
            return json.dumps({"status": "error", "error": "args must be an array of strings"})
        execution_params = {
            key: value for key, value in params.items()
            if key not in {"skill_slug", "script_path", "args"}
        }
        return await _execute_code_skill(
            state, selected, execution_params,
            script_path=str(params.get("script_path") or ""), script_args=raw_args,
        )
    return json.dumps({"status": "error", "error": "Unknown Agent Skill tool"})


async def _execute_tool_call(
    state: AgentState, tool_call: dict, registry: dict[str, dict],
) -> tuple[dict, str, bool]:
    """执行单个 tool_call，返回 (tool 消息, 结果预览, 是否成功)。

    不负责 emit——由 agent_loop 在调用前后下发 tool_call/tool_result 事件。
    """
    deps = get_deps()
    db = deps["db"]
    name = tool_call.get("name", "")
    args = tool_call.get("arguments", "{}")
    try:
        params = json.loads(args) if isinstance(args, str) else (args or {})
    except json.JSONDecodeError:
        params = {}

    tool_call_id = tool_call.get("id", "")

    # 内置工作空间文件工具
    if name in BUILTIN_TOOL_NAMES:
        result_text = await _execute_builtin_tool(state, name, params)
        ok = not result_text.startswith(("no ", "workspace ", "file not found",
                                         "tool error", "unknown builtin"))
        if ok:
            try:
                structured_result = json.loads(result_text)
            except (json.JSONDecodeError, TypeError):
                structured_result = None
            if isinstance(structured_result, dict) and structured_result.get("status") in {
                "error", "unavailable",
            }:
                ok = False
        preview = result_text
        if len(preview) > 4000:
            preview = preview[:4000] + "\n[工具结果预览已截断，模型已收到完整分页结果]"
        return ({"role": "tool", "tool_call_id": tool_call_id, "content": result_text},
                preview, ok)

    entry = registry.get(name)
    if entry is None:
        msg = f"tool '{name}' not found"
        return ({"role": "tool", "tool_call_id": tool_call_id, "content": msg}, msg, False)

    if entry.get("kind") == "prompt":
        content = entry.get("content") or ""
        return ({"role": "tool", "tool_call_id": tool_call_id, "content": content}, content[:4000], True)
    if entry.get("kind") == "code":
        content = await _execute_code_skill(state, entry, params)
        try:
            ok = json.loads(content).get("status") == "success"
        except (json.JSONDecodeError, AttributeError):
            ok = False
        return ({"role": "tool", "tool_call_id": tool_call_id, "content": content}, content[:4000], ok)
    if entry.get("kind") in {"load_skill", "read_skill_resource", "run_skill_script"}:
        content = await _execute_agent_skill_tool(state, entry, entry["kind"], params)
        try:
            ok = json.loads(content).get("status") == "success"
        except (json.JSONDecodeError, AttributeError):
            ok = False
        return ({"role": "tool", "tool_call_id": tool_call_id, "content": content}, content[:4000], ok)

    folder: SkillFolder = entry["folder"]
    ep: ToolEndpoint = entry["endpoint"]
    conn = await db.get(ToolConnector, ep.connector_id)
    if conn is None:
        msg = "connector not found"
        return ({"role": "tool", "tool_call_id": tool_call_id, "content": msg}, msg, False)

    try:
        result = await execute_endpoint(
            db, org_id=UUID(state["org_id"]), connector=conn, endpoint=ep,
            params=params, skill_id=folder.id,
        )
        preview = json.dumps(result.body, ensure_ascii=False) if result.body is not None else (result.error or "")
        ok = 200 <= int(result.status_code or 0) < 400
        return ({"role": "tool", "tool_call_id": tool_call_id, "content": preview[:4000]},
                preview[:4000], ok)
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool_call_failed", tool=name, error=str(exc))
        msg = f"tool error: {exc}"
        return ({"role": "tool", "tool_call_id": tool_call_id, "content": msg}, msg, False)


def _format_data_interface_params(di) -> str:
    """把数据接口 params_schema 压缩成一行参数提示，供 agent 规划时判断该提交哪些入参。

    形如 ``参数: style_code!(str), days(str)``——``!`` 表示必填（required）。
    schema 缺失或无 properties 时返回空串（不额外渲染）。
    """
    schema = di.params_schema or {}
    if not isinstance(schema, dict):
        return ""
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    if not props:
        return ""
    required = set(schema.get("required") or [])
    parts = []
    for pname, pschema in props.items():
        ptype = (pschema or {}).get("type", "any") if isinstance(pschema, dict) else "any"
        mark = "!" if pname in required else ""
        desc = (pschema or {}).get("description") if isinstance(pschema, dict) else None
        seg = f"{pname}{mark}({ptype})"
        if desc:
            seg += f":{str(desc)[:24]}"
        parts.append(seg)
    return "\n  参数: " + ", ".join(parts)


def _compact_ontologies(files: list[OntologyFile]) -> str:
    """把多个本体 Markdown 文件压缩为可注入 system_prompt 的文本。

    本体已文件化：每个 OntologyFile 的 content 即 Markdown 文本，直接按文件拼接，
    每段以文件路径为标题，便于智能体引用。
    """
    parts: list[str] = []
    for f in files:
        content = (f.content or "").strip()
        if not content:
            continue
        parts.append(f"[本体 {f.path}]\n{content}")
    return "\n\n".join(parts)


async def agent_loop(state: AgentState) -> dict:
    """LLM ↔ 工具 多步循环。流式 chat：逐 token 下发文本 + 工具调用块（tool_call/tool_result）。

    事件协议（经 stream_writer）：
    - ``phase``   每轮 LLM 开始
    - ``text``    逐 token 文本增量（终答实时流出）
    - ``tool_call``    工具调用前（name+arguments），前端立即显示「调用中」
    - ``tool_result``  工具执行后（content+ok）
    - ``done``    收口（usage）
    """
    deps = get_deps()
    db = deps["db"]
    messages: list[dict] = list(state.get("messages", []))
    steps: list[dict] = list(state.get("steps", []))
    traces: list[dict] = list(state.get("traces", []))
    usage_in = int(state.get("usage", {}).get("input_tokens", 0))
    usage_out = int(state.get("usage", {}).get("output_tokens", 0))

    # 注入长期记忆 / 组织本体 / 数据接口 / RAG 上下文到 system prompt
    system_prompt = state.get("system_prompt", "")
    mem_ctx = state.get("memory_context") or []
    if mem_ctx:
        # 记忆内容为 markdown：按条用 scope 标签行 + 原文拼接，避免把整段 markdown 压成单行。
        parts = [f"[{m['scope_type']}{('/' + m['category']) if m.get('category') else ''}]\n{m['content']}"
                 for m in mem_ctx]
        mem_text = "\n\n".join(parts)
        system_prompt = f"{system_prompt}\n\n[长期记忆]\n{mem_text}"
    if state.get("mode") == "general":
        ontology_ids = state.get("ontology_ids") or []
        if ontology_ids:
            ontologies = [o for o in [await db.get(OntologyFile, UUID(oid)) for oid in ontology_ids] if o]
            ont_text = _compact_ontologies(ontologies)
            if ont_text:
                system_prompt = f"{system_prompt}\n\n[组织本体]\n{ont_text}"
            ont_trace = {"category": "ontology", "title": "组织本体注入",
                         "files": len(ontologies), "paths": [o.path for o in ontologies]}
            _emit({"type": "trace", **ont_trace})
            traces.append(ont_trace)
        # 数据接口：按用户权限自动载入可用接口（管理端目录，仅供参考参数/返回结构，
        # 不真正执行），压缩注入 system_prompt，并留痕。user 缺失（agent 模式）则跳过。
        user = deps.get("user")
        if user is not None:
            try:
                di_list = await scope_service.list_data_interfaces_for_user(db, user)
            except Exception as exc:  # noqa: BLE001
                logger.warning("load_data_interfaces_failed", error=str(exc))
                di_list = []
            if di_list:
                system_names = sorted({(di.system.name if di.system else "?") for di in di_list})
                di_lines = []
                for di in di_list:
                    sys_name = di.system.name if di.system else "?"
                    params_hint = _format_data_interface_params(di)
                    di_lines.append(
                        f"- {sys_name}/{di.name}"
                        f"{f' {di.method}' if di.method else ''}"
                        f"{f' {di.path}' if di.path else ''}"
                        f"{f': {di.description}' if di.description else ''}"
                        f"{params_hint}"
                    )
                system_prompt = (
                    f"{system_prompt}\n\n[数据接口] 以下为当前可用数据接口"
                    "（仅供参考其参数/返回结构，不能直接执行调用；path 中 {占位符} 为路径参数，"
                    "调用时须提供实际值）：\n" + "\n".join(di_lines)
                )
            di_trace = {"category": "data_interface", "title": "数据接口注入",
                        "systems": len(system_names) if di_list else 0,
                        "interfaces": len(di_list),
                        "names": [f"{(di.system.name if di.system else '?')}/{di.name}" for di in di_list]}
            _emit({"type": "trace", **di_trace})
            traces.append(di_trace)
    rag_ctx = state.get("rag_context") or []
    if rag_ctx:
        ctx_text = "\n\n---\n".join(c["content"] for c in rag_ctx)
        system_prompt = f"{system_prompt}\n\n[知识库检索结果]\n{ctx_text}"

    # 用户通过结构化附件或 @<file_id> 引用的工作空间文件：读取内容注入 system prompt。
    # Office/PDF 二进制文件使用工作空间已提取文本，绝不把 Base64 注入模型。
    # 越权（不在用户 scope 内）文件跳过。文件是上下文，Ask/Plan 也注入。
    ref_file_ids = state.get("referenced_file_ids") or []
    if ref_file_ids:
        user = deps.get("user")
        file_parts: list[str] = []
        file_names: list[str] = []
        file_refs: list[dict[str, str]] = []
        for fid in ref_file_ids:
            try:
                f = await workspace_service.get_file(db, UUID(fid))
            except (ValueError, AttributeError):
                f = None
            if f is None or not f.workspace_id:
                continue
            ws = await workspace_service.get_workspace(db, UUID(str(f.workspace_id)))
            if ws is None or (user is not None and not scope_service.is_workspace_visible(ws, user)):
                continue  # 文件不可见，跳过
            file_names.append(f.path)
            file_refs.append({"file_id": fid, "path": f.path})
            content = workspace_service.resolve_file_content(f)
            rendered = content if content.strip() else "（文件内容为空或尚未解析，无法直接分析）"
            file_parts.append(f"[引用文件 file_id={fid} path={f.path}]\n{rendered}")
        if file_refs:
            mapping = "\n".join(f"- @{r['file_id']} → {r['path']}" for r in file_refs)
            system_prompt = (
                f"{system_prompt}\n\n[已解析的文件引用]\n"
                "本轮结构化附件或用户消息中的 @UUID 已由系统精确解析，映射如下：\n"
                f"{mapping}\n"
                "这些文件内容已直接载入下方上下文。请把 UUID 与对应路径视为同一个文件，不得声称无法按 UUID 定位；"
                "除非用户明确要求比较其他文件，否则不要调用工作空间列表/读取工具，也不要分析未引用文件。\n\n"
                + "\n\n".join(file_parts)
            )
        file_trace = {"category": "file", "title": "引用工作空间文件",
                      "files": len(file_names), "paths": file_names, "references": file_refs}
        _emit({"type": "trace", **file_trace})
        traces.append(file_trace)

    # 执行模式：Craft 挂全量工具自主多步执行；Ask / Plan 不挂工具（tools=None → 单轮、无 tool_call），
    # 仅追加模式 prompt 约束输出。
    exec_mode = state.get("exec_mode") or "craft"
    if exec_mode == "ask":
        system_prompt = f"{system_prompt}{ASK_PROMPT}"
        tools, registry = [], {}
    elif exec_mode == "plan":
        system_prompt = f"{system_prompt}{PLAN_PROMPT}"
        tools, registry = [], {}
    else:
        tools, registry = await _build_tools(
            db, state.get("skill_ids") or [], state.get("workspace_id"), deps.get("user"),
        )
        # 挂载了工具 → 注入「先分析再调用」策略，约束 agent 结合本体/数据接口规划最少端点集，
        # 而非盲目把所有端点试一遍。
        system_prompt = f"{system_prompt}{TOOL_STRATEGY_PROMPT}"
        # 输出协议（场景无关）：先 text 流式分析后 generate_docx + 不臆造数据。
        # 上提到 runtime 后任务提示词不必再重复这两段 boilerplate。
        system_prompt = f"{system_prompt}{OUTPUT_PROTOCOL_PROMPT}"
        # 用户在消息中以 /slug 引用了具体技能 → 注入「主动调用」指令（仅 Craft 挂工具时生效）。
        referenced = state.get("referenced_skills") or []
        if referenced:
            lines = "\n".join(f"- {s['name']} (/{s['slug']})" for s in referenced)
            system_prompt = (
                f"{system_prompt}\n\n[用户引用的技能] 用户在消息中以 /slug 引用了以下技能，"
                "执行任务时请主动调用这些技能完成相关操作（在相关步骤务必实际调用，而非仅提及）：\n"
                f"{lines}"
            )
            skill_trace = {"category": "skill", "title": "引用技能",
                           "skills": [{"name": s["name"], "slug": s["slug"]} for s in referenced]}
            _emit({"type": "trace", **skill_trace})
            traces.append(skill_trace)

    assistant_final = ""
    for step_idx in range(MAX_STEPS):
        _emit({"type": "phase", "phase": "llm", "index": step_idx})
        round_text = ""
        round_tool_calls: list[dict] = []
        try:
            async for kind, payload, extra in llm_client.stream_chat(
                db, UUID(state["org_id"]), state.get("model_alias", "default"), messages,
                system_prompt=system_prompt,
                temperature=state.get("temperature"),
                max_tokens=state.get("max_tokens"),
                tools=tools or None,
                dept_id=state.get("department_id"),
                team_id=state.get("team_id"),
            ):
                if kind == "text":
                    round_text += payload
                    _emit({"type": "text", "delta": payload})
                elif kind == "tool_calls":
                    round_tool_calls = payload or []
                elif kind == "usage" and extra:
                    if extra.get("input_tokens"):
                        usage_in += int(extra["input_tokens"])
                    if extra.get("output_tokens"):
                        usage_out += int(extra["output_tokens"])
        except Exception as exc:  # noqa: BLE001
            logger.error("agent_llm_failed", error=str(exc), exc_info=True)
            return {"error": f"llm failed: {exc}", "messages": messages, "steps": steps,
                    "traces": traces,
                    "assistant_final": f"(执行出错: {exc})",
                    "usage": {"input_tokens": usage_in, "output_tokens": usage_out}}

        # 兜底：个别上游不在 SSE 流里下发 tool_calls（仅非流式可见），此时本轮空 → 降级非流式重取一次。
        if not round_text and not round_tool_calls:
            try:
                result = await llm_client.chat(
                    db, UUID(state["org_id"]), state.get("model_alias", "default"), messages,
                    system_prompt=system_prompt,
                    temperature=state.get("temperature"),
                    max_tokens=state.get("max_tokens"),
                    tools=tools or None,
                    dept_id=state.get("department_id"),
                    team_id=state.get("team_id"),
                )
                round_text = result.content or ""
                round_tool_calls = result.tool_calls or []
                if round_text:
                    _emit({"type": "text", "delta": round_text})
                usage_in += int(result.usage.get("input_tokens") or 0)
                usage_out += int(result.usage.get("output_tokens") or 0)
            except Exception as exc:  # noqa: BLE001
                logger.error("agent_llm_failed", error=str(exc), exc_info=True)
                return {"error": f"llm failed: {exc}", "messages": messages, "steps": steps,
                        "traces": traces,
                        "assistant_final": f"(执行出错: {exc})",
                        "usage": {"input_tokens": usage_in, "output_tokens": usage_out}}

        # 累计本轮文本到终答：工具调用轮里输出的中间说明/正文也要持久化，
        # 否则只有最后一轮文本落库，重开任务时会丢失此前已实时展示的内容。
        if round_text:
            assistant_final += round_text

        if round_tool_calls:
            # 重新发给上游的 assistant 工具调用消息须用 OpenAI 嵌套格式
            # {"id","type":"function","function":{"name","arguments"}}；扁平格式会被严格上游
            # （如阿里云 MaaS）以 ``tool_calls.0.function Field required`` 拒绝，且与
            # ``_to_anthropic_messages`` 期望一致。
            assistant_msg: dict = {
                "role": "assistant",
                "content": round_text or "",
                "tool_calls": [
                    {"id": tc.get("id", ""), "type": "function",
                     "function": {"name": tc.get("name", ""), "arguments": tc.get("arguments", "")}}
                    for tc in round_tool_calls
                ],
            }
            messages.append(assistant_msg)
            steps.append({"step": "llm", "tool_calls": [tc["name"] for tc in round_tool_calls]})
            for tc in round_tool_calls:
                _emit({"type": "tool_call", "id": tc.get("id", ""), "name": tc.get("name", ""),
                       "arguments": tc.get("arguments", "")})
                tool_msg, preview, ok = await _execute_tool_call(state, tc, registry)
                _emit({"type": "tool_result", "id": tc.get("id", ""), "name": tc.get("name", ""),
                       "content": preview[:4000], "ok": ok})
                messages.append(tool_msg)
                steps.append({"step": "tool", "name": tc.get("name"), "ok": ok})
                # 技能调用痕迹：仅落 state.traces 供保存/回放，不另发 trace 事件
                # （实时展示已由上方 tool_call/tool_result + 前端 ToolCard 承担，避免重复）。
                traces.append({"category": "skill", "title": tc.get("name", ""),
                               "id": tc.get("id", ""), "name": tc.get("name", ""),
                               "arguments": tc.get("arguments", ""),
                               "result": preview[:4000], "ok": ok})
            continue

        # 无 tool_calls → 终答（文本已逐 token 下发，且本轮文本已累计到 assistant_final）
        messages.append({"role": "assistant", "content": round_text})
        steps.append({"step": "llm_final"})
        break

    if not assistant_final:
        assistant_final = "(达到最大步数，未产生终答)"
        _emit({"type": "text", "delta": assistant_final})

    _emit({"type": "done", "usage": {"input_tokens": usage_in, "output_tokens": usage_out}})
    return {
        "messages": messages,
        "assistant_final": assistant_final,
        "steps": steps,
        "traces": traces,
        "usage": {"input_tokens": usage_in, "output_tokens": usage_out},
    }


# ── save_memory ────────────────────────────────────────────────────────

async def save_memory(state: AgentState) -> dict:
    """持久化本轮对话消息。

    agent 模式：写入 ``AgentMessage``（session 级）。
    general 模式：写入 ``TaskMessage``（任务线程级）。长期记忆沉淀由后续 ``extract_memory`` 节点完成。
    """
    deps = get_deps()
    db = deps["db"]

    if state.get("mode") == "general":
        from app.models.task import TaskMessage
        task_id = state.get("task_id")
        if not task_id:
            return {}
        # 仅落 assistant 消息：user 消息已在 _run_graph_bg 起始落库并提交
        # （让 run 期间 GET /tasks 能带回提示词、重连回放时前面有用户消息）。
        db.add(TaskMessage(task_id=UUID(task_id), role="assistant",
                           content=state.get("assistant_final", ""),
                           metadata_={"traces": state.get("traces", [])}))
        await db.flush()
        # **立即提交**：让 assistant 回复（及本轮工具写入的工作空间文件）当场持久化，
        # 不再依赖 _run_graph_bg 末尾的统一 commit。这样即使后续 extract_memory /
        # judge / write_run_log 抛异常或末尾 commit 失败，回复也不会被回滚「消失」
        # （与起首 user 消息同等耐久）。commit 自身极少失败（TaskMessage 无唯一约束），
        # 真失败则 rollback 清理会话并告警——不让本节点把图搞崩。
        try:
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.warning("save_memory_commit_failed", task_id=str(task_id), exc_info=True)
            await db.rollback()
        return {}

    # ── agent 模式 ──
    mem_cfg = state.get("memory_config") or {}
    if not mem_cfg.get("enabled", False):
        return {}
    from app.models.agent_memory import AgentMessage

    agent_id = UUID(state["agent_id"])
    session_id = state["session_id"]
    db.add_all([
        AgentMessage(agent_id=agent_id, session_id=session_id, role="user",
                     content=state.get("request", "")),
        AgentMessage(agent_id=agent_id, session_id=session_id, role="assistant",
                     content=state.get("assistant_final", "")),
    ])
    await db.flush()
    return {}


# ── extract_memory ─────────────────────────────────────────────────────

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def _parse_json_lenient(text: str) -> Any:
    """容错解析 LLM 输出的 JSON。

    推理模型（如 glm-5.2）非流式返回常把 JSON 包在 ```json ... ``` markdown
    围栏里，或前后混入说明文字。先剥围栏；仍失败则取首个 ``{`` 到末个 ``}```
    之间的子串再试。解析失败返回 ``{}``（等价于无 facts），避免 extract 抛
    ``Expecting value: line 1 column 1 (char 0)`` 让整轮记忆沉淀静默归零。
    """
    if not text:
        return {}
    s = text.strip()
    m = _JSON_FENCE_RE.match(s)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # 围栏已剥/无围栏但混入文字：截取最外层 { ... } 子串
    lo, hi = s.find("{"), s.rfind("}")
    if lo != -1 and hi != -1 and hi > lo:
        try:
            return json.loads(s[lo:hi + 1])
        except json.JSONDecodeError:
            pass
    return {}


async def extract_memory(state: AgentState) -> dict:
    """general 模式：抽取本轮可沉淀的长期事实写入个人级 ``Memory``（source=auto）。agent 模式 no-op。"""
    if state.get("mode") != "general":
        return {}
    # Plan 模式未真正执行，无可沉淀事实 → 跳过。
    if state.get("exec_mode") == "plan":
        return {}
    user_id = state.get("user_id")
    org_id = state.get("org_id")
    if not user_id or not org_id:
        return {}

    deps = get_deps()
    db = deps["db"]
    request = state.get("request", "")
    assistant = state.get("assistant_final", "")
    prompt = (
        "从以下对话中抽取【可跨任务复用的结论性事实】，写入长期记忆供后续任务复用。"
        "每条用「实体 → 属性 → 值」短句表达，一条一行。\n"
        "值得沉淀（结论性、可复用，举例）：\n"
        "- 业务对象的关键属性结论：如「面料 M-WOOL-DBL-360 → 首选供应商 → XS-FAB-002」"
        "「面料 M-WOOL-DBL-360 → 交期异动 → +5 天（延长）」"
        "「供应商 XS-FAB-003 → 产能瓶颈 → 85% 接近满产」\n"
        "- 用户稳定的偏好/规则：如「采购方偏好账期长的供应商」「交期异动 Δ>0 必须启用备选供应商」\n"
        "不要沉淀（一次性/临时/过程性）：\n"
        "- 单次工具调用的原始返回数据、中间推理过程\n"
        "- 仅本轮有效的临时数值、试算中间值\n"
        "- 与具体任务实例绑死的执行步骤\n"
        "最多 8 条，宁缺毋滥。若无值得沉淀的结论性事实，返回空数组。"
        "返回 JSON {\"facts\":[\"实体 → 属性 → 值\", ...]}。\n"
        f"用户：{request}\n助手：{assistant}"
    )
    facts: list[str] = []
    try:
        result = await llm_client.chat(
            db, UUID(org_id), state.get("model_alias", "default"),
            [{"role": "user", "content": prompt}],
            system_prompt="你只输出 JSON。",
            dept_id=state.get("department_id"),
            team_id=state.get("team_id"),
        )
        parsed = _parse_json_lenient(result.content)
        raw = parsed.get("facts", []) if isinstance(parsed, dict) else []
        facts = [str(f).strip() for f in raw if isinstance(f, str) and f.strip()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("extract_memory_failed", error=str(exc))

    for f in facts:
        await memory_service.add_user_memory(db, UUID(org_id), user_id, f)
    if facts:
        await db.flush()
    trace = {"category": "memory", "subtype": "extract", "title": "记忆沉淀",
             "facts": len(facts)}
    _emit({"type": "trace", **trace})
    return {
        "steps": [*state.get("steps", []), {"step": "extract_memory", "facts": len(facts)}],
        "traces": [*state.get("traces", []), trace],
    }


# ── judge ──────────────────────────────────────────────────────────────

async def judge(state: AgentState) -> dict:
    """若启用判官，按 JudgeTemplate criteria 让 LLM 打分。general 模式默认不启用。"""
    # Ask / Plan 模式不产出可判定的执行结果 → 跳过判官。
    if state.get("exec_mode") in ("ask", "plan"):
        return {}
    jcfg = state.get("judge_config") or {}
    jt_id = state.get("judge_template_id")
    if not (jcfg.get("enabled") or jt_id):
        return {}
    deps = get_deps()
    db = deps["db"]
    criteria: list = []
    rubric: str | None = None
    if jt_id:
        from app.models.judge import JudgeTemplate
        jt = await db.get(JudgeTemplate, UUID(jt_id))
        if jt:
            criteria = list(jt.criteria or [])
            rubric = jt.scoring_rubric
    criteria = list(jcfg.get("criteria_overrides", [])) or criteria
    if not criteria:
        return {}

    prompt = (
        f"你是评审判官。请按以下维度对智能体回复打分（0-100），"
        f"返回 JSON {{\"scores\":{{...}},\"total\":number,\"comment\":\"...\"}}。\n"
        f"维度：{json.dumps(criteria, ensure_ascii=False)}\n"
        f"评分细则：{rubric or '(无)'}\n"
        f"用户问题：{state.get('request','')}\n"
        f"智能体回复：{state.get('assistant_final','')}\n"
    )
    parsed: dict
    try:
        result = await llm_client.chat(
            db, UUID(state["org_id"]), state.get("model_alias", "default"),
            [{"role": "user", "content": prompt}],
            system_prompt="你是一个严格的评审判官，只输出 JSON。",
            dept_id=state.get("department_id"),
            team_id=state.get("team_id"),
        )
        try:
            parsed = json.loads(result.content)
        except json.JSONDecodeError:
            parsed = {"raw": result.content}
    except Exception as exc:  # noqa: BLE001
        parsed = {"error": str(exc)}
    _emit({"type": "judge", "result": parsed})
    return {"judge_result": parsed, "steps": [*state.get("steps", []), {"step": "judge", "result": parsed}]}


# ── write_run_log ──────────────────────────────────────────────────────

async def write_run_log(state: AgentState) -> dict:
    """收口：更新 AgentRun（messages/steps/usage/status/judge）+ 写审计日志。agent/general 共用。"""
    deps = get_deps()
    db = deps["db"]
    run_id = state.get("run_id")
    usage = state.get("usage", {})
    in_tok = usage.get("input_tokens") or 0
    out_tok = usage.get("output_tokens") or 0
    if run_id is not None:
        run = await db.get(AgentRun, run_id)
        if run is not None:
            run.messages = state.get("messages", [])
            run.steps = state.get("steps", [])
            run.input_tokens = in_tok
            run.output_tokens = out_tok
            run.judge_score = state.get("judge_result")
            run.error = state.get("error")
            run.status = "error" if state.get("error") else "success"
            run.latency_ms = 0  # 由 endpoint 计算总耗时更准确；此处占位
            await db.flush()

    # 写审计日志：agent 运行时直连上游、不经 /v1 代理端点，故 audit_logs 此前缺这部分
    # LLM 用量，路由器监控因此显示为空。此处按 run 维度补写一条 agent_request 事件，
    # event_type 与 proxy_request 区分，路由器监控的总量/by_provider 即可覆盖智能体通路。
    try:
        provider_id, model_served = await llm_client.resolve_provider_model(
            db, UUID(state["org_id"]), state.get("model_alias", "default"),
            dept_id=state.get("department_id"),
            team_id=state.get("team_id"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit_resolve_provider_failed", error=str(exc))
        provider_id, model_served = None, state.get("model_alias")
    err = state.get("error")
    audit = AuditLog(
        request_id=state.get("session_id") or (str(run_id) if run_id else ""),
        api_key_id=None,
        organization_id=str(state["org_id"]),
        department_id=str(state["department_id"]) if state.get("department_id") else None,
        team_id=str(state["team_id"]) if state.get("team_id") else None,
        provider_id=provider_id,
        event_type="agent_request",
        direction="outbound",
        model_requested=state.get("model_alias"),
        model_served=model_served,
        input_tokens=in_tok or None,
        output_tokens=out_tok or None,
        latency_ms=None,
        status_code=500 if err else 200,
        dlp_violations=[],
        error_message=err if err else None,
    )
    db.add(audit)
    await db.flush()
    return {}
