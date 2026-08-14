"""PCM 多租户确定性种子数据——starhma（星途热熔胶，工艺与设备管理）。

PCM 是叶系统（其他 mock 不反向引用 PCM），无循环依赖，沿用懒构建保持一致。
``starhma`` 一份 ``PcmData``，覆盖工艺参数 / 设备运行数据 / 排产建议 / 故障预测，
支撑「智能排产 + 工艺参数优化 + 设备预测性维护」三类场景。

码空间约定（no-guessing，详见 seed ontology ``identifiers.md``）：
  - 工艺参数 ``PP-``（PP-STIR- 搅拌 / PP-REACT- 反应 / PP-COOL- 冷却）；
    工艺参数 ``formula_no`` 与 FRM 配方 ``FORM-`` 关联；``product_code`` 与
    ERP 成品胶 ``M-FG-`` 关联。
  - 设备 ``EQ-``（EQ-RX- 反应釜 / EQ-MTR- 电机 / EQ-GRN- 造粒机）；
    设备 ``line_no`` 与 MES 产线 ``LINE-`` 关联（跨系统，按 line_no 关联）。
  - 排产建议 ``PSCH-``（由 ``optimizeProductionSchedule`` 派生），
    ``work_order_no`` 引用 MES 工单 ``WO``。
  - 故障预测 ``PM-``（由 ``predictEquipmentFault`` 派生）。
``P-`` 单独出现为 HRM 岗位，与设备 ``EQ-`` 不同码空间，按 prefix 区分勿互传。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry, TenantBuilding

BASE_DATE: date = date(2026, 7, 25)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class PcmData:
    process_params: list[dict]                 # 工艺参数（搅拌/反应/冷却）
    process_param_by_code: dict[str, dict]
    equipment: list[dict]                       # 设备运行数据（反应釜/电机/造粒机）
    equip_by_code: dict[str, dict]
    equipment_run_data: list[dict]             # 设备运行时序数据
    schedule_rules: list[dict]                 # 排产规则（换线成本/产线负荷）


# ───────────────────────── 跨系统取数（同 tenant） ─────────────────────────


def _mes_work_orders(tenant: str) -> list[dict]:
    """跨系统取同 tenant 的 MES 工单；MES 未就绪或循环构造中时回退占位。"""
    try:
        from mock.systems.mes.data import load as _load_mes
        d = _load_mes(tenant)
        out: list[dict] = []
        for w in d.work_orders:
            due = w.get("planned_end") or w.get("due_date") or ""
            out.append({
                "work_order_no": w["work_order_no"], "line": w.get("line"),
                "product_code": w.get("product_code"),
                "qty": w.get("plan_qty", w.get("qty", 0)),
                "status": w.get("status"),
                "due_date": str(due)[:10] or None,
            })
        return out
    except (Exception, TenantBuilding):  # noqa: BLE001
        return []


def _mes_lines(tenant: str) -> list[str]:
    try:
        from mock.systems.mes.data import load as _load_mes
        d = _load_mes(tenant)
        return [l["code"] for l in d.lines]
    except (Exception, TenantBuilding):  # noqa: BLE001
        return ["LINE-AUTO-01", "LINE-AUTO-02"]


# ───────────────────────── starhma（星途热熔胶） ─────────────────────────


def _build_starhma() -> PcmData:
    """星途热熔胶工艺与设备口径：13 条产线（2 全自动）的工艺参数 + 反应釜/电机/造粒机
    运行数据 + 排产规则。工艺参数按配方 FORM- 组织，设备按产线 LINE- 组织。"""
    R = D.rng(20260725)

    # 工艺参数（搅拌/反应/冷却，按配方；product_code 关联 ERP 成品胶 M-FG-）
    process_params = [
        {"pp_no": "PP-STIR-001", "formula_no": "FORM-STD-001", "product_code": "M-FG-001",
         "stage": "搅拌", "param": "搅拌温度", "value": 160, "unit": "℃",
         "lower": 155, "upper": 165, "recommendation": "投料后阶梯升温至 160℃ 保温 20min"},
        {"pp_no": "PP-REACT-001", "formula_no": "FORM-STD-001", "product_code": "M-FG-001",
         "stage": "反应", "param": "反应时长", "value": 90, "unit": "min",
         "lower": 85, "upper": 95, "recommendation": "N2 保护下 90min 充分反应"},
        {"pp_no": "PP-COOL-001", "formula_no": "FORM-STD-001", "product_code": "M-FG-001",
         "stage": "冷却", "param": "出料温度", "value": 130, "unit": "℃",
         "lower": 120, "upper": 140, "recommendation": "降温至 130℃ 经造粒机出料"},
        {"pp_no": "PP-STIR-002", "formula_no": "FORM-STD-002", "product_code": "M-FG-002",
         "stage": "搅拌", "param": "搅拌温度", "value": 170, "unit": "℃",
         "lower": 165, "upper": 175, "recommendation": "高熔点配方升温至 170℃"},
        {"pp_no": "PP-REACT-002", "formula_no": "FORM-STD-002", "product_code": "M-FG-002",
         "stage": "反应", "param": "反应时长", "value": 100, "unit": "min",
         "lower": 95, "upper": 105, "recommendation": "压敏胶需充分反应 100min"},
        {"pp_no": "PP-COOL-002", "formula_no": "FORM-STD-002", "product_code": "M-FG-002",
         "stage": "冷却", "param": "出料温度", "value": 135, "unit": "℃",
         "lower": 125, "upper": 145, "recommendation": "造粒出料前降温至 135℃"},
        {"pp_no": "PP-STIR-003", "formula_no": "FORM-STD-003", "product_code": "M-FG-003",
         "stage": "搅拌", "param": "搅拌温度", "value": 150, "unit": "℃",
         "lower": 145, "upper": 155, "recommendation": "食品级低温配方控温 150℃"},
        {"pp_no": "PP-REACT-003", "formula_no": "FORM-STD-003", "product_code": "M-FG-003",
         "stage": "反应", "param": "反应时长", "value": 80, "unit": "min",
         "lower": 75, "upper": 85, "recommendation": "控温反应 80min 防降解"},
        {"pp_no": "PP-STIR-004", "formula_no": "FORM-CUS-002", "product_code": None,
         "stage": "搅拌", "param": "搅拌温度", "value": 130, "unit": "℃",
         "lower": 125, "upper": 135, "recommendation": "医用低温胶控温 130℃ 防变色"},
        {"pp_no": "PP-COOL-003", "formula_no": "FORM-CUS-002", "product_code": None,
         "stage": "冷却", "param": "出料温度", "value": 100, "unit": "℃",
         "lower": 90, "upper": 110, "recommendation": "低温出料 100℃ 保证流动性"},
    ]
    process_param_by_code = {p["pp_no"]: p for p in process_params}

    # 设备（反应釜/电机/造粒机，按产线组织；line 关联 MES LINE-）
    equipment = [
        {"eq_no": "EQ-RX-01", "name": "1# 反应釜", "type": "反应釜", "line": "LINE-AUTO-01",
         "capacity_kg": 3000, "status": "运行", "run_hours": 4860,
         "last_maintain": f"{BASE_DATE - timedelta(days=42)}",
         "health_score": 82, "vibration_mm_s": 2.1, "temp_c": 162, "current_a": 180},
        {"eq_no": "EQ-RX-02", "name": "2# 反应釜", "type": "反应釜", "line": "LINE-AUTO-02",
         "capacity_kg": 3000, "status": "运行", "run_hours": 5210,
         "last_maintain": f"{BASE_DATE - timedelta(days=88)}",
         "health_score": 61, "vibration_mm_s": 4.6, "temp_c": 168, "current_a": 195},
        {"eq_no": "EQ-RX-03", "name": "3# 反应釜", "type": "反应釜", "line": "LINE-03",
         "capacity_kg": 2000, "status": "运行", "run_hours": 3120,
         "last_maintain": f"{BASE_DATE - timedelta(days=20)}",
         "health_score": 88, "vibration_mm_s": 1.8, "temp_c": 158, "current_a": 150},
        {"eq_no": "EQ-MTR-01", "name": "1# 搅拌电机", "type": "电机", "line": "LINE-AUTO-01",
         "capacity_kg": None, "status": "运行", "run_hours": 4860,
         "last_maintain": f"{BASE_DATE - timedelta(days=42)}",
         "health_score": 79, "vibration_mm_s": 2.4, "temp_c": 68, "current_a": 42},
        {"eq_no": "EQ-MTR-02", "name": "2# 搅拌电机", "type": "电机", "line": "LINE-AUTO-02",
         "capacity_kg": None, "status": "预警", "run_hours": 5210,
         "last_maintain": f"{BASE_DATE - timedelta(days=95)}",
         "health_score": 54, "vibration_mm_s": 5.2, "temp_c": 82, "current_a": 49},
        {"eq_no": "EQ-GRN-01", "name": "1# 造粒机", "type": "造粒机", "line": "LINE-AUTO-01",
         "capacity_kg": 800, "status": "运行", "run_hours": 4400,
         "last_maintain": f"{BASE_DATE - timedelta(days=30)}",
         "health_score": 85, "vibration_mm_s": 1.9, "temp_c": 95, "current_a": 88},
        {"eq_no": "EQ-GRN-02", "name": "2# 造粒机", "type": "造粒机", "line": "LINE-AUTO-02",
         "capacity_kg": 800, "status": "运行", "run_hours": 4700,
         "last_maintain": f"{BASE_DATE - timedelta(days=58)}",
         "health_score": 72, "vibration_mm_s": 3.1, "temp_c": 98, "current_a": 92},
    ]
    equip_by_code = {e["eq_no"]: e for e in equipment}

    # 设备运行时序数据（近 7 天采样，确定性派生）
    equipment_run_data: list[dict] = []
    for e in equipment:
        for day_off in range(7):
            equipment_run_data.append({
                "eq_no": e["eq_no"], "line": e["line"],
                "at": f"{BASE_DATE - timedelta(days=day_off)}T14:00:00",
                "vibration_mm_s": round(e["vibration_mm_s"] + D.randint(R, -3, 5) * 0.1, 2),
                "temp_c": e["temp_c"] + D.randint(R, -2, 3),
                "current_a": e["current_a"] + D.randint(R, -3, 4),
                "health_score": max(20, e["health_score"] + D.randint(R, -3, 1)),
            })

    # 排产规则
    schedule_rules = [
        {"rule_no": "SR-001", "line": "LINE-AUTO-01", "type": "全自动",
         "changeover_cost_min": 45, "daily_capacity_t": 8.0, "preferred_formulas": ["FORM-STD-001", "FORM-STD-002"]},
        {"rule_no": "SR-002", "line": "LINE-AUTO-02", "type": "全自动",
         "changeover_cost_min": 45, "daily_capacity_t": 8.0, "preferred_formulas": ["FORM-STD-003", "FORM-CUS-002"]},
        {"rule_no": "SR-003", "line": "LINE-03", "type": "半自动",
         "changeover_cost_min": 90, "daily_capacity_t": 4.5, "preferred_formulas": ["FORM-CUS-001", "FORM-CUS-003"]},
    ]

    return PcmData(
        process_params=process_params, process_param_by_code=process_param_by_code,
        equipment=equipment, equip_by_code=equip_by_code,
        equipment_run_data=equipment_run_data, schedule_rules=schedule_rules,
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[PcmData]({
    "starhma": _build_starhma,
})


def load(tenant: str) -> PcmData:
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量 ───────────────────────────────────────────────────


def recommend_process_params(tenant: str, *, formula_no: str | None = None,
                              product_code: str | None = None) -> dict:
    """工艺参数智能推荐：按配方/产品给出最优工艺区间（搅拌/反应/冷却）。"""
    d = load(tenant)
    rows = d.process_params
    if formula_no:
        rows = [p for p in rows if p["formula_no"] == formula_no]
    elif product_code:
        rows = [p for p in rows if p["product_code"] == product_code]
    if not rows:
        return {}
    by_stage: dict[str, list[dict]] = {}
    for p in rows:
        by_stage.setdefault(p["stage"], []).append(p)
    return {
        "formula_no": formula_no, "product_code": product_code,
        "stages": [
            {"stage": st, "params": [
                {"pp_no": p["pp_no"], "param": p["param"], "value": p["value"],
                 "unit": p["unit"], "lower": p["lower"], "upper": p["upper"],
                 "recommendation": p["recommendation"]}
                for p in ps
            ]}
            for st, ps in by_stage.items()
        ],
        "note": "工艺区间按配方历史数据沉淀，稳定产品一致性",
    }


def predict_equipment_fault(tenant: str, eq_no: str) -> dict:
    """设备故障预测：基于振动/温度/电流/健康分预判故障，提前保养提醒。"""
    d = load(tenant)
    e = d.equip_by_code.get(eq_no)
    if e is None:
        return {}
    vib = e["vibration_mm_s"]; temp = e["temp_c"]; hs = e["health_score"]
    days_since = (BASE_DATE - _parse_date(e["last_maintain"])).days
    risk_flags = []
    if vib >= 4.5:
        risk_flags.append("振动超标（≥4.5mm/s，疑轴承磨损/不平衡）")
    if temp >= e.get("temp_c", 0) and e["type"] == "电机" and temp >= 75:
        risk_flags.append("电机温升偏高（≥75℃，疑散热/负载异常）")
    if days_since >= 90:
        risk_flags.append(f"距上次保养 {days_since} 天（≥90d，超周期）")
    if hs < 65:
        risk_flags.append(f"健康分 {hs}（<65，综合状态下滑）")
    risk_level = "高" if (vib >= 5.0 or hs < 55) else ("中" if risk_flags else "低")
    remaining = max(0, 14 if risk_level == "高" else (45 if risk_level == "中" else 120))
    return {
        "eq_no": eq_no, "name": e["name"], "type": e["type"], "line": e["line"],
        "status": e["status"], "run_hours": e["run_hours"],
        "last_maintain": e["last_maintain"], "days_since_maintain": days_since,
        "metrics": {"vibration_mm_s": vib, "temp_c": temp, "current_a": e["current_a"],
                    "health_score": hs},
        "risk_level": risk_level, "risk_flags": risk_flags,
        "remaining_hours_est": e["run_hours"] + remaining * 24,
        "suggested_action": (
            "立即停机检修（振动/温升/健康分多指标告警）" if risk_level == "高"
            else f"7 日内安排预防性保养（{'; '.join(risk_flags) or '周期临近'}）" if risk_level == "中"
            else "按计划周期保养，状态正常"
        ),
    }


def optimize_production_schedule(tenant: str, *, line_no: str | None = None,
                                  horizon_days: int = 7) -> dict:
    """智能排产：综合 MES 工单交期/产线负荷/换线成本，给出排产建议 + 冲突订单识别。"""
    d = load(tenant)
    work_orders = _mes_work_orders(tenant)
    rules = d.schedule_rules
    if line_no:
        rules = [r for r in rules if r["line"] == line_no] or rules
    # 按交期排序，同配方聚合减少换线（MES 工单 qty 单位 kg，产线产能 t → 统一换算 kg）；
    # 每个工单只分配到一条产线，优先排到首选配方匹配的产线，满载后剩余进冲突清单。
    remaining = list(work_orders)
    plan: list[dict] = []
    conflict: list[dict] = []
    seq = 1
    for r in rules:
        cap_kg = float(r["daily_capacity_t"]) * 1000  # t/day → kg/day
        cap_total_kg = cap_kg * horizon_days
        used = 0.0
        preferred = set(r.get("preferred_formulas") or [])
        # 先排首选配方工单，再排其余
        def _rank(w):
            return 0 if w.get("product_code") in preferred else 1
        for w in sorted(remaining, key=_rank):
            if w.get("_placed"):
                continue
            qty = float(w.get("qty") or 0)
            if used + qty > cap_total_kg:
                continue
            used += qty
            plan.append({
                "seq": seq, "line": r["line"], "work_order_no": w["work_order_no"],
                "product_code": w.get("product_code"), "qty": qty,
                "due_date": w.get("due_date"), "status": w.get("status"),
            })
            seq += 1
            w["_placed"] = True
        if used >= cap_total_kg:
            break
    # 剩余未排产工单进冲突清单
    for w in remaining:
        if w.get("_placed"):
            continue
        conflict.append({
            "work_order_no": w["work_order_no"], "line": None,
            "reason": f"工单 {w['work_order_no']} ({w.get('product_code')}) "
                      f"{float(w.get('qty') or 0)/1000}t 在 {horizon_days}d 内无产线可承接，"
                      "需调配其它产线、外协或调整交期",
        })
    return {
        "line_no": line_no, "horizon_days": horizon_days,
        "lines": [
            {"line": r["line"], "type": r["type"],
             "daily_capacity_t": r["daily_capacity_t"],
             "changeover_cost_min": r["changeover_cost_min"],
             "preferred_formulas": r["preferred_formulas"],
             "allocated_t": round(sum(p["qty"] for p in plan if p["line"] == r["line"]) / 1000, 1),
             "utilization_pct": round(
                 min(100, sum(p["qty"] for p in plan if p["line"] == r["line"])
                     / (float(r["daily_capacity_t"]) * 1000 * horizon_days) * 100), 1)}
            for r in rules
        ],
        "plan": plan,
        "conflict_orders": conflict,
        "note": "综合 MES 工单交期/产线负荷/换线成本；冲突订单需人工裁决或调配",
    }


def get_equipment_run_data(tenant: str, eq_no: str) -> list[dict]:
    """设备运行时序数据（近 7 天采样）。"""
    d = load(tenant)
    return [r for r in d.equipment_run_data if r["eq_no"] == eq_no]


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:  # noqa: BLE001
        return BASE_DATE
