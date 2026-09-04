from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api import file_events


@pytest.fixture(autouse=True)
def db_engine():
    """These stream framing tests use an in-memory session double."""
    yield


class _Context:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return None


class _ConnectedRequest:
    async def is_disconnected(self):
        return False


@pytest.mark.asyncio
async def test_new_file_event_stream_emits_atomic_baseline_cursor(monkeypatch):
    class BaselineDb:
        async def scalar(self, _statement):
            return 17

    monkeypatch.setattr(file_events, "async_session_factory", lambda: _Context(BaselineDb()))
    principal = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    response = await file_events.stream_file_events(
        _ConnectedRequest(), after=0, cu=principal,
    )
    iterator = response.body_iterator
    first = await anext(iterator)
    assert first == 'retry: 1500\nid: 17\nevent: cursor\ndata: {"cursor":17}\n\n'
    await iterator.aclose()


@pytest.mark.asyncio
async def test_filtered_tail_advances_client_with_cursor_only_frame(monkeypatch):
    organization_id = uuid4()
    principal = SimpleNamespace(id=uuid4(), organization_id=organization_id)
    workspace = SimpleNamespace(id=uuid4())
    row = SimpleNamespace(
        id=11,
        organization_id=organization_id,
        workspace_id=workspace.id,
        workspace_file_id=uuid4(),
        version_id=uuid4(),
        event_type="version_created",
        created_at=datetime.now(UTC),
    )

    class Result:
        def __init__(self, *, scalar=None, rows=None):
            self.scalar = scalar
            self.rows = rows or []

        def scalar_one_or_none(self):
            return self.scalar

        def scalars(self):
            return self.rows

    class EventDb:
        def __init__(self):
            self.calls = 0

        async def execute(self, _statement):
            self.calls += 1
            if self.calls == 1:
                return Result(scalar=SimpleNamespace(
                    id=principal.id, deleted_at=None, is_active=True,
                ))
            return Result(rows=[row])

        async def get(self, _model, requested_id):
            assert str(requested_id) == str(workspace.id)
            return workspace

    db = EventDb()
    monkeypatch.setattr(file_events, "async_session_factory", lambda: _Context(db))
    monkeypatch.setattr(
        file_events,
        "current_user_for_user",
        lambda _db, _user: _async_value(principal),
    )
    monkeypatch.setattr(
        file_events.workspace_permission_service,
        "capabilities",
        lambda _db, _workspace, _principal: _async_value({"read": False}),
    )
    response = await file_events.stream_file_events(
        _ConnectedRequest(), after=10, cu=principal,
    )
    iterator = response.body_iterator
    assert "event: cursor" in await anext(iterator)
    second = await anext(iterator)
    assert second == 'id: 11\nevent: cursor\ndata: {"cursor":11}\n\n'
    assert "workspace_id" not in second
    await iterator.aclose()


async def _async_value(value):
    return value
