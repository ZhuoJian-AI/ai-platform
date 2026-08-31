"""Fast, faithful workspace PDF page previews.

The original PDF stays in OSS.  A short-lived local copy is fetched over the
same-region private endpoint, then each requested page is returned as its
original embedded JPEG when possible or as a PNG raster fallback.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
from pathlib import Path
from uuid import uuid4

import pdfplumber
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory
from app.models.workspace import WorkspaceFile
from app.services import skill_runner_client, storage_gateway_service

_CACHE_ROOT = Path("/tmp/zhuojian-pdf-preview")
_locks: dict[str, asyncio.Lock] = {}
logger = structlog.get_logger()

_OFFICE_TOOL_KIND = {
    "doc": "document", "docx": "document", "docm": "document", "dot": "document",
    "dotx": "document", "dotm": "document", "rtf": "document", "odt": "document",
    "xls": "spreadsheet", "xlsx": "spreadsheet", "xlsm": "spreadsheet", "xlsb": "spreadsheet",
    "xlt": "spreadsheet", "xltx": "spreadsheet", "xltm": "spreadsheet", "ods": "spreadsheet",
    "csv": "spreadsheet", "tsv": "spreadsheet",
    "ppt": "presentation", "pptx": "presentation", "pptm": "presentation", "pps": "presentation",
    "ppsx": "presentation", "ppsm": "presentation", "pot": "presentation", "potx": "presentation",
    "potm": "presentation", "odp": "presentation",
}


class WorkspacePdfPreviewError(RuntimeError):
    """The source is not a readable PDF page preview."""


def _source_revision(file: WorkspaceFile) -> str:
    revision = f"{file.id}:{file.current_version_id or ''}:{file.content_hash or ''}:{file.content_ref or ''}"
    return hashlib.sha256(revision.encode("utf-8")).hexdigest()[:32]


def _extension(file: WorkspaceFile) -> str:
    metadata = file.metadata_ or {}
    filename = str(metadata.get("name") or file.path.rsplit("/", 1)[-1])
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


async def _office_preview_ref(db: AsyncSession, file: WorkspaceFile) -> str:
    """Create one durable PDF rendition per immutable Office source revision."""
    extension = _extension(file)
    tool_kind = _OFFICE_TOOL_KIND.get(extension)
    if tool_kind is None:
        raise WorkspacePdfPreviewError("This file type does not support paged preview")
    if not storage_gateway_service.is_object_ref(file.content_ref):
        raise WorkspacePdfPreviewError("Office page preview requires object storage")

    revision = _source_revision(file)
    metadata = dict(file.metadata_ or {})
    cached = metadata.get("office_preview_pdf")
    if (
        isinstance(cached, dict)
        and cached.get("source_revision") == revision
        and storage_gateway_service.is_object_ref(str(cached.get("content_ref") or ""))
    ):
        return str(cached["content_ref"])

    lock = _locks.setdefault(f"office:{revision}", asyncio.Lock())
    async with lock:
        await db.refresh(file)
        metadata = dict(file.metadata_ or {})
        cached = metadata.get("office_preview_pdf")
        if (
            isinstance(cached, dict)
            and cached.get("source_revision") == revision
            and storage_gateway_service.is_object_ref(str(cached.get("content_ref") or ""))
        ):
            return str(cached["content_ref"])

        signed = await storage_gateway_service.get_signed_download(str(file.content_ref))
        source_name = str(metadata.get("name") or file.path.rsplit("/", 1)[-1])
        try:
            result, _ = await skill_runner_client.execute_builtin(
                tool_kind=tool_kind,
                action="convert",
                params={"target_format": "pdf", "output_name": f"{Path(source_name).stem}.pdf"},
                inputs=[{
                    "file_id": str(file.id),
                    "name": source_name,
                    "download_url": str(signed["url"]),
                    "download_headers": {
                        str(key): str(value) for key, value in (signed.get("headers") or {}).items()
                    },
                    "expected_size": int(file.size),
                }],
                execution_id=f"workspace-preview-{file.id}-{uuid4().hex[:8]}",
                timeout_seconds=600,
            )
            output = next(iter(result.get("outputs") or []), None)
            if not isinstance(output, dict):
                raise ValueError("conversion returned no PDF")
            raw = base64.b64decode(str(output.get("content_base64") or ""), validate=True)
            if not raw.startswith(b"%PDF-"):
                raise ValueError("conversion output is not a PDF")
        except Exception as exc:
            raise WorkspacePdfPreviewError("Office preview is still being generated; please retry shortly") from exc

        content_ref = await storage_gateway_service.upload_bytes(
            raw,
            filename=f"workspace-previews/{file.id}/{revision}.pdf",
            content_type="application/pdf",
        )
        metadata["office_preview_pdf"] = {
            "source_revision": revision,
            "content_ref": content_ref,
            "size": len(raw),
        }
        file.metadata_ = metadata
        await db.commit()
        return content_ref


async def _preview_pdf_ref(db: AsyncSession, file: WorkspaceFile) -> str:
    if _extension(file) == "pdf":
        if not storage_gateway_service.is_object_ref(file.content_ref):
            raise WorkspacePdfPreviewError("PDF page preview requires object storage")
        return str(file.content_ref)
    return await _office_preview_ref(db, file)


async def _cached_pdf(file: WorkspaceFile, content_ref: str) -> Path:
    if not storage_gateway_service.is_object_ref(content_ref):
        raise WorkspacePdfPreviewError("PDF page preview requires object storage")
    key = hashlib.sha256(content_ref.encode("utf-8")).hexdigest()[:32]
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
            content_ref, temporary, max_bytes=settings.workspace_max_file_bytes,
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


async def warm_office_preview(file_id: str) -> None:
    """Best-effort post-upload warmup so the user's first open is a cache hit."""
    async with async_session_factory() as db:
        file = await db.get(WorkspaceFile, file_id)
        if file is None or file.deleted_at is not None or _extension(file) not in _OFFICE_TOOL_KIND:
            return
        try:
            await get_pdf_info(db, file)
        except Exception as exc:  # preview stays retryable from the read endpoint
            await db.rollback()
            logger.warning(
                "workspace_office_preview_warmup_failed",
                file_id=str(file_id),
                error_type=type(exc).__name__,
            )
