"""Enterprise application visibility and AI-tool authorization tests."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth.user_auth import CurrentUser
from app.models.connector import ToolConnector, ToolEndpoint
from app.models.department import Department
from app.models.enterprise_application import (
    CrossDepartmentWorkItem,
    EnterpriseApplicationAction,
    EnterpriseApplicationActionRequest,
    EnterpriseApplicationEvent,
    EnterpriseApplicationEventDelivery,
    EnterpriseApplicationGrant,
)
from app.models.organization import Organization
from app.models.role import Role
from app.models.skill import SkillFile, SkillFolder
from app.models.team import Team
from app.models.tool_call_log import ToolCallLog
from app.models.user import User
from app.schemas.enterprise_application import (
    EnterpriseApplicationCreate,
    EnterpriseApplicationEventRouteInput,
    EnterpriseApplicationGrantInput,
    EnterpriseApplicationIntegrationInput,
    EnterpriseApplicationToolBindingInput,
)
from app.services import enterprise_application_service as service
from app.services import subsystem_action_service as action_service
from app.services import subsystem_integration_service as integration_service


def test_action_params_use_complete_json_schema_validation():
    action = SimpleNamespace(input_schema={
        "type": "object",
        "properties": {
            "season": {"type": "string", "pattern": r"^\d{2}[春夏秋冬]$"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "status": {"type": "string", "enum": ["进行中", "已完成"]},
        },
        "required": ["season"],
        "additionalProperties": False,
    })

    action_service._validate_params(action, {"season": "26秋", "limit": 20, "status": "进行中"})

    invalid_rows = [
        {"season": "秋季"},
        {"season": "26秋", "limit": 0},
        {"season": "26秋", "status": "未知"},
        {"season": "26秋", "unexpected": True},
    ]
    for params in invalid_rows:
        with pytest.raises(HTTPException) as raised:
            action_service._validate_params(action, params)
        assert raised.value.status_code == 422
        assert "不符合约定" in raised.value.detail


def test_invalid_action_schema_is_a_contract_conflict():
    action = SimpleNamespace(input_schema={"type": "object", "properties": {"value": {"type": "nope"}}})

    with pytest.raises(HTTPException) as raised:
        action_service._validate_params(action, {"value": "x"})

    assert raised.value.status_code == 409
    assert raised.value.detail == "子系统 Action 输入 Schema 无效"


def _typed_secret(prefix: str, label: str, manifest_url: str) -> str:
    digest = hashlib.sha256(manifest_url.encode()).hexdigest()[:16]
    return f"{prefix}{digest}_{label}-at-least-32-bytes"


def _integration_input(manifest_url: str) -> EnterpriseApplicationIntegrationInput:
    return EnterpriseApplicationIntegrationInput(
        manifest_url=manifest_url,
        manifest_access_token=_typed_secret("zjmf_", "manifest", manifest_url),
        sso_exchange_token=_typed_secret("zjss_", "sso", manifest_url),
        action_signing_secret=_typed_secret("zjac_", "action", manifest_url),
        event_signing_secret=_typed_secret("zjev_", "event", manifest_url),
    )


def test_protocol_v22_validates_department_page_and_action_limits():
    manifest = {
        "protocol": "zhuojian-subsystem",
        "version": 2,
        "contractRevision": "2.2",
        "enterprise": {"key": "aifabei", "name": "爱法贝"},
        "applicationSlug": "sample-review",
        "applicationName": "样品评审",
        "eventsUrl": "/api/integration/events",
        "eventDeliveriesUrl": "/api/integration/event-deliveries",
        "auth": {"ssoPath": "/api/integration/sso", "algorithm": "HS256"},
        "modules": [{
            "moduleKey": "sample_review",
            "name": "样品评审",
            "route": "/sample-review",
            "departments": [{
                "key": "quality",
                "name": "质量部",
                "role": "owner",
                "pageKeys": ["sample_review.list"],
                "actionKeys": ["sample_review.query"],
            }],
            "pages": [{
                "pageKey": "sample_review.list",
                "name": "评审列表",
                "routePattern": "/sample-review",
                "queryActionKey": "sample_review.query",
                "actionKeys": ["sample_review.query"],
                "contextSchema": {"type": "object"},
            }],
            "actions": [{
                "actionKey": "sample_review.query",
                "name": "查询评审",
                "operation": "query",
                "aiEnabled": True,
                "requiresConfirmation": False,
                "inputSchema": {"type": "object"},
                "resultSchema": {"type": "object"},
            }],
        }],
    }
    normalized, events_url, version = integration_service._validate_manifest_payload(
        manifest,
        entry_url="https://sample.example.test/",
        manifest_url="https://sample.example.test/api/integration/manifest",
        expected_slug="sample-review",
    )
    department = normalized["modules"][0]["departments"][0]
    assert version == 2
    assert events_url == "https://sample.example.test/api/integration/events"
    assert department["pageKeys"] == ["sample_review.list"]
    assert department["actionKeys"] == ["sample_review.query"]

    high_risk_manifest = deepcopy(manifest)
    high_risk_manifest["modules"][0]["actions"].append({
        "actionKey": "sample_review.delete",
        "name": "删除评审",
        "operation": "delete",
        "aiEnabled": True,
        "requiresConfirmation": False,
        "inputSchema": {"type": "object"},
        "resultSchema": {"type": "object"},
    })
    high_risk_manifest["modules"][0]["pages"][0]["actionKeys"].append(
        "sample_review.delete"
    )
    high_risk_manifest["modules"][0]["departments"][0]["actionKeys"].append(
        "sample_review.delete"
    )
    normalized_high_risk, _, _ = integration_service._validate_manifest_payload(
        high_risk_manifest,
        entry_url="https://sample.example.test/",
        manifest_url="https://sample.example.test/api/integration/manifest",
        expected_slug="sample-review",
    )
    delete_action = normalized_high_risk["modules"][0]["actions"][1]
    assert delete_action["requiresConfirmation"] is True

    manifest["modules"][0]["departments"][0]["actionKeys"] = ["sample_review.delete"]
    with pytest.raises(ValueError, match="department actionKeys"):
        integration_service._validate_manifest_payload(
            manifest,
            entry_url="https://sample.example.test/",
            manifest_url="https://sample.example.test/api/integration/manifest",
            expected_slug="sample-review",
        )


def test_protocol_v24_separates_department_responsibility_from_access_roles():
    manifest = {
        "protocol": "zhuojian-subsystem",
        "version": 2,
        "contractRevision": "2.4",
        "enterprise": {"key": "aifabei", "name": "爱法贝"},
        "applicationSlug": "sample-review",
        "applicationName": "样品评审",
        "eventsUrl": "/api/integration/events",
        "eventDeliveriesUrl": "/api/integration/event-deliveries",
        "auth": {"ssoPath": "/api/integration/sso", "algorithm": "HS256"},
        "modules": [{
            "moduleKey": "sample_review",
            "name": "样品评审",
            "route": "/sample-review",
            "departments": [{"key": "design", "name": "设计部", "role": "owner"}],
            "accessRoles": [{
                "roleKey": "sample_review.designer",
                "name": "样品设计负责人",
                "suggestedDepartmentKey": "design",
                "pageKeys": ["sample_review.list"],
                "actionKeys": ["sample_review.query"],
            }],
            "pages": [{
                "pageKey": "sample_review.list",
                "name": "评审列表",
                "routePattern": "/sample-review",
                "queryActionKey": "sample_review.query",
                "actionKeys": ["sample_review.query"],
                "contextSchema": {"type": "object"},
            }],
            "actions": [{
                "actionKey": "sample_review.query",
                "name": "查询评审",
                "operation": "query",
                "aiEnabled": True,
                "requiresConfirmation": False,
                "inputSchema": {"type": "object"},
                "resultSchema": {"type": "object"},
            }],
        }],
    }
    normalized, _, _ = integration_service._validate_manifest_payload(
        manifest,
        entry_url="https://sample.example.test/",
        manifest_url="https://sample.example.test/api/integration/manifest",
        expected_slug="sample-review",
    )
    assert normalized["modules"][0]["departments"][0].get("pageKeys") is None
    assert normalized["modules"][0]["accessRoles"][0]["roleKey"] == "sample_review.designer"

    manifest["modules"][0]["accessRoles"][0]["actionKeys"] = ["sample_review.delete"]
    with pytest.raises(ValueError, match="actionKeys must reference module actions"):
        integration_service._validate_manifest_payload(
            manifest,
            entry_url="https://sample.example.test/",
            manifest_url="https://sample.example.test/api/integration/manifest",
            expected_slug="sample-review",
        )


def test_protocol_v25_uses_code_exchange_and_reviews_nested_schema_changes():
    manifest = {
        "protocol": "zhuojian-subsystem",
        "version": 2,
        "contractRevision": "2.5",
        "enterprise": {"key": "aifabei", "name": "爱法贝"},
        "applicationSlug": "sample-review",
        "applicationName": "样品评审",
        "eventsUrl": "/api/integration/events",
        "eventDeliveriesUrl": "/api/integration/event-deliveries",
        "auth": {
            "ssoPath": "/api/integration/sso",
            "mode": "authorization_code",
        },
        "modules": [{
            "moduleKey": "sample_review",
            "name": "样品评审",
            "route": "/sample-review",
            "departments": [{"key": "design", "name": "设计部", "role": "owner"}],
            "accessRoles": [{
                "roleKey": "sample_review.designer",
                "name": "样品设计负责人",
                "suggestedDepartmentKey": "design",
                "pageKeys": ["sample_review.list"],
                "actionKeys": ["sample_review.query"],
            }],
            "pages": [{
                "pageKey": "sample_review.list",
                "name": "评审列表",
                "routePattern": "/sample-review",
                "queryActionKey": "sample_review.query",
                "actionKeys": ["sample_review.query"],
                "contextSchema": {"type": "object"},
            }],
            "actions": [{
                "actionKey": "sample_review.query",
                "name": "查询评审",
                "operation": "query",
                "aiEnabled": True,
                "requiresConfirmation": False,
                "inputSchema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
                "resultSchema": {"type": "object"},
            }],
        }],
    }
    normalized, _, _ = integration_service._validate_manifest_payload(
        manifest,
        entry_url="https://sample.example.test/",
        manifest_url="https://sample.example.test/api/integration/manifest",
        expected_slug="sample-review",
    )

    display_copy = deepcopy(normalized)
    display_copy["modules"][0]["actions"][0]["name"] = "查询样品评审"
    assert integration_service.manifest_change_summary(normalized, display_copy)[0][
        "securitySensitive"
    ] is True

    schema_change = deepcopy(normalized)
    schema_change["modules"][0]["actions"][0]["inputSchema"]["properties"]["name"] = {
        "type": "number"
    }
    schema_diff = integration_service.manifest_change_summary(normalized, schema_change)[0]
    assert schema_diff["securitySensitive"] is True
    assert any("inputSchema.properties.name" in path for path in schema_diff["changedPaths"])

    legacy_auth = deepcopy(manifest)
    legacy_auth["auth"] = {
        "ssoPath": "/api/integration/sso",
        "algorithm": "HS256",
    }
    with pytest.raises(ValueError, match="authorization_code"):
        integration_service._validate_manifest_payload(
            legacy_auth,
            entry_url="https://sample.example.test/",
            manifest_url="https://sample.example.test/api/integration/manifest",
            expected_slug="sample-review",
        )


def test_manifest_review_scans_sensitive_changes_after_display_cap():
    before = {
        "modules": [
            {"name": f"模块 {index}", "description": f"说明 {index}"}
            for index in range(205)
        ],
        "zzSecurityBoundary": "before",
    }
    after = deepcopy(before)
    for index, module in enumerate(after["modules"]):
        module["name"] = f"新模块 {index}"
    after["zzSecurityBoundary"] = "after"

    summary = integration_service.manifest_change_summary(before, after)[0]
    assert summary["securitySensitive"] is True
    assert summary["changedPathCount"] == 206
    assert len(summary["changedPaths"]) == 200
    assert summary["changedPathsTruncated"] is True
    assert "$.zzSecurityBoundary" not in summary["changedPaths"]


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("modules", 0, "pages", 0, "routePattern"), "/new-list"),
        (("modules", 0, "actions", 0, "operation"), "update"),
        (
            (
                "modules", 0, "actions", 0, "inputSchema",
                "properties", "styleId", "type",
            ),
            "integer",
        ),
        (("modules", 0, "actions", 0, "aiEnabled"), False),
    ],
)
def test_protocol_v24_sensitive_manifest_updates_require_review(path, replacement):
    before = {
        "contractRevision": "2.4",
        "modules": [{
            "pages": [{"routePattern": "/list"}],
            "actions": [{
                "operation": "query",
                "aiEnabled": True,
                "inputSchema": {
                    "type": "object",
                    "properties": {"styleId": {"type": "string"}},
                },
            }],
        }],
    }
    after = deepcopy(before)
    cursor = after
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = replacement

    summary = integration_service.manifest_change_summary(before, after)
    assert summary[0]["securitySensitive"] is True
    assert integration_service._manifest_requires_review(before, "2.4", summary) is True


def test_manifest_review_preserves_initial_contract_gates():
    sensitive_diff = [{"securitySensitive": True}]

    assert integration_service._manifest_requires_review({}, "2.4", sensitive_diff) is False
    assert integration_service._manifest_requires_review({}, "2.5", sensitive_diff) is True


def test_integration_credentials_reject_cross_purpose_values():
    manifest_url = "https://sample.example.test/api/integration/manifest"
    with pytest.raises(ValueError, match="manifest access credential"):
        EnterpriseApplicationIntegrationInput(
            manifest_url=manifest_url,
            auth_token=_typed_secret("zjss_", "sso", manifest_url),
        )
    with pytest.raises(ValueError, match="zjac_"):
        EnterpriseApplicationIntegrationInput(
            manifest_url=manifest_url,
            action_signing_secret=_typed_secret("zjev_", "event", manifest_url),
        )


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
async def test_v25_credentials_cannot_be_partially_cleared_or_downgraded(db_session):
    org, _, _, _, _ = await _organization_tree(db_session)
    manifest_url = "https://credentials.example.test/api/integration/manifest"
    application = await service.create_application(
        db_session,
        org.id,
        EnterpriseApplicationCreate(
            name="Credentials",
            slug="credentials",
            entry_url="https://credentials.example.test/",
        ),
    )
    integration = await integration_service.configure_integration(
        db_session,
        application,
        _integration_input(manifest_url),
    )
    integration.manifest = {"contractRevision": "2.5"}
    await db_session.flush()

    with pytest.raises(HTTPException) as raised:
        await integration_service.configure_integration(
            db_session,
            application,
            EnterpriseApplicationIntegrationInput(
                manifest_url=manifest_url,
                clear_action_signing_secret=True,
            ),
        )
    assert raised.value.status_code == 422
    assert integration.credential_version == 2
    assert integration.action_signing_secret_encrypted is not None

    revoked = await integration_service.configure_integration(
        db_session,
        application,
        EnterpriseApplicationIntegrationInput(
            manifest_url=manifest_url,
            sync_enabled=False,
            clear_auth_token=True,
            clear_sso_exchange_token=True,
            clear_action_signing_secret=True,
            clear_event_signing_secret=True,
        ),
    )
    assert revoked.sync_enabled is False
    assert revoked.credential_version == 2
    assert integration_service.credentials_complete(revoked) is False


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
            module_keys=["factory_progress"],
        ),
        EnterpriseApplicationGrantInput(
            scope_type="team", scope_id=team.id, permissions=["ai_update", "export"],
            module_keys=["factory_progress"],
        ),
    ])
    visible = await service.list_applications_for_user(db_session, current)
    assert len(visible) == 1
    assert visible[0][1] == {"view", "ai_query", "ai_update", "export"}
    assert service.effective_module_keys(application, current) == ["factory_progress"]

    application.is_active = False
    await db_session.flush()
    assert service.effective_permissions(application, current) == set()


@pytest.mark.asyncio
async def test_application_grant_does_not_treat_another_department_as_membership(db_session):
    org, _, primary_department, team, current = await _organization_tree(db_session)
    secondary_department = Department(
        organization_id=org.id,
        name="Quality",
        slug=f"quality-{uuid4().hex[:6]}",
    )
    db_session.add(secondary_department)
    await db_session.flush()
    application = await service.create_application(db_session, org.id, EnterpriseApplicationCreate(
        name="Quality Collaboration",
        slug="quality-collaboration",
        entry_url="https://quality.example.test",
    ))
    application = await service.replace_grants(db_session, application, [
        EnterpriseApplicationGrantInput(
            scope_type="department",
            scope_id=secondary_department.id,
            permissions=["view", "ai_query"],
            module_keys=["quality_review"],
        ),
    ])

    assert service.effective_permissions(application, current) == set()
    assert service.effective_module_keys(application, current) == []


@pytest.mark.asyncio
async def test_replace_grants_repairs_a_preexisting_orphan_scope(db_session):
    org, _, department, _, _ = await _organization_tree(db_session)
    role = Role(
        organization_id=org.id,
        name="Quality approver",
        code=f"quality-approver-{uuid4().hex[:6]}",
        data_scope="self",
        is_active=True,
    )
    db_session.add(role)
    await db_session.flush()
    application = await service.create_application(db_session, org.id, EnterpriseApplicationCreate(
        name="Review Console",
        slug=f"review-console-{uuid4().hex[:6]}",
        entry_url="https://review.example.test",
    ))
    application = await service.replace_grants(db_session, application, [
        EnterpriseApplicationGrantInput(
            scope_type="department", scope_id=department.id, permissions=["view"],
        ),
    ])

    department.deleted_at = datetime.now(UTC)
    await db_session.flush()
    application = await service.replace_grants(db_session, application, [
        # A stale replace-all client echoes the now-orphaned grant.
        EnterpriseApplicationGrantInput(
            scope_type="department", scope_id=department.id, permissions=["view"],
        ),
        EnterpriseApplicationGrantInput(
            scope_type="role", scope_id=role.id, permissions=["view", "ai_query"],
        ),
    ])

    assert [(grant.scope_type, grant.scope_id) for grant in application.grants] == [
        ("role", str(role.id)),
    ]
    stale = (await db_session.execute(select(EnterpriseApplicationGrant).where(
        EnterpriseApplicationGrant.application_id == application.id,
        EnterpriseApplicationGrant.scope_type == "department",
    ))).scalar_one()
    assert stale.deleted_at is not None


@pytest.mark.asyncio
async def test_replace_grants_still_rejects_a_new_invalid_scope(db_session):
    org, _, _, _, _ = await _organization_tree(db_session)
    application = await service.create_application(db_session, org.id, EnterpriseApplicationCreate(
        name="Strict Console",
        slug=f"strict-console-{uuid4().hex[:6]}",
        entry_url="https://strict.example.test",
    ))

    with pytest.raises(HTTPException) as exc_info:
        await service.replace_grants(db_session, application, [
            EnterpriseApplicationGrantInput(
                scope_type="department", scope_id=uuid4(), permissions=["view"],
            ),
        ])
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_one_department_can_receive_multiple_applications_and_modules(db_session):
    org, _, department, _, current = await _organization_tree(db_session)
    applications = []
    for name, slug, module_key in (
        ("Sample Review", "sample-review", "sample_review"),
        ("Production Handoff", "production-handoff", "production_handoff"),
    ):
        application = await service.create_application(db_session, org.id, EnterpriseApplicationCreate(
            name=name,
            slug=f"{slug}-{uuid4().hex[:6]}",
            entry_url=f"https://{slug}.example.test",
        ))
        applications.append(await service.replace_grants(db_session, application, [
            EnterpriseApplicationGrantInput(
                scope_type="department",
                scope_id=department.id,
                permissions=["view", "ai_query"],
                module_keys=[module_key],
            ),
        ]))

    visible = await service.list_applications_for_user(db_session, current)
    assert {application.id for application, _ in visible} == {
        application.id for application in applications
    }
    assert {
        module_key
        for application in applications
        for module_key in service.effective_module_keys(application, current)
    } == {"sample_review", "production_handoff"}


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


@pytest.mark.asyncio
async def test_subsystem_sync_is_replay_safe_and_routes_work_items(db_session, monkeypatch):
    org, _, department, _, _ = await _organization_tree(db_session)
    application = await service.create_application(
        db_session,
        org.id,
        EnterpriseApplicationCreate(
            name="Garment Production",
            slug="garment-production-collaboration",
            entry_url="https://garment.example.test/",
        ),
    )
    integration = await integration_service.configure_integration(
        db_session,
        application,
        _integration_input("https://garment.example.test/api/integration/manifest"),
    )
    expected_manifest_token = _typed_secret(
        "zjmf_", "manifest", "https://garment.example.test/api/integration/manifest"
    )
    assert integration.auth_token_encrypted != expected_manifest_token
    await integration_service.replace_routes(
        db_session,
        application,
        [EnterpriseApplicationEventRouteInput(
            name="生产款号更新通知设计部",
            event_type="production.style.saved",
            module_key="style_hub",
            target_scope_type="department",
            target_scope_id=department.id,
            target_module_key="style_design",
        )],
    )

    manifest = {
        "protocol": "zhuojian-subsystem",
        "version": 1,
        "applicationSlug": application.slug,
        "applicationName": "爱法贝生产协同",
        "modules": [{"key": "style_hub", "name": "款号资料中心"}],
        "eventFeed": {"path": "/api/integration/events"},
    }
    event = {
        "sequence": 1,
        "eventId": "event-1",
        "eventType": "production.style.saved",
        "moduleKey": "style_hub",
        "entityType": "style",
        "entityId": "203A023",
        "action": "saved",
        "occurredAt": "2026-08-27T12:00:00+08:00",
        "payload": {"styles": ["203A023"]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {expected_manifest_token}"
        if request.url.path.endswith("/manifest"):
            return httpx.Response(200, json=manifest)
        after = int(request.url.params.get("after", "0"))
        return httpx.Response(
            200,
            json={"items": [event] if after == 0 else [], "nextAfter": 1, "hasMore": False},
        )

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        integration_service.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_client(transport=transport),
    )

    first = await integration_service.sync_integration(db_session, application)
    second = await integration_service.sync_integration(db_session, application)
    assert first == {
        "status": "healthy",
        "manifest_updated": True,
        "received_events": 1,
        "created_work_items": 1,
        "delivered_events": 0,
        "cursor_sequence": 1,
        "detail": None,
    }
    assert second["status"] == "healthy"
    assert second["received_events"] == 0
    assert len((await db_session.execute(select(EnterpriseApplicationEvent))).scalars().all()) == 1
    work_items = list((await db_session.execute(select(CrossDepartmentWorkItem))).scalars().all())
    assert len(work_items) == 1
    assert work_items[0].title == "生产款号更新通知设计部：203A023"


@pytest.mark.asyncio
async def test_subsystem_sync_rejects_late_bad_page_without_partial_activation(
    db_session, monkeypatch
):
    org, _, _, _, _ = await _organization_tree(db_session)
    application = await service.create_application(
        db_session,
        org.id,
        EnterpriseApplicationCreate(
            name="Atomic Sync",
            slug="atomic-sync",
            entry_url="https://atomic.example.test/",
        ),
    )
    integration = await integration_service.configure_integration(
        db_session,
        application,
        _integration_input("https://atomic.example.test/api/integration/manifest"),
    )
    baseline = {
        "protocol": "zhuojian-subsystem",
        "version": 1,
        "applicationSlug": application.slug,
        "applicationName": "Old Manifest",
        "modules": [{"key": "orders", "name": "Orders"}],
        "eventFeed": {"path": "/api/integration/events"},
    }
    integration.manifest = deepcopy(baseline)
    integration.events_url = "https://atomic.example.test/api/integration/events"
    integration.protocol_version = 1
    integration.sync_status = "healthy"
    await db_session.flush()
    candidate = deepcopy(baseline)
    candidate["applicationName"] = "New Manifest"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/manifest"):
            return httpx.Response(200, json=candidate)
        after = int(request.url.params.get("after", "0"))
        event = {
            "sequence": 1,
            "eventId": f"event-{after}",
            "eventType": "orders.changed.v1",
            "moduleKey": "orders",
            "payload": {},
        }
        return httpx.Response(200, json={"items": [event], "hasMore": True})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        integration_service.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_client(transport=httpx.MockTransport(handler)),
    )

    result = await integration_service.sync_integration(db_session, application)
    await db_session.refresh(integration)
    assert result["status"] == "error"
    assert "strictly ascending" in str(result["detail"])
    assert integration.manifest == baseline
    assert integration.cursor_sequence == 0
    assert not (await db_session.execute(select(EnterpriseApplicationEvent))).scalars().all()
    assert not (await db_session.execute(select(CrossDepartmentWorkItem))).scalars().all()


@pytest.mark.asyncio
async def test_protocol_v2_sync_discovers_actions_and_matches_departments_without_auto_grants(
    db_session, monkeypatch,
):
    org, _, department, _, _ = await _organization_tree(db_session)
    application = await service.create_application(
        db_session,
        org.id,
        EnterpriseApplicationCreate(
            name="Sample Review", slug="sample-review", entry_url="https://sample.example.test/",
        ),
    )
    await integration_service.configure_integration(
        db_session,
        application,
        _integration_input("https://sample.example.test/api/integration/manifest"),
    )
    manifest = {
        "protocol": "zhuojian-subsystem",
        "version": 2,
        "enterprise": {"key": "aifabei", "name": "爱法贝"},
        "applicationSlug": application.slug,
        "applicationName": "样衣协同",
        "eventsUrl": "/api/integration/events",
        "auth": {"ssoPath": "/api/integration/sso", "algorithm": "HS256"},
        "modules": [{
            "moduleKey": "sample_review",
            "name": "样衣评审",
            "route": "/sample-review",
            "departments": [{"key": department.slug, "name": department.name, "role": "owner"}],
            "actions": [{
                "actionKey": "sample_review.approve",
                "name": "通过评审",
                "operation": "update",
                "aiEnabled": True,
                "requiresConfirmation": True,
                "inputSchema": {"type": "object", "required": ["styleId"]},
                "resultSchema": {"type": "object"},
            }],
        }],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/manifest"):
            return httpx.Response(200, json=manifest)
        return httpx.Response(200, json={"items": [], "nextAfter": 0, "hasMore": False})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        integration_service.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    result = await integration_service.sync_integration(db_session, application)

    assert result["status"] == "healthy"
    integration = await integration_service.get_integration(db_session, application.id)
    assert integration is not None and integration.protocol_version == 2
    department_manifest = integration.manifest["modules"][0]["departments"][0]
    assert department_manifest["platformDepartmentId"] == str(department.id)
    actions = list((await db_session.execute(select(EnterpriseApplicationAction))).scalars().all())
    assert [(item.action_key, item.module_key, item.requires_confirmation) for item in actions] == [
        ("sample_review.approve", "sample_review", True),
    ]
    assert application.grants == []


@pytest.mark.asyncio
async def test_module_permissions_and_high_risk_action_confirmation_are_replay_safe(
    db_session, monkeypatch,
):
    org, _, department, _, current = await _organization_tree(db_session)
    application = await service.create_application(
        db_session,
        org.id,
        EnterpriseApplicationCreate(
            name="Sample Review", slug="sample-review-action", entry_url="https://action.example.test/",
        ),
    )
    integration = await integration_service.configure_integration(
        db_session,
        application,
        _integration_input("https://action.example.test/api/integration/manifest"),
    )
    integration.protocol_version = 2
    integration.manifest = {
        "contractRevision": "2.1",
        "modules": [{
            "moduleKey": "sample_review",
            "pages": [{
                "pageKey": "sample_review.detail",
                "actionKeys": ["sample_review.approve"],
            }],
        }],
    }
    action = EnterpriseApplicationAction(
        application_id=application.id,
        organization_id=org.id,
        module_key="sample_review",
        action_key="sample_review.approve",
        name="通过评审",
        operation="approve",
        ai_enabled=True,
        requires_confirmation=True,
        input_schema={"type": "object", "required": ["styleId"]},
        result_schema={"type": "object"},
    )
    db_session.add(action)
    await db_session.flush()
    application = await service.replace_grants(db_session, application, [
        EnterpriseApplicationGrantInput(
            scope_type="department",
            scope_id=department.id,
            permissions=["view", "ai_approve"],
            module_keys=["sample_review"],
            module_access={
                "sample_review": {
                    "role": "owner",
                    "permissions": ["view", "ai_approve"],
                    "action_keys": ["sample_review.approve"],
                    "page_access": {
                        "sample_review.detail": {
                            "permissions": ["view", "ai_approve"],
                            "action_keys": ["sample_review.approve"],
                        },
                    },
                },
            },
        ),
    ])
    assert service.effective_module_permissions(application, current, "sample_review") == {
        "view", "ai_approve",
    }
    no_data_scope = {
        "unrestricted": False,
        "include_self": False,
        "own_only": False,
        "department_ids": (),
    }
    serialized_no_data_scope = {**no_data_scope, "department_ids": []}
    module_claims = service.effective_module_claims(application, current, "sample_review")
    assert module_claims == {
        "permissions": ["ai_approve", "view"],
        "action_keys": ["sample_review.approve"],
        "page_access": {
            "sample_review.detail": {
                "permissions": ["ai_approve", "view"],
                "action_keys": ["sample_review.approve"],
                "data_scopes": {
                    "ai_approve": no_data_scope,
                    "view": no_data_scope,
                },
                "action_data_scopes": {
                    "sample_review.approve": no_data_scope,
                },
            },
        },
    }
    launch_code, launch_nonce = await action_service.issue_launch_code(
        db_session,
        integration,
        application,
        current,
        "sample_review",
        {"view", "ai_approve"},
        module_claims,
        redirect_path="/sample-review",
        session_binding_hash="a" * 64,
    )
    redemption = await action_service.redeem_launch_code(
        db_session,
        integration,
        code=launch_code,
        redirect_path="/sample-review",
        launch_nonce=launch_nonce,
    )
    launch_claims = redemption["claims"]
    with pytest.raises(HTTPException) as replay:
        await action_service.redeem_launch_code(
            db_session,
            integration,
            code=launch_code,
            redirect_path="/sample-review",
            launch_nonce=launch_nonce,
        )
    assert replay.value.status_code == 401

    disabled_code, disabled_nonce = await action_service.issue_launch_code(
        db_session,
        integration,
        application,
        current,
        "sample_review",
        {"view", "ai_approve"},
        module_claims,
        redirect_path="/sample-review",
        session_binding_hash="b" * 64,
    )
    application.is_active = False
    await db_session.flush()
    with pytest.raises(HTTPException) as disabled:
        await action_service.redeem_launch_code(
            db_session,
            integration,
            code=disabled_code,
            redirect_path="/sample-review",
            launch_nonce=disabled_nonce,
        )
    assert disabled.value.status_code == 409
    application.is_active = True
    await db_session.flush()

    assert launch_claims["pageKeys"] == ["sample_review.detail"]
    assert launch_claims["actionKeys"] == ["sample_review.approve"]
    assert (
        datetime.fromisoformat(launch_claims["exp"])
        - datetime.fromisoformat(launch_claims["iat"])
    ).total_seconds() == 120
    assert launch_claims["sessionBindingHash"] == "a" * 64
    assert launch_claims["authEpoch"] == current.user.auth_epoch
    assert launch_claims["pageAccess"]["sample_review.detail"] == {
        "permissions": ["ai_approve", "view"],
        "actionKeys": ["sample_review.approve"],
        "dataScopes": {
            "ai_approve": serialized_no_data_scope,
            "view": serialized_no_data_scope,
        },
        "actionDataScopes": {
            "sample_review.approve": serialized_no_data_scope,
        },
    }
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        token = request.headers["authorization"].split(" ", 1)[1]
        claims = jwt.decode(
            token,
            _typed_secret(
                "zjac_", "action", "https://action.example.test/api/integration/manifest"
            ),
            algorithms=["HS256"],
            audience=application.slug,
        )
        assert claims["typ"] == "zhuojian-action"
        assert claims["moduleKey"] == "sample_review"
        assert claims["pageKey"] == "sample_review.detail"
        assert claims["actionKey"] == action.action_key
        assert claims["confirmationId"]
        assert claims["confirmedBy"] == current.id
        assert claims["confirmedAt"]
        assert claims["paramsHash"]
        body = json.loads(request.content)
        assert body["requestId"] == "action-request-1"
        assert body["operation"] == "approve"
        assert body["expectedVersion"] == 1
        return httpx.Response(200, json={"status": "approved", "entityVersion": "2"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        action_service.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    pending = await action_service.invoke_action(
        db_session,
        application.id,
        action.action_key,
        action.module_key,
        {"styleId": "203A023"},
        current,
        request_id="action-request-1",
        page_key="sample_review.detail",
        operation="approve",
        expected_version=1,
    )
    assert pending["status"] == "pending"
    request_row = (await db_session.execute(select(EnterpriseApplicationActionRequest))).scalar_one()
    assert request_row.params_encrypted and "203A023" not in request_row.params_encrypted

    completed = await action_service.resolve_confirmation(db_session, request_row.id, current, approve=True)
    repeated = await action_service.resolve_confirmation(db_session, request_row.id, current, approve=True)
    assert completed["status"] == repeated["status"] == "completed"
    assert completed["result"]["entityVersion"] == "2"
    assert calls == 1
    assert request_row.params_encrypted is None


@pytest.mark.asyncio
async def test_cross_application_event_delivery_is_signed_and_idempotent(db_session, monkeypatch):
    org, _, department, _, _ = await _organization_tree(db_session)
    source = await service.create_application(
        db_session,
        org.id,
        EnterpriseApplicationCreate(
            name="Sample Review", slug="sample-review-source",
            entry_url="https://source.example/",
        ),
    )
    target = await service.create_application(
        db_session,
        org.id,
        EnterpriseApplicationCreate(
            name="Production Handoff", slug="production-handoff-target",
            entry_url="https://target.example/",
        ),
    )
    source_integration = await integration_service.configure_integration(
        db_session,
        source,
        _integration_input("https://source.example/api/integration/manifest"),
    )
    target_integration = await integration_service.configure_integration(
        db_session,
        target,
        _integration_input("https://target.example/api/integration/manifest"),
    )
    target_integration.protocol_version = 2
    target_integration.manifest = {
        "contractRevision": "2.1",
        "enterprise": {"key": "aifabei", "name": "爱法贝"},
        "eventDeliveriesUrl": "/api/integration/event-deliveries",
    }
    await integration_service.replace_routes(
        db_session,
        source,
        [EnterpriseApplicationEventRouteInput(
            name="样品评审通过后生成生产交接草稿",
            event_type="design.sample_review.approved.v1",
            module_key="sample_review",
            target_scope_type="department",
            target_scope_id=department.id,
            target_application_id=target.id,
            target_module_key="production_handoff",
        )],
    )
    stored, work_items = await integration_service._store_event(db_session, source_integration, {
        "sequence": 1,
        "eventId": "sample-review-approved-1",
        "eventType": "design.sample_review.approved.v1",
        "moduleKey": "sample_review",
        "entityType": "sample_review",
        "entityId": "SR-001",
        "action": "approved",
        "occurredAt": "2026-08-30T12:00:00+08:00",
        "payload": {"sampleNumber": "S-001"},
    })
    assert stored is True and work_items == 1

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url == "https://target.example/api/integration/event-deliveries"
        claims = jwt.decode(
            request.headers["authorization"].split(" ", 1)[1],
            _typed_secret(
                "zjev_", "event", "https://target.example/api/integration/manifest"
            ),
            algorithms=["HS256"],
            audience=target.slug,
        )
        body = json.loads(request.content)
        assert claims["typ"] == "zhuojian-event"
        assert claims["organizationId"] == str(org.id)
        assert claims["deliveryId"] == body["deliveryId"]
        assert claims["eventId"] == body["event"]["eventId"]
        assert claims["targetModuleKey"] == "production_handoff"
        return httpx.Response(200, json={"status": "accepted", "draftId": "PH-001"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        integration_service.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    assert await integration_service.deliver_pending_events(
        db_session, organization_id=org.id,
    ) == 1
    assert await integration_service.deliver_pending_events(
        db_session, organization_id=org.id,
    ) == 0
    delivery = (
        await db_session.execute(select(EnterpriseApplicationEventDelivery))
    ).scalar_one()
    assert delivery.status == "delivered"
    assert delivery.response["draftId"] == "PH-001"
    assert calls == 1


def test_public_url_validation_rejects_private_and_metadata_addresses():
    from app.utils.public_url import assert_public_http_url

    with pytest.raises(ValueError):
        assert_public_http_url("https://127.0.0.1/health")
    with pytest.raises(ValueError):
        assert_public_http_url("http://169.254.169.254/latest/meta-data")
