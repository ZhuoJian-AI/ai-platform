"""Compatibility tombstones for the retired GitHub/Coolify module publisher.

Runtime registration and ECS publishing remain available through their own
APIs. These routes remain for one compatibility window so stale clients get an
explicit Chinese ``410 Gone`` response without importing the retired publisher
implementation or its credentials.
"""

from fastapi import APIRouter

from app.api.retirement import retired_api_dependency

router = APIRouter(
    prefix="/module-publisher",
    dependencies=[retired_api_dependency("旧 GitHub/Coolify 模块发布器")],
)


@router.post("/repositories", status_code=410)
async def retired_repository_provisioning():
    """Retained only so old publishers receive the router-level tombstone."""


@router.get("/organizations/{org_id}/deployment-profile", status_code=410)
async def retired_deployment_profile_read(org_id: str):  # noqa: ARG001
    """Retained only so old administrators receive the 410 response."""


@router.put("/organizations/{org_id}/deployment-profile", status_code=410)
async def retired_deployment_profile_write(org_id: str):  # noqa: ARG001
    """Retained only so old administrators receive the 410 response."""


@router.post("/deployments", status_code=410)
async def retired_deployment_request():
    """Retained only so old publishers receive the 410 response."""


@router.get("/deployments/{module_slug}", status_code=410)
async def retired_deployment_read(module_slug: str):  # noqa: ARG001
    """Retained only so old publishers receive the 410 response."""
