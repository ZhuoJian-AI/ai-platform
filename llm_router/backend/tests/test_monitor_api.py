"""Tests for the retained router, assistant and Manifest Action monitors."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.enterprise_application import (
    EnterpriseApplication,
    EnterpriseApplicationAction,
    EnterpriseApplicationActionRequest,
)
from app.models.user import User


async def _make_org(client: AsyncClient, slug: str = "mon-org") -> str:
    response = await client.post(
        "/api/v1/organizations",
        json={"name": f"公司-{slug}", "slug": slug},
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_monitor_overview_empty(client: AsyncClient):
    org_id = await _make_org(client)
    response = await client.get(f"/api/v1/organizations/{org_id}/monitor/overview")
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"router", "agent", "tool"}
    assert data["router"]["requests"] == 0
    assert data["agent"]["runs"] == 0
    assert data["tool"] == {
        "calls": 0,
        "success_count": 0,
        "error_count": 0,
        "error_rate": 0.0,
        "avg_latency_ms": 0.0,
        "by_action": [],
        "inventory": {},
    }
    assert data["router"]["by_provider"] == []


@pytest.mark.asyncio
async def test_monitor_agent_uses_workspace_and_memory_events(
    client: AsyncClient,
    db_session: AsyncSession,
):
    org_id = await _make_org(client, "mon2")
    created = await client.post(
        f"/api/v1/organizations/{org_id}/agents",
        json={"name": "采购角色", "system_prompt": "你是采购助手"},
    )
    assert created.status_code == 201
    run = AgentRun(
        organization_id=UUID(org_id),
        agent_id=UUID(created.json()["id"]),
        session_id="monitor-native-run",
        request="hi",
        status="error",
        error="test",
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add_all(
        [
            AgentRunEvent(
                run_id=run.id,
                seq=1,
                payload={"type": "tool_result", "name": "workspace_search", "ok": True},
            ),
            AgentRunEvent(
                run_id=run.id,
                seq=2,
                payload={
                    "type": "trace",
                    "category": "memory",
                    "subtype": "load",
                    "facts": 2,
                },
            ),
        ]
    )
    await db_session.flush()

    response = await client.get(f"/api/v1/organizations/{org_id}/monitor/agents")
    assert response.status_code == 200
    data = response.json()
    assert data["runs"] >= 1
    assert data["by_agent"][0]["agent_name"] == "采购角色"
    assert data["components"] == {
        "workspace": {"runs": 1, "ops": 1},
        "memory": {
            "load_runs": 1,
            "facts_loaded": 2,
            "extract_runs": 0,
            "facts_saved": 0,
        },
    }


@pytest.mark.asyncio
async def test_monitor_tools_uses_manifest_action_requests_only(
    client: AsyncClient,
    db_session: AsyncSession,
):
    org_id = await _make_org(client, "mon-tools")
    user = User(organization_id=org_id, username=f"monitor-{uuid4().hex[:8]}")
    application = EnterpriseApplication(
        organization_id=org_id,
        name="Monitor Application",
        slug=f"monitor-app-{uuid4().hex[:8]}",
        entry_url="https://monitor.example.test",
    )
    db_session.add_all([user, application])
    await db_session.flush()
    action = EnterpriseApplicationAction(
        application_id=application.id,
        organization_id=org_id,
        module_key="orders",
        action_key="orders.query",
        name="Query orders",
        operation="query",
        ai_enabled=True,
    )
    db_session.add(action)
    await db_session.flush()
    now = datetime.now(UTC)
    request = EnterpriseApplicationActionRequest(
        application_id=application.id,
        organization_id=org_id,
        action_id=action.id,
        user_id=user.id,
        request_id=f"monitor-{uuid4()}",
        module_key="orders",
        status="completed",
        expires_at=now + timedelta(minutes=5),
    )
    db_session.add(request)
    await db_session.flush()
    request.resolved_at = request.created_at + timedelta(milliseconds=40)
    await db_session.flush()

    response = await client.get(f"/api/v1/organizations/{org_id}/monitor/tools")
    assert response.status_code == 200
    data = response.json()
    assert data["calls"] == 1
    assert data["success_count"] == 1
    assert data["error_count"] == 0
    assert data["avg_latency_ms"] == 40
    assert data["inventory"] == {}
    assert data["by_action"][0]["action_key"] == "orders.query"
    assert data["by_action"][0]["calls"] == 1
