"""Focused lifecycle tests for Redis-backed DSH admission control."""

from __future__ import annotations

import pytest

from app.config import settings
from app.services.agent_admission import AgentAdmission, AgentQueueFullError, AgentQueueTimeoutError


class ScriptedRedis:
    def __init__(self, results: list[list[int] | int]) -> None:
        self.results = list(results)
        self.calls = 0

    async def eval(self, *_args):
        self.calls += 1
        return self.results.pop(0)


def admission(redis: ScriptedRedis) -> AgentAdmission:
    service = AgentAdmission()
    service.redis = redis  # type: ignore[assignment]
    return service


@pytest.mark.asyncio
async def test_permit_releases_after_success():
    redis = ScriptedRedis([[1, 0], 1])
    statuses: list[tuple[str, int | None]] = []
    async with admission(redis).permit("run-1", "user-1", lambda s, p: _append(statuses, s, p)):
        assert statuses == [("running", None)]
    assert redis.calls == 2


@pytest.mark.asyncio
async def test_queue_full_still_removes_queued_state():
    redis = ScriptedRedis([[-2, 0], 1])
    with pytest.raises(AgentQueueFullError):
        async with admission(redis).permit("run-2", "user-2"):
            pass
    assert redis.calls == 2


@pytest.mark.asyncio
async def test_queue_timeout_is_truthful_and_releases(monkeypatch):
    monkeypatch.setattr(settings, "agent_queue_wait_seconds", 0)
    redis = ScriptedRedis([[0, 3], 1])
    statuses: list[tuple[str, int | None]] = []
    with pytest.raises(AgentQueueTimeoutError, match="0 秒"):
        async with admission(redis).permit("run-3", "user-3", lambda s, p: _append(statuses, s, p)):
            pass
    assert statuses == [("queued", 3)]
    assert redis.calls == 2


async def _append(target: list[tuple[str, int | None]], status: str, position: int | None) -> None:
    target.append((status, position))
