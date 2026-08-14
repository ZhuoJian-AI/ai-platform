"""PIM 多租户确定性种子数据——agilestationery（敏睿文具，产品与防伪）。

PIM 是叶系统，无循环依赖，沿用懒构建。``agilestationery`` 一份 ``PimData``，覆盖
文具产品/SKU 主数据 + 品类 + 防伪标识档案 + 假货样本库（含真伪判定）+ 全渠道反馈
（质量/功能/包装/书写体验四维分类）。

标识符：产品 ``SKU-ZB-``、品类 ``CAT-``、防伪样本 ``CTF-``、反馈 ``FB-``。
产品码 ``SKU-ZB-`` 与 ERP 物料 ``M-ZB-`` 不同码空间，按 product_code/material_code
关联时需 prefix 转换（identifiers.md 显式消歧）。
"""

from __future__ import annotations

from dataclasses import dataclass

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry

BASE_DATE = "2026-07-14"


@dataclass
class PimData:
    products: list[dict]                       # 文具产品/SKU 主数据
    product_by_code: dict[str, dict]
    categories: list[dict]                     # 品类
    counterfeit_samples: list[dict]           # 假货样本库（含真伪判定与比对细节）
    sample_by_code: dict[str, dict]
    authenticity_profiles: list[dict]         # 防伪标识档案（笔身/包装/防伪标）
    profile_by_product: dict[str, dict]
    feedback: list[dict]                      # 全渠道反馈（质量/功能/包装/书写体验）


# ───────────────────────── agilestationery（敏睿文具） ─────────────────────────


