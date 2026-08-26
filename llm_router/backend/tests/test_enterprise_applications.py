"""Enterprise application visibility and AI-tool authorization tests."""

from uuid import uuid4

import pytest

from app.auth.user_auth import CurrentUser
from app.models.connector import ToolConnector, ToolEndpoint
from app.models.department import Department
from app.models.organization import Organization
from app.models.skill import SkillFile, SkillFolder
from app.models.team import Team
from app.models.tool_call_log import ToolCallLog
from app.models.user import User
from app.schemas.enterprise_application import (
    EnterpriseApplicationCreate,
    EnterpriseApplicationGrantInput,
    EnterpriseApplicationToolBindingInput,
)
from app.services import enterprise_application_service as service


async def _organization_tree(db_session):
    org = Organization(name="Tenant Applications", slug=f"apps-{uuid4().hex[:8]}")
    other = Organization(name="Other Tenant", slug=f"other-{uuid4().hex[:8]}")
    db_session.add_all([org, other])
    await db_session.flush()
    department = Department(
        organization_id=org.id, name="Production", slug=f"production-{uuid4().hex[:6]}",
    )
    db_session.add(department)
    await db_session.flush()
    team = Team(
        organization_id=org.id, department_id=department.id,
        name="Planning", slug=f"planning-{uuid4().hex[:6]}",
    )
    user = User(
        organization_id=org.id, department_id=department.id, team_id=team.id,
        username=f"member-{uuid4().hex[:8]}", role="member", is_active=True,
    )
    db_session.add_all([team, user])
    await db_session.flush()
    current = CurrentUser(
        user=user, id=str(user.id), email=user.username, role=user.role,
        organization_id=org.id, department_id=str(department.id), team_id=str(team.id),
    )
    return org, other, department, team, current


@pytest.mark.asyncio
async def test_application_is_hidden_by_default_and_grants_union_across_existing_scopes(db_session):
    org, _, department, team, current = await _organization_tree(db_session)
    application = await service.create_application(db_session, org.id, EnterpriseApplicationCreate(
        name="Production Collaboration",
        slug="production-collaboration",
        entry_url="https://production.example.test",
    ))

    assert await service.list_applications_for_user(db_session, current) == []

    application = await service.replace_grants(db_session, application, [
        EnterpriseApplicationGrantInput(
            scope_type="department", scope_id=department.id, permissions=["view", "ai_query"],
        ),
        EnterpriseApplicationGrantInput(
            scope_type="team", scope_id=team.id, permissions=["ai_update", "export"],
        ),
    ])
    visible = await service.list_applications_for_user(db_session, current)
    assert len(visible) == 1
    assert visible[0][1] == {"view", "ai_query", "ai_update", "export"}

    application.is_active = False
    await db_session.flush()
    assert service.effective_permissions(application, current) == set()


@pytest.mark.asyncio
async def test_bound_tool_requires_matching_application_operation_permission(db_session):
    org, _, department, _, current = await _organization_tree(db_session)
    connector = ToolConnector(
        organization_id=org.id, name="ERP", slug=f"erp-{uuid4().hex[:6]}",
        base_url="https://erp.example.test", auth_type="none",
    )
    db_session.add(connector)
    await db_session.flush()
    endpoint = ToolEndpoint(
        connector_id=connector.id, name="update_order", method="POST", path="/orders/update",
    )
    db_session.add(endpoint)
    await db_session.flush()

    application = await service.create_application(db_session, org.id, EnterpriseApplicationCreate(
        name="ERP Console", slug="erp-console", entry_url="https://erp.example.test/app",
    ))
    application = await service.replace_grants(db_session, application, [
        EnterpriseApplicationGrantInput(
            scope_type="department", scope_id=department.id, permissions=["view", "ai_query"],
        ),
    ])
    await service.replace_tool_bindings(db_session, application, [
        EnterpriseApplicationToolBindingInput(
            target_type="tool_endpoint", target_id=endpoint.id, operation="update",
        ),
    ])

    assert not await service.target_allowed_for_user(
        db_session, current, "tool_endpoint", endpoint.id,
    )
    await service.replace_grants(db_session, application, [
        EnterpriseApplicationGrantInput(
            scope_type="department", scope_id=department.id,
            permissions=["view", "ai_query", "ai_update"],
        ),
    ])
    assert await service.target_allowed_for_user(
        db_session, current, "tool_endpoint", endpoint.id,
    )


