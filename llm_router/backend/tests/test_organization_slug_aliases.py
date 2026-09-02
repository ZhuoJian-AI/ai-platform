"""Regression coverage for canonical organization slugs and legacy aliases."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.models.admin import Admin
from app.models.user import User


async def _create_org(client: AsyncClient, *, name: str, slug: str) -> dict:
    response = await client.post(
        "/api/v1/organizations",
        json={"name": name, "slug": slug},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_renamed_slug_remains_an_alias_and_returns_canonical_slug(
    client: AsyncClient,
):
    organization = await _create_org(client, name="爱法贝", slug="aifabei")

    renamed = await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"slug": "alphabet"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["slug"] == "alphabet"

    canonical = await client.get("/api/v1/auth/org-info/alphabet")
    alias = await client.get("/api/v1/auth/org-info/aifabei")
    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert canonical.json() == {"name": "爱法贝", "slug": "alphabet"}
    assert alias.json() == canonical.json()


@pytest.mark.asyncio
async def test_slug_alias_cannot_be_claimed_by_another_organization(
    client: AsyncClient,
):
    organization = await _create_org(client, name="原组织", slug="legacy-name")
    renamed = await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"slug": "current-name"},
    )
    assert renamed.status_code == 200

    create_conflict = await client.post(
        "/api/v1/organizations",
        json={"name": "新组织", "slug": "legacy-name"},
    )
    assert create_conflict.status_code == 409

    other = await _create_org(client, name="另一个组织", slug="other-name")
    update_conflict = await client.patch(
        f"/api/v1/organizations/{other['id']}",
        json={"slug": "legacy-name"},
    )
    assert update_conflict.status_code == 409


@pytest.mark.asyncio
async def test_organization_can_promote_its_own_alias_back_to_canonical(
    client: AsyncClient,
):
    organization = await _create_org(client, name="往返组织", slug="first-name")
    first_rename = await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"slug": "second-name"},
    )
    assert first_rename.status_code == 200

    rename_back = await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"slug": "first-name"},
    )
    assert rename_back.status_code == 200, rename_back.text
    assert rename_back.json()["slug"] == "first-name"

    former_canonical = await client.get("/api/v1/auth/org-info/second-name")
    assert former_canonical.status_code == 200
    assert former_canonical.json()["slug"] == "first-name"


@pytest.mark.asyncio
async def test_admin_and_user_login_accept_legacy_slug_and_return_canonical_identity(
    client: AsyncClient,
    db_session: AsyncSession,
):
    organization = await _create_org(client, name="登录组织", slug="legacy-login")
    renamed = await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"slug": "canonical-login"},
    )
    assert renamed.status_code == 200
    organization_id = UUID(organization["id"])

    db_session.add_all(
        [
            Admin(
                username="alias-admin",
                password_hash=hash_password("admin-password"),
                role="org_admin",
                organization_id=organization_id,
                is_active=True,
            ),
            User(
                organization_id=organization_id,
                username="alias-user",
                display_name="Alias User",
                role="member",
                password_hash=hash_password("user-password"),
                is_active=True,
            ),
        ]
    )
    await db_session.flush()

    admin_login = await client.post(
        "/api/v1/auth/login",
        json={
            "slug": "legacy-login",
            "username": "alias-admin",
            "password": "admin-password",
        },
    )
    assert admin_login.status_code == 200, admin_login.text
    assert admin_login.json()["admin"]["organization_slug"] == "canonical-login"

    user_login = await client.post(
        "/api/v1/users/login-by-slug",
        json={
            "slug": "legacy-login",
            "username": "alias-user",
            "password": "user-password",
        },
    )
    assert user_login.status_code == 200, user_login.text
    assert user_login.json()["user"]["organization_id"] == organization["id"]
