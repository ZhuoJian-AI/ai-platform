"""Standalone hourly storage lifecycle worker.

This worker is intentionally independent from document parsing. A quiet or
backlogged parser must never delay retention deadlines or upload-session GC.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import structlog

from app.config import settings
from app.database import async_session_factory
from app.services import storage_lifecycle_service

logger = structlog.get_logger()


async def run_once(*, reconcile_orphans: bool = False) -> dict[str, int]:
    async with async_session_factory() as db:
        try:
            result = await storage_lifecycle_service.run_cleanup(db)
            if reconcile_orphans:
                result.update(await storage_lifecycle_service.reconcile_orphan_objects(db))
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    logger.info("storage_lifecycle_completed", **result)
    return result


async def main() -> None:
    last_orphan_scan: date | None = None
    while True:
        try:
            today = datetime.now(UTC).date()
            scan_orphans = today != last_orphan_scan
            result = await run_once(reconcile_orphans=scan_orphans)
            if scan_orphans and result.get("orphan_scan_supported") is not None:
                last_orphan_scan = today
        except Exception as exc:  # keep retrying; tombstones remain authoritative
            logger.exception("storage_lifecycle_failed", error=str(exc))
        await asyncio.sleep(max(60, settings.storage_lifecycle_interval_seconds))


if __name__ == "__main__":
    asyncio.run(main())
