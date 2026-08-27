"""Idempotent metadata backfill for managed workspace outputs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import SkillExecution, SkillFolder, SkillVersion
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
    executions = list((await db.execute(select(SkillExecution).where(
        SkillExecution.task_id.in_(task_ids),
    ))).scalars().all()) if tasks else []

    execution_by_file: dict[str, SkillExecution] = {}
    for execution in executions:
        for file_id in execution.output_file_ids or []:
            execution_by_file[str(file_id)] = execution

    updated = unchanged = ambiguous = 0
    folder_cache: dict[str, SkillFolder | None] = {}
    version_cache: dict[str, SkillVersion | None] = {}
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
        execution = execution_by_file.get(str(row.id))
        if execution is not None:
            folder_key = str(execution.skill_folder_id)
            version_key = str(execution.skill_version_id)
            if folder_key not in folder_cache:
                folder_cache[folder_key] = await db.get(SkillFolder, execution.skill_folder_id)
            if version_key not in version_cache:
                version_cache[version_key] = await db.get(SkillVersion, execution.skill_version_id)
            folder = folder_cache[folder_key]
            version = version_cache[version_key]
            source.update({
                "source_kind": "skill",
                "skill_id": folder_key,
                "skill_display_name": folder.name if folder else None,
                "skill_version": str(version.version_no) if version else None,
            })
        elif source_kind == "skill" and not current.get("skill_id"):
            ambiguous += 1
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
        "ambiguous": ambiguous,
    }
