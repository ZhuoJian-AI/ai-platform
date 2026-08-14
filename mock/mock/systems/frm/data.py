"""FRM 多租户确定性种子数据——starhma（星途热熔胶，配方研发）。

FRM 是叶系统（其他 mock 不反向引用 FRM），无循环依赖，沿用懒构建保持一致。
``starhma`` 一份 ``FrmData``，覆盖配方 / 原料组分 / 实验 / 样品 / 测试方案，
支撑「配方智能推荐 + 实验数据分析与报告生成 + 性能预测」三类场景。

码空间约定（no-guessing，详见 seed ontology ``identifiers.md``）：
  - 配方 ``FORM-``（FORM-STD- 标准品 / FORM-CUS- 定制）；标准品配方与 ERP 成品胶
    ``M-FG-`` 按 ``product_code`` 关联；定制配方转生产时与 MES 批次 ``BAT-`` 按
    ``formula_no`` 关联。
  - 原料组分 ``ING-``（ING-RES- 树脂 / ING-TK- 增粘剂 / ING-WAX- 蜡 / ING-AO- 抗氧剂）；
    每个组分带 ``material_code`` 映射 ERP 采购物料 ``M-RES-`` / ``M-TK-`` / ``M-WAX-``
    （prefix 转换：ING-RES- → M-RES-，勿互传）。
  - 实验 ``EXP-``（EXP-RHE- 流变 / EXP-TEN- 拉力剥离 / EXP-ADH- 持粘）。
  - 性能预测 ``PERF-``（由 ``predictPerformance`` 派生）。
  - 样品 ``SMP-``；样品 ``customer_code`` 与 CRM 客户 ``CLI-`` 关联。
  - 测试方案 ``TS-``（来料/成品/客诉复测模板）。
``P-`` 单独出现为 HRM 岗位（P-RD 研发岗），与 ERP 物料 ``M-`` / FRM 组分 ``ING-``
不同码空间，按 prefix 区分勿互传。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry

BASE_DATE: date = date(2026, 7, 25)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class FrmData:
    formulas: list[dict]                      # 配方
    formula_by_code: dict[str, dict]
    ingredients: list[dict]                   # 原料组分（带 ERP material_code）
    ingredient_by_code: dict[str, dict]
    experiments: list[dict]                  # 实验（流变/拉力/持粘）
    experiment_by_code: dict[str, dict]
    samples: list[dict]                      # 样品（关联客户）
    test_schemes: list[dict]                 # 测试方案模板
    failure_records: list[dict]             # 失效实验记录（研发知识库）


# ───────────────────────── starhma（星途热熔胶） ─────────────────────────


def _build_starhma() -> FrmData:
    """星途热熔胶配方研发口径：6 款配方（3 标准品 + 3 定制）覆盖汽车内饰/医疗/食品包装/
    物流快递袋/鞋材箱包/粘扣带六大赛道 + 树脂/增粘剂/蜡/抗氧剂四类原料组分 +
    流变/拉力/持粘三类实验 + 客户样品 + 测试方案 + 失效记录。"""
    R = D.rng(20260725)

    formulas = [
        {"formula_no": "FORM-STD-001", "name": "环保型书刊装订热熔胶", "type": "标准品",
         "industry": "印刷装订", "substrate": "铜版纸/胶版纸",
         "application_temp": "160℃", "open_time_sec": 8, "peel_strength_N": 18,
         "env_std": ["REACH", "SGS"], "cost_per_kg": 18.5, "product_code": "M-FG-001",
         "status": "量产", "version": "V3.2", "owner": "P-RD-001",
         "updated_at": f"{BASE_DATE - timedelta(days=12)}"},
        {"formula_no": "FORM-STD-002", "name": "物流快递袋压敏胶", "type": "标准品",
         "industry": "物流快递袋", "substrate": "BOPP/CPE 复合膜",
         "application_temp": "170℃", "open_time_sec": 5, "peel_strength_N": 22,
         "env_std": ["REACH"], "cost_per_kg": 21.0, "product_code": "M-FG-002",
         "status": "量产", "version": "V2.6", "owner": "P-RD-002",
         "updated_at": f"{BASE_DATE - timedelta(days=8)}"},
        {"formula_no": "FORM-STD-003", "name": "食品日化包装用热熔胶", "type": "标准品",
         "industry": "食品日化包装", "substrate": "PET/铝箔",
         "application_temp": "150℃", "open_time_sec": 10, "peel_strength_N": 16,
         "env_std": ["FDA", "REACH", "SGS"], "cost_per_kg": 26.5, "product_code": "M-FG-003",
         "status": "量产", "version": "V2.1", "owner": "P-RD-003",
         "updated_at": f"{BASE_DATE - timedelta(days=20)}"},
        {"formula_no": "FORM-CUS-001", "name": "汽车内饰植绒用压敏胶（客户定制）", "type": "定制",
         "industry": "汽车内饰", "substrate": "PET 植绒布/ABS",
         "application_temp": "180℃", "open_time_sec": 12, "peel_strength_N": 28,
         "env_std": ["REACH", "SGS"], "cost_per_kg": 32.0, "product_code": None,
         "customer_code": "CLI-001", "status": "已定样", "version": "V1.4", "owner": "P-RD-001",
         "updated_at": f"{BASE_DATE - timedelta(days=3)}"},
        {"formula_no": "FORM-CUS-002", "name": "医疗用品低温热熔胶（客户定制）", "type": "定制",
         "industry": "医疗用品", "substrate": "无纺布/PE 膜",
         "application_temp": "130℃", "open_time_sec": 6, "peel_strength_N": 14,
         "env_std": ["FDA", "ISO-10993"], "cost_per_kg": 38.5, "product_code": None,
         "customer_code": "CLI-002", "status": "小试中", "version": "V0.7", "owner": "P-RD-004",
         "updated_at": f"{BASE_DATE - timedelta(days=1)}"},
        {"formula_no": "FORM-CUS-003", "name": "鞋材箱包低温贴合热熔胶（客户定制）", "type": "定制",
         "industry": "鞋材箱包", "substrate": "EVA/PU 革",
         "application_temp": "120℃", "open_time_sec": 9, "peel_strength_N": 20,
         "env_std": ["REACH"], "cost_per_kg": 23.0, "product_code": None,
         "customer_code": "CLI-003", "status": "送样中", "version": "V1.0", "owner": "P-RD-002",
         "updated_at": f"{BASE_DATE - timedelta(days=5)}"},
    ]
    formula_by_code = {f["formula_no"]: f for f in formulas}

    # 原料组分（material_code 映射 ERP 采购物料 M-RES-/M-TK-/M-WAX-/M-AO-）
    ingredients = [
        {"ing_code": "ING-RES-001", "name": "EVA 树脂 28-150", "category": "树脂",
         "material_code": "M-RES-001", "default_ratio_pct": 35.0, "uom": "kg",
         "function": "基体聚合物，提供内聚强度与熔融粘度"},
        {"ing_code": "ING-RES-002", "name": "APAO 乙烯-丙烯共聚物", "category": "树脂",
         "material_code": "M-RES-002", "default_ratio_pct": 18.0, "uom": "kg",
         "function": "改性基体，改善低温柔韧性与开放时间"},
        {"ing_code": "ING-TK-001", "name": "石油树脂 C5", "category": "增粘剂",
         "material_code": "M-TK-001", "default_ratio_pct": 30.0, "uom": "kg",
         "function": "提高初粘力与剥离强度"},
        {"ing_code": "ING-TK-002", "name": "萜烯树脂 T100", "category": "增粘剂",
         "material_code": "M-TK-002", "default_ratio_pct": 12.0, "uom": "kg",
         "function": "改善食品级与医用级兼容性、抗氧性"},
        {"ing_code": "ING-WAX-001", "name": "费托蜡 FT-100", "category": "蜡",
         "material_code": "M-WAX-001", "default_ratio_pct": 8.0, "uom": "kg",
         "function": "降低熔融粘度、调节开放时间与凝固速度"},
        {"ing_code": "ING-WAX-002", "name": "PE 微粉蜡", "category": "蜡",
         "material_code": "M-WAX-002", "default_ratio_pct": 5.0, "uom": "kg",
         "function": "提高耐高温性、防止结皮"},
        {"ing_code": "ING-AO-001", "name": "抗氧剂 BHT/1010", "category": "抗氧剂",
         "material_code": "M-AO-001", "default_ratio_pct": 0.5, "uom": "kg",
         "function": "抑制高温氧化降解、延长贮存期"},
    ]
    ingredient_by_code = {i["ing_code"]: i for i in ingredients}

    # 配方—组分配比（FORM-CUS-002 医用低温配方；其它配方用 default_ratio）
    formula_ingredients = {
        "FORM-STD-001": [
            ("ING-RES-001", 38.0), ("ING-TK-001", 33.0), ("ING-WAX-001", 8.0),
            ("ING-AO-001", 0.5), ("ING-RES-002", 20.5),
        ],
        "FORM-STD-002": [
            ("ING-RES-001", 35.0), ("ING-RES-002", 15.0), ("ING-TK-001", 30.0),
            ("ING-WAX-001", 9.0), ("ING-AO-001", 0.5), ("ING-WAX-002", 10.5),
        ],
        "FORM-STD-003": [
            ("ING-RES-001", 30.0), ("ING-TK-002", 35.0), ("ING-WAX-002", 6.0),
            ("ING-AO-001", 0.6), ("ING-RES-002", 28.4),
        ],
        "FORM-CUS-001": [
            ("ING-RES-001", 32.0), ("ING-RES-002", 20.0), ("ING-TK-001", 28.0),
            ("ING-WAX-002", 6.0), ("ING-AO-001", 0.8), ("ING-TK-002", 13.2),
        ],
        "FORM-CUS-002": [
            ("ING-RES-001", 28.0), ("ING-TK-002", 38.0), ("ING-WAX-001", 7.0),
            ("ING-AO-001", 0.8), ("ING-RES-002", 26.2),
        ],
        "FORM-CUS-003": [
            ("ING-RES-001", 34.0), ("ING-RES-002", 18.0), ("ING-TK-001", 28.0),
            ("ING-WAX-001", 9.0), ("ING-AO-001", 0.6), ("ING-WAX-002", 10.4),
        ],
    }
    for fno, ings in formula_ingredients.items():
        formula_by_code[fno]["ingredients"] = [
            {"ing_code": ic, "name": ingredient_by_code[ic]["name"],
             "category": ingredient_by_code[ic]["category"],
             "material_code": ingredient_by_code[ic]["material_code"],
             "ratio_pct": r}
            for ic, r in ings
        ]

    # 实验（流变/拉力/持粘）
    experiments = [
        {"exp_no": "EXP-RHE-001", "formula_no": "FORM-CUS-002", "test_type": "流变",
         "equipment": "旋转流变仪 DHR-20", "performed_by": "P-RD-004",
         "performed_at": f"{BASE_DATE - timedelta(days=1)}T10:20:00",
         "result": {"softening_point_c": 86, "viscosity_mpa_s_180c": 6200,
                    "open_time_sec": 6, "storage_modulus_pa": 85000},
         "anomaly_flags": [], "status": "正常",
         "report_no": "TS-MED-2026-001"},
        {"exp_no": "EXP-RHE-002", "formula_no": "FORM-CUS-001", "test_type": "流变",
         "equipment": "旋转流变仪 DHR-20", "performed_by": "P-RD-001",
         "performed_at": f"{BASE_DATE - timedelta(days=3)}T14:00:00",
         "result": {"softening_point_c": 96, "viscosity_mpa_s_180c": 8800,
                    "open_time_sec": 12, "storage_modulus_pa": 120000},
         "anomaly_flags": ["粘度偏离配方历史区间上限"], "status": "异常-待复测",
         "report_no": "TS-AUTO-2026-007"},
        {"exp_no": "EXP-TEN-001", "formula_no": "FORM-CUS-002", "test_type": "拉力剥离",
         "equipment": "万能拉力试验机 INSTRON-3367", "performed_by": "P-RD-004",
         "performed_at": f"{BASE_DATE - timedelta(days=1)}T15:10:00",
         "result": {"peel_strength_N": 14.2, "failure_mode": "内聚破坏",
                    "substrate": "无纺布/PE 膜", "temp_c": 23},
         "anomaly_flags": [], "status": "正常", "report_no": "TS-MED-2026-001"},
        {"exp_no": "EXP-ADH-001", "formula_no": "FORM-CUS-003", "test_type": "持粘",
         "equipment": "持粘性测试仪 CZY-6S", "performed_by": "P-RD-002",
         "performed_at": f"{BASE_DATE - timedelta(days=5)}T09:30:00",
         "result": {"hold_time_min": 240, "displacement_mm": 1.8,
                    "load_kg": 1.0, "temp_c": 40},
         "anomaly_flags": [], "status": "正常", "report_no": "TS-SHOE-2026-003"},
        {"exp_no": "EXP-TEN-002", "formula_no": "FORM-CUS-001", "test_type": "拉力剥离",
         "equipment": "万能拉力试验机 INSTRON-3367", "performed_by": "P-RD-001",
         "performed_at": f"{BASE_DATE - timedelta(days=3)}T16:00:00",
         "result": {"peel_strength_N": 27.8, "failure_mode": "粘附破坏",
                    "substrate": "PET 植绒布/ABS", "temp_c": 23},
         "anomaly_flags": ["剥离界面粘附破坏（应内聚破坏）"], "status": "异常-待复测",
         "report_no": "TS-AUTO-2026-007"},
        {"exp_no": "EXP-RHE-003", "formula_no": "FORM-STD-002", "test_type": "流变",
         "equipment": "旋转流变仪 DHR-20", "performed_by": "P-RD-002",
         "performed_at": f"{BASE_DATE - timedelta(days=8)}T11:00:00",
         "result": {"softening_point_c": 92, "viscosity_mpa_s_180c": 7400,
                    "open_time_sec": 5, "storage_modulus_pa": 98000},
         "anomaly_flags": [], "status": "正常", "report_no": "TS-LOG-2026-002"},
    ]
    experiment_by_code = {e["exp_no"]: e for e in experiments}

    # 样品（关联客户）
    samples = [
        {"sample_no": "SMP-2026-001", "formula_no": "FORM-CUS-001",
         "customer_code": "CLI-001", "request_no": "INQ-001",
         "status": "已寄出", "sent_at": f"{BASE_DATE - timedelta(days=3)}"},
        {"sample_no": "SMP-2026-002", "formula_no": "FORM-CUS-002",
         "customer_code": "CLI-002", "request_no": "INQ-002",
         "status": "已寄出", "sent_at": f"{BASE_DATE - timedelta(days=1)}"},
        {"sample_no": "SMP-2026-003", "formula_no": "FORM-CUS-003",
         "customer_code": "CLI-003", "request_no": "INQ-003",
         "status": "待寄出", "sent_at": None},
    ]

    # 测试方案模板
    test_schemes = [
        {"scheme_no": "TS-MED-2026-001", "name": "医疗用品低温胶测试方案",
         "items": ["流变（软化点/粘度/开放时间）", "拉力剥离（23℃/37℃）",
                   "细胞毒性 ISO-10993-5", "皮肤刺激 ISO-10993-10"]},
        {"scheme_no": "TS-AUTO-2026-007", "name": "汽车内饰植绒胶测试方案",
         "items": ["流变", "拉力剥离（高温/低温/湿热老化后）", "耐温性 85℃×240h",
                   "VOC 排放 SGS"]},
        {"scheme_no": "TS-LOG-2026-002", "name": "物流快递袋胶测试方案",
         "items": ["流变", "初粘力（球环初粘仪）", "持粘 40℃", "低温适应性 -10℃"]},
        {"scheme_no": "TS-SHOE-2026-003", "name": "鞋材低温贴合胶测试方案",
         "items": ["流变", "拉力剥离", "持粘 40℃", "耐水解 60℃×95%RH×7d"]},
    ]

    # 失效实验记录（研发知识库沉淀）
    failure_records = [
        {"fr_no": "FR-2025-014", "formula_no": "FORM-CUS-001",
         "symptom": "高温下剥离强度衰减过快", "root_cause": "APAO 比例过高导致耐温不足",
         "solution": "下调 ING-RES-002 至 18%，增加 ING-WAX-002 至 8% 提升耐高温",
         "recorded_by": "P-RD-001", "recorded_at": f"{BASE_DATE - timedelta(days=120)}"},
        {"fr_no": "FR-2025-021", "formula_no": "FORM-CUS-002",
         "symptom": "低温 -10℃ 开胶", "root_cause": "石油树脂 C5 玻璃化温度偏高",
         "solution": "改用 ING-TK-002 萜烯树脂，并提升 ING-RES-002 柔韧相比例",
         "recorded_by": "P-RD-004", "recorded_at": f"{BASE_DATE - timedelta(days=60)}"},
        {"fr_no": "FR-2026-003", "formula_no": "FORM-STD-002",
         "symptom": "客户产线堵枪", "root_cause": "蜡比例偏低、熔融粘度过高",
         "solution": "ING-WAX-001 上调至 10%，凝固速度调快",
         "recorded_by": "P-RD-002", "recorded_at": f"{BASE_DATE - timedelta(days=30)}"},
    ]

    return FrmData(
        formulas=formulas, formula_by_code=formula_by_code,
        ingredients=ingredients, ingredient_by_code=ingredient_by_code,
        experiments=experiments, experiment_by_code=experiment_by_code,
        samples=samples, test_schemes=test_schemes,
        failure_records=failure_records,
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[FrmData]({
    "starhma": _build_starhma,
})


def load(tenant: str) -> FrmData:
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量 ───────────────────────────────────────────────────


def recommend_formula(tenant: str, *, industry: str | None = None,
                      substrate: str | None = None, application_temp: str | None = None,
                      open_time_sec: int | None = None, peel_strength_N: int | None = None,
                      env_std: str | None = None, cost_upper: float | None = None) -> dict:
    """配方智能推荐：按客户行业/基材/温度/开放时间/剥离力/环保/成本上限匹配历史配方，
    返回候选 + 初始配比（组分比例）+ 预估性能（确定性派生，不杜撰分数）。"""
    d = load(tenant)
    cands = list(d.formulas)
    if industry:
        cands = [f for f in cands if industry in f["industry"] or f["industry"] in industry]
    if substrate and substrate != "":
        cands = [f for f in cands if substrate in f["substrate"] or f["substrate"] in substrate]
    if env_std:
        cands = [f for f in cands if env_std in (f.get("env_std") or [])]
    if cost_upper:
        cands = [f for f in cands if f["cost_per_kg"] <= cost_upper]
    # 评分：软约束匹配数
    scored = []
    for f in cands:
        score = 0
        if application_temp and application_temp in f["application_temp"]:
            score += 1
        if open_time_sec and abs((f["open_time_sec"] or 0) - open_time_sec) <= 3:
            score += 1
        if peel_strength_N and abs((f["peel_strength_N"] or 0) - peel_strength_N) <= 6:
            score += 1
        scored.append((f, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:3]
    return {
        "input": {"industry": industry, "substrate": substrate,
                  "application_temp": application_temp, "open_time_sec": open_time_sec,
                  "peel_strength_N": peel_strength_N, "env_std": env_std,
                  "cost_upper": cost_upper},
        "candidates": [
            {
                "formula_no": f["formula_no"], "name": f["name"], "type": f["type"],
                "industry": f["industry"], "substrate": f["substrate"],
                "application_temp": f["application_temp"], "open_time_sec": f["open_time_sec"],
                "peel_strength_N": f["peel_strength_N"], "env_std": f["env_std"],
                "cost_per_kg": f["cost_per_kg"], "status": f["status"],
                "version": f["version"], "match_score": sc,
                "initial_ratio": f.get("ingredients", []),
                "predicted_performance": _predicted_perf(f),
            }
            for f, sc in top
        ],
        "note": "initial_ratio 中 material_code 经 prefix 转换关联 ERP 采购物料"
                "（ING-RES-→M-RES-/ING-TK-→M-TK-/ING-WAX-→M-WAX-/ING-AO-→M-AO-）",
    }


def _predicted_perf(f: dict) -> dict:
    """基于配方组分的确定性性能预估（不杜撰，给区间）。"""
    ings = f.get("ingredients") or []
    wax = sum(i["ratio_pct"] for i in ings if i["category"] == "蜡")
    tk = sum(i["ratio_pct"] for i in ings if i["category"] == "增粘剂")
    res = sum(i["ratio_pct"] for i in ings if i["category"] == "树脂")
    softening = 80 + int(wax * (-1.5)) + int(tk * 0.4) + int(res * 0.3)
    viscosity = 5000 + int(tk * 80) + int(res * 60) - int(wax * 300)
    return {
        "softening_point_c": max(60, softening),
        "viscosity_mpa_s_180c": max(2000, viscosity),
        "peel_strength_N_est": f.get("peel_strength_N"),
        "temp_resistance_c_est": 60 + int(res * 0.5) - int(wax),
        "note": "区间预估，需小试复核",
    }


def predict_performance(tenant: str, formula_no: str) -> dict:
    """单配方性能预测：输入配方比例，预测软化点/粘度/剥离/持粘/耐温。"""
    d = load(tenant)
    f = d.formula_by_code.get(formula_no)
    if f is None:
        return {}
    return {
        "formula_no": formula_no, "name": f["name"], "type": f["type"],
        "ingredients": f.get("ingredients", []),
        "predicted": _predicted_perf(f),
        "history_experiments": [
            {"exp_no": e["exp_no"], "test_type": e["test_type"], "result": e["result"]}
            for e in d.experiments if e["formula_no"] == formula_no
        ],
    }


def analyze_experiment_data(tenant: str, exp_no: str) -> dict:
    """实验数据智能分析：识别异常数据（anomaly_flags）+ 关联测试方案 + 历史对比。"""
    d = load(tenant)
    e = d.experiment_by_code.get(exp_no)
    if e is None:
        return {}
    flags = e.get("anomaly_flags") or []
    same_formula = [x for x in d.experiments
                    if x["formula_no"] == e["formula_no"] and x["exp_no"] != exp_no]
    return {
        "exp_no": exp_no, "formula_no": e["formula_no"], "test_type": e["test_type"],
        "equipment": e["equipment"], "performed_by": e["performed_by"],
        "performed_at": e["performed_at"], "result": e["result"],
        "anomaly_flags": flags, "has_anomaly": len(flags) > 0,
        "report_no": e.get("report_no"),
        "same_formula_experiments": [
            {"exp_no": x["exp_no"], "test_type": x["test_type"], "result": x["result"]}
            for x in same_formula
        ],
        "related_failure_records": [
            {"fr_no": fr["fr_no"], "symptom": fr["symptom"],
             "root_cause": fr["root_cause"], "solution": fr["solution"]}
            for fr in d.failure_records if fr["formula_no"] == e["formula_no"]
        ],
        "analysis_summary": (
            "检测到异常指标，建议结合失效记录复测并调整配方"
            if flags else "数据正常，可流转下一测试环节"
        ),
    }


def generate_experiment_report(tenant: str, formula_no: str) -> dict:
    """实验报告自动生成：聚合配方下全部实验 + 测试方案 + 派生结论。"""
    d = load(tenant)
    f = d.formula_by_code.get(formula_no)
    if f is None:
        return {}
    exps = [e for e in d.experiments if e["formula_no"] == formula_no]
    scheme = next((s for s in d.test_schemes if any(
        s["scheme_no"] == e.get("report_no") for e in exps)), None)
    return {
        "report_title": f"《{f['name']} 实验分析报告》",
        "formula_no": formula_no, "name": f["name"], "type": f["type"],
        "industry": f["industry"], "substrate": f["substrate"],
        "env_std": f["env_std"], "version": f["version"], "owner": f["owner"],
        "ingredients": f.get("ingredients", []),
        "experiments": [
            {"exp_no": e["exp_no"], "test_type": e["test_type"], "equipment": e["equipment"],
             "result": e["result"], "anomaly_flags": e.get("anomaly_flags", []),
             "status": e["status"]}
            for e in exps
        ],
        "test_scheme": scheme,
        "performance_prediction": _predicted_perf(f),
        "related_failure_records": [
            {"fr_no": fr["fr_no"], "symptom": fr["symptom"],
             "root_cause": fr["root_cause"], "solution": fr["solution"]}
            for fr in d.failure_records if fr["formula_no"] == formula_no
        ],
        "conclusion": (
            "配方性能满足指标，可推进小试/送样" if not any(e.get("anomaly_flags") for e in exps)
            else "存在异常指标，建议复测并按失效记录调整配方后再流转"
        ),
    }
