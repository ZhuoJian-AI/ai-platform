from types import SimpleNamespace

from app.services import scope_service, workspace_permission_service


def test_role_workspace_codes_add_cross_department_visibility() -> None:
    cu = SimpleNamespace(
        id="user-1",
        department_id="department-home",
        department_ids=("department-home",),
        team_id=None,
        role_ids=("role-1",),
        permission_codes=(
            "workspace.department.read:department-design",
            "workspace.department.upload:department-production",
        ),
        effective_data_scopes={},
    )

    assert workspace_permission_service.department_workspace_scope_ids(cu) == (
        "department-design",
        "department-production",
    )
    assert scope_service.is_workspace_visible(
        SimpleNamespace(scope_type="department", scope_id="department-design"), cu,
    )
    assert scope_service.is_workspace_visible(
        SimpleNamespace(scope_type="department", scope_id="department-production"), cu,
    )
    assert not scope_service.is_workspace_visible(
        SimpleNamespace(scope_type="department", scope_id="department-finance"), cu,
    )
