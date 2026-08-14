"""EHS 多租户确定性种子数据——agilesteel（敏睿钢铁，安全管理）。

EHS 是叶系统，无循环依赖，沿用懒构建。``agilesteel`` 一份 ``EhsData``，覆盖
隐患台账（含整改闭环状态）+ 违章记录（AI 识别 + 人工核实）+ 巡检记录 + 风险点分级
（红/橙/黄/蓝）+ 劳保用品台账 + 培训记录。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry

BASE_DATE: date = date(2026, 6, 29)


@dataclass
class EhsData:
    hazards: list[dict]                          # 隐患台账（含整改闭环）
    hazard_by_code: dict[str, dict]
    violations: list[dict]                       # 违章记录
    violation_by_code: dict[str, dict]
    inspections: list[dict]                      # 巡检记录
    safety_risks: list[dict]                    # 风险点分级
    ppe: list[dict]                              # 劳保用品台账
    training_records: list[dict]                # 安全培训记录


# ───────────────────────── agilesteel（敏睿钢铁） ─────────────────────────


def _build_agilesteel() -> EhsData:
    """敏睿钢铁安全管理口径：隐患 + 违章 + 巡检 + 风险点 + 劳保 + 培训。"""
    R = D.rng(20260617)

    hazards = [
        {"code": "HD20260001", "area": "炼钢厂2#转炉", "category": "高温液渣喷溅",
         "level": "红", "found_at": f"{BASE_DATE - timedelta(days=6)}T09:10:00",
         "found_by": "saf-inspector", "desc": "2#转炉倾动时液渣喷溅，威胁炉前作业人员",
         "rectification": "增设挡渣墙+炉前工退至安全距离操作", "responsible_dept": "炼钢厂",
         "deadline": f"{BASE_DATE + timedelta(days=2)}", "status": "整改中",
         "equipment_code": "EQ-CV-2"},
        {"code": "HD20260002", "area": "炼铁厂1#高炉炉台", "category": "煤气泄漏",
         "level": "红", "found_at": f"{BASE_DATE - timedelta(days=4)}T14:20:00",
         "found_by": "AI视觉", "desc": "1#高炉炉台煤气区域报警器浓度趋升，疑似阀门微漏",
         "rectification": "阀门打压查漏+更换密封+作业票升级", "responsible_dept": "炼铁厂",
         "deadline": f"{BASE_DATE + timedelta(days=1)}", "status": "整改中",
         "equipment_code": "EQ-BF-1"},
        {"code": "HD20260003", "area": "轧钢厂3#连轧机检修", "category": "未挂牌",
         "level": "橙", "found_at": f"{BASE_DATE - timedelta(days=3)}T08:40:00",
         "found_by": "saf-inspector", "desc": "3#连轧机检修未执行 LOTO 挂牌，存在误启动风险",
         "rectification": "补办 LOTO 挂牌+培训检修规程", "responsible_dept": "轧钢厂",
         "deadline": f"{BASE_DATE}", "status": "待整改",
         "equipment_code": "EQ-RM-3"},
        {"code": "HD20260004", "area": "炼钢厂连铸平台", "category": "防护设施缺失",
         "level": "黄", "found_at": f"{BASE_DATE - timedelta(days=8)}T10:30:00",
         "found_by": "saf-inspector", "desc": "连铸平台安全防护栏局部缺失",
         "rectification": "补焊防护栏+定期巡检", "responsible_dept": "炼钢厂",
         "deadline": f"{BASE_DATE - timedelta(days=2)}", "status": "已闭环",
         "equipment_code": "EQ-CCM-1"},
        {"code": "HD20260005", "area": "原料场", "category": "环保设施破损",
         "level": "蓝", "found_at": f"{BASE_DATE - timedelta(days=12)}T11:00:00",
         "found_by": "AI视觉", "desc": "原料场防尘网局部破损，扬尘风险",
         "rectification": "更换防尘网", "responsible_dept": "原料场",
         "deadline": f"{BASE_DATE + timedelta(days=5)}", "status": "整改中",
         "equipment_code": None},
        {"code": "HD20260006", "area": "炼钢厂受限空间", "category": "作业票未办",
         "level": "橙", "found_at": f"{BASE_DATE - timedelta(days=2)}T15:00:00",
         "found_by": "saf-inspector", "desc": "炼钢区受限空间作业未办理作业票",
         "rectification": "立即停工补办作业票+通风检测", "responsible_dept": "炼钢厂",
         "deadline": f"{BASE_DATE}", "status": "待整改",
         "equipment_code": None},
        {"code": "HD20260007", "area": "轧钢厂天车", "category": "安全装置失效",
         "level": "橙", "found_at": f"{BASE_DATE - timedelta(days=1)}T09:30:00",
         "found_by": "AI视觉", "desc": "轧材天车限位器失效，存在冲顶风险",
         "rectification": "更换限位器+特种设备复检", "responsible_dept": "轧钢厂",
         "deadline": f"{BASE_DATE + timedelta(days=1)}", "status": "整改中",
         "equipment_code": None},
    ]
    hazard_by_code = {h["code"]: h for h in hazards}

    violations = [
        {"code": "VIO20260701", "type": "未戴安全帽", "area": "炼钢厂生产区",
         "detected_by": "AI视觉", "detected_at": f"{BASE_DATE - timedelta(days=1)}T08:15:00",
         "person": "ASSA042", "desc": "进入生产区未佩戴安全帽",
         "severity": "一般", "status": "已核实", "penalty": "扣 200 元+通报"},
        {"code": "VIO20260702", "type": "高处作业未系带", "area": "轧钢厂3#连轧机",
         "detected_by": "AI视觉", "detected_at": f"{BASE_DATE - timedelta(days=2)}T10:20:00",
         "person": "ASSA108", "desc": "高处检修作业未系安全带",
         "severity": "严重", "status": "已核实", "penalty": "扣 500 元+停岗培训"},
        {"code": "VIO20260703", "type": "违规动火", "area": "炼钢厂2#转炉区域",
         "detected_by": "AI视觉", "detected_at": f"{BASE_DATE - timedelta(days=3)}T14:00:00",
         "person": "ASSA055", "desc": "煤气区域违规吸烟",
         "severity": "严重", "status": "已核实", "penalty": "扣 1000 元+待岗"},
        {"code": "VIO20260704", "type": "未执行LOTO", "area": "轧钢厂3#连轧机检修",
         "detected_by": "saf-inspector", "detected_at": f"{BASE_DATE - timedelta(days=3)}T08:40:00",
         "person": "ASSA077", "desc": "检修未执行挂牌上锁",
         "severity": "严重", "status": "已核实", "penalty": "扣 500 元+复训"},
        {"code": "VIO20260705", "type": "未佩报警器", "area": "炼铁厂1#高炉煤气区域",
         "detected_by": "AI视觉", "detected_at": f"{BASE_DATE - timedelta(days=4)}T09:00:00",
         "person": "ASSA021", "desc": "煤气区域未佩戴便携式报警器",
         "severity": "严重", "status": "已核实", "penalty": "扣 500 元+复训"},
        {"code": "VIO20260706", "type": "未穿防护服", "area": "炼钢厂炉前",
         "detected_by": "AI视觉", "detected_at": f"{BASE_DATE - timedelta(days=5)}T11:30:00",
         "person": "ASSA013", "desc": "炉前作业未穿高温防护服",
         "severity": "一般", "status": "待核实", "penalty": None},
    ]
    violation_by_code = {v["code"]: v for v in violations}

    inspections = [
        {"code": "INS20260701", "area": "炼铁厂1#高炉", "type": "周巡检",
         "inspector": "saf-inspector", "inspected_at": f"{BASE_DATE - timedelta(days=1)}T09:00:00",
         "findings": 2, "hazards_found": ["HD20260002"], "status": "已完成"},
        {"code": "INS20260702", "area": "轧钢厂轧材线", "type": "日巡检",
         "inspector": "saf-inspector", "inspected_at": f"{BASE_DATE}T08:00:00",
         "findings": 1, "hazards_found": ["HD20260003"], "status": "已完成"},
        {"code": "INS20260703", "area": "炼钢厂连铸", "type": "专项巡检",
         "inspector": "saf-inspector", "inspected_at": f"{BASE_DATE - timedelta(days=2)}T14:00:00",
         "findings": 2, "hazards_found": ["HD20260001", "HD20260006"], "status": "已完成"},
    ]

    safety_risks = [
        {"area": "炼钢厂转炉主控室", "level": "红", "desc": "高温液渣喷溅高风险区",
         "exposed_persons": 12, "controls": "挡渣墙+安全距离+防护服"},
        {"area": "炼铁厂1#高炉炉台", "level": "红", "desc": "煤气泄漏高风险区",
         "exposed_persons": 8, "controls": "报警器+通风+作业票"},
        {"area": "炼钢厂连铸二冷室", "level": "橙", "desc": "受限空间作业风险",
         "exposed_persons": 5, "controls": "作业票+通风检测+监护"},
        {"area": "轧钢厂3#连轧机", "level": "黄", "desc": "检修误启动风险",
         "exposed_persons": 6, "controls": "LOTO 挂牌+联锁"},
        {"area": "原料场", "level": "蓝", "desc": "扬尘环保风险",
         "exposed_persons": 15, "controls": "防尘网+喷淋"},
        {"area": "化验室", "level": "蓝", "desc": "化学试剂风险",
         "exposed_persons": 4, "controls": "MSDS+通风柜"},
    ]

    ppe = [
        {"code": "PPE-HELMET", "name": "安全帽", "stock_qty": 1200, "safety_stock": 200,
         "status": "充足", "check_date": f"{BASE_DATE}"},
        {"code": "PPE-MASK", "name": "防尘口罩", "stock_qty": 800, "safety_stock": 300,
         "status": "充足", "check_date": f"{BASE_DATE}"},
        {"code": "PPE-GASALARM", "name": "便携式煤气报警器", "stock_qty": 45, "safety_stock": 60,
         "status": "不足", "check_date": f"{BASE_DATE}"},
        {"code": "PPE-HARNESS", "name": "安全带", "stock_qty": 80, "safety_stock": 50,
         "status": "充足", "check_date": f"{BASE_DATE}"},
        {"code": "PPE-HOTSUIT", "name": "高温防护服", "stock_qty": 40, "safety_stock": 45,
         "status": "不足", "check_date": f"{BASE_DATE}"},
    ]

    training_records = [
        {"code": "TRN202601", "name": "三级安全教育", "type": "新员工",
         "attendees": 28, "completed": 28, "date": f"{BASE_DATE - timedelta(days=20)}",
         "status": "已完成"},
        {"code": "TRN202602", "name": "煤气作业专项培训", "type": "特种作业",
         "attendees": 15, "completed": 13, "date": f"{BASE_DATE - timedelta(days=10)}",
         "status": "进行中"},
        {"code": "TRN202603", "name": "天车特种作业复训", "type": "复训",
         "attendees": 22, "completed": 22, "date": f"{BASE_DATE - timedelta(days=5)}",
         "status": "已完成"},
    ]

    return EhsData(
        hazards=hazards, hazard_by_code=hazard_by_code,
        violations=violations, violation_by_code=violation_by_code,
        inspections=inspections, safety_risks=safety_risks,
        ppe=ppe, training_records=training_records,
    )


TENANTS = LazyTenantRegistry[EhsData]({
    "agilesteel": _build_agilesteel,
})


def load(tenant: str) -> EhsData:
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量 ───────────────────────────────────────────────────

# 违章类型 → 规程条款 + 整改建议（用于 detectViolationType 业务端点）
_VIOLATION_RULES = {
    "未戴安全帽": {"regulation": "《安全生产责任制》§3.2 进入生产区须佩戴安全帽",
                  "category": "个人防护", "fix": "立即补戴+班组安全教育+扣分"},
    "高处作业未系带": {"regulation": "《高处作业安全管理规定》§4.1 2m 以上作业须系安全带",
                     "category": "高处作业", "fix": "停工补系+高处作业复训"},
    "违规动火": {"regulation": "《动火作业管理规定》§2.1 煤气区域严禁动火吸烟",
               "category": "动火作业", "fix": "清离现场+煤气检测+复训"},
    "未执行LOTO": {"regulation": "《检修挂牌上锁规定》§3.1 检修须执行 LOTO",
                 "category": "检修作业", "fix": "补办挂牌+联锁验证+复训"},
    "未佩报警器": {"regulation": "《煤气安全管理规定》§5.2 煤气区域须佩戴报警器",
                "category": "煤气作业", "fix": "补发报警器+煤气作业专项培训"},
    "未穿防护服": {"regulation": "《劳动防护用品管理规定》§3.3 炉前作业须穿高温防护服",
                "category": "个人防护", "fix": "补穿防护服+劳保盘点"},
}


def classify_violation(tenant: str, desc: str) -> dict:
    """由违章描述 → 分类(违章类型/规程条款/整改建议)。"""
    d = load(tenant)
    # 先按描述命中违章类型
    hit_type = None
    for vtype in _VIOLATION_RULES:
        if vtype in desc:
            hit_type = vtype
            break
    if hit_type is None:
        # 模糊匹配：取已知违章记录里 type 包含描述关键词的
        for v in d.violations:
            if v["type"] in desc or any(k in desc for k in v["type"]):
                hit_type = v["type"]
                break
    if hit_type is None:
        return {"input": desc, "matched_type": None,
                "regulation": None, "category": None, "fix": "无法自动分类，转人工核实"}
    rule = _VIOLATION_RULES[hit_type]
    related = [v["code"] for v in d.violations if v["type"] == hit_type]
    return {"input": desc, "matched_type": hit_type,
            "regulation": rule["regulation"], "category": rule["category"],
            "fix": rule["fix"], "related_violations": related}


def score_hazard_priority(tenant: str) -> list[dict]:
    """隐患整改优先级打分（风险等级×暴露人数×剩余天数）。"""
    d = load(tenant)
    level_weight = {"红": 1.0, "橙": 0.7, "黄": 0.4, "蓝": 0.2}
    today = BASE_DATE
    rows = []
    for h in d.hazards:
        if h["status"] == "已闭环":
            continue
        lw = level_weight.get(h["level"], 0.2)
        risk_area = next((r for r in d.safety_risks if r["area"] in h["area"]), None)
        exposed = risk_area["exposed_persons"] if risk_area else 5
        try:
            deadline = date.fromisoformat(h["deadline"])
            days_left = (deadline - today).days
        except Exception:  # noqa: BLE001
            days_left = 7
        urgency = max(0, 10 - days_left)  # 越临近越高
        score = round(lw * 100 + exposed * 2 + urgency * 5, 2)
        rows.append({
            "code": h["code"], "area": h["area"], "category": h["category"],
            "level": h["level"], "status": h["status"],
            "responsible_dept": h["responsible_dept"], "deadline": h["deadline"],
            "days_left": days_left, "exposed_persons": exposed,
            "priority_score": score,
            "priority_rank": ("P0-立即" if score >= 100 else "P1-本周" if score >= 60 else "P2-两周"),
        })
    rows.sort(key=lambda r: r["priority_score"], reverse=True)
    return rows
