"""Platform-owned Assistant Core tool catalog.

Tenant authorization and per-run tool assembly happen in the Assistant Core;
this module only names platform-maintained capabilities.
"""

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
]


def platform_managed_tool_names() -> set[str]:
    """Return names owned by the platform's native Assistant Core."""

    return {
        str(name)
        for group in SYSTEM_TOOL_GROUPS
        for name in (group.get("tools") or [])
    }
