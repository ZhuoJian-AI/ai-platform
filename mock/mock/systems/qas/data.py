"""QAS 多租户确定性种子数据——starhma（星途热熔胶，质量与技术服务）。

QAS 是叶系统（其他 mock 不反向引用 QAS），无循环依赖，沿用懒构建保持一致。
``starhma`` 一份 ``QasData``，覆盖来料/成品质检报告 / 客户客诉 / 售后故障案例 /
不良品记录，支撑「售后粘接故障智能诊断 + 检测报告自动生成 + 质量异常根因分析」三类场景。

码空间约定（no-guessing，详见 seed ontology ``identifiers.md``）：
  - 检测报告 ``QR-``（QR-IN- 来料 / QR-FG- 成品）；``batch_no`` 关联 MES 批次 ``BAT-``，
    ``material_code`` 关联 ERP 物料 ``M-``，``formula_no`` 关联 FRM 配方 ``FORM-``。
  - 客诉 ``CC-``；``customer_code`` 关联 CRM 客户 ``CLI-``，``formula_no``/``batch_no``
    回挂 FRM/MES 定位责任批次。
  - 故障案例 ``FC-``（symptom：开胶/拉丝/堵枪/低温失效/其他），售后知识库核心。
  - 不良品 ``NG-``；``batch_no`` 关联 MES 批次，根因分析据此跨 FRM 配方 + PCM 工艺参数。
  - 根因分析 ``RCA-``（由 ``analyzeRootCause`` 派生）。
``P-`` 单独出现为 HRM 岗位，与检测报告 ``QR-`` 不同码空间，按 prefix 区分勿互传。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry

BASE_DATE: date = date(2026, 7, 25)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class QasData:
    quality_reports: list[dict]               # 检测报告（来料/成品）
    quality_report_by_code: dict[str, dict]
    customer_complaints: list[dict]           # 客诉（售后粘接故障）
    complaint_by_code: dict[str, dict]
    failure_cases: list[dict]                 # 故障案例库（售后诊断知识库）
    failure_case_by_code: dict[str, dict]
    ng_records: list[dict]                    # 不良品记录（根因分析入口）


# ───────────────────────── starhma（星途热熔胶） ─────────────────────────


def _build_starhma() -> QasData:
    """星途热熔胶质量与技术服务口径：来料/成品质检报告 + 4 类售后粘接故障客诉
    （开胶/拉丝/堵枪/低温失效）+ 故障案例库 + 不良品记录，关联 FRM 配方与 MES 批次。"""
    R = D.rng(20260725)

    # 检测报告（来料 QR-IN-/成品 QR-FG-）
    quality_reports = [
        {"qr_no": "QR-IN-2026-001", "type": "来料",
         "material_code": "M-RES-001", "supplier_code": "S-HMA-RES",
         "batch_no": None, "formula_no": None,
         "items": [
             {"item": "熔融指数", "spec": "18-25 g/10min", "actual": "21.6", "result": "合格"},
             {"item": "含水率", "spec": "≤0.1%", "actual": "0.06%", "result": "合格"},
             {"item": "灰分", "spec": "≤0.3%", "actual": "0.18%", "result": "合格"},
         ],
         "inspector": "P-QAS-001", "inspected_at": f"{BASE_DATE - timedelta(days=4)}T10:00:00",
         "status": "已签发", "conclusion": "合格放行"},
        {"qr_no": "QR-IN-2026-002", "type": "来料",
         "material_code": "M-TK-001", "supplier_code": "S-HMA-TK",
         "batch_no": None, "formula_no": None,
         "items": [
             {"item": "软化点", "spec": "95±5℃", "actual": "92℃", "result": "合格"},
             {"item": "色度", "spec": "≤3#", "actual": "2#", "result": "合格"},
             {"item": "酸值", "spec": "≤1.0", "actual": "1.4", "result": "不合格"},
         ],
         "inspector": "P-QAS-001", "inspected_at": f"{BASE_DATE - timedelta(days=2)}T11:20:00",
         "status": "复检中", "conclusion": "酸值超标，让步接收或退货"},
        {"qr_no": "QR-FG-2026-001", "type": "成品",
         "material_code": "M-FG-001", "supplier_code": None,
         "batch_no": "BAT-2026-0701", "formula_no": "FORM-STD-001",
         "items": [
             {"item": "软化点", "spec": "88±5℃", "actual": "90℃", "result": "合格"},
             {"item": "粘度(180℃)", "spec": "6000±1000 mPa·s", "actual": "6300", "result": "合格"},
             {"item": "剥离强度", "spec": "≥16 N", "actual": "18.2 N", "result": "合格"},
             {"item": "开放时间", "spec": "8±2 s", "actual": "8 s", "result": "合格"},
         ],
         "inspector": "P-QAS-002", "inspected_at": f"{BASE_DATE - timedelta(days=3)}T16:00:00",
         "status": "已签发", "conclusion": "合格入库"},
        {"qr_no": "QR-FG-2026-002", "type": "成品",
         "material_code": "M-FG-002", "supplier_code": None,
         "batch_no": "BAT-2026-0702", "formula_no": "FORM-STD-002",
         "items": [
             {"item": "软化点", "spec": "92±5℃", "actual": "85℃", "result": "不合格"},
             {"item": "粘度(180℃)", "spec": "7400±1000 mPa·s", "actual": "9100", "result": "不合格"},
             {"item": "剥离强度", "spec": "≥20 N", "actual": "15.4 N", "result": "不合格"},
         ],
         "inspector": "P-QAS-002", "inspected_at": f"{BASE_DATE - timedelta(days=1)}T17:00:00",
         "status": "异常待处理", "conclusion": "多指标不合格，关联客诉 CC-2026-002 复盘"},
    ]
    quality_report_by_code = {q["qr_no"]: q for q in quality_reports}

    # 客诉（售后粘接故障）
    customer_complaints = [
        {"cc_no": "CC-2026-001", "customer_code": "CLI-001",
         "customer_name": "某汽车零部件厂", "formula_no": "FORM-CUS-001",
         "batch_no": "BAT-2026-0703", "symptom": "开胶",
         "substrate": "PET 植绒布/ABS", "condition_desc": "夏季车内高温 75℃ 持续暴晒后局部脱胶",
         "severity": "高", "status": "处理中", "received_at": f"{BASE_DATE - timedelta(days=6)}",
         "contact": "P-SAL-001"},
        {"cc_no": "CC-2026-002", "customer_code": "CLI-003",
         "customer_name": "某鞋材厂", "formula_no": "FORM-STD-002",
         "batch_no": "BAT-2026-0702", "symptom": "堵枪",
         "substrate": "EVA/PU 革", "condition_desc": "客户自动喷胶设备频繁堵枪，停机清理",
         "severity": "中", "status": "处理中", "received_at": f"{BASE_DATE - timedelta(days=1)}",
         "contact": "P-SAL-002"},
        {"cc_no": "CC-2026-003", "customer_code": "CLI-002",
         "customer_name": "某医疗耗材厂", "formula_no": "FORM-CUS-002",
         "batch_no": "BAT-2026-0704", "symptom": "低温失效",
         "substrate": "无纺布/PE 膜", "condition_desc": "冷链运输 -10℃ 后初粘不足、易剥离",
         "severity": "高", "status": "待复测", "received_at": f"{BASE_DATE - timedelta(days=2)}",
         "contact": "P-SAL-001"},
        {"cc_no": "CC-2026-004", "customer_code": "CLI-001",
         "customer_name": "某汽车零部件厂", "formula_no": "FORM-CUS-001",
         "batch_no": "BAT-2026-0703", "symptom": "拉丝",
         "substrate": "PET 植绒布/ABS", "condition_desc": "喷涂拉丝过长、断丝不齐",
         "severity": "低", "status": "已闭环", "received_at": f"{BASE_DATE - timedelta(days=18)}",
         "contact": "P-SAL-001"},
    ]
    complaint_by_code = {c["cc_no"]: c for c in customer_complaints}

    # 故障案例库（售后诊断知识库）
    failure_cases = [
        {"fc_no": "FC-2025-008", "symptom": "开胶", "substrate": "汽车内饰植绒",
         "root_cause": "APAO 比例过高，耐温不足，高温下内聚强度衰减",
         "solution": "下调 ING-RES-002 比例、增加 ING-WAX-002 提升耐高温；补充耐温 85℃×240h 老化测试",
         "related_formula": "FORM-CUS-001", "confidence": "高"},
        {"fc_no": "FC-2025-011", "symptom": "堵枪", "substrate": "鞋材/箱包",
         "root_cause": "蜡比例偏低、熔融粘度过高、凝固过快堵塞喷嘴",
         "solution": "上调 ING-WAX-001 至 10%，降低熔融粘度，调整凝固速度",
         "related_formula": "FORM-STD-002", "confidence": "高"},
        {"fc_no": "FC-2025-019", "symptom": "低温失效", "substrate": "医疗无纺布",
         "root_cause": "石油树脂 C5 玻璃化温度偏高，低温下初粘不足",
         "solution": "改用 ING-TK-002 萜烯树脂，提升 ING-RES-002 柔韧相比例，补做 -10℃ 适应性测试",
         "related_formula": "FORM-CUS-002", "confidence": "中"},
        {"fc_no": "FC-2026-002", "symptom": "拉丝", "substrate": "汽车内饰",
         "root_cause": "开放时间偏长、熔体延伸性过大",
         "solution": "微调 ING-WAX-001 缩短开放时间，提高凝固速度",
         "related_formula": "FORM-CUS-001", "confidence": "中"},
    ]
    failure_case_by_code = {f["fc_no"]: f for f in failure_cases}

    # 不良品记录（根因分析入口，关联 MES 批次 + FRM 配方 + PCM 工艺参数）
    ng_records = [
        {"ng_no": "NG-2026-001", "batch_no": "BAT-2026-0702",
         "formula_no": "FORM-STD-002", "product_code": "M-FG-002",
         "defect": "软化点偏低/粘度偏高/剥离不达标", "defect_qty_kg": 320,
         "detected_at": f"{BASE_DATE - timedelta(days=1)}T17:30:00",
         "process_suspect": "PP-REACT-002 反应时长/PP-STIR-002 搅拌温度",
         "related_qr": "QR-FG-2026-002", "related_cc": "CC-2026-002"},
        {"ng_no": "NG-2026-002", "batch_no": "BAT-2026-0703",
         "formula_no": "FORM-CUS-001", "product_code": None,
         "defect": "高温剥离衰减（客诉开胶）", "defect_qty_kg": 80,
         "detected_at": f"{BASE_DATE - timedelta(days=5)}T09:00:00",
         "process_suspect": "PP-STIR-004/反应釜 EQ-RX-02 振动异常",
         "related_qr": None, "related_cc": "CC-2026-001"},
    ]

    return QasData(
        quality_reports=quality_reports, quality_report_by_code=quality_report_by_code,
        customer_complaints=customer_complaints, complaint_by_code=complaint_by_code,
        failure_cases=failure_cases, failure_case_by_code=failure_case_by_code,
        ng_records=ng_records,
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[QasData]({
    "starhma": _build_starhma,
})


def load(tenant: str) -> QasData:
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量 ───────────────────────────────────────────────────


def diagnose_after_sales_fault(tenant: str, *, symptom: str | None = None,
                                substrate: str | None = None,
                                condition: str | None = None) -> dict:
    """售后故障智能诊断：按现象/基材/工况匹配历史客诉与故障案例，给排查方案。"""
    d = load(tenant)
    cases = list(d.failure_cases)
    if symptom:
        cases = [c for c in cases if c["symptom"] == symptom or symptom in c["symptom"]]
    matched_complaints = [c for c in d.customer_complaints
                         if (not symptom or c["symptom"] == symptom)
                         and (not substrate or substrate in c["substrate"]
                              or c["substrate"] in substrate)]
    return {
        "input": {"symptom": symptom, "substrate": substrate, "condition": condition},
        "matched_failure_cases": cases[:3],
        "matched_complaints": [
            {"cc_no": c["cc_no"], "customer_code": c["customer_code"],
             "customer_name": c["customer_name"], "formula_no": c["formula_no"],
             "batch_no": c["batch_no"], "symptom": c["symptom"],
             "substrate": c["substrate"], "condition_desc": c["condition_desc"],
             "severity": c["severity"], "status": c["status"]}
            for c in matched_complaints
        ],
        "diagnosis": (
            f"现象「{symptom or '-'}」匹配故障案例 {len(cases)} 条；"
            f"历史客诉 {len(matched_complaints)} 条"
        ),
        "suggested_actions": [
            f"复核配方 {c['related_formula']} 组分比例，参考案例 {c['fc_no']}"
            for c in cases[:2]
        ] or ["无匹配案例，建议立案实验复测"],
    }


def generate_inspection_report(tenant: str, *, batch_no: str | None = None,
                                qr_no: str | None = None) -> dict:
    """检测报告自动生成：聚合来料/成品检验数据，生成标准化质检报告。"""
    d = load(tenant)
    if qr_no:
        q = d.quality_report_by_code.get(qr_no)
        if q is None:
            return {}
        reports = [q]
    elif batch_no:
        reports = [r for r in d.quality_reports if r.get("batch_no") == batch_no]
        if not reports:
            return {}
    else:
        return {}
    summary = []
    for r in reports:
        items = r.get("items") or []
        unqualified = [i for i in items if i["result"] == "不合格"]
        summary.append({
            "qr_no": r["qr_no"], "type": r["type"], "batch_no": r.get("batch_no"),
            "formula_no": r.get("formula_no"), "material_code": r.get("material_code"),
            "inspector": r["inspector"], "inspected_at": r["inspected_at"],
            "status": r["status"], "conclusion": r["conclusion"],
            "items": items, "unqualified_count": len(unqualified),
        })
    all_pass = all(s["unqualified_count"] == 0 for s in summary)
    return {
        "report_title": "星途热熔胶 质量检测报告",
        "batch_no": batch_no, "qr_no": qr_no,
        "reports": summary,
        "overall_conclusion": "全部指标合格，准予放行" if all_pass
        else "存在不合格项，按让步/退货/复检流程处置",
        "note": "原料 batch_no 关联 MES 批次，material_code 关联 ERP 物料",
    }


def analyze_root_cause(tenant: str, *, ng_no: str | None = None,
                        batch_no: str | None = None) -> dict:
    """质量异常根因分析：关联不良品→配方→工艺参数→客诉，辅助定位质量波动原因。"""
    d = load(tenant)
    if ng_no:
        ngs = [n for n in d.ng_records if n["ng_no"] == ng_no]
    elif batch_no:
        ngs = [n for n in d.ng_records if n["batch_no"] == batch_no]
    else:
        ngs = d.ng_records
    if not ngs:
        return {}
    result_ngs = []
    for n in ngs:
        related_qr = (d.quality_report_by_code.get(n["related_qr"])
                      if n.get("related_qr") else None)
        related_cc = (d.complaint_by_code.get(n["related_cc"])
                      if n.get("related_cc") else None)
        result_ngs.append({
            "ng_no": n["ng_no"], "batch_no": n["batch_no"], "formula_no": n["formula_no"],
            "product_code": n["product_code"], "defect": n["defect"],
            "defect_qty_kg": n["defect_qty_kg"], "detected_at": n["detected_at"],
            "process_suspect": n["process_suspect"],
            "related_quality_report": (
                {"qr_no": related_qr["qr_no"], "type": related_qr["type"],
                 "items": related_qr["items"], "conclusion": related_qr["conclusion"]}
                if related_qr else None
            ),
            "related_complaint": (
                {"cc_no": related_cc["cc_no"], "symptom": related_cc["symptom"],
                 "customer_name": related_cc["customer_name"],
                 "condition_desc": related_cc["condition_desc"]}
                if related_cc else None
            ),
        })
    return {
        "ng_records": result_ngs,
        "root_cause_summary": (
            "多起不良品指向工艺参数漂移（反应时长/搅拌温度）与设备振动异常，"
            "建议联动 PCM 工艺参数复核与设备预测维护闭环排查"
        ),
        "cross_system_refs": {
            "mes_batch": [n["batch_no"] for n in ngs],
            "frm_formula": list({n["formula_no"] for n in ngs if n.get("formula_no")}),
            "pcm_process_suspect": [n["process_suspect"] for n in ngs],
        },
    }
