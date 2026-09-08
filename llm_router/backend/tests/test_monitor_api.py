"""Tests for application monitor aggregation endpoints."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun, AgentRunEvent


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
async def test_monitor_router_and_agent_after_activity(
    client: AsyncClient,
    db_session: AsyncSession,
):
    org_id = await _make_org(client, "mon2")
    # 监控读取原生助手共用的运行元数据与持久事件，不依赖已退役的测试广场。
    a = await client.post(
        f"/api/v1/organizations/{org_id}/agents",
        json={"name": "m", "slug": "m", "system_prompt": "x", "model_alias": "default"},
    )
    aid = a.json()["id"]
    run = AgentRun(
        organization_id=UUID(org_id),
        agent_id=UUID(aid),
        session_id="monitor-native-run",
        request="hi",
        status="error",
        error="test",
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add(
        AgentRunEvent(
            run_id=run.id,
            seq=1,
            payload={"type": "trace", "category": "rag", "hits": 2},
        )
    )
    await db_session.flush()

    agent_mon = await client.get(f"/api/v1/organizations/{org_id}/monitor/agents")
    assert agent_mon.status_code == 200
    assert agent_mon.json()["runs"] >= 1
    assert agent_mon.json()["by_agent"][0]["agent_name"] == "m"
    assert agent_mon.json()["components"]["rag"] == {"runs": 1, "hits": 2}
