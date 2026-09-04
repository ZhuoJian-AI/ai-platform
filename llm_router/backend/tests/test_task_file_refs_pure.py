from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import task_service


@pytest.fixture(autouse=True)
def db_engine():
    yield


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Db:
    def __init__(self, existing):
        self.existing = existing

    async def get(self, _model, file_id):
        return SimpleNamespace(id=file_id)

    async def execute(self, _statement):
        return _Result(self.existing)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_tool_access_cannot_unpin_task_scoped_historical_version():
    task_id = uuid4()
    file_id = uuid4()
    pinned_version = uuid4()
    latest_version = uuid4()
    existing = SimpleNamespace(
        task_id=task_id,
        workspace_file_id=file_id,
        scope="task",
        version_id=pinned_version,
        follow_latest=False,
        source="internal_url",
        workspace_name="技术部",
        canonical_path="技术部:/历史/尺寸表.xlsx",
    )
    await task_service.upsert_task_file_refs(
        _Db(existing),
        task_id,
        [{
            "file_id": str(file_id),
            "scope": "turn",
            "version_id": str(latest_version),
            "follow_latest": True,
            "source": "tool_result",
            "workspace_name": "技术部",
            "canonical_path": "技术部:/历史/尺寸表.xlsx",
        }],
    )
    assert existing.scope == "task"
    assert existing.version_id == pinned_version
    assert existing.follow_latest is False


@pytest.mark.asyncio
async def test_explicit_new_reference_can_change_a_pinned_task_version():
    task_id = uuid4()
    file_id = uuid4()
    pinned_version = uuid4()
    newly_selected_version = uuid4()
    existing = SimpleNamespace(
        task_id=task_id,
        workspace_file_id=file_id,
        scope="task",
        version_id=pinned_version,
        follow_latest=False,
        source="internal_url",
        workspace_name=None,
        canonical_path=None,
    )
    await task_service.upsert_task_file_refs(
        _Db(existing),
        task_id,
        [{
            "file_id": str(file_id),
            "scope": "task",
            "version_id": str(newly_selected_version),
            "follow_latest": False,
            "source": "message",
        }],
    )
    assert existing.version_id == newly_selected_version
    assert existing.follow_latest is False


def test_task_cleanup_uses_only_stable_file_generation_not_trace_path():
    file_id = uuid4()
    version_id = uuid4()
    message = SimpleNamespace(metadata_={
        "traces": [{
            "name": "workspace_write_file",
            "arguments": {"path": "共享/可能被重用.txt"},
            "ok": True,
        }],
        "artifacts": [{
            "file_id": str(file_id),
            "current_version_id": str(version_id),
            "created_new": True,
        }],
    })
    assert task_service._message_file_generations(message) == [
        (file_id, version_id, True),
    ]
    assert task_service._message_file_generations(SimpleNamespace(metadata_={
        "traces": message.metadata_["traces"],
    })) == []
