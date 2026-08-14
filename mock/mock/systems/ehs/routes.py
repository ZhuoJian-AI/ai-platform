"""EHS 路由——安全管理只读查询。全部 GET。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["EHS 安全管理"])


# ── 隐患 / 违章 ─────────────────────────────────────────────

@router.get("/hazards", operation_id="listHazards",
            summary="隐患台账（按状态/区域/级别过滤）")
def list_hazards(
    tenant: Annotated[str, Depends(get_tenant)],
    status: Annotated[str | None, Query(description="待整改/整改中/已闭环")] = None,
    level: Annotated[str | None, Query(description="红/橙/黄/蓝")] = None,
    area: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).hazards
    if status:
        rows = [r for r in rows if r["status"] == status]
    if level:
        rows = [r for r in rows if r["level"] == level]
    if area:
        rows = [r for r in rows if area in r["area"]]
    return rows


@router.get("/hazards/{code}", operation_id="getHazard",
            summary="隐患详情 + 整改闭环记录")
def get_hazard(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    h = M.load(tenant).hazard_by_code.get(code)
    if h is None:
        raise HTTPException(404, f"hazard {code} not found")
    return h


@router.get("/violations", operation_id="listViolations",
            summary="违章记录列表（按类型/状态过滤）")
def list_violations(
    tenant: Annotated[str, Depends(get_tenant)],
    type: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="待核实/已核实")] = None,
) -> list[dict]:
    rows = M.load(tenant).violations
    if type:
        rows = [r for r in rows if r["type"] == type]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/violations/{code}", operation_id="getViolation",
            summary="违章详情 + 处置")
def get_violation(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    v = M.load(tenant).violation_by_code.get(code)
    if v is None:
        raise HTTPException(404, f"violation {code} not found")
    return v


# ── 巡检 / 风险点 / 劳保 ───────────────────────────────────

@router.get("/inspections", operation_id="listInspections",
            summary="巡检记录列表")
def list_inspections(
    tenant: Annotated[str, Depends(get_tenant)],
    area: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).inspections
    if area:
        rows = [r for r in rows if area in r["area"]]
    return rows


@router.get("/safety-risks", operation_id="listSafetyRisks",
            summary="风险点分级表（按区域/级别过滤）")
def list_safety_risks(
    tenant: Annotated[str, Depends(get_tenant)],
    level: Annotated[str | None, Query(description="红/橙/黄/蓝")] = None,
) -> list[dict]:
    rows = M.load(tenant).safety_risks
    if level:
        rows = [r for r in rows if r["level"] == level]
    return rows


@router.get("/ppe", operation_id="listPpe",
            summary="劳保用品台账（标不足安全库存项）")
def list_ppe(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    rows = M.load(tenant).ppe
    return [{**r, "below_safety": r["stock_qty"] < r["safety_stock"]} for r in rows]


# ── 业务端点 ───────────────────────────────────────────────

@router.get("/violation-classify", operation_id="detectViolationType",
            summary="违章描述智能分类（违章类型/规程条款/整改建议）")
def detect_violation_type(
    tenant: Annotated[str, Depends(get_tenant)],
    desc: Annotated[str, Query(description="违章描述文本")] = "",
) -> dict:
    return M.classify_violation(tenant, desc)


@router.get("/hazard-priority", operation_id="scoreHazardPriority",
            summary="隐患整改优先级打分（风险×暴露人数×剩余天数）")
def score_hazard_priority(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.score_hazard_priority(tenant)
