"""Compatibility coverage for the retired administrator Agent playground."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_admin_playground_and_run_history_are_retired(client: AsyncClient):
    playground = await client.post(
        "/api/v1/agents/00000000-0000-0000-0000-000000000001/playground",
        json={"message": "你好", "stream": False},
    )
    assert playground.status_code == 410
    assert "测试广场已下线" in playground.json()["detail"]["message"]

    runs = await client.get(
        "/api/v1/agents/00000000-0000-0000-0000-000000000001/runs",
    )
    assert runs.status_code == 410
    assert "真实用户端到端验收" in runs.json()["detail"]["message"]
