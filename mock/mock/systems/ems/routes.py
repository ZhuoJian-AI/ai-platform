"""EMS 路由——能源环保只读查询。全部 GET。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["EMS 能源环保"])


# ── 计量点 / 介质平衡 ───────────────────────────────────────

@router.get("/meters", operation_id="listMeters",
            summary="能源介质计量点列表（按介质/工序过滤）")
def list_meters(
    tenant: Annotated[str, Depends(get_tenant)],
    media: Annotated[str | None, Query(description="高炉煤气/转炉煤气/焦炉煤气/蒸汽/电力/氧气/氮气/工业水")] = None,
    process: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).meters
    if media:
        rows = [r for r in rows if r["media"] == media]
    if process:
        rows = [r for r in rows if r["process"] == process]
    return rows


@router.get("/meters/{code}", operation_id="getMeter",
            summary="计量点详情")
def get_meter(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    m = M.load(tenant).meter_by_code.get(code)
    if m is None:
        raise HTTPException(404, f"meter {code} not found")
    return m


@router.get("/media-balance", operation_id="listMediaBalance",
            summary="介质供需平衡表（按工序/介质过滤）")
def list_media_balance(
    tenant: Annotated[str, Depends(get_tenant)],
    process: Annotated[str | None, Query()] = None,
    media: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).media_balance
    if process:
        rows = [r for r in rows if r["process"] == process]
    if media:
        rows = [r for r in rows if r["media"] == media]
    return rows


# ── 排放 / 能耗 / 调度 / 预警 ───────────────────────────────

@router.get("/emissions", operation_id="listEmissions",
            summary="排放监测列表（按污染物/工序/状态过滤）")
def list_emissions(
    tenant: Annotated[str, Depends(get_tenant)],
    pollutant: Annotated[str | None, Query(description="SO2/NOx/颗粒物/CO2")] = None,
    process: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="达标/临界/超标")] = None,
) -> list[dict]:
    rows = M.load(tenant).emissions
    if pollutant:
        rows = [r for r in rows if r["pollutant"] == pollutant]
    if process:
        rows = [r for r in rows if r["process"] == process]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/energy-consumption", operation_id="listEnergyConsumption",
            summary="工序能耗标杆对比（kgce/t）")
def list_energy_consumption(
    tenant: Annotated[str, Depends(get_tenant)],
    process: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).energy_consumption
    if process:
        rows = [r for r in rows if r["process"] == process]
    return rows


@router.get("/dispatch-plans", operation_id="listDispatchPlans",
            summary="调度方案列表（按介质/状态过滤）")
def list_dispatch_plans(
    tenant: Annotated[str, Depends(get_tenant)],
    media: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="待执行/执行中")] = None,
) -> list[dict]:
    rows = M.load(tenant).dispatch_plans
    if media:
        rows = [r for r in rows if r["media"] == media]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/alarms", operation_id="listAlarms",
            summary="能源/排放预警列表（按级别/类型过滤）")
def list_alarms(
    tenant: Annotated[str, Depends(get_tenant)],
    level: Annotated[str | None, Query(description="高/中/低")] = None,
    type: Annotated[str | None, Query(description="介质/排放")] = None,
    status: Annotated[str | None, Query(description="未处置/已处置")] = None,
) -> list[dict]:
    rows = M.load(tenant).alarms
    if level:
        rows = [r for r in rows if r["level"] == level]
    if type:
        rows = [r for r in rows if r["type"] == type]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


# ── 业务端点 ───────────────────────────────────────────────

@router.get("/media-balance/predict", operation_id="predictMediaShortfall",
            summary="预测班次介质缺口 + 调度建议")
def predict_media_shortfall(
    tenant: Annotated[str, Depends(get_tenant)],
    shift: Annotated[str, Query(description="早班/中班/晚班")] = "早班",
) -> dict:
    return M.predict_media_shortfall(tenant, shift)


@router.get("/emissions/risk", operation_id="scoreEmissionRisk",
            summary="排放源超标风险打分 + 整改优先级")
def score_emission_risk(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.score_emission_risk(tenant)
