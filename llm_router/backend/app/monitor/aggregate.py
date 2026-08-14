"""Monitor aggregation helpers — org-scoped time-bucketed metrics.

复用 audit_logs（路由器）/ agent_runs（智能体）/ tool_call_logs（工具）三套落库表，
按 budget.py 的实时聚合范式统计。所有查询按 organization_id 作用域过滤。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.audit_log import AuditLog
from app.models.connector import ToolConnector, ToolEndpoint
from app.models.data_interface import DataInterface, DataSystem
from app.models.llm_provider import LlmProvider
from app.models.ontology import OntologyFile, OntologyFolder
from app.models.skill import SkillFile, SkillFolder
from app.models.tool_call_log import ToolCallLog


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
    """按 agent_runs.steps 聚合三大组件（工作空间 / RAG / 长期记忆）用量。

    steps 是节点逐步轨迹 JSONB：rag 步含 hits/collections，memory 步含 facts/history，
    extract_memory 步含 facts，tool 步含 name/ok。工作空间经内置工具 workspace_* 触发。
    """
    from sqlalchemy import text
    sql = text("""
        WITH rs AS (
            SELECT id, steps FROM agent_runs
            WHERE organization_id = :org AND created_at >= :s AND created_at < :e
        ), elems AS (
            SELECT rs.id, je.elem
            FROM rs, jsonb_array_elements(COALESCE(rs.steps, '[]'::jsonb)) AS je(elem)
        )
        SELECT
            count(DISTINCT CASE
                WHEN elem->>'step' = 'tool' AND (elem->>'name') LIKE 'workspace_%' THEN id
            END) AS workspace_runs,
            count(*) FILTER (
                WHERE elem->>'step' = 'tool' AND (elem->>'name') LIKE 'workspace_%'
            ) AS workspace_ops,
            count(DISTINCT CASE WHEN elem->>'step' = 'rag' THEN id END) AS rag_runs,
            coalesce(sum((elem->>'hits')::int) FILTER (WHERE elem->>'step' = 'rag'), 0) AS rag_hits,
            count(DISTINCT CASE WHEN elem->>'step' = 'memory' THEN id END) AS memory_load_runs,
            coalesce(sum((elem->>'facts')::int) FILTER (WHERE elem->>'step' = 'memory'), 0)
                AS memory_facts_loaded,
            count(DISTINCT CASE WHEN elem->>'step' = 'extract_memory' THEN id END) AS memory_extract_runs,
            coalesce(sum((elem->>'facts')::int) FILTER (WHERE elem->>'step' = 'extract_memory'), 0)
                AS memory_facts_saved
        FROM elems
    """)
    row = (await db.execute(sql, {"org": org_id, "s": start, "e": end})).one()
    return {
        "workspace": {"runs": int(row.workspace_runs or 0), "ops": int(row.workspace_ops or 0)},
        "rag": {"runs": int(row.rag_runs or 0), "hits": int(row.rag_hits or 0)},
        "memory": {
            "load_runs": int(row.memory_load_runs or 0),
            "facts_loaded": int(row.memory_facts_loaded or 0),
            "extract_runs": int(row.memory_extract_runs or 0),
            "facts_saved": int(row.memory_facts_saved or 0),
        },
    }


# ── Tool (tool_call_logs) ──────────────────────────────────────────────

def _err_cond():
    """工具调用错误判定：有 error 文本 或 HTTP 状态 >= 400。"""
    return ToolCallLog.error.is_not(None) | (ToolCallLog.status_code >= 400)


async def _tool_by_connector(db: AsyncSession, base: list) -> list[dict]:
    """按连接器聚合（仅窗口内有调用的连接器）：调用/错误/延迟/最近调用 + 连接器元信息。"""
    rows = (await db.execute(
        select(
            ToolCallLog.connector_id,
            func.count().label("calls"),
            func.sum(case((_err_cond(), 1), else_=0)).label("errors"),
            func.coalesce(func.avg(ToolCallLog.latency_ms), 0).label("avg_lat"),
            func.max(ToolCallLog.created_at).label("last_called"),
        ).where(*base).group_by(ToolCallLog.connector_id)
    )).all()
    conn_ids = {str(r.connector_id) for r in rows if r.connector_id}
    meta: dict[str, ToolConnector] = {}
    if conn_ids:
        got = (await db.execute(
            select(ToolConnector).where(
                ToolConnector.id.in_([UUID(c) for c in conn_ids]),
                ToolConnector.deleted_at.is_(None),
            )
        )).scalars().all()
        meta = {str(c.id): c for c in got}
    out = []
    for r in rows:
        cid = str(r.connector_id) if r.connector_id else None
        c = meta.get(cid) if cid else None
        calls = int(r.calls)
        errs = int(r.errors or 0)
        out.append({
            "connector_id": cid,
            "connector_name": c.name if c else "(未关联)",
            "type": c.type if c else None,
            "is_active": bool(c.is_active) if c else None,
            "health_status": c.health_status if c else "unknown",
            "calls": calls,
            "error_count": errs,
            "error_rate": round(errs / calls, 4) if calls else 0.0,
            "avg_latency_ms": round(float(r.avg_lat), 2),
            "last_called_at": r.last_called.isoformat() if r.last_called else None,
        })
    out.sort(key=lambda x: x["calls"], reverse=True)
    return out


async def _tool_by_skill(db: AsyncSession, base: list) -> list[dict]:
    """按技能（SkillFolder.id）聚合：调用/错误/延迟 + 技能名/作用域。"""
    rows = (await db.execute(
        select(
            ToolCallLog.skill_id,
            func.count().label("calls"),
            func.sum(case((_err_cond(), 1), else_=0)).label("errors"),
            func.coalesce(func.avg(ToolCallLog.latency_ms), 0).label("avg_lat"),
        ).where(*base, ToolCallLog.skill_id.is_not(None)).group_by(ToolCallLog.skill_id)
    )).all()
    skill_ids = {str(r.skill_id) for r in rows if r.skill_id}
    meta: dict[str, SkillFolder] = {}
    if skill_ids:
        got = (await db.execute(
            select(SkillFolder).where(
                SkillFolder.id.in_([UUID(s) for s in skill_ids]),
                SkillFolder.deleted_at.is_(None),
            )
        )).scalars().all()
        meta = {str(s.id): s for s in got}
    out = []
    for r in rows:
        sid = str(r.skill_id)
        sf = meta.get(sid)
        calls = int(r.calls)
        errs = int(r.errors or 0)
        out.append({
            "skill_id": sid,
            "skill_name": sf.name if sf else "(已删除)",
            "scope_type": sf.scope_type if sf else None,
            "scope_id": str(sf.scope_id) if (sf and sf.scope_id) else None,
            "calls": calls,
            "error_count": errs,
            "error_rate": round(errs / calls, 4) if calls else 0.0,
            "avg_latency_ms": round(float(r.avg_lat), 2),
        })
    out.sort(key=lambda x: x["calls"], reverse=True)
    return out


async def _tool_by_endpoint(db: AsyncSession, base: list) -> list[dict]:
    """按端点（ToolEndpoint.id）聚合：调用/错误/延迟 + 端点/连接器元信息。"""
    rows = (await db.execute(
        select(
            ToolCallLog.endpoint_id,
            func.count().label("calls"),
            func.sum(case((_err_cond(), 1), else_=0)).label("errors"),
            func.coalesce(func.avg(ToolCallLog.latency_ms), 0).label("avg_lat"),
        ).where(*base, ToolCallLog.endpoint_id.is_not(None)).group_by(ToolCallLog.endpoint_id)
    )).all()
    ep_ids = {str(r.endpoint_id) for r in rows if r.endpoint_id}
    eps: dict[str, ToolEndpoint] = {}
    conn_names: dict[str, str] = {}
    if ep_ids:
        got = (await db.execute(
            select(ToolEndpoint).where(
                ToolEndpoint.id.in_([UUID(e) for e in ep_ids]),
                ToolEndpoint.deleted_at.is_(None),
            )
        )).scalars().all()
        eps = {str(e.id): e for e in got}
        cids = {str(e.connector_id) for e in got}
        if cids:
            crows = (await db.execute(
                select(ToolConnector.id, ToolConnector.name).where(
                    ToolConnector.id.in_([UUID(c) for c in cids]),
                    ToolConnector.deleted_at.is_(None),
                )
            )).all()
            conn_names = {str(c.id): c.name for c in crows}
    out = []
    for r in rows:
        eid = str(r.endpoint_id)
        ep = eps.get(eid)
        calls = int(r.calls)
        errs = int(r.errors or 0)
        out.append({
            "endpoint_id": eid,
            "endpoint_name": ep.name if ep else "(已删除)",
            "connector_name": conn_names.get(str(ep.connector_id)) if ep else "(已删除)",
            "method": ep.method if ep else None,
            "path": ep.path if ep else None,
            "calls": calls,
            "error_count": errs,
            "error_rate": round(errs / calls, 4) if calls else 0.0,
            "avg_latency_ms": round(float(r.avg_lat), 2),
        })
    out.sort(key=lambda x: x["calls"], reverse=True)
    return out


async def _tool_inventory(db: AsyncSession, org_id: UUID) -> dict:
    """四组件资源盘点（全量，不按时间窗口）：连接器 / 数据接口 / 技能 / 本体。"""
    org = str(org_id)
    soft = ToolConnector.deleted_at.is_(None)
    conn_total = (await db.execute(
        select(func.count()).select_from(ToolConnector)
        .where(ToolConnector.organization_id == org, soft)
    )).scalar() or 0
    conn_active = (await db.execute(
        select(func.count()).select_from(ToolConnector)
        .where(ToolConnector.organization_id == org, soft, ToolConnector.is_active.is_(True))
    )).scalar() or 0
    health_rows = (await db.execute(
        select(ToolConnector.health_status, func.count())
        .where(ToolConnector.organization_id == org, soft)
        .group_by(ToolConnector.health_status)
    )).all()
    by_health = {str(h or "unknown"): int(c) for h, c in health_rows}

    ds_total = (await db.execute(
        select(func.count()).select_from(DataSystem)
        .where(DataSystem.organization_id == org, DataSystem.deleted_at.is_(None))
    )).scalar() or 0
    di_rows = (await db.execute(
        select(func.count(), func.sum(case((DataInterface.is_active.is_(True), 1), else_=0)))
        .select_from(DataInterface).join(DataSystem, DataInterface.data_system_id == DataSystem.id)
        .where(DataSystem.organization_id == org, DataInterface.deleted_at.is_(None))
    )).one()
    di_total = int(di_rows[0] or 0)
    di_active = int(di_rows[1] or 0)

    sf_total = (await db.execute(
        select(func.count()).select_from(SkillFolder)
        .where(SkillFolder.organization_id == org, SkillFolder.deleted_at.is_(None))
    )).scalar() or 0
    sfile_total = (await db.execute(
        select(func.count()).select_from(SkillFile).join(SkillFolder, SkillFile.skill_folder_id == SkillFolder.id)
        .where(SkillFolder.organization_id == org, SkillFile.deleted_at.is_(None))
    )).scalar() or 0

    of_total = (await db.execute(
        select(func.count()).select_from(OntologyFolder)
        .where(OntologyFolder.organization_id == org, OntologyFolder.deleted_at.is_(None))
    )).scalar() or 0
    ofile_total = (await db.execute(
        select(func.count()).select_from(OntologyFile)
        .where(OntologyFile.organization_id == org, OntologyFile.deleted_at.is_(None))
    )).scalar() or 0

    return {
        "connectors": {
            "total": int(conn_total),
            "active": int(conn_active),
            "inactive": int(conn_total) - int(conn_active),
            "by_health": by_health,
        },
        "data_interfaces": {
            "systems_total": int(ds_total),
            "interfaces_total": di_total,
            "active": di_active,
            "inactive": di_total - di_active,
        },
        "skills": {"folders_total": int(sf_total), "files_total": int(sfile_total)},
        "ontology": {"folders_total": int(of_total), "files_total": int(ofile_total)},
    }


async def tool_metrics(
    db: AsyncSession, org_id: UUID, start: datetime | None, end: datetime | None,
) -> dict:
    s, e = _window(start, end)
    base = [
        ToolCallLog.organization_id == str(org_id),
        ToolCallLog.created_at >= s,
        ToolCallLog.created_at < e,
    ]
    total = (await db.execute(
        select(func.count()).select_from(ToolCallLog).where(*base)
    )).scalar() or 0
    err_cond = _err_cond()
    errors = (await db.execute(
        select(func.count()).select_from(ToolCallLog).where(*base, err_cond)
    )).scalar() or 0
    avg_lat = (await db.execute(
        select(func.coalesce(func.avg(ToolCallLog.latency_ms), 0))
        .where(*base, ToolCallLog.latency_ms.is_not(None))
    )).scalar() or 0

    by_connector = await _tool_by_connector(db, base)
    by_skill = await _tool_by_skill(db, base)
    by_endpoint = await _tool_by_endpoint(db, base)
    inventory = await _tool_inventory(db, org_id)
    return {
        "calls": int(total),
        "success_count": int(total) - int(errors),
        "error_count": int(errors),
        "error_rate": round(errors / total, 4) if total else 0.0,
        "avg_latency_ms": round(float(avg_lat), 2),
        "by_connector": by_connector,
        "by_skill": by_skill,
        "by_endpoint": by_endpoint,
        "inventory": inventory,
    }


async def overview(
    db: AsyncSession, org_id: UUID, start: datetime | None, end: datetime | None,
) -> dict:
    r = await router_metrics(db, org_id, start, end)
    a = await agent_metrics(db, org_id, start, end)
    t = await tool_metrics(db, org_id, start, end)
    return {"router": r, "agent": a, "tool": t}
