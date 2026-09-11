"""Shared conservative file-delivery guard, not an intent-routing gate.

This only prevents success without delivery after an explicit creation request.
It does not choose tools, reject natural-language requests, or prove that an
artifact meets the user's content and format requirements.
"""

import re


def _positive_delivery_clauses(request: str) -> list[str]:
    """Ignore explicit negative clauses in this literal completion backstop.

    This is not semantic intent classification: ambiguous wording remains for
    the main LLM. Keep contrast clauses independent so a denied format does not
    cancel a positively requested one.
    """
    # Past-tense attributive phrases identify an input, not a new deliverable.
    # Keep surrounding verbs: "修改刚才生成的文件" still requires an output.
    request = re.sub(
        r"(?:刚才|之前|此前|上次|已经|已)(?:为我|帮我)?"
        r"(?:生成|创建|制作|导出|转换|保存|输出|新建)(?:好|过)?的",
        "已有的", str(request or ""),
    )
    clauses = re.split(r"[，,。!！?？;；\n]|\.(?![a-zA-Z0-9])|但是|但|而是|\bbut\b", request, flags=re.I)
    return [
        clause for clause in clauses
        if not re.search(
            r"(?:不要|无需|不需要|不用|禁止|不|(?<!分)别)\s*(?:再|帮我|为我)?\s*"
            r"(?:生成|创建|制作|导出|转换|保存|输出|新建|编辑|修改|下载)"
            r"|\b(?:do not|don't|never|no need to)\s+(?:create|generate|export|save|make|convert)\b",
            clause, re.I,
        )
    ]

_OUTPUT_MIME_TYPES = {
    "png": {"image/png"},
    "jpeg": {"image/jpeg"},
    "webp": {"image/webp"},
    "svg": {"image/svg+xml"},
    "mp3": {"audio/mpeg", "audio/mp3"},
    "wav": {"audio/wav", "audio/x-wav", "audio/wave"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    "pdf": {"application/pdf"},
    "csv": {"text/csv"},
    "txt": {"text/plain"},
    "markdown": {"text/markdown", "text/x-markdown"},
}
_OUTPUT_FORMAT_ALIASES = {"excel": "xlsx", "word": "docx", "ppt": "pptx", "jpg": "jpeg", "md": "markdown"}
_EXPLICIT_OUTPUT = re.compile(
    r"(?:生成|创建|制作|导出(?:为)?|输出(?:为)?|另存为|保存为|转换为|转成|转为|"
    r"\b(?:generate|create|produce|export|save as|convert to)\b)"
    r"(?:\s|一份|一个|一段|可下载的|真正的|a\s|an\s)*(?<![a-z0-9])"
    r"(mp3|wav|xlsx|docx|pptx|pdf|csv|txt|markdown|md|excel|word|ppt|png|jpe?g|webp|svg)(?![a-z0-9])",
    re.IGNORECASE,
)
_NAMED_OUTPUT = re.compile(
    r"(?:保存为|另存为|输出为|命名为|文件名(?:为)?|\bsave as\b|\bnamed\b)"
    r"\s*[`\"“']?[^\s/\\，,。;；\n`\"”']+\."
    r"(mp3|wav|xlsx|docx|pptx|pdf|csv|txt|markdown|md|png|jpe?g|webp|svg)"
    r"(?![a-z0-9])", re.IGNORECASE,
)


def explicit_output_formats(request: str) -> set[str]:
    """Extract literal output declarations only; never choose or deny tools.

    This is a completion backstop, not general semantic intent resolution.
    Input filenames and unspecified/contextual formats are not inferred here.
    """
    formats = {
        match.group(1).lower()
        for clause in _positive_delivery_clauses(request)
        for pattern in (_EXPLICIT_OUTPUT, _NAMED_OUTPUT)
        for match in pattern.finditer(clause)
    }
    return {_OUTPUT_FORMAT_ALIASES.get(name, name) for name in formats}


def missing_output_formats(formats: set[str], artifacts: list[dict]) -> set[str]:
    delivered_types = {
        str(item.get("mimeType") or item.get("mime_type") or "").split(";", 1)[0].strip().lower()
        for item in artifacts
        if isinstance(item, dict)
        and (item.get("fileId") or item.get("file_id"))
        and (item.get("versionId") or item.get("version_id"))
    }
    return {
        name for name in formats
        if not (_OUTPUT_MIME_TYPES.get(name, set()) & delivered_types)
    }

FILE_PRODUCTION_VERBS = (
    "生成", "创建", "制作", "导出", "转换", "转成", "转为", "保存", "另存",
    "输出", "做一份", "做成", "写一份", "整理成", "汇总成", "编辑", "修改",
    "新建", "产出", "交付", "下载", "generate", "create", "make", "produce",
    "export", "convert", "save", "write", "build", "deliver",
)

FILE_ARTIFACT_NOUNS = (
    "文件", "表格", "excel", "xlsx", "xls", "csv", "word", "docx", "文档",
    "ppt", "pptx", "幻灯片", "演示文稿", "pdf", "报告", "报表", "压缩包",
    "zip", "附件", "产物", "交付物", "spreadsheet", "sheet", "document",
    "report", "slide", "deck", "presentation", "archive", "deliverable", "file",
    "markdown", "txt", "图片", "图像", "image", "音频", "语音", "配音",
    "mp3", "wav", "audio",
)


def requests_file_delivery(request: str) -> bool:
    """Require both production wording and a file/media noun, not attachments alone."""
    return any(
        any(verb in clause.casefold() for verb in FILE_PRODUCTION_VERBS)
        and any(noun in clause.casefold() for noun in FILE_ARTIFACT_NOUNS)
        for clause in _positive_delivery_clauses(request)
    )
