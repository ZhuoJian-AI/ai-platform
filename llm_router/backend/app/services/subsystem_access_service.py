"""Live organization/application/runtime gates for every subsystem entry point."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ecs_runtime import EcsModuleRelease, EcsRuntime
from app.models.enterprise_application import EnterpriseApplication
from app.models.organization import Organization


async def assert_runtime_organization_active(
    db: AsyncSession, runtime: EcsRuntime
) -> Organization:
    organization = await db.get(Organization, runtime.organization_id)
    if organization is None or organization.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Subsystem organization is unavailable")
    if not runtime.is_active:
        raise HTTPException(status_code=409, detail="ECS runtime is disabled")
    return organization


async def assert_application_available(
    db: AsyncSession,
    application: EnterpriseApplication,
    *,
    require_application_active: bool = True,
    require_release_healthy: bool = True,
) -> None:
    if application.deleted_at is not None or (
        require_application_active and not application.is_active
    ):
        raise HTTPException(status_code=409, detail="Subsystem application is disabled")
    organization = await db.get(Organization, application.organization_id)
    if organization is None or organization.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Subsystem organization is unavailable")

    release = (
        await db.execute(
            select(EcsModuleRelease).where(
                EcsModuleRelease.organization_id == UUID(str(application.organization_id)),
                EcsModuleRelease.application_id == application.id,
            )
        )
    ).scalar_one_or_none()
    if release is None:
        return
    runtime = await db.get(EcsRuntime, release.runtime_id)
    if runtime is None or not runtime.is_active:
        raise HTTPException(status_code=409, detail="ECS runtime is disabled")
    if require_release_healthy and release.status != "healthy":
        raise HTTPException(
            status_code=409,
            detail="Subsystem release is not approved and healthy",
        )
