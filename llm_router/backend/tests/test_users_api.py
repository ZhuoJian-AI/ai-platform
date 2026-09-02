"""Tests for org-scoped user management API."""

import pytest
from httpx import AsyncClient


async def _make_org(client: AsyncClient, slug: str = "user-org") -> str:
    resp = await client.post(
        "/api/v1/organizations",
        json={"name": f"公司-{slug}", "slug": slug},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _make_department(client: AsyncClient, org_id: str, name: str, slug: str) -> str:
    resp = await client.post(
        f"/api/v1/organizations/{org_id}/departments",
        json={"name": name, "slug": slug},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_create_user(client: AsyncClient):
    org_id = await _make_org(client)
    resp = await client.post(
        f"/api/v1/organizations/{org_id}/users",
        json={
            "username": "alice",
            "password": "test-pass-123",
            "display_name": "Alice",
            "role": "member",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "alice"
    assert data["role"] == "member"
    assert data["organization_id"] == org_id


@pytest.mark.asyncio
async def test_create_user_duplicate_username(client: AsyncClient):
    org_id = await _make_org(client, slug="dup-org")
    payload = {"username": "bob", "password": "test-pass-123", "role": "member"}
    r1 = await client.post(f"/api/v1/organizations/{org_id}/users", json=payload)
    assert r1.status_code == 201
    r2 = await client.post(f"/api/v1/organizations/{org_id}/users", json=payload)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_deleted_username_can_be_reused(client: AsyncClient):
    org_id = await _make_org(client, slug="reuse-deleted-username-org")
    payload = {"username": "reusable", "password": "test-pass-123", "role": "member"}

    created = await client.post(f"/api/v1/organizations/{org_id}/users", json=payload)
    assert created.status_code == 201
    original_id = created.json()["id"]
    assert (await client.delete(f"/api/v1/users/{original_id}")).status_code == 204

    recreated = await client.post(f"/api/v1/organizations/{org_id}/users", json=payload)
    assert recreated.status_code == 201
    assert recreated.json()["id"] != original_id
    assert recreated.json()["username"] == "reusable"


@pytest.mark.asyncio
async def test_user_belongs_to_one_department(client: AsyncClient):
    org_id = await _make_org(client, slug="single-dept-org")
    sales_id = await _make_department(client, org_id, "销售部", "sales")
    finance_id = await _make_department(client, org_id, "财务部", "finance")

    rejected = await client.post(
        f"/api/v1/organizations/{org_id}/users",
        json={
            "username": "invalid-multi-member",
            "password": "test-pass-123",
            "role": "member",
            "department_ids": [sales_id, finance_id],
            "department_id": finance_id,
        },
    )
    assert rejected.status_code == 422

    created = await client.post(
        f"/api/v1/organizations/{org_id}/users",
        json={
            "username": "single-dept-member",
            "password": "test-pass-123",
            "role": "member",
            "department_id": finance_id,
            "manager_scopes": [
                {"scope_type": "department", "scope_id": finance_id},
            ],
        },
    )
    assert created.status_code == 201
    data = created.json()
    assert data["department_id"] == finance_id
    assert data["department_ids"] == [finance_id]
    assert [item["scope_id"] for item in data["manager_scopes"]] == [finance_id]

    user_id = data["id"]
    updated = await client.patch(
        f"/api/v1/users/{user_id}",
        json={
            "department_ids": [sales_id],
            "department_id": sales_id,
            "manager_scopes": [{"scope_type": "department", "scope_id": sales_id}],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["department_id"] == sales_id
    assert updated.json()["department_ids"] == [sales_id]
    assert [item["scope_id"] for item in updated.json()["manager_scopes"]] == [sales_id]

    mismatched = await client.patch(
        f"/api/v1/users/{user_id}",
        json={"department_ids": [finance_id], "department_id": sales_id},
    )
    assert mismatched.status_code == 422


@pytest.mark.asyncio
async def test_department_and_team_cannot_be_deleted_while_they_have_active_members(
    client: AsyncClient,
):
    org_id = await _make_org(client, slug="delete-membership-guard-org")
    source_id = await _make_department(client, org_id, "设计部", "design")
    target_id = await _make_department(client, org_id, "生产部", "production")
    team = await client.post(
        f"/api/v1/departments/{source_id}/teams",
        json={"name": "产品设计组", "slug": "product-design"},
    )
    assert team.status_code == 201
    team_id = team.json()["id"]
    user = await client.post(
        f"/api/v1/organizations/{org_id}/users",
        json={
            "username": "department-member",
            "password": "test-pass-123",
            "department_id": source_id,
            "team_id": team_id,
        },
    )
    assert user.status_code == 201

    rejected_team = await client.delete(f"/api/v1/teams/{team_id}")
    assert rejected_team.status_code == 409
    assert "1 名员工" in rejected_team.json()["detail"]

    rejected_department = await client.delete(f"/api/v1/departments/{source_id}")
    assert rejected_department.status_code == 409
    assert "1 名员工" in rejected_department.json()["detail"]
    assert "1 个团队" in rejected_department.json()["detail"]

    moved = await client.patch(
        f"/api/v1/users/{user.json()['id']}",
        json={
            "department_ids": [target_id],
            "department_id": target_id,
            "team_id": None,
        },
    )
    assert moved.status_code == 200
    assert (await client.delete(f"/api/v1/teams/{team_id}")).status_code == 204
    assert (await client.delete(f"/api/v1/departments/{source_id}")).status_code == 204


@pytest.mark.asyncio
async def test_department_cannot_be_deleted_while_it_has_active_children(client: AsyncClient):
    org_id = await _make_org(client, slug="delete-child-guard-org")
    parent_id = await _make_department(client, org_id, "事业部", "division")
    child = await client.post(
        f"/api/v1/organizations/{org_id}/departments",
        json={"name": "设计部", "slug": "design", "parent_id": parent_id},
    )
    assert child.status_code == 201

    rejected = await client.delete(f"/api/v1/departments/{parent_id}")
    assert rejected.status_code == 409
    assert "1 个下级部门" in rejected.json()["detail"]

    assert (await client.delete(f"/api/v1/departments/{child.json()['id']}")).status_code == 204
    assert (await client.delete(f"/api/v1/departments/{parent_id}")).status_code == 204


@pytest.mark.asyncio
async def test_list_update_delete_user(client: AsyncClient):
    org_id = await _make_org(client, slug="crud-org")
    create = await client.post(
        f"/api/v1/organizations/{org_id}/users",
        json={"username": "carol", "password": "test-pass-123", "role": "member"},
    )
    assert create.status_code == 201
    user_id = create.json()["id"]

    # list
    listed = await client.get(f"/api/v1/organizations/{org_id}/users")
    assert listed.status_code == 200
    assert any(u["id"] == user_id for u in listed.json())

    # update
    upd = await client.patch(
        f"/api/v1/users/{user_id}",
        json={"role": "admin", "display_name": "Carol"},
    )
    assert upd.status_code == 200
    assert upd.json()["role"] == "admin"
    assert upd.json()["display_name"] == "Carol"

    # delete
    dele = await client.delete(f"/api/v1/users/{user_id}")
    assert dele.status_code == 204
    after = await client.get(f"/api/v1/users/{user_id}")
    assert after.status_code == 404
