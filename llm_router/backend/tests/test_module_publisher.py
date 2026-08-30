"""Tests for tenant-scoped GitHub module publishing."""

from datetime import UTC, datetime

import httpx
import pytest

from app.config import settings
from app.services import github_module_publisher_service as service


@pytest.fixture
def configured_publisher(monkeypatch):
    monkeypatch.setattr(settings, "github_module_publisher_enabled", True)
    monkeypatch.setattr(settings, "github_module_publisher_owner", "ZhuoJian-AI")
    monkeypatch.setattr(settings, "github_module_publisher_app_id", "123")
    monkeypatch.setattr(settings, "github_module_publisher_installation_id", "456")
    monkeypatch.setattr(settings, "github_module_publisher_private_key_b64", "configured-in-test")
    monkeypatch.setattr(service, "_app_jwt", lambda: "signed-app-jwt")


def test_repository_name_adds_company_once():
    assert service.repository_name("aifabei", "sample-review") == "aifabei-sample-review"
    with pytest.raises(service.ModulePublisherError, match="must not repeat"):
        service.repository_name("aifabei", "aifabei-sample-review")


async def test_provision_repository_creates_private_repo_and_returns_scoped_token(configured_publisher):
    requests: list[httpx.Request] = []
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        requests.append(request)
        if request.url.path == "/app/installations/456/access_tokens":
            token_calls += 1
            token = "broad-token" if token_calls == 1 else "repo-scoped-token"
            return httpx.Response(
                201,
                json={"token": token, "expires_at": "2026-08-30T16:00:00Z"},
            )
        if request.method == "GET" and request.url.path == "/repos/ZhuoJian-AI/aifabei-sample-review":
            return httpx.Response(404, json={"message": "Not Found"})
        if request.method == "POST" and request.url.path == "/orgs/ZhuoJian-AI/repos":
            return httpx.Response(
                201,
                json={
                    "id": 99,
                    "private": True,
                    "clone_url": "https://github.com/ZhuoJian-AI/aifabei-sample-review.git",
                },
            )
        if request.method == "PUT" and request.url.path == "/repos/ZhuoJian-AI/aifabei-sample-review/topics":
            return httpx.Response(200, json={"names": []})
        return httpx.Response(500, json={"message": "unexpected"})

    result = await service.provision_repository(
        "aifabei",
        "爱法贝",
        "sample-review",
        "样品评审",
        transport=httpx.MockTransport(handler),
    )

    assert result.created is True
    assert result.repository_name == "aifabei-sample-review"
    assert result.access_token == "repo-scoped-token"
    assert result.expires_at == datetime(2026, 8, 30, 16, 0, tzinfo=UTC)
    assert token_calls == 2
    creation = next(request for request in requests if request.url.path == "/orgs/ZhuoJian-AI/repos")
    assert b'"private":true' in creation.content
    scoped = [request for request in requests if request.url.path.endswith("/access_tokens")][1]
    assert b'"repository_ids":[99]' in scoped.content
    assert b'"administration"' not in scoped.content
    topic_update = next(request for request in requests if request.url.path.endswith("/topics"))
    assert b'"company-aifabei"' in topic_update.content
    assert b'"zhuojian-native-module"' in topic_update.content


async def test_provision_repository_refuses_existing_public_repo(configured_publisher):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/app/installations/456/access_tokens":
            return httpx.Response(
                201,
                json={"token": "broad-token", "expires_at": "2026-08-30T16:00:00Z"},
            )
        return httpx.Response(
            200,
            json={"id": 99, "private": False, "clone_url": "https://example.invalid/repo.git"},
        )

    with pytest.raises(service.ModulePublisherError, match="public repository"):
        await service.provision_repository(
            "aifabei",
            "爱法贝",
            "sample-review",
            "样品评审",
            transport=httpx.MockTransport(handler),
        )
