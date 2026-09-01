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
                    {"moduleKey": "sample_review", "name": "样品评审"},
                    {"moduleKey": "review_remediation", "name": "评审整改闭环"},
                    {"moduleKey": "sample_release_archive", "name": "样品放行与归档"},
                ],
            },
        ),
    )
    allowed = {"sample_review", "sample_release_archive"}
    monkeypatch.setattr(
        service,
        "effective_module_permissions",
        lambda _application, _user, module_key: {"view"} if module_key in allowed else {"query"},
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
