"""ERP 路由——资源计划系统只读查询 + 收货入库/建账（演示 POST）。

多租户：经 ``Depends(get_tenant)`` 取 ``X-API-Key`` 解析的 tenant，再调
``data.load(tenant)`` 取数。``operationId`` 保持原值，平台 spec 导入与已绑定技能不受影响。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as E

router = APIRouter(prefix="/api/v1", tags=["ERP 资源计划"])


# ── 供应商 / 物料 / 仓库 ────────────────────────────────────

@router.get("/suppliers", operation_id="listSuppliers", summary="供应商列表")
def list_suppliers(
    tenant: Annotated[str, Depends(get_tenant)],
    category: Annotated[str | None, Query(description="原材料/外协加工/辅料包装/面料/辅料")] = None,
    keyword: Annotated[str | None, Query(description="名称模糊匹配")] = None,
) -> list[dict]:
    rows = E.load(tenant).suppliers
    if category:
        rows = [r for r in rows if r["category"] == category]
    if keyword:
        rows = [r for r in rows if keyword in r["name"]]
    return rows


@router.get("/suppliers/{code}", operation_id="getSupplier", summary="供应商详情 + 应付")
def get_supplier(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = E.load(tenant)
    s = d.supplier_by_code.get(code)
    if s is None:
        raise HTTPException(404, f"supplier {code} not found")
    return {**s, "payables": [p for p in d.payables if p["supplier_code"] == code]}


@router.get("/materials", operation_id="listMaterials", summary="物料列表")
def list_materials(
    tenant: Annotated[str, Depends(get_tenant)],
    category: Annotated[str | None, Query()] = None,
    keyword: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = E.load(tenant).materials
    if category:
        rows = [r for r in rows if r["category"] == category]
    if keyword:
        rows = [r for r in rows if keyword in r["name"]]
    return rows


@router.get("/materials/{material_code}", operation_id="getMaterial", summary="物料详情 + 库存")
def get_material(
    material_code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = E.load(tenant)
    m = d.material_by_code.get(material_code)
    if m is None:
        raise HTTPException(404, f"material {material_code} not found")
    return {**m, "inventory": [i for i in d.inventory if i["material_code"] == material_code]}


@router.get("/warehouses", operation_id="listWarehouses", summary="仓库列表")
def list_warehouses(tenant: Annotated[str, Depends(get_tenant)]) -> list[dict]:
    return E.load(tenant).warehouses


# ── 采购订单 ───────────────────────────────────────────────

@router.get("/purchase-orders", operation_id="listPurchaseOrders", summary="采购订单列表")
def list_purchase_orders(
    tenant: Annotated[str, Depends(get_tenant)],
    supplier_code: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="草稿/已下单/部分到货/已入库/关闭")] = None,
) -> list[dict]:
    rows = E.load(tenant).purchase_orders
    if supplier_code:
        rows = [r for r in rows if r["supplier_code"] == supplier_code]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/purchase-orders/{po_no}", operation_id="getPurchaseOrder", summary="采购订单详情 + 行")
def get_purchase_order(
    po_no: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = E.load(tenant)
    po = d.po_by_no.get(po_no)
    if po is None:
        raise HTTPException(404, f"purchase order {po_no} not found")
    return {**po, "lines": [l for l in d.purchase_order_lines if l["po_no"] == po_no]}


@router.post("/purchase-orders/{po_no}/receive", operation_id="receivePurchaseOrder",
             summary="采购收货入库（写入演示）")
def receive_purchase_order(
    po_no: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
    payload: Annotated[dict, Body(examples=[{"line_no": 1, "qty": 100, "warehouse": "WH-RAW", "receiver": "仓管-周"}])] = None,
) -> dict:
    d = E.load(tenant)
    po = d.po_by_no.get(po_no)
    if po is None:
        raise HTTPException(404, f"purchase order {po_no} not found")
    p = payload or {}
    qty = int(p.get("qty", 0))
    return {"po_no": po_no, "received_qty": qty, "warehouse": p.get("warehouse", "WH-RAW"),
            "movement_type": "采购入库", "status": "ok", "tenant": tenant}


# ── 库存 / 出入库 ───────────────────────────────────────────

@router.get("/inventory", operation_id="listInventory", summary="库存查询")
def list_inventory(
    tenant: Annotated[str, Depends(get_tenant)],
    warehouse: Annotated[str | None, Query()] = None,
    material_code: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = E.load(tenant).inventory
    if warehouse:
        rows = [r for r in rows if r["warehouse"] == warehouse]
    if material_code:
        rows = [r for r in rows if r["material_code"] == material_code]
    return rows


@router.get("/stock-movements", operation_id="listStockMovements", summary="库存出入库流水")
def list_stock_movements(
    tenant: Annotated[str, Depends(get_tenant)],
    type: Annotated[str | None, Query(description="采购入库/生产领料/生产入库/销售出库/调拨")] = None,
    material_code: Annotated[str | None, Query()] = None,
    ref_no: Annotated[str | None, Query(description="关联单号（PO/SO/WO/TR）")] = None,
) -> list[dict]:
    rows = E.load(tenant).stock_movements
    if type:
        rows = [r for r in rows if r["type"] == type]
    if material_code:
        rows = [r for r in rows if r["material_code"] == material_code]
    if ref_no:
        rows = [r for r in rows if r["ref_no"] == ref_no]
    return rows


# ── 应付 / 财务凭证 / 成本 ──────────────────────────────────

@router.get("/payables", operation_id="listPayables", summary="应付对账（含逾期汇总）")
def list_payables(
    tenant: Annotated[str, Depends(get_tenant)],
    supplier_code: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="未到期/逾期/已付款")] = None,
) -> dict:
    rows = E.load(tenant).payables
    if supplier_code:
        rows = [r for r in rows if r["supplier_code"] == supplier_code]
    if status:
        rows = [r for r in rows if r["status"] == status]
    overdue = [r for r in rows if r["status"] == "逾期"]
    return {
        "items": rows,
        "summary": {
            "total_count": len(rows), "overdue_count": len(overdue),
            "overdue_amount": sum(r["amount"] for r in overdue),
            "currency": rows[0]["currency"] if rows else "CNY",
        },
    }


@router.get("/vouchers", operation_id="listVouchers", summary="财务凭证列表")
def list_vouchers(
    tenant: Annotated[str, Depends(get_tenant)],
    period: Annotated[str | None, Query(description="YYYY-MM 会计期间")] = None,
    status: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = E.load(tenant).vouchers
    if period:
        rows = [r for r in rows if r["period"] == period]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.post("/vouchers", operation_id="postVoucher", summary="新建财务凭证（写入演示）")
def post_voucher(
    tenant: Annotated[str, Depends(get_tenant)],
    payload: Annotated[dict, Body(examples=[{"period": "2026-06", "summary": "采购入库核算",
                                             "debit_total": 50000, "credit_total": 50000}])] = None,
) -> dict:
    p = payload or {}
    prefix = "XFV" if tenant == "starclothing" else "FV"
    seq = len(E.load(tenant).vouchers) + 1
    return {"voucher_no": f"{prefix}{E.D.pad(seq)}",
            "period": p.get("period", "2026-06"), "status": "草稿", "posted": False, "tenant": tenant}


@router.get("/cost-centers", operation_id="listCostCenters", summary="成本中心列表")
def list_cost_centers(tenant: Annotated[str, Depends(get_tenant)]) -> list[dict]:
    return E.load(tenant).cost_centers


@router.get("/production-costs", operation_id="listProductionCosts",
            summary="生产成本（按 MES 工单归集，含料/工/费）")
def list_production_costs(
    tenant: Annotated[str, Depends(get_tenant)],
    work_order: Annotated[str | None, Query(description="MES 工单号")] = None,
    period: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = E.load(tenant).production_costs
    if work_order:
        rows = [r for r in rows if r["work_order_no"] == work_order]
    if period:
        rows = [r for r in rows if r["period"] == period]
    return rows
