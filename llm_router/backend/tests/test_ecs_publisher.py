"""Tests for the direct-ECS publisher credential and registration flow."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.ecs_runtime import EcsModuleRelease, EcsRuntime
from app.models.enterprise_application import EnterpriseApplication, EnterpriseApplicationGrant
from app.models.organization import Organization
from app.schemas.ecs_publisher import EcsModuleCredentialsInput
from app.services import ecs_publisher_service, subsystem_access_service


def test_runtime_registration_credentials_are_typed_and_non_interchangeable():
    values = {
        "manifest_access_token": "zjmf_manifest-credential-with-at-least-40-bytes",
        "sso_exchange_token": "zjss_sso-credential-with-at-least-40-bytes",
        "action_signing_secret": "zjac_action-credential-with-at-least-40-bytes",
        "event_signing_secret": "zjev_event-credential-with-at-least-40-bytes",
    }
    assert EcsModuleCredentialsInput(**values).sso_exchange_token.startswith("zjss_")
    with pytest.raises(ValueError, match="zjac_"):
        EcsModuleCredentialsInput(
            **{
                **values,
                "action_signing_secret": values["event_signing_secret"],
            }
        )


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
            "runtime_key": "alphabet-hk-01",
            "enterprise_key": "alphabet",
            "environment": "staging",
            "domain_suffix": "aifabei.example",
            "public_address": "8.219.202.188",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["credential"].startswith("zjrt_")
    assert payload["runtime_profile"]["deployment"]["provider"] == "direct-ecs"
    assert payload["runtime"]["enterprise_key"] == "alphabet"
    assert payload["runtime_profile"]["enterpriseKey"] == "alphabet"
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
    runtime = await db_session.scalar(
        select(EcsRuntime).where(EcsRuntime.organization_id == organization.id)
    )
    assert runtime is not None
    runtime.enterprise_key = "aifabei"
    manifest["enterprise"]["key"] = "alphabet"
    await db_session.flush()

    async def fake_discovery(_db, organization_id, base_url, auth_token):
        assert str(organization_id) == str(organization.id)
        assert base_url == "https://sample-review.aifabei.example/"
        assert auth_token == "integration-secret-with-at-least-32-characters"
        return {
            "suggested_slug": "sample-review",
            "manifest": manifest,
        }

    async def fake_sync(_db, _application, **_kwargs):
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
        "image_ref": "zhuojian/aifabei/sample-review:" + "a" * 40,
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

    begin = await client.post(
        "/api/v1/ecs-publisher/modules/sample-review/begin-change",
        json={"target_commit": "b" * 40},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert begin.status_code == 204, begin.text
    replayed_old_release = await client.post(
        "/api/v1/ecs-publisher/modules/register",
        json=body,
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert replayed_old_release.status_code == 409, replayed_old_release.text
    still_verifying = await client.get(
        "/api/v1/ecs-publisher/modules/sample-review",
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert still_verifying.status_code == 200
    assert still_verifying.json()["status"] == "verifying"
    assert still_verifying.json()["requested_commit"] == "b" * 40
    application = (
        await db_session.execute(
            select(EnterpriseApplication).where(
                EnterpriseApplication.organization_id == organization.id,
                EnterpriseApplication.slug == "sample-review",
            )
        )
    ).scalar_one()
    with pytest.raises(HTTPException, match="not approved"):
        await subsystem_access_service.assert_application_available(
            db_session,
            application,
            require_application_active=False,
        )
    cancel = await client.post(
        "/api/v1/ecs-publisher/modules/sample-review/cancel-change",
        json={"target_commit": "b" * 40},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert cancel.status_code == 204, cancel.text

    skipped_intent = await client.post(
        "/api/v1/ecs-publisher/modules/register",
        json={
            **body,
            "source_commit": "c" * 40,
            "image_ref": "zhuojian/aifabei/sample-review:" + "c" * 40,
        },
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert skipped_intent.status_code == 409
    begin = await client.post(
        "/api/v1/ecs-publisher/modules/sample-review/begin-change",
        json={"target_commit": "c" * 40},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert begin.status_code == 204, begin.text
    second = await client.post(
        "/api/v1/ecs-publisher/modules/register",
        json={
            **body,
            "source_commit": "c" * 40,
            "image_ref": "zhuojian/aifabei/sample-review:" + "c" * 40,
        },
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert second.status_code == 200
    assert second.json()["id"] == payload["id"]
    assert second.json()["last_success_commit"] == "c" * 40

    interrupted = await client.post(
        "/api/v1/ecs-publisher/modules/sample-review/begin-change",
        json={"target_commit": "d" * 40},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert interrupted.status_code == 204, interrupted.text
    rollback = await client.post(
        "/api/v1/ecs-publisher/modules/sample-review/begin-change",
        json={"target_commit": "c" * 40},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert rollback.status_code == 204, rollback.text
    cancel_rollback = await client.post(
        "/api/v1/ecs-publisher/modules/sample-review/cancel-change",
        json={"target_commit": "c" * 40},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert cancel_rollback.status_code == 204, cancel_rollback.text
    resumed_interrupted = await client.get(
        "/api/v1/ecs-publisher/modules/sample-review",
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert resumed_interrupted.json()["status"] == "verifying"
    assert resumed_interrupted.json()["requested_commit"] == "d" * 40
    cancel_interrupted = await client.post(
        "/api/v1/ecs-publisher/modules/sample-review/cancel-change",
        json={"target_commit": "d" * 40},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert cancel_interrupted.status_code == 204, cancel_interrupted.text

    await db_session.refresh(application)
    assert application.assistant_config["deploymentProvider"] == "direct-ecs"
    assert application.is_active is False
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

    disabled = await client.patch(
        f"/api/v1/ecs-publisher/organizations/{organization.id}/runtimes/"
        f"{created.json()['runtime']['id']}",
        json={"is_active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    blocked = await client.get(
        "/api/v1/ecs-publisher/modules/sample-review",
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert blocked.status_code == 401


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
            "image_ref": "zhuojian/aifabei/sample-review:" + "a" * 40,
        },
    )
    assert response.status_code == 422
    assert "sample-review.aifabei.example" in response.json()["detail"]


async def test_manifest_review_is_bound_to_the_pending_release_commit(
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
    credential = created.json()["credential"]
    manifest = {**_manifest(), "contractRevision": "2.5"}

    async def fake_discovery(*_args, **_kwargs):
        return {"suggested_slug": "sample-review", "manifest": manifest}

    async def fake_sync(db, application, **_kwargs):
        integration = await ecs_publisher_service.subsystem_integration_service.get_integration(
            db, application.id
        )
        integration.pending_manifest = manifest
        integration.pending_contract_revision = "2.5"
        integration.manifest_review_status = "pending"
        integration.sync_status = "pending_review"
        await db.flush()
        return {"status": "pending_review", "detail": None}

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
    registered = await client.post(
        "/api/v1/ecs-publisher/modules/register",
        headers={"Authorization": f"Bearer {credential}"},
        json={
            "application_slug": "sample-review",
            "application_name": "样品评审",
            "base_url": "https://sample-review.aifabei.example",
            "credentials": {
                "manifest_access_token": "zjmf_" + "m" * 48,
                "sso_exchange_token": "zjss_" + "s" * 48,
                "action_signing_secret": "zjac_" + "a" * 48,
                "event_signing_secret": "zjev_" + "e" * 48,
            },
            "source_commit": "a" * 40,
            "image_ref": "zhuojian/aifabei/sample-review:" + "a" * 40,
        },
    )
    assert registered.status_code == 200, registered.text
    assert registered.json()["status"] == "pending_review"
    application = await db_session.get(
        EnterpriseApplication, registered.json()["application_id"]
    )
    integration = (
        await ecs_publisher_service.subsystem_integration_service.get_integration(
            db_session, application.id
        )
    )
    pending_digest = ecs_publisher_service.subsystem_integration_service._canonical_digest(
        integration.pending_manifest
    )

    begin_next = await client.post(
        "/api/v1/ecs-publisher/modules/sample-review/begin-change",
        json={"target_commit": "b" * 40},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert begin_next.status_code == 204, begin_next.text
    with pytest.raises(HTTPException, match="pending release changed"):
        await ecs_publisher_service.subsystem_integration_service.review_pending_manifest(
            db_session,
            application,
            "approve",
            pending_digest,
        )


async def test_begin_change_fail_closes_an_existing_unmanaged_application(
    client, db_session
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
    credential = created.json()["credential"]
    application = await ecs_publisher_service.enterprise_application_service.create_application(
        db_session,
        organization.id,
        ecs_publisher_service.EnterpriseApplicationCreate(
            name="Legacy Sample Review",
            slug="sample-review",
            entry_url="https://sample-review.aifabei.example/",
            is_active=True,
        ),
    )

    begin = await client.post(
        "/api/v1/ecs-publisher/modules/sample-review/begin-change",
        json={"target_commit": "a" * 40},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert begin.status_code == 204, begin.text
    release = (await db_session.execute(select(EcsModuleRelease))).scalar_one()
    assert release.application_id == application.id
    assert release.status == "verifying"
    with pytest.raises(HTTPException, match="not approved"):
        await subsystem_access_service.assert_application_available(db_session, application)

    cancel = await client.post(
        "/api/v1/ecs-publisher/modules/sample-review/cancel-change",
        json={"target_commit": "a" * 40},
        headers={"Authorization": f"Bearer {credential}"},
    )
    assert cancel.status_code == 204, cancel.text
    assert (await db_session.execute(select(EcsModuleRelease))).scalar_one_or_none() is None


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
            "image_ref": "zhuojian/aifabei/sample-review:" + "a" * 40,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    stored = (
        await db_session.execute(select(EcsModuleRelease))
    ).scalar_one()
    assert stored.last_error == "manifest is invalid"
    assert stored.application_id is None
    begin_retry = await client.post(
        "/api/v1/ecs-publisher/modules/sample-review/begin-change",
        json={"target_commit": "b" * 40},
        headers={"Authorization": f"Bearer {created.json()['credential']}"},
    )
    assert begin_retry.status_code == 204, begin_retry.text
    cancel_retry = await client.post(
        "/api/v1/ecs-publisher/modules/sample-review/cancel-change",
        json={"target_commit": "b" * 40},
        headers={"Authorization": f"Bearer {created.json()['credential']}"},
    )
    assert cancel_retry.status_code == 204, cancel_retry.text
