"""Authenticated original-file bytes for workspace previews.

The caller supplies source bytes loaded through the workspace storage layer.
Every binary is returned unchanged with its real media type. Rendering belongs
to the browser's file-type-specific viewer; this service must never silently
turn an Office file into another format and call that the original preview.
"""

from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath

from app.models.workspace import WorkspaceFile


_OFFICE_MIME_TYPES = {
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".docm": "application/vnd.ms-word.document.macroenabled.12",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".rtf": "application/rtf",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroenabled.12",
    ".xlsb": "application/vnd.ms-excel.sheet.binary.macroenabled.12",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pptm": "application/vnd.ms-powerpoint.presentation.macroenabled.12",
    ".odp": "application/vnd.oasis.opendocument.presentation",
}


class OriginalPreviewError(ValueError):
    """A source cannot be safely rendered as an original-file preview."""


def source_metadata(file: WorkspaceFile) -> tuple[str, str]:
    metadata = file.metadata_ or {}
    if not metadata.get("binary"):
        raise OriginalPreviewError("文本文件请使用 AI 解析内容视图")
    filename = str(metadata.get("name") or PurePosixPath(file.path).name)
    declared_mime = str(metadata.get("mime") or "").strip().lower()
    suffix = PurePosixPath(filename).suffix.lower()
    guessed_mime = _OFFICE_MIME_TYPES.get(suffix) or mimetypes.guess_type(filename)[0]
    # Older workspace rows often stored the generic upload MIME. Prefer the
    # extension-derived Office type so the browser receives useful metadata,
    # while the bytes themselves remain completely unchanged.
    mime = guessed_mime if declared_mime in {"", "application/octet-stream"} and guessed_mime else declared_mime
    mime = mime or "application/octet-stream"
    return filename, mime


def build_original_preview(file: WorkspaceFile, raw: bytes) -> tuple[bytes, str, str]:
    """Return unchanged source bytes, real media type, and display filename."""
    if not raw:
        raise OriginalPreviewError("原文件为空")
    filename, mime = source_metadata(file)
    return raw, mime, filename
