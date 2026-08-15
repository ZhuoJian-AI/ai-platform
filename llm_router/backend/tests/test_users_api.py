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
