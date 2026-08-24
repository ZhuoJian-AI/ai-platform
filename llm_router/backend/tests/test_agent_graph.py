"""Contract tests for the single DSH agent runtime entrypoint."""

import pytest
from httpx import AsyncClient

from app.agents.dsh import run_agent


async def _make_agent(client: AsyncClient, slug: str = "g") -> str:
    org = await client.post("/api/v1/organizations", json={"name": f"公司-{slug}", "slug": slug})
    org_id = org.json()["id"]
    a = await client.post(
        f"/api/v1/organizations/{org_id}/agents",
        json={"name": "测试智能体", "slug": "tester", "system_prompt": "你是助手", "model_alias": "default"},
    )
    return a.json()["id"]


def test_playground_uses_dsh_runtime():
    assert run_agent.__module__ == "app.agents.dsh.runner"


@pytest.mark.asyncio
async def test_playground_no_provider_graceful_error(client: AsyncClient):
    agent_id = await _make_agent(client, "pg-org")
    # 非流式运行：无 provider → DSH bridge 优雅降级并写 error，AgentRun 落库
    resp = await client.post(
        f"/api/v1/agents/{agent_id}/playground",
        json={"message": "你好", "stream": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data and data["error"]
    assert data["run_id"] is not None
    assert data["assistant"]  # 占位终答

    # 执行记录应已落库
    runs = await client.get(f"/api/v1/agents/{agent_id}/runs")
    assert runs.status_code == 200
    assert runs.json()["total"] >= 1
    assert runs.json()["data"][0]["status"] == "error"