def _build_agilestationery() -> PimData:
    """敏睿文具产品与防伪口径：中性笔/圆珠笔/记号笔/荧光笔 + 防伪标识 + 假货样本 + 全渠道反馈。"""
    R = D.rng(20260714)

    categories = [
        {"code": "CAT-GEL", "name": "中性笔", "desc": "凝胶中性墨水笔，主力品"},
        {"code": "CAT-BALL", "name": "圆珠笔", "desc": "油性圆珠笔，经典款"},
        {"code": "CAT-MARK", "name": "记号笔", "desc": "白板/永久记号笔"},
        {"code": "CAT-HIGHLIGHT", "name": "荧光笔", "desc": "荧光高亮笔"},
        {"code": "CAT-REFILL", "name": "笔芯", "desc": "替换芯"},
    ]

    products = [
        {"product_code": "SKU-ZB-G001", "name": "敏睿中性笔 0.5 黑",
         "category": "CAT-GEL", "brand": "敏睿", "uom": "支",
         "unit_cost": 2.80, "list_price": 5.50, "status": "在售", "launch_date": "2025-03-01",
         "lifecycle": "成长期", "jp_source_code": "MR-中性笔-BK"},
        {"product_code": "SKU-ZB-G002", "name": "敏睿中性笔 0.5 红",
         "category": "CAT-GEL", "brand": "敏睿", "uom": "支",
         "unit_cost": 2.80, "list_price": 5.50, "status": "在售", "launch_date": "2025-03-01",
         "lifecycle": "成长期", "jp_source_code": "MR-中性笔-RD"},
        {"product_code": "SKU-ZB-B001", "name": "敏睿金属圆珠笔",
         "category": "CAT-BALL", "brand": "敏睿", "uom": "支",
         "unit_cost": 12.50, "list_price": 28.00, "status": "在售", "launch_date": "2024-06-15",
         "lifecycle": "成熟期", "jp_source_code": "MR-金属圆珠笔"},
        {"product_code": "SKU-ZB-M001", "name": "敏睿油性记号笔",
         "category": "CAT-MARK", "brand": "敏睿", "uom": "支",
         "unit_cost": 4.20, "list_price": 9.90, "status": "在售", "launch_date": "2025-01-10",
         "lifecycle": "成长期", "jp_source_code": "MR-MK-1"},
        {"product_code": "SKU-ZB-H001", "name": "敏睿荧光笔 黄",
         "category": "CAT-HIGHLIGHT", "brand": "敏睿", "uom": "支",
         "unit_cost": 3.10, "list_price": 6.80, "status": "在售", "launch_date": "2024-09-01",
         "lifecycle": "成熟期", "jp_source_code": "MR-荧光笔-YW"},
        {"product_code": "SKU-ZB-G010", "name": "敏睿中性笔 0.4 蓝",
         "category": "CAT-GEL", "brand": "敏睿", "uom": "支",
         "unit_cost": 3.50, "list_price": 7.20, "status": "在售", "launch_date": "2026-02-20",
         "lifecycle": "导入期", "jp_source_code": "MR-SRS-04-BL"},
        {"product_code": "SKU-ZB-G011", "name": "敏睿中性笔 0.4 黑",
         "category": "CAT-GEL", "brand": "敏睿", "uom": "支",
         "unit_cost": 3.50, "list_price": 7.20, "status": "在售", "launch_date": "2026-02-20",
         "lifecycle": "导入期", "jp_source_code": "MR-SRS-04-BK"},
        {"product_code": "SKU-ZB-R001", "name": "敏睿替换芯 0.5",
         "category": "CAT-REFILL", "brand": "敏睿", "uom": "支",
         "unit_cost": 1.20, "list_price": 2.80, "status": "在售", "launch_date": "2025-03-15",
         "lifecycle": "成长期", "jp_source_code": "MR-中性笔-REF"},
        {"product_code": "SKU-ZB-B002", "name": "敏睿细字圆珠笔",
         "category": "CAT-BALL", "brand": "敏睿", "uom": "支",
         "unit_cost": 2.50, "list_price": 5.90, "status": "滞销", "launch_date": "2023-05-10",
         "lifecycle": "衰退期", "jp_source_code": "MR-细字圆珠笔"},
        {"product_code": "SKU-ZB-M002", "name": "敏睿细字记号笔",
         "category": "CAT-MARK", "brand": "敏睿", "uom": "支",
         "unit_cost": 4.20, "list_price": 9.90, "status": "在售", "launch_date": "2025-01-10",
         "lifecycle": "成长期", "jp_source_code": "MR-MK-2"},
    ]
    product_by_code = {p["product_code"]: p for p in products}

    # 防伪标识档案：正品笔身/包装/防伪标特征（用于比对鉴定）
    authenticity_profiles = [
        {"product_code": "SKU-ZB-G001", "cap_marking": "笔夹印 敏睿 激光雕刻",
         "body_print": "笔身印 中性笔 黑色丝印，字迹清晰锐利",
         "anti_fake_label": "笔身内侧防伪二维码 + 日本敏睿 hologram 标",
         "refill_spec": "金属笔尖 0.5mm 三点承托", "pack_barcode": "条码 4902031XXXXXX"},
        {"product_code": "SKU-ZB-B001", "cap_marking": "金属笔夹刻 敏睿",
         "body_print": "金属笔身拉丝工艺，尾堵印 LOT 编号",
         "anti_fake_label": "包装盒防伪刮层 + hologram 标",
         "refill_spec": "0.7mm 金属子弹头笔芯", "pack_barcode": "条码 4902031XXXXXY"},
        {"product_code": "SKU-ZB-M001", "cap_marking": "笔帽印 模塑字体",
         "body_print": "笔身印 敏睿 油性记号笔，墨水容量标示",
         "anti_fake_label": "笔身防伪镭射标 + 双语说明",
         "refill_spec": "纤维笔头，不可替芯", "pack_barcode": "条码 4902031XXXXXZ"},
        {"product_code": "SKU-ZB-G010", "cap_marking": "笔夹印 中性笔 金属夹",
         "body_print": "笔身印 中性笔 0.4 丝印",
         "anti_fake_label": "笔身内侧二维码 + hologram 标",
         "refill_spec": "0.4mm 金属笔尖", "pack_barcode": "条码 4902031XXXXXA"},
    ]
    profile_by_product = {p["product_code"]: p for p in authenticity_profiles}

    # 假货样本库（抽检/维权取证，含真伪判定与比对细节）
    counterfeit_samples = [
        {"sample_code": "CTF20260701", "product_code": "SKU-ZB-G001",
         "source": "华南电商抽检", "merchant_code": "MR-EC-09",
         "reported_at": "2026-07-08T10:20:00", "channel": "电商平台",
         "suspect_features": "笔夹无激光雕刻，笔身丝印模糊偏色，防伪二维码扫不出",
         "verdict": "假货", "confidence": 0.92, "risk_level": "高",
         "matched_profile_diff": "cap_marking 缺失+body_print 模糊+anti_fake_label 失效",
         "evidence_code": "EV20260701", "status": "已取证"},
        {"sample_code": "CTF20260702", "product_code": "SKU-ZB-B001",
         "source": "华东经销商窜货抽检", "merchant_code": "MR-DL-12",
         "reported_at": "2026-07-06T14:00:00", "channel": "线下分销",
         "suspect_features": "尾堵无 LOT 编号，包装盒无防伪刮层",
         "verdict": "假货", "confidence": 0.88, "risk_level": "高",
         "matched_profile_diff": "anti_fake_label 缺失+body_print LOT 缺失",
         "evidence_code": "EV20260702", "status": "已取证"},
        {"sample_code": "CTF20260703", "product_code": "SKU-ZB-G001",
         "source": "西南KA客户投诉", "merchant_code": "MR-DL-05",
         "reported_at": "2026-07-10T09:30:00", "channel": "KA客户",
         "suspect_features": "书写断墨，笔身二维码可扫但跳转异常",
         "verdict": "疑似假货", "confidence": 0.61, "risk_level": "中",
         "matched_profile_diff": "二维码跳转异常+书写断墨（墨水疑似劣质）",
         "evidence_code": "EV20260703", "status": "取证中"},
        {"sample_code": "CTF20260704", "product_code": "SKU-ZB-M001",
         "source": "华北电商抽检", "merchant_code": "MR-EC-21",
         "reported_at": "2026-07-11T11:00:00", "channel": "电商平台",
         "suspect_features": "笔帽字体模糊，墨水容量与正品不符",
         "verdict": "假货", "confidence": 0.85, "risk_level": "高",
         "matched_profile_diff": "cap_marking 模糊+body_print 容量不符",
         "evidence_code": "EV20260704", "status": "已取证"},
        {"sample_code": "CTF20260705", "product_code": "SKU-ZB-G010",
         "source": "华南经销商正常抽检", "merchant_code": "MR-DL-03",
         "reported_at": "2026-07-12T15:30:00", "channel": "线下分销",
         "suspect_features": "笔夹金属夹、丝印清晰、二维码可扫跳转正常",
         "verdict": "正品", "confidence": 0.95, "risk_level": "低",
         "matched_profile_diff": "全部特征匹配正品档案",
         "evidence_code": "EV20260705", "status": "已归档"},
        {"sample_code": "CTF20260706", "product_code": "SKU-ZB-G002",
         "source": "华中电商抽检", "merchant_code": "MR-EC-15",
         "reported_at": "2026-07-09T16:00:00", "channel": "电商平台",
         "suspect_features": "笔身丝印颜色偏淡，防伪标缺失",
         "verdict": "假货", "confidence": 0.83, "risk_level": "高",
         "matched_profile_diff": "body_print 偏色+anti_fake_label 缺失",
         "evidence_code": "EV20260706", "status": "已取证"},
    ]
    sample_by_code = {s["sample_code"]: s for s in counterfeit_samples}

    # 全渠道反馈（B端客户反馈/售后工单/渠道投诉，按质量/功能/包装/书写体验分类）
    feedback = [
        {"feedback_code": "FB20260701", "product_code": "SKU-ZB-G001",
         "source": "经销商反馈", "channel": "线下分销", "region": "华东",
         "type": "书写体验", "severity": "一般", "status": "待处理",
         "content": "部分批次 中性笔 0.5 黑偶有首笔不出墨", "qty_affected": 120,
         "reported_at": "2026-07-05T09:00:00", "owner": "prd-quality"},
        {"feedback_code": "FB20260702", "product_code": "SKU-ZB-B001",
         "source": "KA客户工单", "channel": "KA客户", "region": "华北",
         "type": "功能", "severity": "严重", "status": "处理中",
         "content": "金属笔夹松动脱落，影响使用", "qty_affected": 35,
         "reported_at": "2026-07-06T14:00:00", "owner": "prd-quality"},
        {"feedback_code": "FB20260703", "product_code": "SKU-ZB-M001",
         "source": "电商评价", "channel": "电商平台", "region": "华南",
         "type": "质量", "severity": "一般", "status": "待处理",
         "content": "记号笔墨水偏淡，标记不持久", "qty_affected": 80,
         "reported_at": "2026-07-07T10:30:00", "owner": "prd-quality"},
        {"feedback_code": "FB20260704", "product_code": "SKU-ZB-H001",
         "source": "经销商反馈", "channel": "线下分销", "region": "西南",
         "type": "包装", "severity": "一般", "status": "已闭环",
         "content": "荧光笔外包装色卡与实物色差偏大", "qty_affected": 200,
         "reported_at": "2026-07-03T11:00:00", "owner": "prd-quality"},
        {"feedback_code": "FB20260705", "product_code": "SKU-ZB-G010",
         "source": "电商评价", "channel": "电商平台", "region": "华中",
         "type": "书写体验", "severity": "一般", "status": "处理中",
         "content": "中性笔 0.4 新品偶尔刮纸，书写阻力偏大", "qty_affected": 60,
         "reported_at": "2026-07-10T08:00:00", "owner": "prd-quality"},
        {"feedback_code": "FB20260706", "product_code": "SKU-ZB-G001",
         "source": "KA客户工单", "channel": "KA客户", "region": "华南",
         "type": "质量", "severity": "严重", "status": "处理中",
         "content": "中性笔整批笔尖偏磨，书写出墨不均", "qty_affected": 500,
         "reported_at": "2026-07-09T14:30:00", "owner": "prd-quality"},
        {"feedback_code": "FB20260707", "product_code": "SKU-ZB-R001",
         "source": "经销商反馈", "channel": "线下分销", "region": "华东",
         "type": "功能", "severity": "一般", "status": "待处理",
         "content": "中性笔 替换芯与部分旧款笔杆配合偏紧", "qty_affected": 90,
         "reported_at": "2026-07-11T09:00:00", "owner": "prd-quality"},
        {"feedback_code": "FB20260708", "product_code": "SKU-ZB-B002",
         "source": "电商评价", "channel": "电商平台", "region": "华北",
         "type": "书写体验", "severity": "一般", "status": "已闭环",
         "content": "细字笔出墨偏少，疑似滞销库存墨水干涸", "qty_affected": 150,
         "reported_at": "2026-07-02T13:00:00", "owner": "prd-quality"},
    ]

    return PimData(
        products=products, product_by_code=product_by_code,
        categories=categories,
        counterfeit_samples=counterfeit_samples, sample_by_code=sample_by_code,
        authenticity_profiles=authenticity_profiles, profile_by_product=profile_by_product,
        feedback=feedback,
    )