@pytest.mark.asyncio
async def test_cross_tenant_scope_and_binding_targets_are_rejected(db_session):
    org, other, _, _, _ = await _organization_tree(db_session)
    foreign_department = Department(
        organization_id=other.id, name="Foreign", slug=f"foreign-{uuid4().hex[:6]}",
    )
    foreign_connector = ToolConnector(
        organization_id=other.id, name="Foreign ERP", slug=f"foreign-erp-{uuid4().hex[:6]}",
        base_url="https://foreign.example.test", auth_type="none",
    )
    db_session.add_all([foreign_department, foreign_connector])
    await db_session.flush()
    foreign_endpoint = ToolEndpoint(
        connector_id=foreign_connector.id, name="foreign", method="GET", path="/foreign",
    )
    db_session.add(foreign_endpoint)
    await db_session.flush()
    application = await service.create_application(db_session, org.id, EnterpriseApplicationCreate(
        name="Local App", slug="local-app", entry_url="https://local.example.test",
    ))

    with pytest.raises(Exception) as grant_error:
        await service.replace_grants(db_session, application, [
            EnterpriseApplicationGrantInput(
                scope_type="department", scope_id=foreign_department.id, permissions=["view"],
            ),
        ])
    assert getattr(grant_error.value, "status_code", None) == 422

    with pytest.raises(Exception) as binding_error:
        await service.replace_tool_bindings(db_session, application, [
            EnterpriseApplicationToolBindingInput(
                target_type="tool_endpoint", target_id=foreign_endpoint.id, operation="query",
            ),
        ])
    assert getattr(binding_error.value, "status_code", None) == 422


@pytest.mark.asyncio
async def test_application_overview_resolves_tools_without_double_counting_skill_wrapper(db_session):
    org, _, _, _, _ = await _organization_tree(db_session)
    connector = ToolConnector(
        organization_id=org.id, name="Production API", slug=f"production-{uuid4().hex[:6]}",
        base_url="https://production.example.test", auth_type="none", health_status="healthy",
    )
    db_session.add(connector)
    await db_session.flush()
    endpoints = [
        ToolEndpoint(connector_id=connector.id, name=f"query_progress_{index}", method="GET", path=f"/progress/{index}")
        for index in range(4)
    ]
    skill = SkillFolder(
        organization_id=org.id, scope_type="organization", scope_id=None,
        name="Production API Skill", slug=f"production-api-{uuid4().hex[:6]}", is_active=True,
    )
    db_session.add_all([*endpoints, skill])
    await db_session.flush()
    db_session.add(SkillFile(skill_folder_id=skill.id, path="skill.md", size=20, content="# Production API"))

    application = await service.create_application(db_session, org.id, EnterpriseApplicationCreate(
        name="Production Collaboration", slug="production-overview",
        entry_url="https://production.example.test/app",
    ))
    bindings = [
        EnterpriseApplicationToolBindingInput(
            target_type="tool_endpoint", target_id=endpoint.id, operation="query",
        )
        for endpoint in endpoints
    ]
    bindings.append(EnterpriseApplicationToolBindingInput(
        target_type="skill_folder", target_id=skill.id, operation="query",
    ))
    application = await service.replace_tool_bindings(db_session, application, bindings)
    db_session.add(ToolCallLog(
        organization_id=org.id, connector_id=connector.id, endpoint_id=endpoints[0].id,
        method="GET", path=endpoints[0].path, status_code=200, latency_ms=42,
    ))
    await db_session.flush()

    overview = await service.get_application_overview(db_session, application)

    assert overview["operation_counts"]["query"] == 4
    assert overview["direct_capability_count"] == 4
    assert overview["skill_binding_count"] == 1
    assert len(overview["capabilities"]) == 5
    assert overview["recent_calls"][0]["capability_name"] == endpoints[0].name
    assert overview["recent_calls"][0]["status"] == "success"
