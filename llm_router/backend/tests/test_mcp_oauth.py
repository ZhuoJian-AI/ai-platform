"""OAuth/MCP tenant-bound authorization and one-time credential tests."""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.session_cookies import user_session_cookie_name
from app.models.api_key import ApiKey

INITIAL_PASSWORD = "oauth-test-pass"
ACTIVE_PASSWORD = "oauth-ready-pass"


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


async def _create_employee(client: AsyncClient) -> tuple[str, str]:
    organization = await client.post(
        "/api/v1/organizations",
        json={"name": "OAuth 企业", "slug": "oauth-enterprise"},
    )
    assert organization.status_code == 201
    organization_id = organization.json()["id"]
    user = await client.post(
        f"/api/v1/organizations/{organization_id}/users",
        json={"username": "oauth-user", "password": INITIAL_PASSWORD, "role": "member"},
    )
    assert user.status_code == 201
    login = await client.post(
        "/api/v1/users/login",
        json={
            "organization_id": organization_id,
            "username": "oauth-user",
            "password": INITIAL_PASSWORD,
        },
    )
    assert login.status_code == 200
    changed = await client.post(
        "/api/v1/users/change-password",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"old_password": INITIAL_PASSWORD, "new_password": ACTIVE_PASSWORD},
    )
    assert changed.status_code == 200, changed.text
    client.cookies.delete(user_session_cookie_name())
    return organization_id, user.json()["id"]


@pytest.mark.asyncio
async def test_oauth_authorization_code_pkce_and_refresh_replay_family_revocation(client: AsyncClient):
    organization_id, _ = await _create_employee(client)
    callback = "http://127.0.0.1:9876/callback"
    registration = await client.post(
        "/api/v1/oauth/register",
        json={
            "client_name": "Codex test client",
            "redirect_uris": [callback],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert registration.status_code == 200
    client_id = registration.json()["client_id"]
    resource = f"http://test/mcp/organizations/{organization_id}"
    verifier = "v" * 64
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": callback,
        "code_challenge": _challenge(verifier),
        "code_challenge_method": "S256",
        "resource": resource,
        "scope": "mcp:tools",
        "state": "state-123",
    }

    login_page = await client.get("/api/v1/oauth/authorize", params=params)
    assert login_page.status_code == 200
    assert "普通员工账号" in login_page.text
    csrf = client.cookies.get("ai_infra_oauth_csrf")
    assert csrf

    approved = await client.post(
        "/api/v1/oauth/authorize",
        data={**params, "csrf_token": csrf, "username": "oauth-user", "password": ACTIVE_PASSWORD},
        follow_redirects=False,
    )
    assert approved.status_code == 302
    redirect = urlparse(approved.headers["location"])
    values = parse_qs(redirect.query)
    assert values["state"] == ["state-123"]
    code = values["code"][0]

    exchanged = await client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": callback,
            "code_verifier": verifier,
            "resource": resource,
        },
    )
    assert exchanged.status_code == 200
    first_refresh = exchanged.json()["refresh_token"]
    assert exchanged.json()["scope"] == "mcp:tools"

    rotated = await client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": first_refresh,
            "resource": resource,
        },
    )
    assert rotated.status_code == 200
    second_refresh = rotated.json()["refresh_token"]
    assert second_refresh != first_refresh

    replay = await client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": first_refresh,
            "resource": resource,
        },
    )
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"

    family_revoked = await client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": second_refresh,
            "resource": resource,
        },
    )
    assert family_revoked.status_code == 400


@pytest.mark.asyncio
async def test_api_key_plaintext_is_returned_once_and_not_reversibly_stored(
    client: AsyncClient, db_session,
):
    organization_id, _ = await _create_employee(client)
    created = await client.post(
        f"/api/v1/organizations/{organization_id}/api-keys",
        json={"key_name": "one-time", "scope_type": "organization"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["key"].startswith(body["key_prefix"])
    assert "key_plain" not in body

    listed = await client.get(f"/api/v1/organizations/{organization_id}/api-keys")
    assert listed.status_code == 200
    assert "key" not in listed.json()[0]
    assert "key_plain" not in listed.json()[0]

    record = (await db_session.execute(select(ApiKey).where(ApiKey.id == body["id"]))).scalar_one()
    assert record.key_encrypted == ""


@pytest.mark.asyncio
async def test_protected_resource_metadata_is_tenant_specific(client: AsyncClient):
    organization_id, _ = await _create_employee(client)
    response = await client.get(
        f"/.well-known/oauth-protected-resource/mcp/organizations/{organization_id}"
    )
    assert response.status_code == 200
    assert response.json()["resource"] == f"http://test/mcp/organizations/{organization_id}"
    assert response.json()["scopes_supported"] == ["mcp:tools"]
