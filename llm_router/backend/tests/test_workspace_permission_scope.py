from types import SimpleNamespace

import pytest

from app.services import scope_service, workspace_permission_service


@pytest.fixture(autouse=True)
def db_engine():
    """These capability tests are intentionally database-free."""
    yield


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


@pytest.mark.asyncio
async def test_department_membership_is_read_only_and_roles_are_unioned() -> None:
    cu = SimpleNamespace(
        id="user-1",
        organization_id="organization-1",
        department_id="department-home",
        team_id=None,
        # The authentication layer has already unioned all assigned roles into
        # permission_codes. Both department permissions must remain effective.
        permission_codes=(
            "workspace.department.read:department-design",
            "workspace.department.upload:department-production",
        ),
    )

    def workspace(scope_id: str):
        return SimpleNamespace(
            organization_id="organization-1",
            scope_type="department",
            scope_id=scope_id,
            deleted_at=None,
        )

    assert await workspace_permission_service.capabilities(None, workspace("department-home"), cu) == {
        "read": True, "create": False, "manage": False, "publish": False,
    }
    assert await workspace_permission_service.capabilities(None, workspace("department-design"), cu) == {
        "read": True, "create": False, "manage": False, "publish": False,
    }
    assert await workspace_permission_service.capabilities(None, workspace("department-production"), cu) == {
        "read": True, "create": True, "manage": True, "publish": False,
    }
