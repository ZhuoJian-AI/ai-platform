"""PIM 路由——产品与防伪只读查询。全部 GET。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["PIM 产品与防伪"])


# ── 产品 / 品类 ─────────────────────────────────────────────


@router.get("/products", operation_id="listProducts",
            summary="文具产品/SKU 列表（按品类/品牌/状态过滤）")
def list_products(
    tenant: Annotated[str, Depends(get_tenant)],
    category: Annotated[str | None, Query(description="品类码 CAT-GEL/CAT-BALL…")] = None,
    brand: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="在售/滞销")] = None,
) -> list[dict]:
    rows = M.load(tenant).products
    if category:
        rows = [r for r in rows if r["category"] == category]
    if brand:
        rows = [r for r in rows if brand in r["brand"]]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.get("/products/{product_code}", operation_id="getProduct",
            summary="产品详情 + 防伪档案")
def get_product(
    product_code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    p = d.product_by_code.get(product_code)
    if p is None:
        raise HTTPException(404, f"product {product_code} not found")
    return {**p, "authenticity_profile": d.profile_by_product.get(product_code)}


@router.get("/categories", operation_id="listCategories",
            summary="品类列表")
def list_categories(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.load(tenant).categories


# ── 防伪 / 假货 ───────────────────────────────────────────────


@router.get("/counterfeit-samples", operation_id="listAntiCounterfeitSamples",
            summary="假货样本库（按产品/渠道/风险过滤）")
def list_counterfeit_samples(
    tenant: Annotated[str, Depends(get_tenant)],
    product_code: Annotated[str | None, Query()] = None,
    risk_level: Annotated[str | None, Query(description="高/中/低")] = None,
    verdict: Annotated[str | None, Query(description="正品/疑似假货/假货")] = None,
) -> list[dict]:
    rows = M.load(tenant).counterfeit_samples
    if product_code:
        rows = [r for r in rows if r["product_code"] == product_code]
    if risk_level:
        rows = [r for r in rows if r["risk_level"] == risk_level]
    if verdict:
        rows = [r for r in rows if r["verdict"] == verdict]
    return rows


@router.get("/authenticity-profiles/{product_code}", operation_id="getAuthenticityProfile",
            summary="正品防伪标识档案（笔身/包装/防伪标特征）")
def get_authenticity_profile(
    product_code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    p = M.load(tenant).profile_by_product.get(product_code)
    if p is None:
        raise HTTPException(404, f"authenticity profile for {product_code} not found")
    return p


@router.get("/identify-authenticity", operation_id="identifyAuthenticity",
            summary="抽检样本真伪鉴定（比对笔身/包装/防伪标识）")
def identify_authenticity(
    tenant: Annotated[str, Depends(get_tenant)],
    product_code: Annotated[str, Query(description="产品码 SKU-ZB-")] = "",
    sample_desc: Annotated[str, Query(description="抽检样本描述文本")] = "",
) -> dict:
    return M.identify_authenticity(tenant, product_code, sample_desc)


@router.get("/counterfeit-risk", operation_id="scoreCounterfeitRisk",
            summary="各区域/渠道假货分布与风险等级打分")
def score_counterfeit_risk(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.score_counterfeit_risk(tenant)


# ── 全渠道反馈 ───────────────────────────────────────────────


@router.get("/feedback", operation_id="listFeedback",
            summary="全渠道反馈列表（按类型/状态/产品过滤）")
def list_feedback(
    tenant: Annotated[str, Depends(get_tenant)],
    type: Annotated[str | None, Query(description="质量/功能/包装/书写体验")] = None,
    status: Annotated[str | None, Query(description="待处理/处理中/已闭环")] = None,
    product_code: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).feedback
    if type:
        rows = [r for r in rows if r["type"] == type]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if product_code:
        rows = [r for r in rows if r["product_code"] == product_code]
    return rows


@router.get("/feedback-stats", operation_id="listFeedbackStats",
            summary="反馈按 类型×产品 聚合统计（定位高频问题）")
def list_feedback_stats(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.feedback_stats(tenant)
