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
