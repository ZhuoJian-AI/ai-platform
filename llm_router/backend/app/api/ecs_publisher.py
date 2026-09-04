"""Admin bootstrap and runtime-authenticated direct-ECS publisher APIs."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import CurrentAdmin, require_org_access, require_org_access_write
from app.auth.ecs_publisher_auth import authenticate_ecs_runtime
from app.config import settings
from app.database import get_db
from app.models.ecs_runtime import EcsRuntime
from app.models.organization import Organization
from app.schemas.ecs_publisher import (
    EcsModulePublishInput,
    EcsModuleReleaseIntentInput,
    EcsModuleReleaseRead,
    EcsRuntimeCreate,
    EcsRuntimeCredentialRead,
    EcsRuntimeRead,
    EcsRuntimeStateInput,
)
from app.services import ecs_publisher_service

router = APIRouter(prefix="/ecs-publisher")


def _no_store(response: Response) -> None:
    response.headers["cache-control"] = "no-store"
    response.headers["pragma"] = "no-cache"


async def _runtime_or_404(
    db: AsyncSession, organization_id: UUID, runtime_id: UUID
) -> EcsRuntime:
    runtime = await ecs_publisher_service.get_runtime(db, organization_id, runtime_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail="ECS runtime not found")
    return runtime


@router.post(
    "/organizations/{org_id}/runtimes",
    response_model=EcsRuntimeCredentialRead,
    status_code=201,
)
async def create_runtime_endpoint(
    org_id: UUID,
    data: EcsRuntimeCreate,
    response: Response,
    _: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    organization = await db.get(Organization, org_id)
    if organization is None or organization.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Organization not found")
    runtime, credential = await ecs_publisher_service.create_runtime(db, organization, data)
    _no_store(response)
    return EcsRuntimeCredentialRead(
        runtime=EcsRuntimeRead.model_validate(runtime),
        credential=credential,
        runtime_profile=ecs_publisher_service.runtime_profile(
            runtime, settings.module_saas_origin
        ),
    )


@router.get(
    "/organizations/{org_id}/runtimes",
    response_model=list[EcsRuntimeRead],
)
async def list_runtimes_endpoint(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access),
    db: AsyncSession = Depends(get_db),
):
    return await ecs_publisher_service.list_runtimes(db, org_id)


@router.post(
    "/organizations/{org_id}/runtimes/{runtime_id}/rotate-credential",
    response_model=EcsRuntimeCredentialRead,
)
async def rotate_runtime_credential_endpoint(
    org_id: UUID,
    runtime_id: UUID,
    response: Response,
    _: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    runtime = await _runtime_or_404(db, org_id, runtime_id)
    credential = await ecs_publisher_service.rotate_credential(db, runtime)
    _no_store(response)
    return EcsRuntimeCredentialRead(
        runtime=EcsRuntimeRead.model_validate(runtime),
        credential=credential,
        runtime_profile=ecs_publisher_service.runtime_profile(
            runtime, settings.module_saas_origin
        ),
    )


@router.patch(
    "/organizations/{org_id}/runtimes/{runtime_id}",
    response_model=EcsRuntimeRead,
)
async def set_runtime_state_endpoint(
    org_id: UUID,
    runtime_id: UUID,
    data: EcsRuntimeStateInput,
    _: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    runtime = await _runtime_or_404(db, org_id, runtime_id)
    return await ecs_publisher_service.set_runtime_active(db, runtime, data.is_active)


@router.post("/modules/register", response_model=EcsModuleReleaseRead)
async def register_module_endpoint(
    data: EcsModulePublishInput,
    runtime: EcsRuntime = Depends(authenticate_ecs_runtime),
    db: AsyncSession = Depends(get_db),
):
    return await ecs_publisher_service.register_module(db, runtime, data)


@router.post("/modules/{application_slug}/begin-change", status_code=204)
async def begin_module_change_endpoint(
    application_slug: str,
    data: EcsModuleReleaseIntentInput,
    runtime: EcsRuntime = Depends(authenticate_ecs_runtime),
    db: AsyncSession = Depends(get_db),
):
    await ecs_publisher_service.begin_release_change(
        db,
        runtime,
        application_slug,
        data.target_commit,
    )


@router.post("/modules/{application_slug}/cancel-change", status_code=204)
async def cancel_module_change_endpoint(
    application_slug: str,
    data: EcsModuleReleaseIntentInput,
    runtime: EcsRuntime = Depends(authenticate_ecs_runtime),
    db: AsyncSession = Depends(get_db),
):
    await ecs_publisher_service.cancel_release_change(
        db,
        runtime,
        application_slug,
        data.target_commit,
    )


@router.get("/modules/{application_slug}", response_model=EcsModuleReleaseRead)
async def get_module_release_endpoint(
    application_slug: str,
    runtime: EcsRuntime = Depends(authenticate_ecs_runtime),
    db: AsyncSession = Depends(get_db),
):
    release = await ecs_publisher_service.get_release(
        db, runtime.organization_id, application_slug
    )
    if release is None or release.runtime_id != runtime.id:
        raise HTTPException(status_code=404, detail="Module release not found")
    return release
