"""CHN 多租户确定性种子数据——agilestationery（敏睿文具，渠道与电商秩序）。

CHN 是叶系统，无循环依赖，沿用懒构建。``agilestationery`` 一份 ``ChnData``，覆盖
渠道商家（MR-，含授权状态）+ 低价窜货违规 + 非授权店铺 + 违规取证（EV-，关联 PIM
假货样本 CTF-）+ 渠道效能（投入产出）+ 竞品动态（CMP-）。

标识符：渠道商家 ``MR-``、违规取证 ``EV-``、竞品 ``CMP-``、渠道 ``CH-``。
假货样本 ``CTF-``（PIM）的 evidence_code 关联 CHN 取证 ``EV-`` 与违规商家 ``MR-``，
按 merchant_code 关联，勿直传 CTF 给 CHN（不同码空间，identifiers.md 显式消歧）。
"""

from __future__ import annotations

from dataclasses import dataclass

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry

BASE_DATE = "2026-07-14"


@dataclass
class ChnData:
    merchants: list[dict]                   # 渠道商家（含授权状态）
    merchant_by_code: dict[str, dict]
    price_violations: list[dict]            # 低价窜货违规
    unauthorized_stores: list[dict]         # 非授权店铺
    evidence: list[dict]                    # 违规取证（关联 PIM 假货样本）
    channel_performance: list[dict]         # 渠道效能（投入产出）
    competitors: list[dict]                 # 竞品动态
    competitor_by_code: dict[str, dict]


# ───────────────────────── agilestationery（敏睿文具） ─────────────────────────


