"""2026-09-03 审计修复回归：记忆编辑 scope 字段（H3）、删除对话轮次越界（H9）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.memory import _strip_scope_fields
from app.models.organization import Organization
from app.models.task import Task, TaskMessage
from app.models.user import User
from app.schemas.memory import MemoryUpdate
from app.services.task_service import soft_delete_task_turn

# ── H3：编辑个人记忆时不得把 scope_type/scope_id 置 NULL ──────────────────


def test_strip_scope_fields_does_not_mark_scope_as_set():
    data = MemoryUpdate(content="新内容", scope_type="organization", scope_id="dept-1")

    stripped = _strip_scope_fields(data)

    dumped = stripped.model_dump(exclude_unset=True)
    assert dumped == {"content": "新内容"}
    assert "scope_type" not in stripped.model_fields_set
    assert "scope_id" not in stripped.model_fields_set


def test_strip_scope_fields_ignores_explicit_none_scope():
    """前端 PATCH 常带 ``scope_type: null``——同样不能写进 NOT NULL 列。"""
    data = MemoryUpdate(category="偏好", scope_type=None, scope_id=None)

    stripped = _strip_scope_fields(data)

    assert stripped.model_dump(exclude_unset=True) == {"category": "偏好"}


def test_old_model_copy_approach_would_have_written_null():
    """记录当初的坑：model_copy(update=None) 会把 None 记进 fields_set。"""
    data = MemoryUpdate(content="x").model_copy(update={"scope_type": None, "scope_id": None})
    assert data.model_dump(exclude_unset=True)["scope_type"] is None  # 这就是 500 的来源
    assert "scope_type" not in _strip_scope_fields(data).model_dump(exclude_unset=True)


# ── H9：删除一轮对话时，assistant 消息必须落在本轮 user 与下一轮 user 之间 ──


async def _make_task(db: AsyncSession) -> Task:
    suffix = uuid4().hex[:8]
    org = Organization(name=f"审计测试组织-{suffix}", slug=f"audit-{suffix}")
    db.add(org)
    await db.flush()
    user = User(organization_id=org.id, username=f"audit-{suffix}", role="member", is_active=True)
    db.add(user)
    await db.flush()
    task = Task(
        organization_id=org.id, user_id=user.id, session_id=f"audit-{uuid4().hex}",
        title="删除轮次", message="hi", config={},
    )
    db.add(task)
    await db.flush()
    return task


async def _add_message(
    db: AsyncSession, task: Task, role: str, content: str, at: datetime,
) -> TaskMessage:
    msg = TaskMessage(task_id=task.id, role=role, content=content, metadata_={}, created_at=at)
    db.add(msg)
    await db.flush()
    return msg


@pytest.mark.asyncio
async def test_delete_turn_without_assistant_does_not_take_next_turns_reply(db_session: AsyncSession):
    task = await _make_task(db_session)
    base = datetime.now(UTC)
    user_1 = await _add_message(db_session, task, "user", "第一轮（运行被取消，没有回复）", base)
    user_2 = await _add_message(db_session, task, "user", "第二轮", base + timedelta(seconds=10))
    asst_2 = await _add_message(db_session, task, "assistant", "第二轮回复", base + timedelta(seconds=20))

    result = await soft_delete_task_turn(db_session, task, user_1.id)

    assert result == {"deleted_messages": 1, "deleted_files": 0}
    remaining = (await db_session.execute(
        select(TaskMessage.id).where(TaskMessage.task_id == task.id),
    )).scalars().all()
    assert set(remaining) == {user_2.id, asst_2.id}


@pytest.mark.asyncio
async def test_delete_turn_with_assistant_removes_only_that_pair(db_session: AsyncSession):
    task = await _make_task(db_session)
    base = datetime.now(UTC)
    user_1 = await _add_message(db_session, task, "user", "第一轮", base)
    asst_1 = await _add_message(db_session, task, "assistant", "第一轮回复", base + timedelta(seconds=5))
    user_2 = await _add_message(db_session, task, "user", "第二轮", base + timedelta(seconds=10))
    asst_2 = await _add_message(db_session, task, "assistant", "第二轮回复", base + timedelta(seconds=20))

    result = await soft_delete_task_turn(db_session, task, user_1.id)

    assert result["deleted_messages"] == 2
    remaining = (await db_session.execute(
        select(TaskMessage.id).where(TaskMessage.task_id == task.id),
    )).scalars().all()
    assert set(remaining) == {user_2.id, asst_2.id}
    assert asst_1.id not in remaining


@pytest.mark.asyncio
async def test_delete_last_turn_without_assistant_keeps_earlier_turns(db_session: AsyncSession):
    """最后一轮没有回复、也没有下一条 user：只删这条 user，不碰前面的 assistant。"""
    task = await _make_task(db_session)
    base = datetime.now(UTC)
    user_1 = await _add_message(db_session, task, "user", "第一轮", base)
    asst_1 = await _add_message(db_session, task, "assistant", "第一轮回复", base + timedelta(seconds=5))
    user_2 = await _add_message(db_session, task, "user", "第二轮（失败无回复）", base + timedelta(seconds=10))

    result = await soft_delete_task_turn(db_session, task, user_2.id)

    assert result["deleted_messages"] == 1
    remaining = (await db_session.execute(
        select(TaskMessage.id).where(TaskMessage.task_id == task.id),
    )).scalars().all()
    assert set(remaining) == {user_1.id, asst_1.id}
