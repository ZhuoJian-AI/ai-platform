"""AI Platform agent capabilities used by the single DSH coordinator.

This module owns configuration loading, authorized tool discovery/execution, memory,
evaluation and audit persistence.  It intentionally contains no model/tool loop; DSH
owns step scheduling, observations and termination.

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

from app.agents.graph.context import get_deps, get_stream_writer
from app.agents.graph.state import AgentState
from app.config import settings
from app.dlp.scanner import scan_request
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
    multimodal_service,
    scope_service,
    skill_import_service,
    skill_runner_client,
    skill_scope_service,
    storage_gateway_service,
    workspace_permission_service,
    workspace_service,
)
from app.services import model_gateway as llm_client
from app.services.rag_service import retrieve as rag_retrieve
from app.services.skill_store_service import SKILL_MANIFEST_PATH
from app.services.skill_store_service import get_file_by_path as get_skill_file_by_path
from app.tools.executor import execute_endpoint
from app.tools.skill_manifest import parse_skill_manifest

logger = structlog.get_logger()

MAX_STEPS = 8
RUNNER_INLINE_FILE_BYTES = 10 * 1024 * 1024

GENERAL_SYSTEM_PROMPT = (
    "你是组织智能助手。默认用 Markdown 直接回答；只有用户明确要求生成、编辑、转换或导出文件时，"
    "才调用相应的平台文件工具。你可以：按需调用当前用户有权使用的技能完成专业业务操作；使用平台"
    "文件工具处理表格、文档、演示文稿、PDF、文本、图片与压缩包；按需搜索和读取公开网页；"
    "管理当前工作空间文件；参考组织本体与四级长期记忆。"
    "用户明确调用 Skill 或某个 Skill 明显匹配专业流程时优先遵循该 Skill，平台文件工具作为通用能力。只有系统实际提供了"
    "[知识库检索结果]时才能使用RAG内容，通用智能体不会自动加载知识库。"
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
    "必须先询问，不得擅自读取全部文件；status=unavailable 时明确告知文件已删除或无权访问。\n"
    "7. 用户明确调用 Skill，或已载入 Skill 与当前专业流程匹配时，优先遵循 SKILL.md 并执行其脚本；"
    "只有没有适用 Skill 时才使用 spreadsheet/document/presentation/pdf/text/image/archive/web 平台通用工具兜底。"
)

# ── 输出协议（Craft 模式注入，场景无关 boilerplate，避免每个任务提示词重复）────
# 约束 agent「先输出完整分析，仅在任务明确要求时生成附件」+「不要臆造数据」。
# 任务提示词只需写业务目标、对象和期望交付物，不必重复这两段。
OUTPUT_PROTOCOL_PROMPT = (
    "\n\n[输出协议]\n"
    "1. 默认以 Markdown 返回结果。仅当用户请求或智能体任务说明明确要求生成、编辑、转换、导出、下载或归档附件时，"
    "才调用与目标格式对应的平台文件工具或已匹配 Skill；普通问答、解释或文件分析不得擅自生成附件。\n"
    "2. 不要臆造数据：所有编码 / 工单号 / 款号 / 数值 / 结论必须来自已注入的数据接口返回、"
    "本体、知识库检索命中或用户给定，不可拼凑不存在的标识符。\n"
    "3. 任何‘已调用工具 / 执行成功 / 已生成文件’的声明，以及 file_id、输出路径和处理结果，都必须来自"
    "本轮真实 tool_result。若本轮没有真实 tool_call，只能如实说明尚未执行，严禁编造 UUID、路径或成功状态。"
)

def _emit(event: dict) -> None:
    """经 stream_writer 下发事件（流式分支；非流式分支 writer 为 no-op）。"""
    try:
        writer = get_stream_writer()
        writer(json.dumps(event, ensure_ascii=False))
    except Exception:  # noqa: BLE001 — 非流式分支无 writer，忽略
        pass


# ── 内置工作空间文件工具 ─────────────────────────────────────────────────

PLATFORM_TOOL_NAMES = {
    "spreadsheet_tool", "document_tool", "presentation_tool", "pdf_tool", "text_tool",
    "image_tool", "archive_tool", "web_tool",
}
ALWAYS_AVAILABLE_TOOL_NAMES = {"web_tool"}
BUILTIN_TOOL_NAMES = {
    "workspace_list_files", "workspace_read_file", "workspace_write_file", "workspace_delete_file",
    *PLATFORM_TOOL_NAMES, "image_generation_tool",
}
# Kept executable for old persisted calls, but no longer advertised to new LLM rounds.
LEGACY_BUILTIN_TOOL_NAMES = {"generate_docx"}


def _builtin_tool_defs(
    *, include_workspace: bool = True, include_image_generation: bool = False,
) -> list[dict]:
    """内置工作空间文件工具的 OpenAI function-tool 定义。"""
    tools = [
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
            "description": "向当前工作空间写入纯文本文件。Office、PDF 等二进制格式必须使用对应平台文件工具。",
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
            "name": "spreadsheet_tool",
            "description": "检查、创建、编辑或转换 Excel/CSV/TSV/ODS 表格。没有专业 Skill 时使用此通用工具。",
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["inspect", "create", "edit", "convert"]},
                "input_file_ids": {"type": "array", "items": {"type": "string"}},
                "output_name": {"type": "string"},
                "sheets": {"type": "array", "items": {"type": "object", "properties": {
                    "name": {"type": "string"},
                    "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                }}},
                "operations": {"type": "array", "items": {"type": "object"}},
                "target_format": {"type": "string"},
                "max_rows": {"type": "integer"}, "max_columns": {"type": "integer"},
            }, "required": ["action"]},
        }},
        {"type": "function", "function": {
            "name": "document_tool",
            "description": "检查、创建、编辑或转换 Word/DOCX/DOC/ODT/RTF 文档；正文使用 Markdown。",
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["inspect", "create", "edit", "convert"]},
                "input_file_ids": {"type": "array", "items": {"type": "string"}},
                "output_name": {"type": "string"}, "markdown": {"type": "string"},
                "replace": {"type": "boolean"}, "target_format": {"type": "string"},
            }, "required": ["action"]},
        }},
        {"type": "function", "function": {
            "name": "presentation_tool",
            "description": "检查、创建、追加编辑或转换 PowerPoint/PPTX/PPT/ODP 演示文稿。",
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["inspect", "create", "edit", "convert"]},
                "input_file_ids": {"type": "array", "items": {"type": "string"}},
                "output_name": {"type": "string"},
                "slides": {"type": "array", "items": {"type": "object", "properties": {
                    "title": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                }}},
                "target_format": {"type": "string"},
            }, "required": ["action"]},
        }},
        {"type": "function", "function": {
            "name": "pdf_tool",
            "description": "检查、创建、合并、提取页面或转换 PDF。edit 时 operation 可为 merge、split、extract_pages。",
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["inspect", "create", "edit", "convert"]},
                "input_file_ids": {"type": "array", "items": {"type": "string"}},
                "output_name": {"type": "string"}, "markdown": {"type": "string"},
                "operation": {"type": "string", "enum": ["merge", "split", "extract_pages"]},
                "pages": {"type": "array", "items": {"type": "integer"}},
                "target_format": {"type": "string"}, "max_pages": {"type": "integer"},
            }, "required": ["action"]},
        }},
        {"type": "function", "function": {
            "name": "text_tool",
            "description": "检查、创建、编辑或转换 UTF-8 TXT/Markdown 文本文件。",
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["inspect", "create", "edit", "convert"]},
                "input_file_ids": {"type": "array", "items": {"type": "string"}},
                "output_name": {"type": "string"}, "content": {"type": "string"},
                "replace": {"type": "boolean"}, "format": {"type": "string"},
                "target_format": {"type": "string"},
            }, "required": ["action"]},
        }},
        {"type": "function", "function": {
            "name": "image_tool",
            "description": "检查、转换、缩放、裁剪、压缩图片，或对图片/扫描 PDF 执行中英文 OCR。",
            "parameters": {"type": "object", "properties": {
                "action": {
                    "type": "string",
                    "enum": ["inspect", "convert", "resize", "crop", "compress", "ocr"],
                },
                "input_file_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                "output_name": {"type": "string"},
                "target_format": {"type": "string", "enum": ["png", "jpg", "jpeg", "webp", "tiff", "bmp"]},
                "width": {"type": "integer", "minimum": 1},
                "height": {"type": "integer", "minimum": 1},
                "keep_aspect": {"type": "boolean"},
                "quality": {"type": "integer", "minimum": 1, "maximum": 100},
                "box": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4},
                "language": {"type": "string", "description": "Tesseract 语言，如 chi_sim+eng"},
                "max_pages": {"type": "integer", "minimum": 1, "maximum": 20},
            }, "required": ["action", "input_file_ids"]},
        }},
        {"type": "function", "function": {
            "name": "archive_tool",
            "description": "安全查看、解压或创建 ZIP/TAR/TAR.GZ；解压结果写回当前工作空间。",
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["list", "extract", "create"]},
                "input_file_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20},
                "output_name": {"type": "string"},
                "format": {"type": "string", "enum": ["zip", "tar", "tar.gz"]},
            }, "required": ["action", "input_file_ids"]},
        }},
        {"type": "function", "function": {
            "name": "web_tool",
            "description": (
                "搜索公开网页、提取指定网页正文，或把公开 URL 下载到工作空间。"
                "禁止访问 localhost、内网与云元数据地址；涉及专业流程时仍优先使用已绑定 Skill。"
            ),
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["search", "fetch", "download"]},
                "query": {"type": "string"},
                "url": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                "max_chars": {"type": "integer", "minimum": 1000, "maximum": 100000},
                "output_name": {"type": "string"},
            }, "required": ["action"]},
        }},
    ]
    if include_image_generation:
        tools.append({"type": "function", "function": {
            "name": "image_generation_tool",
            "description": (
                "使用当前组织配置的专用生图模型生成真实图片，并保存到当前工作空间。"
                "仅在用户明确要求生成图片、插画、海报或视觉素材时调用。"
            ),
            "parameters": {"type": "object", "properties": {
                "prompt": {"type": "string", "description": "完整、具体的生图提示词"},
                "output_name": {"type": "string", "description": "输出文件名；系统统一保存为 PNG"},
                "size": {"type": "string", "description": "如 1024x1024、1536x1024、1024x1536 或 auto"},
                "quality": {"type": "string", "enum": ["auto", "low", "medium", "high"]},
            }, "required": ["prompt"]},
        }})
    if include_workspace:
        return tools
    return [
        tool for tool in tools
        if tool.get("function", {}).get("name") in ALWAYS_AVAILABLE_TOOL_NAMES
    ]


async def _runner_input(file) -> dict:
    """Keep large OSS objects out of agent/backend JSON payloads."""
    meta = file.metadata_ or {}
    item = {
        "file_id": str(file.id),
        "name": str(meta.get("name") or PurePosixPath(file.path).name),
        "expected_size": file.size,
    }
    if file.size > RUNNER_INLINE_FILE_BYTES and storage_gateway_service.is_object_ref(file.content_ref):
        signed = await storage_gateway_service.get_signed_download(str(file.content_ref))
        item.update({"download_url": signed["url"], "download_headers": signed.get("headers") or {}})
    else:
        raw = await workspace_service.load_file_bytes(file)
        item["content_base64"] = base64.b64encode(raw).decode("ascii")
    return item


async def _validated_runner_output(item: dict, fallback_mime: str) -> tuple[str, int, str, str]:
    """Trust OSS, not the Runner response, for large output metadata."""
    content_ref = str(item.get("content_ref") or "")
    actual = await storage_gateway_service.inspect_object(content_ref)
    actual_size = int(actual.get("size") or 0)
    if actual_size <= 0:
        raise ValueError("Runner 输出文件为空")
    if actual_size > settings.workspace_max_file_bytes:
        raise ValueError("Runner 输出文件超过 100MB 上限")
    declared_size = int(item.get("size") or 0)
    if declared_size and declared_size != actual_size:
        raise ValueError(f"Runner 输出大小校验失败：声明 {declared_size}，实际 {actual_size}")
    actual_etag = str(actual.get("etag") or "").strip('"')
    declared_etag = str(item.get("etag") or "").strip('"')
    if declared_etag and actual_etag and declared_etag != actual_etag:
        raise ValueError("Runner 输出 ETag 校验失败")
    actual_mime = str(actual.get("content_type") or "").split(";", 1)[0].strip().lower()
    mime = actual_mime if actual_mime and actual_mime != "application/octet-stream" else fallback_mime
    return content_ref, actual_size, mime, actual_etag


async def _execute_platform_file_tool(
    state: AgentState, name: str, params: dict, ws, user,
) -> str:
    """Authorize files, call Runner's immutable builtin lane, and persist outputs."""
    if state.get("exec_mode") != "craft":
        return json.dumps({"status": "error", "error": "请切换到 Craft 模式执行文件工具"}, ensure_ascii=False)
    deps = get_deps()
    db = deps["db"]
    tool_kind = name.removesuffix("_tool")
    action = str(params.get("action") or "").strip().lower()
    requested_ids = params.get("input_file_ids")
    if requested_ids is None:
        requested_ids = [] if name == "web_tool" else (state.get("referenced_file_ids") or [])
    if not isinstance(requested_ids, list):
        return json.dumps({"status": "error", "error": "input_file_ids must be an array"})
    if len(requested_ids) > 20:
        return json.dumps({"status": "error", "error": "At most 20 input files are allowed"})
    if requested_ids and ws is None:
        return json.dumps({"status": "error", "error": "请先绑定工作空间"}, ensure_ascii=False)
    runner_inputs: list[dict] = []
    for value in requested_ids:
        try:
            file = await workspace_service.get_file(db, UUID(str(value)))
        except (ValueError, TypeError, AttributeError):
            file = None
        if file is None or ws is None or str(file.workspace_id) != str(ws.id):
            return json.dumps({"status": "error", "error": f"Input file {value} is unavailable"})
        runner_inputs.append(await _runner_input(file))
    runner_params = {key: value for key, value in params.items() if key != "input_file_ids"}
    try:
        result, latency = await skill_runner_client.execute_builtin(
            tool_kind=tool_kind,
            action=action,
            params=runner_params,
            inputs=runner_inputs,
            execution_id=f"{state.get('task_id') or 'playground'}-{uuid4().hex[:8]}",
        )
        output_items: list[dict] = []
        if result.get("outputs") and ws is None:
            return json.dumps({"status": "error", "error": "下载文件前请先绑定工作空间"}, ensure_ascii=False)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        task_part = state.get("task_id") or "playground"
        for item in result.get("outputs") or []:
            original = PurePosixPath(str(item.get("name") or "output.bin")).name
            relative = PurePosixPath(str(item.get("relative_path") or original).replace("\\", "/"))
            safe_parts = [part for part in relative.parts if part not in {"", ".", ".."}]
            relative_path = "/".join(safe_parts) or original
            path = f"平台工具输出/{task_part}/{stamp}-{uuid4().hex[:8]}-{relative_path}"
            mime = item.get("mime_type") or mimetypes.guess_type(original)[0] or "application/octet-stream"
            if item.get("content_ref"):
                content_ref, actual_size, mime, actual_etag = await _validated_runner_output(item, mime)
                saved = await workspace_service.upsert_file(
                    db, ws,
                    WorkspaceFileCreate(path=path, content="", metadata={
                        "binary": True, "mime": mime, "name": original,
                        "storage_backend": "oss_gateway", "etag": actual_etag,
                    }),
                    content_ref=content_ref, raw_size=actual_size,
                    raw_content_hash=None, created_by_user_id=user.id,
                )
                saved.content = None
                saved.parse_status = "queued"
                await workspace_service.sync_current_version(db, saved)
            else:
                raw = base64.b64decode(item.get("content_base64") or "", validate=True)
                saved = await workspace_service.ingest_uploaded_file(
                    db, ws, path=path, filename=original, content_type=mime, raw=raw,
                    created_by_user_id=user.id,
                )
            output_meta = {
                **(saved.metadata_ or {}),
                "generated_by": "platform_file_tool",
                "platform_tool": name,
            }
            if state.get("task_id"):
                output_meta["task_id"] = str(state["task_id"])
            saved.metadata_ = output_meta
            await db.flush()
            output_items.append({
                "file_id": str(saved.id),
                "name": original,
                "path": saved.path,
                "parse_status": saved.parse_status,
            })
        return json.dumps({
            "status": "success",
            "tool": name,
            "action": action,
            "summary": result.get("summary"),
            "outputs": output_items,
            "latency_ms": latency,
        }, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("platform_file_tool_failed", tool=name, action=action, error=str(exc))
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)


