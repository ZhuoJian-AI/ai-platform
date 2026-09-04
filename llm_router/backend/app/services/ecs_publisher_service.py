"""Least-privilege direct-ECS publishing into the ZhuoJian application catalog."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.ecs_publisher_auth import STORED_PREFIX_LENGTH
from app.models.ecs_runtime import EcsModuleRelease, EcsRuntime
from app.models.enterprise_application import EnterpriseApplication, EnterpriseApplicationSsoCode
from app.models.organization import Organization
from app.schemas.ecs_publisher import EcsModulePublishInput, EcsRuntimeCreate
from app.schemas.enterprise_application import (
    EnterpriseApplicationCreate,
    EnterpriseApplicationIntegrationInput,
    EnterpriseApplicationUpdate,
)
from app.services import enterprise_application_service, subsystem_integration_service
from app.utils.crypto import hash_api_key
from app.utils.public_url import assert_public_http_url, same_origin

CANONICAL_ENTERPRISE_KEY = "alphabet"
LEGACY_ENTERPRISE_KEYS = frozenset({"aifabei"})


def canonical_enterprise_key(value: str) -> str:
    """Return the current contract identity without rewriting persisted legacy runtimes."""
    normalized = value.strip().lower()
    if normalized in LEGACY_ENTERPRISE_KEYS:
        return CANONICAL_ENTERPRISE_KEY
    return normalized


def _new_credential() -> tuple[str, str, str]:
    token = f"zjrt_{secrets.token_urlsafe(48)}"
    return token, token[:STORED_PREFIX_LENGTH], hash_api_key(token)


def runtime_profile(runtime: EcsRuntime, platform_url: str) -> dict:
    return {
        "schemaVersion": 2,
        "enterpriseKey": runtime.enterprise_key,
        "organizationId": str(runtime.organization_id),
        "environment": runtime.environment,
        "runtimeId": runtime.runtime_key,
        "deployment": {
            "provider": "direct-ecs",
            "repositoriesRoot": "/srv/zhuojian/repositories",
            "deploymentsRoot": "/srv/zhuojian/deployments",
            "dataRoot": "/srv/zhuojian/data",
            "backupsRoot": "/srv/zhuojian/backups",
            "nginxConfigRoot": "/etc/nginx/conf.d",
            "registrationCredentialRef": "/etc/zhuojian/runtime-registration.key",
        },
        "domains": {
            "suffix": runtime.domain_suffix,
            "httpsRequired": True,
        },
        "platform": {
            "baseUrl": platform_url.rstrip("/"),
            "registrationEndpoint": "/api/v1/ecs-publisher/modules/register",
            "ssoExchangeEndpoint": "/api/v1/subsystem-sso/exchange",
            "registrationEnabled": runtime.is_active,
        },
        "credentials": {
            "version": 2,
            "requiredTypes": [
                "zjmf_manifest_access",
                "zjss_sso_exchange",
                "zjac_action_signing",
                "zjev_event_signing",
            ],
            "crossPurposeUseAllowed": False,
        },
    }


async def create_runtime(
    db: AsyncSession,
    organization: Organization,
    data: EcsRuntimeCreate,
) -> tuple[EcsRuntime, str]:
    existing = (
        await db.execute(
            select(EcsRuntime).where(
                EcsRuntime.organization_id == organization.id,
                EcsRuntime.runtime_key == data.runtime_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="ECS runtime key already exists")
    credential, prefix, digest = _new_credential()
    row = EcsRuntime(
        organization_id=organization.id,
        runtime_key=data.runtime_key,
        # Persist the requested identity so an explicitly restored legacy
        # Runtime keeps its historical container and image namespace.
        enterprise_key=data.enterprise_key,
        environment=data.environment,
        domain_suffix=data.domain_suffix,
        public_address=data.public_address,
        credential_prefix=prefix,
        credential_hash=digest,
        credential_rotated_at=datetime.now(UTC),
        is_active=True,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row, credential


async def list_runtimes(db: AsyncSession, organization_id: UUID | str) -> list[EcsRuntime]:
    return list(
        (
            await db.execute(
                select(EcsRuntime)
                .where(EcsRuntime.organization_id == UUID(str(organization_id)))
                .order_by(EcsRuntime.created_at)
            )
        ).scalars()
    )


async def get_runtime(
    db: AsyncSession, organization_id: UUID | str, runtime_id: UUID | str
) -> EcsRuntime | None:
    return (
        await db.execute(
            select(EcsRuntime).where(
                EcsRuntime.id == UUID(str(runtime_id)),
                EcsRuntime.organization_id == UUID(str(organization_id)),
            )
        )
    ).scalar_one_or_none()


async def rotate_credential(db: AsyncSession, runtime: EcsRuntime) -> str:
    credential, prefix, digest = _new_credential()
    runtime.credential_prefix = prefix
    runtime.credential_hash = digest
    runtime.credential_rotated_at = datetime.now(UTC)
    await db.flush()
    # ``updated_at`` is generated by a server-side onupdate expression.  Refresh
    # before FastAPI/Pydantic serializes the ORM object to avoid async lazy IO.
    await db.refresh(runtime)
    return credential


async def set_runtime_active(db: AsyncSession, runtime: EcsRuntime, active: bool) -> EcsRuntime:
    runtime.is_active = active
    if not active:
        application_ids = select(EcsModuleRelease.application_id).where(
            EcsModuleRelease.runtime_id == runtime.id,
            EcsModuleRelease.application_id.is_not(None),
        )
        await db.execute(
            update(EnterpriseApplicationSsoCode)
            .where(
                EnterpriseApplicationSsoCode.application_id.in_(application_ids),
                EnterpriseApplicationSsoCode.consumed_at.is_(None),
            )
            .values(expires_at=datetime.now(UTC))
        )
    await db.flush()
    await db.refresh(runtime)
    return runtime


async def get_release(
    db: AsyncSession,
    organization_id: UUID | str,
    application_slug: str,
    *,
    for_update: bool = False,
) -> EcsModuleRelease | None:
    query = select(EcsModuleRelease).where(
        EcsModuleRelease.organization_id == UUID(str(organization_id)),
        EcsModuleRelease.application_slug == application_slug,
    )
    if for_update:
        query = query.with_for_update()
    return (
        await db.execute(query)
    ).scalar_one_or_none()


async def _owned_release_for_change(
    db: AsyncSession,
    runtime: EcsRuntime,
    application_slug: str,
) -> EcsModuleRelease:
    release = (
        await db.execute(
            select(EcsModuleRelease)
            .where(
                EcsModuleRelease.organization_id == runtime.organization_id,
                EcsModuleRelease.application_slug == application_slug,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if release is None or release.runtime_id != runtime.id:
        raise HTTPException(status_code=404, detail="Module release not found")
    if not runtime.is_active:
        raise HTTPException(status_code=401, detail="ECS runtime credential is revoked")
    return release


async def begin_release_change(
    db: AsyncSession,
    runtime: EcsRuntime,
    application_slug: str,
    target_commit: str,
) -> None:
    """Fail-close employee access before a Runtime switches code."""

    target = target_commit.lower()
    if not runtime.is_active:
        raise HTTPException(status_code=401, detail="ECS runtime credential is revoked")
    release = await get_release(
        db,
        runtime.organization_id,
        application_slug,
        for_update=True,
    )
    if release is None:
        application = (
            await db.execute(
                select(EnterpriseApplication)
                .where(
                    EnterpriseApplication.organization_id == runtime.organization_id,
                    EnterpriseApplication.slug == application_slug,
                    EnterpriseApplication.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if application is None:
            return
        base_url = _validated_base_url(runtime, application_slug, application.entry_url)
        release = EcsModuleRelease(
            organization_id=runtime.organization_id,
            runtime_id=runtime.id,
            application_id=application.id,
            application_slug=application_slug,
            application_name=application.name,
            base_url=base_url,
            requested_commit=target,
            status="verifying",
            release_metadata={
                "changeIntent": {
                    "targetCommit": target,
                    "previousHealthyCommit": None,
                    "previousStatus": None,
                    "previousRequestedCommit": None,
                    "previousLastError": None,
                    "previousChangeIntent": None,
                    "adoption": True,
                    "startedAt": datetime.now(UTC).isoformat(),
                }
            },
            last_seen_at=datetime.now(UTC),
        )
        db.add(release)
        await db.flush()
        return
    if release.runtime_id != runtime.id:
        raise HTTPException(status_code=404, detail="Module release not found")
    existing_intent = (release.release_metadata or {}).get("changeIntent")
    if release.status == "verifying" and release.requested_commit == target:
        if isinstance(existing_intent, dict) and existing_intent.get("targetCommit") == target:
            return
        raise HTTPException(status_code=409, detail="Release change intent is missing or invalid")
    previous_status = release.status
    previous_requested_commit = release.requested_commit
    if previous_status == "healthy":
        pass
    elif previous_status in {"failed", "pending_review"}:
        # A blocked candidate may be corrected or rolled back without ever
        # reopening employee traffic.
        pass
    elif previous_status == "verifying" and (
        not release.last_success_commit or target == release.last_success_commit
    ):
        # Supersede an interrupted first candidate, or recover an interrupted
        # update to the last accepted commit. The gate remains closed.
        pass
    else:
        raise HTTPException(
            status_code=409,
            detail="Current module release must be reconciled before another switch",
        )
    metadata = dict(release.release_metadata or {})
    metadata["changeIntent"] = {
        "targetCommit": target,
        "previousHealthyCommit": release.last_success_commit,
            "previousStatus": previous_status,
            "previousRequestedCommit": previous_requested_commit,
            "previousLastError": release.last_error,
            "previousChangeIntent": existing_intent if isinstance(existing_intent, dict) else None,
            "adoption": False,
            "startedAt": datetime.now(UTC).isoformat(),
        }
    release.release_metadata = metadata
    release.requested_commit = target
    release.status = "verifying"
    release.last_error = None
    release.last_seen_at = datetime.now(UTC)
    await db.flush()


async def cancel_release_change(
    db: AsyncSession,
    runtime: EcsRuntime,
    application_slug: str,
    target_commit: str,
) -> None:
    """Restore the previous healthy gate only after the local switch was rolled back."""

    release = await _owned_release_for_change(db, runtime, application_slug)
    target = target_commit.lower()
    intent = (release.release_metadata or {}).get("changeIntent")
    if (
        release.status != "verifying"
        or release.requested_commit != target
        or not isinstance(intent, dict)
        or intent.get("targetCommit") != target
        or intent.get("previousHealthyCommit") != release.last_success_commit
        or intent.get("previousStatus") not in {None, "healthy", "failed", "pending_review", "verifying"}
    ):
        raise HTTPException(status_code=409, detail="Release change intent no longer matches")
    if intent.get("adoption") is True:
        if release.last_success_commit is not None or intent.get("previousStatus") is not None:
            raise HTTPException(status_code=409, detail="Invalid adoption release intent")
        await db.delete(release)
        await db.flush()
        return
    previous_requested_commit = intent.get("previousRequestedCommit")
    if not isinstance(previous_requested_commit, str):
        raise HTTPException(status_code=409, detail="Release change intent no longer matches")
    metadata = dict(release.release_metadata or {})
    metadata.pop("changeIntent", None)
    previous_intent = intent.get("previousChangeIntent")
    if isinstance(previous_intent, dict):
        metadata["changeIntent"] = previous_intent
    release.release_metadata = metadata
    release.requested_commit = previous_requested_commit
    release.status = str(intent["previousStatus"])
    previous_error = intent.get("previousLastError")
    release.last_error = previous_error if isinstance(previous_error, str) else None
    release.last_seen_at = datetime.now(UTC)
    await db.flush()


def _validated_base_url(runtime: EcsRuntime, application_slug: str, value: str) -> str:
    base_url = value.rstrip("/") + "/"
    try:
        assert_public_http_url(base_url, require_https=runtime.environment != "development")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    parsed = urlsplit(base_url)
    expected_host = f"{application_slug}.{runtime.domain_suffix}"
    if parsed.hostname != expected_host:
        raise HTTPException(
            status_code=422,
            detail=f"base_url host must be '{expected_host}' for this ECS runtime",
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise HTTPException(status_code=422, detail="base_url must not contain a path, query or fragment")
    return base_url


def _manifest_digest(manifest: dict) -> str:
    canonical = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


async def _upsert_application(
    db: AsyncSession,
    runtime: EcsRuntime,
    release: EcsModuleRelease,
    data: EcsModulePublishInput,
) -> EnterpriseApplication:
    application = (
        await db.execute(
            select(EnterpriseApplication).where(
                EnterpriseApplication.organization_id == runtime.organization_id,
                EnterpriseApplication.slug == data.application_slug,
                EnterpriseApplication.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if application is not None and release.application_id and application.id != release.application_id:
        raise HTTPException(status_code=409, detail="Application slug is bound to another release")
    if application is not None and not same_origin(application.entry_url, release.base_url):
        if release.application_id is None:
            raise HTTPException(status_code=409, detail="Application slug uses a different origin")
    config = {
        "deploymentManaged": True,
        "deploymentProvider": "direct-ecs",
        "runtimeId": str(runtime.id),
        "runtimeKey": runtime.runtime_key,
        "sourceCommit": data.source_commit,
    }
    if application is None:
        application = await enterprise_application_service.create_application(
            db,
            UUID(str(runtime.organization_id)),
            EnterpriseApplicationCreate(
                name=data.application_name,
                slug=data.application_slug,
                description="由企业 AI 按灼见原生协议开发并部署在企业 ECS",
                entry_url=release.base_url,
                display_mode="embedded",
                # Runtime registration creates an administrator-reviewable
                # candidate.  Only an administrator may activate the app.
                is_active=False,
                assistant_enabled=True,
                assistant_config=config,
            ),
        )
    else:
        application = await enterprise_application_service.update_application(
            db,
            application,
            EnterpriseApplicationUpdate(
                name=data.application_name,
                entry_url=release.base_url,
                assistant_config={**(application.assistant_config or {}), **config},
            ),
        )
    return application


async def register_module(
    db: AsyncSession,
    runtime: EcsRuntime,
    data: EcsModulePublishInput,
) -> EcsModuleRelease:
    if not runtime.is_active:
        raise HTTPException(status_code=401, detail="ECS runtime credential is revoked")
    manifest_access_token = (
        data.credentials.manifest_access_token
        if data.credentials is not None
        else data.integration_secret
    )
    if not manifest_access_token:
        raise HTTPException(status_code=422, detail="Manifest access credential is required")
    metadata_size = len(json.dumps(data.release_metadata, ensure_ascii=False).encode("utf-8"))
    if metadata_size > 64 * 1024:
        raise HTTPException(status_code=422, detail="release_metadata exceeds 64KB")
    base_url = _validated_base_url(runtime, data.application_slug, data.base_url)
    target_commit = data.source_commit.lower()
    expected_image = (
        f"zhuojian/{runtime.enterprise_key}/{data.application_slug}:{target_commit}"
    )
    if data.image_ref != expected_image:
        raise HTTPException(
            status_code=422,
            detail="image_ref must be the Runtime-managed immutable commit image",
        )
    release = await get_release(
        db,
        runtime.organization_id,
        data.application_slug,
        for_update=True,
    )
    if release is not None and release.runtime_id != runtime.id:
        previous_runtime = await db.get(EcsRuntime, release.runtime_id)
        if previous_runtime is not None and previous_runtime.is_active:
            raise HTTPException(
                status_code=409,
                detail="Module is bound to another active ECS runtime; deactivate it before migration",
            )
        release.runtime_id = runtime.id
    if release is not None:
        intent = (release.release_metadata or {}).get("changeIntent")
        intent_matches = (
            release.status == "verifying"
            and release.requested_commit == target_commit
            and isinstance(intent, dict)
            and intent.get("targetCommit") == target_commit
            and intent.get("previousHealthyCommit") == release.last_success_commit
        )
        retry_matches = (
            release.status in {"failed", "pending_review"}
            and release.requested_commit == target_commit
        )
        healthy_replay = (
            release.status == "healthy"
            and release.last_success_commit == target_commit
        )
        if not intent_matches and not retry_matches and not healthy_replay:
            raise HTTPException(
                status_code=409,
                detail="Begin the matching release change before registering this commit",
            )
    now = datetime.now(UTC)
    if release is None:
        release = EcsModuleRelease(
            organization_id=runtime.organization_id,
            runtime_id=runtime.id,
            application_slug=data.application_slug,
            application_name=data.application_name,
            base_url=base_url,
            requested_commit=target_commit,
            image_ref=data.image_ref,
            status="verifying",
            release_metadata=data.release_metadata,
            deployed_at=data.deployed_at or now,
            last_seen_at=now,
        )
        db.add(release)
    else:
        release.application_name = data.application_name
        release.base_url = base_url
        release.requested_commit = target_commit
        release.image_ref = data.image_ref
        release.status = "verifying"
        release_metadata = dict(data.release_metadata or {})
        existing_intent = (release.release_metadata or {}).get("changeIntent")
        if isinstance(existing_intent, dict):
            release_metadata["changeIntent"] = existing_intent
        release.release_metadata = release_metadata
        release.last_error = None
        release.deployed_at = data.deployed_at or now
        release.last_seen_at = now
    await db.flush()

    try:
        discovery = await subsystem_integration_service.discover_subsystem(
            db, runtime.organization_id, base_url, manifest_access_token
        )
        manifest = discovery["manifest"]
        contract_revision = str(manifest.get("contractRevision") or "2.0")
        if contract_revision == "2.5" and data.credentials is None:
            raise ValueError("contractRevision 2.5 requires separated subsystem credentials")
        if discovery["suggested_slug"] != data.application_slug:
            raise ValueError("Manifest applicationSlug does not match the release")
        enterprise = manifest.get("enterprise") if isinstance(manifest, dict) else None
        manifest_enterprise_key = enterprise.get("key") if isinstance(enterprise, dict) else ""
        if canonical_enterprise_key(str(manifest_enterprise_key or "")) != canonical_enterprise_key(
            runtime.enterprise_key
        ):
            raise ValueError("Manifest enterprise.key does not match the ECS runtime")
        application = await _upsert_application(db, runtime, release, data)
        await subsystem_integration_service.configure_integration(
            db,
            application,
            EnterpriseApplicationIntegrationInput(
                manifest_url=urljoin(base_url, "/api/integration/manifest"),
                manifest_access_token=(
                    data.credentials.manifest_access_token if data.credentials else None
                ),
                auth_token=(data.integration_secret if data.credentials is None else None),
                sso_exchange_token=(
                    data.credentials.sso_exchange_token if data.credentials else None
                ),
                action_signing_secret=(
                    data.credentials.action_signing_secret if data.credentials else None
                ),
                event_signing_secret=(
                    data.credentials.event_signing_secret if data.credentials else None
                ),
                sync_enabled=True,
            ),
        )
        sync = await subsystem_integration_service.sync_integration(
            db,
            application,
            allow_initial_inactive_candidate=True,
        )
        if sync.get("status") not in {"healthy", "pending_review"}:
            raise ValueError(str(sync.get("detail") or "Manifest synchronization failed"))
        release.application_id = application.id
        release.contract_revision = contract_revision
        release.manifest_digest = _manifest_digest(manifest)
        if sync.get("status") == "pending_review":
            release.status = "pending_review"
            application.health_status = "unknown"
        else:
            release.last_success_commit = target_commit
            release.status = "healthy"
            application.health_status = "healthy"
        release_metadata = dict(release.release_metadata or {})
        release_metadata.pop("changeIntent", None)
        release.release_metadata = release_metadata
        release.last_error = None
    except HTTPException:
        raise
    except Exception as exc:
        release.status = "failed"
        release.last_error = str(exc)[:1000]
        release_metadata = dict(release.release_metadata or {})
        release_metadata.pop("changeIntent", None)
        release.release_metadata = release_metadata
    runtime.last_seen_at = now
    await db.flush()
    await db.refresh(release)
    return release
