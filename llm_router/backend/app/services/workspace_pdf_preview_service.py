"""Fast, faithful workspace PDF page previews.

The original PDF stays in OSS.  A short-lived local copy is fetched over the
same-region private endpoint, then each requested page is returned as its
original embedded JPEG when possible or as a PNG raster fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
from pathlib import Path

import pdfplumber

from app.config import settings
from app.models.workspace import WorkspaceFile
from app.services import storage_gateway_service

_CACHE_ROOT = Path("/tmp/zhuojian-pdf-preview")
_locks: dict[str, asyncio.Lock] = {}


class WorkspacePdfPreviewError(RuntimeError):
    """The source is not a readable PDF page preview."""


def _cache_key(file: WorkspaceFile) -> str:
    revision = f"{file.id}:{file.updated_at.isoformat()}:{file.content_ref or ''}"
    return hashlib.sha256(revision.encode("utf-8")).hexdigest()[:32]


async def _cached_pdf(file: WorkspaceFile) -> Path:
    if not storage_gateway_service.is_object_ref(file.content_ref):
        raise WorkspacePdfPreviewError("PDF page preview requires object storage")
    key = _cache_key(file)
    target = _CACHE_ROOT / f"{key}.pdf"
    if target.exists() and target.stat().st_size > 0:
        return target
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        if target.exists() and target.stat().st_size > 0:
            return target
        _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        temporary = _CACHE_ROOT / f"{key}.part"
        await storage_gateway_service.download_to_path(
            str(file.content_ref), temporary, max_bytes=settings.workspace_max_file_bytes,
        )
        temporary.replace(target)
    return target


def _document_info(path: Path) -> dict[str, int | float]:
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                raise WorkspacePdfPreviewError("PDF has no pages")
            first = pdf.pages[0]
            return {
                "page_count": len(pdf.pages),
                "width": float(first.width),
                "height": float(first.height),
            }
    except WorkspacePdfPreviewError:
        raise
    except Exception as exc:
        raise WorkspacePdfPreviewError("PDF metadata could not be read") from exc


def _original_jpeg(page: object) -> bytes | None:
    images = getattr(page, "images", [])
    if len(images) != 1:
        return None
    image = images[0]
    stream = image.get("stream")
    raw = getattr(stream, "rawdata", None)
    if not isinstance(raw, bytes) or not raw.startswith(b"\xff\xd8"):
        return None
    # Only return the embedded image directly when it covers the complete page.
    tolerance = 2.0
    if abs(float(image.get("x0", 0))) > tolerance or abs(float(image.get("top", 0))) > tolerance:
        return None
    if abs(float(image.get("x1", 0)) - float(getattr(page, "width"))) > tolerance:
        return None
    if abs(float(image.get("bottom", 0)) - float(getattr(page, "height"))) > tolerance:
        return None
    return raw


def _render_page(path: Path, page_number: int) -> tuple[bytes, str]:
    try:
        with pdfplumber.open(path) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                raise WorkspacePdfPreviewError("PDF page is out of range")
            page = pdf.pages[page_number - 1]
            original = _original_jpeg(page)
            if original is not None:
                return original, "image/jpeg"
            image = page.to_image(resolution=120, antialias=True).original
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue(), "image/png"
    except WorkspacePdfPreviewError:
        raise
    except Exception as exc:
        raise WorkspacePdfPreviewError("PDF page could not be rendered") from exc


async def get_pdf_info(file: WorkspaceFile) -> dict[str, int | float]:
    path = await _cached_pdf(file)
    return await asyncio.to_thread(_document_info, path)


async def get_pdf_page(file: WorkspaceFile, page_number: int) -> tuple[bytes, str]:
    path = await _cached_pdf(file)
    return await asyncio.to_thread(_render_page, path, page_number)
