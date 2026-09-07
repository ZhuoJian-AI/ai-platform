"""Compatibility endpoints for the retired Team hierarchy.

Team is no longer an authorization or resource scope. Keep the old routes for
one compatibility window so stale administrator clients receive an explicit
Chinese response instead of an ambiguous 404.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.auth.admin_auth import CurrentAdmin, require_admin

router = APIRouter()

_TEAM_RETIRED = "Team 已停用，请使用部门归属和角色授权"


def _gone() -> None:
    raise HTTPException(status_code=410, detail=_TEAM_RETIRED)


@router.post("/departments/{dept_id}/teams", status_code=410)
async def create_team_endpoint(
    dept_id: UUID,  # noqa: ARG001 - compatibility path
    auth: CurrentAdmin = Depends(require_admin),  # noqa: ARG001
):
    _gone()


@router.get("/departments/{dept_id}/teams", status_code=410)
async def list_teams_endpoint(
    dept_id: UUID,  # noqa: ARG001 - compatibility path
    auth: CurrentAdmin = Depends(require_admin),  # noqa: ARG001
):
    _gone()


@router.get("/teams/{team_id}", status_code=410)
async def get_team_endpoint(
    team_id: UUID,  # noqa: ARG001 - compatibility path
    auth: CurrentAdmin = Depends(require_admin),  # noqa: ARG001
):
    _gone()


@router.patch("/teams/{team_id}", status_code=410)
async def update_team_endpoint(
    team_id: UUID,  # noqa: ARG001 - compatibility path
    auth: CurrentAdmin = Depends(require_admin),  # noqa: ARG001
):
    _gone()


@router.delete("/teams/{team_id}", status_code=410)
async def delete_team_endpoint(
    team_id: UUID,  # noqa: ARG001 - compatibility path
    auth: CurrentAdmin = Depends(require_admin),  # noqa: ARG001
):
    _gone()
