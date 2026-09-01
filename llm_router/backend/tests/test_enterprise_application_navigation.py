"""Authorization projection tests for native enterprise child-module navigation."""

from types import SimpleNamespace

from app.auth.user_auth import CurrentUser
from app.services import enterprise_application_service as service


def _current_user() -> CurrentUser:
    return CurrentUser(
        user=SimpleNamespace(department_ids=[]),
        id="user-1",
        email="member@example.test",
        role="member",
        organization_id="organization-1",
        department_id="department-1",
        team_id=None,
        role_ids=("role-1",),
    )


def test_visible_manifest_modules_uses_the_same_view_grants_as_launch(monkeypatch):
    application = SimpleNamespace(
        integration=SimpleNamespace(
            protocol_version=2,
            manifest={
                "modules": [
                    {
                        "moduleKey": "sample_review",
                        "name": "样品评审",
                        "pages": [{
                            "pageKey": "sample_review.list",
                            "queryActionKey": "sample_review.query",
                            "actionKeys": ["sample_review.query"],
                        }],
                    },
                    {
                        "moduleKey": "review_remediation",
                        "name": "评审整改闭环",
                        "pages": [{
                            "pageKey": "review_remediation.list",
                            "queryActionKey": "review_remediation.query",
                            "actionKeys": ["review_remediation.query"],
                        }],
                    },
                    {
                        "moduleKey": "sample_release_archive",
                        "name": "样品放行与归档",
                        "pages": [{
                            "pageKey": "sample_release_archive.list",
                            "queryActionKey": "sample_release_archive.query",
                            "actionKeys": ["sample_release_archive.query"],
                        }],
                    },
                ],
            },
        ),
        is_active=True,
        deleted_at=None,
        grants=[],
    )
    allowed = {"sample_review", "sample_release_archive"}
    monkeypatch.setattr(
        service,
        "effective_module_permissions",
        lambda _application, _user, module_key: {"view"} if module_key in allowed else {"query"},
    )
    monkeypatch.setattr(
        service,
        "effective_module_claims",
        lambda _application, _user, module_key: {"page_access": {"page": {}}}
        if module_key in allowed else {"page_access": {}},
    )

    assert service.visible_manifest_modules(application, _current_user()) == [
        {"module_key": "sample_review", "name": "样品评审"},
        {"module_key": "sample_release_archive", "name": "样品放行与归档"},
    ]


def test_legacy_integrations_do_not_create_native_child_module_navigation():
    application = SimpleNamespace(
        integration=SimpleNamespace(protocol_version=1, manifest={"modules": []}),
    )

    assert service.visible_manifest_modules(application, _current_user()) == []


def test_contract_v24_ignores_department_grants_and_uses_role_grants():
    module_access = {
        "sample_review": {
            "permissions": ["view", "ai_query"],
            "action_keys": ["sample_review.query"],
            "page_access": {},
        }
    }
    role_grant = SimpleNamespace(
        deleted_at=None, scope_type="role", scope_id="role-1",
        permissions=["view"], module_keys=["sample_review"], module_access=module_access,
    )
    department_grant = SimpleNamespace(
        deleted_at=None, scope_type="department", scope_id="department-1",
        permissions=["view", "ai_delete"], module_keys=["sample_review"], module_access=module_access,
    )
    application = SimpleNamespace(
        is_active=True,
        deleted_at=None,
        grants=[department_grant, role_grant],
        integration=SimpleNamespace(
            protocol_version=2,
            manifest={"contractRevision": "2.4", "modules": []},
        ),
    )

    assert service.effective_module_permissions(
        application, _current_user(), "sample_review"
    ) == {"view", "ai_query"}


def test_page_ai_gate_does_not_remove_employee_action_allowlist():
    grant = SimpleNamespace(
        deleted_at=None,
        scope_type="role",
        scope_id="role-1",
        permissions=["view", "ai_update"],
        module_keys=["sample_review"],
        module_access={
            "sample_review": {
                "permissions": ["view", "ai_update"],
                "action_keys": ["sample_review.update"],
                "page_access": {
                    "sample_review.detail": {
                        "permissions": ["view", "ai_update"],
                        "action_keys": ["sample_review.update"],
                        "ai_enabled": False,
                    },
                },
            },
        },
    )
    application = SimpleNamespace(
        is_active=True,
        deleted_at=None,
        grants=[grant],
        integration=SimpleNamespace(
            protocol_version=2,
            manifest={"contractRevision": "2.4", "modules": []},
        ),
    )

    claims = service.effective_module_claims(
        application, _current_user(), "sample_review"
    )
    assert claims["page_access"]["sample_review.detail"]["action_keys"] == [
        "sample_review.update"
    ]
    assert service.action_allowed_for_user(
        application,
        _current_user(),
        "sample_review",
        "sample_review.detail",
        "sample_review.update",
        "ai_update",
    ) is False


def test_existing_page_grant_without_ai_gate_remains_ai_compatible():
    grant = SimpleNamespace(
        deleted_at=None,
        scope_type="role",
        scope_id="role-1",
        permissions=["view", "ai_query"],
        module_keys=["sample_review"],
        module_access={
            "sample_review": {
                "permissions": ["view", "ai_query"],
                "action_keys": ["sample_review.query"],
                "page_access": {
                    "sample_review.list": {
                        "permissions": ["view", "ai_query"],
                        "action_keys": ["sample_review.query"],
                    },
                },
            },
        },
    )
    application = SimpleNamespace(
        is_active=True,
        deleted_at=None,
        grants=[grant],
        integration=SimpleNamespace(
            protocol_version=2,
            manifest={"contractRevision": "2.4", "modules": []},
        ),
    )

    assert service.action_allowed_for_user(
        application,
        _current_user(),
        "sample_review",
        "sample_review.list",
        "sample_review.query",
        "ai_query",
    ) is True


def test_legacy_view_grant_becomes_manifest_scoped_read_only_claims(monkeypatch):
    grant = SimpleNamespace(
        deleted_at=None,
        scope_type="department",
        scope_id="department-1",
        permissions=["view"],
        module_keys=[],
        module_access={},
    )
    application = SimpleNamespace(
        is_active=True,
        deleted_at=None,
        grants=[grant],
        integration=SimpleNamespace(
            protocol_version=2,
            manifest={
                "modules": [{
                    "moduleKey": "chair_catalog",
                    "pages": [
                        {
                            "pageKey": "chair_catalog.list",
                            "queryActionKey": "chair_catalog.view",
                            "actionKeys": ["chair_catalog.view", "chair_catalog.delete"],
                        },
                        {
                            "pageKey": "chair_catalog.overview",
                            "queryActionKey": "chair_catalog.view",
                            "actionKeys": ["chair_catalog.view"],
                        },
                    ],
                }],
            },
        ),
    )
    monkeypatch.setattr(
        service.scope_service,
        "effective_scope_set",
        lambda _user: [("department", "department-1")],
    )

    assert service.effective_module_claims(
        application, _current_user(), "chair_catalog"
    ) == {
        "permissions": ["view"],
        "action_keys": ["chair_catalog.view"],
        "page_access": {
            "chair_catalog.list": {
                "permissions": ["view"],
                "action_keys": ["chair_catalog.view"],
            },
            "chair_catalog.overview": {
                "permissions": ["view"],
                "action_keys": ["chair_catalog.view"],
            },
        },
    }
