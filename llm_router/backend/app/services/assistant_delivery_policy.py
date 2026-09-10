"""Shared conservative file-delivery guard, not an intent-routing gate.

This only prevents success without delivery after an explicit creation request.
It does not choose tools, reject natural-language requests, or prove that an
artifact meets the user's content and format requirements.
"""

import re

_OUTPUT_MIME_TYPES = {
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
_OUTPUT_FORMAT_ALIASES = {"excel": "xlsx", "word": "docx", "ppt": "pptx"}
_EXPLICIT_OUTPUT = re.compile(
    r"(?:生成|创建|制作|导出(?:为)?|输出(?:为)?|另存为|保存为|转换为|转成|转为|"
    r"\b(?:generate|create|produce|export|save as|convert to)\b)"
    r"(?:\s|一份|一个|一段|可下载的|真正的|a\s|an\s)*(?<![a-z0-9])"
    r"(mp3|wav|xlsx|docx|pptx|pdf|csv|txt|markdown|excel|word|ppt)(?![a-z0-9])",
    re.IGNORECASE,
)


def explicit_output_formats(request: str) -> set[str]:
    """Extract literal output declarations only; never choose or deny tools.

    This is a completion backstop, not general semantic intent resolution.
    Input filenames and unspecified/contextual formats are not inferred here.
    """
    formats = {match.group(1).lower() for match in _EXPLICIT_OUTPUT.finditer(str(request or ""))}
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
    text = str(request or "").casefold()
    return (
        bool(text)
        and any(verb in text for verb in FILE_PRODUCTION_VERBS)
        and any(noun in text for noun in FILE_ARTIFACT_NOUNS)
    )
