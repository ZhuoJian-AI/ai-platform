"""Agent test playground API — run an agent (stream/non-stream) + list runs."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_agent_graph, run_agent, stream_agent
from app.auth.admin_auth import (
    CurrentAdmin,
    assert_org_access,
    assert_org_write_access,
    require_admin,
)
from app.database import get_db
from app.models.agent import Agent
from app.models.agent_run import AgentRun
from app.schemas.agent import AgentRunRead

router = APIRouter()


class PlaygroundRequest(BaseModel):
    message: str
    session_id: str | None = None
    stream: bool = False


async def _load_agent_or_404(db: AsyncSession, agent_id: UUID) -> Agent:
    from app.services.agent_service import get_agent
    agent = await get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/agents/{agent_id}/playground")
async def playground_endpoint(
    agent_id: UUID,
    data: PlaygroundRequest,
    request: Request,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """测试广场：运行智能体。stream=true 返回 SSE，否则返回最终结果。"""
    agent = await _load_agent_or_404(db, agent_id)
    assert_org_write_access(auth, agent.organization_id)
    graph = get_agent_graph()
    if data.stream:
        return await stream_agent(
            graph,
            agent_id=str(agent.id), org_id=str(agent.organization_id),
            message=data.message, session_id=data.session_id,
            db=db, request=request, admin=auth,
        )
    result = await run_agent(
        graph,
        agent_id=str(agent.id), org_id=str(agent.organization_id),
        message=data.message, session_id=data.session_id,
        db=db, request=request, admin=auth,
    )
    return result


@router.get("/agents/{agent_id}/runs")
async def list_runs_endpoint(
    agent_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """列出智能体的执行记录（测试历史）。"""
    agent = await _load_agent_or_404(db, agent_id)
    assert_org_access(auth, agent.organization_id)
    query = (
        select(AgentRun)
        .where(AgentRun.agent_id == agent_id)
        .order_by(AgentRun.created_at.desc())
        .offset(offset).limit(limit)
    )
    rows = (await db.execute(query)).scalars().all()
    total = (await db.execute(
        select(func.count()).select_from(AgentRun).where(AgentRun.agent_id == agent_id)
    )).scalar() or 0
    return {
        "total": total, "offset": offset, "limit": limit,
        "data": [AgentRunRead.model_validate(r).model_dump() for r in rows],
    }
