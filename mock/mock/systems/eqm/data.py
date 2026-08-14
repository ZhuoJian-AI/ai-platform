"""EQM 多租户确定性种子数据——agilesteel（敏睿钢铁，设备预测性维护）。

EQM 是叶系统（其他 mock 不引用 EQM），无循环依赖，沿用懒构建保持一致。
``agilesteel`` 一份 ``EqmData``，覆盖关键设备档案（高炉/转炉/连铸/轧机/精炼/空压）/
备件清单 / 传感器时序（振动·温度·电流近 30 天）/ 故障历史（MTBF/MTTR）/ 预测性
维护建议 / 设备健康分。

设备编码 ``EQ-`` 与 MES agilesteel equipment **共享码空间**：MES 看设备运行状态，
EQM 看同码设备的预测性维护外延（同码不同系统，闭环不冲突）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry

BASE_DATE: date = date(2026, 6, 29)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class EqmData:
    equipment: list[dict]                      # 关键设备档案
    equip_by_code: dict[str, dict]
    spare_parts: list[dict]                    # 备件清单
    spare_by_code: dict[str, dict]
    sensor_readings: list[dict]               # 近 30 天传感器时序（按设备/日期）
    fault_history: list[dict]                  # 故障历史（含 MTBF/MTTR）
    maintenance_plans: list[dict]              # 预测性维护建议（待执行/已执行）
    health_scores: dict[str, dict]            # 设备健康分快照


# ───────────────────────── agilesteel（敏睿钢铁） ─────────────────────────


def _build_agilesteel() -> EqmData:
    """敏睿钢铁设备管理口径：高炉/转炉/连铸/轧机/精炼/空压/除尘风机 +
    备件 + 30 天传感器时序 + 故障历史 + 预测性维护建议 + 健康分。"""
    R = D.rng(20260615)

    equipment = [
        {"code": "EQ-BF-1", "name": "1#高炉", "type": "高炉", "workshop": "炼铁厂",
         "criticality": "A", "commission_date": "2016-09-01", "status": "running"},
        {"code": "EQ-BF-2", "name": "2#高炉", "type": "高炉", "workshop": "炼铁厂",
         "criticality": "A", "commission_date": "2018-04-12", "status": "running"},
        {"code": "EQ-CV-1", "name": "1#转炉", "type": "转炉", "workshop": "炼钢厂",
         "criticality": "A", "commission_date": "2017-06-20", "status": "running"},
        {"code": "EQ-CV-2", "name": "2#转炉", "type": "转炉", "workshop": "炼钢厂",
         "criticality": "A", "commission_date": "2019-11-05", "status": "fault"},
        {"code": "EQ-CCM-1", "name": "1#连铸机", "type": "连铸机", "workshop": "炼钢厂",
         "criticality": "A", "commission_date": "2017-08-01", "status": "running"},
        {"code": "EQ-LF-1", "name": "1#精炼炉LF", "type": "精炼炉", "workshop": "炼钢厂",
         "criticality": "B", "commission_date": "2018-12-10", "status": "running"},
        {"code": "EQ-RH-1", "name": "1#精炼炉RH", "type": "精炼炉", "workshop": "炼钢厂",
         "criticality": "B", "commission_date": "2020-03-15", "status": "running"},
        {"code": "EQ-RM-1", "name": "1#连轧机", "type": "连轧机", "workshop": "轧钢厂",
         "criticality": "A", "commission_date": "2016-05-01", "status": "running"},
        {"code": "EQ-RM-3", "name": "3#连轧机", "type": "连轧机", "workshop": "轧钢厂",
         "criticality": "A", "commission_date": "2019-02-28", "status": "maintenance"},
        {"code": "EQ-AC-1", "name": "1#空压机", "type": "空压机", "workshop": "公辅",
         "criticality": "B", "commission_date": "2018-07-01", "status": "running"},
        {"code": "EQ-FAN-1", "name": "1#除尘风机", "type": "除尘风机", "workshop": "公辅",
         "criticality": "B", "commission_date": "2017-10-10", "status": "running"},
    ]
    equip_by_code = {e["code"]: e for e in equipment}

    spare_parts = [
        {"code": "SP-CV-TUYERE", "name": "转炉氧枪枪头", "fit_equipment": "EQ-CV-1,EQ-CV-2",
         "stock_qty": 6, "safety_stock": 4, "unit_cost": 18500.0, "supplier": "S-STEEL-012",
         "interchange": "SP-CV-LANCE"},
        {"code": "SP-CV-LANCE", "name": "氧枪本体", "fit_equipment": "EQ-CV-1,EQ-CV-2",
         "stock_qty": 2, "safety_stock": 2, "unit_cost": 92000.0, "supplier": "S-STEEL-012",
         "interchange": None},
        {"code": "SP-RM-ROLL", "name": "轧机轧辊", "fit_equipment": "EQ-RM-1,EQ-RM-3",
         "stock_qty": 3, "safety_stock": 4, "unit_cost": 76000.0, "supplier": "S-STEEL-015",
         "interchange": None},
        {"code": "SP-BF-COOLING", "name": "高炉冷却壁", "fit_equipment": "EQ-BF-1,EQ-BF-2",
         "stock_qty": 8, "safety_stock": 6, "unit_cost": 42000.0, "supplier": "S-STEEL-018",
         "interchange": None},
        {"code": "SP-CCM-MOLD", "name": "连铸结晶器", "fit_equipment": "EQ-CCM-1",
         "stock_qty": 1, "safety_stock": 2, "unit_cost": 158000.0, "supplier": "S-STEEL-020",
         "interchange": None},
        {"code": "SP-LF-ELECTRODE", "name": "精炼电极", "fit_equipment": "EQ-LF-1",
         "stock_qty": 12, "safety_stock": 8, "unit_cost": 9800.0, "supplier": "S-STEEL-022",
         "interchange": None},
        {"code": "SP-FAN-BEARING", "name": "除尘风机轴承", "fit_equipment": "EQ-FAN-1",
         "stock_qty": 2, "safety_stock": 3, "unit_cost": 6500.0, "supplier": "S-STEEL-025",
         "interchange": None},
    ]
    spare_by_code = {s["code"]: s for s in spare_parts}

    # 传感器时序：近 30 天，重点设备 EQ-CV-2（将故障）/ EQ-RM-3（待维护）/ EQ-FAN-1
    sensor_readings: list[dict] = []
    focus_eqs = [
        ("EQ-CV-2", 1.6, 9.2, 320.0, "fault"),    # 振动↑温度↑电流↑
        ("EQ-RM-3", 1.2, 7.5, 280.0, "maintenance"),
        ("EQ-FAN-1", 1.4, 6.8, 90.0, "running"),
        ("EQ-BF-1", 0.8, 5.2, 0.0, "running"),
        ("EQ-CCM-1", 0.9, 5.6, 0.0, "running"),
    ]
    for code, vib_base, temp_base, curr_base, _st in focus_eqs:
        for d_off in range(-29, 1):
            day = BASE_DATE + timedelta(days=d_off)
            # 后期（临近今日）振动/温度呈上升趋势，模拟劣化
            degrade = (d_off + 29) / 29.0
            sensor_readings.append({
                "equipment_code": code,
                "date": day.isoformat(),
                "vibration_mm_s": round(vib_base * (1 + degrade * 0.6) + D.randfloat(R, -0.1, 0.1), 3),
                "temperature_c": round(temp_base * (1 + degrade * 0.25) + D.randfloat(R, -0.3, 0.3), 2),
                "current_a": round(curr_base * (1 + degrade * 0.15) + D.randfloat(R, -2, 2), 2)
                if curr_base > 0 else None,
                "oil_pressure_mpa": round(0.42 + degrade * 0.05 + D.randfloat(R, -0.01, 0.01), 3),
            })

    fault_history = [
        {"fault_id": "EQF20260301", "equipment_code": "EQ-CV-2", "fault_desc": "氧枪漏水停机",
         "occurred_at": f"{BASE_DATE - timedelta(days=115)}T08:20:00", "downtime_hours": 6.5,
         "root_cause": "氧枪枪头烧穿冷却水泄漏", "corrective": "更换氧枪枪头 SP-CV-TUYERE",
         "spare_used": "SP-CV-TUYERE"},
        {"fault_id": "EQF20260215", "equipment_code": "EQ-RM-3", "fault_desc": "轧辊剥落",
         "occurred_at": f"{BASE_DATE - timedelta(days=129)}T14:10:00", "downtime_hours": 14.0,
         "root_cause": "轧辊疲劳裂纹扩展导致表层剥落", "corrective": "更换轧辊 SP-RM-ROLL 并磨削",
         "spare_used": "SP-RM-ROLL"},
        {"fault_id": "EQF20260120", "equipment_code": "EQ-BF-1", "fault_desc": "冷却壁烧穿",
         "occurred_at": f"{BASE_DATE - timedelta(days=156)}T22:30:00", "downtime_hours": 32.0,
         "root_cause": "冷却壁长期热负荷过高局部烧穿", "corrective": "更换冷却壁 SP-BF-COOLING",
         "spare_used": "SP-BF-COOLING"},
        {"fault_id": "EQF20260228", "equipment_code": "EQ-FAN-1", "fault_desc": "轴承振动超限",
         "occurred_at": f"{BASE_DATE - timedelta(days=120)}T06:45:00", "downtime_hours": 4.0,
         "root_cause": "轴承磨损间隙增大引发振动超标", "corrective": "更换轴承 SP-FAN-BEARING",
         "spare_used": "SP-FAN-BEARING"},
        {"fault_id": "EQF20260108", "equipment_code": "EQ-CCM-1", "fault_desc": "结晶器漏钢",
         "occurred_at": f"{BASE_DATE - timedelta(days=172)}T11:00:00", "downtime_hours": 18.0,
         "root_cause": "结晶器铜板磨损液面波动漏钢", "corrective": "更换结晶器 SP-CCM-MOLD",
         "spare_used": "SP-CCM-MOLD"},
        {"fault_id": "EQF20251205", "equipment_code": "EQ-CV-2", "fault_desc": "倾动减速机异响",
         "occurred_at": f"{BASE_DATE - timedelta(days=206)}T03:20:00", "downtime_hours": 9.0,
         "root_cause": "减速机齿轮点蚀", "corrective": "齿轮修复并换油", "spare_used": None},
    ]

    maintenance_plans = [
        {"plan_no": "MP202607001", "equipment_code": "EQ-CV-2", "type": "预测性维护",
         "desc": "氧枪系统预测更换（振动+温度趋势双双超警）", "confidence": 0.86,
         "priority": "紧急", "status": "待执行", "window": f"{BASE_DATE + timedelta(days=3)}",
         "spare_suggested": "SP-CV-TUYERE", "est_downtime_hours": 6.0},
        {"plan_no": "MP202607002", "equipment_code": "EQ-RM-3", "type": "预测性维护",
         "desc": "轧辊磨削建议（振动劣化趋势明显）", "confidence": 0.92,
         "priority": "高", "status": "待执行", "window": f"{BASE_DATE + timedelta(days=5)}",
         "spare_suggested": "SP-RM-ROLL", "est_downtime_hours": 14.0},
        {"plan_no": "MP202607003", "equipment_code": "EQ-BF-1", "type": "状态检测",
         "desc": "冷却壁检测（温度场局部偏高）", "confidence": 0.71,
         "priority": "中", "status": "待执行", "window": f"{BASE_DATE + timedelta(days=10)}",
         "spare_suggested": "SP-BF-COOLING", "est_downtime_hours": 32.0},
        {"plan_no": "MP202606004", "equipment_code": "EQ-FAN-1", "type": "预测性维护",
         "desc": "轴承更换（振动接近二次预警）", "confidence": 0.78,
         "priority": "高", "status": "已执行", "window": f"{BASE_DATE - timedelta(days=2)}",
         "spare_suggested": "SP-FAN-BEARING", "est_downtime_hours": 4.0},
        {"plan_no": "MP202606005", "equipment_code": "EQ-LF-1", "type": "定期维护",
         "desc": "电极定期更换", "confidence": 0.95,
         "priority": "低", "status": "已执行", "window": f"{BASE_DATE - timedelta(days=5)}",
         "spare_suggested": "SP-LF-ELECTRODE", "est_downtime_hours": 2.0},
    ]

    # 健康分快照（0-100，越低越需关注）
    health_scores = {
        "EQ-BF-1": {"score": 62, "trend": "下降", "risk_level": "中", "updated_at": f"{BASE_DATE}T08:00:00"},
        "EQ-BF-2": {"score": 78, "trend": "平稳", "risk_level": "低", "updated_at": f"{BASE_DATE}T08:00:00"},
        "EQ-CV-1": {"score": 81, "trend": "平稳", "risk_level": "低", "updated_at": f"{BASE_DATE}T08:00:00"},
        "EQ-CV-2": {"score": 38, "trend": "下降", "risk_level": "高", "updated_at": f"{BASE_DATE}T08:00:00"},
        "EQ-CCM-1": {"score": 70, "trend": "平稳", "risk_level": "中", "updated_at": f"{BASE_DATE}T08:00:00"},
        "EQ-LF-1": {"score": 85, "trend": "平稳", "risk_level": "低", "updated_at": f"{BASE_DATE}T08:00:00"},
        "EQ-RH-1": {"score": 88, "trend": "平稳", "risk_level": "低", "updated_at": f"{BASE_DATE}T08:00:00"},
        "EQ-RM-1": {"score": 74, "trend": "平稳", "risk_level": "低", "updated_at": f"{BASE_DATE}T08:00:00"},
        "EQ-RM-3": {"score": 45, "trend": "下降", "risk_level": "高", "updated_at": f"{BASE_DATE}T08:00:00"},
        "EQ-AC-1": {"score": 80, "trend": "平稳", "risk_level": "低", "updated_at": f"{BASE_DATE}T08:00:00"},
        "EQ-FAN-1": {"score": 58, "trend": "下降", "risk_level": "中", "updated_at": f"{BASE_DATE}T08:00:00"},
    }

    return EqmData(
        equipment=equipment, equip_by_code=equip_by_code,
        spare_parts=spare_parts, spare_by_code=spare_by_code,
        sensor_readings=sensor_readings, fault_history=fault_history,
        maintenance_plans=maintenance_plans, health_scores=health_scores,
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[EqmData]({
    "agilesteel": _build_agilesteel,
})


def load(tenant: str) -> EqmData:
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量 ───────────────────────────────────────────────────


def predict_failure(tenant: str, code: str) -> dict:
    """设备故障概率预测（按健康分+近期传感器趋势确定性派生）。"""
    d = load(tenant)
    eq = d.equip_by_code.get(code)
    if eq is None:
        return {}
    hs = d.health_scores.get(code, {"score": 80, "trend": "平稳", "risk_level": "低"})
    score = hs["score"]
    # 健康分越低，故障概率越高
    fault_prob = round(max(0.0, min(0.99, (100 - score) / 100.0)), 3)
    recent = [r for r in d.sensor_readings if r["equipment_code"] == code][-3:]
    avg_vib = sum(r["vibration_mm_s"] for r in recent) / max(1, len(recent))
    avg_temp = sum(r["temperature_c"] for r in recent) / max(1, len(recent))
    plan = next((p for p in d.maintenance_plans
                 if p["equipment_code"] == code and p["status"] == "待执行"), None)
    spares = [s for s in d.spare_parts if code in (s["fit_equipment"] or "")]
    return {
        "equipment_code": code,
        "name": eq["name"],
        "type": eq["type"],
        "health_score": score,
        "risk_level": hs["risk_level"],
        "trend": hs["trend"],
        "fault_probability_7d": fault_prob,
        "recent_avg_vibration_mm_s": round(avg_vib, 3) if recent else None,
        "recent_avg_temperature_c": round(avg_temp, 2) if recent else None,
        "maintenance_plan": plan,
        "candidate_spares": [{"code": s["code"], "name": s["name"],
                               "stock_qty": s["stock_qty"],
                               "below_safety": s["stock_qty"] < s["safety_stock"]}
                              for s in spares],
        "recommendation": ("立即安排预测性维护" if fault_prob >= 0.6
                           else "纳入下周维护窗口" if fault_prob >= 0.3
                           else "维持状态监测"),
    }


def score_maintenance_priority(tenant: str) -> list[dict]:
    """多设备待维护项打分排序（风险×产能影响×备件现货），返回优先级队列。"""
    d = load(tenant)
    crit_weight = {"A": 1.0, "B": 0.7, "C": 0.4}
    rows: list[dict] = []
    for eq in d.equipment:
        hs = d.health_scores.get(eq["code"], {"score": 80, "risk_level": "低"})
        if hs["risk_level"] in ("高", "中") or eq["status"] in ("fault", "maintenance"):
            plan = next((p for p in d.maintenance_plans
                         if p["equipment_code"] == eq["code"] and p["status"] == "待执行"), None)
            spares = [s for s in d.spare_parts if eq["code"] in (s["fit_equipment"] or "")]
            in_stock = any(s["stock_qty"] >= s["safety_stock"] for s in spares)
            risk = (100 - hs["score"]) / 100.0
            crit = crit_weight.get(eq["criticality"], 0.4)
            spare_score = 1.0 if in_stock else 0.4
            priority_score = round(risk * crit * 100 + spare_score * 20, 2)
            rows.append({
                "equipment_code": eq["code"], "name": eq["name"], "type": eq["type"],
                "health_score": hs["score"], "risk_level": hs["risk_level"],
                "criticality": eq["criticality"], "status": eq["status"],
                "priority_score": priority_score,
                "maintenance_plan_no": plan["plan_no"] if plan else None,
                "spare_in_stock": in_stock,
            })
    rows.sort(key=lambda r: r["priority_score"], reverse=True)
    return rows
