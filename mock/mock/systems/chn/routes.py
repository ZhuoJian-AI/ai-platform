"""CHN 路由——渠道与电商秩序只读查询。全部 GET。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as M

router = APIRouter(prefix="/api/v1", tags=["CHN 渠道与电商秩序"])


# ── 渠道商家 / 违规 / 取证 ───────────────────────────────────────


@router.get("/merchants", operation_id="listMerchants",
            summary="渠道商家列表（按渠道/授权状态/层级过滤）")
def list_merchants(
    tenant: Annotated[str, Depends(get_tenant)],
    channel: Annotated[str | None, Query(description="线下分销/电商平台/KA客户")] = None,
    authorized: Annotated[str | None, Query(description="true/false")] = None,
    tier: Annotated[str | None, Query(description="A/B/C/D")] = None,
) -> list[dict]:
    rows = M.load(tenant).merchants
    if channel:
        rows = [r for r in rows if r["channel"] == channel]
    if authorized is not None:
        want = authorized.lower() == "true"
        rows = [r for r in rows if r["authorized"] == want]
    if tier:
        rows = [r for r in rows if r["tier"] == tier]
    return rows


@router.get("/merchants/{merchant_code}", operation_id="getMerchant",
            summary="商家详情 + 关联违规/取证")
def get_merchant(
    merchant_code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = M.load(tenant)
    m = d.merchant_by_code.get(merchant_code)
    if m is None:
        raise HTTPException(404, f"merchant {merchant_code} not found")
    pvs = [p for p in d.price_violations if p["merchant_code"] == merchant_code]
    evs = [e for e in d.evidence if e["merchant_code"] == merchant_code]
    unss = [u for u in d.unauthorized_stores if u["merchant_code"] == merchant_code]
    return {**m, "price_violations": pvs, "evidence": evs, "unauthorized_stores": unss}


@router.get("/price-violations", operation_id="listPriceViolations",
            summary="低价窜货违规列表（按状态/类型过滤）")
def list_price_violations(
    tenant: Annotated[str, Depends(get_tenant)],
    status: Annotated[str | None, Query(description="已取证/取证中")] = None,
    type: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).price_violations
    if status:
        rows = [r for r in rows if r["status"] == status]
    if type:
        rows = [r for r in rows if type in r["type"]]
    return rows


@router.get("/unauthorized-stores", operation_id="listUnauthorizedStores",
            summary="非授权店铺列表（按平台/风险过滤）")
def list_unauthorized_stores(
    tenant: Annotated[str, Depends(get_tenant)],
    platform: Annotated[str | None, Query()] = None,
    fake_risk: Annotated[str | None, Query(description="高/中/低")] = None,
) -> list[dict]:
    rows = M.load(tenant).unauthorized_stores
    if platform:
        rows = [r for r in rows if platform in r["platform"]]
    if fake_risk:
        rows = [r for r in rows if r["fake_risk"] == fake_risk]
    return rows


@router.get("/evidence", operation_id="listEvidence",
            summary="违规取证列表（关联 PIM 假货样本）")
def list_evidence(
    tenant: Annotated[str, Depends(get_tenant)],
    merchant_code: Annotated[str | None, Query()] = None,
    type: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).evidence
    if merchant_code:
        rows = [r for r in rows if r["merchant_code"] == merchant_code]
    if type:
        rows = [r for r in rows if type in r["type"]]
    return rows


@router.get("/violation-risk", operation_id="scoreViolationRisk",
            summary="违规商家风险打分与优先维权队列")
def score_violation_risk(
    tenant: Annotated[str, Depends(get_tenant)],
) -> list[dict]:
    return M.score_violation_risk(tenant)


# ── 渠道效能 / 竞品 ───────────────────────────────────────────


@router.get("/channel-performance", operation_id="listChannelPerformance",
            summary="渠道效能分析（GMV/投放/转化/ROI）")
def list_channel_performance(
    tenant: Annotated[str, Depends(get_tenant)],
    channel: Annotated[str | None, Query()] = None,
    trend: Annotated[str | None, Query(description="上升/平稳/下降")] = None,
) -> list[dict]:
    rows = M.load(tenant).channel_performance
    if channel:
        rows = [r for r in rows if channel in r["channel"]]
    if trend:
        rows = [r for r in rows if r["trend"] == trend]
    return rows


@router.get("/competitors", operation_id="listCompetitors",
            summary="竞品动态列表（渠道政策/新品/价格/策略）")
def list_competitors(
    tenant: Annotated[str, Depends(get_tenant)],
    category: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = M.load(tenant).competitors
    if category:
        rows = [r for r in rows if category in r["category"]]
    return rows


@router.get("/competitors/{competitor_code}", operation_id="getCompetitor",
            summary="竞品详情 + 渠道/新品/价格/弱点")
def get_competitor(
    competitor_code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    c = M.load(tenant).competitor_by_code.get(competitor_code)
    if c is None:
        raise HTTPException(404, f"competitor {competitor_code} not found")
    return c
