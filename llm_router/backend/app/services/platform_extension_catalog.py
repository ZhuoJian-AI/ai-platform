"""Truthful built-in extension catalog and baseline release manifest."""

from __future__ import annotations

CORE_PLUGINS = [
    {
        "slug": "dsh-llm-runtime",
        "name": "LLM Runtime",
        "version": "0.1.0-rc.5",
        "kind": "runtime_plugin",
        "required": True,
        "capabilities": ["llm_runtime"],
    },
    {
        "slug": "dsh-session",
        "name": "Session Store",
        "version": "0.1.0-rc.5",
        "kind": "runtime_plugin",
        "required": True,
        "capabilities": ["session"],
    },
    {
        "slug": "dsh-system-prompt",
        "name": "System Prompt",
        "version": "0.1.0-rc.5",
        "kind": "runtime_plugin",
        "required": True,
        "capabilities": ["system_prompt"],
    },
    {
        "slug": "dsh-tools",
        "name": "Tool Runtime",
        "version": "0.1.0-rc.5",
        "kind": "runtime_plugin",
        "required": True,
        "capabilities": ["tool_runtime"],
    },
    {
        "slug": "dsh-agent",
        "name": "Agent Registry",
        "version": "0.1.0-rc.5",
        "kind": "runtime_plugin",
        "required": True,
        "capabilities": ["agent_registry"],
    },
    {
        "slug": "dsh-agent-loop",
        "name": "Agent Loop",
        "version": "0.1.0-rc.5",
        "kind": "runtime_plugin",
        "required": True,
        "capabilities": ["coordinator"],
        "config": {"maxParallelToolCalls": 1},
    },
    {
        "slug": "dsh-invariants",
        "name": "Invariant Registry",
        "version": "0.1.0-rc.5",
        "kind": "runtime_plugin",
        "required": False,
        "enabled": False,
        "capabilities": ["invariants"],
    },
    {
        "slug": "dsh-timeout",
        "name": "DSH Timeout",
        "version": "0.1.0-rc.5",
        "kind": "library",
        "required": False,
        "enabled": True,
        "capabilities": ["timeout_library"],
    },
    {
        "slug": "dsh-user-approval",
        "name": "User Approval",
        "version": "0.1.0-rc.5",
        "kind": "adapter_required",
        "required": False,
        "enabled": False,
        "capabilities": ["approval"],
        "warnings": ["平台审批事件与应答通道尚未适配，禁止发布"],
    },
]

SYSTEM_TOOL_GROUPS = [
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
            "spreadsheet_tool",
            "document_tool",
            "presentation_tool",
            "pdf_tool",
            "text_tool",
        ],
    },
    {
        "slug": "media",
        "name": "图片与生图",
        "description": "图片处理、OCR 与模型生图",
        "tools": ["image_tool", "image_generation_tool"],
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
    {
        "slug": "rag",
        "name": "RAG 检索",
        "description": "按智能体绑定集合检索企业知识",
        "tools": ["rag_search"],
    },
    {
        "slug": "agent-skills",
        "name": "用户 Skill 桥接",
        "description": "读取并运行当前智能体绑定的用户 Skill",
        "tools": ["load_skill", "read_skill_resource", "run_skill_script"],
    },
    {
        "slug": "enterprise-connectors",
        "name": "企业连接器",
        "description": "按组织权限动态注册 ERP/MES/CRM 数据接口",
        "tools": [],
    },
]


def baseline_manifest() -> dict:
    return {
        "schema_version": 1,
        "platform_version": "0.1.0",
        "node_version": "22.19.0",
        "dsh_version": "0.1.0-rc.5",
        "plugins": [{**item} for item in CORE_PLUGINS],
        "system_tools": [{**item, "kind": "system_tool", "enabled": True} for item in SYSTEM_TOOL_GROUPS],
        "external_extensions": [],
    }


def catalog_items() -> list[dict]:
    rows = []
    for item in CORE_PLUGINS:
        rows.append(
            {
                "slug": item["slug"],
                "name": item["name"],
                "version": item["version"],
                "description": "平台基线 DSH 能力",
                "kind": item["kind"],
                "source": "core",
                "status": "enabled" if item.get("enabled", True) else "available",
                "removable": not item.get("required", False),
                "capabilities": item.get("capabilities", []),
                "compatibility_warnings": item.get("warnings", []),
            }
        )
    for item in SYSTEM_TOOL_GROUPS:
        rows.append(
            {
                "slug": item["slug"],
                "name": item["name"],
                "version": "platform",
                "description": item["description"],
                "kind": "system_tool",
                "source": "core",
                "status": "enabled",
                "removable": False,
                "capabilities": item["tools"],
                "compatibility_warnings": [],
            }
        )
    return rows
