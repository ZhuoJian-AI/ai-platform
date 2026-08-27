"""Task service — CRUD for terminal user task threads."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.task import Task, TaskMessage
from app.models.workspace import WorkspaceFile
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.storage_lifecycle_service import mark_deleted
from app.services.workspace_service import get_file_by_path as workspace_service_get_file_by_path

# 写文件类内置工具：arguments 中 path/filename 为产出文件路径。
# 删除一整轮对话时据此识别本轮产出的工作空间文件，避免残留孤立产物。
FILE_WRITE_TOOLS = {"workspace_write_file", "generate_docx"}

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
    """软删除该任务在工作空间中产出的文件（``metadata.task_id`` 标记）；返回清理条数。"""
    ws_id = (task.config or {}).get("workspace_id")
    if not ws_id:
        return 0
    stmt = (
        select(WorkspaceFile)
        .where(
            WorkspaceFile.workspace_id == ws_id,
            WorkspaceFile.metadata_["task_id"].as_string() == str(task.id),
            WorkspaceFile.deleted_at.is_(None),
        )
    )
    files = list((await db.execute(stmt)).scalars().all())
    now = datetime.now(UTC)
    for f in files:
        mark_deleted(f, now=now)
    if files:
        await db.flush()
    return len(files)


async def list_messages(db: AsyncSession, task_id: UUID) -> list[TaskMessage]:
    stmt = (
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .order_by(TaskMessage.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


def _extract_turn_file_paths(assistant_msg: TaskMessage) -> list[str]:
    """从 assistant 消息 metadata.traces 中提取本轮产出的工作空间文件路径。

    仅取 ``category='skill'`` 且 ``name`` 属于写文件类工具的 trace，且 ``result.ok !== false``。
    ``workspace_write_file`` 取 ``arguments.path``，``generate_docx`` 取 ``arguments.filename``。
    """
    meta = assistant_msg.metadata_ or {}
    traces = meta.get("traces") or []
    if not isinstance(traces, list):
        return []
    paths: list[str] = []
    for t in traces:
        if not isinstance(t, dict):
            continue
        if t.get("category") != "skill":
            continue
        name = t.get("name") or ""
        if name not in FILE_WRITE_TOOLS:
            continue
        result = t.get("result")
        if isinstance(result, dict) and result.get("ok") is False:
            continue
        raw_args = t.get("arguments") or ""
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except Exception:
                continue
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            continue
        path = ("filename" if name == "generate_docx" else "path")
        val = args.get(path) if isinstance(args, dict) else None
        if isinstance(val, str) and val.strip():
            paths.append(val.strip())
    return paths


async def soft_delete_task_turn(
    db: AsyncSession, task: Task, user_message_id: UUID,
) -> dict:
    """软删除一整轮对话：用户消息 + 紧随其后的 assistant 消息，以及仅本轮产出的工作空间文件。

    文件清理复用 ``metadata.task_id`` 之外的另一条线索——从 assistant 消息 ``metadata.traces``
    里提取 ``workspace_write_file`` / ``generate_docx`` 写入的路径，按 (workspace_id, path) 软删除。
    若同一路径在后续轮次中又被写入，则视为后续轮次所有，不在本轮删除（避免误删别轮产物）。

    返回 ``{deleted_messages, deleted_files}`` 供接口日志展示。
    """
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
    stmt_asst = (
        select(TaskMessage)
        .where(
            TaskMessage.task_id == task.id,
            TaskMessage.role == "assistant",
            TaskMessage.created_at >= user_msg.created_at,
        )
        .order_by(TaskMessage.created_at.asc())
        .limit(1)
    )
    assistant_msg = (await db.execute(stmt_asst)).scalar_one_or_none()

    # 2) 收集本轮产出文件路径；若有 assistant 消息则剔除后续轮次重复写入的路径
    turn_paths: list[str] = []
    if assistant_msg is not None:
        turn_paths = _extract_turn_file_paths(assistant_msg)
    if turn_paths:
        later_stmt = (
            select(TaskMessage)
            .where(
                TaskMessage.task_id == task.id,
                TaskMessage.role == "assistant",
                TaskMessage.created_at > assistant_msg.created_at,
            )
            .order_by(TaskMessage.created_at.asc())
        )
        later_msgs = list((await db.execute(later_stmt)).scalars().all())
        later_paths: set[str] = set()
        for m in later_msgs:
            later_paths.update(_extract_turn_file_paths(m))
        turn_paths = [p for p in turn_paths if p not in later_paths]

    # 3) 软删除工作空间文件（若任务绑定了工作空间）
    ws_id = (task.config or {}).get("workspace_id")
    deleted_files = 0
    if ws_id and turn_paths:
        # 同一 (workspace_id, path) 可能因多次写入存在历史软删除记录——只清理当前可见的一条。
        ws_uuid = UUID(ws_id) if isinstance(ws_id, str) else ws_id
        for path in turn_paths:
            f = await workspace_service_get_file_by_path(db, ws_uuid, path)
            if f is None:
                continue
            mark_deleted(f)
            deleted_files += 1
        if deleted_files:
            await db.flush()

    # 4) 删除消息（硬删除——TaskMessage 无 SoftDeleteMixin，对话历史不留软删除残留）
    to_delete = [user_msg]
    if assistant_msg is not None:
        to_delete.append(assistant_msg)
    for m in to_delete:
        await db.delete(m)
    await db.flush()
    return {"deleted_messages": len(to_delete), "deleted_files": deleted_files}
