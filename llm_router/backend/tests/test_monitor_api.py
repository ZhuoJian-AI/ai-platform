"""Tests for application monitor aggregation endpoints."""

import pytest
from httpx import AsyncClient


async def _make_org(client: AsyncClient, slug: str = "mon-org") -> str:
    r = await client.post("/api/v1/organizations", json={"name": f"公司-{slug}", "slug": slug})
    assert r.status_code == 201
    return r.json()["id"]


@pytest.mark.asyncio
async def test_monitor_overview_empty(client: AsyncClient):
    org_id = await _make_org(client)
    r = await client.get(f"/api/v1/organizations/{org_id}/monitor/overview")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"router", "agent", "tool"}
    assert data["router"]["requests"] == 0
    assert data["agent"]["runs"] == 0
    assert data["tool"]["calls"] == 0
    assert data["router"]["by_provider"] == []


@pytest.mark.asyncio
async def test_monitor_router_and_agent_after_activity(client: AsyncClient):
    org_id = await _make_org(client, "mon2")
    # 触发一次 agent 执行（无 provider，会落一条 error 的 AgentRun）
    a = await client.post(
        f"/api/v1/organizations/{org_id}/agents",
        json={"name": "m", "slug": "m", "system_prompt": "x", "model_alias": "default"},
    )
    aid = a.json()["id"]
    await client.post(f"/api/v1/agents/{aid}/playground", json={"message": "hi", "stream": False})

    agent_mon = await client.get(f"/api/v1/organizations/{org_id}/monitor/agents")
    assert agent_mon.status_code == 200
    assert agent_mon.json()["runs"] >= 1
    assert agent_mon.json()["by_agent"][0]["agent_name"] == "m"
