"""Fast preview routing and durable Office fallback conversion orchestration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.workspace import WorkspaceFile, WorkspaceFileVersion, WorkspacePreviewJob
from app.services import storage_gateway_service
from app.services.workspace_preview_service import OriginalPreviewError, source_metadata


WEBOFFICE_SUFFIXES = {
    ".doc", ".docx", ".txt", ".dot", ".wps", ".wpt", ".dotx", ".docm", ".dotm",
    ".rtf", ".ppt", ".pptx", ".pptm", ".ppsx", ".ppsm", ".pps", ".potx",
    ".potm", ".dpt", ".dps", ".et", ".xls", ".xlt", ".xlsx", ".xlsm",
    ".xltx", ".xltm", ".csv", ".pdf",
}
OFFICE_FALLBACK_SUFFIXES = WEBOFFICE_SUFFIXES - {".pdf", ".txt", ".csv"} | {
    ".odt", ".ods", ".odp", ".xlsb",
}


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
        str(file.content_ref), filename=filename,
    )
    return {"mode": "url", **signed}


async def create_preview_session(
    db: AsyncSession, file: WorkspaceFile, *, weboffice_user_id: str,
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

    if suffix == ".pdf" and size <= settings.workspace_pdf_direct_preview_max_bytes:
        source = await _browser_source(file, filename=filename)
        return {**base, **source, "mode": "pdfjs" if source["mode"] != "blob" else "blob"}

    if suffix in WEBOFFICE_SUFFIXES and storage_gateway_service.is_object_ref(file.content_ref):
        if settings.workspace_weboffice_enabled:
            try:
                token = await storage_gateway_service.generate_weboffice_token(
                    str(file.content_ref), filename=filename, user_id=weboffice_user_id,
                )
                # Keep a signed PDF source in the same response so the browser
                # can downgrade immediately after a 15-second WebOffice stall.
                pdf_source = (
                    await _browser_source(file, filename=filename)
                    if suffix == ".pdf" else {}
                )
                return {**base, **pdf_source, "mode": "weboffice", **token}
            except storage_gateway_service.StorageGatewayError:
                if suffix == ".pdf":
                    source = await _browser_source(file, filename=filename)
                    return {
                        **base,
                        **source,
                        "mode": "pdfjs",
                        "reason": "WebOffice 暂不可用，已切换 PDF 预览",
                    }
        if suffix == ".pdf":
            source = await _browser_source(file, filename=filename)
            return {**base, **source, "mode": "pdfjs"}
        await enqueue_fallback(db, file)
        return {**base, "mode": "fallback", "reason": "正在生成备用预览"}

    if suffix in OFFICE_FALLBACK_SUFFIXES:
        await enqueue_fallback(db, file)
        return {**base, "mode": "fallback", "reason": "正在生成备用预览"}

    if str(base["mime_type"]).startswith(("image/", "audio/", "video/")):
        source = await _browser_source(file, filename=filename)
        return {**base, **source, "mode": "native" if source["mode"] != "blob" else "blob"}

    if str(base["mime_type"]).startswith("text/"):
        return {**base, "mode": "blob"}

    return {**base, "mode": "download_only", "reason": "该格式不支持在线预览"}


async def refresh_preview_session(
    file: WorkspaceFile, *, access_token: str, refresh_token: str, refresh_context: str,
    weboffice_user_id: str,
) -> dict:
    if not settings.workspace_weboffice_enabled:
        raise storage_gateway_service.StorageGatewayError("WebOffice is not enabled")
    if not storage_gateway_service.is_object_ref(file.content_ref):
        raise storage_gateway_service.StorageGatewayError("WebOffice requires object storage")
    return await storage_gateway_service.refresh_weboffice_token(
        str(file.content_ref), access_token=access_token, refresh_token=refresh_token,
        refresh_context=refresh_context, user_id=weboffice_user_id,
    )


async def enqueue_fallback(db: AsyncSession, file: WorkspaceFile) -> WorkspacePreviewJob:
    if not storage_gateway_service.is_object_ref(file.content_ref):
        raise OriginalPreviewError("历史文件尚未迁移到对象存储，无法生成备用预览")
    if not file.current_version_id:
        raise OriginalPreviewError("文件版本尚未就绪")
    statement = insert(WorkspacePreviewJob).values(
        workspace_file_id=file.id,
        file_version_id=file.current_version_id,
        conversion_type="pdf",
        status="queued",
        attempt_count=0,
        next_attempt_at=datetime.now(UTC),
    ).on_conflict_do_nothing(
        index_elements=["file_version_id", "conversion_type"]
    )
    await db.execute(statement)
    await db.flush()
    job = (await db.execute(select(WorkspacePreviewJob).where(
        WorkspacePreviewJob.file_version_id == file.current_version_id,
        WorkspacePreviewJob.conversion_type == "pdf",
    ))).scalar_one()
    if job.status == "failed" and job.attempt_count < 3:
        job.status = "queued"
        job.next_attempt_at = datetime.now(UTC)
        job.error = None
        await db.flush()
    return job


async def fallback_status(db: AsyncSession, file: WorkspaceFile) -> dict:
    job = await enqueue_fallback(db, file)
    result = {
        "status": job.status,
        "attempt_count": int(job.attempt_count or 0),
        "error": job.error if job.status == "failed" else None,
    }
    if job.status == "ready" and storage_gateway_service.is_object_ref(job.output_ref):
        signed = await storage_gateway_service.get_browser_signed_download(
            str(job.output_ref),
            filename=f"{PurePosixPath(_base(file)['filename']).stem}-preview.pdf",
        )
        expires_in = min(15 * 60, int(signed.get("expires_in") or 15 * 60))
        result.update({
            "url": signed["url"],
            "fallback_url": signed.get("fallback_url"),
            "expires_at": datetime.now(UTC) + timedelta(seconds=expires_in),
        })
    return result


async def current_version(db: AsyncSession, file: WorkspaceFile) -> WorkspaceFileVersion:
    if not file.current_version_id:
        raise OriginalPreviewError("文件版本尚未就绪")
    version = await db.get(WorkspaceFileVersion, file.current_version_id)
    if version is None:
        raise OriginalPreviewError("文件版本不存在")
    return version