def _build_agilestationery() -> ChnData:
    """敏睿文具渠道与电商秩序口径：经销商/电商/KA 渠道商家 + 低价窜货 + 非授权店 + 取证 + 效能 + 竞品。"""
    R = D.rng(20260716)

    merchants = [
        {"merchant_code": "MR-DL-01", "name": "华东文具分销·上海晨光联合体", "channel": "线下分销",
         "region": "华东", "type": "经销商", "authorized": True, "tier": "A",
         "owner": "黄淇", "monthly_sales": 680000, "payment_terms_days": 45, "status": "合作中"},
        {"merchant_code": "MR-DL-03", "name": "华南文具批发·广州联宝", "channel": "线下分销",
         "region": "华南", "type": "经销商", "authorized": True, "tier": "A",
         "owner": "林苒", "monthly_sales": 520000, "payment_terms_days": 30, "status": "合作中"},
        {"merchant_code": "MR-DL-05", "name": "西南 KA 集采·成都世纪文具", "channel": "KA客户",
         "region": "西南", "type": "KA大客户", "authorized": True, "tier": "B",
         "owner": "周琰", "monthly_sales": 310000, "payment_terms_days": 60, "status": "合作中"},
        {"merchant_code": "MR-DL-12", "name": "华东窜货商·义乌小商品城某档口", "channel": "线下分销",
         "region": "华东", "type": "经销商", "authorized": False, "tier": "D",
         "owner": "陈鹭", "monthly_sales": 95000, "payment_terms_days": 0, "status": "违规冻结"},
        {"merchant_code": "MR-EC-09", "name": "电商店铺·淘宝「敏睿正品直销店」(冒名)", "channel": "电商平台",
         "region": "华南", "type": "电商商家", "authorized": False, "tier": "D",
         "owner": "外部", "monthly_sales": 42000, "payment_terms_days": 0, "status": "维权中"},
        {"merchant_code": "MR-EC-15", "name": "电商店铺·拼多多「敏睿 工厂直供」(冒名)", "channel": "电商平台",
         "region": "华中", "type": "电商商家", "authorized": False, "tier": "D",
         "owner": "外部", "monthly_sales": 38000, "payment_terms_days": 0, "status": "维权中"},
        {"merchant_code": "MR-EC-21", "name": "电商店铺·京东第三方「敏睿海外专营」(冒名)", "channel": "电商平台",
         "region": "华北", "type": "电商商家", "authorized": False, "tier": "D",
         "owner": "外部", "monthly_sales": 51000, "payment_terms_days": 0, "status": "维权中"},
        {"merchant_code": "MR-EC-30", "name": "电商店铺·天猫「敏睿官方旗舰」(授权)", "channel": "电商平台",
         "region": "华东", "type": "电商商家", "authorized": True, "tier": "A",
         "owner": "黄淇", "monthly_sales": 430000, "payment_terms_days": 30, "status": "合作中"},
        {"merchant_code": "MR-DL-08", "name": "华北文具分销·北京世纪文仪", "channel": "线下分销",
         "region": "华北", "type": "经销商", "authorized": True, "tier": "B",
         "owner": "黄淇", "monthly_sales": 280000, "payment_terms_days": 45, "status": "合作中"},
    ]
    merchant_by_code = {m["merchant_code"]: m for m in merchants}

    # 低价窜货违规（低于指导价/跨区域窜货）
    price_violations = [
        {"violation_no": "PV20260701", "merchant_code": "MR-DL-12",
         "product_code": "SKU-ZB-G001", "list_price": 5.50, "actual_price": 3.20,
         "discount_pct": 41.8, "channel": "线下分销", "region": "华东",
         "detected_at": "2026-07-08T10:00:00", "type": "低价倾销", "status": "已取证",
         "evidence_code": "EV20260701"},
        {"violation_no": "PV20260702", "merchant_code": "MR-EC-09",
         "product_code": "SKU-ZB-G001", "list_price": 5.50, "actual_price": 2.90,
         "discount_pct": 47.3, "channel": "电商平台", "region": "华南",
         "detected_at": "2026-07-09T11:00:00", "type": "低价倾销+假冒", "status": "已取证",
         "evidence_code": "EV20260701"},
        {"violation_no": "PV20260703", "merchant_code": "MR-EC-15",
         "product_code": "SKU-ZB-G002", "list_price": 5.50, "actual_price": 3.10,
         "discount_pct": 43.6, "channel": "电商平台", "region": "华中",
         "detected_at": "2026-07-10T09:00:00", "type": "低价倾销", "status": "取证中",
         "evidence_code": "EV20260706"},
        {"violation_no": "PV20260704", "merchant_code": "MR-DL-12",
         "product_code": "SKU-ZB-B001", "list_price": 28.00, "actual_price": 15.00,
         "discount_pct": 46.4, "channel": "线下分销", "region": "华东",
         "detected_at": "2026-07-06T14:00:00", "type": "跨区窜货+低价", "status": "已取证",
         "evidence_code": "EV20260702"},
        {"violation_no": "PV20260705", "merchant_code": "MR-EC-21",
         "product_code": "SKU-ZB-M001", "list_price": 9.90, "actual_price": 5.80,
         "discount_pct": 41.4, "channel": "电商平台", "region": "华北",
         "detected_at": "2026-07-11T11:00:00", "type": "低价倾销", "status": "取证中",
         "evidence_code": "EV20260704"},
    ]

    # 非授权店铺
    unauthorized_stores = [
        {"store_code": "UNS-TB-09", "merchant_code": "MR-EC-09", "platform": "淘宝",
         "store_name": "敏睿正品直销店", "listed_products": 18, "fake_risk": "高",
         "detected_at": "2026-07-08T10:00:00", "status": "维权中", "evidence_codes": ["EV20260701"]},
        {"store_code": "UNS-PDD-15", "merchant_code": "MR-EC-15", "platform": "拼多多",
         "store_name": "敏睿 工厂直供", "listed_products": 22, "fake_risk": "高",
         "detected_at": "2026-07-10T09:00:00", "status": "维权中", "evidence_codes": ["EV20260706"]},
        {"store_code": "UNS-JD-21", "merchant_code": "MR-EC-21", "platform": "京东第三方",
         "store_name": "敏睿海外专营", "listed_products": 12, "fake_risk": "中",
         "detected_at": "2026-07-11T11:00:00", "status": "维权中", "evidence_codes": ["EV20260704"]},
        {"store_code": "UNS-XS-12", "merchant_code": "MR-DL-12", "platform": "线下档口",
         "store_name": "义乌小商品城档口", "listed_products": 9, "fake_risk": "高",
         "detected_at": "2026-07-06T14:00:00", "status": "冻结", "evidence_codes": ["EV20260701", "EV20260702"]},
    ]

    # 违规取证（EV-，关联 PIM 假货样本 CTF-.evidence_code）
    evidence = [
        {"evidence_code": "EV20260701", "merchant_code": "MR-EC-09", "product_code": "SKU-ZB-G001",
         "type": "假冒+低价", "collected_at": "2026-07-08T10:30:00",
         "detail": "抽检样本 CTF20260701 判定假货（笔夹无雕刻+丝印模糊+二维码失效）+低于指导价 47%",
         "pim_sample_code": "CTF20260701", "legal_status": "已取证待投诉", "platform": "淘宝"},
        {"evidence_code": "EV20260702", "merchant_code": "MR-DL-12", "product_code": "SKU-ZB-B001",
         "type": "假冒+窜货", "collected_at": "2026-07-06T14:30:00",
         "detail": "抽检样本 CTF20260702 判定假货（尾堵无 LOT+包装无防伪刮层）+跨区窜货",
         "pim_sample_code": "CTF20260702", "legal_status": "已取证待投诉", "platform": "线下"},
        {"evidence_code": "EV20260703", "merchant_code": "MR-DL-05", "product_code": "SKU-ZB-G001",
         "type": "疑似假货", "collected_at": "2026-07-10T09:45:00",
         "detail": "抽检样本 CTF20260703 疑似假货（二维码跳转异常+断墨），待复检",
         "pim_sample_code": "CTF20260703", "legal_status": "取证中", "platform": "KA客户"},
        {"evidence_code": "EV20260704", "merchant_code": "MR-EC-21", "product_code": "SKU-ZB-M001",
         "type": "假冒+低价", "collected_at": "2026-07-11T11:30:00",
         "detail": "抽检样本 CTF20260704 判定假货（笔帽字体模糊+墨水容量不符）+低价倾销",
         "pim_sample_code": "CTF20260704", "legal_status": "已取证待投诉", "platform": "京东"},
        {"evidence_code": "EV20260706", "merchant_code": "MR-EC-15", "product_code": "SKU-ZB-G002",
         "type": "假冒+低价", "collected_at": "2026-07-10T10:00:00",
         "detail": "抽检样本 CTF20260706 判定假货（丝印偏色+防伪标缺失）+低价倾销",
         "pim_sample_code": "CTF20260706", "legal_status": "已取证待投诉", "platform": "拼多多"},
    ]

    # 渠道效能（投入产出）
    channel_performance = [
        {"channel": "天猫旗舰", "merchant_code": "MR-EC-30", "region": "华东",
         "month": "2026-07", "gmv": 430000, "ad_spend": 28000, "traffic": 320000,
         "conversion_pct": 3.8, "refund_pct": 2.1, "roi": 15.4, "trend": "上升"},
        {"channel": "京东自营", "merchant_code": None, "region": "全国",
         "month": "2026-07", "gmv": 380000, "ad_spend": 22000, "traffic": 210000,
         "conversion_pct": 3.2, "refund_pct": 1.8, "roi": 17.3, "trend": "平稳"},
        {"channel": "拼多多", "merchant_code": None, "region": "全国",
         "month": "2026-07", "gmv": 95000, "ad_spend": 12000, "traffic": 180000,
         "conversion_pct": 2.1, "refund_pct": 4.5, "roi": 7.9, "trend": "下降"},
        {"channel": "线下分销华东", "merchant_code": "MR-DL-01", "region": "华东",
         "month": "2026-07", "gmv": 680000, "ad_spend": 8000, "traffic": None,
         "conversion_pct": None, "refund_pct": 0.8, "roi": 85.0, "trend": "上升"},
        {"channel": "线下分销华南", "merchant_code": "MR-DL-03", "region": "华南",
         "month": "2026-07", "gmv": 520000, "ad_spend": 6000, "traffic": None,
         "conversion_pct": None, "refund_pct": 1.0, "roi": 86.7, "trend": "平稳"},
        {"channel": "KA集采西南", "merchant_code": "MR-DL-05", "region": "西南",
         "month": "2026-07", "gmv": 310000, "ad_spend": 3000, "traffic": None,
         "conversion_pct": None, "refund_pct": 0.5, "roi": 103.3, "trend": "下降"},
    ]

    # 竞品动态（CMP-）
    competitors = [
        {"competitor_code": "CMP-01", "name": "百乐（Pilot）", "category": "中性笔/钢笔",
         "channel_policy": "线上直营+区域代理双轨", "new_product": "Pilot V5 系列新品中性笔",
         "price_range": "5-12 元", "ka_strategy": "重点抢校园/办公用品集采",
         "weakness": "线下乡镇渗透弱", "detected_at": "2026-07-10",
         "intel_summary": "百乐 7 月主推 V5 新品，线上投放加码，线下校园渠道促销力度大"},
        {"competitor_code": "CMP-02", "name": "三菱（Uni）", "category": "中性笔/记号笔",
         "channel_policy": "总代+经销商分级授权", "new_product": "Uni Signo 巨大中性笔",
         "price_range": "6-14 元", "ka_strategy": "政企采购渠道深耕",
         "weakness": "电商授权管控松，窜货多", "detected_at": "2026-07-09",
         "intel_summary": "三菱政企集采优势明显，但电商窜货管控薄弱，可作我方秩序管控对标"},
        {"competitor_code": "CMP-03", "name": "晨光（M&G）", "category": "学生文具/中性笔",
         "channel_policy": "加盟连锁+电商低价走量", "new_product": "晨光本味系列",
         "price_range": "2-6 元", "ka_strategy": "学生市场+下沉渠道密集分销",
         "weakness": "高端商务市场弱", "detected_at": "2026-07-12",
         "intel_summary": "晨光以低价与学生市场为主，与我方高端商务/进口品质定位错位竞争"},
        {"competitor_code": "CMP-04", "name": "得力（Deli）", "category": "办公文具综合",
         "channel_policy": "办公集采+电商自营", "new_product": "得力会议笔记本套装",
         "price_range": "3-30 元", "ka_strategy": "政企办公集采全品类打包",
         "weakness": "进口品牌调性不足", "detected_at": "2026-07-11",
         "intel_summary": "得力办公集采全品类打包能力强，建议在 B 端办公用品集采上与其正面竞争"},
    ]
    competitor_by_code = {c["competitor_code"]: c for c in competitors}

    return ChnData(
        merchants=merchants, merchant_by_code=merchant_by_code,
        price_violations=price_violations, unauthorized_stores=unauthorized_stores,
        evidence=evidence, channel_performance=channel_performance,
        competitors=competitors, competitor_by_code=competitor_by_code,
    )


