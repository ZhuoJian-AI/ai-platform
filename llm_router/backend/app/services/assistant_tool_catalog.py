"""Platform-owned Assistant Core tool catalog and lazy discovery helpers.

Tenant authorization and per-run tool assembly still happen in the Assistant Core.
This module provides the provider-neutral descriptors and deterministic retrieval
used *after* authorization.  Retrieval may reduce a large authorized catalog, but
it never grants a tool or decides whether a business operation should execute.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

ENTRY_TOOL_NAMES = {
    "enterprise_capability_search",
    "enterprise_navigate",
    "workspace_search",
}

ENTRY_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "enterprise_capability_search",
            "description": (
                "按用户自然语言搜索当前角色可用的企业系统、模块、页面和平台工具；"
                "返回少量候选并在本轮激活候选工具的完整参数结构。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "description": "用户要完成的业务目标或所需能力，用自然语言描述",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 12},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enterprise_navigate",
            "description": (
                "当用户明确要求前往某处，或必须让用户查看、选择或补充页面信息时，"
                "导航到能力搜索返回的已授权企业页面。查询和可后台完成的任务不需要导航。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "application_id": {"type": "string", "minLength": 1},
                    "module_key": {"type": "string", "minLength": 1},
                    "page_key": {"type": "string", "minLength": 1},
                    "business_object": {
                        "type": "object",
                        "description": "可选的业务对象定位信息，例如订单号",
                        "additionalProperties": True,
                    },
                    "reason": {"type": "string", "maxLength": 300},
                },
                "required": ["application_id", "module_key", "page_key"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
]

SYSTEM_TOOL_GROUPS = [
    {
        "slug": "enterprise-navigation",
        "name": "企业能力导航",
        "description": "搜索当前角色可用的系统、模块、页面和工具，并按需导航",
        "tools": ["enterprise_capability_search", "enterprise_navigate"],
    },
    {
        "slug": "workspace-files",
        "name": "工作空间文件",
        "description": "搜索当前用户可读空间，并按稳定文件 ID 读写和管理版本",
        "tools": [
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
        ],
    },
    {
        "slug": "office-documents",
        "name": "Office 与 PDF",
        "description": "表格、Word、PPT、PDF 和纯文本处理",
        "tools": [
            "spreadsheet_create",
            "spreadsheet_inspect",
            "spreadsheet_edit",
            "spreadsheet_convert",
            "document_create",
            "document_inspect",
            "document_edit",
            "document_convert",
            "presentation_create",
            "presentation_inspect",
            "presentation_edit",
            "presentation_convert",
            "pdf_create",
            "pdf_inspect",
            "pdf_merge",
            "pdf_split",
            "pdf_extract",
            "pdf_convert",
            "text_create",
            "text_inspect",
            "text_edit",
            "text_convert",
        ],
    },
    {
        "slug": "media",
        "name": "图片与生图",
        "description": "图片处理、OCR 与模型生图",
        "tools": ["image_tool", "image_generation_tool"],
    },
    {
        "slug": "audio",
        "name": "语音",
        "description": "语音转写、音频理解和文字转语音",
        "tools": ["audio_transcribe", "audio_understand", "speech_synthesize"],
    },
    {
        "slug": "archives",
        "name": "压缩包",
        "description": "安全查看、创建和解压归档文件",
        "tools": ["archive_tool"],
    },
    {
        "slug": "web",
        "name": "公开网页",
        "description": "搜索、抓取与下载公开网页",
        "tools": ["web_tool"],
    },
]


_GROUP_ALIASES = {
    "enterprise-navigation": "系统 模块 页面 功能 能力 导航 跳转 打开 前往 订单 款号 工厂 业务",
    "workspace-files": "工作空间 文件 文件夹 查找 搜索 读取 写入 修改 移动 复制 删除 版本 恢复",
    "office-documents": (
        "表格 excel xlsx csv word docx ppt pptx powerpoint pdf txt markdown md "
        "文档 报告 报表 导出 创建 编辑 转换 合并 拆分"
    ),
    "media": "图片 图像 识图 视觉 ocr 文字识别 生图 生成图片",
    "audio": "音频 语音 录音 asr 转写 听写 理解 tts 朗读 配音 音色 声音",
    "archives": "压缩包 zip tar 解压 打包 归档",
    "web": "网页 web 互联网 搜索 抓取 下载 公开资料",
}


def entry_tool_definitions() -> list[dict[str, Any]]:
    """Return a fresh copy of the small provider-visible discovery entry set."""

    import copy

    return copy.deepcopy(ENTRY_TOOL_DEFINITIONS)


def tool_group(name: str) -> dict[str, Any] | None:
    for group in SYSTEM_TOOL_GROUPS:
        if name in (group.get("tools") or []):
            return group
    return None


def _terms(value: str) -> set[str]:
    normalized = str(value or "").lower()
    latin = set(re.findall(r"[a-z0-9_.-]+", normalized))
    chinese_chunks = re.findall(r"[\u4e00-\u9fff]+", normalized)
    chinese: set[str] = set()
    for chunk in chinese_chunks:
        chinese.add(chunk)
        chinese.update(chunk[index : index + 2] for index in range(max(0, len(chunk) - 1)))
    return {item for item in latin | chinese if item}


def descriptor_search_text(spec: dict[str, Any]) -> str:
    name = str(spec.get("name") or "")
    group = tool_group(name) or {}
    return " ".join(
        (
            name,
            str(spec.get("description") or ""),
            str(group.get("name") or ""),
            str(group.get("description") or ""),
            _GROUP_ALIASES.get(str(group.get("slug") or ""), ""),
            " ".join(str(item) for item in (spec.get("search_terms") or [])),
        )
    ).lower()


def search_tool_specs(
    query: str,
    specs: Iterable[dict[str, Any]],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Rank an already-authorized catalog without making an execution decision."""

    query_text = str(query or "").strip().lower()
    query_terms = _terms(query_text)
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for spec in specs:
        name = str(spec.get("name") or "")
        if not name or name in ENTRY_TOOL_NAMES:
            continue
        haystack = descriptor_search_text(spec)
        score = 0
        if query_text and query_text in haystack:
            score += 30
        for term in query_terms:
            if term in name.lower():
                score += 12
            elif term in haystack:
                score += 4
        if spec.get("required_context") == "current_page":
            score += 2
        if score:
            ranked.append((score, name, spec))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[: max(1, min(int(limit or 8), 12))]]


def partition_tool_specs(
    specs: Iterable[dict[str, Any]],
    *,
    current_page_tool_names: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Expose only discovery entries and current-page Actions; keep the rest lazy."""

    materialized = list(specs)
    if not any(str(item.get("name") or "") == "enterprise_capability_search" for item in materialized):
        return materialized, []
    current_page_tool_names = current_page_tool_names or set()
    visible: list[dict[str, Any]] = []
    lazy: list[dict[str, Any]] = []
    for spec in materialized:
        name = str(spec.get("name") or "")
        if name in ENTRY_TOOL_NAMES or name in current_page_tool_names:
            visible.append(spec)
        else:
            lazy.append(spec)
    return visible, lazy


def platform_managed_tool_names() -> set[str]:
    """Return names owned by the platform's native Assistant Core."""

    return {
        str(name)
        for group in SYSTEM_TOOL_GROUPS
        for name in (group.get("tools") or [])
    }
