"""Tests for the LangGraph agent runtime graph.

不依赖真实 LLM 上游：未配置 provider 时 agent_loop 应优雅降级（error），
且 AgentRun 仍落库（status=error），验证图拓扑与 write_run_log 收口。
"""

import pytest
from httpx import AsyncClient

from app.agents.graph import get_agent_graph


async def _make_agent(client: AsyncClient, slug: str = "g") -> str:
    org = await client.post("/api/v1/organizations", json={"name": f"公司-{slug}", "slug": slug})
    org_id = org.json()["id"]
    a = await client.post(
        f"/api/v1/organizations/{org_id}/agents",
        json={"name": "测试智能体", "slug": "tester", "system_prompt": "你是助手", "model_alias": "default"},
    )
    return a.json()["id"]


def test_agent_graph_topology():
    g = get_agent_graph()
    nodes = set(g.get_graph().nodes)
    for n in ("load_config", "retrieve_rag", "load_memory", "agent_loop", "save_memory", "judge", "write_run_log"):
        assert n in nodes


@pytest.mark.asyncio
async def test_playground_no_provider_graceful_error(client: AsyncClient):
    agent_id = await _make_agent(client, "pg-org")
    # 非流式运行：无 provider → agent_loop 捕获并写 error，AgentRun 落库
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
