from types import SimpleNamespace

import pytest

from app.auth.user_auth import CurrentUser
from app.models.department import Department
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace
from app.services import scope_service, workspace_permission_service


@pytest.fixture(autouse=True)
def db_engine():
    """These capability tests are intentionally database-free."""
    yield


def test_role_workspace_codes_add_cross_department_visibility() -> None:
    cu = SimpleNamespace(
        id="user-1",
        organization_id="org-1",
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
        SimpleNamespace(
            organization_id="org-1", deleted_at=None,
            scope_type="department", scope_id="department-design",
        ), cu,
    )
    assert scope_service.is_workspace_visible(
        SimpleNamespace(
            organization_id="org-1", deleted_at=None,
            scope_type="department", scope_id="department-production",
        ), cu,
    )
    assert not scope_service.is_workspace_visible(
        SimpleNamespace(
            organization_id="org-1", deleted_at=None,
            scope_type="department", scope_id="department-finance",
        ), cu,
    )


@pytest.mark.asyncio
async def test_wildcard_role_grants_department_update_but_never_shared_delete() -> None:
    cu = SimpleNamespace(
        id="user-1", organization_id="org-1", department_id="home",
        team_id=None, permission_codes=("*",),
    )
    workspace = SimpleNamespace(
        organization_id="org-1", deleted_at=None, scope_type="department",
        scope_id="finance",
    )

    assert scope_service.is_workspace_visible(workspace, cu)
    assert await workspace_permission_service.capabilities(None, workspace, cu) == {
        "read": True, "create": True, "update": True, "delete": False,
        "manage": True, "publish": False,
    }


@pytest.mark.asyncio
async def test_department_membership_is_read_only_and_roles_are_unioned() -> None:
    cu = SimpleNamespace(
        id="user-1",
        organization_id="organization-1",
        department_id="department-home",
        team_id=None,
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
        "read": True, "create": False, "update": False, "delete": False,
        "manage": False, "publish": False,
    }
    assert await workspace_permission_service.capabilities(None, workspace("department-design"), cu) == {
        "read": True, "create": False, "update": False, "delete": False,
        "manage": False, "publish": False,
    }
    assert await workspace_permission_service.capabilities(None, workspace("department-production"), cu) == {
        "read": True, "create": True, "update": True, "delete": False,
        "manage": True, "publish": False,
    }


@pytest.mark.asyncio
async def test_generic_data_scope_does_not_expand_workspace_visibility(db_session) -> None:
    org = Organization(name="Role matrix", slug="role-matrix")
    db_session.add(org)
    await db_session.flush()
    home = Department(organization_id=org.id, name="Home", slug="home")
    other = Department(organization_id=org.id, name="Other", slug="other")
    user = User(organization_id=org.id, username="role-matrix-user", role="member", is_active=True)
    db_session.add_all([home, other, user])
    await db_session.flush()
    user.department_id = home.id
    home_ws = Workspace(
        organization_id=org.id, name="Home", slug="home-ws",
        scope_type="department", scope_id=str(home.id),
    )
    other_ws = Workspace(
        organization_id=org.id, name="Other", slug="other-ws",
        scope_type="department", scope_id=str(other.id),
    )
    db_session.add_all([home_ws, other_ws])
    await db_session.flush()
    cu = CurrentUser(
        user=user, id=str(user.id), email=user.username, role=user.role,
        organization_id=org.id, department_id=str(home.id),
        effective_data_scopes={"unrestricted": True},
    )

    visible = await scope_service.list_workspaces_for_user(db_session, cu)

    assert {str(item.id) for item in visible} == {str(home_ws.id)}
