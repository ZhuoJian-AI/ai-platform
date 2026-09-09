"""Idempotent metadata backfill for managed workspace outputs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.models.workspace import WorkspaceFile
from app.utils.workspace_presentation import MANAGED_OUTPUT_ROOTS, enrich_metadata, infer_source


async def backfill_workspace_presentations(
    db: AsyncSession,
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    rows = list((await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.deleted_at.is_(None),
    ))).scalars().all())
    managed = [row for row in rows if row.path.split("/", 1)[0] in MANAGED_OUTPUT_ROOTS]
    task_ids: set[UUID] = set()
    for row in managed:
        _, task_id = infer_source(row.path, row.metadata_ or {})
        try:
            if task_id:
                task_ids.add(UUID(task_id))
        except ValueError:
            pass
    tasks = {
        str(task.id): task
        for task in (await db.execute(select(Task).where(Task.id.in_(task_ids)))).scalars().all()
    } if task_ids else {}
    updated = unchanged = 0
    for row in managed:
        current = dict(row.metadata_ or {})
        source_kind, task_id = infer_source(row.path, current)
        task = tasks.get(str(task_id)) if task_id else None
        source: dict[str, object] = {
            "source_kind": source_kind,
            "source_task_id": task_id,
            "source_task_title": task.title if task else None,
            "source_created_at": row.created_at.isoformat(),
        }
        enriched = enrich_metadata(row.path, current, **source)
        if enriched == current:
            unchanged += 1
            continue
        updated += 1
        if not dry_run:
            row.metadata_ = enriched
    if not dry_run:
        await db.flush()
    return {
        "scanned": len(rows),
        "managed": len(managed),
        "updated": updated,
        "unchanged": unchanged,
        "ambiguous": 0,
    }
