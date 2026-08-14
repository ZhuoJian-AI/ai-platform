"""EQM 路由——设备预测性维护只读查询。

多租户：经 ``Depends(get_tenant)`` 取 tenant，再调 ``data.load(tenant)`` 取数。
``operationId`` 保持稳定，平台 spec 导入与技能绑定不受影响。全部 GET（业务端点亦为
GET+query 参数，便于技能只绑 GET 端点）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["EQM 设备管理"])


# ── 设备档案 ───────────────────────────────────────────────

@router.get("/equipment", operation_id="listEquipment",
            summary="关键设备档案列表（按类型/状态过滤）")
def list_equipment(
    tenant: Annotated[str, Depends(get_tenant)],
    type: Annotated[str | None, Query(description="设备类型：高炉/转炉/连铸机/精炼炉/连轧机/空压机/除尘风机")] = None,
    status: Annotated[str | None, Query(description="running/idle/fault/maintenance")] = None,
) -> list[dict]:
    rows = M.load(tenant).equipment
    if type:
        rows = [r for r in rows if r["type"] == type]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/equipment/{code}", operation_id="getEquipment",
            summary="设备详情 + 健康分 + 近 N 次故障")
def get_equipment(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    eq = d.equip_by_code.get(code)
    if eq is None:
        raise HTTPException(404, f"equipment {code} not found")
    return {
        **eq,
        "health": d.health_scores.get(code),
        "faults": [f for f in d.fault_history if f["equipment_code"] == code],
    }


# ── 备件 ───────────────────────────────────────────────────

@router.get("/spare-parts", operation_id="listSpareParts",
            summary="备件清单（按适用设备过滤；标低安全库存）")
def list_spare_parts(
    tenant: Annotated[str, Depends(get_tenant)],
    fit_equipment: Annotated[str | None, Query(description="适用设备码 EQ-...")] = None,
) -> list[dict]:
    rows = M.load(tenant).spare_parts
    if fit_equipment:
        rows = [r for r in rows if fit_equipment in (r["fit_equipment"] or "")]
    return [{**r, "below_safety": r["stock_qty"] < r["safety_stock"]} for r in rows]


@router.get("/spare-parts/{code}", operation_id="getSparePart",
            summary="备件详情（库存/供应商/互换件）")
def get_spare_part(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    s = M.load(tenant).spare_by_code.get(code)
    if s is None:
        raise HTTPException(404, f"spare part {code} not found")
    return s


# ── 故障历史 / 维护建议 / 传感器时序 ───────────────────────

@router.get("/fault-history", operation_id="listFaultHistory",
            summary="故障历史（MTBF/MTTR 分项；按设备过滤）")
def list_fault_history(
    tenant: Annotated[str, Depends(get_tenant)],
    equipment_code: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).fault_history
    if equipment_code:
        rows = [r for r in rows if r["equipment_code"] == equipment_code]
    return rows


@router.get("/maintenance-plans", operation_id="listMaintenancePlans",
            summary="预测性维护建议列表（按状态/优先级过滤）")
def list_maintenance_plans(
    tenant: Annotated[str, Depends(get_tenant)],
    status: Annotated[str | None, Query(description="待执行/已执行")] = None,
    priority: Annotated[str | None, Query(description="紧急/高/中/低")] = None,
) -> list[dict]:
    rows = M.load(tenant).maintenance_plans
    if status:
        rows = [r for r in rows if r["status"] == status]
    if priority:
        rows = [r for r in rows if r["priority"] == priority]
    return rows


@router.get("/equipment/{code}/readings", operation_id="listSensorReadings",
            summary="设备传感器时序读数（近 30 天，振动/温度/电流/油压）")
def list_sensor_readings(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
    days: Annotated[int, Query(description="近 N 天，默认 30")] = 30,
) -> list[dict]:
    rows = [r for r in M.load(tenant).sensor_readings if r["equipment_code"] == code]
    return rows[-days:]


# ── 业务端点（GET + query 参数，便于技能绑定） ───────────────

@router.get("/equipment/{code}/predict", operation_id="predictEquipmentFailure",
            summary="设备故障概率预测（健康分+趋势+备件现货+维护建议）")
def predict_equipment_failure(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    res = M.predict_failure(tenant, code)
    if not res:
        raise HTTPException(404, f"equipment {code} not found")
    return res


@router.get("/maintenance-priority", operation_id="scoreMaintenancePriority",
            summary="多设备待维护项打分排序（风险×产能影响×备件现货）")
def score_maintenance_priority(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.score_maintenance_priority(tenant)