async def _execute_builtin_tool(state: AgentState, name: str, params: dict) -> str:
    """执行内置工作空间文件工具，返回结果文本。"""
    deps = get_deps()
    db = deps["db"]
    ws_id = state.get("workspace_id")
    user = deps.get("user")
    ws = await workspace_service.get_workspace(db, UUID(ws_id)) if ws_id else None
    no_workspace_web_action = name == "web_tool" and str(params.get("action") or "").lower() in {
        "search", "fetch",
    }
    if ws is None and not no_workspace_web_action:
        return "no workspace bound to this task"
    if ws is not None and user is not None:
        if not (await workspace_permission_service.capabilities(db, ws, user))["read"]:
            return "workspace out of your scope"

    # 用 SAVEPOINT 隔离本轮工具的 DB 写入：若 flush 失败（如唯一约束冲突），
    # 只回滚保存点，不污染 run 主事务。否则主事务进入 PendingRollback 态，
    # 后续 save_memory / write_run_log 的 flush 全部抛 PendingRollbackError，
    # _finalize_bg_error 又用独立会话收口、不提交主事务 → 本轮 assistant 消息
    # （仅在 save_memory 里 flush 未提交）被一并回滚，「任务回复消失」。
    try:
        async with db.begin_nested():
            if name == "image_generation_tool":
                if state.get("exec_mode") != "craft":
                    return json.dumps({"status": "error", "error": "请切换到 Craft 模式执行生图"}, ensure_ascii=False)
                if ws is None or user is None:
                    return json.dumps({"status": "error", "error": "请先绑定工作空间"}, ensure_ascii=False)
                scoped = await multimodal_service.resolve_image_generation(
                    db, UUID(state["org_id"]), dept_id=state.get("department_id"),
                    team_id=state.get("team_id"),
                )
                if scoped is None:
                    return json.dumps({"status": "unavailable", "error": "当前组织未配置生图模型"}, ensure_ascii=False)
                prompt = str(params.get("prompt") or "").strip()
                if not prompt:
                    return json.dumps({"status": "error", "error": "prompt is required"}, ensure_ascii=False)
                if len(prompt) > 12000:
                    return json.dumps({"status": "error", "error": "prompt is too long"}, ensure_ascii=False)
                dlp = await scan_request(
                    db, prompt, str(state["org_id"]), state.get("department_id"), state.get("team_id"),
                )
                if dlp.blocked:
                    return json.dumps({"status": "error", "error": "生图提示词被安全策略拦截"}, ensure_ascii=False)
                prompt = dlp.redacted_text or prompt
                generation = (scoped.provider.config or {}).get("image_generation") or {}
                size = str(params.get("size") or generation.get("default_size") or "1024x1024")
                if size not in multimodal_service.ALLOWED_IMAGE_SIZES and not re.fullmatch(r"\d{2,5}x\d{2,5}", size):
                    return json.dumps({"status": "error", "error": "不支持的图片尺寸"}, ensure_ascii=False)
                started = datetime.now(UTC)
                result = await llm_client.generate_image(
                    scoped.provider, scoped.model, prompt=prompt, size=size,
                    quality=str(params.get("quality") or "auto"),
                    endpoint_path=str(generation.get("endpoint_path") or "/images/generations"),
                )
                raw, width, height = multimodal_service.normalize_generated_png(result.raw)
                requested = PurePosixPath(str(params.get("output_name") or "generated-image.png")).name
                stem = PurePosixPath(requested).stem or "generated-image"
                safe_stem = (
                    re.sub(r"[^\w\-.\u4e00-\u9fff]+", "-", stem, flags=re.UNICODE).strip("-.")
                    or "generated-image"
                )
                filename = f"{safe_stem}.png"
                stamp = started.strftime("%Y%m%d-%H%M%S")
                task_part = state.get("task_id") or "playground"
                path = f"平台工具输出/{task_part}/{stamp}-{uuid4().hex[:8]}-{filename}"
                saved = await workspace_service.ingest_uploaded_file(
                    db, ws, path=path, filename=filename, content_type="image/png", raw=raw,
                )
                saved.metadata_ = {
                    **(saved.metadata_ or {}), "generated_by": "image_generation_tool",
                    "provider_id": result.provider_id, "model": result.model_served,
                    "width": width, "height": height, "task_id": str(task_part),
                }
                db.add(AuditLog(
                    request_id=f"image-generation-{uuid4().hex}",
                    organization_id=str(state["org_id"]), department_id=state.get("department_id"),
                    team_id=state.get("team_id"), provider_id=result.provider_id,
                    event_type="image_generation", direction="outbound",
                    model_requested=scoped.model, model_served=result.model_served,
                    latency_ms=max(0, int((datetime.now(UTC) - started).total_seconds() * 1000)),
                    status_code=200, metadata_={
                        "file_id": str(saved.id), "sha256": saved.content_hash,
                        "mime": "image/png", "width": width, "height": height,
                    },
                ))
                await db.flush()
                return json.dumps({
                    "status": "success", "tool": name,
                    "outputs": [{"file_id": str(saved.id), "name": filename, "path": saved.path,
                                 "mime_type": "image/png", "width": width, "height": height,
                                 "parse_status": saved.parse_status}],
                    "revised_prompt": result.revised_prompt,
                }, ensure_ascii=False)
            if name in PLATFORM_TOOL_NAMES:
                return await _execute_platform_file_tool(state, name, params, ws, user)
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


