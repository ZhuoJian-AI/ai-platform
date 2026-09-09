"""Monitor aggregation helpers — org-scoped time-bucketed metrics.

复用 audit_logs（路由器）、agent_runs（智能体）与 Manifest ActionRequest，
按 budget.py 的实时聚合范式统计。所有查询按 organization_id 作用域过滤。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.audit_log import AuditLog
from app.models.enterprise_application import (
    EnterpriseApplicationAction,
    EnterpriseApplicationActionRequest,
)
from app.models.llm_provider import LlmProvider


def default_window() -> tuple[datetime, datetime]:
    """默认最近 24 小时窗口 [start, end)。"""
    end = datetime.now(UTC)
    start = end - timedelta(hours=24)
    return start, end


def _window(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    s, e = default_window()
    return (start or s, end or e)


# ── Router (audit_logs) ────────────────────────────────────────────────

async def router_metrics(
    db: AsyncSession, org_id: UUID, start: datetime | None, end: datetime | None,
) -> dict:
    s, e = _window(start, end)
    base = [
        AuditLog.organization_id == str(org_id),
        AuditLog.created_at >= s,
        AuditLog.created_at < e,
    ]
    total = (await db.execute(
        select(func.count()).select_from(AuditLog).where(*base)
    )).scalar() or 0
    in_tok = (await db.execute(
        select(func.coalesce(func.sum(AuditLog.input_tokens), 0)).where(*base)
    )).scalar() or 0
    out_tok = (await db.execute(
        select(func.coalesce(func.sum(AuditLog.output_tokens), 0)).where(*base)
    )).scalar() or 0
    err_cond = (AuditLog.status_code >= 400) | (AuditLog.error_message.is_not(None))
    errors = (await db.execute(
        select(func.count()).select_from(AuditLog).where(*base, err_cond)
    )).scalar() or 0
    avg_lat = (await db.execute(
        select(func.coalesce(func.avg(AuditLog.latency_ms), 0))
        .where(*base, AuditLog.latency_ms.is_not(None))
    )).scalar() or 0
    dlp_hits = (await db.execute(
        select(func.count()).select_from(AuditLog)
        .where(*base, func.jsonb_array_length(AuditLog.dlp_violations) > 0)
    )).scalar() or 0

    # 按 provider 分组
    by_provider = (await db.execute(
        select(
            AuditLog.provider_id,
            func.count().label("reqs"),
            func.coalesce(func.sum(AuditLog.input_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(AuditLog.output_tokens), 0).label("out_tok"),
        ).where(*base).group_by(AuditLog.provider_id)
    )).all()
    provider_ids = {str(r.provider_id) for r in by_provider if r.provider_id}
    names: dict[str, str] = {}
    if provider_ids:
        rows = (await db.execute(
            select(LlmProvider.id, LlmProvider.name)
            .where(LlmProvider.id.in_([UUID(p) for p in provider_ids]))
        )).all()
        names = {str(r.id): r.name for r in rows}
    breakdown = [
        {"provider_id": str(r.provider_id) if r.provider_id else None,
         "provider_name": names.get(str(r.provider_id)) if r.provider_id else "(未关联)",
         "requests": int(r.reqs), "input_tokens": int(r.in_tok), "output_tokens": int(r.out_tok)}
        for r in by_provider
    ]

    return {
        "requests": int(total),
        "input_tokens": int(in_tok), "output_tokens": int(out_tok),
        "error_count": int(errors), "error_rate": round(errors / total, 4) if total else 0.0,
        "avg_latency_ms": round(float(avg_lat), 2),
        "dlp_violation_count": int(dlp_hits),
        "by_provider": breakdown,
    }


# ── Agent (agent_runs) ─────────────────────────────────────────────────

async def agent_metrics(
    db: AsyncSession, org_id: UUID, start: datetime | None, end: datetime | None,
) -> dict:
    s, e = _window(start, end)
    base = [
        AgentRun.organization_id == str(org_id),
        AgentRun.created_at >= s,
        AgentRun.created_at < e,
    ]
    total = (await db.execute(
        select(func.count()).select_from(AgentRun).where(*base)
    )).scalar() or 0
    success = (await db.execute(
        select(func.count()).select_from(AgentRun).where(*base, AgentRun.status == "success")
    )).scalar() or 0
    in_tok = (await db.execute(
        select(func.coalesce(func.sum(AgentRun.input_tokens), 0)).where(*base)
    )).scalar() or 0
    out_tok = (await db.execute(
        select(func.coalesce(func.sum(AgentRun.output_tokens), 0)).where(*base)
    )).scalar() or 0
    avg_lat = (await db.execute(
        select(func.coalesce(func.avg(AgentRun.latency_ms), 0))
        .where(*base, AgentRun.latency_ms.is_not(None))
    )).scalar() or 0

    from app.models.agent import Agent
    by_agent = (await db.execute(
        select(
            AgentRun.agent_id,
            AgentRun.exec_mode,
            func.count().label("runs"),
            func.coalesce(func.sum(AgentRun.input_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(AgentRun.output_tokens), 0).label("out_tok"),
        ).where(*base).group_by(AgentRun.agent_id, AgentRun.exec_mode)
    )).all()
    agent_ids = {str(r.agent_id) for r in by_agent if r.agent_id}
    names: dict[str, str] = {}
    if agent_ids:
        rows = (await db.execute(
            select(Agent.id, Agent.name)
            .where(Agent.id.in_([UUID(a) for a in agent_ids]))
        )).all()
        names = {str(r.id): r.name for r in rows}
    breakdown = []
    for r in by_agent:
        if r.agent_id:
            label = names.get(str(r.agent_id), "(已删除)")
            row_type = "agent"
        else:
            label = (r.exec_mode or "craft").capitalize()
            row_type = "general"
        breakdown.append({
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "exec_mode": r.exec_mode or "craft",
            "type": row_type,
            "agent_name": label,
            "runs": int(r.runs), "input_tokens": int(r.in_tok), "output_tokens": int(r.out_tok),
        })

    components = await _component_usage(db, str(org_id), s, e)
    return {
        "runs": int(total),
        "success_count": int(success),
        "success_rate": round(success / total, 4) if total else 0.0,
        "input_tokens": int(in_tok), "output_tokens": int(out_tok),
        "avg_latency_ms": round(float(avg_lat), 2),
        "by_agent": breakdown,
        "components": components,
    }


async def _component_usage(
    db: AsyncSession, org_id: str, start: datetime, end: datetime,
) -> dict:
    """Aggregate workspace and memory usage from durable run events.

    ``AgentRun.steps`` was a duplicate runtime snapshot and is no longer
    written. ``AgentRunEvent`` is the single replay and monitoring source.
    """
    from sqlalchemy import text
    sql = text("""
        WITH elems AS (
            SELECT r.id, e.payload AS elem
            FROM agent_runs AS r
            JOIN agent_run_events AS e ON e.run_id = r.id
            WHERE r.organization_id = :org AND r.created_at >= :s AND r.created_at < :e
        )
        SELECT
            count(DISTINCT CASE
                WHEN elem->>'type' = 'tool_result' AND (elem->>'name') LIKE 'workspace_%' THEN id
            END) AS workspace_runs,
            count(*) FILTER (
                WHERE elem->>'type' = 'tool_result' AND (elem->>'name') LIKE 'workspace_%'
            ) AS workspace_ops,
            count(DISTINCT CASE
                WHEN elem->>'type' = 'trace' AND elem->>'category' = 'memory'
                    AND elem->>'subtype' = 'load' THEN id
            END) AS memory_load_runs,
            coalesce(sum((elem->>'facts')::int) FILTER (
                WHERE elem->>'type' = 'trace' AND elem->>'category' = 'memory'
                    AND elem->>'subtype' = 'load'
            ), 0)
                AS memory_facts_loaded,
            count(DISTINCT CASE
                WHEN elem->>'type' = 'trace' AND elem->>'category' = 'memory'
                    AND elem->>'subtype' = 'extract' THEN id
            END) AS memory_extract_runs,
            coalesce(sum((elem->>'facts')::int) FILTER (
                WHERE elem->>'type' = 'trace' AND elem->>'category' = 'memory'
                    AND elem->>'subtype' = 'extract'
            ), 0)
                AS memory_facts_saved
        FROM elems
    """)
    row = (await db.execute(sql, {"org": org_id, "s": start, "e": end})).one()
    return {
        "workspace": {"runs": int(row.workspace_runs or 0), "ops": int(row.workspace_ops or 0)},
        "memory": {
            "load_runs": int(row.memory_load_runs or 0),
            "facts_loaded": int(row.memory_facts_loaded or 0),
            "extract_runs": int(row.memory_extract_runs or 0),
            "facts_saved": int(row.memory_facts_saved or 0),
        },
    }


# ── Tool (Manifest Action requests) ───────────────────────────────────


async def _tool_by_action(
    db: AsyncSession,
    org_id: UUID,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Aggregate active Manifest Action executions without consulting legacy connectors."""
    duration_ms = func.extract(
        "epoch",
        EnterpriseApplicationActionRequest.resolved_at - EnterpriseApplicationActionRequest.created_at,
    ) * 1000
    rows = (await db.execute(
        select(
            EnterpriseApplicationActionRequest.action_id,
            func.count().label("calls"),
            func.sum(
                case((EnterpriseApplicationActionRequest.status.in_(("failed", "expired")), 1), else_=0)
            ).label("errors"),
            func.coalesce(
                func.avg(duration_ms).filter(EnterpriseApplicationActionRequest.resolved_at.is_not(None)),
                0,
            ).label("avg_lat"),
        ).where(
            EnterpriseApplicationActionRequest.organization_id == str(org_id),
            EnterpriseApplicationActionRequest.created_at >= start,
            EnterpriseApplicationActionRequest.created_at < end,
        ).group_by(EnterpriseApplicationActionRequest.action_id)
    )).all()
    action_ids = {str(row.action_id) for row in rows if row.action_id}
    actions: dict[str, EnterpriseApplicationAction] = {}
    if action_ids:
        got = (await db.execute(
            select(EnterpriseApplicationAction).where(
                EnterpriseApplicationAction.id.in_([UUID(action_id) for action_id in action_ids]),
            )
        )).scalars().all()
        actions = {str(action.id): action for action in got}
    out = []
    for row in rows:
        action_id = str(row.action_id)
        action = actions.get(action_id)
        calls = int(row.calls)
        errors = int(row.errors or 0)
        out.append({
            "action_id": action_id,
            "action_key": action.action_key if action else "(已删除)",
            "action_name": action.name if action else "(已删除)",
            "module_key": action.module_key if action else None,
            "operation": action.operation if action else None,
            "calls": calls,
            "error_count": errors,
            "error_rate": round(errors / calls, 4) if calls else 0.0,
            "avg_latency_ms": round(float(row.avg_lat), 2),
        })
    out.sort(key=lambda item: item["calls"], reverse=True)
    return out


