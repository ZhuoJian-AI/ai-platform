"""Tests for the direct-ECS publisher credential and registration flow."""

from sqlalchemy import select

from app.models.ecs_runtime import EcsModuleRelease
from app.models.enterprise_application import EnterpriseApplication, EnterpriseApplicationGrant
from app.models.organization import Organization
from app.services import ecs_publisher_service


def _manifest() -> dict:
    return {
        "protocol": "zhuojian-subsystem",
        "version": 2,
        "contractRevision": "2.3",
        "enterprise": {"key": "aifabei", "name": "爱法贝"},
        "applicationSlug": "sample-review",
        "applicationName": "样品评审",
        "bridgeVersion": 1,
        "eventsUrl": "/api/integration/events",
        "eventDeliveriesUrl": "/api/integration/event-deliveries",
        "auth": {"ssoPath": "/api/integration/sso", "algorithm": "HS256"},
        "modules": [
            {
                "moduleKey": "sample_review",
                "name": "样品评审",
                "route": "/sample-review",
                "departments": [
                    {
                        "key": "design",
                        "name": "设计部",
                        "role": "owner",
                        "pageKeys": ["sample_review.list"],
                        "actionKeys": ["sample_review.query"],
                    }
                ],
                "pages": [
                    {
                        "pageKey": "sample_review.list",
                        "name": "评审列表",
                        "routePattern": "/sample-review",
                        "queryActionKey": "sample_review.query",
                        "actionKeys": ["sample_review.query"],
                        "contextSchema": {"type": "object"},
                    }
                ],
                "actions": [
                    {
                        "actionKey": "sample_review.query",
                        "name": "查询评审",
                        "operation": "query",
                        "aiEnabled": True,
                        "requiresConfirmation": False,
                        "inputSchema": {"type": "object"},
                        "resultSchema": {"type": "object"},
                    }
                ],
                "events": {"publishes": [], "subscribes": []},
            }
        ],
    }


async def _organization(db_session) -> Organization:
    organization = Organization(name="爱法贝", slug="aifabei", settings={})
    db_session.add(organization)
    await db_session.flush()
    return organization


