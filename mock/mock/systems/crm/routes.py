"""CRM 路由——销售系统只读查询 + 报价送审（演示 POST）。

多租户：经 ``Depends(get_tenant)`` 取 ``X-API-Key`` 解析的 tenant，再调
``data.load(tenant)`` 取数。``operationId`` 保持原值，平台 spec 导入与已绑定技能不受影响。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as C

router = APIRouter(prefix="/api/v1", tags=["CRM 工业销售"])


# ── 客户 / 联系人 ───────────────────────────────────────────

@router.get("/customers", operation_id="listCustomers", summary="客户列表")
def list_customers(
    tenant: Annotated[str, Depends(get_tenant)],
    type: Annotated[str | None, Query(description="OEM/ODM/经销商/终端/外贸/品牌/ODM代工")] = None,
    industry: Annotated[str | None, Query()] = None,
    keyword: Annotated[str | None, Query(description="名称模糊匹配")] = None,
) -> list[dict]:
    rows = C.load(tenant).customers
    if type:
        rows = [r for r in rows if r["type"] == type]
    if industry:
        rows = [r for r in rows if industry in r["industry"]]
    if keyword:
        rows = [r for r in rows if keyword in r["name"]]
    return rows


@router.get("/customers/{code}", operation_id="getCustomer", summary="客户详情 + 信用/账期 + 联系人")
def get_customer(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = C.load(tenant)
    c = d.customer_by_code.get(code)
    if c is None:
        raise HTTPException(404, f"customer {code} not found")
    return {**c, "contacts": [ct for ct in d.contacts if ct["customer_code"] == code]}


@router.get("/contacts", operation_id="listContacts", summary="联系人列表")
def list_contacts(
    tenant: Annotated[str, Depends(get_tenant)],
    customer_code: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = C.load(tenant).contacts
    if customer_code:
        rows = [r for r in rows if r["customer_code"] == customer_code]
    return rows


# ── 商机 / 报价 ────────────────────────────────────────────

@router.get("/opportunities", operation_id="listOpportunities", summary="商机列表")
def list_opportunities(
    tenant: Annotated[str, Depends(get_tenant)],
    stage: Annotated[str | None, Query(description="minrui:线索/打样/报价/送样/NPI/成交/流失；starclothing:发现/方案/报价/谈判/已签约/输单")] = None,
    customer_code: Annotated[str | None, Query()] = None,
    owner: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = C.load(tenant).opportunities
    if stage:
        rows = [r for r in rows if r["stage"] == stage]
    if customer_code:
        rows = [r for r in rows if r["customer_code"] == customer_code]
    if owner:
        rows = [r for r in rows if r["owner"] == owner]
    return rows


@router.get("/opportunities/{opportunity_id}", operation_id="getOpportunity", summary="商机详情 + 报价 + 跟进")
def get_opportunity(
    opportunity_id: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = C.load(tenant)
    o = d.opportunity_by_no.get(opportunity_id)
    if o is None:
        raise HTTPException(404, f"opportunity {opportunity_id} not found")
    return {
        **o,
        "quotations": [q for q in d.quotations if q["opportunity_id"] == opportunity_id],
        "follow_ups": [f for f in d.follow_ups if f["opportunity_id"] == opportunity_id],
    }


@router.get("/quotations", operation_id="listQuotations", summary="报价列表（含阶梯价/模具费）")
def list_quotations(
    tenant: Annotated[str, Depends(get_tenant)],
    customer_code: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = C.load(tenant).quotations
    if customer_code:
        rows = [r for r in rows if r["customer_code"] == customer_code]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/quotations/{quotation_id}", operation_id="getQuotation", summary="报价明细")
def get_quotation(
    quotation_id: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = C.load(tenant)
    q = d.quotation_by_no.get(quotation_id)
    if q is None:
        raise HTTPException(404, f"quotation {quotation_id} not found")
    return q


@router.post("/quotations/{quotation_id}/submit", operation_id="submitQuotation", summary="报价送审（写入演示）")
def submit_quotation(
    quotation_id: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
    payload: Annotated[dict, Body(examples=[{"approver": "林芳", "comment": "同意阶梯价"}])] = None,
) -> dict:
    d = C.load(tenant)
    q = d.quotation_by_no.get(quotation_id)
    if q is None:
        raise HTTPException(404, f"quotation {quotation_id} not found")
    q["status"] = "待审"
    return {"quotation_id": quotation_id, "status": q["status"],
            "submitted_by": (payload or {}).get("approver", ""), "tenant": tenant}


# ── 销售订单 / 跟进 ─────────────────────────────────────────

@router.get("/sales-orders", operation_id="listSalesOrders", summary="销售订单列表")
def list_sales_orders(
    tenant: Annotated[str, Depends(get_tenant)],
    customer_code: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = C.load(tenant).sales_orders
    if customer_code:
        rows = [r for r in rows if r["customer_code"] == customer_code]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/follow-ups", operation_id="listFollowUps", summary="客户跟进记录")
def list_follow_ups(
    tenant: Annotated[str, Depends(get_tenant)],
    customer_code: Annotated[str | None, Query()] = None,
    owner: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = C.load(tenant).follow_ups
    if customer_code:
        rows = [r for r in rows if r["customer_code"] == customer_code]
    if owner:
        rows = [r for r in rows if r["owner"] == owner]
    return rows


# ── 客诉 / 8D（关联 MES 工单号） ────────────────────────────

@router.get("/complaints", operation_id="listComplaints", summary="客诉 / 8D 列表")
def list_complaints(
    tenant: Annotated[str, Depends(get_tenant)],
    customer_code: Annotated[str | None, Query()] = None,
    severity: Annotated[str | None, Query(description="一般/严重/致命")] = None,
    status: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = C.load(tenant).complaints
    if customer_code:
        rows = [r for r in rows if r["customer_code"] == customer_code]
    if severity:
        rows = [r for r in rows if r["severity"] == severity]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/complaints/{complaint_id}", operation_id="getComplaint", summary="客诉详情 + 关联 MES 工单号")
def get_complaint(
    complaint_id: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = C.load(tenant)
    c = d.complaint_by_no.get(complaint_id)
    if c is None:
        raise HTTPException(404, f"complaint {complaint_id} not found")
    return {**c, "trace_hint": f"可用 work_order_no={c['work_order_no']} 经 MES 连接器追溯该工单与不良记录"}


# ── 应收对账 ───────────────────────────────────────────────

@router.get("/receivables", operation_id="listReceivables", summary="应收对账（含逾期汇总）")
def list_receivables(
    tenant: Annotated[str, Depends(get_tenant)],
    customer_code: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="未到期/逾期/已收款")] = None,
) -> dict:
    rows = C.load(tenant).receivables
    if customer_code:
        rows = [r for r in rows if r["customer_code"] == customer_code]
    if status:
        rows = [r for r in rows if r["status"] == status]
    overdue = [r for r in rows if r["status"] == "逾期"]
    return {
        "items": rows,
        "summary": {
            "total_count": len(rows),
            "overdue_count": len(overdue),
            "overdue_amount": sum(r["amount"] for r in overdue),
            "currency": rows[0]["currency"] if rows else "CNY",
        },
    }
