"""Single-concurrency, crash-recoverable LibreOffice fallback preview worker."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from sqlalchemy import or_, select, text

from app.config import settings
from app.database import async_session_factory, engine
from app.models.workspace import WorkspaceFileVersion, WorkspacePreviewJob
from app.services import storage_gateway_service

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
CONVERSION_TIMEOUT_SECONDS = 10 * 60
MAX_OUTPUT_BYTES = 500 * 1024 * 1024
WORKER_ADVISORY_LOCK_ID = 9_318_411


async def claim_one() -> str | None:
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        async with db.begin():
            row = (await db.execute(
                select(WorkspacePreviewJob)
                .where(
                    WorkspacePreviewJob.attempt_count < 3,
                    WorkspacePreviewJob.next_attempt_at <= now,
                    or_(
                        WorkspacePreviewJob.status == "queued",
                        (WorkspacePreviewJob.status == "processing")
                        & (WorkspacePreviewJob.lease_expires_at < now),
                    ),
                )
                .order_by(WorkspacePreviewJob.next_attempt_at, WorkspacePreviewJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )).scalar_one_or_none()
            if row is None:
                return None
            row.status = "processing"
            row.attempt_count = int(row.attempt_count or 0) + 1
            row.locked_by = WORKER_ID
            row.lease_expires_at = now + timedelta(
                seconds=settings.workspace_preview_job_lease_seconds
            )
            row.error = None
            return str(row.id)


async def _convert_to_pdf(source: Path, output_dir: Path) -> Path:
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise RuntimeError("LibreOffice unavailable")
    profile = output_dir / "lo-profile"
    profile.mkdir()
    process = await asyncio.create_subprocess_exec(
        executable,
        "--headless",
        f"-env:UserInstallation={profile.as_uri()}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(source),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=CONVERSION_TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError("LibreOffice timeout")
    if process.returncode:
        raise RuntimeError("LibreOffice conversion failed")
    output = output_dir / f"{source.stem}.pdf"
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("LibreOffice produced no PDF")
    return output


async def process_one(job_id: str) -> None:
    async with async_session_factory() as db:
        job = await db.get(WorkspacePreviewJob, job_id)
        if job is None or job.status != "processing" or job.locked_by != WORKER_ID:
            return
        try:
            version = await db.get(WorkspaceFileVersion, job.file_version_id)
            if version is None:
                raise RuntimeError("Source version missing")
            if not storage_gateway_service.is_object_ref(version.content_ref):
                raise RuntimeError("Legacy source is not in object storage")
            metadata = dict(version.metadata_ or {})
            filename = str(metadata.get("name") or "document")
            suffix = PurePosixPath(filename).suffix.lower()
            if not suffix or suffix == ".pdf":
                raise RuntimeError("Source format does not require Office conversion")
            with tempfile.TemporaryDirectory(prefix="workspace-preview-") as temp_dir:
                directory = Path(temp_dir)
                source = directory / f"source{suffix}"
                await storage_gateway_service.download_to_path(
                    str(version.content_ref),
                    source,
                    max_bytes=settings.workspace_weboffice_max_bytes,
                )
                output = await _convert_to_pdf(source, directory)
                output_ref = await storage_gateway_service.upload_path(
                    output,
                    filename=f"workspace-previews/{job.file_version_id}.pdf",
                    content_type="application/pdf",
                    max_bytes=MAX_OUTPUT_BYTES,
                )
            if job.output_ref and job.output_ref != output_ref:
                try:
                    await storage_gateway_service.delete_object(job.output_ref)
                except storage_gateway_service.StorageGatewayError:
                    pass
            job.output_ref = output_ref
            job.status = "ready"
            job.error = None
        except Exception as exc:
            if int(job.attempt_count or 0) >= 3:
                job.status = "failed"
                job.error = f"备用预览转换失败：{type(exc).__name__}"[:500]
            else:
                job.status = "queued"
                job.next_attempt_at = datetime.now(UTC) + timedelta(
                    seconds=30 * (2 ** max(int(job.attempt_count or 1) - 1, 0))
                )
                job.error = None
        finally:
            job.lease_expires_at = None
            job.locked_by = None
            await db.commit()


async def main() -> None:
    while True:
        # A database advisory lock keeps conversion globally single-concurrency,
        # even if the deployment is accidentally started with multiple replicas.
        async with engine.connect() as lock_connection:
            acquired = bool((await lock_connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": WORKER_ADVISORY_LOCK_ID},
            )).scalar_one())
            if acquired:
                try:
                    job_id = await claim_one()
                    if job_id:
                        await process_one(job_id)
                        continue
                finally:
                    await lock_connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": WORKER_ADVISORY_LOCK_ID},
                    )
        await asyncio.sleep(settings.workspace_preview_job_poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())