async def tool_metrics(
    db: AsyncSession, org_id: UUID, start: datetime | None, end: datetime | None,
) -> dict:
    s, e = _window(start, end)
    action_base = [
        EnterpriseApplicationActionRequest.organization_id == str(org_id),
        EnterpriseApplicationActionRequest.created_at >= s,
        EnterpriseApplicationActionRequest.created_at < e,
    ]
    action_total = (await db.execute(
        select(func.count()).select_from(EnterpriseApplicationActionRequest).where(*action_base)
    )).scalar() or 0
    action_errors = (await db.execute(
        select(func.count()).select_from(EnterpriseApplicationActionRequest).where(
            *action_base,
            EnterpriseApplicationActionRequest.status.in_(("failed", "expired")),
        )
    )).scalar() or 0
    action_duration_ms = func.extract(
        "epoch",
        EnterpriseApplicationActionRequest.resolved_at - EnterpriseApplicationActionRequest.created_at,
    ) * 1000
    action_latency = (await db.execute(
        select(
            func.count(EnterpriseApplicationActionRequest.resolved_at),
            func.coalesce(func.sum(action_duration_ms), 0),
        ).where(*action_base, EnterpriseApplicationActionRequest.resolved_at.is_not(None))
    )).one()

    by_action = await _tool_by_action(db, org_id, s, e)
    combined_total = int(action_total)
    combined_errors = int(action_errors)
    latency_count = int(action_latency[0] or 0)
    latency_sum = float(action_latency[1] or 0)
    return {
        "calls": combined_total,
        "success_count": combined_total - combined_errors,
        "error_count": combined_errors,
        "error_rate": round(combined_errors / combined_total, 4) if combined_total else 0.0,
        "avg_latency_ms": round(latency_sum / latency_count, 2) if latency_count else 0.0,
        "by_action": by_action,
        "inventory": {},
    }


async def overview(
    db: AsyncSession, org_id: UUID, start: datetime | None, end: datetime | None,
) -> dict:
    r = await router_metrics(db, org_id, start, end)
    a = await agent_metrics(db, org_id, start, end)
    t = await tool_metrics(db, org_id, start, end)
    return {"router": r, "agent": a, "tool": t}
