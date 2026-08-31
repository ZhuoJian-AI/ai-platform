"""Orchestrate repository-to-Coolify-to-SaaS module releases."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from urllib.parse import urljoin
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.enterprise_application import EnterpriseApplication
from app.models.module_deployment import ModuleDeployment, ModuleDeploymentProfile
from app.models.organization import Organization
from app.schemas.enterprise_application import (
    EnterpriseApplicationCreate,
    EnterpriseApplicationIntegrationInput,
    EnterpriseApplicationUpdate,
)
from app.schemas.module_publisher import (
    ModuleDeploymentProfileInput,
    ModuleDeploymentRequest,
)
from app.services import enterprise_application_service, subsystem_integration_service
from app.services.coolify_module_client import (
    CoolifyModuleClient,
    CoolifyModuleError,
    CoolifyTarget,
    classify_failure,
    redact_logs,
)
from app.services.github_module_publisher_service import ModulePublisherError, repository_name
from app.utils.crypto import decrypt_provider_api_key, encrypt_provider_api_key
from app.utils.public_url import same_origin

ACTIVE_STATES = {"queued", "deploying", "verifying", "rollback_queued", "rolling_back"}
SUCCESS_STATES = {"finished", "success", "successful", "completed"}
FAILURE_STATES = {"failed", "cancelled", "canceled", "error"}


async def get_profile(
    db: AsyncSession,
    organization_id: UUID | str,
    runtime_key: str | None = None,
) -> ModuleDeploymentProfile | None:
    query = select(ModuleDeploymentProfile).where(
        ModuleDeploymentProfile.organization_id == UUID(str(organization_id)),
        ModuleDeploymentProfile.is_active.is_(True),
    )
    if runtime_key:
        query = query.where(ModuleDeploymentProfile.runtime_key == runtime_key)
    else:
        query = query.order_by(
            ModuleDeploymentProfile.is_default.desc(),
            ModuleDeploymentProfile.created_at,
        )
    return (await db.execute(query.limit(1))).scalar_one_or_none()


async def save_profile(
    db: AsyncSession,
    organization_id: UUID | str,
    data: ModuleDeploymentProfileInput,
) -> ModuleDeploymentProfile:
    row = (
        await db.execute(
            select(ModuleDeploymentProfile).where(
                ModuleDeploymentProfile.organization_id == UUID(str(organization_id)),
                ModuleDeploymentProfile.runtime_key == data.runtime_key,
            )
        )
    ).scalar_one_or_none()
    values = data.model_dump()
    existing_count = len(
        list(
            (
                await db.execute(
                    select(ModuleDeploymentProfile.id).where(
                        ModuleDeploymentProfile.organization_id == UUID(str(organization_id))
                    )
                )
            ).scalars()
        )
    )
    if existing_count == 0:
        values["is_default"] = True
    elif row is not None and row.is_default and not values["is_default"]:
        other_default = (
            await db.execute(
                select(ModuleDeploymentProfile.id).where(
                    ModuleDeploymentProfile.organization_id == UUID(str(organization_id)),
                    ModuleDeploymentProfile.id != row.id,
                    ModuleDeploymentProfile.is_default.is_(True),
                )
            )
        ).scalar_one_or_none()
        if other_default is None:
            values["is_default"] = True
    if values["is_default"]:
        for existing in (
            await db.execute(
                select(ModuleDeploymentProfile).where(
                    ModuleDeploymentProfile.organization_id == UUID(str(organization_id)),
                    ModuleDeploymentProfile.is_default.is_(True),
                )
            )
        ).scalars():
            if row is None or existing.id != row.id:
                existing.is_default = False
        await db.flush()
    if row is None:
        row = ModuleDeploymentProfile(
            organization_id=UUID(str(organization_id)),
            **values,
        )
        db.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    await db.flush()
    return row


async def get_deployment(
    db: AsyncSession, organization_id: UUID | str, module_slug: str
) -> ModuleDeployment | None:
    return (
        await db.execute(
            select(ModuleDeployment).where(
                ModuleDeployment.organization_id == UUID(str(organization_id)),
                ModuleDeployment.module_slug == module_slug,
            )
        )
    ).scalar_one_or_none()


def _target(profile: ModuleDeploymentProfile) -> CoolifyTarget:
    return CoolifyTarget(
        server_uuid=profile.server_uuid,
        project_uuid=profile.project_uuid,
        environment_name=profile.environment_name,
        environment_uuid=profile.environment_uuid,
        destination_uuid=profile.destination_uuid,
        github_app_uuid=profile.github_app_uuid,
        use_build_server=profile.use_build_server,
    )


def _domain(profile: ModuleDeploymentProfile, module_slug: str) -> str:
    return f"https://{module_slug}.{profile.domain_suffix}"


def _envs(row: ModuleDeployment) -> dict[str, str]:
    return {
        "ZHUOJIAN_INTEGRATION_SECRET": decrypt_provider_api_key(row.integration_secret_encrypted),
        "SESSION_SECRET": decrypt_provider_api_key(row.session_secret_encrypted),
        "ZHUOJIAN_ORGANIZATION_ID": str(row.organization_id),
        "ZHUOJIAN_SAAS_ORIGINS": settings.module_saas_origin.rstrip("/"),
        "DATABASE_PATH": "/data/subsystem.db",
    }


async def request_deployment(
    db: AsyncSession,
    organization: Organization,
    data: ModuleDeploymentRequest,
    *,
    client: CoolifyModuleClient | None = None,
) -> ModuleDeployment:
    if not settings.coolify_module_deployer_configured:
        raise HTTPException(status_code=503, detail="Coolify module deployer is not configured")
    row = await get_deployment(db, organization.id, data.module_slug)
    if row is not None:
        profile = await db.get(ModuleDeploymentProfile, row.deployment_profile_id)
        if profile is None or not profile.is_active:
            raise HTTPException(status_code=409, detail="The module's Coolify runtime is inactive")
        if data.runtime_key and data.runtime_key != profile.runtime_key:
            raise HTTPException(
                status_code=409,
                detail="An existing module cannot be moved to another runtime during publish",
            )
    else:
        profile = await get_profile(db, organization.id, data.runtime_key)
    if profile is None or not profile.is_active:
        raise HTTPException(
            status_code=409,
            detail="The organization has no active Coolify deployment profile",
        )
    try:
        expected_repository = repository_name(organization.slug, data.module_slug)
    except ModulePublisherError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if data.repository_name != expected_repository:
        raise HTTPException(
            status_code=422,
            detail=f"repository_name must be '{expected_repository}'",
        )
    if row is not None and row.requested_commit == data.source_commit and row.status in ACTIVE_STATES | {"healthy"}:
        return row

    coolify = client or CoolifyModuleClient()
    entry_url = _domain(profile, data.module_slug).rstrip("/") + "/"
    integration_secret = secrets.token_urlsafe(48)
    session_secret = secrets.token_urlsafe(48)
    try:
        if row is None:
            application_uuid = await coolify.create_application(
                target=_target(profile),
                repository=f"https://github.com/{settings.github_module_publisher_owner}/{expected_repository}",
                name=f"{organization.slug}-{data.module_slug}",
                domain=entry_url.rstrip("/"),
                commit=data.source_commit,
            )
            row = ModuleDeployment(
                organization_id=organization.id,
                deployment_profile_id=profile.id,
                module_slug=data.module_slug,
                module_name=data.module_name,
                repository_name=expected_repository,
                coolify_application_uuid=application_uuid,
                entry_url=entry_url,
                integration_secret_encrypted=encrypt_provider_api_key(integration_secret),
                session_secret_encrypted=encrypt_provider_api_key(session_secret),
                requested_commit=data.source_commit,
                status="queued",
            )
            db.add(row)
            await db.flush()
        else:
            row.module_name = data.module_name
            row.repository_name = expected_repository
            row.entry_url = entry_url
            row.requested_commit = data.source_commit
            row.rollback_deployment_uuid = None
            row.failure_stage = None
            row.last_error = None
            row.log_excerpt = None
            await coolify.update_release(
                row.coolify_application_uuid,
                domain=entry_url.rstrip("/"),
                commit=data.source_commit,
            )
        await coolify.set_envs(row.coolify_application_uuid, _envs(row))
        await coolify.ensure_storage(
            row.coolify_application_uuid,
            f"zhuojian-{organization.slug}-{data.module_slug}-data",
        )
        deployment_uuid = await coolify.deploy(row.coolify_application_uuid)
    except CoolifyModuleError as exc:
        if row is not None:
            row.status = "failed"
            row.failure_stage = exc.stage
            row.last_error = exc.detail
            await db.flush()
            return row
        raise HTTPException(status_code=503, detail=f"{exc.stage}: {exc.detail}") from exc
    row.deployment_uuid = deployment_uuid
    row.status = "deploying"
    await db.flush()
    return row


def _coolify_status(payload: dict) -> str:
    return str(payload.get("status") or "unknown").strip().lower()


async def _ensure_platform_registration(
    db: AsyncSession,
    row: ModuleDeployment,
) -> tuple[bool, str | None]:
    result = await db.execute(
        select(EnterpriseApplication).where(
            EnterpriseApplication.organization_id == row.organization_id,
            EnterpriseApplication.slug == row.module_slug,
            EnterpriseApplication.deleted_at.is_(None),
        )
    )
    application = result.scalar_one_or_none()
    if application is not None:
        if row.application_id and str(application.id) != str(row.application_id):
            return False, "The module slug is already bound to another platform application"
        if not row.application_id and not same_origin(application.entry_url, row.entry_url):
            return False, "The module slug is already registered with a different origin"
    if application is None:
        application = await enterprise_application_service.create_application(
            db,
            UUID(str(row.organization_id)),
            EnterpriseApplicationCreate(
                name=row.module_name,
                slug=row.module_slug,
                description="由企业 AI 按灼见原生协议开发并独立部署",
                entry_url=row.entry_url,
                display_mode="embedded",
                is_active=True,
                assistant_enabled=True,
                assistant_config={
                    "deploymentManaged": True,
                    "coolifyApplicationUuid": row.coolify_application_uuid,
                },
            ),
        )
    else:
        application = await enterprise_application_service.update_application(
            db,
            application,
            EnterpriseApplicationUpdate(
                name=row.module_name,
                entry_url=row.entry_url,
                is_active=True,
                assistant_enabled=True,
                assistant_config={
                    **(application.assistant_config or {}),
                    "deploymentManaged": True,
                    "coolifyApplicationUuid": row.coolify_application_uuid,
                },
            ),
        )
    integration_secret = decrypt_provider_api_key(row.integration_secret_encrypted)
    await subsystem_integration_service.configure_integration(
        db,
        application,
        EnterpriseApplicationIntegrationInput(
            manifest_url=urljoin(row.entry_url, "/api/integration/manifest"),
            auth_token=integration_secret,
            sync_enabled=True,
        ),
    )
    sync = await subsystem_integration_service.sync_integration(db, application)
    if sync.get("status") != "healthy":
        return False, str(sync.get("detail") or "Manifest sync failed")
    application.health_status = "healthy"
    row.application_id = application.id
    await db.flush()
    return True, None


async def _probe_health(row: ModuleDeployment) -> None:
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=6.0), follow_redirects=False
        ) as client:
            response = await client.get(urljoin(row.entry_url, "/health"))
            if response.status_code != 200:
                raise ValueError(f"GET /health returned HTTP {response.status_code}")
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("status") not in {"ok", "healthy"}:
                raise ValueError("GET /health did not return a healthy status")
    except (httpx.HTTPError, ValueError) as exc:
        raise CoolifyModuleError("health", str(exc)) from exc


async def _start_rollback(
    db: AsyncSession,
    row: ModuleDeployment,
    coolify: CoolifyModuleClient,
) -> None:
    if not row.last_success_commit or row.last_success_commit == row.requested_commit:
        row.status = "failed"
        await db.flush()
        return
    try:
        await coolify.update_release(
            row.coolify_application_uuid,
            domain=row.entry_url.rstrip("/"),
            commit=row.last_success_commit,
        )
        row.rollback_deployment_uuid = await coolify.deploy(row.coolify_application_uuid)
        row.status = "rollback_queued"
    except CoolifyModuleError as exc:
        row.status = "rollback_failed"
        row.last_error = f"{row.last_error or 'Release failed'}; rollback failed: {exc.detail}"
    await db.flush()


async def _record_failure(
    db: AsyncSession,
    row: ModuleDeployment,
    coolify: CoolifyModuleClient,
    detail: str,
    logs: str,
) -> None:
    secrets_to_hide = tuple(_envs(row).values())
    excerpt = redact_logs(logs, secrets_to_hide)
    stage, message, _ = classify_failure(excerpt, detail)
    row.failure_stage = stage
    row.last_error = message[:1000]
    row.log_excerpt = excerpt
    await _start_rollback(db, row, coolify)


async def refresh_deployment(
    db: AsyncSession,
    row: ModuleDeployment,
    *,
    client: CoolifyModuleClient | None = None,
) -> ModuleDeployment:
    coolify = client or CoolifyModuleClient()
    active_uuid = row.rollback_deployment_uuid or row.deployment_uuid
    if not active_uuid:
        return row
    payload = await coolify.deployment(active_uuid)
    status = _coolify_status(payload)
    logs = str(payload.get("logs") or "")
    if row.rollback_deployment_uuid:
        if status in SUCCESS_STATES:
            row.status = "rolled_back"
        elif status in FAILURE_STATES:
            row.status = "rollback_failed"
            row.last_error = f"{row.last_error or 'Release failed'}; automatic rollback failed"
        else:
            row.status = "rolling_back"
        await db.flush()
        return row
    if status in FAILURE_STATES:
        if not logs:
            try:
                logs = await coolify.application_logs(row.coolify_application_uuid)
            except CoolifyModuleError:
                logs = ""
        await _record_failure(db, row, coolify, "Coolify deployment failed", logs)
        return row
    if status not in SUCCESS_STATES:
        row.status = "deploying"
        await db.flush()
        return row
    row.status = "verifying"
    await db.flush()
    try:
        await _probe_health(row)
        registered, detail = await _ensure_platform_registration(db, row)
        if not registered:
            raise CoolifyModuleError("contract", detail or "Manifest sync failed")
    except CoolifyModuleError as exc:
        await _record_failure(db, row, coolify, exc.detail, logs)
        if row.failure_stage == "deploy":
            row.failure_stage = exc.stage
        return row
    row.status = "healthy"
    row.last_success_commit = row.requested_commit
    row.failure_stage = None
    row.last_error = None
    row.log_excerpt = None
    row.deployed_at = datetime.now(UTC)
    await db.flush()
    return row


def deployment_read(row: ModuleDeployment) -> dict:
    retryable = row.status in {"failed", "rolled_back", "rollback_failed"}
    next_action = None
    if retryable:
        _, _, next_action = classify_failure(row.log_excerpt or "", row.last_error or "Release failed")
    return {
        "id": row.id,
        "module_slug": row.module_slug,
        "module_name": row.module_name,
        "repository_name": row.repository_name,
        "entry_url": row.entry_url,
        "coolify_application_uuid": row.coolify_application_uuid,
        "deployment_uuid": row.rollback_deployment_uuid or row.deployment_uuid,
        "requested_commit": row.requested_commit,
        "last_success_commit": row.last_success_commit,
        "status": row.status,
        "failure_stage": row.failure_stage,
        "detail": row.last_error,
        "log_excerpt": row.log_excerpt,
        "application_id": row.application_id,
        "retryable": retryable,
        "next_action": next_action,
    }
