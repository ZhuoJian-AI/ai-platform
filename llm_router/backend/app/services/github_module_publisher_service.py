"""Create tenant-prefixed repositories with a centrally held GitHub App key."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from app.config import settings


class ModulePublisherError(RuntimeError):
    """Safe publisher failure that never includes credentials."""


@dataclass(frozen=True)
class ProvisionedRepository:
    owner: str
    repository_name: str
    clone_url: str
    access_token: str
    expires_at: datetime
    created: bool


def repository_name(organization_slug: str, module_slug: str) -> str:
    prefix = f"{organization_slug}-"
    if module_slug == organization_slug or module_slug.startswith(prefix):
        raise ModulePublisherError("module_slug must not repeat the organization prefix")
    return f"{organization_slug}-{module_slug}"


def _private_key() -> str:
    try:
        return base64.b64decode(
            settings.github_module_publisher_private_key_b64,
            validate=True,
        ).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ModulePublisherError("GitHub module publisher private key is invalid") from exc


def _app_jwt(now: datetime | None = None) -> str:
    issued_at = now or datetime.now(UTC)
    payload = {
        "iat": int((issued_at - timedelta(seconds=60)).timestamp()),
        "exp": int((issued_at + timedelta(minutes=9)).timestamp()),
        "iss": settings.github_module_publisher_app_id,
    }
    return jwt.encode(payload, _private_key(), algorithm="RS256")


def _github_error(response: httpx.Response, action: str) -> ModulePublisherError:
    request_id = response.headers.get("x-github-request-id")
    suffix = f" (request {request_id})" if request_id else ""
    return ModulePublisherError(f"GitHub {action} failed with HTTP {response.status_code}{suffix}")


async def _installation_token(
    client: httpx.AsyncClient,
    app_jwt: str,
    *,
    repository_id: int | None = None,
) -> tuple[str, datetime]:
    body: dict[str, Any] = {
        "permissions": {"contents": "write", "metadata": "read"},
    }
    if repository_id is None:
        body["permissions"]["administration"] = "write"
    else:
        body["repository_ids"] = [repository_id]
    response = await client.post(
        f"/app/installations/{settings.github_module_publisher_installation_id}/access_tokens",
        headers={"authorization": f"Bearer {app_jwt}"},
        json=body,
    )
    if response.status_code != 201:
        raise _github_error(response, "installation token")
    payload = response.json()
    try:
        expires_at = datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00"))
        return str(payload["token"]), expires_at
    except (KeyError, TypeError, ValueError) as exc:
        raise ModulePublisherError("GitHub installation token response is incomplete") from exc


async def provision_repository(
    organization_slug: str,
    organization_name: str,
    module_slug: str,
    module_name: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProvisionedRepository:
    if not settings.github_module_publisher_configured:
        raise ModulePublisherError("GitHub module publisher is not configured")
    owner = settings.github_module_publisher_owner.strip()
    name = repository_name(organization_slug, module_slug)
    headers = {
        "accept": "application/vnd.github+json",
        "x-github-api-version": "2026-03-10",
        "user-agent": "ZhuoJian-Module-Publisher/1.0",
    }
    timeout = httpx.Timeout(settings.github_module_publisher_timeout_seconds)
    try:
        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=headers,
            timeout=timeout,
            transport=transport,
        ) as client:
            app_jwt = _app_jwt()
            broad_token, _ = await _installation_token(client, app_jwt)
            auth_headers = {"authorization": f"Bearer {broad_token}"}
            response = await client.get(f"/repos/{owner}/{name}", headers=auth_headers)
            created = False
            if response.status_code == 404:
                response = await client.post(
                    f"/orgs/{owner}/repos",
                    headers=auth_headers,
                    json={
                        "name": name,
                        "description": f"{organization_name} · {module_name} · 灼见原生模块",
                        "private": True,
                        "has_issues": True,
                        "has_projects": False,
                        "has_wiki": False,
                        "auto_init": False,
                    },
                )
                if response.status_code != 201:
                    raise _github_error(response, "repository creation")
                created = True
            elif response.status_code != 200:
                raise _github_error(response, "repository lookup")
            repository = response.json()
            if not bool(repository.get("private")):
                raise ModulePublisherError("Refusing to publish enterprise code to a public repository")
            try:
                repository_id = int(repository["id"])
                clone_url = str(repository["clone_url"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ModulePublisherError("GitHub repository response is incomplete") from exc
            topics = [
                f"company-{organization_slug}",
                "zhuojian-native-module",
                "contract-v2",
            ]
            if "coldstart" in module_slug.split("-"):
                topics.append("acceptance-test")
            response = await client.put(
                f"/repos/{owner}/{name}/topics",
                headers=auth_headers,
                json={"names": topics},
            )
            if response.status_code != 200:
                raise _github_error(response, "repository topic update")
            scoped_token, expires_at = await _installation_token(
                client,
                app_jwt,
                repository_id=repository_id,
            )
            return ProvisionedRepository(
                owner=owner,
                repository_name=name,
                clone_url=clone_url,
                access_token=scoped_token,
                expires_at=expires_at,
                created=created,
            )
    except httpx.HTTPError as exc:
        raise ModulePublisherError("GitHub module publisher is temporarily unavailable") from exc