TENANTS = LazyTenantRegistry[PimData]({
    "agilestationery": _build_agilestationery,
})


def load(tenant: str) -> PimData:
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量 ───────────────────────────────────────────────────


def identify_authenticity(tenant: str, product_code: str, sample_desc: str) -> dict:
    """由抽检样本描述 + 正品防伪档案 → 真伪判定（verdict/confidence/risk_level/差异点）。

    先查是否有同 product_code 的已判定假货样本（命中即复用其结论），否则按描述与
    正品档案特征逐项比对，缺失/异常特征多判假货。
    """
    d = load(tenant)
    profile = d.profile_by_product.get(product_code)
    if profile is None:
        return {"product_code": product_code, "input": sample_desc,
                "verdict": "无法鉴定", "confidence": 0.0, "risk_level": "未知",
                "matched_profile_diff": "无该产品防伪档案，转人工核实"}
    # 复用已判定的同款样本结论
    for s in d.counterfeit_samples:
        if s["product_code"] == product_code and sample_desc and (
                s["suspect_features"][:8] in sample_desc or sample_desc[:8] in s["suspect_features"]):
            return {"product_code": product_code, "input": sample_desc,
                    "verdict": s["verdict"], "confidence": s["confidence"],
                    "risk_level": s["risk_level"],
                    "matched_profile_diff": s["matched_profile_diff"],
                    "sample_code": s["sample_code"]}
    # 按关键词与正品档案逐项比对
    diffs = []
    keywords = {"cap_marking": ["笔夹", "笔帽", "雕刻", "模塑"],
                "body_print": ["笔身", "丝印", "印字"],
                "anti_fake_label": ["二维码", "防伪", "hologram", "刮层", "镭射"]}
    for field, kws in keywords.items():
        if any(k in sample_desc for k in kws):
            if any(neg in sample_desc for neg in ["无", "缺失", "模糊", "偏色", "异常", "失效", "假"]):
                diffs.append(f"{field} 异常")
    if not diffs:
        return {"product_code": product_code, "input": sample_desc,
                "verdict": "正品", "confidence": 0.90, "risk_level": "低",
                "matched_profile_diff": "描述特征与正品档案一致"}
    confidence = round(min(0.95, 0.60 + 0.12 * len(diffs)), 2)
    verdict = "假货" if confidence >= 0.80 else "疑似假货"
    risk = "高" if confidence >= 0.80 else "中"
    return {"product_code": product_code, "input": sample_desc,
            "verdict": verdict, "confidence": confidence, "risk_level": risk,
            "matched_profile_diff": "；".join(diffs) + "（对照正品档案）"}


