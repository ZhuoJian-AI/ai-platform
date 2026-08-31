"""Tenant API for repository provisioning and scoped Coolify releases."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import CurrentAdmin, require_org_access_write
from app.auth.api_key_auth import AuthenticatedKey, authenticate_request
from app.config import settings
from app.database import get_db
from app.models.organization import Organization
from app.schemas.module_publisher import (
    ModuleDeploymentProfileInput,
    ModuleDeploymentProfileRead,
    ModuleDeploymentRead,
    ModuleDeploymentRequest,
    ModuleRepositoryProvisionInput,
    ModuleRepositoryProvisionRead,
)
from app.services import module_deployment_service
from app.services.coolify_module_client import CoolifyModuleError
from app.services.github_module_publisher_service import ModulePublisherError, provision_repository

router = APIRouter(prefix="/module-publisher")


@router.post("/repositories", response_model=ModuleRepositoryProvisionRead)
async def provision_module_repository_endpoint(
    data: ModuleRepositoryProvisionInput,
    response: Response,
    auth: AuthenticatedKey = Depends(authenticate_request),
    db: AsyncSession = Depends(get_db),
):
    if auth.scope_type != "organization":
        raise HTTPException(status_code=403, detail="An organization-scoped publish key is required")
    organization = await db.get(Organization, auth.organization_id)
    if organization is None or organization.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        repository = await provision_repository(
            organization.slug,
            organization.name,
            data.module_slug,
            data.module_name,
        )
    except ModulePublisherError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response.headers["cache-control"] = "no-store"
    response.headers["pragma"] = "no-cache"
    return ModuleRepositoryProvisionRead(**repository.__dict__)


@router.get(
    "/organizations/{org_id}/deployment-profile",
    response_model=ModuleDeploymentProfileRead,
)
async def get_module_deployment_profile_endpoint(
    org_id: UUID,
    runtime_key: str | None = None,
    _: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    profile = await module_deployment_service.get_profile(db, org_id, runtime_key)
    if profile is None:
        raise HTTPException(status_code=404, detail="Module deployment profile not found")
    return ModuleDeploymentProfileRead(
        id=profile.id,
        organization_id=profile.organization_id,
        runtime_key=profile.runtime_key,
        server_uuid=profile.server_uuid,
        project_uuid=profile.project_uuid,
        environment_name=profile.environment_name,
        environment_uuid=profile.environment_uuid,
        destination_uuid=profile.destination_uuid,
        github_app_uuid=profile.github_app_uuid,
        domain_suffix=profile.domain_suffix,
        use_build_server=profile.use_build_server,
        is_default=profile.is_default,
        is_active=profile.is_active,
        deployer_configured=settings.coolify_module_deployer_configured,
    )


@router.put(
    "/organizations/{org_id}/deployment-profile",
    response_model=ModuleDeploymentProfileRead,
)
async def save_module_deployment_profile_endpoint(
    org_id: UUID,
    data: ModuleDeploymentProfileInput,
    _: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    organization = await db.get(Organization, org_id)
    if organization is None or organization.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Organization not found")
    profile = await module_deployment_service.save_profile(db, org_id, data)
    return ModuleDeploymentProfileRead(
        id=profile.id,
        organization_id=profile.organization_id,
        **data.model_dump(exclude={"is_default"}),
        is_default=profile.is_default,
        deployer_configured=settings.coolify_module_deployer_configured,
    )


@router.post("/deployments", response_model=ModuleDeploymentRead)
async def deploy_module_endpoint(
    data: ModuleDeploymentRequest,
    auth: AuthenticatedKey = Depends(authenticate_request),
    db: AsyncSession = Depends(get_db),
):
    if auth.scope_type != "organization":
        raise HTTPException(status_code=403, detail="An organization-scoped publish key is required")
    organization = await db.get(Organization, auth.organization_id)
    if organization is None or organization.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Organization not found")
    deployment = await module_deployment_service.request_deployment(db, organization, data)
    return ModuleDeploymentRead(**module_deployment_service.deployment_read(deployment))


@router.get("/deployments/{module_slug}", response_model=ModuleDeploymentRead)
async def get_module_deployment_endpoint(
    module_slug: str,
    auth: AuthenticatedKey = Depends(authenticate_request),
    db: AsyncSession = Depends(get_db),
):
    if auth.scope_type != "organization":
        raise HTTPException(status_code=403, detail="An organization-scoped publish key is required")
    deployment = await module_deployment_service.get_deployment(
        db, auth.organization_id, module_slug
    )
    if deployment is None:
        raise HTTPException(status_code=404, detail="Module deployment not found")
    try:
        if deployment.status in module_deployment_service.ACTIVE_STATES:
            deployment = await module_deployment_service.refresh_deployment(db, deployment)
    except CoolifyModuleError as exc:
        raise HTTPException(status_code=503, detail=f"{exc.stage}: {exc.detail}") from exc
    return ModuleDeploymentRead(**module_deployment_service.deployment_read(deployment))
