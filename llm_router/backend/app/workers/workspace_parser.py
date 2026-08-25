"""Single-concurrency, crash-recoverable parser for OSS workspace files."""

from __future__ import annotations

import asyncio
import os
import socket
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select

from app.config import settings
from app.database import async_session_factory
from app.models.workspace import WorkspaceFile
from app.services import (
    doc_parser,
    storage_gateway_service,
    workspace_service,
)

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
POLL_SECONDS = 2
LEASE_MINUTES = 6
PARSE_TIMEOUT_SECONDS = 5 * 60


async def claim_one() -> str | None:
    async with async_session_factory() as db:
        async with db.begin():
            stale = datetime.now(UTC) - timedelta(minutes=LEASE_MINUTES)
            row = (await db.execute(
                select(WorkspaceFile)
                .where(
                    WorkspaceFile.deleted_at.is_(None),
                    or_(
                        WorkspaceFile.parse_status == "queued",
                        (WorkspaceFile.parse_status == "processing") & (WorkspaceFile.parse_locked_at < stale),
                    ),
                )
                .order_by(WorkspaceFile.updated_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )).scalar_one_or_none()
            if row is None:
                return None
            row.parse_status = "processing"
            row.parse_locked_at = datetime.now(UTC)
            row.parse_locked_by = WORKER_ID
            row.parse_attempts = (row.parse_attempts or 0) + 1
            await workspace_service.sync_current_version(db, row)
            return str(row.id)


async def parse_one(file_id: str) -> None:
    async with async_session_factory() as db:
        file = await db.get(WorkspaceFile, file_id)
        if file is None or file.deleted_at is not None:
            return
        meta = file.metadata_ or {}
        filename = str(meta.get("name") or file.path.rsplit("/", 1)[-1])
        content_type = str(meta.get("mime") or "application/octet-stream")
        try:
            if storage_gateway_service.is_object_ref(file.content_ref):
                with tempfile.TemporaryDirectory(prefix="workspace-parse-") as temp_dir:
                    source = Path(temp_dir) / "source.bin"
                    await asyncio.wait_for(
                        storage_gateway_service.download_to_path(
                            str(file.content_ref), source, max_bytes=settings.workspace_max_file_bytes,
                        ),
                        timeout=PARSE_TIMEOUT_SECONDS,
                    )
                    raw = await asyncio.to_thread(source.read_bytes)
            else:
                raw = await asyncio.wait_for(workspace_service.load_file_bytes(file), timeout=PARSE_TIMEOUT_SECONDS)
            text, kind = await asyncio.wait_for(
                asyncio.to_thread(doc_parser.extract_text, filename, content_type, raw),
                timeout=PARSE_TIMEOUT_SECONDS,
            )
            if not text.strip():
                raise doc_parser.UnsupportedFileTypeError("文件解析后内容为空")
            file.extracted_text = text
            file.parse_status = "ready"
            file.parse_kind = kind
            file.parse_error = None
        except doc_parser.UnsupportedFileTypeError as exc:
            file.extracted_text = None
            file.parse_status = "unsupported" if str(exc).startswith("不支持的文件类型") else "failed"
            file.parse_kind = None
            file.parse_error = str(exc)[:1000]
        except TimeoutError:
            file.parse_status = "failed"
            file.parse_error = "文件解析超过 5 分钟，已安全终止；可手动重试"
        except Exception as exc:  # worker must survive malformed documents and storage outages
            file.parse_status = "failed"
            file.parse_error = f"文件解析失败：{type(exc).__name__}"[:1000]
        finally:
            file.parse_locked_at = None
            file.parse_locked_by = None
            await workspace_service.sync_current_version(db, file)
            await db.commit()


async def main() -> None:
    while True:
        file_id = await claim_one()
        if file_id:
            await parse_one(file_id)
            continue
        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
