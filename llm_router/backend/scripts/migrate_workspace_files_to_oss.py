"""Idempotently migrate legacy workspace binary payloads from PostgreSQL to OSS.

Dry-run is the default.  Run inside the backend container after object storage
has been enabled and verified:

    python scripts/migrate_workspace_files_to_oss.py
    python scripts/migrate_workspace_files_to_oss.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import mimetypes
import sys
from pathlib import Path, PurePosixPath

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models.workspace import WorkspaceFile  # noqa: E402
from app.services import storage_gateway_service  # noqa: E402


async def migrate(*, apply: bool) -> dict[str, int]:
    if not settings.workspace_object_storage_configured:
        raise RuntimeError("Workspace object storage is not fully configured")
    stats = {"candidates": 0, "migrated": 0, "skipped": 0, "failed": 0}
    async with async_session_factory() as db:
        rows = list((await db.execute(
            select(WorkspaceFile).where(
                WorkspaceFile.deleted_at.is_(None),
                WorkspaceFile.content.is_not(None),
                WorkspaceFile.content != "",
            ).order_by(WorkspaceFile.created_at)
        )).scalars().all())
        for file in rows:
            metadata = dict(file.metadata_ or {})
            if not metadata.get("binary") or storage_gateway_service.is_object_ref(file.content_ref):
                stats["skipped"] += 1
                continue
            stats["candidates"] += 1
            if not apply:
                print(f"DRY-RUN {file.id} {file.path} {file.size} bytes")
                continue
            content_ref: str | None = None
            try:
                raw = base64.b64decode(file.content or "", validate=True)
                digest = hashlib.sha256(raw).hexdigest()
                if file.content_hash and digest != file.content_hash:
                    raise ValueError("database payload hash mismatch")
                filename = str(metadata.get("name") or PurePosixPath(file.path).name)
                mime = str(metadata.get("mime") or mimetypes.guess_type(filename)[0] or "application/octet-stream")
                content_ref = await storage_gateway_service.upload_bytes(
                    raw, filename=filename, content_type=mime,
                )
                uploaded = await storage_gateway_service.download_bytes(content_ref)
                if hashlib.sha256(uploaded).hexdigest() != digest:
                    raise ValueError("uploaded object verification failed")
                file.content_ref = content_ref
                file.content = None
                file.size = len(raw)
                file.content_hash = digest
                file.metadata_ = {**metadata, "storage_backend": "oss_gateway"}
                await db.commit()
                stats["migrated"] += 1
                print(f"MIGRATED {file.id} {file.path} {len(raw)} bytes")
            except Exception as exc:  # noqa: BLE001 - migration must continue and report each row
                await db.rollback()
                if content_ref is not None:
                    try:
                        await storage_gateway_service.delete_object(content_ref)
                    except storage_gateway_service.StorageGatewayError:
                        pass
                stats["failed"] += 1
                print(f"FAILED {file.id} {file.path}: {exc}", file=sys.stderr)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="upload, verify and clear migrated Base64 payloads")
    args = parser.parse_args()
    result = asyncio.run(migrate(apply=args.apply))
    print("SUMMARY " + " ".join(f"{key}={value}" for key, value in result.items()))
    if result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
