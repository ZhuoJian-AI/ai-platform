"""PLM 路由——服装产品生命周期只读查询 + 写入演示（缺陷/凭证/成本台账）。

多租户：经 ``Depends(get_tenant)`` 取 ``X-API-Key`` 解析的 tenant，再调
``data.load(tenant)`` 取数。``operationId`` 保持原值，平台 spec 导入与已绑定技能不受影响。
所有路由挂 ``/api/v1``。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from mock.core import data as D
from mock.core.tenant import get_tenant
from . import data as P

router = APIRouter(prefix="/api/v1", tags=["PLM 产品生命周期"])


# ── 款式 / BOM ──────────────────────────────────────────────

@router.get("/styles", operation_id="listStyles", summary="款式列表")
def list_styles(
    tenant: Annotated[str, Depends(get_tenant)],
    category: Annotated[str | None, Query(description="FW 秋冬季/SS 春夏季/AP 春秋季")] = None,
    keyword: Annotated[str | None, Query(description="款号/名称模糊匹配")] = None,
    status: Annotated[str | None, Query(description="开发中/打样中/已量产/已停产")] = None,
) -> list[dict]:
    rows = P.load(tenant).styles
    if category:
        rows = [r for r in rows if r["category"] == category]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if keyword:
        k = keyword.lower()
        rows = [r for r in rows if k in r["style_code"].lower() or k in r["name"].lower()]
    return rows


@router.get("/styles/{style_code}", operation_id="getStyle", summary="款式详情 + BOM")
def get_style(
    style_code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = P.load(tenant)
    s = d.style_by_code.get(style_code)
    if s is None:
        raise HTTPException(404, f"style {style_code} not found")
    return {**s, "bom": d.bom_by_style.get(style_code, [])}


@router.get("/boms", operation_id="listBoms", summary="BOM 列表（按款号过滤）")
def list_boms(
    tenant: Annotated[str, Depends(get_tenant)],
    style_code: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = P.load(tenant).boms
    if style_code:
        rows = [r for r in rows if r["style_code"] == style_code]
    return rows


# ── 面料库 ─────────────────────────────────────────────────

@router.get("/fabrics", operation_id="listFabrics", summary="数字面料库")
def list_fabrics(
    tenant: Annotated[str, Depends(get_tenant)],
    category: Annotated[str | None, Query(description="面料/辅料/辅料包装")] = None,
    composition_keyword: Annotated[str | None, Query(description="成分模糊匹配")] = None,
    supplier_code: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = P.load(tenant).fabrics
    if category:
        rows = [r for r in rows if r["category"] == category]
    if composition_keyword:
        rows = [r for r in rows if composition_keyword in r["composition"]]
    if supplier_code:
        rows = [r for r in rows if r["supplier_code"] == supplier_code]
    return rows


@router.get("/fabrics/{fabric_code}", operation_id="getFabric", summary="面料详情")
def get_fabric(
    fabric_code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = P.load(tenant)
    f = d.fabric_by_code.get(fabric_code)
    if f is None:
        raise HTTPException(404, f"fabric {fabric_code} not found")
    return f


@router.get("/fabrics/{fabric_code}/cost", operation_id="calcFabricCost",
            summary="按款式测算单件面料用量与成本（确定性公式）")
def calc_fabric_cost(
    fabric_code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
    style_code: Annotated[str, Query(description="关联款式取 BOM 用量")] = "",
    qty: Annotated[int, Query(description="件数（默认 1）")] = 1,
) -> dict:
    d = P.load(tenant)
    f = d.fabric_by_code.get(fabric_code)
    if f is None:
        raise HTTPException(404, f"fabric {fabric_code} not found")
    bom = d.bom_by_style.get(style_code, [])
    line = next((l for l in bom if l["material_code"] == fabric_code or
                 l["material_code"].replace("M-", "F-") == fabric_code), None)
    qty_per = line["qty_per_garment"] if line else 1.0
    loss = (line["loss_rate_pct"] if line else f["loss_rate"]) / 100.0
    gross = qty_per * qty
    net = gross * (1 + loss)
    cost = round(net * f["unit_cost"], 2)
    return {
        "fabric_code": fabric_code, "style_code": style_code or None,
        "qty_garments": qty, "qty_per_garment": qty_per,
        "loss_rate_pct": round(loss * 100, 2),
        "fabric_qty_total": round(net, 4),
        "unit_cost": f["unit_cost"], "cost_total": cost,
        "tenant": tenant,
    }


# ── 打样单 ─────────────────────────────────────────────────

@router.get("/sampling-orders", operation_id="listSamplingOrders", summary="打样单列表")
def list_sampling_orders(
    tenant: Annotated[str, Depends(get_tenant)],
    status: Annotated[str | None, Query(description="待排/打样中/已确认/已退回")] = None,
    style_code: Annotated[str | None, Query()] = None,
    overdue: Annotated[bool | None, Query(description="仅超期")] = None,
) -> list[dict]:
    rows = P.load(tenant).sampling_orders
    if status:
        rows = [r for r in rows if r["status"] == status]
    if style_code:
        rows = [r for r in rows if r["style_code"] == style_code]
    if overdue is True:
        rows = [r for r in rows if r["overdue"]]
    if overdue is False:
        rows = [r for r in rows if not r["overdue"]]
    return rows


@router.get("/sampling-orders/{sampling_no}", operation_id="getSamplingProgress",
            summary="打样进度明细")
def get_sampling_progress(
    sampling_no: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = P.load(tenant)
    s = d.sampling_order_by_no.get(sampling_no)
    if s is None:
        raise HTTPException(404, f"sampling order {sampling_no} not found")
    return {**s, "bom": d.bom_by_style.get(s["style_code"], [])}


# ── 大货单 ─────────────────────────────────────────────────

@router.get("/bulk-orders", operation_id="listBulkOrders", summary="大货单列表")
def list_bulk_orders(
    tenant: Annotated[str, Depends(get_tenant)],
    status: Annotated[str | None, Query(description="qc_status: PASS/PENDING/FAIL")] = None,
    style_code: Annotated[str | None, Query()] = None,
    customer_code: Annotated[str | None, Query()] = None,
    overdue: Annotated[bool | None, Query(description="仅超期")] = None,
) -> list[dict]:
    rows = P.load(tenant).bulk_orders
    if status:
        rows = [r for r in rows if r["qc_status"] == status]
    if style_code:
        rows = [r for r in rows if r["style_code"] == style_code]
    if customer_code:
        rows = [r for r in rows if r["customer_code"] == customer_code]
    if overdue is True:
        rows = [r for r in rows if r["overdue"]]
    if overdue is False:
        rows = [r for r in rows if not r["overdue"]]
    return rows


@router.get("/bulk-orders/{bulk_no}", operation_id="getBulkOrder", summary="大货单详情")
def get_bulk_order(
    bulk_no: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = P.load(tenant)
    b = d.bulk_order_by_no.get(bulk_no)
    if b is None:
        raise HTTPException(404, f"bulk order {bulk_no} not found")
    return {
        **b,
        "bom": d.bom_by_style.get(b["style_code"], []),
        "qc_reports": [q for q in d.qc_reports if q["bulk_no"] == bulk_no],
        "pickings": [p for p in d.pickings if p["bulk_no"] == bulk_no],
    }


# ── 质检 / 缺陷 ───────────────────────────────────────────

@router.get("/qc-reports", operation_id="listQcReports", summary="质检报告列表")
def list_qc_reports(
    tenant: Annotated[str, Depends(get_tenant)],
    bulk_no: Annotated[str | None, Query()] = None,
    pass_: Annotated[bool | None, Query(alias="pass", description="true 仅合格 / false 仅不合格")] = None,
) -> list[dict]:
    rows = P.load(tenant).qc_reports
    if bulk_no:
        rows = [r for r in rows if r["bulk_no"] == bulk_no]
    if pass_ is True:
        rows = [r for r in rows if r["pass"]]
    if pass_ is False:
        rows = [r for r in rows if not r["pass"]]
    return rows


@router.get("/defect-history", operation_id="listDefectHistory", summary="缺陷历史检索（PD-3）")
def list_defect_history(
    tenant: Annotated[str, Depends(get_tenant)],
    style_code: Annotated[str | None, Query()] = None,
    defect_type: Annotated[str | None, Query(description="漏水/压胶脱落/起球/掉色/尺寸偏差/跳针断线/印花错位/整烫烫花")] = None,
    category: Annotated[str | None, Query(description="款类如 压胶冲锋衣/双面呢大衣")] = None,
) -> list[dict]:
    rows = P.load(tenant).defect_history
    if style_code:
        rows = [r for r in rows if r["style_code"] == style_code]
    if defect_type:
        rows = [r for r in rows if r["defect_type"] == defect_type]
    if category:
        rows = [r for r in rows if r["category"] == category]
    return rows


@router.post("/defect-history", operation_id="addDefectRecord",
             summary="新建缺陷记录（写入演示）")
def add_defect_record(
    tenant: Annotated[str, Depends(get_tenant)],
    payload: Annotated[dict, Body(examples=[{"style_code": "P-FW2026-002",
                                             "defect_type": "漏水", "severity": "严重",
                                             "root_cause": "压胶温度不足"}])] = None,
) -> dict:
    p = payload or {}
    seq = len(P.load(tenant).defect_history) + 1
    return {"case_id": f"DF2026{D.pad(90000 + seq)}",
            "style_code": p.get("style_code"), "defect_type": p.get("defect_type"),
            "severity": p.get("severity"), "status": "ok", "tenant": tenant}


# ── 库存 / 领料 ───────────────────────────────────────────

@router.get("/material-inventory", operation_id="listMaterialInventory",
            summary="面料/辅料库存查询")
def list_material_inventory(
    tenant: Annotated[str, Depends(get_tenant)],
    warehouse: Annotated[str | None, Query(description="WH-FAB/WH-ACC/WH-PKG")] = None,
    material_code: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = P.load(tenant).material_inventory
    if warehouse:
        rows = [r for r in rows if r["warehouse"] == warehouse]
    if material_code:
        rows = [r for r in rows if r["material_code"] == material_code]
    return rows


@router.get("/pickings", operation_id="listPickings", summary="领料流水")
def list_pickings(
    tenant: Annotated[str, Depends(get_tenant)],
    bulk_no: Annotated[str | None, Query()] = None,
    style_code: Annotated[str | None, Query()] = None,
    material_code: Annotated[str | None, Query()] = None,
    ref_work_order: Annotated[str | None, Query(description="关联 MES 工单号")] = None,
) -> list[dict]:
    rows = P.load(tenant).pickings
    if bulk_no:
        rows = [r for r in rows if r["bulk_no"] == bulk_no]
    if style_code:
        rows = [r for r in rows if r["style_code"] == style_code]
    if material_code:
        rows = [r for r in rows if r["material_code"] == material_code]
    if ref_work_order:
        rows = [r for r in rows if r["ref_work_order"] == ref_work_order]
    return rows


# ── 应付 / 应收 / 凭证 ─────────────────────────────────────

@router.get("/payables", operation_id="listPayables", summary="应付对账（含逾期汇总）")
def list_payables(
    tenant: Annotated[str, Depends(get_tenant)],
    status: Annotated[str | None, Query(description="未到期/逾期/已付款")] = None,
    supplier_code: Annotated[str | None, Query()] = None,
) -> dict:
    rows = P.load(tenant).payables
    if status:
        rows = [r for r in rows if r["status"] == status]
    if supplier_code:
        rows = [r for r in rows if r["supplier_code"] == supplier_code]
    overdue = [r for r in rows if r["status"] == "逾期"]
    return {
        "items": rows,
        "summary": {
            "total_count": len(rows), "overdue_count": len(overdue),
            "overdue_amount": sum(r["amount"] for r in overdue),
            "currency": "CNY",
        },
    }


@router.get("/receivables", operation_id="listReceivables", summary="应收对账（含逾期汇总）")
def list_receivables(
    tenant: Annotated[str, Depends(get_tenant)],
    status: Annotated[str | None, Query(description="未到期/逾期/已收款")] = None,
    customer_code: Annotated[str | None, Query()] = None,
) -> dict:
    rows = P.load(tenant).receivables
    if status:
        rows = [r for r in rows if r["status"] == status]
    if customer_code:
        rows = [r for r in rows if r["customer_code"] == customer_code]
    overdue = [r for r in rows if r["status"] == "逾期"]
    return {
        "items": rows,
        "summary": {
            "total_count": len(rows), "overdue_count": len(overdue),
            "overdue_amount": sum(r["amount"] for r in overdue),
            "currency": "CNY",
        },
    }


@router.get("/vouchers", operation_id="listVouchers", summary="财务凭证列表")
def list_vouchers(
    tenant: Annotated[str, Depends(get_tenant)],
    period: Annotated[str | None, Query(description="YYYY-MM 会计期间")] = None,
    status: Annotated[str | None, Query(description="草稿/已复核/已过账")] = None,
) -> list[dict]:
    rows = P.load(tenant).vouchers
    if period:
        rows = [r for r in rows if r["period"] == period]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.post("/vouchers", operation_id="postVoucher", summary="新建财务凭证（写入演示）")
def post_voucher(
    tenant: Annotated[str, Depends(get_tenant)],
    payload: Annotated[dict, Body(examples=[{"period": "2026-06", "summary": "面料采购入库核算",
                                             "debit_total": 50000, "credit_total": 50000}])] = None,
) -> dict:
    p = payload or {}
    seq = len(P.load(tenant).vouchers) + 1
    return {"voucher_no": f"XPLFV2026{D.pad(seq)}",
            "period": p.get("period", "2026-06"), "status": "草稿",
            "posted": False, "tenant": tenant}


# ── 成本台账 ──────────────────────────────────────────────

@router.get("/cost-ledger", operation_id="getCostLedger", summary="成本台账查询（SC-4 比价后更新）")
def get_cost_ledger(
    tenant: Annotated[str, Depends(get_tenant)],
    style_code: Annotated[str | None, Query()] = None,
    material_code: Annotated[str | None, Query()] = None,
    period: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = P.load(tenant).cost_ledger
    if style_code:
        rows = [r for r in rows if r["style_code"] == style_code]
    if material_code:
        rows = [r for r in rows if r["material_code"] == material_code]
    if period:
        rows = [r for r in rows if r["period"] == period]
    return rows


@router.post("/cost-ledger", operation_id="updateCostLedger",
             summary="更新成本台账（SC-4 比价后写入演示）")
def update_cost_ledger(
    tenant: Annotated[str, Depends(get_tenant)],
    payload: Annotated[dict, Body(examples=[{"style_code": "P-FW2026-001",
                                             "material_code": "F-WOOL-DBL-360",
                                             "cost_material": 410.0}])] = None,
) -> dict:
    p = payload or {}
    return {"ledger_no": f"XCL2026{D.pad(9000 + len(P.load(tenant).cost_ledger) + 1)}",
            "style_code": p.get("style_code"),
            "material_code": p.get("material_code"),
            "cost_material": p.get("cost_material"),
            "status": "updated", "tenant": tenant}


# ── 可行性测算留痕 ─────────────────────────────────────────

@router.get("/feasibility-logs", operation_id="listFeasibilityLogs",
            summary="面料可行性测算留痕（PD-2 交期快照）")
def list_feasibility_logs(
    tenant: Annotated[str, Depends(get_tenant)],
    style_code: Annotated[str | None, Query()] = None,
    fabric_code: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = P.load(tenant).feasibility_logs
    if style_code:
        rows = [r for r in rows if r["style_code"] == style_code]
    if fabric_code:
        rows = [r for r in rows if r["fabric_code"] == fabric_code]
    return rows


# ── 逾期汇总（PD-1 关键端点） ─────────────────────────────

@router.get("/overdue-orders", operation_id="listOverdueOrders",
            summary="打样+大货逾期汇总（PD-1 推送）")
def list_overdue_orders(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    d = P.load(tenant)
    out: list[dict] = []
    for s in d.sampling_orders:
        if s["overdue"]:
            out.append({
                "type": "sampling", "ref_no": s["sampling_no"],
                "style_code": s["style_code"], "stage": s["stage"],
                "factory": s["factory"], "days_late": s["days_late"],
                "responsible": s.get("developer") or s.get("factory"),
                "plan_date": s["plan_date"], "actual_date": s["actual_date"],
            })
    for b in d.bulk_orders:
        if b["overdue"]:
            out.append({
                "type": "bulk", "ref_no": b["bulk_no"],
                "style_code": b["style_code"], "factory": b["factory"],
                "days_late": b["days_late"],
                "responsible": b["factory"],
                "plan_end": b["plan_end"], "actual_end": b["actual_end"],
                "customer_code": b["customer_code"],
            })
    out.sort(key=lambda r: r["days_late"], reverse=True)
    return out


# ── 钢种主数据（agilesteel） ───────────────────────────────

@router.get("/steel-grades", operation_id="listSteelGrades",
            summary="钢种主数据列表（按类别过滤）")
def list_steel_grades(
    tenant: Annotated[str, Depends(get_tenant)],
    category: Annotated[str | None, Query(description="低合金钢/优质碳素钢/合金结构钢/钢筋钢/碳素结构钢")] = None,
) -> list[dict]:
    rows = P.load(tenant).steel_grades
    if category:
        rows = [r for r in rows if r["category"] == category]
    return rows


@router.get("/steel-grades/{grade_code}", operation_id="getSteelGrade",
            summary="钢种详情 + 历史质量案例")
def get_steel_grade(
    grade_code: Annotated[str, Path(description="钢种码 P-ST-...，如 P-ST-Q345B")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = P.load(tenant)
    g = d.steel_grade_by_code.get(grade_code)
    if g is None:
        raise HTTPException(404, f"steel grade {grade_code} not found")
    return {**g, "defect_history": [c for c in d.defect_history if c["style_code"] == grade_code]}
