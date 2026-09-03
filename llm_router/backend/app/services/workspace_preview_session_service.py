"""Fast preview routing and durable Office fallback conversion orchestration."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.workspace import WorkspaceFile, WorkspaceFileVersion, WorkspacePreviewJob
from app.services import storage_gateway_service
from app.services.workspace_preview_service import OriginalPreviewError, source_metadata

MIB = 1024 * 1024
LOCAL_OFFICE_MAX_BYTES = 20 * MIB
TABULAR_TEXT_LOCAL_MAX_BYTES = 5 * MIB
MODERN_WORD_SUFFIXES = {".docx", ".docm", ".dotx", ".dotm"}
LEGACY_WORD_SUFFIXES = {".doc", ".dot", ".wps", ".wpt", ".rtf", ".odt"}
PRESENTATION_SUFFIXES = {
    ".ppt",
    ".pptx",
    ".pptm",
    ".pps",
    ".ppsx",
    ".ppsm",
    ".pot",
    ".potx",
    ".potm",
    ".dpt",
    ".dps",
    ".odp",
}
SPREADSHEET_SUFFIXES = {
    ".xls",
    ".xlsx",
    ".xlsm",
    ".xlsb",
    ".xlt",
    ".xltx",
    ".xltm",
    ".ods",
    ".et",
}
TABULAR_TEXT_SUFFIXES = {".csv", ".tsv"}
TEXT_SUFFIXES = {
    ".txt",
    ".csv",
    ".tsv",
    ".md",
    ".markdown",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
    ".ini",
    ".conf",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".py",
    ".java",
    ".sql",
    ".sh",
    ".bat",
    ".ps1",
}

# Tokens must never be persisted. This short process-local cache is only an
# idempotency guard for React remounts/double clicks hitting the same backend
# replica; client-side single-flight provides the first line of defence.
_session_cache: dict[str, tuple[float, dict]] = {}
_session_locks: dict[str, asyncio.Lock] = {}
_SESSION_CACHE_SECONDS = 10 * 60
_REFRESH_CACHE_SECONDS = 2 * 60
_spreadsheet_artifact_cache: dict[str, dict] = {}


def _base(file: WorkspaceFile) -> dict:
    try:
        filename, mime_type = source_metadata(file)
    except OriginalPreviewError:
        metadata = dict(file.metadata_ or {})
        filename = str(metadata.get("name") or PurePosixPath(file.path).name)
        mime_type = str(metadata.get("mime") or "text/plain")
    return {
        "filename": filename,
        "mime_type": mime_type,
        "size": int(file.size or 0),
    }


async def _browser_source(file: WorkspaceFile, *, filename: str) -> dict:
    if not storage_gateway_service.is_object_ref(file.content_ref):
        return {"mode": "blob"}
    signed = await storage_gateway_service.get_browser_signed_download(
        str(file.content_ref),
        filename=filename,
    )
    return {"mode": "url", **signed}


async def create_preview_session(
    db: AsyncSession,
    file: WorkspaceFile,
    *,
    weboffice_user_id: str,
    client_open_id: str,
    preferred_mode: str = "default",
) -> dict:
    """Choose a route quickly; LibreOffice is never called on this request path."""
    base = _base(file)
    filename = str(base["filename"])
    suffix = PurePosixPath(filename).suffix.lower()
    size = int(base["size"])

    if size > settings.workspace_weboffice_max_bytes:
        return {**base, "mode": "download_only", "reason": "超过 200MB 在线预览上限"}

    if not storage_gateway_service.is_object_ref(file.content_ref):
        return {
            **base,
            "mode": "download_only",
            "reason": "历史文件尚未迁移到对象存储，仅支持下载",
        }

    if suffix == ".pdf":
        source = await _browser_source(file, filename=filename)
        return {
            **base,
            **source,
            "mode": "pdfjs" if source["mode"] != "blob" else "blob",
            "strict_range": size > settings.workspace_pdf_direct_preview_max_bytes,
        }

    if suffix in MODERN_WORD_SUFFIXES and size <= LOCAL_OFFICE_MAX_BYTES:
        source = await _browser_source(file, filename=filename)
        return {**base, **source, "mode": "browser_office"}

    if suffix in SPREADSHEET_SUFFIXES and size <= LOCAL_OFFICE_MAX_BYTES:
        source = await _browser_source(file, filename=filename)
        return {**base, **source, "mode": "browser_office"}

    if suffix in TABULAR_TEXT_SUFFIXES and size > TABULAR_TEXT_LOCAL_MAX_BYTES:
        await enqueue_preview_job(db, file, conversion_type="spreadsheet_rows")
        return {**base, "mode": "spreadsheet_preview", "reason": "正在生成分页表格预览"}

    if suffix in TEXT_SUFFIXES:
        source = await _browser_source(file, filename=filename)
        return {**base, **source, "mode": "text"}

    if suffix in SPREADSHEET_SUFFIXES:
        await enqueue_preview_job(db, file, conversion_type="spreadsheet_rows")
        return {**base, "mode": "spreadsheet_preview", "reason": "正在生成分页表格预览"}

    if suffix in LEGACY_WORD_SUFFIXES or suffix in MODERN_WORD_SUFFIXES:
        ready = await fallback_status(db, file, create=False)
        if ready["status"] == "ready":
            return {**base, "mode": "fallback", "reason": "已加载版本化版式缓存"}
        await enqueue_fallback(db, file)
        return {**base, "mode": "fallback", "reason": "正在生成备用预览"}

    if suffix in PRESENTATION_SUFFIXES:
        if preferred_mode == "fast_layout":
            ready = await fallback_status(db, file, create=False)
            if ready["status"] == "ready":
                return {**base, "mode": "fallback", "reason": "已选择免费快速版式预览"}
        if not settings.workspace_weboffice_enabled:
            await enqueue_fallback(db, file)
            return {**base, "mode": "fallback", "reason": "WebOffice 未启用，正在生成备用预览"}
        cache_key = ":".join(
            (
                str(file.current_version_id or file.id),
                weboffice_user_id,
                client_open_id,
                preferred_mode,
            )
        )
        now = time.monotonic()
        cached = _session_cache.get(cache_key)
        if cached and cached[0] > now:
            return dict(cached[1])
        lock = _session_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = _session_cache.get(cache_key)
            if cached and cached[0] > time.monotonic():
                return dict(cached[1])
            try:
                token = await storage_gateway_service.generate_weboffice_token(
                    str(file.content_ref),
                    filename=filename,
                    user_id=weboffice_user_id,
                )
                result = {**base, "mode": "weboffice", **token}
                _session_cache[cache_key] = (time.monotonic() + _SESSION_CACHE_SECONDS, result)
                if len(_session_cache) > 512:
                    expired = [key for key, value in _session_cache.items() if value[0] <= time.monotonic()]
                    for key in expired:
                        _session_cache.pop(key, None)
                        _session_locks.pop(key, None)
                return dict(result)
            except storage_gateway_service.StorageGatewayError:
                await enqueue_fallback(db, file)
                return {**base, "mode": "fallback", "reason": "WebOffice 不可用，正在生成备用预览"}

    if str(base["mime_type"]).startswith(("image/", "audio/", "video/")):
        source = await _browser_source(file, filename=filename)
        return {**base, **source, "mode": "native" if source["mode"] != "blob" else "blob"}

    if str(base["mime_type"]).startswith("text/"):
        source = await _browser_source(file, filename=filename)
        return {**base, **source, "mode": "text"}

    return {**base, "mode": "download_only", "reason": "该格式不支持在线预览"}


async def refresh_preview_session(
    file: WorkspaceFile,
    *,
    access_token: str,
    refresh_token: str,
    refresh_context: str,
    weboffice_user_id: str,
) -> dict:
    if not settings.workspace_weboffice_enabled:
        raise storage_gateway_service.StorageGatewayError("WebOffice is not enabled")
    if not storage_gateway_service.is_object_ref(file.content_ref):
        raise storage_gateway_service.StorageGatewayError("WebOffice requires object storage")
    fingerprint = hashlib.sha256(
        f"{file.current_version_id}:{weboffice_user_id}:{refresh_context}:{refresh_token}".encode()
    ).hexdigest()
    cache_key = f"refresh:{fingerprint}"
    cached = _session_cache.get(cache_key)
    if cached and cached[0] > time.monotonic():
        return dict(cached[1])
    lock = _session_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = _session_cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return dict(cached[1])
        result = await storage_gateway_service.refresh_weboffice_token(
            str(file.content_ref),
            access_token=access_token,
            refresh_token=refresh_token,
            refresh_context=refresh_context,
            user_id=weboffice_user_id,
        )
        _session_cache[cache_key] = (time.monotonic() + _REFRESH_CACHE_SECONDS, result)
        return dict(result)


async def enqueue_fallback(db: AsyncSession, file: WorkspaceFile) -> WorkspacePreviewJob:
    return await enqueue_preview_job(db, file, conversion_type="pdf")


async def enqueue_preview_job(
    db: AsyncSession,
    file: WorkspaceFile,
    *,
    conversion_type: str,
) -> WorkspacePreviewJob:
    if not storage_gateway_service.is_object_ref(file.content_ref):
        raise OriginalPreviewError("历史文件尚未迁移到对象存储，无法生成备用预览")
    if not file.current_version_id:
        raise OriginalPreviewError("文件版本尚未就绪")
    statement = (
        insert(WorkspacePreviewJob)
        .values(
            workspace_file_id=file.id,
            file_version_id=file.current_version_id,
            conversion_type=conversion_type,
            status="queued",
            attempt_count=0,
            next_attempt_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["file_version_id", "conversion_type"])
    )
    await db.execute(statement)
    await db.flush()
    job = (
        await db.execute(
            select(WorkspacePreviewJob).where(
                WorkspacePreviewJob.file_version_id == file.current_version_id,
                WorkspacePreviewJob.conversion_type == conversion_type,
            )
        )
    ).scalar_one()
    if job.status == "failed" and job.attempt_count < 3:
        job.status = "queued"
        job.next_attempt_at = datetime.now(UTC)
        job.error = None
        await db.flush()
    return job


async def _job_status(
    db: AsyncSession,
    file: WorkspaceFile,
    *,
    conversion_type: str,
    create: bool,
) -> tuple[WorkspacePreviewJob | None, dict]:
    if not file.current_version_id:
        raise OriginalPreviewError("文件版本尚未就绪")
    job = (
        await db.execute(
            select(WorkspacePreviewJob).where(
                WorkspacePreviewJob.file_version_id == file.current_version_id,
                WorkspacePreviewJob.conversion_type == conversion_type,
            )
        )
    ).scalar_one_or_none()
    if job is None and create:
        job = await enqueue_preview_job(db, file, conversion_type=conversion_type)
    if job is None:
        return None, {"status": "missing", "attempt_count": 0, "error": None}
    result = {
        "status": job.status,
        "attempt_count": int(job.attempt_count or 0),
        "error": job.error if job.status == "failed" else None,
    }
    return job, result


async def fallback_status(db: AsyncSession, file: WorkspaceFile, *, create: bool = False) -> dict:
    job, result = await _job_status(db, file, conversion_type="pdf", create=create)
    if job is None:
        return result
    if job.status == "ready" and storage_gateway_service.is_object_ref(job.output_ref):
        signed = await storage_gateway_service.get_browser_signed_download(
            str(job.output_ref),
            filename=f"{PurePosixPath(_base(file)['filename']).stem}-preview.pdf",
        )
        expires_in = min(15 * 60, int(signed.get("expires_in") or 15 * 60))
        result.update(
            {
                "url": signed["url"],
                "fallback_url": signed.get("fallback_url"),
                "expires_at": datetime.now(UTC) + timedelta(seconds=expires_in),
            }
        )
    return result


async def spreadsheet_status(
    db: AsyncSession,
    file: WorkspaceFile,
    *,
    create: bool = False,
) -> dict:
    job, result = await _job_status(
        db,
        file,
        conversion_type="spreadsheet_rows",
        create=create,
    )
    if job is None or job.status != "ready" or not storage_gateway_service.is_object_ref(job.output_ref):
        result["sheets"] = []
        return result
    payload = await _spreadsheet_payload(str(job.output_ref))
    result["sheets"] = [
        {
            "name": str(sheet.get("name") or "Sheet"),
            "rows": int(sheet.get("total_rows") or 0),
            "columns": int(sheet.get("columns") or 0),
            "pages": len(sheet.get("pages") or []),
            "truncated": bool(sheet.get("truncated")),
        }
        for sheet in payload.get("sheets") or []
    ]
    return result


async def spreadsheet_page(
    db: AsyncSession,
    file: WorkspaceFile,
    *,
    sheet_name: str,
    page: int,
) -> dict:
    if page < 1:
        raise OriginalPreviewError("页码必须大于 0")
    job, _ = await _job_status(db, file, conversion_type="spreadsheet_rows", create=False)
    if job is None or job.status != "ready" or not storage_gateway_service.is_object_ref(job.output_ref):
        raise OriginalPreviewError("分页表格预览尚未就绪")
    payload = await _spreadsheet_payload(str(job.output_ref))
    selected = next((item for item in payload.get("sheets") or [] if item.get("name") == sheet_name), None)
    if selected is None:
        raise OriginalPreviewError("工作表不存在")
    pages = selected.get("pages") or []
    if page > len(pages):
        raise OriginalPreviewError("页码超出范围")
    return {
        "sheet": sheet_name,
        "page": page,
        "page_size": int(payload.get("page_size") or 200),
        "total_rows": int(selected.get("total_rows") or 0),
        "truncated": bool(selected.get("truncated")),
        "rows": pages[page - 1],
    }


async def _spreadsheet_payload(output_ref: str) -> dict:
    cached = _spreadsheet_artifact_cache.get(output_ref)
    if cached is not None:
        return cached
    try:
        raw = await storage_gateway_service.download_bytes(output_ref)
        if len(raw) > 100 * MIB:
            raise ValueError("artifact too large")
        payload = json.loads(gzip.decompress(raw))
        if not isinstance(payload, dict):
            raise ValueError("invalid artifact")
    except (OSError, ValueError, TypeError, storage_gateway_service.StorageGatewayError) as exc:
        raise OriginalPreviewError("分页表格预览产物不可读") from exc
    if len(_spreadsheet_artifact_cache) >= 4:
        _spreadsheet_artifact_cache.pop(next(iter(_spreadsheet_artifact_cache)))
    _spreadsheet_artifact_cache[output_ref] = payload
    return payload


async def current_version(db: AsyncSession, file: WorkspaceFile) -> WorkspaceFileVersion:
    if not file.current_version_id:
        raise OriginalPreviewError("文件版本尚未就绪")
    version = await db.get(WorkspaceFileVersion, file.current_version_id)
    if version is None:
        raise OriginalPreviewError("文件版本不存在")
    return version
