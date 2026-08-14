"""DES 多租户确定性种子数据——starexploration（星途勘探，工程设计）。

DES 是叶系统（其他 mock 不反向引用 DES），无循环依赖，沿用懒构建保持一致。
``starexploration`` 一份 ``DesData``，覆盖设计方案 / 图纸 / 规范条款 / 算量项 /
跨专业碰撞，支撑「设计方案比选 + 规范合规校验 + 智能算量造价」三类场景。

码空间约定（no-guessing，详见 seed ontology ``identifiers.md``）：
  - 设计方案 ``SCH-``（SCH-IND- 工业厂房 / SCH-BAT- 电池工厂 / SCH-CIV- 市政）；
    方案转项目时与 EPC ``PRJ-`` 按 ``scheme_no`` 关联。
  - 图纸 ``DWG-``（DWG-ARC- 建筑 / DWG-STR- 结构 / DWG-MEP- 机电）；图纸交付物
    与 EPC 项目文档 ``PDOC-``、SEC 涉密文档 ``SECDOC-`` 按 ``drawing_no`` 关联。
  - 规范条款 ``SPEC-``（SPEC-GB-xxxxx 国标编号）。
  - 算量项 ``QTI-``（QTI-CON- 混凝土 / QTI-STE- 钢筋 / QTI-ARC- 建筑做法）；
    算量项转采购物料与 ERP ``M-CON-`` / ``M-STE-`` 按 ``material_code`` 关联
    （prefix 转换：QTI-CON- → M-CON-，QTI-STE- → M-STE-，勿互传）。
  - 跨专业碰撞 ``CLS-``。
``P-`` 单独出现为 HRM 岗位（P-DES 设计岗），与 ERP 物料 ``M-`` 不同码空间，
按 prefix 区分勿互传。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry

BASE_DATE: date = date(2026, 7, 23)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class DesData:
    schemes: list[dict]                     # 设计方案
    scheme_by_code: dict[str, dict]
    drawings: list[dict]                    # 图纸（关联方案）
    drawing_by_code: dict[str, dict]
    specs: list[dict]                       # 规范条款（含强条/条文）
    spec_by_code: dict[str, dict]
    quantity_items: list[dict]              # 算量项（关联方案/图纸/ERP 物料）
    clashes: list[dict]                     # 跨专业碰撞


# ───────────────────────── starexploration（星途勘探） ─────────────────────────


def _build_starexploration() -> DesData:
    """星途勘探设计管理口径：工业厂房 / 电池工厂 / 市政水厂三套方案 +
    各专业图纸 + 抗震/防火/地基规范强条 + 混凝土/钢筋/做法算量项 + 跨专业碰撞。"""
    R = D.rng(20260723)

    schemes = [
        {"scheme_no": "SCH-IND-001", "name": "某电工装备制造厂房方案",
         "domain": "工业工程", "site": "湖南长沙经开区", "capacity": "年产电工装备 50 万套",
         "footprint_m2": 42000, "invest_wan": 18000, "stage": "施工图",
         "lead": "P-DES-001", "disciplines": ["建筑", "结构", "机电", "工艺"],
         "status": "设计中", "version": "V2.1", "updated_at": f"{BASE_DATE - timedelta(days=6)}"},
        {"scheme_no": "SCH-BAT-001", "name": "某锂离子电池工厂方案",
         "domain": "工业工程", "site": "江苏常州高新区", "capacity": "年产能 20GWh",
         "footprint_m2": 96000, "invest_wan": 95000, "stage": "扩初",
         "lead": "P-DES-002", "disciplines": ["建筑", "结构", "机电", "工艺", "洁净"],
         "status": "比选阶段", "version": "V1.3", "updated_at": f"{BASE_DATE - timedelta(days=2)}"},
        {"scheme_no": "SCH-CIV-001", "name": "某市政污水处理厂方案",
         "domain": "城乡服务", "site": "安徽合肥滨湖", "capacity": "日处理 20 万吨",
         "footprint_m2": 58000, "invest_wan": 32000, "stage": "可研",
         "lead": "P-DES-003", "disciplines": ["建筑", "结构", "机电", "水工"],
         "status": "前期咨询", "version": "V0.9", "updated_at": f"{BASE_DATE - timedelta(days=18)}"},
    ]
    scheme_by_code = {s["scheme_no"]: s for s in schemes}

    drawings = [
        # SCH-IND-001 图纸
        {"drawing_no": "DWG-ARC-001", "scheme_no": "SCH-IND-001", "discipline": "建筑",
         "title": "厂房总平面与立面图", "scale": "1:200", "sheet_count": 12,
         "designer": "P-DES-011", "reviewer": "P-DES-001", "status": "校审中",
         "compliance_flags": ["防火分区面积超限"], "updated_at": f"{BASE_DATE - timedelta(days=4)}"},
        {"drawing_no": "DWG-STR-001", "scheme_no": "SCH-IND-001", "discipline": "结构",
         "title": "厂房基础与主体结构图", "scale": "1:100", "sheet_count": 18,
         "designer": "P-DES-012", "reviewer": "P-DES-001", "status": "校审中",
         "compliance_flags": ["抗震等级取值偏低"], "updated_at": f"{BASE_DATE - timedelta(days=3)}"},
        {"drawing_no": "DWG-MEP-001", "scheme_no": "SCH-IND-001", "discipline": "机电",
         "title": "厂房机电管线综合图", "scale": "1:150", "sheet_count": 9,
         "designer": "P-DES-013", "reviewer": "P-DES-001", "status": "设计中",
         "compliance_flags": [], "updated_at": f"{BASE_DATE - timedelta(days=2)}"},
        # SCH-BAT-001 图纸
        {"drawing_no": "DWG-ARC-002", "scheme_no": "SCH-BAT-001", "discipline": "建筑",
         "title": "电池工厂总平面图", "scale": "1:300", "sheet_count": 8,
         "designer": "P-DES-021", "reviewer": "P-DES-002", "status": "比选中",
         "compliance_flags": ["洁净区疏散距离偏长"], "updated_at": f"{BASE_DATE - timedelta(days=1)}"},
        {"drawing_no": "DWG-STR-002", "scheme_no": "SCH-BAT-001", "discipline": "结构",
         "title": "电池工厂结构方案图", "scale": "1:150", "sheet_count": 14,
         "designer": "P-DES-022", "reviewer": "P-DES-002", "status": "比选中",
         "compliance_flags": [], "updated_at": f"{BASE_DATE - timedelta(days=1)}"},
        {"drawing_no": "DWG-MEP-002", "scheme_no": "SCH-BAT-001", "discipline": "机电",
         "title": "电池工厂机电管线综合", "scale": "1:200", "sheet_count": 11,
         "designer": "P-DES-023", "reviewer": "P-DES-002", "status": "比选中",
         "compliance_flags": ["防爆区电气未隔离"], "updated_at": f"{BASE_DATE}"},
        # SCH-CIV-001 图纸
        {"drawing_no": "DWG-ARC-003", "scheme_no": "SCH-CIV-001", "discipline": "建筑",
         "title": "水厂附属建筑图", "scale": "1:200", "sheet_count": 6,
         "designer": "P-DES-031", "reviewer": "P-DES-003", "status": "可研",
         "compliance_flags": [], "updated_at": f"{BASE_DATE - timedelta(days=16)}"},
    ]
    drawing_by_code = {d["drawing_no"]: d for d in drawings}

    specs = [
        {"spec_code": "SPEC-GB-50011", "name": "建筑抗震设计规范", "clause": "6.1.3",
         "is_mandatory": True, "discipline": "结构", "requirement": "丙类建筑抗震设防烈度按所在地区采用",
         "check_field": "seismic_fortification_intensity"},
        {"spec_code": "SPEC-GB-50011", "name": "建筑抗震设计规范", "clause": "6.1.2",
         "is_mandatory": True, "discipline": "结构", "requirement": "钢筋混凝土房屋抗震等级按设防烈度与高度查表",
         "check_field": "seismic_grade"},
        {"spec_code": "SPEC-GB-50016", "name": "建筑设计防火规范", "clause": "3.3.1",
         "is_mandatory": True, "discipline": "建筑", "requirement": "厂房防火分区最大允许建筑面积按类别与层数查表",
         "check_field": "fire_compartment_area"},
        {"spec_code": "SPEC-GB-50016", "name": "建筑设计防火规范", "clause": "3.7.4",
         "is_mandatory": True, "discipline": "建筑", "requirement": "厂房内任一点至最近安全出口疏散距离限值",
         "check_field": "evacuation_distance"},
        {"spec_code": "SPEC-GB-50007", "name": "建筑地基基础设计规范", "clause": "3.0.4",
         "is_mandatory": True, "discipline": "结构", "requirement": "地基基础设计等级按建筑规模与地基复杂程度确定",
         "check_field": "foundation_design_grade"},
        {"spec_code": "SPEC-GB-50207", "name": "洁净厂房设计规范", "clause": "4.3.1",
         "is_mandatory": True, "discipline": "工艺/洁净", "requirement": "洁净区疏散口设置满足安全疏散要求",
         "check_field": "cleanroom_evacuation"},
        {"spec_code": "SPEC-GB-50058", "name": "爆炸危险环境电力装置设计规范", "clause": "5.2.2",
         "is_mandatory": True, "discipline": "机电", "requirement": "防爆区电气设备选型与隔离满足防爆等级",
         "check_field": "explosion_proof_electrical"},
    ]
    spec_by_code: dict[str, dict] = {}
    for sp in specs:
        spec_by_code.setdefault(sp["spec_code"], sp)

    # 算量项（关联方案/图纸，material_code 映射 ERP 物料 M-CON-/M-STE-）
    quantity_items = [
        {"qi_no": "QTI-CON-001", "scheme_no": "SCH-IND-001", "drawing_no": "DWG-STR-001",
         "item": "C35 现浇混凝土柱", "discipline": "结构", "uom": "m³",
         "qty": 1280.5, "material_code": "M-CON-001", "unit_cost": 580.0},
        {"qi_no": "QTI-CON-002", "scheme_no": "SCH-IND-001", "drawing_no": "DWG-STR-001",
         "item": "C30 现浇混凝土梁板", "discipline": "结构", "uom": "m³",
         "qty": 4600.0, "material_code": "M-CON-002", "unit_cost": 540.0},
        {"qi_no": "QTI-STE-001", "scheme_no": "SCH-IND-001", "drawing_no": "DWG-STR-001",
         "item": "HRB400 钢筋（主筋）", "discipline": "结构", "uom": "t",
         "qty": 186.4, "material_code": "M-STE-001", "unit_cost": 4200.0},
        {"qi_no": "QTI-ARC-001", "scheme_no": "SCH-IND-001", "drawing_no": "DWG-ARC-001",
         "item": "环氧地坪做法", "discipline": "建筑", "uom": "m²",
         "qty": 12000.0, "material_code": "M-ARC-001", "unit_cost": 165.0},
        {"qi_no": "QTI-CON-003", "scheme_no": "SCH-BAT-001", "drawing_no": "DWG-STR-002",
         "item": "C40 洁净车间现浇混凝土", "discipline": "结构", "uom": "m³",
         "qty": 9200.0, "material_code": "M-CON-001", "unit_cost": 610.0},
        {"qi_no": "QTI-STE-002", "scheme_no": "SCH-BAT-001", "drawing_no": "DWG-STR-002",
         "item": "HRB500 钢筋（洁净车间）", "discipline": "结构", "uom": "t",
         "qty": 412.0, "material_code": "M-STE-002", "unit_cost": 4350.0},
        {"qi_no": "QTI-CON-004", "scheme_no": "SCH-CIV-001", "drawing_no": "DWG-STR-001",
         "item": "C30 水池池壁混凝土", "discipline": "结构", "uom": "m³",
         "qty": 3200.0, "material_code": "M-CON-002", "unit_cost": 560.0},
    ]

    # 跨专业碰撞（结构 vs 机电 vs 建筑同一方案内）
    clashes = [
        {"clash_no": "CLS-2026-001", "scheme_no": "SCH-IND-001",
         "discipline_a": "结构", "drawing_a": "DWG-STR-001",
         "discipline_b": "机电", "drawing_b": "DWG-MEP-001",
         "desc": "结构梁与机电风管碰撞（轴 5-6/C-D）", "severity": "中", "status": "待协调",
         "detected_at": f"{BASE_DATE - timedelta(days=3)}"},
        {"clash_no": "CLS-2026-002", "scheme_no": "SCH-IND-001",
         "discipline_a": "建筑", "drawing_a": "DWG-ARC-001",
         "discipline_b": "机电", "drawing_b": "DWG-MEP-001",
         "desc": "建筑防火墙开洞与机电桥架穿越未封堵", "severity": "高", "status": "待协调",
         "detected_at": f"{BASE_DATE - timedelta(days=2)}"},
        {"clash_no": "CLS-2026-003", "scheme_no": "SCH-BAT-001",
         "discipline_a": "结构", "drawing_a": "DWG-STR-002",
         "discipline_b": "机电", "drawing_b": "DWG-MEP-002",
         "desc": "结构楼板预留洞与机电管道定位偏差", "severity": "中", "status": "已协调",
         "detected_at": f"{BASE_DATE - timedelta(days=1)}"},
    ]

    return DesData(
        schemes=schemes, scheme_by_code=scheme_by_code,
        drawings=drawings, drawing_by_code=drawing_by_code,
        specs=specs, spec_by_code=spec_by_code,
        quantity_items=quantity_items, clashes=clashes,
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[DesData]({
    "starexploration": _build_starexploration,
})


def load(tenant: str) -> DesData:
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量 ───────────────────────────────────────────────────


def check_drawing_compliance(tenant: str, drawing_no: str) -> dict:
    """图纸 vs 规范条款合规校验：把图纸 ``compliance_flags`` 逐条匹配规范强条，
    返回违规项 + 修正建议（确定性派生，不杜撰分数）。"""
    d = load(tenant)
    dwg = d.drawing_by_code.get(drawing_no)
    if dwg is None:
        return {}
    flags = dwg.get("compliance_flags") or []
    violations: list[dict] = []
    flag_to_spec = {
        "防火分区面积超限": ("SPEC-GB-50016", "3.3.1", "按厂房类别与层数复核防火分区最大允许建筑面积，超限应设防火墙分隔或调整层数"),
        "抗震等级取值偏低": ("SPEC-GB-50011", "6.1.2", "按设防烈度与房屋高度查表确定抗震等级并复核构造措施"),
        "洁净区疏散距离偏长": ("SPEC-GB-50207", "4.3.1", "洁净区增设安全出口或调整平面缩短疏散距离"),
        "防爆区电气未隔离": ("SPEC-GB-50058", "5.2.2", "防爆区电气设备按防爆等级选型并隔离非防爆回路"),
    }
    for fl in flags:
        spec_code, clause, fix = flag_to_spec.get(
            fl, ("SPEC-UNKNOWN", "-", "对照相应设计规范强条复核"))
        violations.append({
            "drawing_no": drawing_no, "discipline": dwg["discipline"],
            "flag": fl, "spec_code": spec_code, "clause": clause,
            "is_mandatory": True, "fix_suggestion": fix,
        })
    return {
        "drawing_no": drawing_no, "title": dwg["title"],
        "discipline": dwg["discipline"], "status": dwg["status"],
        "scheme_no": dwg["scheme_no"],
        "checked_specs": [s["spec_code"] for s in d.specs],
        "violations": violations,
        "passed": len(violations) == 0,
    }


def compute_quantity_takeoff(tenant: str, scheme_no: str) -> dict:
    """按方案聚合算量项 + 造价测算：联动 ERP 物料 material_code（prefix 转换）。"""
    d = load(tenant)
    sch = d.scheme_by_code.get(scheme_no)
    if sch is None:
        return {}
    items = [q for q in d.quantity_items if q["scheme_no"] == scheme_no]
    total = 0.0
    by_discipline: dict[str, dict] = {}
    by_material: list[dict] = []
    for q in items:
        amt = round(q["qty"] * q["unit_cost"], 2)
        total += amt
        agg = by_discipline.setdefault(q["discipline"], {"qty_lines": 0, "amount": 0.0})
        agg["qty_lines"] += 1
        agg["amount"] = round(agg["amount"] + amt, 2)
        by_material.append({
            "qi_no": q["qi_no"], "item": q["item"], "discipline": q["discipline"],
            "uom": q["uom"], "qty": q["qty"],
            "material_code": q["material_code"],  # 映射 ERP 物料 M-CON-/M-STE-/M-ARC-
            "unit_cost": q["unit_cost"], "amount": amt,
        })
    return {
        "scheme_no": scheme_no, "name": sch["name"], "domain": sch["domain"],
        "invest_wan": sch["invest_wan"], "stage": sch["stage"],
        "qty_lines": len(items),
        "by_discipline": [{"discipline": k, **v} for k, v in by_discipline.items()],
        "by_material": by_material,
        "total_cost": round(total, 2),
        "note": "material_code 经 prefix 转换关联 ERP 采购物料（QTI-CON-→M-CON-/QTI-STE-→M-STE-）",
    }


def detect_clashes(tenant: str, scheme_no: str) -> list[dict]:
    """同一方案内跨专业碰撞清单（确定性派生）。"""
    d = load(tenant)
    return [c for c in d.clashes if c["scheme_no"] == scheme_no]
