"""LLM Request Router — model→provider mapping with load balancing and failover.

提供商支持组织/部门/团队三级作用域。调用解析遵循 **团队级 > 部门级 > 组织级**
优先级且可继承：团队调用方候选含 团队+部门+组织级；部门调用方含 部门+组织级；
组织调用方仅组织级。同模型命中多级时，优先取最高层级（scope_rank 降序），同层级再按
provider.priority 降序。
"""

from __future__ import annotations

import fnmatch
import random
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_provider import LlmProvider
from app.models.routing_policy import RoutingPolicy


# 层级权重：团队 > 部门 > 组织。用于候选排序与「优先」策略的复合键。
_SCOPE_RANK = {"team": 3, "department": 2, "organization": 1}


def _scope_rank(p: LlmProvider) -> int:
    return _SCOPE_RANK.get(p.scope_type, 0)


async def find_provider(
    db: AsyncSession,
    org_id: UUID,
    model: str,
    preferred_type: str | None = None,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> LlmProvider | None:
    """根据路由策略找到支持指定模型的提供商。

    dept_id/team_id 取自调用方作用域（API Key 或智能体运行时 scope），用于按
    团队>部门>组织 优先级筛选继承候选。
    """
    # 查找匹配的路由策略
    result = await db.execute(
        select(RoutingPolicy).where(
            RoutingPolicy.organization_id == org_id,
            RoutingPolicy.deleted_at.is_(None),
        ).order_by(RoutingPolicy.is_default.asc())  # 非默认策略优先
    )
    policies = list(result.scalars().all())

    for policy in policies:
        if fnmatch.fnmatch(model, policy.model_pattern):
            provider = await _select_provider(db, org_id, policy, model, preferred_type, dept_id, team_id)
            if provider:
                return provider

    # 如果没有匹配的策略，尝试直接查找支持该模型的提供商
    return await _find_any_provider(db, org_id, model, preferred_type, dept_id, team_id)


async def _select_provider(
    db: AsyncSession,
    org_id: UUID,
    policy: RoutingPolicy,
    model: str,
    preferred_type: str | None = None,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> LlmProvider | None:
    """按策略选择提供商。"""
    # 获取策略配置的提供商（已按 团队>部门>组织 优先级排序）
    providers = await _get_active_providers(db, org_id, policy.provider_ids, model, preferred_type, dept_id, team_id)
    if not providers:
        return None

    if policy.strategy == "priority":
        # 复合键：层级优先，同层级再按 priority
        return max(providers, key=lambda p: (_scope_rank(p), p.priority))
    elif policy.strategy == "round_robin":
        return providers[random.randint(0, len(providers) - 1)]  # noqa: S311
    elif policy.strategy == "weighted":
        return _weighted_select(providers)
    elif policy.strategy == "least_latency":
        # 简化实现：选 health_status 最好的（候选已按层级降序，故同健康度下取更高层级）
        healthy = [p for p in providers if p.health_status == "healthy"]
        return healthy[0] if healthy else providers[0]
    elif policy.strategy == "failover":
        return providers[0]  # 第一个（最高层级）为主，其余在失败时使用
    else:
        return providers[0]


def _scope_clause(dept_id: str | UUID | None, team_id: str | UUID | None):
    """构造调用方作用域筛选条件：组织级（全员可见）+ 本部门 + 本团队。"""
    branches = [LlmProvider.scope_type == "organization"]
    if dept_id:
        branches.append((LlmProvider.scope_type == "department") & (LlmProvider.department_id == str(dept_id)))
    if team_id:
        branches.append((LlmProvider.scope_type == "team") & (LlmProvider.team_id == str(team_id)))
    return or_(*branches)


async def _get_active_providers(
    db: AsyncSession,
    org_id: UUID,
    provider_ids: list,
    model: str,
    preferred_type: str | None = None,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> list[LlmProvider]:
    """获取活跃且支持指定模型的提供商列表（按 团队>部门>组织 + priority 降序）。"""
    result = await db.execute(
        select(LlmProvider).where(
            LlmProvider.organization_id == org_id,
            LlmProvider.id.in_([UUID(pid) if isinstance(pid, str) else pid for pid in provider_ids]),
            LlmProvider.is_active.is_(True),
            LlmProvider.deleted_at.is_(None),
            LlmProvider.health_status != "down",
            _scope_clause(dept_id, team_id),
        )
    )
    all_providers = list(result.scalars().all())

    # 过滤出支持该模型的提供商
    matched = [
        p for p in all_providers
        if not p.supported_models or model in p.supported_models or any(fnmatch.fnmatch(model, m) for m in p.supported_models)
    ]
    # 层级降序 + priority 降序
    matched.sort(key=lambda p: (_scope_rank(p), p.priority), reverse=True)

    # 如果指定了 preferred_type，优先返回该类型（保持层级+priority 排序）
    if preferred_type and matched:
        preferred = [p for p in matched if p.provider_type == preferred_type]
        if preferred:
            return preferred

    return matched


async def _find_any_provider(
    db: AsyncSession,
    org_id: UUID,
    model: str,
    preferred_type: str | None = None,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> LlmProvider | None:
    """未匹配路由策略时，直接查找支持该模型的提供商（团队>部门>组织 级联回退）。"""
    result = await db.execute(
        select(LlmProvider).where(
            LlmProvider.organization_id == org_id,
            LlmProvider.is_active.is_(True),
            LlmProvider.deleted_at.is_(None),
            LlmProvider.health_status != "down",
            _scope_clause(dept_id, team_id),
        )
    )
    providers = list(result.scalars().all())
    # 层级降序 + priority 降序，保证团队级优先、无团队级时回退部门/组织级
    providers.sort(key=lambda p: (_scope_rank(p), p.priority), reverse=True)

    # 如果指定了 preferred_type，优先查找该类型（在已排序候选中取首个匹配）
    if preferred_type:
        for provider in providers:
            if provider.provider_type == preferred_type:
                if not provider.supported_models or model in provider.supported_models:
                    return provider

    for provider in providers:
        if not provider.supported_models or model in provider.supported_models:
            return provider
    return None


def _weighted_select(providers: list[LlmProvider]) -> LlmProvider:
    """按权重随机选择提供商。"""
    total_weight = sum(p.weight for p in providers)
    r = random.randint(1, total_weight)  # noqa: S311
    cumulative = 0
    for p in providers:
        cumulative += p.weight
        if r <= cumulative:
            return p
    return providers[-1]
