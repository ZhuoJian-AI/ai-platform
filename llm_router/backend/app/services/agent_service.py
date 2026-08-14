"""Agent service — CRUD for agent configurations."""

import re
import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentUpdate

_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """名称 → 合法 slug 片段（小写字母/数字/连字符）。非拉丁名称结果为空，由调用方兜底。"""
    s = name.lower().strip()
    s = _NON_SLUG_RE.sub("-", s).strip("-")
    return s[:80]


async def _unique_agent_slug(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: UUID | None, name: str,
) -> str:
    """按编码规则生成同 scope 内唯一的 slug：名称派生为 base；冲突则追加随机后缀。

    非拉丁名称 base 为空 → 兜底 ``agent``。org 级 scope_id 为 None 时按 IS NULL 匹配
    （Postgres 默认 NULL 不参与唯一约束，这里显式避让重复 slug，保持整洁）。
    注意：查询**不排除软删行**——DB 唯一约束 ``uq_agent_scope_slug`` 不含 deleted_at，
    软删后的 slug 仍被占用；故同名删后再建需走后缀，避免 IntegrityError→409。
    """
    base = _slugify(name) or "agent"
    candidate = base
    for _ in range(6):
        q = select(Agent.id).where(
            Agent.organization_id == org_id,
            Agent.scope_type == scope_type,
            Agent.slug == candidate,
        )
        if scope_id:
            q = q.where(Agent.scope_id == str(scope_id))
        else:
            q = q.where(Agent.scope_id.is_(None))
        if (await db.execute(q)).first() is None:
            return candidate
        candidate = f"{base}-{secrets.token_hex(3)}"
    return f"agent-{secrets.token_hex(6)}"


async def create_agent(
    db: AsyncSession, org_id: UUID, data: AgentCreate, *, created_by: UUID | None = None,
) -> Agent:
    """创建 agent。created_by 由调用方注入（终端用户=cu.id；admin/历史=None），
    不在 AgentCreate schema 内，避免管理端旧调用传入。"""
    payload = data.model_dump()
    # scope_id 是纯 String(36) 列（无 FK，不继承 UUID 类型），而 AgentCreate.scope_id
    # 被 Pydantic 解析成 UUID；asyncpg 拒收 UUID→varchar（"expected str, got UUID"），需转 str。
    if payload.get("scope_id") is not None:
        payload["scope_id"] = str(payload["scope_id"])
    # slug 未提供 → 按编码规则自动生成（名称派生 + 同 scope 内唯一）。
    if not payload.get("slug"):
        payload["slug"] = await _unique_agent_slug(db, org_id, data.scope_type, data.scope_id, data.name)
    agent = Agent(organization_id=org_id, created_by=created_by, **payload)
    db.add(agent)
    await db.flush()
    return agent


async def list_agents(
    db: AsyncSession, org_id: UUID,
    scope_type: str | None = None, scope_id: str | None = None,
) -> list[Agent]:
    """列出 org 下 agent；传 scope 则按作用域精确过滤（org 级 scope_id 为 None）。"""
    stmt = select(Agent).where(Agent.organization_id == org_id, Agent.deleted_at.is_(None))
    if scope_type:
        if scope_type == "organization":
            stmt = stmt.where(Agent.scope_type == "organization", Agent.scope_id.is_(None))
        else:
            stmt = stmt.where(Agent.scope_type == scope_type, Agent.scope_id == scope_id)
    return list((await db.execute(stmt)).scalars().all())


async def get_agent(db: AsyncSession, agent_id: UUID) -> Agent | None:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_agent(db: AsyncSession, agent: Agent, data: AgentUpdate) -> Agent:
    provided = data.model_dump(exclude_unset=True)
    for field, value in provided.items():
        setattr(agent, field, value)
    # 迁 scope 到 organization 时，显式清 scope_id（exclude_unset 下「未传 scope_id」≠「置空」）。
    if provided.get("scope_type") == "organization" and "scope_id" not in provided:
        agent.scope_id = None
    agent.version += 1
    await db.flush()
    await db.refresh(agent)
    return agent


async def soft_delete_agent(db: AsyncSession, agent: Agent) -> None:
    agent.deleted_at = datetime.now(UTC)
    await db.flush()