async def _runtime_skill_summary(db, folder: SkillFolder) -> dict | None:
    """Return a compact ready-to-use Skill catalog row without loading full instructions."""
    version = await db.get(SkillVersion, folder.active_version_id) if folder.active_version_id else None
    if folder.active_version_id:
        if version is None or version.install_status != "ready":
            return None
        manifest = version.manifest if isinstance(version.manifest, dict) else {}
        description = str(manifest.get("description") or folder.name)
        executable = bool(version.is_executable)
        platform = manifest.get("_platform") if isinstance(manifest.get("_platform"), dict) else {}
        package_format = str(platform.get("package_format") or "package")
    else:
        manifest_file = await get_skill_file_by_path(db, folder.id, SKILL_MANIFEST_PATH)
        manifest = parse_skill_manifest(manifest_file.content if manifest_file else None)
        if manifest is None:
            return None
        description = manifest.description or folder.name
        executable = manifest.runtime in {"python", "node"}
        package_format = "legacy"
    return {
        "id": str(folder.id), "name": folder.name, "slug": folder.slug,
        "description": description[:1000], "scope_type": folder.scope_type,
        "scope_id": str(folder.scope_id) if folder.scope_id else None,
        "is_executable": executable, "package_format": package_format,
    }


async def _load_config_general(state: AgentState, deps, db) -> dict:
    """General mode: fixed Agent RAG plus a prioritized catalog of every authorized Skill."""
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

    # RAG remains fixed to the selected Agent. Skill bindings are recommendations, not an allowlist.
    default_skill_ids = [str(s) for s in (tpl.skill_ids or [])] if tpl_id and tpl is not None else []
    # Preserve old task configs as additional recommendations while new UI selections use invoked_skill_ids.
    for legacy_id in state.get("skill_ids") or []:
        if str(legacy_id) not in default_skill_ids:
            default_skill_ids.append(str(legacy_id))
    skill_ids: list[str] = []
    skill_catalog: list[dict] = []
    default_skills: list[dict] = []
    ontology_ids = list(state.get("ontology_ids") or [])
    rag_ids = [str(r) for r in (tpl.rag_collection_ids or [])] if tpl_id and tpl is not None else []
    referenced_skills: list[dict] = list(state.get("invoked_skills") or [])
    slug_ambiguities: list[str] = []
    # 结构化附件优先进入 state；正文中的历史 @UUID 再补充，按出现顺序去重。
    referenced_file_ids: list[str] = []

    if user is not None:
        visible_folders = await scope_service.list_skills_for_user(db, user)
        visible_rows: list[tuple[SkillFolder, dict]] = []
        for folder in visible_folders:
            summary = await _runtime_skill_summary(db, folder)
            if summary is not None:
                visible_rows.append((folder, summary))
        visible_by_id = {str(folder.id): (folder, summary) for folder, summary in visible_rows}

        default_folders = await skill_scope_service.assert_bound_skills_visible(
            db, user, default_skill_ids,
        )
        invoked_folders = await skill_scope_service.assert_bound_skills_visible(
            db, user, list(state.get("invoked_skill_ids") or []),
        )
        invoked_id_order = [str(folder.id) for folder in invoked_folders]
        default_id_order = [str(folder.id) for folder in default_folders]
        ordered_ids = list(dict.fromkeys([
            *invoked_id_order, *default_id_order, *(str(folder.id) for folder, _ in visible_rows),
        ]))
        skill_catalog = [visible_by_id[sid][1] for sid in ordered_ids if sid in visible_by_id]
        skill_ids = [row["id"] for row in skill_catalog]
        default_skills = [
            {**visible_by_id[sid][1], "is_default": True}
            for sid in default_id_order if sid in visible_by_id
        ]
        # Trust server-side snapshots, not client names/descriptions, after UUID authorization succeeds.
        explicit_ids = set(invoked_id_order)
        referenced_skills = [
            {**visible_by_id[sid][1], "activation": "explicit"}
            for sid in invoked_id_order if sid in visible_by_id
        ]
        bound_rags = await scope_service.assert_bound_rags_visible(db, user, rag_ids)
        rag_ids = [str(r.id) for r in bound_rags]
        if not ontology_ids:
            ontology_ids = [str(o.id) for o in await scope_service.list_ontologies_for_user(db, user)]
        # /slug remains current-turn compatibility. A duplicate visible slug is deliberately ambiguous.
        slug_to_rows: dict[str, list[dict]] = {}
        for row in skill_catalog:
            slug_to_rows.setdefault(row["slug"], []).append(row)
        seen_slugs: set[str] = set()
        for m in re.finditer(r'(?<![\w/])/([a-z0-9][a-z0-9-]*)', state.get("request", "") or ""):
            slug = m.group(1)
            matches = slug_to_rows.get(slug, [])
            if len(matches) > 1:
                if slug not in slug_ambiguities:
                    slug_ambiguities.append(slug)
                continue
            if matches and slug not in seen_slugs:
                seen_slugs.add(slug)
                row = matches[0]
                if row["id"] not in explicit_ids:
                    referenced_skills.append({**row, "activation": "slash"})
        # 解析用户消息中 @<file_id> 引用的工作空间文件（精确 UUID，避免误命中邮件等）。
        # DSH turn preparation injects these authorized file references into model context.
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
           "default_skills": len(default_skills),
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
        "skill_catalog": skill_catalog,
        "default_skills": default_skills,
        "invoked_skills": referenced_skills,
        "invoked_skill_ids": [row["id"] for row in referenced_skills],
        "loaded_skills": [],
        "executed_skills": [],
        "skill_slug_ambiguities": slug_ambiguities,
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
    长期记忆填入 ``memory_context``，由 DSH context contribution 注入。
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
            workspace_visible = bool(workspace is not None and (
                await workspace_permission_service.capabilities(db, workspace, user)
            )["read"])
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


