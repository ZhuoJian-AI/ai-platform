"""Truthful built-in extension catalog and baseline release manifest."""

from __future__ import annotations

CORE_PLUGINS = [
    {
        "slug": "dsh-llm-runtime",
        "name": "LLM Runtime",
        "version": "0.1.0-rc.8",
        "kind": "runtime_plugin",
        "required": True,
        "capabilities": ["llm_runtime"],
    },
    {
        "slug": "dsh-session",
        "name": "Session Store",
        "version": "0.1.0-rc.8",
        "kind": "runtime_plugin",
        "required": True,
        "capabilities": ["session"],
    },
    {
        "slug": "dsh-system-prompt",
        "name": "System Prompt",
        "version": "0.1.0-rc.8",
        "kind": "runtime_plugin",
        "required": True,
        "capabilities": ["system_prompt"],
    },
    {
        "slug": "dsh-tools",
        "name": "Tool Runtime",
        "version": "0.1.0-rc.8",
        "kind": "runtime_plugin",
        "required": True,
        "capabilities": ["tool_runtime"],
    },
    {
        "slug": "dsh-agent",
        "name": "Agent Registry",
        "version": "0.1.0-rc.8",
        "kind": "runtime_plugin",
        "required": True,
        "capabilities": ["agent_registry"],
    },
    {
        "slug": "dsh-agent-loop",
        "name": "Agent Loop",
        "version": "0.1.0-rc.8",
        "kind": "runtime_plugin",
        "required": True,
        "capabilities": ["coordinator"],
        "config": {"maxParallelToolCalls": 1},
    },
    {
        "slug": "dsh-invariants",
        "name": "Invariant Registry",
        "version": "0.1.0-rc.8",
        "kind": "runtime_plugin",
        "required": False,
        "enabled": False,
        "capabilities": ["invariants"],
    },
    {
        "slug": "dsh-timeout",
        "name": "DSH Timeout",
        "version": "0.1.0-rc.8",
        "kind": "library",
        "required": False,
        "enabled": True,
        "capabilities": ["timeout_library"],
        # Used by the runtime tool pipeline: each ToolSpec carries ``timeout_ms`` from the
        # platform (read tools 60s, scripts / enterprise actions / web 300s, default 120s) and
        # the runtime enforces that deadline, emitting ``policy:tool_timeout`` when it fires.
        "description": "工具调用截止时间：按平台下发的 ToolSpec.timeout_ms 中断超时工具并上报 tool_timeout 策略事件",
    },
    {
        "slug": "dsh-user-approval",
        "name": "User Approval",
        "version": "0.1.0-rc.8",
        "kind": "adapter_required",
        "required": False,
        "enabled": True,
        "capabilities": ["approval"],
        # The platform adapter is in place: tools tagged ``ToolSpec.approval="ask"`` pause inside the
        # runtime, the bridge relays ``approval_request`` / ``approval_decided`` over the run's SSE
        # channel, and the terminal user answers via POST /terminal/tasks/{task_id}/approvals/{id}.
        "description": (
            "高风险工具审批：运行时按 ToolSpec.approval 暂停调用，平台经运行 SSE 通道把审批请求转给终端用户，"
            "由用户放行或拒绝后才继续执行"
        ),
    },
    # rc.8 providers: vendored in ``dsh_runtime/vendor`` but not yet loaded by
    # ``runtime.ts::buildContext``.  Listed disabled so the catalog stays truthful.
    {
        "slug": "dsh-session-persistence-jsonl",
        "name": "Session Persistence (JSONL)",
        "version": "0.1.0-rc.8",
        "kind": "runtime_plugin",
        "required": False,
        "enabled": False,
        "capabilities": ["session_persistence"],
        "description": "JSONL 会话持久化 provider（路线图 C1）：已随 rc.8 打包进运行时，尚未接线，PostgreSQL 仍是事实源",
    },
    {
        "slug": "dsh-code-runtime-worker-thread",
        "name": "Code Runtime (Worker Thread)",
        "version": "0.1.0-rc.8",
        "kind": "runtime_plugin",
        "required": False,
        "enabled": False,
        "capabilities": ["code_runtime"],
        "description": "worker-thread 代码运行时 provider（路线图 C2 Code Mode）：已随 rc.8 打包进运行时，尚未接线",
    },
    {
        "slug": "dsh-repeat-tool-reminder",
        "name": "Repeat Tool Reminder",
        "version": "0.1.0-rc.8",
        "kind": "runtime_plugin",
        "required": False,
        "enabled": False,
        "capabilities": ["hook_guard"],
        "description": "上游重复调用提醒插件（仅注入提示，不拦截）；平台当前由 policies.ts 的重复失败拦截覆盖，保留未启用",
    },
    {
        "slug": "dsh-tool-call-timeout-policy",
        "name": "Tool Call Timeout Policy",
        "version": "0.1.0-rc.8",
        "kind": "runtime_plugin",
        "required": False,
        "enabled": False,
        "capabilities": ["hook_guard"],
        "description": "上游工具超时插件；平台已在 registerTool 用 dsh-timeout 直接实现同等硬超时，保留未启用",
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
        "dsh_version": "0.1.0-rc.8",
        # ``description`` is catalog-only display text; the runtime release manifest keeps its shape.
        "plugins": [{key: value for key, value in item.items() if key != "description"} for item in CORE_PLUGINS],
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
                "description": item.get("description") or "平台基线 DSH 能力",
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
