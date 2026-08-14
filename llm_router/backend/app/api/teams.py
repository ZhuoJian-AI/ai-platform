"""Teams CRUD API."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import (
    CurrentAdmin,
    assert_org_access,
    assert_org_write_access,
    require_admin,
)
from app.database import get_db
from app.schemas.organization import TeamCreate, TeamRead, TeamUpdate
from app.services.organization_service import (
    create_team,
    get_department,
    get_team,
    list_teams,
    soft_delete_team,
    update_team,
)

router = APIRouter()


@router.post("/departments/{dept_id}/teams", response_model=TeamRead, status_code=201)
async def create_team_endpoint(dept_id: UUID, data: TeamCreate, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    dept = await get_department(db, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    assert_org_write_access(auth, dept.organization_id)
    try:
        return await create_team(db, dept_id, dept.organization_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists in this department")


@router.get("/departments/{dept_id}/teams", response_model=list[TeamRead])
async def list_teams_endpoint(dept_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    dept = await get_department(db, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    assert_org_access(auth, dept.organization_id)
    return await list_teams(db, dept_id)


@router.get("/teams/{team_id}", response_model=TeamRead)
async def get_team_endpoint(team_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    team = await get_team(db, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    assert_org_access(auth, team.organization_id)
    return team


@router.patch("/teams/{team_id}", response_model=TeamRead)
async def update_team_endpoint(team_id: UUID, data: TeamUpdate, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    team = await get_team(db, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    assert_org_write_access(auth, team.organization_id)
    try:
        return await update_team(db, team, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists in this department")


@router.delete("/teams/{team_id}", status_code=204)
async def delete_team_endpoint(team_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    team = await get_team(db, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    assert_org_write_access(auth, team.organization_id)
    await soft_delete_team(db, team)
