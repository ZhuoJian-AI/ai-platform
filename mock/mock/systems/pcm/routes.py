"""PCM 路由——工艺与设备管理只读查询。

多租户：经 ``Depends(get_tenant)`` 取 tenant，再调 ``data.load(tenant)`` 取数。
``operationId`` 保持稳定。全部 GET（业务端点亦为 GET+query/path 参数，便于技能只绑
GET 端点）。path 参数一律用真实码（如 ``EQ-RX-02``），勿用 ``{code}`` 占位。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["PCM 工艺与设备管理"])


# ── 工艺参数 ───────────────────────────────────────────────

@router.get("/process-params", operation_id="listProcessParams",
            summary="工艺参数列表（按配方/阶段过滤）")
def list_process_params(
    tenant: Annotated[str, Depends(get_tenant)],
    formula_no: Annotated[str | None, Query(description="配方号 FORM-...")] = None,
    stage: Annotated[str | None, Query(description="搅拌/反应/冷却")] = None,
) -> list[dict]:
    rows = M.load(tenant).process_params
    if formula_no:
        rows = [r for r in rows if r["formula_no"] == formula_no]
    if stage:
        rows = [r for r in rows if r["stage"] == stage]
    return rows


@router.get("/process-params/recommend", operation_id="recommendProcessParams",
            summary="工艺参数智能推荐（按配方/产品给最优区间）")
def recommend_process_params(
    tenant: Annotated[str, Depends(get_tenant)],
    formula_no: Annotated[str | None, Query(description="配方号 FORM-...")] = None,
    product_code: Annotated[str | None, Query(description="ERP 成品胶码 M-FG-...")] = None,
) -> dict:
    res = M.recommend_process_params(tenant, formula_no=formula_no, product_code=product_code)
    if not res:
        raise HTTPException(404, "no process params for given formula/product")
    return res


# ── 设备 ───────────────────────────────────────────────────

@router.get("/equipment", operation_id="listEquipment",
            summary="设备列表（按类型/产线过滤）")
def list_equipment(
    tenant: Annotated[str, Depends(get_tenant)],
    type: Annotated[str | None, Query(description="反应釜/电机/造粒机")] = None,
    line: Annotated[str | None, Query(description="产线 LINE-...")] = None,
) -> list[dict]:
    rows = M.load(tenant).equipment
    if type:
        rows = [r for r in rows if r["type"] == type]
    if line:
        rows = [r for r in rows if r["line"] == line]
    return rows


@router.get("/equipment/{eq_no}", operation_id="getEquipment",
            summary="设备详情 + 近 7 天运行数据")
def get_equipment(
    eq_no: Annotated[str, Path(description="设备号，如 EQ-RX-02")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    e = d.equip_by_code.get(eq_no)
    if e is None:
        raise HTTPException(404, f"equipment {eq_no} not found")
    return {
        **e,
        "run_data_recent": [r for r in d.equipment_run_data if r["eq_no"] == eq_no],
    }


@router.get("/equipment/{eq_no}/fault-prediction", operation_id="predictEquipmentFault",
            summary="设备故障预测（振动/温升/健康分预判+保养提醒）")
def predict_equipment_fault(
    eq_no: Annotated[str, Path(description="设备号，如 EQ-MTR-02")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    res = M.predict_equipment_fault(tenant, eq_no)
    if not res:
        raise HTTPException(404, f"equipment {eq_no} not found")
    return res


@router.get("/equipment/{eq_no}/run-data", operation_id="getEquipmentRunData",
            summary="设备运行时序数据（近 7 天采样）")
def get_equipment_run_data(
    eq_no: Annotated[str, Path(description="设备号，如 EQ-MTR-02")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.get_equipment_run_data(tenant, eq_no)


# ── 排产 ───────────────────────────────────────────────────

@router.get("/schedule/optimize", operation_id="optimizeProductionSchedule",
            summary="智能排产建议（综合工单/负荷/换线+冲突识别）")
def optimize_production_schedule(
    tenant: Annotated[str, Depends(get_tenant)],
    line_no: Annotated[str | None, Query(description="产线 LINE-...，不传则全局")] = None,
    horizon_days: Annotated[int, Query(description="排产周期(天)", ge=1, le=30)] = 7,
) -> dict:
    return M.optimize_production_schedule(tenant, line_no=line_no, horizon_days=horizon_days)


@router.get("/schedule/rules", operation_id="listScheduleRules",
            summary="排产规则列表（产线产能/换线成本）")
def list_schedule_rules(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.load(tenant).schedule_rules
