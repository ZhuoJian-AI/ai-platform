"""MES 路由——制造执行系统只读查询 + 报工写入（演示 POST）。

多租户：经 ``Depends(get_tenant)`` 取 ``X-API-Key`` 解析的 tenant，再调
``data.load(tenant)`` 取数。``operationId`` 保持原值，平台 spec 导入与已绑定技能不受影响。
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["MES 制造执行"])


# ── 生产订单 ───────────────────────────────────────────────

@router.get("/production-orders", operation_id="listProductionOrders",
            summary="生产订单列表")
def list_production_orders(
    tenant: Annotated[str, Depends(get_tenant)],
    status: Annotated[str | None, Query(description="状态过滤：已下达/在制/完工/关闭")] = None,
    product_code: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).production_orders
    if status:
        rows = [r for r in rows if r["status"] == status]
    if product_code:
        rows = [r for r in rows if r["product_code"] == product_code]
    return rows


@router.get("/production-orders/{order_no}", operation_id="getProductionOrder",
            summary="生产订单详情 + 其下工单")
def get_production_order(
    order_no: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    po = d.production_order_by_no.get(order_no)
    if po is None:
        raise HTTPException(404, f"production order {order_no} not found")
    return {**po, "work_orders": [w for w in d.work_orders if w["order_no"] == order_no]}


# ── 工单 ───────────────────────────────────────────────────

@router.get("/work-orders", operation_id="listWorkOrders",
            summary="工单列表（支持产线/状态/班次过滤）")
def list_work_orders(
    tenant: Annotated[str, Depends(get_tenant)],
    line: Annotated[str | None, Query(description="产线代号，如 LINE-A")] = None,
    status: Annotated[str | None, Query(description="待开工/在制/暂停/完工")] = None,
    shift: Annotated[str | None, Query(description="早班/中班/晚班")] = None,
) -> list[dict]:
    rows = M.load(tenant).work_orders
    if line:
        rows = [r for r in rows if r["line"] == line]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if shift:
        rows = [r for r in rows if r["shift"] == shift]
    return rows


@router.get("/work-orders/{won}", operation_id="getWorkOrder",
            summary="工单明细：工序进度 / 报工 / 不良")
def get_work_order(
    won: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    wo = d.work_order_by_no.get(won)
    if wo is None:
        raise HTTPException(404, f"work order {won} not found")
    return {
        **wo,
        "operations": M.work_order_progress(tenant, won),
        "defects": [de for de in d.defects if de["work_order_no"] == won],
    }


@router.post("/work-orders/{won}/report", operation_id="reportWorkOrder",
             summary="工单报工（写入演示）")
def report_work_order(
    won: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
    payload: Annotated[dict, Body(examples=[{"operation_seq": 40, "qty": 50, "operator": "OP0007"}])],
) -> dict:
    d = M.load(tenant)
    wo = d.work_order_by_no.get(won)
    if wo is None:
        raise HTTPException(404, f"work order {won} not found")
    qty = int(payload.get("qty", 0))
    wo["done_qty"] = min(wo["plan_qty"], wo["done_qty"] + qty)
    return {"work_order_no": won, "accepted_qty": qty, "done_qty": wo["done_qty"], "status": "ok"}


# ── 设备 ───────────────────────────────────────────────────

@router.get("/equipment/status", operation_id="listEquipmentStatus",
            summary="设备状态列表")
def list_equipment_status(
    tenant: Annotated[str, Depends(get_tenant)],
    line: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="running/idle/fault/maintenance")] = None,
) -> list[dict]:
    rows = M.load(tenant).equipment
    if line:
        rows = [r for r in rows if r["line"] == line]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/equipment/{code}", operation_id="getEquipment",
            summary="单台设备 + 实时参数")
def get_equipment(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    rt = M.equipment_runtime(tenant, code)
    if not rt:
        raise HTTPException(404, f"equipment {code} not found")
    return rt


# ── OEE / 不良 / 班次产量 / 在制品 / 工艺路线 ───────────────

@router.get("/oee", operation_id="getOee",
            summary="产线 OEE（可用率×性能×质量）")
def get_oee(
    tenant: Annotated[str, Depends(get_tenant)],
    line: Annotated[str | None, Query(description="产线代号；缺省返回全部产线当日")] = None,
    day: Annotated[str | None, Query(description="YYYY-MM-DD，缺省为基准日")] = None,
) -> dict:
    d = M.load(tenant)
    target = date.fromisoformat(day) if day else M.BASE_DATE
    lines = [line] if line else [ln["code"] for ln in d.lines]
    return {"date": target.isoformat(), "items": [M.oee(tenant, ln, target) for ln in lines]}


@router.get("/defects", operation_id="listDefects",
            summary="不良记录（可按工单过滤）")
def list_defects(
    tenant: Annotated[str, Depends(get_tenant)],
    work_order: Annotated[str | None, Query(description="工单号")] = None,
    line: Annotated[str | None, Query()] = None,
    severity: Annotated[str | None, Query(description="轻微/一般/严重")] = None,
) -> list[dict]:
    rows = M.load(tenant).defects
    if work_order:
        rows = [r for r in rows if r["work_order_no"] == work_order]
    if line:
        rows = [r for r in rows if r["line"] == line]
    if severity:
        rows = [r for r in rows if r["severity"] == severity]
    return rows


@router.get("/defects/{defect_id}/root-cause", operation_id="getDefectRootCause",
            summary="缺陷根因分析（按缺陷 ID 检索 5W2H 根因 + 纠正措施 + 预防建议）")
def get_defect_root_cause(
    defect_id: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    defect = next((x for x in d.defects if x["defect_id"] == defect_id), None)
    if defect is None:
        raise HTTPException(404, f"defect {defect_id} not found")
    wo = d.work_order_by_no.get(defect["work_order_no"])
    product = d.product_by_code.get(defect["product_code"])
    routing = product["routing"] if product else []
    op_match = next((s for s in routing if s["name"] == defect.get("operation")), None)
    # 关联同款产品的历史相似缺陷
    similar = [
        {"defect_id": x["defect_id"], "work_order_no": x["work_order_no"],
         "severity": x["severity"], "status": x["status"],
         "found_at": x["found_at"]}
        for x in d.defects
        if x["defect_code"] == defect["defect_code"] and x["defect_id"] != defect_id
    ][:5]
    return {
        "defect_id": defect["defect_id"],
        "work_order_no": defect["work_order_no"],
        "product_code": defect["product_code"],
        "product_name": product["name"] if product else None,
        "line": defect["line"],
        "operation": defect.get("operation"),
        "operation_seq": op_match["seq"] if op_match else None,
        "defect_code": defect["defect_code"],
        "defect_name": defect["defect_name"],
        "severity": defect["severity"],
        "qty": defect["qty"],
        "found_at": defect["found_at"],
        "root_cause": defect["root_cause"],
        "corrective_action": defect.get("corrective_action") or "待分析",
        "avoidance_hint": defect.get("avoidance_hint") or "待补 SOP",
        "status": defect["status"],
        "work_order_status": wo["status"] if wo else None,
        "similar_history": similar,
    }


@router.get("/shifts/outputs", operation_id="listShiftOutputs",
            summary="班次产量")
def list_shift_outputs(
    tenant: Annotated[str, Depends(get_tenant)],
    line: Annotated[str | None, Query()] = None,
    day: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).shift_outputs
    if line:
        rows = [r for r in rows if r["line"] == line]
    if day:
        rows = [r for r in rows if r["date"] == day]
    return rows


@router.get("/wip", operation_id="listWip",
            summary="在制品")
def list_wip(
    tenant: Annotated[str, Depends(get_tenant)],
    line: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).wip
    if line:
        rows = [r for r in rows if r["line"] == line]
    return rows


@router.get("/routings/{product_code}", operation_id="getRouting",
            summary="产品工艺路线（工序序列 / 标准工时）")
def get_routing(
    product_code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    p = M.load(tenant).product_by_code.get(product_code)
    if p is None:
        raise HTTPException(404, f"product {product_code} not found")
    return p


# ── 炉次（钢铁主实体，agilesteel） ─────────────────────────

@router.get("/heats", operation_id="listHeats",
            summary="炉次列表（按钢种/状态/转炉过滤）")
def list_heats(
    tenant: Annotated[str, Depends(get_tenant)],
    steel_grade: Annotated[str | None, Query(description="钢种码 P-ST-...，如 P-ST-Q345B")] = None,
    status: Annotated[str | None, Query(description="待吹炼/进行中/已完工")] = None,
    converter: Annotated[str | None, Query(description="转炉码 EQ-CV-...")] = None,
) -> list[dict]:
    rows = M.load(tenant).heats
    if steel_grade:
        rows = [r for r in rows if r["steel_grade"] == steel_grade]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if converter:
        rows = [r for r in rows if r["converter_code"] == converter]
    return rows


@router.get("/heats/{heat_no}", operation_id="getHeat",
            summary="炉次详情：终点碳温磷 + 配料 + 关联生产订单")
def get_heat(
    heat_no: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    h = d.heat_by_no.get(heat_no)
    if h is None:
        raise HTTPException(404, f"heat {heat_no} not found")
    linked_po = d.production_order_by_no.get(h.get("linked_production_order"))
    return {**h, "linked_production_order": linked_po}