# ── DSH platform capability assembly ───────────────────────────────────

async def _prepare_current_turn_images(state: AgentState, db, user) -> list[multimodal_service.PreparedImage]:
    """Load only the current turn's authorized image attachments and run best-effort OCR DLP."""
    snapshots = state.get("attachment_files") or []
    image_snapshots = [
        item for item in snapshots
        if PurePosixPath(str(item.get("name") or item.get("path") or "")).suffix.lower()
        in multimodal_service.ALLOWED_IMAGE_SUFFIXES
    ]
    if not image_snapshots:
        return []
    if len(image_snapshots) > multimodal_service.MAX_IMAGE_COUNT:
        raise ValueError(f"每轮最多发送 {multimodal_service.MAX_IMAGE_COUNT} 张图片")
    prepared: list[multimodal_service.PreparedImage] = []
    for item in image_snapshots:
        try:
            file = await workspace_service.get_file(db, UUID(str(item.get("file_id"))))
        except (ValueError, TypeError, AttributeError):
            file = None
        if file is None or str(file.workspace_id) != str(state.get("workspace_id") or ""):
            raise ValueError("图片附件已不存在或不属于当前工作空间")
        workspace = await workspace_service.get_workspace(db, file.workspace_id)
        if workspace is None or user is None or not (
            await workspace_permission_service.capabilities(db, workspace, user)
        )["read"]:
            raise ValueError("图片附件已不存在或无权访问")
        raw = await workspace_service.load_file_bytes(file)
        meta = file.metadata_ or {}
        image = multimodal_service.prepare_image_bytes(
            file_id=str(file.id), name=str(meta.get("name") or item.get("name") or file.path),
            declared_mime=str(meta.get("mime") or "") or None, raw=raw,
        )
        prepared.append(image)

        # OCR is only a DLP pre-check. Failure does not turn OCR into a prerequisite for vision.
        try:
            ocr, _ = await skill_runner_client.execute_builtin(
                tool_kind="image", action="ocr", params={"language": "chi_sim+eng", "max_pages": 1},
                inputs=[{
                    "file_id": image.file_id, "name": image.name,
                    "content_base64": base64.b64encode(image.raw).decode("ascii"),
                }],
                execution_id=f"vision-dlp-{state.get('task_id') or 'playground'}-{uuid4().hex[:8]}",
                timeout_seconds=min(settings.skill_runner_timeout_seconds, 45),
            )
            summary = ocr.get("summary") or {}
            ocr_text = str(summary.get("content") or summary.get("text") or "").strip()
            if ocr_text:
                dlp = await scan_request(
                    db, ocr_text, str(state["org_id"]), state.get("department_id"), state.get("team_id"),
                )
                # Redacting extracted text cannot redact pixels, so raw image transmission must stop.
                if dlp.blocked or dlp.redacted_text is not None:
                    raise ValueError(f"图片 {image.name} 含安全策略限制内容，不能发送给外部视觉模型")
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.info("vision_ocr_dlp_unavailable", file_id=image.file_id, error=str(exc))
    multimodal_service.ensure_image_batch_limits(prepared)
    return prepared


