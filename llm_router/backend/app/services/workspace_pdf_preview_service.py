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
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.workspace import WorkspaceFile
from app.services import storage_gateway_service

_CACHE_ROOT = Path("/tmp/zhuojian-pdf-preview")
_locks: dict[str, asyncio.Lock] = {}


class WorkspacePdfPreviewError(RuntimeError):
    """The source is not a readable PDF page preview."""


def _extension(file: WorkspaceFile) -> str:
    metadata = file.metadata_ or {}
    filename = str(metadata.get("name") or file.path.rsplit("/", 1)[-1])
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


async def _preview_pdf_ref(db: AsyncSession, file: WorkspaceFile) -> str:
    # Office conversion is intentionally forbidden on this synchronous GET
    # path. Durable workspace_preview_jobs own all LibreOffice work.
    if _extension(file) != "pdf":
        raise WorkspacePdfPreviewError("Office preview must use the background preview job")
    if not storage_gateway_service.is_object_ref(file.content_ref):
        raise WorkspacePdfPreviewError("PDF page preview requires object storage")
    return str(file.content_ref)


async def _cached_pdf(file: WorkspaceFile, content_ref: str) -> Path:
    if not storage_gateway_service.is_object_ref(content_ref):
        raise WorkspacePdfPreviewError("PDF page preview requires object storage")
    storage_version_id = str((file.metadata_ or {}).get("storage_version_id") or "") or None
    # One logical OSS key can contain many immutable object generations.  The
    # cache key and download must both pin VersionId or historical previews can
    # accidentally display a later edit.
    key_material = f"{content_ref}\0{storage_version_id or 'current'}"
    key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:32]
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
            content_ref,
            temporary,
            max_bytes=settings.workspace_max_file_bytes,
            version_id=storage_version_id,
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


async def get_pdf_info(db: AsyncSession, file: WorkspaceFile) -> dict[str, int | float]:
    content_ref = await _preview_pdf_ref(db, file)
    path = await _cached_pdf(file, content_ref)
    return await asyncio.to_thread(_document_info, path)


async def get_pdf_page(db: AsyncSession, file: WorkspaceFile, page_number: int) -> tuple[bytes, str]:
    content_ref = await _preview_pdf_ref(db, file)
    path = await _cached_pdf(file, content_ref)
    return await asyncio.to_thread(_render_page, path, page_number)
