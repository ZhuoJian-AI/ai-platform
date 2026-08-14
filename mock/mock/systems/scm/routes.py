"""SCM 路由——供应商/报价/产能/到货/补单/交期/校验只读查询 + 写入演示。

多租户：经 ``Depends(get_tenant)`` 取 ``X-API-Key`` 解析的 tenant，再调
``data.load(tenant)`` 取数。``operationId`` 保持稳定值，平台 spec 导入与已绑定
技能不受影响。

PD-2 关键端点（绝不缓存）：
  - ``GET /leadtime-diff`` —— 同面料同供应商较 since 快照的交期变化；
  - ``GET /estimate-leadtime`` —— 按当前产能占用 + 面料到货在途实时估算交期。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from mock.core.tenant import get_tenant
from . import data as S

router = APIRouter(prefix="/api/v1", tags=["SCM 供应链协同"])

BASE_DATE = S.BASE_DATE


# ── 供应商 ─────────────────────────────────────────────────


@router.get("/suppliers", operation_id="listSuppliers", summary="供应商列表")
def list_suppliers(
    tenant: Annotated[str, Depends(get_tenant)],
    category: Annotated[str | None, Query(description="面料/辅料/外协/辅料包装")] = None,
    keyword: Annotated[str | None, Query(description="名称模糊匹配")] = None,
) -> list[dict]:
    rows = S.load(tenant).suppliers
    if category:
        rows = [r for r in rows if r["category"] == category]
    if keyword:
        rows = [r for r in rows if keyword in r["name"]]
    return rows


@router.get("/suppliers/{code}", operation_id="getSupplier", summary="供应商详情 + 产能/报价")
def get_supplier(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = S.load(tenant)
    s = d.supplier_by_code.get(code)
    if s is None:
        raise HTTPException(404, f"supplier {code} not found")
    return {
        **s,
        "quotations": [q for q in d.quotations if q["supplier_code"] == code],
        "capacity": [c for c in d.capacity_calendar if c["supplier_code"] == code],
        "arrival_plans": [p for p in d.fabric_arrival_plans if p["supplier_code"] == code],
    }


# ── 报价单 / 比价 ──────────────────────────────────────────


@router.get("/quotations", operation_id="listQuotations", summary="报价单列表")
def list_quotations(
    tenant: Annotated[str, Depends(get_tenant)],
    supplier_code: Annotated[str | None, Query()] = None,
    material_code: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="有效/已过期/已下单")] = None,
) -> list[dict]:
    rows = S.load(tenant).quotations
    if supplier_code:
        rows = [r for r in rows if r["supplier_code"] == supplier_code]
    if material_code:
        rows = [r for r in rows if r["material_code"] == material_code]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


# 注意：/quotations/compare 必须在 /quotations/{quotation_no} 之前注册，
# 否则 {quotation_no} 路径参数会捕获 "compare" 字面量导致 404。
@router.get("/quotations/compare", operation_id="compareQuotations",
            summary="同规格多家报价对比（综合评分排序）")
def compare_quotations(
    tenant: Annotated[str, Depends(get_tenant)],
    material_code: Annotated[str, Query(description="物料编码，如 M-WOOL-DBL-360")] = ...,
) -> dict:
    d = S.load(tenant)
    cands = [q for q in d.quotations
             if q["material_code"] == material_code and q["status"] in ("有效", "已下单")]
    if not cands:
        raise HTTPException(404, f"no valid quotation for {material_code}")

    prices = [q["unit_price"] for q in cands]
    leads = [q["leadtime_days"] for q in cands]
    pays = [q["payment_terms_days"] for q in cands]
    p_min, p_max = min(prices), max(prices)
    l_min, l_max = min(leads), max(leads)
    pay_max = max(pays) or 1

    rows: list[dict] = []
    for q in cands:
        # 价格分（40）：越低越高；leadtime 分（30）：越短越高；账期分（30）：越长越高（采购方资金占用少）
        price_score = ((p_max - q["unit_price"]) / (p_max - p_min) * 40) if p_max > p_min else 20.0
        lead_score = ((l_max - q["leadtime_days"]) / (l_max - l_min) * 30) if l_max > l_min else 15.0
        pay_min = min(pays)
        pay_score = ((q["payment_terms_days"] - pay_min) / (pay_max - pay_min) * 30) if pay_max > pay_min else 15.0
        score = round(price_score + lead_score + pay_score, 2)
        rows.append({
            "supplier_code": q["supplier_code"],
            "supplier_name": q["supplier_name"],
            "quotation_no": q["quotation_no"],
            "spec": q["spec"],
            "unit_price": q["unit_price"],
            "moq": q["moq"],
            "leadtime_days": q["leadtime_days"],
            "payment_terms_days": q["payment_terms_days"],
            "valid_until": q["valid_until"],
            "score": score,
            "score_breakdown": {
                "price_score": round(price_score, 2),
                "leadtime_score": round(lead_score, 2),
                "payment_score": round(pay_score, 2),
            },
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    return {
        "material_code": material_code,
        "candidate_count": len(rows),
        "best_supplier": rows[0]["supplier_code"] if rows else None,
        "items": rows,
    }


@router.get("/quotations/{quotation_no}", operation_id="getQuotation", summary="报价单详情")
def get_quotation(
    quotation_no: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    d = S.load(tenant)
    q = d.quotation_by_no.get(quotation_no)
    if q is None:
        raise HTTPException(404, f"quotation {quotation_no} not found")
    return q



# ── 产能日历 ───────────────────────────────────────────────


@router.get("/capacity-calendar", operation_id="listCapacityCalendar",
            summary="供应商产能日历")
def list_capacity_calendar(
    tenant: Annotated[str, Depends(get_tenant)],
    supplier_code: Annotated[str | None, Query()] = None,
    date: Annotated[str | None, Query(description="YYYY-MM-DD 精确过滤")] = None,
) -> list[dict]:
    rows = S.load(tenant).capacity_calendar
    if supplier_code:
        rows = [r for r in rows if r["supplier_code"] == supplier_code]
    if date:
        rows = [r for r in rows if r["date"] == date]
    return rows


@router.get("/suppliers/{code}/capacity", operation_id="getSupplierCapacity",
            summary="供应商未来 N 天产能占用")
def get_supplier_capacity(
    code: Annotated[str, Path()],
    tenant: Annotated[str, Depends(get_tenant)],
    days: Annotated[int, Query(ge=1, le=90)] = 14,
) -> dict:
    d = S.load(tenant)
    s = d.supplier_by_code.get(code)
    if s is None:
        raise HTTPException(404, f"supplier {code} not found")
    cap = s["capacity_per_day"]
    # 该供应商已知日历项（按日期索引）
    known = {c["date"]: c for c in d.capacity_calendar if c["supplier_code"] == code}
    # 取该供应商最近一条已知占用率作为缺口填充基线
    recent_util = 0.70
    known_sorted = sorted(known.values(), key=lambda c: c["date"])
    if known_sorted:
        recent_util = known_sorted[-1]["utilization_pct"] / 100.0

    items: list[dict] = []
    for i in range(days):
        dte = BASE_DATE + timedelta(days=i)
        key = f"{dte}"
        if key in known:
            c = known[key]
            items.append({
                "date": key, "total_capacity": c["total_capacity"],
                "used": c["used"], "available": c["available"],
                "utilization_pct": c["utilization_pct"], "uom": c.get("uom"),
                "source": "calendar",
            })
        else:
            used = int(cap * recent_util)
            items.append({
                "date": key, "total_capacity": cap,
                "used": used, "available": max(0, cap - used),
                "utilization_pct": round(recent_util * 100, 1),
                "uom": s["specialty"].split("/")[0] if s["category"] == "面料" else
                       ("条" if "拉链" in s["specialty"] else
                        ("粒" if "纽扣" in s["specialty"] else
                         ("件" if "水洗" in s["specialty"] else "个"))),
                "source": "projected",
            })
    avg_util = round(sum(it["utilization_pct"] for it in items) / max(1, len(items)), 1)
    return {
        "supplier_code": code, "supplier_name": s["name"],
        "capacity_per_day": cap, "days": days,
        "from_date": f"{BASE_DATE}", "to_date": f"{BASE_DATE + timedelta(days=days - 1)}",
        "avg_utilization_pct": avg_util,
        "items": items,
    }


# ── 面料到货计划 ───────────────────────────────────────────


@router.get("/fabric-arrival-plans", operation_id="listFabricArrivalPlans",
            summary="面料在途到货计划")
def list_fabric_arrival_plans(
    tenant: Annotated[str, Depends(get_tenant)],
    supplier_code: Annotated[str | None, Query()] = None,
    material_code: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query(description="在途/已到货/延误")] = None,
) -> list[dict]:
    rows = S.load(tenant).fabric_arrival_plans
    if supplier_code:
        rows = [r for r in rows if r["supplier_code"] == supplier_code]
    if material_code:
        rows = [r for r in rows if r["material_code"] == material_code]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


# ── 补单节奏建议 ──────────────────────────────────────────


@router.get("/replenishment-suggestions", operation_id="listReplenishmentSuggestions",
            summary="补单节奏建议列表")
def list_replenishment_suggestions(
    tenant: Annotated[str, Depends(get_tenant)],
    style_code: Annotated[str | None, Query()] = None,
    bulk_no: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = S.load(tenant).replenishment_suggestions
    if style_code:
        rows = [r for r in rows if r["style_code"] == style_code]
    if bulk_no:
        rows = [r for r in rows if r["bulk_no"] == bulk_no]
    return rows


@router.get("/suggest-replenishment", operation_id="suggestReplenishment",
            summary="按交期反推 + 产能占用给补单节奏")
def suggest_replenishment(
    tenant: Annotated[str, Depends(get_tenant)],
    style_code: Annotated[str, Query(description="款号")] = ...,
    total_qty: Annotated[int, Query(gt=0)] = ...,
    delivery_date: Annotated[str, Query(description="YYYY-MM-DD 目标交期")] = ...,
) -> dict:
    d = S.load(tenant)
    # 已有同款号建议则优先返回，并叠加目标交期约束
    existed = [r for r in d.replenishment_suggestions if r["style_code"] == style_code]
    base = existed[0] if existed else None

    try:
        dd = datetime.strptime(delivery_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "delivery_date must be YYYY-MM-DD")

    # 默认三批：40% / 33% / 27%，按交期倒推每批间隔 10 天
    first_qty = int(total_qty * 0.40)
    r1_qty = int(total_qty * 0.33)
    r2_qty = total_qty - first_qty - r1_qty
    r2_date = dd
    r1_date = dd - timedelta(days=10)
    first_date = dd - timedelta(days=20)

    if base:
        return {
            "source": "seeded",
            "style_code": style_code, "total_qty": total_qty, "delivery_date": delivery_date,
            "first_batch_qty": base["first_batch_qty"], "first_batch_date": base["first_batch_date"],
            "replenish_1_qty": base["replenish_1_qty"], "replenish_1_date": base["replenish_1_date"],
            "replenish_2_qty": base["replenish_2_qty"], "replenish_2_date": base["replenish_2_date"],
            "fabric_arrival_date": base["fabric_arrival_date"],
            "factory_capacity_note": base["factory_capacity_note"],
            "risks": base["risks"],
            "adjusted_first_date": f"{first_date}",
            "delivery_feasible": (first_date >= (datetime.strptime(
                base["fabric_arrival_date"], "%Y-%m-%d").date() if base["fabric_arrival_date"] else BASE_DATE)),
        }
    return {
        "source": "computed",
        "style_code": style_code, "total_qty": total_qty, "delivery_date": delivery_date,
        "first_batch_qty": first_qty, "first_batch_date": f"{first_date}",
        "replenish_1_qty": r1_qty, "replenish_1_date": f"{r1_date}",
        "replenish_2_qty": r2_qty, "replenish_2_date": f"{r2_date}",
        "fabric_arrival_date": None,
        "factory_capacity_note": "按 40/33/27 节奏 + 10 天间隔默认推算",
        "risks": [],
    }


# ── 交期快照 / 异动检测（PD-2 关键，绝不缓存） ───────────────


@router.get("/leadtime-snapshots", operation_id="listLeadtimeSnapshots",
            summary="交期快照列表")
def list_leadtime_snapshots(
    tenant: Annotated[str, Depends(get_tenant)],
    material_code: Annotated[str | None, Query()] = None,
    supplier_code: Annotated[str | None, Query()] = None,
) -> list[dict]:
    rows = S.load(tenant).leadtime_snapshots
    if material_code:
        rows = [r for r in rows if r["material_code"] == material_code]
    if supplier_code:
        rows = [r for r in rows if r["supplier_code"] == supplier_code]
    return rows


@router.get("/leadtime-diff", operation_id="getLeadtimeDiff",
            summary="实时交期异动检测（PD-2 关键端点，绝不缓存）")
def get_leadtime_diff(
    tenant: Annotated[str, Depends(get_tenant)],
    material_code: Annotated[str, Query()] = ...,
    supplier_code: Annotated[str, Query()] = ...,
    since: Annotated[str, Query(description="ISO 时间戳，取该时刻之后的最新快照为基线")] = ...,
) -> dict:
    d = S.load(tenant)
    try:
        since_raw = since.replace("Z", "+00:00")
        since_dt = datetime.fromisoformat(since_raw)
        # 快照的 snapshot_at 是 offset-naive（如 2026-06-10T09:00:00），统一去掉 tz 信息对比
        if since_dt.tzinfo is not None:
            since_dt = since_dt.replace(tzinfo=None)
    except ValueError:
        raise HTTPException(400, "since must be ISO datetime")

    snaps = [s for s in d.leadtime_snapshots
             if s["material_code"] == material_code and s["supplier_code"] == supplier_code]
    snaps = sorted(snaps, key=lambda s: s["snapshot_at"])
    if not snaps:
        raise HTTPException(404, "no snapshot for material+supplier")

    # 基线 = since 时刻及之前的最新快照；对比 = since 之后最新快照（无则取最后一条）
    baseline = None
    for s in snaps:
        sdt = datetime.fromisoformat(s["snapshot_at"])
        if sdt <= since_dt:
            baseline = s
    if baseline is None:
        baseline = snaps[0]   # since 早于所有快照，用最早做基线
    after = [s for s in snaps
             if datetime.fromisoformat(s["snapshot_at"]) > since_dt]
    latest = after[-1] if after else snaps[-1]

    delta = latest["leadtime_days"] - baseline["leadtime_days"]
    return {
        "material_code": material_code,
        "supplier_code": supplier_code,
        "baseline_snapshot_id": baseline["snapshot_id"],
        "baseline_leadtime_days": baseline["leadtime_days"],
        "baseline_snapshot_at": baseline["snapshot_at"],
        "latest_snapshot_id": latest["snapshot_id"],
        "latest_leadtime_days": latest["leadtime_days"],
        "latest_snapshot_at": latest["snapshot_at"],
        "delta_days": delta,
        "trend": "延长" if delta > 0 else ("缩短" if delta < 0 else "持平"),
        "cached": False,
        "tenant": tenant,
    }


@router.get("/estimate-leadtime", operation_id="estimateLeadtime",
            summary="按产能占用 + 在途实时估算交期（PD-2 关键端点，绝不缓存）")
def estimate_leadtime(
    tenant: Annotated[str, Depends(get_tenant)],
    material_code: Annotated[str, Query()] = ...,
    qty: Annotated[int, Query(gt=0)] = ...,
) -> dict:
    d = S.load(tenant)
    # 选首选供应商：有有效报价者取报价交期最短者，否则取产能日历中该物料首条供应商
    quotes = [q for q in d.quotations
              if q["material_code"] == material_code and q["status"] in ("有效", "已下单")]
    if not quotes:
        raise HTTPException(404, f"no quotation for {material_code}")
    quotes.sort(key=lambda q: q["leadtime_days"])
    chosen = quotes[0]
    sup = d.supplier_by_code.get(chosen["supplier_code"])
    cap = sup["capacity_per_day"] if sup else 0

    # 该供应商已知日历占用率 → 取最近一条作为当前占用基线
    cal = [c for c in d.capacity_calendar if c["supplier_code"] == chosen["supplier_code"]]
    cal.sort(key=lambda c: c["date"])
    recent_util = (cal[-1]["utilization_pct"] / 100.0) if cal else 0.70
    available_per_day = max(1, int(cap * (1 - recent_util)))

    days_needed = max(1, math.ceil(qty / available_per_day))
    quote_leadtime = chosen["leadtime_days"]
    # 取该物料在途到货：若存在则面料到位前不能开工
    arrivals = [p for p in d.fabric_arrival_plans
                if p["material_code"] == material_code and p["status"] in ("在途", "延误")]
    fabric_ready_date = None
    fabric_block_days = 0
    if arrivals:
        # 取最晚一条到货 ETA 作为面料齐料日
        latest_eta = max(
            (datetime.strptime(a["eta"], "%Y-%m-%d").date() for a in arrivals),
            default=None,
        )
        if latest_eta:
            fabric_ready_date = f"{latest_eta}"
            fabric_block_days = max(0, (latest_eta - BASE_DATE).days)
    production_start = BASE_DATE + timedelta(days=fabric_block_days)
    estimated_delivery = production_start + timedelta(days=max(days_needed, quote_leadtime))
    # 延误风险：若该物料在途有 delay_days > 0，标记风险
    delay_risk = next((a for a in arrivals if a.get("delay_days", 0) > 0), None)

    return {
        "material_code": material_code,
        "qty": qty,
        "chosen_supplier_code": chosen["supplier_code"],
        "chosen_supplier_name": chosen["supplier_name"],
        "quotation_no": chosen["quotation_no"],
        "capacity_per_day": cap,
        "current_utilization_pct": round(recent_util * 100, 1),
        "available_capacity_per_day": available_per_day,
        "days_needed_by_capacity": days_needed,
        "quote_leadtime_days": quote_leadtime,
        "fabric_arrival_date": fabric_ready_date,
        "fabric_arrival_status": (delay_risk["status"] if delay_risk else
                                  (arrivals[0]["status"] if arrivals else "无在途")),
        "fabric_delay_days": (delay_risk["delay_days"] if delay_risk else 0),
        "production_start_date": f"{production_start}",
        "estimated_delivery_date": f"{estimated_delivery}",
        "total_leadtime_days": (estimated_delivery - BASE_DATE).days,
        "risks": (["面料在途延误，开工推迟"] if delay_risk else []),
        "cached": False,
        "tenant": tenant,
    }


# ── 物料校验（SC-1） ───────────────────────────────────────


@router.get("/material-validations", operation_id="listMaterialValidations",
            summary="物料校验记录（工厂端/我方端双向）")
def list_material_validations(
    tenant: Annotated[str, Depends(get_tenant)],
    initiated_by: Annotated[str | None, Query(description="factory/internal")] = None,
    work_order: Annotated[str | None, Query(description="MES 工单号")] = None,
    status: Annotated[str | None, Query(description="正常/缺料/超领")] = None,
) -> list[dict]:
    rows = S.load(tenant).material_validations
    if initiated_by:
        rows = [r for r in rows if r["initiated_by"] == initiated_by]
    if work_order:
        rows = [r for r in rows if r["work_order_no"] == work_order]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@router.post("/material-validations", operation_id="createMaterialValidation",
             summary="新建物料校验记录（写入演示，区分工厂端/我方端发起）")
def create_material_validation(
    tenant: Annotated[str, Depends(get_tenant)],
    payload: Annotated[dict, Body(examples=[{
        "initiated_by": "factory",
        "work_order_no": "WO20260607",
        "style_code": "XT-DS2026-001",
        "bom_material_code": "M-WOOL-DBL-360",
        "required_qty": 1500, "actual_qty": 1480,
        "operator": "裁剪-王", "check_date": "2026-06-29",
    }])] = None,
) -> dict:
    d = S.load(tenant)
    p = payload or {}
    required = float(p.get("required_qty", 0) or 0)
    actual = float(p.get("actual_qty", 0) or 0)
    variance = round(actual - required, 2)
    variance_pct = round((variance / required * 100) if required else 0.0, 2)
    if variance_pct < -5:
        status = "缺料"
    elif variance_pct > 5:
        status = "超领"
    else:
        status = "正常"
    seq = len(d.material_validations) + 1
    vid = f"MV-{seq:03d}"
    return {
        "validation_id": vid,
        "initiated_by": p.get("initiated_by", "internal"),
        "work_order_no": p.get("work_order_no"),
        "style_code": p.get("style_code"),
        "bom_material_code": p.get("bom_material_code"),
        "required_qty": required,
        "actual_qty": actual,
        "variance_qty": variance,
        "variance_pct": variance_pct,
        "status": status,
        "operator": p.get("operator", ""),
        "check_date": p.get("check_date", f"{BASE_DATE}"),
        "tenant": tenant,
        "created": True,
    }


# ── 废钢分级（agilesteel） ─────────────────────────────────

@router.get("/scrap-grades", operation_id="listScrapGrades",
            summary="废钢分级列表（密度/杂质限/价格/适用钢种）")
def list_scrap_grades(
    tenant: Annotated[str, Depends(get_tenant)],
    category: Annotated[str | None, Query(description="重废/破碎料/车屑")] = None,
) -> list[dict]:
    rows = S.load(tenant).scrap_grades
    if category:
        rows = [r for r in rows if r["category"] == category]
    return rows


@router.get("/scrap-grades/{scrap_code}/price", operation_id="getScrapPrice",
            summary="废钢牌价详情（含适用钢种）")
def get_scrap_price(
    scrap_code: Annotated[str, Path(description="废钢码 SCR-...，如 SCR-HMS1")],
    tenant: Annotated[str, Depends(get_tenant)],
) -> dict:
    g = S.load(tenant).scrap_grade_by_code.get(scrap_code)
    if g is None:
        raise HTTPException(404, f"scrap grade {scrap_code} not found")
    return g
