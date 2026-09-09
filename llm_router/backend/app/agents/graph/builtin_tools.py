"""Authorized workspace, file, web and multimodal tool execution helpers.

The native Assistant Core keeps orchestration in :mod:`nodes`; this module owns the
large built-in tool catalog and the corresponding execution paths.  The public
helpers are re-exported by ``nodes`` for compatibility with persisted callers and
tests.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select

from app.agents.graph.context import get_deps as _context_get_deps
from app.agents.graph.state import AgentState
from app.auth.user_auth import current_user_for_user
from app.dlp.scanner import scan_request
from app.models.audit_log import AuditLog
from app.models.workspace import WorkspaceFileMutation, WorkspaceFileVersion
from app.schemas.workspace import WorkspaceFileCreate, WorkspaceFileUpdate
from app.services import model_gateway as llm_client
from app.services import (
    multimodal_service,
    scope_service,
    storage_gateway_service,
    tool_executor_client,
    workspace_governance_service,
    workspace_permission_service,
    workspace_service,
)
from app.services.file_capability_registry import (
    FILE_TOOL_OPERATIONS,
    LEGACY_FAMILY_TO_TOOL,
    FileToolValidationError,
    file_tool_definitions,
    normalize_file_tool_call,
    validate_artifact_bytes,
)
from app.utils.workspace_presentation import clean_display_name, enrich_metadata, presentation_dict

logger = structlog.get_logger()

RUNNER_INLINE_FILE_BYTES = 10 * 1024 * 1024
RUNNER_MAX_FILE_BYTES = 100 * 1024 * 1024


def get_deps() -> dict[str, Any]:
    """Resolve the runtime binding while preserving ``nodes.get_deps`` test patches."""

    from app.agents.graph import nodes

    resolver = getattr(nodes, "get_deps", _context_get_deps)
    return resolver()


async def _task_source_fields(db: Any, state: AgentState) -> dict[str, str | None]:
    """Delegate task provenance lookup to the orchestration module."""

    from app.agents.graph import nodes

    return await nodes._task_source_fields(db, state)


STRICT_FILE_TOOL_NAMES = set(FILE_TOOL_OPERATIONS)
LEGACY_FILE_TOOL_NAMES = set(LEGACY_FAMILY_TO_TOOL.values())
PLATFORM_TOOL_NAMES = {
    *STRICT_FILE_TOOL_NAMES,
    *LEGACY_FILE_TOOL_NAMES,
    "image_tool",
    "archive_tool",
    "web_tool",
}
ALWAYS_AVAILABLE_TOOL_NAMES = {"web_tool"}
BUSINESS_ASSISTANT_FILE_TOOL_NAMES = {
    "workspace_list",
    "workspace_search",
    "workspace_get_file",
    "workspace_list_files",
    "workspace_read_file",
    "workspace_create_file",
    "workspace_write_file",
    "workspace_update_file",
    "workspace_list_versions",
    *STRICT_FILE_TOOL_NAMES,
    "image_tool",
    "archive_tool",
}
BUILTIN_TOOL_NAMES = {
    "workspace_list",
    "workspace_search",
    "workspace_get_file",
    "workspace_list_files",
    "workspace_read_file",
    "workspace_create_file",
    "workspace_write_file",
    "workspace_update_file",
    "workspace_rename_file",
    "workspace_move_file",
    "workspace_copy_file",
    "workspace_delete_file",
    "workspace_list_versions",
    "workspace_restore_version",
    *PLATFORM_TOOL_NAMES,
    "image_generation_tool",
}
# Kept executable for old persisted calls, but no longer advertised to new LLM rounds.
LEGACY_BUILTIN_TOOL_NAMES = {"generate_docx"}


def _builtin_tool_defs(
    *,
    include_workspace: bool = True,
    include_image_generation: bool = False,
) -> list[dict]:
    """内置工作空间文件工具的 OpenAI function-tool 定义。"""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "workspace_list",
                "description": "实时列出当前用户全部可读工作空间及角色能力；不要求先点名或引用文件。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                        "offset": {"type": "integer", "minimum": 0},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_search",
                "description": "搜索当前用户所有实时可读工作空间，返回稳定文件、版本、路径和 capabilities。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "workspace_id": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                        "offset": {"type": "integer", "minimum": 0},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_get_file",
                "description": "按稳定 file_id 获取文件元数据、当前版本、路径和实时 capabilities。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "version_id": {"type": "string"},
                    },
                    "required": ["file_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_list_files",
                "description": "兼容工具；省略 workspace_id 时列出所有实时可读空间的文件。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                        "offset": {"type": "integer", "minimum": 0},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_read_file",
                "description": (
                    "按稳定 file_id 读取任一实时可读空间中的文件；兼容 workspace_id + path。"
                    "用户消息含 @UUID 时直接作为 file_id；"
                    "若[已解析的文件引用]已经注入内容，无需重复调用。大文件结果包含 has_more 与 next_offset，"
                    "必须按 next_offset 继续读取，不能把当前页当作完整文件。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "工作空间文件 UUID"},
                        "version_id": {"type": "string", "description": "可选的精确历史版本 UUID"},
                        "path": {"type": "string", "description": "相对工作空间根的 POSIX 路径"},
                        "offset": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "从第几行开始读取（1-based，默认 1）",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1000,
                            "description": "最多读取多少行（默认 200，最大 1000）",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_create_file",
                "description": "在有实时 create 权限的目标工作空间原子创建一个新文本文件；路径已存在时返回冲突。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_workspace_id": {"type": "string"},
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_write_file",
                "description": "兼容写工具；file_id 存在时原位更新并生成新版本，否则按 path 新建文本文件。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "base_version_id": {"type": "string"},
                        "idempotency_key": {"type": "string", "minLength": 8},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_update_file",
                "description": (
                    "按 file_id 原位更新文本内容；必须带读取到的 base_version_id，重试复用 idempotency_key。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "content": {"type": "string"},
                        "base_version_id": {"type": "string"},
                        "idempotency_key": {"type": "string", "minLength": 8},
                    },
                    "required": ["file_id", "content", "base_version_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_rename_file",
                "description": "按 file_id 重命名同一文件并保留稳定 ID。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "new_name": {"type": "string"},
                        "base_version_id": {"type": "string"},
                        "idempotency_key": {"type": "string", "minLength": 8},
                    },
                    "required": ["file_id", "new_name", "base_version_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_move_file",
                "description": "按 file_id 移动/改名文件并保留稳定 ID；可指定有新建权限的目标工作空间。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "target_path": {"type": "string"},
                        "target_workspace_id": {"type": "string"},
                        "base_version_id": {"type": "string"},
                        "idempotency_key": {"type": "string", "minLength": 8},
                    },
                    "required": ["file_id", "target_path", "base_version_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_copy_file",
                "description": "复制 file_id 到有新建权限的目标工作空间，返回新的稳定 file_id。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "target_workspace_id": {"type": "string"},
                        "target_path": {"type": "string"},
                        "base_version_id": {"type": "string"},
                        "idempotency_key": {"type": "string", "minLength": 8},
                    },
                    "required": ["file_id", "target_workspace_id", "base_version_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_delete_file",
                "description": "按 file_id 删除有实时 delete 权限的文件；兼容 workspace_id + path。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "path": {"type": "string"},
                        "base_version_id": {"type": "string"},
                        "idempotency_key": {"type": "string", "minLength": 8},
                    },
                    "required": ["file_id", "base_version_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_list_versions",
                "description": "按 file_id 列出不可变版本。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                    },
                    "required": ["file_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "workspace_restore_version",
                "description": "把 file_id 恢复到指定 version_id，并创建新的当前版本。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "version_id": {"type": "string"},
                        "base_version_id": {"type": "string"},
                        "idempotency_key": {"type": "string", "minLength": 8},
                    },
                    "required": ["file_id", "version_id", "base_version_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "spreadsheet_tool",
                "description": "检查、创建、编辑或转换 Excel/CSV/TSV/ODS 表格。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["inspect", "create", "edit", "convert"]},
                        "input_file_ids": {"type": "array", "items": {"type": "string"}},
                        "output_name": {"type": "string"},
                        "sheets": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                                },
                            },
                        },
                        "operations": {"type": "array", "items": {"type": "object"}},
                        "target_format": {"type": "string"},
                        "sheet": {"type": "string", "description": "inspect 时可选的工作表名称"},
                        "range": {"type": "string", "description": "inspect 时可选 A1 范围，例如 A2:F200"},
                        "offset": {"type": "integer", "minimum": 0, "description": "inspect 分页的零基行偏移"},
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1000,
                            "description": "inspect 每次读取行数",
                        },
                        "max_rows": {"type": "integer", "description": "兼容旧客户端；优先使用 limit"},
                        "max_columns": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "document_tool",
                "description": "检查、创建、编辑或转换 Word/DOCX/DOC/ODT/RTF 文档；正文使用 Markdown。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["inspect", "create", "edit", "convert"]},
                        "input_file_ids": {"type": "array", "items": {"type": "string"}},
                        "output_name": {"type": "string"},
                        "markdown": {"type": "string"},
                        "replace": {"type": "boolean"},
                        "target_format": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "presentation_tool",
                "description": "检查、创建、追加编辑或转换 PowerPoint/PPTX/PPT/ODP 演示文稿。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["inspect", "create", "edit", "convert"]},
                        "input_file_ids": {"type": "array", "items": {"type": "string"}},
                        "output_name": {"type": "string"},
                        "slides": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "bullets": {"type": "array", "items": {"type": "string"}},
                                    "notes": {"type": "string"},
                                },
                            },
                        },
                        "target_format": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "pdf_tool",
                "description": (
                    "检查、创建、合并、提取页面或转换 PDF。edit 时 operation 可为 merge、split、extract_pages。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["inspect", "create", "edit", "convert"]},
                        "input_file_ids": {"type": "array", "items": {"type": "string"}},
                        "output_name": {"type": "string"},
                        "markdown": {"type": "string"},
                        "operation": {"type": "string", "enum": ["merge", "split", "extract_pages"]},
                        "pages": {"type": "array", "items": {"type": "integer"}},
                        "target_format": {"type": "string"},
                        "max_pages": {"type": "integer"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "text_tool",
                "description": "检查、创建、编辑或转换 UTF-8 TXT/Markdown 文本文件。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["inspect", "create", "edit", "convert"]},
                        "input_file_ids": {"type": "array", "items": {"type": "string"}},
                        "output_name": {"type": "string"},
                        "content": {"type": "string"},
                        "replace": {"type": "boolean"},
                        "format": {"type": "string"},
                        "target_format": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "image_tool",
                "description": "检查、转换、缩放、裁剪、压缩图片，或对图片/扫描 PDF 执行中英文 OCR。",
                "parameters": {
                    "type": "object",
                    "properties": {
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
                    },
                    "required": ["action", "input_file_ids"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "archive_tool",
                "description": "安全查看、解压或创建 ZIP/TAR/TAR.GZ；解压结果写回当前工作空间。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list", "extract", "create"]},
                        "input_file_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20},
                        "output_name": {"type": "string"},
                        "format": {"type": "string", "enum": ["zip", "tar", "tar.gz"]},
                    },
                    "required": ["action", "input_file_ids"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_tool",
                "description": (
                    "搜索公开网页、提取指定网页正文，或把公开 URL 下载到工作空间。"
                    "禁止访问 localhost、内网与云元数据地址。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["search", "fetch", "download"]},
                        "query": {"type": "string"},
                        "url": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                        "max_chars": {"type": "integer", "minimum": 1000, "maximum": 100000},
                        "output_name": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        },
    ]
    # New model rounds only see operation-specific, closed schemas.  Hidden
    # legacy aliases remain executable so persisted calls do not break.
    tools = [
        item for item in tools if str((item.get("function") or {}).get("name") or "") not in LEGACY_FILE_TOOL_NAMES
    ]
    tools.extend(file_tool_definitions())
    if include_image_generation:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "image_generation_tool",
                    "description": (
                        "使用当前组织配置的专用生图模型生成真实图片，并保存到当前工作空间。"
                        "仅在用户明确要求生成图片、插画、海报或视觉素材时调用。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "prompt": {"type": "string", "description": "完整、具体的生图提示词"},
                            "output_name": {"type": "string", "description": "输出文件名；系统统一保存为 PNG"},
                            "size": {"type": "string", "description": "如 1024x1024、1536x1024、1024x1536 或 auto"},
                            "quality": {"type": "string", "enum": ["auto", "low", "medium", "high"]},
                        },
                        "required": ["prompt"],
                    },
                },
            }
        )
    for item in tools:
        function = item.get("function") or {}
        properties = (function.get("parameters") or {}).get("properties")
        if not isinstance(properties, dict):
            continue
        tool_name = function.get("name")
        if tool_name in {"workspace_list_files", "workspace_read_file", "workspace_delete_file"}:
            properties["workspace_id"] = {
                "type": "string",
                "description": "可选工作空间 UUID；list 省略时覆盖所有可读空间，path 操作省略时使用个人空间",
            }
        if tool_name in {
            "workspace_write_file",
            "generate_docx",
            "image_generation_tool",
            "image_tool",
            "archive_tool",
            "web_tool",
        }:
            properties["target_workspace_id"] = {
                "type": "string",
                "description": "新建输出目标；省略时使用个人空间。按 file_id 更新时由文件确定空间",
            }
        if tool_name in {"image_tool", "archive_tool", "web_tool"}:
            properties.update(
                {
                    "target_file_id": {
                        "type": "string",
                        "description": "可选：单个产出原位更新的稳定文件 UUID；不传则创建新文件",
                    },
                    "base_version_id": {
                        "type": "string",
                        "description": "target_file_id 存在时必填：开始编辑时读取到的版本 UUID",
                    },
                    "idempotency_key": {
                        "type": "string",
                        "minLength": 8,
                        "description": "target_file_id 存在时必填：同一次重试必须复用",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "创建新文件时的目标相对路径；省略则生成隔离输出路径",
                    },
                }
            )
    if include_workspace:
        return tools
    return [tool for tool in tools if tool.get("function", {}).get("name") in ALWAYS_AVAILABLE_TOOL_NAMES]


async def _runner_input(file) -> dict:
    """Keep large OSS objects out of agent/backend JSON payloads."""
    meta = file.metadata_ or {}
    item = {
        "file_id": str(file.id),
        "name": str(meta.get("name") or PurePosixPath(file.path).name),
        "expected_size": file.size,
    }
    if file.size > RUNNER_INLINE_FILE_BYTES and storage_gateway_service.is_object_ref(file.content_ref):
        signed = await storage_gateway_service.get_signed_download(
            str(file.content_ref),
            version_id=workspace_service.storage_version_id(file),
        )
        item.update({"download_url": signed["url"], "download_headers": signed.get("headers") or {}})
    else:
        raw = await workspace_service.load_file_bytes(file)
        item["content_base64"] = base64.b64encode(raw).decode("ascii")
    return item


async def _validated_runner_output(
    item: dict,
    fallback_mime: str,
) -> tuple[str, int, str, str, str, str, bool]:
    """Trust OSS, not the Runner response, for large output metadata."""
    content_ref = str(item.get("content_ref") or "")
    actual = await storage_gateway_service.inspect_object(content_ref)
    actual_size = int(actual.get("size") or 0)
    if actual_size <= 0:
        raise ValueError("Runner 输出文件为空")
    if actual_size > RUNNER_MAX_FILE_BYTES:
        raise ValueError("Runner 单次处理产出超过 100MB 上限（平台工作空间仍可存储最大 5GB 文件）")
    declared_size = int(item.get("size") or 0)
    if declared_size and declared_size != actual_size:
        raise ValueError(f"Runner 输出大小校验失败：声明 {declared_size}，实际 {actual_size}")
    actual_etag = str(actual.get("etag") or "").strip('"')
    declared_etag = str(item.get("etag") or "").strip('"')
    if declared_etag and actual_etag and declared_etag != actual_etag:
        raise ValueError("Runner 输出 ETag 校验失败")
    actual_hash = str(actual.get("content_hash") or "").casefold()
    if len(actual_hash) != 64 or any(ch not in "0123456789abcdef" for ch in actual_hash):
        raise ValueError("Runner 输出缺少可验证的 SHA-256")
    declared_hash = str(item.get("content_hash") or "").casefold()
    if declared_hash and declared_hash != actual_hash:
        raise ValueError("Runner 输出 SHA-256 校验失败")
    actual_mime = str(actual.get("content_type") or "").split(";", 1)[0].strip().lower()
    mime = actual_mime if actual_mime and actual_mime != "application/octet-stream" else fallback_mime
    detected_format = str(actual.get("detected_format") or "")
    format_verified = actual.get("format_verified") is True and bool(detected_format)
    return (
        content_ref,
        actual_size,
        mime,
        actual_etag,
        actual_hash,
        detected_format,
        format_verified,
    )


async def _fresh_user_principal(db, user):
    """Rebuild mutable role permissions immediately before a file operation."""
    from app.agents.graph import nodes

    override = getattr(nodes, "_fresh_user_principal", None)
    if override is not None and override is not _fresh_user_principal:
        return await override(db, user)
    if user is None or getattr(user, "user", None) is None:
        return user
    return await current_user_for_user(db, user.user)


async def _resolve_tool_workspace(
    state: AgentState,
    params: dict,
    user,
    *,
    capability: str,
    parameter: str,
):
    """Resolve a workspace and enforce the user's current RBAC capability."""
    deps = get_deps()
    db = deps["db"]
    default_id = str(state.get("workspace_id") or "")
    requested_id = str(params.get(parameter) or default_id).strip()
    if not requested_id:
        return None, user, "no workspace bound to this task"
    try:
        workspace = await workspace_service.get_workspace(db, UUID(requested_id))
    except (ValueError, TypeError, AttributeError):
        workspace = None
    if workspace is None:
        return None, user, "工作空间不存在或无权访问"
    principal = await _fresh_user_principal(db, user)
    if principal is None:
        # Admin/playground runs do not carry an employee RBAC principal.  They
        # are therefore confined to the workspace selected when the run was
        # created; a model-supplied UUID must never turn that absence into
        # cross-tenant discovery or mutation authority.
        if str(workspace.id) != default_id:
            return None, principal, "工作空间不存在或无权访问"
    elif not (await workspace_permission_service.capabilities(db, workspace, principal)).get(capability, False):
        return None, principal, "工作空间权限已撤销或不允许此操作"
    return workspace, principal, None


