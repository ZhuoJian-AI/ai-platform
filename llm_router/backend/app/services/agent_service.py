"""Agent service — CRUD for agent configurations."""

import re
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_auth import CurrentUser
from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentUpdate
from app.services import enterprise_application_service, subsystem_integration_service

_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")


def merged_application_context(
    agent: Agent,
    data: AgentUpdate,
) -> tuple[UUID | str | None, str | None, str | None]:
    """Resolve a partial update without allowing a half-bound application page."""

    provided = data.model_dump(exclude_unset=True)
    return (
        provided.get("application_id", agent.application_id),
        provided.get("module_key", agent.module_key),
        provided.get("page_key", agent.page_key),
    )


async def validate_application_context(
    db: AsyncSession,
    org_id: UUID | str,
    application_id: UUID | str | None,
    module_key: str | None,
    page_key: str | None,
    *,
    user: CurrentUser | None = None,
) -> None:
    """Validate a persisted Agent page against the current accepted Manifest.

    Administrators validate ownership and existence when saving. Terminal users
    additionally need live page permission. Runtime callers repeat this check so
    a later role or Manifest change takes effect immediately.
    """

    values = (application_id, module_key, page_key)
    if not any(value is not None for value in values):
        return
    if not all(value is not None for value in values):
        raise HTTPException(status_code=400, detail="业务应用、模块和页面必须同时设置")
    application = await enterprise_application_service.get_application(db, application_id)
    if (
        application is None
        or str(application.organization_id) != str(org_id)
        or not application.is_active
        or application.deleted_at is not None
    ):
        raise HTTPException(status_code=404, detail="业务应用不存在或已停用")
    integration = application.integration
    if integration is None or subsystem_integration_service.manifest_page(
        integration,
        str(module_key),
        str(page_key),
    ) is None:
        raise HTTPException(status_code=400, detail="所选模块或页面不在当前应用 Manifest 中")
    if user is not None and "view" not in enterprise_application_service.effective_page_permissions(
        application,
        user,
        str(module_key),
        str(page_key),
    ):
        raise HTTPException(status_code=403, detail="当前账号无权使用该业务页面")


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
    if payload.get("application_id") is not None:
        payload["application_id"] = str(payload["application_id"])
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
    if provided.get("application_id") is not None:
        provided["application_id"] = str(provided["application_id"])
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
