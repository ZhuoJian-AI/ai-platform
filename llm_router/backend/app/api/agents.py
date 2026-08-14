"""Agent CRUD API."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import (
    CurrentAdmin,
    assert_org_access,
    assert_org_write_access,
    require_admin,
    require_org_access,
    require_org_access_write,
)
from app.database import get_db
from app.schemas.agent import AgentCreate, AgentRead, AgentUpdate
from app.services.agent_service import (
    create_agent,
    get_agent,
    list_agents,
    soft_delete_agent,
    update_agent,
)

router = APIRouter()


@router.post("/organizations/{org_id}/agents", response_model=AgentRead, status_code=201)
async def create_agent_endpoint(
    org_id: UUID, data: AgentCreate,
    _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    try:
        return await create_agent(db, org_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists in this scope")


@router.get("/organizations/{org_id}/agents", response_model=list[AgentRead])
async def list_agents_endpoint(
    org_id: UUID,
    scope_type: str | None = Query(default=None, description="organization/department/team/user"),
    scope_id: str | None = Query(default=None),
    _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    return await list_agents(db, org_id, scope_type=scope_type, scope_id=scope_id)


@router.get("/agents/{agent_id}", response_model=AgentRead)
async def get_agent_endpoint(
    agent_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    agent = await get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    assert_org_access(auth, agent.organization_id)
    return agent


@router.patch("/agents/{agent_id}", response_model=AgentRead)
async def update_agent_endpoint(
    agent_id: UUID, data: AgentUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    agent = await get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    assert_org_write_access(auth, agent.organization_id)
    return await update_agent(db, agent, data)


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent_endpoint(
    agent_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    agent = await get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    assert_org_write_access(auth, agent.organization_id)
    await soft_delete_agent(db, agent)
