"""Shared conservative file-delivery guard, not an intent-routing gate.

This only prevents success without delivery after an explicit creation request.
It does not choose tools, reject natural-language requests, or prove that an
artifact meets the user's content and format requirements.
"""

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
