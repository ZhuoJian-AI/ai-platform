"""EMS 多租户确定性种子数据——agilesteel（敏睿钢铁，能源环保）。

EMS 是叶系统，无循环依赖，沿用懒构建。``agilesteel`` 一份 ``EmsData``，覆盖
能源介质计量点（煤气/蒸汽/电力/氧气/氮气/水）+ 介质供需平衡（分工序）+ 排放监测
（SO2/NOx/颗粒物/CO2）+ 工序能耗标杆 + 调度方案 + 预警。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry

BASE_DATE: date = date(2026, 6, 29)


@dataclass
class EmsData:
    meters: list[dict]                          # 能源介质计量点
    meter_by_code: dict[str, dict]
    media_balance: list[dict]                  # 介质供需平衡（分工序）
    emissions: list[dict]                      # 排放监测（按排放源）
    emission_by_code: dict[str, dict]
    energy_consumption: list[dict]            # 工序能耗标杆（kgce/t）
    dispatch_plans: list[dict]                 # 调度方案
    alarms: list[dict]                          # 能源/排放预警


# ───────────────────────── agilesteel（敏睿钢铁） ─────────────────────────


def _build_agilesteel() -> EmsData:
    """敏睿钢铁能源环保口径：6 类介质计量点 + 工序平衡 + 排放 + 能耗标杆 + 调度 + 预警。"""
    R = D.rng(20260616)

    meters = [
        {"code": "EM-GAS-BF1", "name": "1#高炉煤气流量计", "media": "高炉煤气",
         "process": "炼铁", "unit": "m³/h", "capacity": 450000, "status": "online"},
        {"code": "EM-GAS-CV1", "name": "1#转炉煤气流量计", "media": "转炉煤气",
         "process": "炼钢", "unit": "m³/h", "capacity": 80000, "status": "online"},
        {"code": "EM-GAS-COKE", "name": "焦炉煤气流量计", "media": "焦炉煤气",
         "process": "焦化", "unit": "m³/h", "capacity": 60000, "status": "online"},
        {"code": "EM-STM-LF1", "name": "1#精炼蒸汽流量计", "media": "蒸汽",
         "process": "炼钢", "unit": "t/h", "capacity": 35, "status": "online"},
        {"code": "EM-STM-BOLER", "name": "余热锅炉蒸汽流量计", "media": "蒸汽",
         "process": "公辅", "unit": "t/h", "capacity": 120, "status": "online"},
        {"code": "EM-PWR-MAIN", "name": "总降电力关口表", "media": "电力",
         "process": "全厂", "unit": "kWh", "capacity": 220000, "status": "online"},
        {"code": "EM-O2-CV1", "name": "1#转炉氧气流量计", "media": "氧气",
         "process": "炼钢", "unit": "m³/h", "capacity": 15000, "status": "online"},
        {"code": "EM-N2-BF1", "name": "1#高炉氮气流量计", "media": "氮气",
         "process": "炼铁", "unit": "m³/h", "capacity": 8000, "status": "online"},
        {"code": "EM-H2O-RM1", "name": "1#轧材工业水流量计", "media": "工业水",
         "process": "轧钢", "unit": "m³/h", "capacity": 2200, "status": "online"},
        {"code": "EM-PWR-RM1", "name": "轧材电力关口表", "media": "电力",
         "process": "轧钢", "unit": "kWh", "capacity": 48000, "status": "online"},
    ]
    meter_by_code = {m["code"]: m for m in meters}

    # 介质供需平衡：5 工序 × 6 介质
    processes = ["焦化", "烧结", "炼铁", "炼钢", "轧材"]
    media_list = ["高炉煤气", "转炉煤气", "焦炉煤气", "蒸汽", "电力", "氧气"]
    # 简化：每工序每介质一条供需记录
    balance_templates = {
        ("炼铁", "高炉煤气"): (450000, 380000, "自产+外供"),
        ("炼钢", "转炉煤气"): (80000, 60000, "回收至储气柜"),
        ("焦化", "焦炉煤气"): (60000, 55000, "自用+外供"),
        ("轧材", "蒸汽"): (120, 135, "缺口 15t/h 需补网"),
        ("炼钢", "蒸汽"): (35, 40, "缺口 5t/h"),
        ("轧材", "电力"): (48000, 46000, "基本平衡"),
    }
    media_balance: list[dict] = []
    for proc in processes:
        for media in media_list:
            supply, demand, note = balance_templates.get((proc, media),
                                                          (D.randint(R, 1000, 9000),
                                                           D.randint(R, 1000, 9000),
                                                           "动态平衡"))
            gap = supply - demand
            media_balance.append({
                "process": proc, "media": media,
                "supply": supply, "demand": demand,
                "gap": gap, "gap_pct": round(gap / demand * 100, 2) if demand else 0.0,
                "note": note, "date": BASE_DATE.isoformat(),
            })

    emissions = [
        {"code": "EMS-SO2-SINTER", "source": "烧结机头", "pollutant": "SO2",
         "process": "烧结", "value": 180.0, "limit": 200.0, "unit": "mg/m³",
         "status": "达标", "measured_at": f"{BASE_DATE}T08:00:00"},
        {"code": "EMS-NOX-CV", "source": "转炉烟气", "pollutant": "NOx",
         "process": "炼钢", "value": 240.0, "limit": 300.0, "unit": "mg/m³",
         "status": "达标", "measured_at": f"{BASE_DATE}T08:00:00"},
        {"code": "EMS-PM-RM", "source": "轧材除尘", "pollutant": "颗粒物",
         "process": "轧钢", "value": 28.0, "limit": 30.0, "unit": "mg/m³",
         "status": "临界", "measured_at": f"{BASE_DATE}T08:00:00"},
        {"code": "EMS-PM-SINTER", "source": "烧结机头", "pollutant": "颗粒物",
         "process": "烧结", "value": 35.0, "limit": 40.0, "unit": "mg/m³",
         "status": "达标", "measured_at": f"{BASE_DATE}T08:00:00"},
        {"code": "EMS-CO2-PLANT", "source": "厂区碳排放", "pollutant": "CO2",
         "process": "全厂", "value": 1.78, "limit": 1.85, "unit": "t CO2 / t 钢",
         "status": "达标", "measured_at": f"{BASE_DATE}T08:00:00"},
        {"code": "EMS-SO2-COKE", "source": "焦炉烟气", "pollutant": "SO2",
         "process": "焦化", "value": 95.0, "limit": 100.0, "unit": "mg/m³",
         "status": "临界", "measured_at": f"{BASE_DATE}T08:00:00"},
    ]
    emission_by_code = {e["code"]: e for e in emissions}

    energy_consumption = [
        {"process": "焦化", "benchmark_kgce_per_t": 105.0, "actual_kgce_per_t": 108.5,
         "steel_grade": "通用", "date": BASE_DATE.isoformat()},
        {"process": "烧结", "benchmark_kgce_per_t": 48.0, "actual_kgce_per_t": 55.2,
         "steel_grade": "通用", "date": BASE_DATE.isoformat()},
        {"process": "炼铁", "benchmark_kgce_per_t": 385.0, "actual_kgce_per_t": 420.0,
         "steel_grade": "通用", "date": BASE_DATE.isoformat()},
        {"process": "炼钢", "benchmark_kgce_per_t": -10.0, "actual_kgce_per_t": -8.0,
         "steel_grade": "通用（转炉煤气回收抵扣）", "date": BASE_DATE.isoformat()},
        {"process": "轧材", "benchmark_kgce_per_t": 58.0, "actual_kgce_per_t": 65.0,
         "steel_grade": "P-ST-Q345B", "date": BASE_DATE.isoformat()},
        {"process": "轧材", "benchmark_kgce_per_t": 62.0, "actual_kgce_per_t": 70.5,
         "steel_grade": "P-ST-45#", "date": BASE_DATE.isoformat()},
    ]

    dispatch_plans = [
        {"plan_no": "EDP202607001", "title": "转炉煤气回收至储气柜",
         "media": "转炉煤气", "status": "执行中",
         "desc": "1#转炉吨钢回收量 85m³/t，回收至 8 万 m³ 储气柜供轧材加热炉",
         "expected_save_kgce": 2.6, "created_at": f"{BASE_DATE - timedelta(days=2)}T08:00:00"},
        {"plan_no": "EDP202607002", "title": "余热蒸汽并网自备电厂",
         "media": "蒸汽", "status": "待执行",
         "desc": "余热锅炉 120t/h 蒸汽并网，补轧材缺口 15t/h，减少外购蒸汽",
         "expected_save_kgce": 1.4, "created_at": f"{BASE_DATE - timedelta(days=1)}T08:00:00"},
        {"plan_no": "EDP202607003", "title": "烧结电除尘提效",
         "media": "电力", "status": "待执行",
         "desc": "烧结机头电除尘参数优化，颗粒物排放降至 30mg/m³ 以下",
         "expected_save_kgce": 0.3, "created_at": f"{BASE_DATE}T08:00:00"},
    ]

    alarms = [
        {"alarm_no": "EA20260701A", "level": "中", "type": "介质",
         "media": "高炉煤气", "meter_code": "EM-GAS-BF1",
         "desc": "1#高炉煤气压力低于 8kPa，接近放散阈值", "raised_at": f"{BASE_DATE}T06:20:00",
         "status": "未处置", "suggested": "提产储气柜回收，降低放散"},
        {"alarm_no": "EA20260702B", "level": "高", "type": "排放",
         "media": "SO2", "meter_code": "EMS-SO2-SINTER",
         "desc": "烧结机头 SO2 升至 180mg/m³，接近 200 限值", "raised_at": f"{BASE_DATE}T07:10:00",
         "status": "未处置", "suggested": "提高脱硫循环泵出力，预警 1-2h 前调整"},
        {"alarm_no": "EA20260630C", "level": "中", "type": "排放",
         "media": "颗粒物", "meter_code": "EMS-PM-RM",
         "desc": "轧材除尘颗粒物 28mg/m³ 临界 30 限值", "raised_at": f"{BASE_DATE - timedelta(days=1)}T15:40:00",
         "status": "已处置", "suggested": "清灰+提压"},
    ]

    return EmsData(
        meters=meters, meter_by_code=meter_by_code,
        media_balance=media_balance, emissions=emissions,
        emission_by_code=emission_by_code, energy_consumption=energy_consumption,
        dispatch_plans=dispatch_plans, alarms=alarms,
    )


TENANTS = LazyTenantRegistry[EmsData]({
    "agilesteel": _build_agilesteel,
})


def load(tenant: str) -> EmsData:
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量 ───────────────────────────────────────────────────


def predict_media_shortfall(tenant: str, shift: str = "早班") -> dict:
    """预测指定班次介质缺口 + 调度建议（按平衡表缺口确定性派生）。"""
    d = load(tenant)
    shortfalls = [b for b in d.media_balance if b["gap"] < 0]
    plans = {p["media"]: p for p in d.dispatch_plans if p["status"] in ("待执行", "执行中")}
    items = []
    for b in shortfalls:
        plan = plans.get(b["media"])
        items.append({
            "process": b["process"], "media": b["media"],
            "supply": b["supply"], "demand": b["demand"],
            "gap": b["gap"], "gap_pct": b["gap_pct"],
            "note": b["note"],
            "dispatch_plan_no": plan["plan_no"] if plan else None,
            "dispatch_desc": plan["desc"] if plan else None,
            "expected_save_kgce": plan["expected_save_kgce"] if plan else None,
        })
    total_gap = sum(i["gap"] for i in items)
    return {
        "shift": shift, "date": BASE_DATE.isoformat(),
        "shortfall_count": len(items),
        "total_gap": total_gap,
        "items": items,
        "recommendation": ("立即启动余热蒸汽并网+回收转炉煤气" if total_gap < -20
                           else "动态调度储气柜回收平衡" if total_gap < 0
                           else "介质基本平衡，维持现状"),
    }


def score_emission_risk(tenant: str) -> list[dict]:
    """排放源超标风险打分 + 整改优先级（按值/限值比确定性派生）。"""
    d = load(tenant)
    rows = []
    for e in d.emissions:
        ratio = e["value"] / e["limit"] if e["limit"] else 0
        risk_score = round(ratio * 100, 2)
        risk_level = ("高" if ratio >= 0.95 else "中" if ratio >= 0.85 else "低")
        rows.append({
            "code": e["code"], "source": e["source"], "pollutant": e["pollutant"],
            "process": e["process"], "value": e["value"], "limit": e["limit"],
            "unit": e["unit"], "ratio_pct": risk_score, "risk_level": risk_level,
            "status": e["status"],
            "remediation_priority": "P0-立即" if risk_level == "高"
            else "P1-本周" if risk_level == "中" else "P2-持续监控",
        })
    rows.sort(key=lambda r: r["ratio_pct"], reverse=True)
    return rows
