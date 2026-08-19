"""Authenticated original-file previews for workspace binaries.

The source bytes remain unchanged in PostgreSQL.  PDF/images are streamed as
stored; Office documents are converted to a derived PDF in a hash-addressed
cache using an isolated LibreOffice profile.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from app.config import settings
from app.models.workspace import WorkspaceFile

PREVIEW_TIMEOUT_SECONDS = 30
OFFICE_EXTENSIONS = {
    "doc", "docx", "docm", "dot", "dotx", "dotm", "rtf", "odt",
    "xls", "xlsx", "xlsm", "xlsb", "xlt", "xltx", "xltm", "ods",
    "ppt", "pptx", "pptm", "pps", "ppsx", "ppsm", "pot", "potx", "potm", "odp",
}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "avif"}


class OriginalPreviewError(ValueError):
    """A source cannot be safely rendered as an original-file preview."""


def _extension(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower().lstrip(".")


def _source_bytes(file: WorkspaceFile) -> tuple[bytes, str, str]:
    metadata = file.metadata_ or {}
    if not metadata.get("binary"):
        raise OriginalPreviewError("文本文件请使用 AI 解析内容视图")
    filename = str(metadata.get("name") or PurePosixPath(file.path).name)
    mime = str(metadata.get("mime") or mimetypes.guess_type(filename)[0] or "application/octet-stream")
    try:
        raw = base64.b64decode(file.content or "", validate=True)
    except (ValueError, TypeError) as exc:
        raise OriginalPreviewError("原文件 Base64 内容损坏") from exc
    if not raw:
        raise OriginalPreviewError("原文件为空")
    return raw, filename, mime


def _convert_office_to_pdf(raw: bytes, filename: str, content_hash: str | None) -> bytes:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if executable is None:
        raise OriginalPreviewError("服务器未安装 LibreOffice，无法生成原文件预览")
    cache_root = Path(settings.original_preview_cache_root).resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    digest = content_hash if content_hash and len(content_hash) >= 32 else hashlib.sha256(raw).hexdigest()
    cache_file = cache_root / f"{digest}.pdf"
    if cache_file.is_file() and cache_file.stat().st_size:
        return cache_file.read_bytes()

    suffix = PurePosixPath(filename).suffix or ".bin"
    with tempfile.TemporaryDirectory(prefix="workspace-preview-", dir=cache_root) as tmp:
        root = Path(tmp)
        source = root / f"source{suffix}"
        output = root / "output"
        profile = root / "profile"
        output.mkdir()
        profile.mkdir()
        source.write_bytes(raw)
        command = [
            executable, "--headless", "--safe-mode", "--nologo", "--nodefault",
            "--nofirststartwizard", "--norestore",
            f"-env:UserInstallation={profile.as_uri()}",
            "--convert-to", "pdf", "--outdir", str(output), str(source),
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, check=False, timeout=PREVIEW_TIMEOUT_SECONDS,
                env={**os.environ, "HOME": str(root), "SAL_USE_VCLPLUGIN": "svp"},
            )
        except subprocess.TimeoutExpired as exc:
            raise OriginalPreviewError("原文件预览转换超时") from exc
        converted = next(output.glob("*.pdf"), None)
        if result.returncode != 0 or converted is None or not converted.stat().st_size:
            detail = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
            raise OriginalPreviewError(f"原文件预览转换失败：{detail[:300] or '未知错误'}")
        temp_cache = cache_root / f".{digest}-{os.getpid()}.pdf"
        shutil.copyfile(converted, temp_cache)
        try:
            temp_cache.replace(cache_file)
        except OSError:
            if not cache_file.exists():
                raise
            temp_cache.unlink(missing_ok=True)
        return cache_file.read_bytes()


def build_original_preview(file: WorkspaceFile) -> tuple[bytes, str, str]:
    """Return preview bytes, media type and display filename."""
    raw, filename, mime = _source_bytes(file)
    ext = _extension(filename)
    if ext == "pdf" or mime == "application/pdf":
        return raw, "application/pdf", filename
    if ext in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return raw, mime, filename
    if ext in OFFICE_EXTENSIONS:
        return _convert_office_to_pdf(raw, filename, file.content_hash), "application/pdf", f"{filename}.pdf"
    raise OriginalPreviewError(f"暂不支持 {ext or mime} 原文件在线预览，可下载后查看")