def _attach_images_to_current_user_message(
    messages: list[dict], images: list[multimodal_service.PreparedImage],
) -> None:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        original = message.get("content", "")
        text = original if isinstance(original, str) else ""
        message["content"] = [
            {"type": "text", "text": text},
            *[
                {"type": "image_url", "image_url": {"url": image.data_url, "detail": "auto"}}
                for image in images
            ],
        ]
        return


async def _configure_visual_turn(
    state: AgentState, db, user, messages: list[dict], system_prompt: str,
) -> tuple[Any | None, str | None, str]:
    """Resolve the main provider and apply direct-vision or scoped fallback routing once per turn."""
    images = await _prepare_current_turn_images(state, db, user)
    if not images:
        # Preserve the existing routing path for text-only turns (and its test/failover behavior).
        return None, None, system_prompt
    provider, model = await llm_client.resolve_provider(
        db, UUID(state["org_id"]), state.get("model_alias", "default"),
        dept_id=state.get("department_id"), team_id=state.get("team_id"),
    )
    vision_enabled, _ = await multimodal_service.organization_feature_flags(db, UUID(state["org_id"]))
    direct = bool(
        vision_enabled and provider.provider_type != "anthropic"
        and multimodal_service.provider_model_supports_vision(provider, model)
    )
    _emit({"type": "vision_preprocess", "status": "ready", "images": len(images),
           "mode": "direct" if direct else "fallback"})
    if direct:
        _attach_images_to_current_user_message(messages, images)
        db.add(AuditLog(
            request_id=f"vision-{uuid4().hex}", organization_id=str(state["org_id"]),
            department_id=state.get("department_id"), team_id=state.get("team_id"),
            provider_id=str(provider.id), event_type="vision_input", direction="outbound",
            model_requested=model, model_served=model, status_code=200, dlp_violations=[],
            metadata_={
                "mode": "direct", "images": [
                    {"file_id": image.file_id, "sha256": image.sha256, "mime": image.mime_type,
                     "width": image.width, "height": image.height}
                    for image in images
                ],
            },
        ))
        return provider, model, system_prompt

    fallback = await multimodal_service.resolve_vision_fallback(
        db, UUID(state["org_id"]), dept_id=state.get("department_id"), team_id=state.get("team_id"),
    )
    if fallback is None:
        raise RuntimeError("当前组织未配置视觉模型；仍可使用 OCR 或 image_tool 处理图片")
    visual_messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": (
                "请准确分析这些图片，输出结构化中文描述。包括可见对象、文字、表格/图表、空间关系、"
                "重要细节与不确定之处。不要猜测图片中不存在的信息。"
            )},
            *[
                {"type": "image_url", "image_url": {"url": image.data_url, "detail": "auto"}}
                for image in images
            ],
        ],
    }]
    visual = await llm_client.chat(
        db, UUID(state["org_id"]), fallback.model, visual_messages,
        system_prompt="你是视觉信息提取器，只描述图片中可验证的内容。",
        provider_override=fallback.provider, model_override=fallback.model,
    )
    description = (visual.content or "").strip()
    if not description:
        raise RuntimeError("视觉回退模型未返回有效描述")
    db.add(AuditLog(
        request_id=f"vision-fallback-{uuid4().hex}", organization_id=str(state["org_id"]),
        department_id=state.get("department_id"), team_id=state.get("team_id"),
        provider_id=str(fallback.provider.id), event_type="vision_fallback", direction="outbound",
        model_requested=fallback.model, model_served=visual.model_served, status_code=200,
        input_tokens=visual.usage.get("input_tokens"), output_tokens=visual.usage.get("output_tokens"),
        dlp_violations=[], metadata_={
            "mode": "fallback", "images": [
                {"file_id": image.file_id, "sha256": image.sha256, "mime": image.mime_type,
                 "width": image.width, "height": image.height}
                for image in images
            ],
        },
    ))
    system_prompt = (
        f"{system_prompt}\n\n[视觉回退模型对本轮图片的结构化描述]\n{description}\n"
        "以上描述来自平台配置的视觉模型；主模型不得声称直接看到了原图。"
    )
    _emit({"type": "vision_preprocess", "status": "completed", "images": len(images), "mode": "fallback"})
    return provider, model, system_prompt

