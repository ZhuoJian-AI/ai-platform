"""Application monitor API — router / agent / tool metrics + overview."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import CurrentAdmin, require_org_access
from app.database import get_db
from app.monitor import aggregate

router = APIRouter()


@router.get("/organizations/{org_id}/monitor/overview")
async def overview_endpoint(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access),
    db: AsyncSession = Depends(get_db),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
):
    return await aggregate.overview(db, org_id, start_time, end_time)


@router.get("/organizations/{org_id}/monitor/router")
async def router_monitor_endpoint(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access),
    db: AsyncSession = Depends(get_db),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
):
    return await aggregate.router_metrics(db, org_id, start_time, end_time)


@router.get("/organizations/{org_id}/monitor/agents")
async def agent_monitor_endpoint(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access),
    db: AsyncSession = Depends(get_db),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
):
    return await aggregate.agent_metrics(db, org_id, start_time, end_time)


@router.get("/organizations/{org_id}/monitor/tools")
async def tool_monitor_endpoint(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access),
    db: AsyncSession = Depends(get_db),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
):
    return await aggregate.tool_metrics(db, org_id, start_time, end_time)
