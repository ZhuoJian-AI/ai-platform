"""Regression tests for role activation lifecycle safeguards."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import Role


async def _make_org(client: AsyncClient, slug: str) -> str:
    response = await client.post(
        "/api/v1/organizations",
        json={"name": f"公司-{slug}", "slug": slug},
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_builtin_roles_cannot_be_disabled_and_legacy_disabled_role_is_repaired(
    client: AsyncClient,
    db_session: AsyncSession,
):
    org_id = await _make_org(client, "builtin-role-guard-org")
    listed = await client.get(f"/api/v1/organizations/{org_id}/roles")
    assert listed.status_code == 200
    employee = next(role for role in listed.json() if role["code"] == "employee")

    role = await db_session.get(Role, UUID(employee["id"]))
    assert role is not None
    role.is_active = False
    await db_session.flush()

    repaired = await client.get(f"/api/v1/organizations/{org_id}/roles")
    assert repaired.status_code == 200
    repaired_employee = next(role for role in repaired.json() if role["code"] == "employee")
    assert repaired_employee["is_active"] is True

    rejected = await client.patch(
        f"/api/v1/roles/{employee['id']}",
        json={"is_active": False},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "内置角色不能停用"


@pytest.mark.asyncio
async def test_assigned_custom_role_must_be_unassigned_before_it_can_be_disabled(
    client: AsyncClient,
):
    org_id = await _make_org(client, "assigned-role-guard-org")
    custom = await client.post(
        f"/api/v1/organizations/{org_id}/roles",
        json={"name": "质量审批员", "code": "quality_approver"},
    )
    assert custom.status_code == 201
    role_id = custom.json()["id"]

    user = await client.post(
        f"/api/v1/organizations/{org_id}/users",
        json={
            "username": "quality-member",
            "password": "test-pass-123",
            "role_ids": [role_id],
        },
    )
    assert user.status_code == 201

    rejected = await client.patch(
        f"/api/v1/roles/{role_id}",
        json={"is_active": False},
    )
    assert rejected.status_code == 409
    assert "1 名在职员工" in rejected.json()["detail"]

    unassigned = await client.put(
        f"/api/v1/users/{user.json()['id']}/roles",
        json={"role_ids": []},
    )
    assert unassigned.status_code == 200

    disabled = await client.patch(
        f"/api/v1/roles/{role_id}",
        json={"is_active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