async def _build_tools(
    db, skill_ids: list[str], workspace_id: str | None, user=None, *, exec_mode: str = "craft",
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
    agent_skill_slugs: dict[str, list[str]] = {}
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
                skill_content = (await skill_import_service.read_version_resource(version, skill_path)).decode("utf-8")
            except (StopIteration, UnicodeDecodeError, KeyError):
                logger.warning("agent_skill_manifest_unavailable", skill_folder=str(folder.id), slug=folder.slug)
                continue
            folder_id = str(folder.id)
            agent_skills[folder_id] = {
                "folder": folder, "version": version, "content": skill_content,
                "platform": platform,
            }
            agent_skill_slugs.setdefault(folder.slug, []).append(folder_id)
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
                "kind": "prompt", "folder": folder, "version": version,
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
            # OpenAI-compatible providers only accept [a-zA-Z0-9_-] tool names.
            # Imported operationIds are not guaranteed to follow that rule.
            namespace = re.sub(r"[^a-zA-Z0-9_-]", "_", manifest.name)
            endpoint_name = re.sub(r"[^a-zA-Z0-9_-]", "_", ep.name)
            base_name = f"{namespace}__{endpoint_name}".strip("_") or "enterprise_endpoint"
            endpoint_suffix = str(ep.id).replace("-", "")[:8]
            tool_name = f"{base_name[:55]}_{endpoint_suffix}"
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
            f"{skill_id} ({entry['folder'].slug}): "
            f"{entry['version'].manifest.get('description') or entry['folder'].name}"
            for skill_id, entry in agent_skills.items()
        )
        id_schema = {"type": "string", "enum": list(agent_skills)}
        tools.extend([
            {"type": "function", "function": {
                "name": "load_skill",
                "description": "按需载入当前用户可用标准 Skill 的完整 SKILL.md。可用技能：" + summaries,
                "parameters": {"type": "object", "properties": {
                    "skill_id": {**id_schema, "description": "技能 UUID（来自 Skill 目录）"},
                }, "required": ["skill_id"]},
            }},
            {"type": "function", "function": {
                "name": "read_skill_resource",
                "description": "读取已载入 Skill 中 references/、assets/ 或脚本说明等文本资源。",
                "parameters": {"type": "object", "properties": {
                    "skill_id": id_schema,
                    "path": {"type": "string", "description": "资源索引中显示的相对路径"},
                }, "required": ["skill_id", "path"]},
            }},
        ])
        if any(entry["version"].is_executable for entry in agent_skills.values()):
            tools.append({"type": "function", "function": {
                "name": "run_skill_script",
                "description": (
                    "在隔离 Runner 中执行当前用户可用 Skill 的 scripts/ 内 Python、Node 或 Bash 脚本。"
                    "先调用 load_skill 并遵循其说明。"
                ),
                "parameters": {"type": "object", "properties": {
                    "skill_id": id_schema,
                    "script_path": {"type": "string", "description": "load_skill 返回的 scripts/ 相对路径"},
                    "args": {
                        "type": "array", "items": {"type": "string"},
                        "description": "直接传给脚本的参数数组，不是 Shell 命令",
                    },
                    "input_file_ids": {
                        "type": "array", "items": {"type": "string"},
                        "description": "工作空间输入文件 UUID；省略时使用本轮附件",
                    },
                }, "required": ["skill_id", "script_path"]},
            }})
        tool_names = ["load_skill", "read_skill_resource"]
        if any(entry["version"].is_executable for entry in agent_skills.values()):
            tool_names.append("run_skill_script")
        for name in tool_names:
            registry[name] = {
                "kind": name, "skills": agent_skills, "slug_index": agent_skill_slugs,
            }
    include_image_generation = False
    if workspace_id and user is not None:
        include_image_generation = await multimodal_service.resolve_image_generation(
            db, user.organization_id, dept_id=user.department_id, team_id=user.team_id,
        ) is not None
    from app.services.platform_tool_registry import (
        active_external_tool_defs,
        active_platform_tool_names,
        platform_managed_tool_names,
    )
    builtin_defs = _builtin_tool_defs(
        include_workspace=bool(workspace_id), include_image_generation=include_image_generation,
    )
    active_builtin_names = await active_platform_tool_names(db)
    if active_builtin_names is not None:
        builtin_defs = [
            item for item in builtin_defs
            if item.get("function", {}).get("name") in active_builtin_names
        ]
        disabled_managed_names = platform_managed_tool_names() - active_builtin_names
        tools = [
            item for item in tools
            if item.get("function", {}).get("name") not in disabled_managed_names
        ]
        for name in disabled_managed_names:
            registry.pop(name, None)
    builtin_defs.extend(await active_external_tool_defs(
        db,
        organization_id=str(user.organization_id) if user is not None else "",
        user_role=str(user.role) if user is not None else None,
        exec_mode=exec_mode,
    ))
    tools.extend(builtin_defs)
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
    if ws is None or not (await workspace_permission_service.capabilities(db, ws, user))["read"]:
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
        inputs.append(await _runner_input(file))
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
            original = PurePosixPath(str(item.get("name") or "output.bin")).name
            path = f"技能输出/{task_part}/{stamp}-{uuid4().hex[:8]}-{original}"
            mime = item.get("mime_type") or mimetypes.guess_type(original)[0] or "application/octet-stream"
            if item.get("content_ref"):
                content_ref, actual_size, mime, actual_etag = await _validated_runner_output(item, mime)
                saved = await workspace_service.upsert_file(
                    db, ws,
                    WorkspaceFileCreate(path=path, content="", metadata={
                        "binary": True, "mime": mime, "name": original,
                        "storage_backend": "oss_gateway", "etag": actual_etag,
                    }),
                    content_ref=content_ref, raw_size=actual_size,
                    raw_content_hash=None, created_by_user_id=user.id,
                )
                saved.content = None
                saved.parse_status = "queued"
                await workspace_service.sync_current_version(db, saved)
            else:
                raw = base64.b64decode(item.get("content_base64") or "", validate=True)
                saved = await workspace_service.ingest_uploaded_file(
                    db, ws, path=path, filename=original, content_type=mime, raw=raw,
                    created_by_user_id=user.id,
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


def _skill_record(folder: SkillFolder, version: SkillVersion | None, action: str) -> dict:
    return {
        "id": str(folder.id), "name": folder.name, "slug": folder.slug,
        "scope_type": folder.scope_type,
        "scope_id": str(folder.scope_id) if folder.scope_id else None,
        "version_id": str(version.id) if version is not None else None,
        "action": action,
    }


def _append_skill_record(
    state: AgentState, key: str, folder: SkillFolder, version: SkillVersion | None, action: str,
) -> None:
    records = state.setdefault(key, [])
    record = _skill_record(folder, version, action)
    marker = (record["id"], record["version_id"], record["action"])
    if marker not in {(item.get("id"), item.get("version_id"), item.get("action")) for item in records}:
        records.append(record)


async def _resolve_agent_skill(state: AgentState, entry: dict, params: dict) -> tuple[dict | None, str | None]:
    skill_id = str(params.get("skill_id") or "")
    if not skill_id:
        # Backward compatibility for persisted/older model tool calls. Duplicate slugs must use UUID.
        slug = str(params.get("skill_slug") or "")
        matches = entry.get("slug_index", {}).get(slug, [])
        if len(matches) > 1:
            return None, "Skill slug is ambiguous; choose it from the picker so a UUID is supplied"
        skill_id = matches[0] if matches else ""
    selected = entry.get("skills", {}).get(skill_id)
    if selected is None:
        return None, "Skill is not available in the current user's catalog"
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
    selected, error = await _resolve_agent_skill(state, entry, params)
    if error or selected is None:
        return json.dumps({"status": "error", "error": error or "Skill unavailable"}, ensure_ascii=False)
    platform = selected["platform"]
    folder: SkillFolder = selected["folder"]
    version: SkillVersion = selected["version"]
    if name == "load_skill":
        _append_skill_record(state, "loaded_skills", folder, version, "load_skill")
        return json.dumps({
            "status": "success",
            "skill": {"id": str(folder.id), "name": folder.name, "slug": folder.slug},
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
        _append_skill_record(state, "loaded_skills", folder, version, "read_skill_resource")
        path = str(params.get("path") or "")
        indexed = {str(item.get("path")) for item in platform.get("resources") or [] if isinstance(item, dict)}
        if path not in indexed:
            return json.dumps({"status": "error", "error": "Resource is not part of this Skill version"})
        try:
            raw = await skill_import_service.read_version_resource(selected["version"], path)
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
            if key not in {"skill_id", "skill_slug", "script_path", "args"}
        }
        result = await _execute_code_skill(
            state, selected, execution_params,
            script_path=str(params.get("script_path") or ""), script_args=raw_args,
        )
        try:
            if json.loads(result).get("status") == "success":
                _append_skill_record(state, "executed_skills", folder, version, "runner_script")
        except (json.JSONDecodeError, AttributeError):
            pass
        return result
    return json.dumps({"status": "error", "error": "Unknown Agent Skill tool"})


async def _execute_tool_call(
    state: AgentState, tool_call: dict, registry: dict[str, dict],
) -> tuple[dict, str, bool]:
    """执行单个 tool_call，返回 (tool 消息, 结果预览, 是否成功)。

    不负责 emit——由 DSH runner 在调用前后下发 tool_call/tool_result 事件。
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
    if name in BUILTIN_TOOL_NAMES | LEGACY_BUILTIN_TOOL_NAMES:
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

    if entry.get("kind") == "rag_search":
        query = str(params.get("query") or state.get("request") or "").strip()
        top_k = max(1, min(int(params.get("top_k") or 5), 8))
        if not query:
            msg = "rag_search requires a non-empty query"
            return ({"role": "tool", "tool_call_id": tool_call_id, "content": msg}, msg, False)
        from app.models.rag import RagCollection

        merged: list[dict] = []
        for cid in entry.get("collection_ids") or []:
            try:
                coll = await db.get(RagCollection, UUID(str(cid)))
                if coll is None:
                    continue
                hits = await rag_retrieve(
                    db, coll, UUID(state["org_id"]), RagRetrieveRequest(query=query, top_k=top_k),
                )
                for hit in hits:
                    merged.append({
                        "content": hit["content"], "score": hit["score"],
                        "document_id": hit["document_id"], "collection_id": str(cid),
                        "metadata": hit.get("metadata") or {},
                    })
            except Exception as exc:  # noqa: BLE001
                logger.warning("agent_rag_tool_failed", collection=str(cid), error=str(exc))
        merged.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        content = json.dumps({"status": "success", "query": query, "hits": merged[:top_k]}, ensure_ascii=False)
        return ({"role": "tool", "tool_call_id": tool_call_id, "content": content}, content[:4000], True)

    if entry.get("kind") == "prompt":
        content = entry.get("content") or ""
        _append_skill_record(state, "loaded_skills", entry["folder"], entry.get("version"), "load_skill")
        return ({"role": "tool", "tool_call_id": tool_call_id, "content": content}, content[:4000], True)
    if entry.get("kind") == "code":
        content = await _execute_code_skill(state, entry, params)
        try:
            ok = json.loads(content).get("status") == "success"
        except (json.JSONDecodeError, AttributeError):
            ok = False
        if ok:
            _append_skill_record(
                state, "executed_skills", entry["folder"], entry.get("version"), "runner_script",
            )
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


async def prepare_dsh_turn(state: AgentState) -> dict:
    """Assemble the authorized prompt and tool catalog for the DSH coordinator.

    Python remains the capability and authorization boundary.  This function deliberately
    performs no model loop and no eager RAG retrieval: DSH receives ``rag_search`` like any
    other scoped platform tool and decides when it is needed.
    """
    deps = get_deps()
    db = deps["db"]
    messages: list[dict] = list(state.get("messages", []))
    traces: list[dict] = list(state.get("traces", []))
    system_prompt = state.get("system_prompt", "")

    memory_context = ""
    mem_ctx = state.get("memory_context") or []
    if mem_ctx:
        parts = [
            f"[{item['scope_type']}{('/' + item['category']) if item.get('category') else ''}]\n{item['content']}"
            for item in mem_ctx
        ]
        memory_context = "[长期记忆]\n" + "\n\n".join(parts)

    ontology_ids = state.get("ontology_ids") or []
    if ontology_ids:
        ontologies = [
            item for item in [await db.get(OntologyFile, UUID(oid)) for oid in ontology_ids] if item
        ]
        ont_text = _compact_ontologies(ontologies)
        if ont_text:
            system_prompt = f"{system_prompt}\n\n[组织本体]\n{ont_text}"
        trace = {
            "category": "ontology", "title": "组织本体注入", "files": len(ontologies),
            "paths": [item.path for item in ontologies],
        }
        _emit({"type": "trace", **trace})
        traces.append(trace)

    user = deps.get("user")
    if user is not None:
        try:
            interfaces = await scope_service.list_data_interfaces_for_user(db, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning("load_data_interfaces_failed", error=str(exc))
            interfaces = []
        system_names = sorted({(item.system.name if item.system else "?") for item in interfaces})
        if interfaces:
            lines = []
            for item in interfaces:
                system_name = item.system.name if item.system else "?"
                lines.append(
                    f"- {system_name}/{item.name}"
                    f"{f' {item.method}' if item.method else ''}"
                    f"{f' {item.path}' if item.path else ''}"
                    f"{f': {item.description}' if item.description else ''}"
                    f"{_format_data_interface_params(item)}"
                )
            system_prompt = (
                f"{system_prompt}\n\n[数据接口] 以下为当前可用数据接口（仅供参考其参数/返回结构，"
                "不能直接执行调用；path 中 {占位符} 为路径参数，调用时须提供实际值）：\n"
                + "\n".join(lines)
            )
        trace = {
            "category": "data_interface", "title": "数据接口注入",
            "systems": len(system_names), "interfaces": len(interfaces),
            "names": [f"{(item.system.name if item.system else '?')}/{item.name}" for item in interfaces],
        }
        _emit({"type": "trace", **trace})
        traces.append(trace)

    skill_catalog = list(state.get("skill_catalog") or [])
    if skill_catalog:
        default_ids = {item.get("id") for item in state.get("default_skills") or []}
        invoked_ids = {item.get("id") for item in state.get("invoked_skills") or []}
        lines: list[str] = []
        for item in skill_catalog[:80]:
            priority = "本轮明确" if item.get("id") in invoked_ids else (
                "智能体默认" if item.get("id") in default_ids else "可用"
            )
            executable = "可执行" if item.get("is_executable") else "说明/API"
            description = str(item.get("description") or "").replace("\n", " ")[:240]
            lines.append(
                f"- [{priority}] id={item.get('id')} /{item.get('slug')} {item.get('name')} | "
                f"{item.get('scope_type')} | {executable} | {description}"
            )
        if len(skill_catalog) > 80:
            lines.append(f"- 其余 {len(skill_catalog) - 80} 个技能未展开；请让用户用选择器明确指定。")
        system_prompt = (
            f"{system_prompt}\n\n[当前用户可用 Skill 目录]\n"
            "此目录仅用于发现能力。不要把目录内容当作已执行结果；需要说明时调用 load_skill，"
            "需要脚本或企业操作时必须实际调用相应工具。\n" + "\n".join(lines)
        )
    ambiguities = state.get("skill_slug_ambiguities") or []
    if ambiguities:
        system_prompt = (
            f"{system_prompt}\n\n[Skill 引用歧义]\n以下 /slug 对应多个作用域，不能自动选择："
            f"{', '.join('/' + slug for slug in ambiguities)}。请让用户通过‘本轮调用技能’选择器指定。"
        )

    file_parts: list[str] = []
    file_names: list[str] = []
    file_refs: list[dict[str, str]] = []
    for fid in state.get("referenced_file_ids") or []:
        try:
            workspace_file = await workspace_service.get_file(db, UUID(fid))
        except (ValueError, AttributeError):
            workspace_file = None
        if workspace_file is None or not workspace_file.workspace_id:
            continue
        workspace = await workspace_service.get_workspace(db, UUID(str(workspace_file.workspace_id)))
        if workspace is None or (user is not None and not (
            await workspace_permission_service.capabilities(db, workspace, user)
        )["read"]):
            continue
        file_names.append(workspace_file.path)
        file_refs.append({"file_id": fid, "path": workspace_file.path})
        content = workspace_service.resolve_file_content(workspace_file)
        raw_tool = workspace_service.raw_tool_file_kind(workspace_file)
        suffix = PurePosixPath(
            str((workspace_file.metadata_ or {}).get("name") or workspace_file.path)
        ).suffix.lower()
        is_current_image = (
            any(str(item.get("file_id")) == fid for item in state.get("attachment_files") or [])
            and suffix in multimodal_service.ALLOWED_IMAGE_SUFFIXES
        )
        if is_current_image:
            rendered = "（本轮原始图片由平台视觉路由处理；如需 OCR、裁剪或格式转换再调用 image_tool。）"
        elif workspace_file.parse_status != "ready" and raw_tool:
            rendered = (
                f"（原始二进制附件无需正文解析；请使用 {raw_tool} 并把 file_id={fid} 作为 "
                "input_file_ids 实际读取。不得声称附件不可用，也不得编造处理结果。）"
            )
        else:
            rendered = content if content.strip() else "（文件内容为空或尚未解析，无法直接分析）"
        file_parts.append(f"[引用文件 file_id={fid} path={workspace_file.path}]\n{rendered}")
    if file_refs:
        mapping = "\n".join(f"- @{item['file_id']} → {item['path']}" for item in file_refs)
        system_prompt = (
            f"{system_prompt}\n\n[已解析的文件引用]\n"
            "本轮结构化附件或用户消息中的 @UUID 已由系统精确解析，映射如下：\n"
            f"{mapping}\n这些文件内容已直接载入下方上下文。请把 UUID 与对应路径视为同一个文件，"
            "不得声称无法按 UUID 定位；除非用户明确要求比较其他文件，否则不要调用工作空间列表/"
            "读取工具，也不要分析未引用文件。\n\n" + "\n\n".join(file_parts)
        )
        trace = {
            "category": "file", "title": "引用工作空间文件", "files": len(file_names),
            "paths": file_names, "references": file_refs,
        }
        _emit({"type": "trace", **trace})
        traces.append(trace)

    exec_mode = state.get("exec_mode") or "craft"
    if exec_mode == "ask":
        system_prompt = f"{system_prompt}{ASK_PROMPT}"
        tools, registry = [], {}
    elif exec_mode == "plan":
        system_prompt = f"{system_prompt}{PLAN_PROMPT}"
        tools, registry = [], {}
    else:
        tools, registry = await _build_tools(
            db, state.get("skill_ids") or [], state.get("workspace_id"), user,
        )
        rag_ids = list(state.get("rag_collection_ids") or [])
        if state.get("rag_collection_id") and str(state["rag_collection_id"]) not in rag_ids:
            rag_ids.append(str(state["rag_collection_id"]))
        from app.services.platform_tool_registry import active_platform_tool_names

        active_platform_names = await active_platform_tool_names(db)
        if rag_ids and (active_platform_names is None or "rag_search" in active_platform_names):
            tools.append({
                "type": "function",
                "function": {
                    "name": "rag_search",
                    "description": "按需检索当前智能体已绑定且当前用户有权访问的知识库。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "检索问题或关键词"},
                            "top_k": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5},
                        },
                        "required": ["query"],
                    },
                },
            })
            registry["rag_search"] = {"kind": "rag_search", "collection_ids": rag_ids}
        system_prompt = f"{system_prompt}{TOOL_STRATEGY_PROMPT}{OUTPUT_PROTOCOL_PROMPT}"
        referenced = state.get("referenced_skills") or []
        if referenced:
            lines = "\n".join(
                f"- id={item.get('id')} {item['name']} (/{item['slug']}, {item.get('activation', 'explicit')})"
                for item in referenced
            )
            system_prompt = (
                f"{system_prompt}\n\n[用户本轮明确调用的 Skill] 以下选择仅对当前轮有效。"
                "请先加载其完整说明，并在任务需要操作时务必实际调用脚本或接口，不得仅声称完成：\n"
                f"{lines}"
            )

    provider, model, system_prompt = await _configure_visual_turn(
        state, db, user, messages, system_prompt,
    )
    return {
        "messages": messages, "system_prompt": system_prompt, "tools": tools,
        "registry": registry, "traces": traces, "provider_override": provider,
        "model_override": model, "memory_context": memory_context,
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
                           metadata_={
                               "traces": state.get("traces", []),
                               "loaded_skills": state.get("loaded_skills", []),
                               "executed_skills": state.get("executed_skills", []),
                           }))
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