def feedback_stats(tenant: str) -> list[dict]:
    """全渠道反馈按 类型×产品 维度聚合统计，定位高频问题。"""
    d = load(tenant)
    bucket: dict[tuple, dict] = {}
    for f in d.feedback:
        key = (f["product_code"], f["type"])
        b = bucket.setdefault(key, {"product_code": f["product_code"],
                                     "type": f["type"], "count": 0,
                                     "qty_affected": 0, "severe_count": 0,
                                     "open_count": 0, "samples": []})
        b["count"] += 1
        b["qty_affected"] += f["qty_affected"]
        if f["severity"] == "严重":
            b["severe_count"] += 1
        if f["status"] != "已闭环":
            b["open_count"] += 1
        if len(b["samples"]) < 2:
            b["samples"].append(f["feedback_code"])
    rows = sorted(bucket.values(), key=lambda r: (r["severe_count"], r["qty_affected"]), reverse=True)
    for r in rows:
        r["samples"] = ", ".join(r["samples"])
    return rows


def score_counterfeit_risk(tenant: str) -> list[dict]:
    """各区域/渠道假货出现频次 → 风险等级（高/中/低）打分。"""
    d = load(tenant)
    fake = [s for s in d.counterfeit_samples if s["verdict"] in ("假货", "疑似假货")]
    bucket: dict[tuple, dict] = {}
    for s in fake:
        key = (s["channel"], s["source"][:2])
        b = bucket.setdefault(key, {"channel": s["channel"], "region_tag": s["source"][:2],
                                    "fake_count": 0, "high_confidence": 0,
                                    "avg_confidence": 0.0, "samples": []})
        b["fake_count"] += 1
        b["high_confidence"] += 1 if s["confidence"] >= 0.80 else 0
        b["avg_confidence"] += s["confidence"]
        b["samples"].append(s["sample_code"])
    rows = []
    for b in bucket.values():
        b["avg_confidence"] = round(b["avg_confidence"] / b["fake_count"], 2) if b["fake_count"] else 0
        score = round(b["fake_count"] * 30 + b["high_confidence"] * 25 + b["avg_confidence"] * 20, 2)
        b["risk_score"] = score
        b["risk_level"] = "高" if score >= 80 else ("中" if score >= 50 else "低")
        b["samples"] = ", ".join(b["samples"])
        rows.append(b)
    rows.sort(key=lambda r: r["risk_score"], reverse=True)
    return rows
