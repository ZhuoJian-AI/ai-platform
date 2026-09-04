"""Crash-recoverable reconciliation of WebOffice saves to workspace versions."""

from __future__ import annotations

import asyncio
import os
import socket

import structlog

from app.config import settings
from app.database import async_session_factory, engine
from app.models.workspace import OfficeEditRoom, OfficeSaveEvent
from app.services import workspace_office_edit_service

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
logger = structlog.get_logger()


async def claim_one() -> str | None:
    async with async_session_factory() as db:
        async with db.begin():
            event = await workspace_office_edit_service.claim_save_event(db, worker_id=WORKER_ID)
            return str(event.id) if event is not None else None


async def process_one(event_id: str) -> None:
    async with async_session_factory() as db:
        async with db.begin():
            event = await db.get(OfficeSaveEvent, event_id)
            if event is None or event.status != "processing" or event.locked_by != WORKER_ID:
                return
            try:
                outcome = await workspace_office_edit_service.reconcile_save_event(db, event)
                logger.info(
                    "office_save_reconciled",
                    event_id=str(event.id),
                    file_id=str(event.workspace_file_id),
                    outcome=outcome,
                )
            except Exception as exc:
                workspace_office_edit_service.retry_save_event(event, type(exc).__name__)
                if event.status == "failed" and event.office_edit_room_id:
                    room = await db.get(OfficeEditRoom, event.office_edit_room_id)
                    if room is not None and room.final_file_version_id is None:
                        room.status = "failed"
                        room.last_error = "WebOffice 保存对账重试已耗尽"
                logger.warning(
                    "office_save_reconcile_retry",
                    event_id=str(event.id),
                    error_type=type(exc).__name__,
                    attempt=event.attempt_count,
                )


async def run_forever() -> None:
    if not settings.workspace_weboffice_edit_configured:
        # The worker is part of the common production compose topology.  Keep
        # the container healthy when the optional feature flag is disabled;
        # deployments can enable it on the next restart without maintaining a
        # second conditional compose file.
        logger.info("office_edit_reconcile_parked", reason="feature_disabled_or_unconfigured")
        while True:
            await asyncio.sleep(60)
    while True:
        event_id = await claim_one()
        if event_id is None:
            await asyncio.sleep(max(float(settings.workspace_office_reconcile_poll_seconds), 0.2))
            continue
        await process_one(event_id)


async def main() -> None:
    try:
        await run_forever()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
