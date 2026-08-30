"""Tenant API for on-demand private module repository provisioning."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key_auth import AuthenticatedKey, authenticate_request
from app.database import get_db
from app.models.organization import Organization
from app.schemas.module_publisher import (
    ModuleRepositoryProvisionInput,
    ModuleRepositoryProvisionRead,
)
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
