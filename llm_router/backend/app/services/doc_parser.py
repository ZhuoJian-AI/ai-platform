"""RAG 文档上传解析器 —— 把上传的二进制文件抽取为纯文本。

按扩展名 / Content-Type 分派到对应解析库（惰性 import，避免无解析任务时强依赖）：
- txt / md / csv：编码探测后解码
- html / htm：去标签取文本
- pdf：逐页抽取文本
- docx：段落 + 表格单元格
- xlsx / xls：逐表逐行单元格

调用方（``rag_service.ingest_uploaded_file``）在请求线程内同步调用本模块完成文本
抽取，结果立即落库为 ``RagDocument.content``；分块与嵌入在后台任务中异步进行。
"""

from __future__ import annotations

import io
from urllib.parse import unquote

import structlog

logger = structlog.get_logger()

# 单文件大小上限（50MB）——防止超大文件耗尽内存 / 拖垮解析
MAX_FILE_BYTES = 50 * 1024 * 1024


class UnsupportedFileTypeError(ValueError):
    """不支持的文件类型 / 无法解析。"""


def _ext(filename: str) -> str:
    name = unquote(filename or "").strip().lower()
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1]


def _decode(raw: bytes) -> str:
    """字节流按探测编码解码，回退 utf-8（errors='replace' 不抛）。"""
    try:
        from charset_normalizer import from_bytes
        result = from_bytes(raw).best()
        if result is not None:
            return str(result)
    except Exception as exc:  # noqa: BLE001 — 探测失败回退 utf-8
        logger.debug("charset_detect_failed", error=str(exc))
    return raw.decode("utf-8", errors="replace")


def extract_text(filename: str, content_type: str | None, raw: bytes) -> tuple[str, str]:
    """抽取纯文本。返回 ``(text, kind)``，``kind`` 为解析类型标识（供 metadata）。

    无法解析时抛 :class:`UnsupportedFileTypeError`，由调用方转为 422 / 写入 parse_error。
    """
    if len(raw) > MAX_FILE_BYTES:
        raise UnsupportedFileTypeError(
            f"文件过大（{len(raw)} 字节），上限 {MAX_FILE_BYTES // (1024 * 1024)}MB"
        )
    if not raw:
        raise UnsupportedFileTypeError("文件为空")

    ext = _ext(filename)
    ct = (content_type or "").split(";")[0].strip().lower()

    kind = _resolve_kind(ext, ct)
    if kind is None:
        raise UnsupportedFileTypeError(f"不支持的文件类型：{ext or ct or '未知'}")

    try:
        if kind in ("txt", "md", "csv"):
            return _decode(raw), kind
        if kind == "html":
            return _parse_html(raw), kind
        if kind == "pdf":
            return _parse_pdf(raw), kind
        if kind == "docx":
            return _parse_docx(raw), kind
        if kind == "xlsx":
            return _parse_xlsx(raw), kind
    except UnsupportedFileTypeError:
        raise
    except Exception as exc:  # noqa: BLE001 — 统一转为带原因的解析错误
        raise UnsupportedFileTypeError(f"{kind} 解析失败：{exc}") from exc

    # 理论不可达（kind 已归一化到上述分支）
    raise UnsupportedFileTypeError(f"不支持的文件类型：{ext or ct or '未知'}")


def _resolve_kind(ext: str, ct: str) -> str | None:
    """按扩展名（优先）或 Content-Type 归一化到解析类型。"""
    table = {
        "txt": "txt", "text": "txt", "log": "txt",
        "md": "md", "markdown": "md",
        "csv": "csv", "tsv": "csv",
        "htm": "html", "html": "html",
        "pdf": "pdf",
        "docx": "docx",
        "xlsx": "xlsx", "xlsm": "xlsx",
    }
    if ext in table:
        return table[ext]
    # Content-Type 兜底
    ct_map = {
        "text/plain": "txt", "text/markdown": "md", "text/csv": "csv",
        "text/html": "html", "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    }
    return ct_map.get(ct)


def _parse_html(raw: bytes) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_decode(raw), "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _parse_pdf(raw: bytes) -> str:
    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
    return "\n\n".join(pages)


def _parse_docx(raw: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(raw))
    parts: list[str] = []
    for para in document.paragraphs:
        text = (para.text or "").strip()
        if text:
            parts.append(text)
    # 表格单元格文本
    for table in document.tables:
        for row in table.rows:
            cells = [(c.text or "").strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _parse_xlsx(raw: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    parts: list[str] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [("" if v is None else str(v)).strip() for v in row]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)