async def test_admin_creates_runtime_and_credential_is_returned_once(client, db_session):
    organization = await _organization(db_session)
    response = await client.post(
        f"/api/v1/ecs-publisher/organizations/{organization.id}/runtimes",
        json={
            "runtime_key": "aifabei-hk-01",
            "enterprise_key": "aifabei",
            "environment": "staging",
            "domain_suffix": "aifabei.example",
            "public_address": "8.219.202.188",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["credential"].startswith("zjrt_")
    assert payload["runtime_profile"]["deployment"]["provider"] == "direct-ecs"
    assert payload["runtime_profile"]["platform"]["registrationEndpoint"].endswith(
        "/ecs-publisher/modules/register"
    )
    assert response.headers["cache-control"] == "no-store"

    listed = await client.get(
        f"/api/v1/ecs-publisher/organizations/{organization.id}/runtimes"
    )
    assert listed.status_code == 200
    assert "credential" not in listed.json()[0]
    assert "credential_hash" not in listed.json()[0]


async def test_runtime_registers_and_resyncs_module_without_grants(
    client, db_session, monkeypatch
):
    organization = await _organization(db_session)
    created = await client.post(
        f"/api/v1/ecs-publisher/organizations/{organization.id}/runtimes",
        json={
            "runtime_key": "aifabei-hk-01",
            "enterprise_key": "aifabei",
            "environment": "staging",
            "domain_suffix": "aifabei.example",
        },
    )
    credential = created.json()["credential"]
    manifest = _manifest()

    async def fake_discovery(_db, organization_id, base_url, auth_token):
        assert str(organization_id) == str(organization.id)
        assert base_url == "https://sample-review.aifabei.example/"
        assert auth_token == "integration-secret-with-at-least-32-characters"
        return {
            "suggested_slug": "sample-review",
            "manifest": manifest,
        }

    async def fake_sync(_db, _application):
        return {"status": "healthy", "detail": None}

    monkeypatch.setattr(
        ecs_publisher_service.subsystem_integration_service,
        "discover_subsystem",
        fake_discovery,
    )
    monkeypatch.setattr(
        ecs_publisher_service.subsystem_integration_service,
        "sync_integration",
        fake_sync,
    )
    body = {
        "application_slug": "sample-review",
        "application_name": "样品评审",
        "base_url": "https://sample-review.aifabei.example",
        "integration_secret": "integration-secret-with-at-least-32-characters",
        "source_commit": "a" * 40,
        "image_ref": "zhuojian/aifabei/sample-review@sha256:" + "b" * 64,
        "release_metadata": {"container": "zhuojian-aifabei-sample-review"},
    }
    first = await client.post(
        "/api/v1/ecs-publisher/modules/register",
        json=body,
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["status"] == "healthy"
    assert payload["last_success_commit"] == "a" * 40
    assert payload["contract_revision"] == "2.3"

    second = await client.post(
        "/api/v1/ecs-publisher/modules/register",
        json={**body, "source_commit": "c" * 40},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert second.status_code == 200
    assert second.json()["id"] == payload["id"]
    assert second.json()["last_success_commit"] == "c" * 40

    application = (
        await db_session.execute(
            select(EnterpriseApplication).where(
                EnterpriseApplication.organization_id == organization.id,
                EnterpriseApplication.slug == "sample-review",
            )
        )
    ).scalar_one()
    assert application.assistant_config["deploymentProvider"] == "direct-ecs"
    grants = list(
        (
            await db_session.execute(
                select(EnterpriseApplicationGrant).where(
                    EnterpriseApplicationGrant.application_id == application.id
                )
            )
        ).scalars()
    )
    assert grants == []


async def test_runtime_cannot_register_outside_its_domain(client, db_session):
    organization = await _organization(db_session)
    created = await client.post(
        f"/api/v1/ecs-publisher/organizations/{organization.id}/runtimes",
        json={
            "runtime_key": "aifabei-hk-01",
            "enterprise_key": "aifabei",
            "domain_suffix": "aifabei.example",
        },
    )
    credential = created.json()["credential"]
    response = await client.post(
        "/api/v1/ecs-publisher/modules/register",
        headers={"Authorization": f"Bearer {credential}"},
        json={
            "application_slug": "sample-review",
            "application_name": "样品评审",
            "base_url": "https://sample-review.other.example",
            "integration_secret": "integration-secret-with-at-least-32-characters",
            "source_commit": "a" * 40,
        },
    )
    assert response.status_code == 422
    assert "sample-review.aifabei.example" in response.json()["detail"]


async def test_rotating_runtime_credential_revokes_old_value(client, db_session):
    organization = await _organization(db_session)
    created = await client.post(
        f"/api/v1/ecs-publisher/organizations/{organization.id}/runtimes",
        json={
            "runtime_key": "aifabei-hk-01",
            "enterprise_key": "aifabei",
            "domain_suffix": "aifabei.example",
        },
    )
    old_credential = created.json()["credential"]
    runtime_id = created.json()["runtime"]["id"]
    rotated = await client.post(
        f"/api/v1/ecs-publisher/organizations/{organization.id}/runtimes/{runtime_id}/rotate-credential"
    )
    assert rotated.status_code == 200
    new_credential = rotated.json()["credential"]
    assert new_credential != old_credential

    old = await client.get(
        "/api/v1/ecs-publisher/modules/sample-review",
        headers={"Authorization": f"Bearer {old_credential}"},
    )
    assert old.status_code == 401
    current = await client.get(
        "/api/v1/ecs-publisher/modules/sample-review",
        headers={"Authorization": f"Bearer {new_credential}"},
    )
    assert current.status_code == 404


async def test_failed_contract_keeps_release_status_for_publisher(
    client, db_session, monkeypatch
):
    organization = await _organization(db_session)
    created = await client.post(
        f"/api/v1/ecs-publisher/organizations/{organization.id}/runtimes",
        json={
            "runtime_key": "aifabei-hk-01",
            "enterprise_key": "aifabei",
            "domain_suffix": "aifabei.example",
        },
    )

    async def broken_discovery(*_args, **_kwargs):
        raise ValueError("manifest is invalid")

    monkeypatch.setattr(
        ecs_publisher_service.subsystem_integration_service,
        "discover_subsystem",
        broken_discovery,
    )
    response = await client.post(
        "/api/v1/ecs-publisher/modules/register",
        headers={"Authorization": f"Bearer {created.json()['credential']}"},
        json={
            "application_slug": "sample-review",
            "application_name": "样品评审",
            "base_url": "https://sample-review.aifabei.example",
            "integration_secret": "integration-secret-with-at-least-32-characters",
            "source_commit": "a" * 40,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    stored = (
        await db_session.execute(select(EcsModuleRelease))
    ).scalar_one()
    assert stored.last_error == "manifest is invalid"
