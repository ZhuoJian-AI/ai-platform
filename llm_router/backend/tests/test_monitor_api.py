"""Tests for application monitor aggregation endpoints."""

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
from app.models.skill import SkillExecution, SkillFolder, SkillVersion
from app.models.user import User


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
    assert set(data["tool"]) == {
        "calls",
        "success_count",
        "error_count",
        "error_rate",
        "avg_latency_ms",
        "by_skill",
        "by_action",
        "inventory",
    }
    assert set(data["tool"]["inventory"]) == {"skills"}
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


@pytest.mark.asyncio
async def test_monitor_tools_uses_skill_executions_and_manifest_action_requests(
    client: AsyncClient,
    db_session: AsyncSession,
):
    org_id = await _make_org(client, "mon-tools")
    user = User(organization_id=org_id, username=f"monitor-{uuid4().hex[:8]}")
    skill = SkillFolder(
        organization_id=org_id,
        scope_type="organization",
        name="Monitor Skill",
        slug=f"monitor-skill-{uuid4().hex[:8]}",
    )
    application = EnterpriseApplication(
        organization_id=org_id,
        name="Monitor Application",
        slug=f"monitor-app-{uuid4().hex[:8]}",
        entry_url="https://monitor.example.test",
    )
    db_session.add_all([user, skill, application])
    await db_session.flush()
    version = SkillVersion(
        skill_folder_id=skill.id,
        version_no=1,
        package_hash="a" * 64,
        install_status="ready",
    )
    action = EnterpriseApplicationAction(
        application_id=application.id,
        organization_id=org_id,
        module_key="orders",
        action_key="orders.query",
        name="Query orders",
        operation="query",
        ai_enabled=True,
    )
    db_session.add_all([version, action])
    await db_session.flush()
    skill.active_version_id = version.id
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
    db_session.add_all([
        SkillExecution(
            organization_id=org_id,
            user_id=user.id,
            skill_folder_id=skill.id,
            skill_version_id=version.id,
            status="success",
            latency_ms=30,
        ),
        SkillExecution(
            organization_id=org_id,
            user_id=user.id,
            skill_folder_id=skill.id,
            skill_version_id=version.id,
            status="failed",
            latency_ms=50,
            error="expected test failure",
        ),
        request,
    ])
    await db_session.flush()
    request.resolved_at = request.created_at + timedelta(milliseconds=40)
    await db_session.flush()

    response = await client.get(f"/api/v1/organizations/{org_id}/monitor/tools")

    assert response.status_code == 200
    data = response.json()
    assert data["calls"] == 3
    assert data["success_count"] == 2
    assert data["error_count"] == 1
    assert data["avg_latency_ms"] == 40
    assert data["by_skill"][0]["skill_name"] == "Monitor Skill"
    assert data["by_skill"][0]["calls"] == 2
    assert data["by_action"][0]["action_key"] == "orders.query"
    assert data["by_action"][0]["calls"] == 1
