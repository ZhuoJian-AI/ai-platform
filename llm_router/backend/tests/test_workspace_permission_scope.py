from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.auth.user_auth import CurrentUser
from app.models.department import Department
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace
from app.services import scope_service, workspace_permission_service


@pytest.mark.asyncio
@pytest.mark.parametrize("other_tenant", [False, True])
async def test_workspace_denial_is_chinese_and_hides_other_tenants(other_tenant) -> None:
    cu = SimpleNamespace(id="u", organization_id="org", permission_codes=())
    workspace = SimpleNamespace(
        organization_id="other" if other_tenant else "org",
        scope_type="organization", scope_id=None, deleted_at=None,
    )
    with pytest.raises(HTTPException) as caught:
        await workspace_permission_service.assert_can_read(None, workspace, cu)
    assert caught.value.status_code == (404 if other_tenant else 403)
    assert caught.value.detail == (
        "工作空间不存在" if other_tenant else "当前角色没有该工作空间的读取权限"
    )


def test_role_workspace_codes_add_cross_department_visibility() -> None:
    cu = SimpleNamespace(
        id="user-1",
        organization_id="org-1",
        department_id="department-home",
        department_ids=("department-home",),
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
        permission_codes=("*",),
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

    organization_workspace = SimpleNamespace(
        organization_id="org-1", deleted_at=None, scope_type="organization",
        scope_id=None,
    )
    assert await workspace_permission_service.capabilities(None, organization_workspace, cu) == {
        "read": True, "create": True, "update": True, "delete": True,
        "manage": True, "publish": False,
    }


@pytest.mark.asyncio
async def test_company_workspace_management_requires_explicit_role_permission() -> None:
    cu = SimpleNamespace(
        id="user-1", organization_id="org-1", department_id="home",
        permission_codes=(workspace_permission_service.ORGANIZATION_MANAGE_PERMISSION,),
    )
    workspace = SimpleNamespace(
        organization_id="org-1", deleted_at=None, scope_type="organization",
        scope_id=None,
    )

    assert await workspace_permission_service.capabilities(None, workspace, cu) == {
        "read": True, "create": True, "update": True, "delete": True,
        "manage": True, "publish": False,
    }


@pytest.mark.asyncio
async def test_department_membership_grants_nothing_and_roles_are_unioned() -> None:
    cu = SimpleNamespace(
        id="user-1",
        organization_id="organization-1",
        department_id="department-home",
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
        "read": False, "create": False, "update": False, "delete": False,
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

    assert visible == []


@pytest.mark.asyncio
async def test_effective_access_omits_workspaces_with_no_capability(db_session) -> None:
    org = Organization(name="Capability catalog", slug="capability-catalog")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id, username="catalog-user", role="member", is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    readable = Workspace(
        organization_id=org.id, name="个人空间", slug="personal-catalog",
        scope_type="user", scope_id=str(user.id),
    )
    hidden = Workspace(
        organization_id=org.id, name="未授权秘密空间", slug="hidden-catalog",
        scope_type="unsupported", scope_id="retired-scope",
    )
    db_session.add_all([readable, hidden])
    await db_session.flush()
    cu = CurrentUser(
        user=user, id=str(user.id), email=user.username, role=user.role,
        organization_id=org.id,
    )

    access = await workspace_permission_service.effective_access(db_session, cu)

    assert [item["id"] for item in access["workspaces"]] == [str(readable.id)]
    assert "未授权秘密空间" not in str(access)


@pytest.mark.asyncio
async def test_effective_access_hides_company_workspace_without_role_grant(db_session) -> None:
    org = Organization(name="Public workspace tenant", slug="public-workspace-tenant")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id, username="public-workspace-user", role="member", is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    public = Workspace(
        organization_id=org.id, name="公司公共空间", slug="organization-public",
        scope_type="organization", scope_id=None,
    )
    db_session.add(public)
    await db_session.flush()
    cu = CurrentUser(
        user=user, id=str(user.id), email=user.username, role=user.role,
        organization_id=org.id,
    )

    access = await workspace_permission_service.effective_access(db_session, cu)

    assert access["workspaces"] == []


@pytest.mark.asyncio
async def test_company_read_role_is_read_only_and_revocation_removes_access() -> None:
    cu = SimpleNamespace(
        id="user-1", organization_id="org-1", department_id="home",
        permission_codes=(workspace_permission_service.ORGANIZATION_READ_PERMISSION,),
    )
    workspace = SimpleNamespace(
        organization_id="org-1", scope_type="organization", scope_id=None,
        deleted_at=None,
    )
    assert await workspace_permission_service.capabilities(None, workspace, cu) == {
        "read": True, "create": False, "update": False, "delete": False,
        "manage": False, "publish": False,
    }
    cu.permission_codes = ()
    assert not any((await workspace_permission_service.capabilities(None, workspace, cu)).values())
    assert workspace_permission_service.capability_sources(workspace, cu) == {}


@pytest.mark.asyncio
async def test_personal_ownership_survives_without_business_roles() -> None:
    cu = SimpleNamespace(id="user-1", organization_id="org-1", permission_codes=())
    workspace = SimpleNamespace(
        organization_id="org-1", scope_type="user", scope_id="user-1", deleted_at=None,
    )
    caps = await workspace_permission_service.capabilities(None, workspace, cu)
    assert all(caps[key] for key in ("read", "create", "update", "delete"))
    workspace.organization_id = "other-org"
    assert not any((await workspace_permission_service.capabilities(None, workspace, cu)).values())