async def _authorized_file(state: AgentState, value: object, user, *, capability: str):
    deps = get_deps()
    db = deps["db"]
    try:
        file = await workspace_service.get_file(db, UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        file = None
    if file is None:
        return None, None, user
    workspace = await workspace_service.get_workspace(db, file.workspace_id)
    principal = await _fresh_user_principal(db, user)
    if workspace is None:
        return None, None, principal
    if principal is None:
        # Admin playground agents retain their single configured workspace.
        if str(file.workspace_id) != str(state.get("workspace_id") or ""):
            return None, None, principal
    elif not (await workspace_permission_service.capabilities(db, workspace, principal)).get(capability, False):
        return None, None, principal
    return file, workspace, principal


async def _authorized_create_replay(state: AgentState, mutation, user):
    """Authorize and reconstruct an immutable create result for safe replay.

    A stable file may have been moved to a workspace the caller can no longer
    read after the original create completed.  Replays therefore authorize the
    *current* real location first, then separately authorize the original
    presentation workspace and return the original result version/path rather
    than leaking later state.
    """
    deps = get_deps()
    db = deps["db"]
    if not mutation.result_file_id or not mutation.result_version_id:
        return None, None, user
    live, _live_workspace, principal = await _authorized_file(
        state,
        mutation.result_file_id,
        user,
        capability="read",
    )
    if live is None:
        return None, None, principal
    result = dict(mutation.result or {})
    original_workspace_id = result.get("workspace_id") or mutation.workspace_id
    try:
        original_workspace = await workspace_service.get_workspace(
            db,
            UUID(str(original_workspace_id)),
        )
    except (TypeError, ValueError):
        original_workspace = None
    if original_workspace is None:
        return None, None, principal
    if principal is None:
        if str(original_workspace.id) != str(state.get("workspace_id") or ""):
            return None, None, principal
    elif not (await workspace_permission_service.capabilities(db, original_workspace, principal)).get("read", False):
        return None, None, principal
    try:
        snapshot, _ = await workspace_service.file_snapshot_at_version(
            db,
            live,
            UUID(str(mutation.result_version_id)),
        )
    except (TypeError, ValueError, workspace_service.WorkspaceFileVersionNotFound):
        return None, None, principal
    original_path = str(result.get("path") or "").strip()
    if not original_path:
        # Older durable claims did not store the result path.  It is safe to
        # use the live path only while the file is still exactly at the
        # original result generation/location; otherwise fail closed.
        if str(live.workspace_id) != str(original_workspace.id) or str(live.current_version_id or "") != str(
            mutation.result_version_id
        ):
            return None, None, principal
        original_path = live.path
    snapshot.workspace_id = original_workspace.id
    snapshot.path = original_path
    snapshot.metadata_ = dict(snapshot.metadata_ or {})
    snapshot.metadata_["name"] = PurePosixPath(original_path).name
    snapshot.is_mutation_replay = True
    snapshot.mutation_result_version_id = mutation.result_version_id
    return snapshot, original_workspace, principal


async def _authorized_input_file(state: AgentState, value: object, user):
    file, _workspace, principal = await _authorized_file(
        state,
        value,
        user,
        capability="read",
    )
    version_id = _referenced_version_id(state, str(value))
    if file is not None and version_id is not None:
        try:
            file, _ = await workspace_service.file_snapshot_at_version(
                get_deps()["db"],
                file,
                version_id,
            )
        except workspace_service.WorkspaceFileVersionNotFound:
            return None, principal
    return file, principal


def _referenced_version_id(
    state: AgentState,
    file_id: str,
    explicit_version_id: object | None = None,
) -> UUID | None:
    raw = explicit_version_id
    if raw is None:
        for item in state.get("file_refs_v1") or []:
            if str(item.get("file_id") or "") != str(file_id):
                continue
            if not bool(item.get("follow_latest", True)):
                raw = item.get("version_id")
                break
    try:
        return UUID(str(raw)) if raw else None
    except (TypeError, ValueError):
        return None


async def _workspace_file_identity(db, file, workspace, user) -> dict:
    caps = (
        await workspace_permission_service.capabilities(db, workspace, user)
        if user is not None
        else {"read": True, "create": True, "update": True, "delete": True}
    )
    version, previous_version_id = await workspace_service.version_lineage(db, file)
    current_version_id = str(file.current_version_id) if file.current_version_id else None
    internal_url = f"/f/{file.id}"
    if getattr(file, "is_historical", False) and current_version_id:
        internal_url = f"{internal_url}?version={current_version_id}"
    return {
        "file_id": str(file.id),
        "workspace_id": str(workspace.id),
        "workspace_name": workspace.name,
        "workspace_slug": workspace.slug,
        "path": file.path,
        "canonical_path": f"{workspace.name}:/{str(file.path).lstrip('/')}",
        "version_id": current_version_id,
        "current_version_id": current_version_id,
        "mutation_result_version_id": (str(getattr(file, "mutation_result_version_id", "") or "") or None),
        "previous_version_id": str(previous_version_id) if previous_version_id else None,
        "current_version_no": int(version.version_no) if version is not None else None,
        "content_hash": file.content_hash,
        "capabilities": caps,
        "effective_capabilities": caps,
        "internal_url": internal_url,
    }


def _remember_tool_file(
    state: AgentState,
    identity: dict,
    *,
    operation: str,
    tool_name: str,
) -> None:
    """Record exact file/version access independently from truncated traces."""
    file_id = str(identity.get("file_id") or "")
    if not file_id:
        return
    version_id = (
        identity.get("mutation_result_version_id") or identity.get("version_id") or identity.get("current_version_id")
    )
    record = {
        "file_id": file_id,
        "scope": "turn",
        "version_id": str(version_id) if version_id else None,
        "follow_latest": True,
        "source": "tool_result",
        "operation": operation,
        "tool_name": tool_name,
        "workspace_id": identity.get("workspace_id"),
        "workspace_name": identity.get("workspace_name"),
        "canonical_path": identity.get("canonical_path"),
        "display_name": identity.get("display_name") or identity.get("name"),
        "mime_type": identity.get("mime_type") or identity.get("mime"),
        "size": identity.get("size"),
        "parse_status": identity.get("parse_status"),
        "created_new": bool(
            operation in {"create", "write", "copy", "output"} and not identity.get("previous_version_id")
        ),
        "tool_call_id": identity.get("tool_call_id"),
    }
    accesses = state.setdefault("file_accesses_v1", [])
    marker = (record["file_id"], record["version_id"], operation, tool_name)
    if marker not in {
        (item.get("file_id"), item.get("version_id"), item.get("operation"), item.get("tool_name")) for item in accesses
    }:
        accesses.append(record)
    refs = state.setdefault("tool_file_refs", [])
    refs[:] = [item for item in refs if str(item.get("file_id") or "") != file_id]
    refs.append(record)


def _remember_structured_tool_result(
    state: AgentState,
    tool_name: str,
    payload: dict,
) -> None:
    """Capture stable identities from the untruncated tool result."""
    direct_operations = {
        "workspace_get_file": "metadata_read",
        "workspace_read_file": "read",
        "workspace_create_file": "create",
        "workspace_write_file": "write",
        "workspace_update_file": "update",
        "workspace_rename_file": "rename",
        "workspace_move_file": "move",
        "workspace_copy_file": "copy",
        "workspace_restore_version": "restore",
        "image_generation_tool": "create",
    }
    candidates: list[dict] = []
    if tool_name in direct_operations and payload.get("file_id"):
        candidates.append(payload)
    outputs = payload.get("outputs")
    if isinstance(outputs, list) and (
        tool_name in PLATFORM_TOOL_NAMES or tool_name == "image_generation_tool"
    ):
        candidates.extend(item for item in outputs if isinstance(item, dict))
    operation = direct_operations.get(tool_name, "output")
    for candidate in candidates:
        _remember_tool_file(
            state,
            candidate,
            operation=operation,
            tool_name=tool_name,
        )


_ARTIFACT_OPERATIONS = {"create", "write", "update", "rename", "move", "copy", "restore", "output"}


async def _verified_tool_file_records(
    state: AgentState,
    records: list[dict[str, Any]],
    user,
    *,
    task_id: str,
    task_title: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Re-resolve server-recorded tool files before persisting refs/cards.

    A model or subsystem can return an arbitrary ``file_id`` string. Only the
    canonical file tools populate ``tool_file_refs`` and every candidate is
    then checked against the live logical file, tenant and fresh RBAC state.
    No metadata from an untrusted tool result is copied into the UI card.
    """
    db = get_deps()["db"]
    principal = await _fresh_user_principal(db, user)
    trusted_tools = BUILTIN_TOOL_NAMES | LEGACY_BUILTIN_TOOL_NAMES
    verified: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str]] = set()
    for candidate in records:
        if not isinstance(candidate, dict):
            continue
        tool_name = str(candidate.get("tool_name") or "")
        operation = str(candidate.get("operation") or "")
        if candidate.get("source") != "tool_result" or tool_name not in trusted_tools:
            continue
        try:
            file_id = UUID(str(candidate.get("file_id") or ""))
        except (TypeError, ValueError):
            continue
        file = await workspace_service.get_file(db, file_id)
        workspace = await workspace_service.get_workspace(db, file.workspace_id) if file is not None else None
        if file is None or workspace is None or str(workspace.organization_id) != str(state.get("org_id") or ""):
            continue
        if principal is None:
            if str(workspace.id) != str(state.get("workspace_id") or ""):
                continue
            capabilities = {"read": True, "create": True, "update": True, "delete": True}
        else:
            capabilities = await workspace_permission_service.capabilities(db, workspace, principal)
            if not capabilities.get("read"):
                continue
        raw_version_id = candidate.get("version_id")
        version = None
        if raw_version_id:
            try:
                version = await db.get(WorkspaceFileVersion, UUID(str(raw_version_id)))
            except (TypeError, ValueError):
                version = None
            if version is None or str(version.workspace_file_id) != str(file.id):
                continue
        resolved_version_id = (
            str(version.id)
            if version is not None
            else (str(file.current_version_id) if file.current_version_id else None)
        )
        presentation_workspace = workspace
        presentation_path = file.path
        if operation == "copy" and version is not None:
            # A replayed copy may have been moved again after its original
            # result committed.  Authorize against the logical file's *live*
            # workspace above, but render only the immutable mutation result;
            # otherwise the replay would disclose a later workspace/path and
            # falsely present that later state as this request's output.
            mutation = (
                await db.execute(
                    select(WorkspaceFileMutation)
                    .where(
                        WorkspaceFileMutation.operation == "copy",
                        WorkspaceFileMutation.status == "completed",
                        WorkspaceFileMutation.result_file_id == file.id,
                        WorkspaceFileMutation.result_version_id == version.id,
                    )
                    .order_by(WorkspaceFileMutation.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if mutation is None:
                continue
            result_workspace = await workspace_service.get_workspace(
                db,
                UUID(str(mutation.workspace_id)),
            )
            result_path = str((mutation.result or {}).get("target_path") or "")
            if (
                result_workspace is None
                or str(result_workspace.organization_id) != str(state.get("org_id") or "")
                or not result_path
            ):
                continue
            if principal is not None and not (
                await workspace_permission_service.capabilities(
                    db,
                    result_workspace,
                    principal,
                )
            ).get("read"):
                continue
            presentation_workspace = result_workspace
            presentation_path = result_path
        marker = (str(file.id), resolved_version_id, operation)
        if marker in seen:
            continue
        seen.add(marker)
        canonical_path = f"{presentation_workspace.name}:/{str(presentation_path).lstrip('/')}"
        record = {
            "file_id": str(file.id),
            "scope": "turn",
            "version_id": resolved_version_id,
            "follow_latest": True,
            "source": "tool_result",
            "operation": operation,
            "tool_name": tool_name,
            "workspace_id": str(presentation_workspace.id),
            "workspace_name": presentation_workspace.name,
            "canonical_path": canonical_path,
        }
        verified.append(record)
        if operation not in _ARTIFACT_OPERATIONS:
            continue
        metadata = dict((version.metadata_ if version is not None else file.metadata_) or {})
        path = presentation_path
        presentation = presentation_dict(path, metadata, created_at=file.created_at)
        artifact = {
            "file_id": str(file.id),
            "display_name": presentation["display_name"],
            "mime_type": metadata.get("mime"),
            "size": int(version.size if version is not None else file.size),
            "parse_status": version.parse_status if version is not None else file.parse_status,
            "current_version_id": resolved_version_id,
            "version_id": resolved_version_id,
            "workspace_id": str(presentation_workspace.id),
            "workspace_name": presentation_workspace.name,
            "workspace_path": path,
            "canonical_path": canonical_path,
            "internal_url": (f"/f/{file.id}?version={resolved_version_id}" if resolved_version_id else f"/f/{file.id}"),
            "operation": operation,
            "created_new": bool(candidate.get("created_new")),
            "checksum_sha256": (
                getattr(version, "content_hash", None) if version is not None else getattr(file, "content_hash", None)
            ),
            "source": {
                "kind": presentation["source_kind"],
                "created_by_user_id": str(getattr(user, "id", "") or "") or None,
                "task_id": task_id,
                "task_title": task_title,
                "run_id": state.get("run_id"),
                "tool_call_id": candidate.get("tool_call_id"),
                "request_id": state.get("client_request_id"),
                "application_id": state.get("application_id"),
                "module_key": (state.get("page_context") or {}).get("module_key"),
                "page_key": (state.get("page_context") or {}).get("page_key"),
                **dict((state.get("business_action_provenance") or [{}])[-1]),
            },
        }
        artifact["provenance"] = dict(artifact["source"])
        artifacts.append(artifact)
    return verified, artifacts


def _relative_platform_output_path(value: object, workspace_name: str) -> str:
    """Accept the readable ``工作空间:/path`` spelling as a relative output path.

    The model is shown canonical paths so it can explain where a file lives, but
    the storage service expects a path relative to the already-authorized target
    workspace.  Strip only that workspace's own prefix; a different prefix stays
    literal and therefore cannot redirect the write to another workspace.
    """

    path = str(value or "").strip().replace("\\", "/")
    prefix = f"{workspace_name}:/" if workspace_name else ""
    if prefix and path.casefold().startswith(prefix.casefold()):
        path = path[len(prefix) :].lstrip("/")
    return path


def _file_tool_error(
    code: str,
    message_zh: str,
    correction_hint: str,
    *,
    retryable: bool = False,
    status: str = "error",
    **extra: object,
) -> str:
    """Return the stable, model-correctable error envelope for file tools."""

    return json.dumps(
        {
            "status": status,
            "code": code,
            "messageZh": message_zh,
            "retryable": retryable,
            "correctionHint": correction_hint,
            # Keep ``error`` during the API transition for older model adapters.
            "error": message_zh,
            **extra,
        },
        ensure_ascii=False,
    )


def _implicit_runner_input_ids(
    state: AgentState,
    *,
    requested_ids: Any,
    name: str,
    canonical_tool_name: str,
    action: str,
) -> Any:
    """Resolve implicit inputs without coupling fresh creates to task history."""

    if requested_ids is not None:
        return requested_ids
    if name == "web_tool" or (
        canonical_tool_name in STRICT_FILE_TOOL_NAMES and action == "create"
    ):
        return []
    return state.get("referenced_file_ids") or []


async def _execute_platform_file_tool(
    state: AgentState,
    name: str,
    params: dict,
    ws,
    user,
) -> str:
    """Authorize files, call Runner's immutable builtin lane, and persist outputs."""
    if state.get("exec_mode") != "craft":
        return _file_tool_error(
            "craft_mode_required",
            "请切换到 Craft 模式执行文件工具",
            "切换到 Craft 模式后重新提交",
        )
    deps = get_deps()
    db = deps["db"]
    params = dict(params)
    canonical_tool_name = name
    if name in STRICT_FILE_TOOL_NAMES | LEGACY_FILE_TOOL_NAMES:
        try:
            tool_kind, action, params, canonical_tool_name = normalize_file_tool_call(name, params)
        except FileToolValidationError as exc:
            return _file_tool_error(exc.code, exc.message_zh, exc.correction_hint)
    else:
        tool_kind = name.removesuffix("_tool")
        action = str(params.get("action") or "").strip().lower()
    if state.get("application_id") and not params.get("target_file_id"):
        # The model-facing schema omits target_workspace_id, but execution must
        # also ignore undeclared arguments from a provider.  Only the server-
        # validated TaskRunRequest target is allowed for new business outputs.
        params["target_workspace_id"] = state.get("workspace_id")
    produces_output = action not in {"inspect", "ocr", "list", "search", "fetch"}
    target_file_id = str(params.get("target_file_id") or "").strip()
    target_file = None
    if target_file_id:
        if not produces_output:
            return _file_tool_error(
                "target_file_not_allowed",
                "当前操作不允许指定目标文件",
                "移除 target_file_id，或改用文件编辑/转换工具",
            )
        if not params.get("base_version_id"):
            return _file_tool_error(
                "base_version_required",
                "修改文件时必须提供基础版本",
                "读取文件的最新版本后同时传入 fileId 和 baseVersionId",
            )
        target_file, ws, user = await _authorized_file(
            state,
            target_file_id,
            user,
            capability="update",
        )
        if target_file is None:
            return _file_tool_error(
                "target_file_unavailable",
                "目标文件不存在或当前用户无权修改",
                "重新选择有修改权限的文件",
            )
    else:
        ws, user, workspace_error = await _resolve_tool_workspace(
            state,
            params,
            user,
            capability="create" if produces_output else "read",
            parameter="target_workspace_id",
        )
        if workspace_error and not (name == "web_tool" and action in {"search", "fetch"}):
            return _file_tool_error(
                "workspace_permission_denied",
                workspace_error,
                "选择个人空间或当前用户有相应权限的工作空间",
            )
    # A create call is output-only unless the model explicitly selected
    # input_file_ids.  Reusing every historical reference from a persistent
    # Task here made a fresh business export depend on unrelated older files.
    requested_ids = _implicit_runner_input_ids(
        state,
        requested_ids=params.get("input_file_ids"),
        name=name,
        canonical_tool_name=canonical_tool_name,
        action=action,
    )
    if not isinstance(requested_ids, list):
        return _file_tool_error(
            "invalid_input_file_ids",
            "输入文件列表格式错误",
            "请传入文件 ID 数组",
        )
    if target_file is not None and target_file_id not in {str(value) for value in requested_ids}:
        requested_ids = [*requested_ids, target_file_id]
    if len(requested_ids) > 20:
        return _file_tool_error(
            "too_many_input_files",
            "一次最多处理 20 个输入文件",
            "减少本轮文件数量后重试",
        )
    runner_inputs: list[dict] = []
    runner_input_identities: list[dict] = []
    for value in requested_ids:
        file, user = await _authorized_input_file(state, value, user)
        if file is None:
            return _file_tool_error(
                "input_file_unavailable",
                f"输入文件 {value} 不存在或当前用户无权读取",
                "重新选择有读取权限的文件",
            )
        runner_inputs.append(await _runner_input(file))
        input_workspace = await workspace_service.get_workspace(db, file.workspace_id)
        if input_workspace is not None:
            runner_input_identities.append(await _workspace_file_identity(db, file, input_workspace, user))
    runner_params = {
        key: value
        for key, value in params.items()
        if key
        not in {
            "input_file_ids",
            "target_workspace_id",
            "target_file_id",
            "base_version_id",
            "idempotency_key",
            "output_path",
            "_mutation_key",
            "_tool_call_id",
        }
    }
    try:
        result, latency = await tool_executor_client.execute_builtin(
            tool_kind=tool_kind,
            action=action,
            params=runner_params,
            inputs=runner_inputs,
            execution_id=f"{state.get('task_id') or 'playground'}-{uuid4().hex[:8]}",
        )
        for identity in runner_input_identities:
            _remember_tool_file(state, identity, operation="read", tool_name=name)
        output_items: list[dict] = []
        task_source = await _task_source_fields(db, state)
        outputs = list(result.get("outputs") or [])
        if target_file is not None and len(outputs) != 1:
            return _file_tool_error(
                "ambiguous_target_file_output",
                "修改已有文件时必须且只能生成一个结果文件",
                "把任务拆成一次只修改一个文件",
            )
        if params.get("output_path") and len(outputs) > 1:
            return _file_tool_error(
                "ambiguous_output_path",
                "多个结果文件不能共用一个保存路径",
                "移除 output_path，或把任务拆成单文件操作",
            )
        if result.get("outputs") and ws is None:
            return _file_tool_error(
                "workspace_required",
                "生成文件前必须绑定工作空间",
                "选择个人空间或有创建权限的部门空间",
            )
        if result.get("outputs") and not produces_output:
            ws, user, workspace_error = await _resolve_tool_workspace(
                state,
                params,
                user,
                capability="create",
                parameter="target_workspace_id",
            )
            if workspace_error:
                return _file_tool_error(
                    "workspace_permission_denied",
                    workspace_error,
                    "选择个人空间或当前用户有创建权限的工作空间",
                )
        task_part = state.get("task_id") or "playground"
        for output_index, item in enumerate(outputs):
            output_mutation_key = f"{params.get('_mutation_key')}-{output_index}"
            original = PurePosixPath(str(item.get("name") or "output.bin")).name
            relative = PurePosixPath(str(item.get("relative_path") or original).replace("\\", "/"))
            safe_parts = [part for part in relative.parts if part not in {"", ".", ".."}]
            relative_path = "/".join(safe_parts) or original
            requested_path = _relative_platform_output_path(
                params.get("output_path"),
                str(getattr(ws, "name", "") or ""),
            )
            path = requested_path or (
                f"平台工具输出/{task_part}/{hashlib.sha256(output_mutation_key.encode()).hexdigest()[:12]}-{relative_path}"
            )
            mime = item.get("mime_type") or mimetypes.guess_type(original)[0] or "application/octet-stream"
            content_ref: str | None = None
            inline_content: str | None = None
            content_hash: str | None = None
            output_size: int
            actual_etag = ""
            detected_format = ""
            format_verified = False
            if item.get("content_ref"):
                (
                    content_ref,
                    output_size,
                    mime,
                    actual_etag,
                    content_hash,
                    detected_format,
                    format_verified,
                ) = await _validated_runner_output(item, mime)
                if name in STRICT_FILE_TOOL_NAMES | LEGACY_FILE_TOOL_NAMES and not format_verified:
                    raise FileToolValidationError(
                        "format_not_verified",
                        "文件格式没有通过平台验证",
                        "请重新生成或转换后再试",
                    )
            else:
                raw = base64.b64decode(item.get("content_base64") or "", validate=True)
                if not raw:
                    raise ValueError("Runner 输出文件为空")
                output_size = len(raw)
                content_hash = hashlib.sha256(raw).hexdigest()
                inline_content = base64.b64encode(raw).decode("ascii")
                if name in STRICT_FILE_TOOL_NAMES | LEGACY_FILE_TOOL_NAMES:
                    detected_format, verified_mime = validate_artifact_bytes(original, raw)
                    mime = verified_mime
                    format_verified = True
            output_meta = enrich_metadata(
                target_file.path if target_file is not None else path,
                {
                    **((target_file.metadata_ or {}) if target_file is not None else {}),
                    "binary": True,
                    "mime": mime,
                    "name": (
                        clean_display_name(target_file.path, target_file.metadata_ or {})
                        if target_file is not None
                        else (PurePosixPath(path).name if params.get("output_path") else original)
                    ),
                    "storage_backend": "oss_gateway" if content_ref else "postgres_base64",
                    **({"etag": actual_etag} if actual_etag else {}),
                    **(
                        {
                            "artifact_format_verified": True,
                            "detected_artifact_format": detected_format,
                        }
                        if format_verified
                        else {}
                    ),
                    "generated_by": "platform_file_tool",
                    "platform_tool": canonical_tool_name,
                    **({"task_id": str(state["task_id"])} if state.get("task_id") else {}),
                },
                source_kind="platform_tool",
                **task_source,
            )
            if target_file is None:
                # Runner execution may be long. Rebuild role capabilities at
                # the final write boundary, including idempotent replays.
                ws, user, workspace_error = await _resolve_tool_workspace(
                    state,
                    {"target_workspace_id": str(ws.id)},
                    user,
                    capability="create",
                    parameter="target_workspace_id",
                )
                if workspace_error:
                    return _file_tool_error(
                        "workspace_permission_revoked",
                        "文件生成期间工作空间创建权限已被收回，未保存文件",
                        "刷新权限后重新选择可写入的工作空间",
                    )
            if target_file is None and params.get("output_path"):
                existing = await workspace_service.get_file_by_path(db, ws.id, path)
                if existing is not None:
                    return _file_tool_error(
                        "output_path_conflict",
                        "保存位置已有同名文件，未覆盖现有内容",
                        "改用新文件名，或读取现有文件版本后执行版本化修改",
                        status="conflict",
                        file_id=str(existing.id),
                        current_version_id=(str(existing.current_version_id) if existing.current_version_id else None),
                    )
            if target_file is not None:
                # Re-resolve authorization immediately before the mutation;
                # Runner execution time must not bridge a role revocation.
                target_file, ws, user = await _authorized_file(
                    state,
                    target_file_id,
                    user,
                    capability="update",
                )
                if target_file is None:
                    return _file_tool_error(
                        "file_permission_revoked",
                        "文件生成期间修改权限已被收回，未覆盖目标文件",
                        "刷新权限后重新选择可修改的文件",
                    )
                try:
                    saved = await workspace_service.replace_file_artifact(
                        db,
                        target_file,
                        content=inline_content,
                        content_ref=content_ref,
                        size=output_size,
                        content_hash=content_hash,
                        metadata=output_meta,
                        parse_status="queued",
                        parse_kind=None,
                        base_version_id=UUID(str(params["base_version_id"])),
                        idempotency_key=str(params.get("_mutation_key") or params["idempotency_key"]),
                        created_by_user_id=user.id,
                    )
                except workspace_service.WorkspaceFileVersionConflict as exc:
                    return _file_tool_error(
                        "file_version_conflict",
                        "文件已经产生新版本，本次修改未覆盖最新内容",
                        "重新读取最新版本后再修改",
                        status="conflict",
                        current_version_id=exc.current_version_id,
                        latest_version_id=exc.current_version_id,
                    )
                except workspace_service.WorkspaceFileIdempotencyConflict:
                    return _file_tool_error(
                        "idempotency_conflict",
                        "重复请求的内容与首次请求不一致，已停止写入",
                        "使用新的请求标识重新提交",
                        status="conflict",
                        current_version_id=str(target_file.current_version_id),
                        latest_version_id=str(target_file.current_version_id),
                    )
                if inline_content is not None:
                    await workspace_service.reparse_file(db, saved)
                if user is not None:
                    await workspace_governance_service.audit(
                        db,
                        ws,
                        "file_updated",
                        user_id=user.id,
                        file=saved,
                        version_id=saved.current_version_id,
                        metadata={"tool": name},
                    )
            else:
                mutation, replayed = await workspace_service.begin_file_mutation(
                    db,
                    workspace=ws,
                    file=None,
                    actor_type="user" if user is not None else "admin",
                    actor_id=str(getattr(user, "id", None) or "playground"),
                    operation="create",
                    idempotency_key=output_mutation_key,
                    payload={
                        "tool": name,
                        "action": action,
                        "output_index": output_index,
                        "path": path,
                        "size": output_size,
                        "content_hash": content_hash,
                        "content_ref": content_ref,
                    },
                )
                if replayed:
                    saved, replay_workspace, user = await _authorized_create_replay(
                        state,
                        mutation,
                        user,
                    )
                    if saved is None or replay_workspace is None:
                        return _file_tool_error(
                            "idempotent_result_unavailable",
                            "重复请求对应的历史文件已经不可用",
                            "使用新的请求标识重新生成文件",
                            status="conflict",
                        )
                    ws = replay_workspace
                elif content_ref:
                    try:
                        saved = await workspace_service.upsert_file(
                            db,
                            ws,
                            WorkspaceFileCreate(path=path, content="", metadata=output_meta),
                            content_ref=content_ref,
                            raw_size=output_size,
                            raw_content_hash=content_hash,
                            created_by_user_id=user.id,
                        )
                        saved.content = None
                        saved.parse_status = "queued"
                        await workspace_service.sync_current_version(db, saved)
                    except Exception:
                        await db.delete(mutation)
                        await db.flush()
                        raise
                else:
                    try:
                        raw = base64.b64decode(inline_content or "", validate=True)
                        saved = await workspace_service.ingest_uploaded_file(
                            db,
                            ws,
                            path=path,
                            filename=original,
                            content_type=mime,
                            raw=raw,
                            created_by_user_id=user.id,
                        )
                        saved.metadata_ = output_meta
                        await workspace_service.sync_current_version(db, saved)
                    except Exception:
                        await db.delete(mutation)
                        await db.flush()
                        raise
                if not replayed:
                    await workspace_service.complete_file_mutation(
                        db,
                        mutation,
                        result_file=saved,
                        result={
                            "file_id": str(saved.id),
                            "workspace_id": str(ws.id),
                            "path": saved.path,
                        },
                    )
            await db.flush()
            identity = await _workspace_file_identity(db, saved, ws, user)
            display_name = clean_display_name(saved.path, saved.metadata_ or {})
            output_items.append(
                {
                    **identity,
                    "display_name": display_name,
                    "name": display_name,
                    "parse_status": saved.parse_status,
                    "tool_call_id": params.get("_tool_call_id"),
                }
            )
        return json.dumps(
            {
                "status": "success",
                "tool": canonical_tool_name,
                "action": action,
                "summary": result.get("summary"),
                "outputs": output_items,
                "latency_ms": latency,
            },
            ensure_ascii=False,
        )
    except workspace_service.WorkspaceFileUnsupportedTextUpdate:
        return _file_tool_error(
            "incompatible_target_format",
            "输出格式与目标文件不兼容",
            "另建文件或使用与目标文件匹配的编辑工具",
        )
    except FileToolValidationError as exc:
        return _file_tool_error(exc.code, exc.message_zh, exc.correction_hint)
    except Exception as exc:  # noqa: BLE001
        # Storage/Runner exceptions can embed presigned URLs, object keys, or input
        # excerpts.  Keep the diagnostic category without copying the downstream
        # message into logs or the model-visible tool result.
        logger.warning(
            "platform_file_tool_failed",
            tool=name,
            action=action,
            error_type=type(exc).__name__,
        )
        return _file_tool_error(
            "file_executor_failed",
            "文件工具执行失败",
            "请重试；若仍失败，请检查输入文件是否损坏或格式是否受支持",
            retryable=True,
        )


async def _execute_builtin_tool(state: AgentState, name: str, params: dict) -> str:
    """执行内置工作空间文件工具，返回结果文本。"""
    deps = get_deps()
    db = deps["db"]
    if state.get("application_id"):
        # 业务助手的产物目标由 TaskRunRequest.target_workspace_id 经服务端鉴权后
        # 写入 state；模型即使越过工具 Schema 私自传入目标，也不能改写它。
        params = dict(params)
        params.pop("target_workspace_id", None)
    ws_id = state.get("workspace_id")
    user = deps.get("user")
    ws = await workspace_service.get_workspace(db, UUID(ws_id)) if ws_id else None
    no_workspace_web_action = name == "web_tool" and str(params.get("action") or "").lower() in {
        "search",
        "fetch",
    }
    if ws is None and user is None and not no_workspace_web_action:
        return "no workspace bound to this task"

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
                ws, user, workspace_error = await _resolve_tool_workspace(
                    state,
                    params,
                    user,
                    capability="create",
                    parameter="target_workspace_id",
                )
                if workspace_error:
                    return json.dumps({"status": "error", "error": workspace_error}, ensure_ascii=False)
                if ws is None or user is None:
                    return json.dumps({"status": "error", "error": "请先绑定工作空间"}, ensure_ascii=False)
                scoped = await multimodal_service.resolve_image_generation(
                    db,
                    UUID(state["org_id"]),
                    dept_id=state.get("department_id"),
                )
                if scoped is None:
                    return json.dumps({"status": "unavailable", "error": "当前组织未配置生图模型"}, ensure_ascii=False)
                prompt = str(params.get("prompt") or "").strip()
                if not prompt:
                    return json.dumps({"status": "error", "error": "prompt is required"}, ensure_ascii=False)
                if len(prompt) > 12000:
                    return json.dumps({"status": "error", "error": "prompt is too long"}, ensure_ascii=False)
                dlp = await scan_request(
                    db,
                    prompt,
                    str(state["org_id"]),
                    state.get("department_id"),
                    None,
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
                    scoped.provider,
                    scoped.model,
                    prompt=prompt,
                    size=size,
                    quality=str(params.get("quality") or "auto"),
                    endpoint_path=str(generation.get("endpoint_path") or "/images/generations"),
                    db=db,
                    org_id=UUID(state["org_id"]),
                    dept_id=state.get("department_id"),
                )
                raw, width, height = multimodal_service.normalize_generated_png(result.raw)
                requested = PurePosixPath(str(params.get("output_name") or "generated-image.png")).name
                stem = PurePosixPath(requested).stem or "generated-image"
                safe_stem = (
                    re.sub(r"[^\w\-.\u4e00-\u9fff]+", "-", stem, flags=re.UNICODE).strip("-.") or "generated-image"
                )
                filename = f"{safe_stem}.png"
                stamp = started.strftime("%Y%m%d-%H%M%S")
                task_part = state.get("task_id") or "playground"
                path = f"平台工具输出/{task_part}/{stamp}-{uuid4().hex[:8]}-{filename}"
                saved = await workspace_service.ingest_uploaded_file(
                    db,
                    ws,
                    path=path,
                    filename=filename,
                    content_type="image/png",
                    raw=raw,
                )
                task_source = await _task_source_fields(db, state)
                saved.metadata_ = enrich_metadata(
                    saved.path,
                    {
                        **(saved.metadata_ or {}),
                        "generated_by": "image_generation_tool",
                        "provider_id": result.provider_id,
                        "model": result.model_served,
                        "width": width,
                        "height": height,
                        "task_id": str(task_part),
                    },
                    source_kind="platform_tool",
                    **task_source,
                )
                await workspace_service.sync_current_version(db, saved)
                db.add(
                    AuditLog(
                        request_id=f"image-generation-{uuid4().hex}",
                        organization_id=str(state["org_id"]),
                        department_id=state.get("department_id"),
                        provider_id=result.provider_id,
                        event_type="image_generation",
                        direction="outbound",
                        model_requested=scoped.model,
                        model_served=result.model_served,
                        latency_ms=max(0, int((datetime.now(UTC) - started).total_seconds() * 1000)),
                        status_code=200,
                        metadata_={
                            "file_id": str(saved.id),
                            "sha256": saved.content_hash,
                            "mime": "image/png",
                            "width": width,
                            "height": height,
                        },
                    )
                )
                await db.flush()
                return json.dumps(
                    {
                        "status": "success",
                        "tool": name,
                        "outputs": [
                            {
                                "file_id": str(saved.id),
                                "display_name": filename,
                                "name": filename,
                                "path": saved.path,
                                "mime_type": "image/png",
                                "width": width,
                                "height": height,
                                "parse_status": saved.parse_status,
                            }
                        ],
                        "revised_prompt": result.revised_prompt,
                    },
                    ensure_ascii=False,
                )
            if name in PLATFORM_TOOL_NAMES:
                return await _execute_platform_file_tool(state, name, params, ws, user)
            if name == "workspace_list":
                user = await _fresh_user_principal(db, user)
                if user is not None:
                    readable_workspaces = await scope_service.list_workspaces_for_user(db, user)
                else:
                    selected_ws, user, workspace_error = await _resolve_tool_workspace(
                        state,
                        params,
                        user,
                        capability="read",
                        parameter="workspace_id",
                    )
                    if workspace_error:
                        return json.dumps({"status": "error", "error": workspace_error}, ensure_ascii=False)
                    readable_workspaces = [selected_ws]
                try:
                    result_limit = min(500, max(1, int(params.get("limit") or 200)))
                    result_offset = max(0, int(params.get("offset") or 0))
                except (TypeError, ValueError):
                    return json.dumps({"status": "error", "error": "limit and offset must be integers"})
                page = readable_workspaces[result_offset : result_offset + result_limit]
                items = []
                for readable in page:
                    capabilities = (
                        await workspace_permission_service.capabilities(db, readable, user)
                        if user is not None
                        else {"read": True, "create": True, "update": True, "delete": True}
                    )
                    items.append(
                        {
                            "workspace_id": str(readable.id),
                            "workspace_name": readable.name,
                            "workspace_slug": readable.slug,
                            "scope_type": readable.scope_type,
                            "scope_id": str(readable.scope_id) if readable.scope_id else None,
                            "effective_capabilities": capabilities,
                        }
                    )
                has_more = result_offset + len(page) < len(readable_workspaces)
                return json.dumps(
                    {
                        "items": items,
                        "offset": result_offset,
                        "limit": result_limit,
                        "has_more": has_more,
                        "next_offset": result_offset + len(page) if has_more else None,
                    },
                    ensure_ascii=False,
                )
            if name in {"workspace_search", "workspace_list_files"}:
                user = await _fresh_user_principal(db, user)
                requested_workspace_id = str(params.get("workspace_id") or "").strip()
                if requested_workspace_id:
                    selected_ws, user, workspace_error = await _resolve_tool_workspace(
                        state,
                        params,
                        user,
                        capability="read",
                        parameter="workspace_id",
                    )
                    if workspace_error:
                        return json.dumps({"status": "error", "error": workspace_error}, ensure_ascii=False)
                    readable_workspaces = [selected_ws]
                elif user is not None:
                    readable_workspaces = await scope_service.list_workspaces_for_user(db, user)
                else:
                    selected_ws, user, workspace_error = await _resolve_tool_workspace(
                        state,
                        params,
                        user,
                        capability="read",
                        parameter="workspace_id",
                    )
                    if workspace_error:
                        return json.dumps({"status": "error", "error": workspace_error}, ensure_ascii=False)
                    readable_workspaces = [selected_ws]
                query = str(params.get("query") or "").casefold().strip()
                try:
                    result_limit = min(500, max(1, int(params.get("limit") or 200)))
                    result_offset = max(0, int(params.get("offset") or 0))
                except (TypeError, ValueError):
                    return json.dumps({"status": "error", "error": "limit and offset must be integers"})
                workspace_by_id = {str(item.id): item for item in readable_workspaces}
                found_rows, has_more = await workspace_service.search_files(
                    db,
                    [item.id for item in readable_workspaces],
                    query=query,
                    offset=result_offset,
                    limit=result_limit,
                )
                found = [
                    await _workspace_file_identity(
                        db,
                        file,
                        workspace_by_id[str(file.workspace_id)],
                        user,
                    )
                    for file in found_rows
                ]
                return json.dumps(
                    {
                        "items": found,
                        "offset": result_offset,
                        "limit": result_limit,
                        "has_more": has_more,
                        "next_offset": result_offset + len(found) if has_more else None,
                    },
                    ensure_ascii=False,
                )
            if name == "workspace_get_file":
                file, file_ws, user = await _authorized_file(
                    state,
                    params.get("file_id"),
                    user,
                    capability="read",
                )
                if file is None:
                    return json.dumps({"status": "error", "error": "file not found"})
                version_id = _referenced_version_id(
                    state,
                    str(file.id),
                    params.get("version_id"),
                )
                if version_id is not None:
                    try:
                        file, _ = await workspace_service.file_snapshot_at_version(
                            db,
                            file,
                            version_id,
                        )
                    except workspace_service.WorkspaceFileVersionNotFound:
                        return json.dumps({"status": "error", "error": "file version not found"})
                identity = await _workspace_file_identity(db, file, file_ws, user)
                _remember_tool_file(
                    state,
                    identity,
                    operation="metadata_read",
                    tool_name=name,
                )
                return json.dumps(identity, ensure_ascii=False)
            if name == "workspace_read_file":
                file_id = str(params.get("file_id") or "").strip()
                path = str(params.get("path") or "").strip()
                f = None
                file_ws = None
                if file_id:
                    f, file_ws, user = await _authorized_file(
                        state,
                        file_id,
                        user,
                        capability="read",
                    )
                elif path:
                    file_ws, user, workspace_error = await _resolve_tool_workspace(
                        state,
                        params,
                        user,
                        capability="read",
                        parameter="workspace_id",
                    )
                    if workspace_error:
                        return json.dumps({"status": "error", "error": workspace_error}, ensure_ascii=False)
                    f = await workspace_service.get_file_by_path(db, file_ws.id, path)
                else:
                    return "file_id or path is required"
                if f is None:
                    return "file not found"
                version_id = _referenced_version_id(
                    state,
                    str(f.id),
                    params.get("version_id"),
                )
                if version_id is not None:
                    try:
                        f, _ = await workspace_service.file_snapshot_at_version(db, f, version_id)
                    except workspace_service.WorkspaceFileVersionNotFound:
                        return json.dumps({"status": "error", "error": "file version not found"})
                try:
                    offset = int(params.get("offset", 1))
                    limit = int(params.get("limit", 200))
                except (TypeError, ValueError):
                    return json.dumps(
                        {"status": "error", "error": "offset and limit must be integers"},
                        ensure_ascii=False,
                    )
                identity = await _workspace_file_identity(db, f, file_ws, user)
                _remember_tool_file(state, identity, operation="read", tool_name=name)
                return json.dumps(
                    {
                        **identity,
                        **workspace_service.paginate_file_content(f, offset=offset, limit=limit),
                    },
                    ensure_ascii=False,
                )
            if name in {"workspace_create_file", "workspace_write_file", "workspace_update_file"}:
                file_id = str(params.get("file_id") or "").strip()
                if name == "workspace_create_file" and file_id:
                    return json.dumps(
                        {
                            "status": "error",
                            "error": "workspace_create_file does not update existing files",
                        }
                    )
                if file_id:
                    f, file_ws, user = await _authorized_file(
                        state,
                        file_id,
                        user,
                        capability="update",
                    )
                    if f is None:
                        return json.dumps({"status": "error", "error": "file not found or update denied"})
                    if not params.get("base_version_id"):
                        return json.dumps(
                            {
                                "status": "error",
                                "error": "base_version_id is required",
                            }
                        )
                    try:
                        updated = await workspace_service.update_file(
                            db,
                            f,
                            WorkspaceFileUpdate(
                                content=params.get("content"),
                                base_version_id=params.get("base_version_id"),
                                idempotency_key=params.get("_mutation_key") or params.get("idempotency_key"),
                            ),
                            created_by_user_id=getattr(user, "id", None),
                        )
                    except workspace_service.WorkspaceFileVersionConflict as exc:
                        return json.dumps(
                            {
                                "status": "conflict",
                                "error": str(exc),
                                "current_version_id": exc.current_version_id,
                            },
                            ensure_ascii=False,
                        )
                    except workspace_service.WorkspaceFileIdempotencyConflict as exc:
                        return json.dumps({"status": "conflict", "error": str(exc)}, ensure_ascii=False)
                    except workspace_service.WorkspaceFileUnsupportedTextUpdate as exc:
                        return json.dumps(
                            {
                                "status": "unsupported_format",
                                "error": str(exc),
                            },
                            ensure_ascii=False,
                        )
                    if user is not None:
                        await workspace_governance_service.audit(
                            db,
                            file_ws,
                            "file_updated",
                            user_id=user.id,
                            file=updated,
                            version_id=updated.current_version_id,
                        )
                    return json.dumps(
                        {
                            "status": "success",
                            **await _workspace_file_identity(db, updated, file_ws, user),
                        },
                        ensure_ascii=False,
                    )
                file_ws, user, workspace_error = await _resolve_tool_workspace(
                    state,
                    params,
                    user,
                    capability="create",
                    parameter="target_workspace_id",
                )
                if workspace_error:
                    return json.dumps({"status": "error", "error": workspace_error}, ensure_ascii=False)
                if not str(params.get("path") or "").strip():
                    return json.dumps({"status": "error", "error": "path is required when creating a file"})
                mutation, replayed = await workspace_service.begin_file_mutation(
                    db,
                    workspace=file_ws,
                    file=None,
                    actor_type="user" if user is not None else "admin",
                    actor_id=str(getattr(user, "id", None) or "playground"),
                    operation="create",
                    idempotency_key=str(params.get("_mutation_key") or params.get("idempotency_key") or ""),
                    payload={
                        "path": str(params.get("path") or ""),
                        "content_hash": hashlib.sha256(str(params.get("content") or "").encode("utf-8")).hexdigest(),
                    },
                )
                if replayed:
                    created, replay_workspace, user = await _authorized_create_replay(
                        state,
                        mutation,
                        user,
                    )
                    if created is None or replay_workspace is None:
                        return json.dumps(
                            {
                                "status": "conflict",
                                "error": "idempotent create result is unavailable",
                            }
                        )
                    return json.dumps(
                        {
                            "status": "success",
                            "replayed": True,
                            **await _workspace_file_identity(db, created, replay_workspace, user),
                        },
                        ensure_ascii=False,
                    )
                existing = await workspace_service.get_file_by_path(
                    db,
                    file_ws.id,
                    str(params.get("path") or ""),
                )
                if existing is not None:
                    await db.delete(mutation)
                    await db.flush()
                    return json.dumps(
                        {
                            "status": "conflict",
                            "error": "path already exists; update it by file_id with base_version_id",
                            "file_id": str(existing.id),
                            "current_version_id": (
                                str(existing.current_version_id) if existing.current_version_id else None
                            ),
                        }
                    )
                # 记录产出文件来源，供对话展示和审计使用。工作空间文件拥有
                # 独立生命周期，删除任务或消息不会删除已经交付的文件。
                meta: dict = {}
                task_id = state.get("task_id")
                if task_id:
                    meta["task_id"] = task_id
                try:
                    created = await workspace_service.upsert_file(
                        db,
                        file_ws,
                        WorkspaceFileCreate(
                            path=params.get("path", ""),
                            content=params.get("content", ""),
                            metadata=meta,
                        ),
                        created_by_user_id=getattr(user, "id", None),
                    )
                except Exception:
                    # A same-path race or format rejection must not strand a
                    # pending durable claim that makes every retry look busy.
                    await db.delete(mutation)
                    await db.flush()
                    raise
                await workspace_service.complete_file_mutation(
                    db,
                    mutation,
                    result_file=created,
                    result={
                        "file_id": str(created.id),
                        "workspace_id": str(file_ws.id),
                        "path": created.path,
                    },
                )
                if user is not None:
                    await workspace_governance_service.audit(
                        db,
                        file_ws,
                        "file_written",
                        user_id=user.id,
                        file=created,
                        version_id=created.current_version_id,
                    )
                return json.dumps(
                    {
                        "status": "success",
                        **await _workspace_file_identity(db, created, file_ws, user),
                    },
                    ensure_ascii=False,
                )
            if name in {"workspace_rename_file", "workspace_move_file"}:
                f, file_ws, user = await _authorized_file(
                    state,
                    params.get("file_id"),
                    user,
                    capability="update",
                )
                if f is None:
                    return json.dumps({"status": "error", "error": "file not found or update denied"})
                target_ws = file_ws
                requested_target_workspace_id = str(params.get("target_workspace_id") or "").strip()
                if (
                    name == "workspace_move_file"
                    and requested_target_workspace_id
                    and requested_target_workspace_id != str(file_ws.id)
                ):
                    if user is not None and not (
                        await workspace_permission_service.capabilities(db, file_ws, user)
                    ).get("delete", False):
                        return json.dumps(
                            {
                                "status": "error",
                                "error": "跨工作空间移动还需要源工作空间删除权限；可改用复制保留源文件",
                            },
                            ensure_ascii=False,
                        )
                    target_ws, user, workspace_error = await _resolve_tool_workspace(
                        state,
                        params,
                        user,
                        capability="create",
                        parameter="target_workspace_id",
                    )
                    if workspace_error:
                        return json.dumps(
                            {"status": "error", "error": workspace_error},
                            ensure_ascii=False,
                        )
                target_path = str(params.get("target_path") or "").strip()
                rename_to = None
                if name == "workspace_rename_file":
                    new_name = PurePosixPath(str(params.get("new_name") or "")).name
                    rename_to = new_name or None
                try:
                    moved = await workspace_service.move_file(
                        db,
                        f,
                        target_path,
                        base_version_id=UUID(str(params.get("base_version_id") or "")),
                        idempotency_key=str(params.get("_mutation_key") or params.get("idempotency_key") or ""),
                        target_workspace=target_ws,
                        rename_to=rename_to,
                        created_by_user_id=getattr(user, "id", None),
                    )
                except workspace_service.WorkspaceFileVersionConflict as exc:
                    return json.dumps(
                        {
                            "status": "conflict",
                            "error": str(exc),
                            "current_version_id": exc.current_version_id,
                        },
                        ensure_ascii=False,
                    )
                except workspace_service.WorkspaceFileIdempotencyConflict as exc:
                    return json.dumps({"status": "conflict", "error": str(exc)}, ensure_ascii=False)
                except workspace_service.WorkspaceFilePathConflict as exc:
                    return json.dumps(
                        {
                            "status": "conflict",
                            "code": "workspace_file_path_conflict",
                            "error": str(exc),
                            "file_id": exc.file_id,
                            "current_version_id": exc.current_version_id,
                        },
                        ensure_ascii=False,
                    )
                except ValueError as exc:
                    return json.dumps(
                        {
                            "status": "conflict",
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    )
                if user is not None:
                    await workspace_governance_service.audit(
                        db,
                        target_ws,
                        "file_moved",
                        user_id=user.id,
                        file=moved,
                        version_id=moved.current_version_id,
                        metadata={
                            "source_workspace_id": str(file_ws.id),
                            "target_workspace_id": str(target_ws.id),
                        },
                    )
                return json.dumps(
                    {
                        "status": "success",
                        **await _workspace_file_identity(db, moved, target_ws, user),
                    },
                    ensure_ascii=False,
                )
            if name == "workspace_copy_file":
                source, _source_ws, user = await _authorized_file(
                    state,
                    params.get("file_id"),
                    user,
                    capability="read",
                )
                if source is None:
                    return json.dumps({"status": "error", "error": "file not found"})
                target_ws, user, workspace_error = await _resolve_tool_workspace(
                    state,
                    params,
                    user,
                    capability="create",
                    parameter="target_workspace_id",
                )
                if workspace_error:
                    return json.dumps({"status": "error", "error": workspace_error}, ensure_ascii=False)
                target_path = str(params.get("target_path") or source.path)
                try:
                    copied = await workspace_service.copy_file(
                        db,
                        source,
                        target_ws,
                        target_path,
                        base_version_id=UUID(str(params.get("base_version_id") or "")),
                        idempotency_key=str(params.get("_mutation_key") or params.get("idempotency_key") or ""),
                        actor_type="user" if user is not None else "admin",
                        actor_id=str(getattr(user, "id", None) or "playground"),
                        created_by_user_id=getattr(user, "id", None),
                    )
                except workspace_service.WorkspaceFileVersionConflict as exc:
                    return json.dumps(
                        {
                            "status": "conflict",
                            "error": str(exc),
                            "current_version_id": exc.current_version_id,
                        },
                        ensure_ascii=False,
                    )
                except workspace_service.WorkspaceFileIdempotencyConflict as exc:
                    return json.dumps({"status": "conflict", "error": str(exc)}, ensure_ascii=False)
                live_result_workspace_id = getattr(
                    copied,
                    "mutation_result_live_workspace_id",
                    None,
                )
                if live_result_workspace_id is not None:
                    live_result_workspace = await workspace_service.get_workspace(
                        db,
                        live_result_workspace_id,
                    )
                    user = await _fresh_user_principal(db, user)
                    if live_result_workspace is None or (
                        user is not None
                        and not (
                            await workspace_permission_service.capabilities(
                                db,
                                live_result_workspace,
                                user,
                            )
                        ).get("read")
                    ):
                        return json.dumps(
                            {
                                "status": "error",
                                "error": "copy result is no longer accessible",
                            }
                        )
                if user is not None:
                    await workspace_governance_service.audit(
                        db,
                        target_ws,
                        "file_copied",
                        user_id=user.id,
                        file=copied,
                        version_id=copied.current_version_id,
                        metadata={"source_file_id": str(source.id)},
                    )
                return json.dumps(
                    {
                        "status": "success",
                        **await _workspace_file_identity(db, copied, target_ws, user),
                    },
                    ensure_ascii=False,
                )
            if name == "workspace_delete_file":
                if params.get("file_id"):
                    try:
                        f = await workspace_service.get_file_including_deleted(
                            db,
                            UUID(str(params.get("file_id"))),
                        )
                    except (TypeError, ValueError):
                        f = None
                    file_ws = await workspace_service.get_workspace(db, f.workspace_id) if f is not None else None
                    user = await _fresh_user_principal(db, user)
                    if f is not None and file_ws is not None:
                        if user is None:
                            if str(file_ws.id) != str(state.get("workspace_id") or ""):
                                f = None
                        elif not (
                            await workspace_permission_service.capabilities(
                                db,
                                file_ws,
                                user,
                            )
                        ).get("delete", False):
                            f = None
                else:
                    file_ws, user, workspace_error = await _resolve_tool_workspace(
                        state,
                        params,
                        user,
                        capability="delete",
                        parameter="workspace_id",
                    )
                    if workspace_error:
                        return json.dumps({"status": "error", "error": workspace_error}, ensure_ascii=False)
                    f = await workspace_service.get_file_by_path(db, file_ws.id, params.get("path", ""))
                if f is None:
                    return "file not found"
                deleted_identity = await _workspace_file_identity(db, f, file_ws, user)
                try:
                    await workspace_service.soft_delete_file(
                        db,
                        f,
                        user_id=getattr(user, "id", None),
                        base_version_id=UUID(str(params.get("base_version_id") or "")),
                        idempotency_key=str(params.get("_mutation_key") or params.get("idempotency_key") or ""),
                        mutation_actor_type="user" if user is not None else "system",
                        mutation_actor_id=str(getattr(user, "id", None) or "playground"),
                    )
                except workspace_service.WorkspaceFileVersionConflict as exc:
                    return json.dumps(
                        {
                            "status": "conflict",
                            "error": str(exc),
                            "current_version_id": exc.current_version_id,
                        },
                        ensure_ascii=False,
                    )
                except workspace_service.WorkspaceFileIdempotencyConflict as exc:
                    return json.dumps({"status": "conflict", "error": str(exc)}, ensure_ascii=False)
                if user is not None:
                    await workspace_governance_service.audit(
                        db,
                        file_ws,
                        "file_deleted",
                        user_id=user.id,
                        file=f,
                        version_id=f.current_version_id,
                    )
                return json.dumps({"status": "success", **deleted_identity}, ensure_ascii=False)
            if name == "workspace_list_versions":
                f, file_ws, user = await _authorized_file(
                    state,
                    params.get("file_id"),
                    user,
                    capability="read",
                )
                if f is None:
                    return json.dumps({"status": "error", "error": "file not found"})
                versions = await workspace_governance_service.list_versions(db, f)
                return json.dumps(
                    {
                        **await _workspace_file_identity(db, f, file_ws, user),
                        "versions": [
                            {
                                "version_id": str(version.id),
                                "version_no": int(version.version_no),
                                "size": int(version.size),
                                "content_hash": version.content_hash,
                                "created_at": version.created_at.isoformat(),
                                "internal_url": f"/f/{f.id}?version={version.id}",
                            }
                            for version in versions
                        ],
                    },
                    ensure_ascii=False,
                )
            if name == "workspace_restore_version":
                f, file_ws, user = await _authorized_file(
                    state,
                    params.get("file_id"),
                    user,
                    capability="update",
                )
                try:
                    version = await db.get(WorkspaceFileVersion, UUID(str(params.get("version_id") or "")))
                except (ValueError, TypeError):
                    version = None
                if f is None or version is None or str(version.workspace_file_id) != str(f.id):
                    return json.dumps({"status": "error", "error": "file version not found"})
                try:
                    restored = await workspace_service.restore_file_version(
                        db,
                        f,
                        version,
                        base_version_id=UUID(str(params.get("base_version_id") or "")),
                        idempotency_key=str(params.get("_mutation_key") or params.get("idempotency_key") or ""),
                        created_by_user_id=getattr(user, "id", None),
                    )
                except workspace_service.WorkspaceFileVersionConflict as exc:
                    return json.dumps(
                        {
                            "status": "conflict",
                            "error": str(exc),
                            "current_version_id": exc.current_version_id,
                        },
                        ensure_ascii=False,
                    )
                except workspace_service.WorkspaceFileIdempotencyConflict as exc:
                    return json.dumps({"status": "conflict", "error": str(exc)}, ensure_ascii=False)
                if user is not None:
                    await workspace_governance_service.audit(
                        db,
                        file_ws,
                        "version_restored",
                        user_id=user.id,
                        file=restored,
                        version_id=restored.current_version_id,
                        metadata={"restored_from": str(version.id)},
                    )
                return json.dumps(
                    {
                        "status": "success",
                        **await _workspace_file_identity(db, restored, file_ws, user),
                    },
                    ensure_ascii=False,
                )
            if name == "generate_docx":
                from app.tools.docx_builder import markdown_to_docx_bytes

                ws, user, workspace_error = await _resolve_tool_workspace(
                    state,
                    params,
                    user,
                    capability="create",
                    parameter="target_workspace_id",
                )
                if workspace_error:
                    return json.dumps({"status": "error", "error": workspace_error}, ensure_ascii=False)
                filename = (params.get("filename") or "document.docx").strip()
                if not filename.lower().endswith(".docx"):
                    filename += ".docx"
                raw = markdown_to_docx_bytes(params.get("markdown") or "")
                saved = await workspace_service.ingest_uploaded_file(
                    db,
                    ws,
                    path=filename,
                    filename=filename,
                    content_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                    raw=raw,
                    created_by_user_id=getattr(user, "id", None),
                )
                task_id = state.get("task_id")
                if task_id:
                    saved.metadata_ = {**dict(saved.metadata_ or {}), "task_id": task_id}
                    await workspace_service.sync_current_version(db, saved)
                return f"generated {filename} ({len(raw)} bytes)"
    except workspace_service.WorkspaceFileUnsupportedTextUpdate:
        return "不能用纯文本内容创建 Office、PDF 或其他二进制文件；请使用对应文件工具"
    except Exception as exc:  # noqa: BLE001
        logger.warning("builtin_tool_failed", tool=name, error_type=type(exc).__name__)
        return "文件工具执行失败，请重试或检查文件状态"
    return f"unknown builtin tool {name}"
