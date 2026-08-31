"""Tests for the scoped Coolify deployment control plane."""

import httpx
import pytest

from app.config import settings
from app.models.organization import Organization
from app.schemas.module_publisher import ModuleDeploymentRequest
from app.services import module_deployment_service
from app.services.coolify_module_client import (
    CoolifyModuleClient,
    classify_failure,
    redact_logs,
)


@pytest.fixture
def configured_deployer(monkeypatch):
    monkeypatch.setattr(settings, "coolify_module_deployer_enabled", True)
    monkeypatch.setattr(settings, "coolify_api_url", "https://coolify.example.com/api/v1")
    monkeypatch.setattr(settings, "coolify_api_token", "central-token")
    monkeypatch.setattr(settings, "github_module_publisher_owner", "ZhuoJian-AI")


async def test_coolify_client_configures_application_without_exposing_token(configured_deployer):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer central-token"
        path = request.url.path
        if request.method == "POST" and path.endswith("/applications/private-github-app"):
            return httpx.Response(201, json={"uuid": "app-1"})
        if request.method == "GET" and path.endswith("/applications/app-1/envs"):
            return httpx.Response(200, json=[])
        if request.method == "POST" and path.endswith("/applications/app-1/envs"):
            return httpx.Response(201, json={"uuid": "env-1"})
        if request.method == "GET" and path.endswith("/applications/app-1/storages"):
            return httpx.Response(200, json={"persistent_storages": [], "file_storages": []})
        if request.method == "POST" and path.endswith("/applications/app-1/storages"):
            return httpx.Response(201, json={})
        if request.method == "POST" and path.endswith("/deploy"):
            return httpx.Response(
                200,
                json={"deployments": [{"deployment_uuid": "deployment-1"}]},
            )
        return httpx.Response(500, json={"message": f"unexpected {request.method} {path}"})

    client = CoolifyModuleClient(transport=httpx.MockTransport(handler))
    target = module_deployment_service.CoolifyTarget(
        server_uuid="server-a",
        project_uuid="project-a",
        environment_name="production",
        environment_uuid=None,
        destination_uuid=None,
        github_app_uuid="github-source-a",
        use_build_server=False,
    )
    app_uuid = await client.create_application(
        target=target,
        repository="https://github.com/ZhuoJian-AI/aifabei-sample-review",
        name="aifabei-sample-review",
        domain="https://sample-review.aifabei.example.com",
        commit="a" * 40,
    )
    await client.set_envs(app_uuid, {"SESSION_SECRET": "secret-value"})
    await client.ensure_storage(app_uuid, "aifabei-sample-review-data")
    deployment_uuid = await client.deploy(app_uuid)

    assert deployment_uuid == "deployment-1"
    creation = requests[0]
    assert b'"server_uuid":"server-a"' in creation.content
    assert b'"health_check_enabled":false' in creation.content
    assert all(b"central-token" not in request.content for request in requests)


async def test_request_deployment_is_tenant_scoped_and_idempotent(
    configured_deployer, db_session
):
    organization = Organization(name="爱法贝", slug="aifabei", settings={})
    db_session.add(organization)
    await db_session.flush()
    await module_deployment_service.save_profile(
        db_session,
        organization.id,
        module_deployment_service.ModuleDeploymentProfileInput(
            server_uuid="server-a",
            project_uuid="project-a",
            environment_name="production",
            github_app_uuid="github-source-a",
            domain_suffix="aifabei.example.com",
        ),
    )

    class FakeCoolify:
        creates = 0
        deploys = 0
        configured_envs: dict[str, str] = {}

        async def create_application(self, **kwargs):
            self.creates += 1
            assert kwargs["target"].server_uuid == "server-a"
            assert kwargs["repository"].endswith("/aifabei-sample-review")
            return "coolify-app-a"

        async def update_release(self, *args, **kwargs):
            raise AssertionError("same healthy/active commit must be idempotent")

        async def set_envs(self, _uuid, values):
            self.configured_envs = values

        async def ensure_storage(self, _uuid, volume_name):
            assert volume_name == "zhuojian-aifabei-sample-review-data"

        async def deploy(self, _uuid):
            self.deploys += 1
            return "deployment-a"

    fake = FakeCoolify()
    request = ModuleDeploymentRequest(
        module_slug="sample-review",
        module_name="样品评审",
        repository_name="aifabei-sample-review",
        source_commit="a" * 40,
    )
    first = await module_deployment_service.request_deployment(
        db_session, organization, request, client=fake
    )
    second = await module_deployment_service.request_deployment(
        db_session, organization, request, client=fake
    )

    assert first.id == second.id
    assert first.entry_url == "https://sample-review.aifabei.example.com/"
    assert fake.creates == 1
    assert fake.deploys == 1
    assert fake.configured_envs["ZHUOJIAN_ORGANIZATION_ID"] == str(organization.id)
    assert len(fake.configured_envs["ZHUOJIAN_INTEGRATION_SECRET"]) >= 32


def test_log_redaction_and_failure_classification():
    logs = "git clone failed Authorization=very-secret-value repository not found"
    cleaned = redact_logs(logs, ("very-secret-value",))
    stage, _, action = classify_failure(cleaned)
    assert "very-secret-value" not in cleaned
    assert stage == "source"
    assert "GitHub App" in action