TENANTS = LazyTenantRegistry[ChnData]({
    "agilestationery": _build_agilestationery,
})


def load(tenant: str) -> ChnData:
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量 ───────────────────────────────────────────────────


def score_violation_risk(tenant: str) -> list[dict]:
    """违规商家风险打分（低价力度×假冒取证×非授权×历史），输出优先维权队列。"""
    d = load(tenant)
    rows = []
    for m in d.merchants:
        if m["authorized"]:
            continue
        pvs = [p for p in d.price_violations if p["merchant_code"] == m["merchant_code"]]
        evs = [e for e in d.evidence if e["merchant_code"] == m["merchant_code"]]
        unss = [u for u in d.unauthorized_stores if u["merchant_code"] == m["merchant_code"]]
        max_discount = max((p["discount_pct"] for p in pvs), default=0)
        fake_evidence = sum(1 for e in evs if "假冒" in e["type"])
        score = round(
            max_discount * 1.0 + fake_evidence * 30 + len(unss) * 15 + len(pvs) * 5, 2)
        rows.append({
            "merchant_code": m["merchant_code"], "name": m["name"], "channel": m["channel"],
            "region": m["region"], "authorized": m["authorized"],
            "violation_count": len(pvs), "fake_evidence_count": fake_evidence,
            "unauthorized_store_count": len(unss), "max_discount_pct": max_discount,
            "risk_score": score, "risk_level": "高" if score >= 80 else ("中" if score >= 50 else "低"),
            "priority_rank": ("P0-立即维权" if score >= 80 else "P1-本周" if score >= 50 else "P2-观察"),
        })
    rows.sort(key=lambda r: r["risk_score"], reverse=True)
    return rows
