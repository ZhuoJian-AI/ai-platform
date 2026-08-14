"""CST 路由——报关与单证只读查询。全部 GET。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["CST 报关与单证"])


# ── 报关单 / HS 归类 ───────────────────────────────────────────


@router.get("/declarations", operation_id="listDeclarations",
            summary="进出口报关单列表（按状态/港口/类型过滤）")
def list_declarations(
    tenant: Annotated[str, Depends(get_tenant)],
    status: Annotated[str | None, Query(description="已申报/查验中/已放行/异常-归类存疑")] = None,
    port: Annotated[str | None, Query()] = None,
    type: Annotated[str | None, Query(description="进口/出口")] = None,
) -> list[dict]:
    rows = M.load(tenant).declarations
    if status:
        rows = [r for r in rows if r["status"] == status]
    if port:
        rows = [r for r in rows if port in r["port"]]
    if type:
        rows = [r for r in rows if r["type"] == type]
    return rows


@router.get("/declarations/{declaration_no}", operation_id="getDeclaration",
            summary="报关单详情 + 关联采购单 PO + 合规校验")
def get_declaration(
    declaration_no: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    dec = d.declaration_by_no.get(declaration_no)
    if dec is None:
        raise HTTPException(404, f"declaration {declaration_no} not found")
    hs = d.hs_by_code.get(dec["hs_code"])
    checks = [c for c in d.compliance_checks if c.get("declaration_no") == declaration_no]
    return {**dec, "hs": hs, "compliance_checks": checks}


@router.get("/hs-codes", operation_id="listHsCodes",
            summary="HS 商品归类表")
def list_hs_codes(
    tenant: Annotated[str, Depends(get_tenant)],
    category: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).hs_codes
    if category:
        rows = [r for r in rows if r["category"] == category]
    return rows


@router.get("/hs-recommend", operation_id="recommendHsCode",
            summary="商品归类智能推荐（产品描述→HS 码）")
def recommend_hs_code(
    tenant: Annotated[str, Depends(get_tenant)],
    product_desc: Annotated[str, Query(description="产品描述文本")] = "",
) -> dict:
    return M.recommend_hs_code(tenant, product_desc)


# ── 发票 / 汇率 ───────────────────────────────────────────────


@router.get("/invoices", operation_id="listInvoices",
            summary="发票列表（按状态/方向/类型过滤）")
def list_invoices(
    tenant: Annotated[str, Depends(get_tenant)],
    status: Annotated[str | None, Query(description="已验真入账/待验真/存疑-发票代码异常")] = None,
    direction: Annotated[str | None, Query(description="进项/销项")] = None,
    type: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).invoices
    if status:
        rows = [r for r in rows if r["status"] == status]
    if direction:
        rows = [r for r in rows if r["direction"] == direction]
    if type:
        rows = [r for r in rows if type in r["type"]]
    return rows


@router.get("/invoice-verify", operation_id="verifyInvoice",
            summary="发票识别验真（查验真伪/入账/关联凭证）")
def verify_invoice(
    tenant: Annotated[str, Depends(get_tenant)],
    invoice_no: Annotated[str, Query(description="发票号 INV")] = "",
) -> dict:
    return M.verify_invoice(tenant, invoice_no)


@router.get("/exchange-rates", operation_id="getExchangeRate",
            summary="汇率行情 + 波动预警（支撑对日采购付款决策）")
def get_exchange_rate(
    tenant: Annotated[str, Depends(get_tenant)],
    pair: Annotated[str | None, Query(description="JPY/CNY/USD/CNY/EUR/CNY")] = None,
) -> list[dict]:
    rows = M.load(tenant).exchange_rates
    if pair:
        rows = [r for r in rows if r["pair"] == pair]
    return rows


# ── 合规 ───────────────────────────────────────────────────


@router.get("/compliance-checks", operation_id="listComplianceChecks",
            summary="合规校验记录列表")
def list_compliance_checks(
    tenant: Annotated[str, Depends(get_tenant)],
    result: Annotated[str | None, Query(description="通过/异常/存疑")] = None,
) -> list[dict]:
    rows = M.load(tenant).compliance_checks
    if result:
        rows = [r for r in rows if r["result"] == result]
    return rows


@router.get("/compliance-check", operation_id="checkCompliance",
            summary="报关单合规综合校验（归类/单证/价格/发票一致性）")
def check_compliance(
    tenant: Annotated[str, Depends(get_tenant)],
    declaration_no: Annotated[str, Query(description="报关单号 CD")] = "",
) -> dict:
    return M.check_compliance(tenant, declaration_no)


@router.get("/declaration-risk", operation_id="scoreDeclarationRisk",
            summary="在途报关单风险打分（状态/归类存疑/单证异常）")
def score_declaration_risk(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.score_declaration_risk(tenant)
