"""Task service — CRUD for terminal user task threads."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.task import Task, TaskFileRef, TaskMessage
from app.models.workspace import WorkspaceFile
from app.schemas.task import TaskCreate, TaskUpdate

_LEADING_COMMAND_RE = re.compile(r"^\s*/[a-zA-Z0-9][a-zA-Z0-9_-]*\s*")
_LEADING_UUID_RE = re.compile(
    r"^\s*@?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\s*"
)
_LEADING_ATTACHMENT_RE = re.compile(
    r"^\s*(?:\[(?:附件|文件)[^\]]*\]|【(?:附件|文件)[^】]*】)\s*"
)


def make_task_title(message: str, *, max_length: int = 36) -> str:
    """Build a readable task title without leaking invocation syntax into the sidebar."""
    value = message or ""
    previous = None
    while value != previous:
        previous = value
        value = _LEADING_COMMAND_RE.sub("", value, count=1)
        value = _LEADING_UUID_RE.sub("", value, count=1)
        value = _LEADING_ATTACHMENT_RE.sub("", value, count=1)
    value = re.sub(r"\s+", " ", value).strip(" -—:：,，")
    if not value:
        return "新任务"
    sentence = re.split(r"[\n。！？!?]", value, maxsplit=1)[0].strip()
    title = sentence or value
    return title if len(title) <= max_length else f"{title[:max_length - 1]}…"


async def create_task(
    db: AsyncSession, *, org_id: UUID, user_id: str, department_id: str | None,
    team_id: str | None, data: TaskCreate,
) -> Task:
    task = Task(
        organization_id=org_id,
        user_id=user_id,
        department_id=department_id,
        team_id=team_id,
        session_id=f"task-{uuid.uuid4()}",
        title=data.title.strip() if data.title.strip() else make_task_title(data.message),
        message=data.message,
        config=data.config.model_dump(mode="json"),
        status="active",
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


async def list_tasks(db: AsyncSession, user_id: str) -> list[Task]:
    stmt = (
        select(Task)
        .where(Task.user_id == user_id, Task.deleted_at.is_(None))
        .order_by(Task.updated_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


def _match_excerpt(content: str, query: str, *, radius: int = 32) -> str | None:
    normalized = re.sub(r"\s+", " ", content or "").strip()
    index = normalized.casefold().find(query.casefold())
    if index < 0:
        return None
    start = max(0, index - radius)
    end = min(len(normalized), index + len(query) + radius)
    excerpt = normalized[start:end]
    return f"{'…' if start else ''}{excerpt}{'…' if end < len(normalized) else ''}"


async def search_tasks(db: AsyncSession, user_id: str, query: str) -> list[tuple[Task, str | None]]:
    """Search titles, initial prompts and persisted messages with a useful excerpt."""
    needle = re.sub(r"\s+", " ", query or "").strip()
    if not needle:
        return [(task, None) for task in await list_tasks(db, user_id)]
    stmt = (
        select(Task)
        .options(selectinload(Task.messages))
        .where(Task.user_id == user_id, Task.deleted_at.is_(None))
        .order_by(Task.updated_at.desc())
    )
    matches: list[tuple[Task, str | None]] = []
    for task in (await db.execute(stmt)).scalars().unique().all():
        if _match_excerpt(task.title, needle) is not None:
            matches.append((task, None))
            continue
        excerpt = _match_excerpt(task.message, needle)
        if excerpt is None:
            for message in task.messages:
                excerpt = _match_excerpt(message.content, needle)
                if excerpt is not None:
                    break
        if excerpt is not None:
            matches.append((task, excerpt))
    return matches


async def get_last_used_model_alias(db: AsyncSession, user_id: str) -> str | None:
    """用户最近一次任务中显式选择的模型别名（按 updated_at 倒序取首个非空）；无则 None。

    终端「默认模型 = 最近一次使用的模型」据此实现。
    """
    stmt = (
        select(Task)
        .where(Task.user_id == user_id, Task.deleted_at.is_(None))
        .order_by(Task.updated_at.desc())
    )
    for t in (await db.execute(stmt)).scalars().all():
        m = (t.config or {}).get("model_alias")
        if m:
            return str(m)
    return None


async def get_task(db: AsyncSession, task_id: UUID) -> Task | None:
    stmt = (
        select(Task)
        .options(selectinload(Task.messages))
        .where(Task.id == task_id, Task.deleted_at.is_(None))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_persistent_file_refs(db: AsyncSession, task_id: UUID, *, limit: int = 20) -> list[dict]:
    """Recover pinned plus recently used file references from message metadata.

    References are durable context only.  Callers must resolve each current
    file identity and re-check RBAC before placing it in an agent state.
    """
    indexed = list((await db.execute(
        select(TaskFileRef)
        .where(TaskFileRef.task_id == task_id)
        .order_by(
            case((TaskFileRef.scope == "task", 0), else_=1),
            TaskFileRef.updated_at.desc(),
        )
        .limit(max(limit * 2, 40))
    )).scalars().all())
    candidates: list[dict] = [{
        "file_id": str(ref.workspace_file_id),
        "scope": ref.scope,
        "version_id": str(ref.version_id) if ref.version_id else None,
        "follow_latest": bool(ref.follow_latest),
        "workspace_name": ref.workspace_name,
        "canonical_path": ref.canonical_path,
    } for ref in indexed]

    # Compatibility backfill for tasks created before the durable index.
    rows = list((await db.execute(
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .order_by(TaskMessage.created_at.desc())
        .limit(200)
    )).scalars().all())
    for message_index, message in enumerate(rows):
        metadata = message.metadata_ or {}
        values = [
            *(metadata.get("file_refs_v1") or []),
            *(metadata.get("attachments") or []),
            *(metadata.get("artifacts") or []),
        ]
        for item in reversed(values):
            if not isinstance(item, dict):
                continue
            file_id = str(item.get("file_id") or "")
            if not file_id:
                continue
            scope = "task" if item.get("scope") == "task" else "turn"
            # Task-scoped refs remain pinned.  Turn refs, actual tool reads and
            # outputs stay in working context for the most recent 40 messages.
            if scope != "task" and message_index >= 40:
                continue
            candidates.append({
                "file_id": file_id,
                "scope": scope,
                "version_id": item.get("version_id") or item.get("current_version_id"),
                "follow_latest": bool(item.get("follow_latest", True)),
            })

    # Pinned refs take priority, then recently used refs in reverse chronology.
    ordered = [
        *[item for item in candidates if item["scope"] == "task"],
        *[item for item in candidates if item["scope"] != "task"],
    ]
    refs: list[dict] = []
    seen: set[str] = set()
    for item in ordered:
        if item["file_id"] in seen:
            continue
        seen.add(item["file_id"])
        refs.append(item)
        if len(refs) >= limit:
            break
    return refs


async def upsert_task_file_refs(
    db: AsyncSession,
    task_id: UUID,
    refs: list[dict],
) -> None:
    """Persist actually supplied/read/written file context without granting access."""
    for item in refs:
        try:
            file_id = UUID(str(item.get("file_id") or ""))
        except (TypeError, ValueError):
            continue
        file = await db.get(WorkspaceFile, file_id)
        if file is None:
            continue
        existing = (await db.execute(select(TaskFileRef).where(
            TaskFileRef.task_id == task_id,
            TaskFileRef.workspace_file_id == file_id,
        ).with_for_update())).scalar_one_or_none()
        raw_version = item.get("version_id") or item.get("current_version_id")
        try:
            version_id = UUID(str(raw_version)) if raw_version else None
        except (TypeError, ValueError):
            version_id = None
        requested_scope = "task" if item.get("scope") == "task" else "turn"
        source = str(item.get("source") or "message")[:32]
        if existing is None:
            existing = TaskFileRef(
                task_id=task_id,
                workspace_file_id=file_id,
                scope=requested_scope,
            )
            db.add(existing)
        elif existing.scope == "task":
            requested_scope = "task"
        preserve_pinned_version = bool(
            existing is not None
            and existing.scope == "task"
            and not existing.follow_latest
            and source == "tool_result"
        )
        existing.scope = requested_scope
        if not preserve_pinned_version:
            existing.version_id = version_id
            existing.follow_latest = bool(item.get("follow_latest", True))
        existing.source = source
        existing.workspace_name = str(item.get("workspace_name") or "")[:255] or None
        existing.canonical_path = str(item.get("canonical_path") or "")[:1400] or None
    await db.flush()


async def update_task(db: AsyncSession, task: Task, data: TaskUpdate) -> Task:
    values = data.model_dump(exclude_unset=True)
    if "config" in values and values["config"] is not None:
        config = values.pop("config")
        task.config = config.model_dump(mode="json") if hasattr(config, "model_dump") else config
    for field, value in values.items():
        setattr(task, field, value)
    await db.flush()
    await db.refresh(task)
    return task


async def soft_delete_task(db: AsyncSession, task: Task) -> None:
    """软删除任务，并一并清理该任务在工作空间中产出的文件。

    工作空间输出文件以 ``metadata.task_id`` 标记归属（见 graph 节点 workspace_write_file）；
    删除任务时把它们同步软删除，避免工作空间残留孤立产物。
    """
    await _soft_delete_task_files(db, task)
    task.deleted_at = datetime.now(UTC)
    await db.flush()


async def _soft_delete_task_files(db: AsyncSession, task: Task) -> int:
    """Delete only task-created stable file generations, never matching paths."""
    messages = list((await db.execute(select(TaskMessage).where(
        TaskMessage.task_id == task.id,
        TaskMessage.role == "assistant",
    ).order_by(TaskMessage.created_at))).scalars().all())
    owned: dict[UUID, UUID] = {}
    for message in messages:
        for file_id, version_id, created_new in _message_file_generations(message):
            if created_new:
                owned[file_id] = version_id
            elif file_id in owned:
                # A later task mutation keeps ownership but advances the exact
                # generation that may safely be removed with this task.
                owned[file_id] = version_id
    # Use the same row-lock, active-room and outbox path as direct/folder
    # deletion.  A task cleanup must never tombstone a file while its human
    # WebOffice editor is still saving.
    from app.services import workspace_service

    files = await workspace_service.soft_delete_file_generations(db, owned)
    return len(files)


async def list_messages(db: AsyncSession, task_id: UUID) -> list[TaskMessage]:
    stmt = (
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .order_by(TaskMessage.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


def _message_file_generations(message: TaskMessage) -> list[tuple[UUID, UUID, bool]]:
    """Read trusted stable ids/generations persisted by ``save_memory``."""
    values = (message.metadata_ or {}).get("artifacts") or []
    result: list[tuple[UUID, UUID, bool]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        try:
            file_id = UUID(str(item.get("file_id") or ""))
            version_id = UUID(str(item.get("current_version_id") or ""))
        except (TypeError, ValueError):
            continue
        result.append((file_id, version_id, item.get("created_new") is True))
    return result


async def soft_delete_task_turn(
    db: AsyncSession, task: Task, user_message_id: UUID,
) -> dict:
    """Delete a turn and only its exact task-created file generations."""
    # 1) 定位本轮 user / assistant 消息
    stmt = (
        select(TaskMessage)
        .where(
            TaskMessage.task_id == task.id,
            TaskMessage.id == user_message_id,
        )
    )
    user_msg = (await db.execute(stmt)).scalar_one_or_none()
    if user_msg is None:
        return {"deleted_messages": 0, "deleted_files": 0}
    # 本轮 assistant 消息必须落在「本条 user 消息」与「下一条 user 消息」之间。
    # 若本轮没有 assistant（运行被取消/失败），只有下界的查询会抓到下一轮的 assistant，
    # 连同它的产物文件一起误删——所以先找下一条 user 消息做上界。
    stmt_next_user = (
        select(TaskMessage)
        .where(
            TaskMessage.task_id == task.id,
            TaskMessage.role == "user",
            TaskMessage.created_at > user_msg.created_at,
        )
        .order_by(TaskMessage.created_at.asc())
        .limit(1)
    )
    next_user_msg = (await db.execute(stmt_next_user)).scalar_one_or_none()
    asst_filters = [
        TaskMessage.task_id == task.id,
        TaskMessage.role == "assistant",
        TaskMessage.created_at >= user_msg.created_at,
    ]
    if next_user_msg is not None:
        asst_filters.append(TaskMessage.created_at < next_user_msg.created_at)
    stmt_asst = (
        select(TaskMessage)
        .where(*asst_filters)
        .order_by(TaskMessage.created_at.asc())
        .limit(1)
    )
    assistant_msg = (await db.execute(stmt_asst)).scalar_one_or_none()

    # 2) Stable IDs cannot accidentally select a later upload that reused the
    # same path.  The generation check also preserves a file updated later.
    generations = _message_file_generations(assistant_msg) if assistant_msg is not None else []
    owned = {
        file_id: version_id
        for file_id, version_id, created_new in generations
        if created_new
    }
    from app.services import workspace_service

    deleted_files = len(await workspace_service.soft_delete_file_generations(db, owned))

    # 3) 删除消息（硬删除——TaskMessage 无 SoftDeleteMixin，对话历史不留软删除残留）
    to_delete = [user_msg]
    if assistant_msg is not None:
        to_delete.append(assistant_msg)
    for m in to_delete:
        await db.delete(m)
    await db.flush()
    return {"deleted_messages": len(to_delete), "deleted_files": deleted_files}
