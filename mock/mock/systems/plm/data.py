"""PLM 多租户确定性种子数据——starclothing（星图服装，服装专用）。

PLM 是叶系统（其他 mock 不引用 PLM），无循环依赖，但沿用懒构建保持一致性。
``starclothing`` 一份 ``PlmData``，覆盖款式 / BOM / 数字面料库 / 打样单 / 大货单 /
质检报告 / 缺陷历史 / 物料库存 / 领料流水 / 应付应收 / 凭证 / 成本台账 /
面料可行性测算留痕。

跨系统取数（MES 工单号 / CRM 销售订单号 / ERP 物料号）走 ``try/except TenantBuilding``
回退占位 ref，避免 import 时硬依赖；PLM 数据本身尽量自包含（关联键自生成）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry, TenantBuilding

BASE_DATE: date = date(2026, 6, 29)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class PlmData:
    styles: list[dict]
    style_by_code: dict[str, dict]
    boms: list[dict]                       # 款式 BOM 行（material_code + 用量 + 损耗）
    bom_by_style: dict[str, list[dict]]
    fabrics: list[dict]                    # 数字面料库
    fabric_by_code: dict[str, dict]
    sampling_orders: list[dict]            # 打样单
    sampling_order_by_no: dict[str, dict]
    bulk_orders: list[dict]                # 大货单
    bulk_order_by_no: dict[str, dict]
    qc_reports: list[dict]                 # 质检报告
    defect_history: list[dict]            # 缺陷历史（结构化，供 PD-3 检索）
    material_inventory: list[dict]        # 面料/辅料实盘
    pickings: list[dict]                   # 领料流水（关联大货工单/款号）
    payables: list[dict]                   # 应付（按款归集的面料采购应付视角）
    receivables: list[dict]               # 应收（按款归集的成衣销售应收视角）
    vouchers: list[dict]                   # 财务凭证
    cost_ledger: list[dict]                # 成本台账（按款号/面料/期间）
    feasibility_logs: list[dict]           # 面料可行性测算留痕（PD-2 交期快照）
    steel_grades: list[dict] = field(default_factory=list)        # 钢种主数据（agilesteel）
    steel_grade_by_code: dict[str, dict] = field(default_factory=dict)


# ───────────────────────── 跨系统取数（同 tenant） ─────────────────────────


def _mes_work_orders(tenant: str) -> list[str]:
    """跨系统取同 tenant 的 MES 工单号；MES 未就绪或循环构造中时回退占位。"""
    try:
        from mock.systems.mes.data import load as _load_mes
        d = _load_mes(tenant)
        return [w["work_order_no"] for w in d.work_orders]
    except (Exception, TenantBuilding):  # noqa: BLE001
        return ["XWO20260607"]


def _crm_sales_orders(tenant: str) -> list[str]:
    try:
        from mock.systems.crm.data import load as _load_crm
        d = _load_crm(tenant)
        return [s["so_no"] for s in d.sales_orders]
    except (Exception, TenantBuilding):  # noqa: BLE001
        return ["XSO20260005"]


# ───────────────────────── starclothing（星图服装） ─────────────────────────


def _build_starclothing() -> PlmData:
    """星图服装口径 PLM 数据：款式/BOM/面料库/打样/大货/质检/缺陷/库存/领料/应收应付/成本/可行性。"""
    R = D.rng(20241201)

    # ── 款式 STYLES（8 款，product_code 与 MES starclothing PRODUCTS 对齐）──
    styles = [
        {
            "style_code": "P-FW2026-001", "name": "双面呢长大衣", "category": "FW 秋冬季",
            "season": "FW2026", "fabric_main": "M-WOOL-DBL-360", "material_composition": "30%羊绒 70%羊毛",
            "qty_per_batch": 200, "unit_cost": 2880.0, "status": "已量产",
            "designer": "设计师-林", "developer": "开发-陈",
            "sample_due_date": f"{BASE_DATE - timedelta(days=120)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=30)}",
        },
        {
            "style_code": "P-FW2026-002", "name": "压胶冲锋衣", "category": "FW 秋冬季",
            "season": "FW2026", "fabric_main": "M-SHELL-3L-150", "material_composition": "三层复合面料 150D",
            "qty_per_batch": 300, "unit_cost": 1580.0, "status": "已量产",
            "designer": "设计师-王", "developer": "开发-周",
            "sample_due_date": f"{BASE_DATE - timedelta(days=90)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=20)}",
        },
        {
            "style_code": "P-SS2026-010", "name": "纯棉T恤", "category": "SS 春夏季",
            "season": "SS2026", "fabric_main": "M-TC-180", "material_composition": "T/C 65/35 平纹",
            "qty_per_batch": 1000, "unit_cost": 89.0, "status": "已量产",
            "designer": "设计师-赵", "developer": "开发-孙",
            "sample_due_date": f"{BASE_DATE - timedelta(days=60)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=10)}",
        },
        {
            "style_code": "P-SS2026-011", "name": "摇粒绒开衫", "category": "SS 春夏季",
            "season": "SS2026", "fabric_main": "M-FLEECE-280", "material_composition": "摇粒绒 280g 抓绒",
            "qty_per_batch": 600, "unit_cost": 199.0, "status": "已量产",
            "designer": "设计师-赵", "developer": "开发-孙",
            "sample_due_date": f"{BASE_DATE - timedelta(days=50)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=5)}",
        },
        {
            "style_code": "P-SS2026-020", "name": "牛仔裤", "category": "SS 春夏季",
            "season": "SS2026", "fabric_main": "M-DNIM-320", "material_composition": "丹宁布 320g",
            "qty_per_batch": 800, "unit_cost": 299.0, "status": "已量产",
            "designer": "设计师-钱", "developer": "开发-李",
            "sample_due_date": f"{BASE_DATE - timedelta(days=70)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=15)}",
        },
        {
            "style_code": "P-AP2026-030", "name": "风衣", "category": "AP 春秋季",
            "season": "AP2026", "fabric_main": "M-MIX-200", "material_composition": "涤粘混纺 200g",
            "qty_per_batch": 400, "unit_cost": 899.0, "status": "打样中",
            "designer": "设计师-林", "developer": "开发-陈",
            "sample_due_date": f"{BASE_DATE + timedelta(days=10)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=60)}",
        },
        {
            "style_code": "P-AP2026-031", "name": "衬衫", "category": "AP 春秋季",
            "season": "AP2026", "fabric_main": "M-LINEN-160", "material_composition": "棉麻 160g",
            "qty_per_batch": 700, "unit_cost": 259.0, "status": "开发中",
            "designer": "设计师-王", "developer": "开发-周",
            "sample_due_date": f"{BASE_DATE + timedelta(days=20)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=75)}",
        },
        {
            "style_code": "P-AP2026-032", "name": "卫衣", "category": "AP 春秋季",
            "season": "AP2026", "fabric_main": "M-KNIT-260", "material_composition": "针织布 260g",
            "qty_per_batch": 500, "unit_cost": 329.0, "status": "打样中",
            "designer": "设计师-钱", "developer": "开发-李",
            "sample_due_date": f"{BASE_DATE + timedelta(days=5)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=50)}",
        },
    ]
    style_by_code = {s["style_code"]: s for s in styles}

    # ── BOM：每款 3-5 行，material_code 与 ERP starclothing materials 对齐 ──
    bom_spec: dict[str, list[tuple[str, float, float]]] = {
        # style_code -> [(material_code, qty_per_garment, loss_rate%), ...]
        "P-FW2026-001": [
            ("M-WOOL-DBL-360", 2.4, 3.0),
            ("M-INTER-030", 1.2, 2.0),
            ("M-BTN-RESIN", 6.0, 1.0),
            ("M-PKG-POLY", 1.0, 0.0),
            ("M-PKG-CTN", 0.05, 0.0),
        ],
        "P-FW2026-002": [
            ("M-SHELL-3L-150", 2.0, 4.0),
            ("M-ZIP-YKK-5", 1.0, 0.5),
            ("M-INTER-030", 0.8, 2.0),
            ("M-PKG-POLY", 1.0, 0.0),
            ("M-PKG-CTN", 0.05, 0.0),
        ],
        "P-SS2026-010": [
            ("M-TC-180", 1.3, 5.0),
            ("M-BTN-RESIN", 2.0, 1.0),
            ("M-PKG-POLY", 1.0, 0.0),
        ],
        "P-SS2026-011": [
            ("M-FLEECE-280", 1.5, 4.0),
            ("M-ZIP-XJ-3", 1.0, 0.5),
            ("M-PKG-POLY", 1.0, 0.0),
        ],
        "P-SS2026-020": [
            ("M-DNIM-320", 1.4, 6.0),
            ("M-ZIP-XJ-3", 1.0, 0.5),
            ("M-BTN-RESIN", 1.0, 1.0),
            ("M-PKG-CTN", 0.05, 0.0),
        ],
        "P-AP2026-030": [
            ("M-MIX-200", 2.2, 4.0),
            ("M-BTN-RESIN", 5.0, 1.0),
            ("M-INTER-030", 1.0, 2.0),
            ("M-PKG-POLY", 1.0, 0.0),
        ],
        "P-AP2026-031": [
            ("M-LINEN-160", 1.6, 5.0),
            ("M-BTN-RESIN", 8.0, 1.0),
            ("M-INTER-030", 0.6, 2.0),
            ("M-PKG-POLY", 1.0, 0.0),
        ],
        "P-AP2026-032": [
            ("M-KNIT-260", 1.7, 4.0),
            ("M-ZIP-XJ-3", 1.0, 0.5),
            ("M-PKG-POLY", 1.0, 0.0),
            ("M-PKG-CTN", 0.05, 0.0),
        ],
    }
    boms: list[dict] = []
    bom_by_style: dict[str, list[dict]] = {}
    for style_code, rows in bom_spec.items():
        lines: list[dict] = []
        for li, (mat_code, qty, loss) in enumerate(rows, start=1):
            line = {
                "style_code": style_code, "line_no": li,
                "material_code": mat_code, "qty_per_garment": qty,
                "uom": "m" if mat_code.startswith(("M-WOOL", "M-SHELL", "M-TC", "M-FLEECE",
                                                    "M-INTER", "M-DNIM", "M-MIX", "M-LINEN", "M-KNIT")) else (
                    "条" if "ZIP" in mat_code else ("粒" if "BTN" in mat_code else "个")),
                "loss_rate_pct": loss,
            }
            boms.append(line)
            lines.append(line)
        bom_by_style[style_code] = lines

    # ── 面料库 FABRICS（12 个，数字面料库，含测算字段）──
    fabrics = [
        {
            "fabric_code": "F-WOOL-DBL-360", "name": "双面呢 360g/㎡", "composition": "30%羊绒 70%羊毛",
            "weight_gsm": 360, "width_mm": 1500, "category": "面料",
            "supplier_code": "XS-FAB-003", "moq": 500, "leadtime_days": 45,
            "capacity_per_day": 500, "unit_cost": 168.0, "loss_rate": 3.0, "available_stock": 1200,
        },
        {
            "fabric_code": "F-SHELL-3L-150", "name": "三层复合面料 150D", "composition": "面料+防水透气膜+里布",
            "weight_gsm": 150, "width_mm": 1450, "category": "面料",
            "supplier_code": "XS-FAB-001", "moq": 300, "leadtime_days": 30,
            "capacity_per_day": 800, "unit_cost": 92.0, "loss_rate": 4.0, "available_stock": 800,
        },
        {
            "fabric_code": "F-TC-180", "name": "T/C 布 65/35 180g 平纹", "composition": "涤棉 65/35",
            "weight_gsm": 180, "width_mm": 1600, "category": "面料",
            "supplier_code": "XS-FAB-002", "moq": 1000, "leadtime_days": 15,
            "capacity_per_day": 2000, "unit_cost": 18.5, "loss_rate": 5.0, "available_stock": 3500,
        },
        {
            "fabric_code": "F-FLEECE-280", "name": "摇粒绒 280g 抓绒", "composition": "100%涤纶",
            "weight_gsm": 280, "width_mm": 1500, "category": "面料",
            "supplier_code": "XS-FAB-001", "moq": 400, "leadtime_days": 20,
            "capacity_per_day": 1200, "unit_cost": 35.0, "loss_rate": 4.0, "available_stock": 900,
        },
        {
            "fabric_code": "F-DNIM-320", "name": "丹宁布 320g", "composition": "100%棉",
            "weight_gsm": 320, "width_mm": 1500, "category": "面料",
            "supplier_code": "XS-FAB-002", "moq": 800, "leadtime_days": 25,
            "capacity_per_day": 1500, "unit_cost": 28.0, "loss_rate": 6.0, "available_stock": 1800,
        },
        {
            "fabric_code": "F-MIX-200", "name": "涤粘混纺 200g", "composition": "涤粘 60/40",
            "weight_gsm": 200, "width_mm": 1500, "category": "面料",
            "supplier_code": "XS-FAB-001", "moq": 500, "leadtime_days": 22,
            "capacity_per_day": 1500, "unit_cost": 42.0, "loss_rate": 4.0, "available_stock": 700,
        },
        {
            "fabric_code": "F-LINEN-160", "name": "棉麻 160g", "composition": "棉麻 55/45",
            "weight_gsm": 160, "width_mm": 1450, "category": "面料",
            "supplier_code": "XS-FAB-002", "moq": 600, "leadtime_days": 18,
            "capacity_per_day": 1800, "unit_cost": 26.0, "loss_rate": 5.0, "available_stock": 1100,
        },
        {
            "fabric_code": "F-KNIT-260", "name": "针织布 260g", "composition": "棉涤涤 60/30/10",
            "weight_gsm": 260, "width_mm": 1750, "category": "面料",
            "supplier_code": "XS-FAB-001", "moq": 500, "leadtime_days": 20,
            "capacity_per_day": 1600, "unit_cost": 38.0, "loss_rate": 4.0, "available_stock": 1000,
        },
        {
            "fabric_code": "F-INTER-030", "name": "30D 有光衬 18g/㎡", "composition": "100%涤纶 有光衬",
            "weight_gsm": 18, "width_mm": 1500, "category": "辅料",
            "supplier_code": "XS-FAB-002", "moq": 800, "leadtime_days": 12,
            "capacity_per_day": 2500, "unit_cost": 2.8, "loss_rate": 2.0, "available_stock": 2000,
        },
        {
            "fabric_code": "F-ZIP-YKK-5", "name": "YKK 5# 树脂拉链 3:1 双开", "composition": "树脂+尼龙",
            "weight_gsm": 0, "width_mm": 0, "category": "辅料",
            "supplier_code": "XS-ACC-010", "moq": 2000, "leadtime_days": 10,
            "capacity_per_day": 8000, "unit_cost": 6.8, "loss_rate": 0.5, "available_stock": 4500,
        },
        {
            "fabric_code": "F-BTN-RESIN", "name": "树脂四眼纽扣 18L", "composition": "树脂",
            "weight_gsm": 0, "width_mm": 0, "category": "辅料",
            "supplier_code": "XS-ACC-020", "moq": 5000, "leadtime_days": 8,
            "capacity_per_day": 20000, "unit_cost": 0.45, "loss_rate": 1.0, "available_stock": 12000,
        },
        {
            "fabric_code": "F-PKG-POLY", "name": "PE 平口袋 30×40", "composition": "PE",
            "weight_gsm": 0, "width_mm": 0, "category": "辅料包装",
            "supplier_code": "XS-PKG-040", "moq": 5000, "leadtime_days": 5,
            "capacity_per_day": 30000, "unit_cost": 0.18, "loss_rate": 0.0, "available_stock": 18000,
        },
    ]
    fabric_by_code = {f["fabric_code"]: f for f in fabrics}

    # ── 打样单 SAMPLING_ORDERS（12 个，故意构造 4 个超期）──
    sampling_orders: list[dict] = []
    sampling_rows = [
        # (suffix, style_code, factory, stage, status, plan_offset, actual_offset)
        (1, "P-FW2026-001", "F-XT-HZ", "确认样", "已确认", -60, -65),
        (2, "P-FW2026-002", "F-XT-HZ", "二样", "已确认", -50, -55),
        (3, "P-SS2026-010", "F-XT-SZ", "初样", "已确认", -40, -42),
        (4, "P-SS2026-011", "F-XT-SZ", "初样", "已确认", -35, -37),
        (5, "P-SS2026-020", "F-XT-DG", "二样", "打样中", -30, None),     # 超期 30 天
        (6, "P-AP2026-030", "F-XT-HZ", "初样", "打样中", -7, None),      # 超期 7 天
        (7, "P-AP2026-031", "F-XT-HZ", "初样", "待排", 3, None),         # 未到计划日，未超期
        (8, "P-AP2026-032", "F-XT-SZ", "二样", "打样中", -5, None),      # 超期 5 天
        (9, "P-FW2026-001", "F-XT-DG", "确认样", "已退回", -45, None),    # 超期 45 天
        (10, "P-FW2026-002", "F-XT-HZ", "初样", "已确认", -20, -22),
        (11, "P-SS2026-010", "F-XT-SZ", "二样", "已确认", -25, -27),
        (12, "P-AP2026-030", "F-XT-HZ", "二样", "待排", 10, None),       # 未到计划日
    ]
    for suffix, style_code, factory, stage, status, plan_off, actual_off in sampling_rows:
        plan_date = BASE_DATE + timedelta(days=plan_off)
        actual_date = (BASE_DATE + timedelta(days=actual_off)) if actual_off is not None else None
        if actual_date is not None:
            days_late = max(0, (actual_date - plan_date).days)
        else:
            days_late = max(0, (BASE_DATE - plan_date).days)
        sampling_orders.append({
            "sampling_no": f"SMP20260{suffix:03d}",
            "style_code": style_code,
            "style_name": style_by_code[style_code]["name"],
            "factory": factory,
            "stage": stage,
            "status": status,
            "plan_date": f"{plan_date}",
            "actual_date": f"{actual_date}" if actual_date else None,
            "days_late": days_late,
            "overdue": days_late > 0,
        })
    sampling_order_by_no = {s["sampling_no"]: s for s in sampling_orders}

    # ── 大货单 BULK_ORDERS（10 个，故意构造 3 个超期）──
    bulk_orders: list[dict] = []
    bulk_rows = [
        # (suffix, style_code, customer_code, factory, qty, plan_start_off, plan_end_off, actual_end_off, cap, delivery_off, qc_status)
        (1, "P-FW2026-001", "C-BRAND-001", "F-XT-HZ", 200, -30, -5, -7, 50, 5, "PASS"),
        (2, "P-FW2026-002", "C-BRAND-003", "F-XT-HZ", 300, -25, -3, None, 60, 3, "PENDING"),  # 超期 3 天
        (3, "P-SS2026-010", "C-BRAND-002", "F-XT-SZ", 1000, -20, -2, -4, 300, 2, "PASS"),
        (4, "P-SS2026-011", "C-BRAND-004", "F-XT-SZ", 600, -18, -1, None, 200, 4, "PENDING"),  # 超期 1 天
        (5, "P-SS2026-020", "C-DIST-010", "F-XT-DG", 800, -22, -3, -5, 250, 3, "PASS"),
        (6, "P-AP2026-030", "C-BRAND-001", "F-XT-HZ", 400, -10, 15, None, 80, 18, "PENDING"),
        (7, "P-FW2026-001", "C-BRAND-003", "F-XT-DG", 200, -35, -8, None, 50, 0, "FAIL"),     # 超期 8 天
        (8, "P-SS2026-010", "C-DIST-011", "F-XT-SZ", 1000, -15, 2, 1, 300, 5, "PASS"),
        (9, "P-SS2026-011", "C-BRAND-004", "F-XT-SZ", 600, -12, 5, None, 200, 8, "PENDING"),
        (10, "P-FW2026-002", "C-ODM-020", "F-XT-HZ", 300, -20, 1, 0, 60, 4, "PASS"),
    ]
    for suffix, style_code, customer_code, factory, qty, ps_off, pe_off, ae_off, cap, del_off, qc_status in bulk_rows:
        plan_start = BASE_DATE + timedelta(days=ps_off)
        plan_end = BASE_DATE + timedelta(days=pe_off)
        actual_end = (BASE_DATE + timedelta(days=ae_off)) if ae_off is not None else None
        delivery_date = BASE_DATE + timedelta(days=del_off)
        if actual_end is not None:
            days_late = max(0, (actual_end - plan_end).days)
        else:
            days_late = max(0, (BASE_DATE - plan_end).days)
        bulk_orders.append({
            "bulk_no": f"BLK20260{suffix:03d}",
            "style_code": style_code,
            "style_name": style_by_code[style_code]["name"],
            "customer_code": customer_code,
            "factory": factory,
            "qty": qty,
            "plan_start": f"{plan_start}",
            "plan_end": f"{plan_end}",
            "actual_end": f"{actual_end}" if actual_end else None,
            "capacity_per_day": cap,
            "delivery_date": f"{delivery_date}",
            "qc_status": qc_status,
            "days_late": days_late,
            "overdue": days_late > 0,
        })
    bulk_order_by_no = {b["bulk_no"]: b for b in bulk_orders}

    # ── 质检报告 QC_REPORTS（10 个）──
    qc_rows = [
        # (suffix, bulk_no, style_code, check_off, aql, sample, defect, pass, summary)
        (1, "BLK2026001", "P-FW2026-001", -4, "AQL2.5", 32, 1, True, "车缝跳针 1 处，已返修"),
        (2, "BLK2026002", "P-FW2026-002", -1, "AQL2.5", 32, 4, False, "压胶脱落 4 处"),
        (3, "BLK2026003", "P-SS2026-010", -2, "AQL2.5", 50, 2, True, "印花错位 2 处，让步接收"),
        (4, "BLK2026004", "P-SS2026-011", 0, "AQL2.5", 32, 0, True, "合格"),
        (5, "BLK2026005", "P-SS2026-020", -3, "AQL4.0", 50, 3, True, "水洗色差 3 处，让步接收"),
        (6, "BLK2026007", "P-FW2026-001", -6, "AQL2.5", 32, 5, False, "整烫烫花 5 处"),
        (7, "BLK2026008", "P-SS2026-010", 1, "AQL2.5", 50, 1, True, "跳针断线 1 处，已返修"),
        (8, "BLK2026010", "P-FW2026-002", 0, "AQL2.5", 32, 0, True, "合格"),
        (9, "BLK2026006", "P-AP2026-030", 14, "AQL2.5", 32, 2, True, "尺寸偏差 2 处，让步接收"),
        (10, "BLK2026009", "P-SS2026-011", 5, "AQL2.5", 32, 6, False, "起球 6 处"),
    ]
    qc_reports: list[dict] = []
    for suffix, bulk_no, style_code, check_off, aql, sample, defect, passed, summary in qc_rows:
        qc_reports.append({
            "qc_no": f"QC20260{suffix:03d}",
            "bulk_no": bulk_no,
            "style_code": style_code,
            "inspector": D.pick(R, ["QC-周", "QC-吴", "QC-郑"]),
            "check_date": f"{BASE_DATE + timedelta(days=check_off)}",
            "aql_level": aql,
            "sample_size": sample,
            "defect_count": defect,
            "pass": passed,
            "defect_summary": summary,
        })

    # ── 缺陷历史 DEFECT_HISTORY（18 条，结构化，供 PD-3 检索）──
    defect_rows = [
        # (case_id, style_code, category, defect_type, severity, root_cause, corrective, avoidance, date_off, work_order_no)
        ("DF20260001", "P-FW2026-002", "压胶冲锋衣", "漏水", "严重", "压胶温度不足 105℃",
         "调高至 130℃+保压 3s", "压胶工序首件必测水温压", -35, "XWO20260607"),
        ("DF20260002", "P-FW2026-002", "压胶冲锋衣", "压胶脱落", "严重", "胶条库存过期受潮",
         "更换新批次胶条+环境湿度≤60%", "胶条先进先出，超过 6 个月禁用", -28, "XWO20260698"),
        ("DF20260003", "P-FW2026-001", "双面呢大衣", "起球", "一般", "羊毛纱线捻度偏低",
         "调整纺纱捻度+抗起球助剂", "羊绒含量≥30%必做抗起球测试", -25, "XWO20260789"),
        ("DF20260004", "P-SS2026-010", "纯棉T恤", "掉色", "严重", "活性染料固色不充分",
         "增加皂洗+固色剂", "深色款必测色牢度≥4级", -22, "XWO20260880"),
        ("DF20260005", "P-SS2026-020", "牛仔裤", "掉色", "一般", "水洗时间不足",
         "延长水洗 15 分钟", "深色丹宁首件测干摩擦牢度", -20, "XWO20260971"),
        ("DF20260006", "P-AP2026-030", "风衣", "尺寸偏差", "一般", "裁剪样板未复核",
         "首件三检+样板版本锁定", "改版后首件必做尺寸全检", -18, "XWO20261062"),
        ("DF20260007", "P-SS2026-010", "纯棉T恤", "印花错位", "一般", "网版定位松动",
         "重新校位+定位销", "印花首件校位并签字", -16, "XWO20261153"),
        ("DF20260008", "P-AP2026-032", "卫衣", "印花错位", "一般", "布面张力不均",
         "调整张力导辊+预热", "针织布印花前必过定型", -14, "XWO20261244"),
        ("DF20260009", "P-FW2026-001", "双面呢大衣", "整烫烫花", "严重", "熨斗温度过高 180℃",
         "调至 150℃+垫布", "羊绒款禁裸烫，必垫烫布", -12, "XWO20261335"),
        ("DF20260010", "P-SS2026-011", "摇粒绒开衫", "跳针断线", "一般", "机针 9# 偏细",
         "换 11# 机针+线张力调低", "摇粒绒款统一用 11# 针", -10, "XWO20261426"),
        ("DF20260011", "P-SS2026-020", "牛仔裤", "尺寸偏差", "严重", "水洗缩率未预缩",
         "样板预加 2% 缩率", "丹宁款必做预缩测试", -8, "XWO20261517"),
        ("DF20260012", "P-FW2026-002", "压胶冲锋衣", "漏水", "严重", "拉链位压胶断点",
         "拉链两端补压 5cm", "拉链位必做封胶检测", -6, "XWO20261608"),
        ("DF20260013", "P-AP2026-031", "衬衫", "跳针断线", "一般", "线迹密度过稀",
         "调至 16 针/3cm", "棉麻款首件测线迹密度", -4, "XWO20261699"),
        ("DF20260014", "P-SS2026-010", "纯棉T恤", "起球", "一般", "纱线毛羽偏长",
         "增加烧毛工序", "纯棉浅色款必过烧毛", -3, "XWO20261790"),
        ("DF20260015", "P-AP2026-030", "风衣", "整烫烫花", "一般", "蒸汽压力过大",
         "调低蒸汽压力 0.2MPa", "混纺款熨烫温度≤160℃", -2, "XWO20261881"),
        ("DF20260016", "P-FW2026-001", "双面呢大衣", "尺寸偏差", "一般", "手缝吃势不均",
         "手缝工序标准化+首件签字", "双面呢款手缝必做尺寸抽检", -1, "XWO20261972"),
        ("DF20260017", "P-SS2026-020", "牛仔裤", "跳针断线", "一般", "包缝线断裂",
         "更换高弹线", "丹宁款包缝统一用 60S/3 弹力线", 0, "XWO20262063"),
        ("DF20260018", "P-FW2026-002", "压胶冲锋衣", "压胶脱落", "严重", "压胶机硅胶轮老化",
         "更换硅胶轮", "压胶机每 3 个月检查胶轮硬度", 1, "XWO20262154"),
    ]
    defect_history: list[dict] = []
    for case_id, style_code, category, dtype, sev, root, corr, avoid, off, won in defect_rows:
        defect_history.append({
            "case_id": case_id,
            "style_code": style_code,
            "category": category,
            "defect_type": dtype,
            "severity": sev,
            "root_cause": root,
            "corrective_action": corr,
            "avoidance_hint": avoid,
            "date_reported": f"{BASE_DATE + timedelta(days=off)}",
            "work_order_no": won,
        })

    # ── 物料库存 MATERIAL_INVENTORY：每面料/辅料一条 ──
    material_inventory: list[dict] = []
    for f in fabrics:
        if f["category"] == "面料":
            wh = "WH-FAB"
        elif f["category"] == "辅料":
            wh = "WH-ACC"
        else:
            wh = "WH-PKG"
        material_inventory.append({
            "material_code": f["fabric_code"],
            "material_name": f["name"],
            "warehouse": wh,
            "stock_qty": f["available_stock"],
            "available_qty": max(0, f["available_stock"] - D.randint(R, 0, 100)),
            "safety_stock": f["moq"],
            "uom": "m" if f["category"] == "面料" else ("条" if "ZIP" in f["fabric_code"] else (
                "粒" if "BTN" in f["fabric_code"] else "个")),
        })

    # ── 领料流水 PICKINGS（18 条）──
    mes_wos = _mes_work_orders("starclothing")
    pickings: list[dict] = []
    picking_specs = [
        # (suffix, bulk_no, style_code, material_code, qty, warehouse, picker, off)
        (1, "BLK2026001", "P-FW2026-001", "F-WOOL-DBL-360", 480, "WH-FAB", "仓管-陈", -8),
        (2, "BLK2026001", "P-FW2026-001", "F-INTER-030", 240, "WH-ACC", "仓管-陈", -8),
        (3, "BLK2026001", "P-FW2026-001", "F-BTN-RESIN", 1200, "WH-ACC", "仓管-陈", -7),
        (4, "BLK2026002", "P-FW2026-002", "F-SHELL-3L-150", 600, "WH-FAB", "仓管-周", -6),
        (5, "BLK2026002", "P-FW2026-002", "F-ZIP-YKK-5", 300, "WH-ACC", "仓管-周", -6),
        (6, "BLK2026003", "P-SS2026-010", "F-TC-180", 1300, "WH-FAB", "仓管-林", -5),
        (7, "BLK2026004", "P-SS2026-011", "F-FLEECE-280", 900, "WH-FAB", "仓管-林", -4),
        (8, "BLK2026004", "P-SS2026-011", "F-ZIP-YKK-5", 600, "WH-ACC", "仓管-林", -4),
        (9, "BLK2026005", "P-SS2026-020", "F-DNIM-320", 1120, "WH-FAB", "仓管-邓", -3),
        (10, "BLK2026006", "P-AP2026-030", "F-MIX-200", 880, "WH-FAB", "仓管-陈", -2),
        (11, "BLK2026007", "P-FW2026-001", "F-WOOL-DBL-360", 480, "WH-FAB", "仓管-陈", -2),
        (12, "BLK2026008", "P-SS2026-010", "F-TC-180", 1300, "WH-FAB", "仓管-林", -1),
        (13, "BLK2026010", "P-FW2026-002", "F-SHELL-3L-150", 600, "WH-FAB", "仓管-周", 0),
        (14, "BLK2026005", "P-SS2026-020", "F-BTN-RESIN", 800, "WH-ACC", "仓管-邓", -3),
        (15, "BLK2026009", "P-SS2026-011", "F-FLEECE-280", 900, "WH-FAB", "仓管-林", 0),
        (16, "BLK2026003", "P-SS2026-010", "F-BTN-RESIN", 2000, "WH-ACC", "仓管-林", -5),
        (17, "BLK2026001", "P-FW2026-001", "F-PKG-POLY", 200, "WH-PKG", "仓管-胡", -7),
        (18, "BLK2026010", "P-FW2026-002", "F-PKG-POLY", 300, "WH-PKG", "仓管-胡", 0),
    ]
    for suffix, bulk_no, style_code, mat_code, qty, wh, picker, off in picking_specs:
        won = mes_wos[(suffix - 1) % len(mes_wos)] if mes_wos else "XWO20260607"
        pickings.append({
            "picking_no": f"PK20260{suffix:03d}",
            "bulk_no": bulk_no,
            "style_code": style_code,
            "material_code": mat_code,
            "qty": qty,
            "uom": "m" if mat_code.startswith("F-WOOL") or mat_code.startswith("F-SHELL") or
                     mat_code.startswith("F-TC") or mat_code.startswith("F-FLEECE") or
                     mat_code.startswith("F-DNIM") or mat_code.startswith("F-MIX") or
                     mat_code.startswith("F-LINEN") or mat_code.startswith("F-KNIT") or
                     mat_code.startswith("F-INTER") else ("条" if "ZIP" in mat_code else (
                "粒" if "BTN" in mat_code else "个")),
            "warehouse": wh,
            "ref_work_order": won,
            "picker": picker,
            "date": f"{BASE_DATE + timedelta(days=off)}",
        })

    # ── 应付 PAYABLES（8 条，按款归集的面料采购应付视角）──
    payable_specs = [
        # (suffix, supplier_code, style_code, amount, billing_off, due_off, status)
        (1, "XS-FAB-003", "P-FW2026-001", 240_000, -45, 5, "未到期"),
        (2, "XS-FAB-001", "P-FW2026-002", 168_000, -40, -5, "逾期"),
        (3, "XS-FAB-002", "P-SS2026-010", 96_000, -35, 10, "未到期"),
        (4, "XS-FAB-001", "P-SS2026-011", 84_000, -30, -2, "逾期"),
        (5, "XS-FAB-002", "P-SS2026-020", 120_000, -32, 8, "未到期"),
        (6, "XS-ACC-010", "P-FW2026-002", 36_000, -28, -8, "逾期"),
        (7, "XS-FAB-001", "P-AP2026-030", 132_000, -20, 15, "未到期"),
        (8, "XS-FAB-002", "P-AP2026-031", 78_000, -18, 18, "未到期"),
    ]
    payables: list[dict] = []
    for suffix, sup, style_code, amt, b_off, d_off, status in payable_specs:
        due = BASE_DATE + timedelta(days=d_off)
        payables.append({
            "payable_id": f"XPAP20260{suffix:03d}",
            "supplier_code": sup,
            "style_code": style_code,
            "invoice_no": f"XPINV20260{suffix:03d}",
            "amount": amt, "currency": "CNY",
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": status,
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    # ── 应收 RECEIVABLES（8 条，按款归集的成衣销售应收视角）──
    receivable_specs = [
        # (suffix, customer_code, style_code, amount, billing_off, due_off, status)
        (1, "C-BRAND-001", "P-FW2026-001", 576_000, -25, 20, "未到期"),
        (2, "C-BRAND-003", "P-FW2026-002", 474_000, -22, -3, "逾期"),
        (3, "C-BRAND-002", "P-SS2026-010", 89_000, -20, 25, "未到期"),
        (4, "C-BRAND-004", "P-SS2026-011", 119_400, -18, -1, "逾期"),
        (5, "C-DIST-010", "P-SS2026-020", 239_200, -15, 30, "未到期"),
        (6, "C-BRAND-001", "P-AP2026-030", 359_600, -10, 35, "未到期"),
        (7, "C-ODM-020", "P-FW2026-002", 474_000, -12, 18, "未到期"),
        (8, "C-DIST-011", "P-SS2026-010", 89_000, -8, -7, "逾期"),
    ]
    receivables: list[dict] = []
    for suffix, cust, style_code, amt, b_off, d_off, status in receivable_specs:
        due = BASE_DATE + timedelta(days=d_off)
        receivables.append({
            "receivable_id": f"XAR20260{suffix:03d}",
            "customer_code": cust,
            "style_code": style_code,
            "invoice_no": f"XARINV20260{suffix:03d}",
            "amount": amt, "currency": "CNY",
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": status,
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    # ── 凭证 VOUCHERS（7 条）──
    voucher_specs = [
        # (suffix, period, summary_off, debit, credit, status)
        (1, "2026-04", -70, 240_000, 240_000, "已过账"),
        (2, "2026-05", -50, 168_000, 168_000, "已过账"),
        (3, "2026-05", -40, 96_000, 96_000, "已复核"),
        (4, "2026-06", -25, 120_000, 120_000, "已复核"),
        (5, "2026-06", -15, 84_000, 84_000, "草稿"),
        (6, "2026-06", -8, 132_000, 132_000, "草稿"),
        (7, "2026-06", -3, 78_000, 78_000, "草稿"),
    ]
    summaries = ["双面呢面料采购入库核算", "冲锋衣面料采购入库核算", "T恤面料采购入库核算",
                 "牛仔裤面料采购入库核算", "摇粒绒面料采购入库核算", "风衣面料采购入库核算",
                 "衬衫面料采购入库核算"]
    vouchers: list[dict] = []
    for suffix, period, off, debit, credit, status in voucher_specs:
        vouchers.append({
            "voucher_no": f"XPLFV20260{suffix:03d}",
            "period": period,
            "entry_date": f"{BASE_DATE + timedelta(days=off)}",
            "summary": summaries[suffix - 1],
            "debit_total": debit, "credit_total": credit,
            "status": status,
        })

    # ── 成本台账 COST_LEDGER（12 条）──
    cost_specs = [
        # (suffix, style_code, material_code, period, mat, labor, oh)
        (1, "P-FW2026-001", "F-WOOL-DBL-360", "2026-04", 403.2, 180.0, 90.0),
        (2, "P-FW2026-001", "F-INTER-030", "2026-04", 3.36, 0.0, 2.0),
        (3, "P-FW2026-002", "F-SHELL-3L-150", "2026-05", 184.0, 120.0, 60.0),
        (4, "P-FW2026-002", "F-ZIP-YKK-5", "2026-05", 6.8, 5.0, 1.0),
        (5, "P-SS2026-010", "F-TC-180", "2026-05", 24.05, 12.0, 6.0),
        (6, "P-SS2026-011", "F-FLEECE-280", "2026-06", 52.5, 18.0, 8.0),
        (7, "P-SS2026-020", "F-DNIM-320", "2026-06", 39.2, 25.0, 10.0),
        (8, "P-AP2026-030", "F-MIX-200", "2026-06", 92.4, 35.0, 15.0),
        (9, "P-AP2026-031", "F-LINEN-160", "2026-06", 41.6, 20.0, 8.0),
        (10, "P-AP2026-032", "F-KNIT-260", "2026-06", 64.6, 22.0, 10.0),
        (11, "P-FW2026-001", "F-BTN-RESIN", "2026-04", 2.7, 1.5, 0.5),
        (12, "P-FW2026-002", "F-SHELL-3L-150", "2026-06", 184.0, 125.0, 62.0),
    ]
    cost_ledger: list[dict] = []
    for suffix, style_code, mat_code, period, mat, labor, oh in cost_specs:
        cost_ledger.append({
            "ledger_no": f"XCL20260{suffix:03d}",
            "style_code": style_code,
            "material_code": mat_code,
            "period": period,
            "cost_material": round(mat, 2),
            "cost_labor": round(labor, 2),
            "cost_overhead": round(oh, 2),
            "cost_total": round(mat + labor + oh, 2),
            "updated_at": f"{BASE_DATE + timedelta(days=D.randint(R, -5, 0))}T10:00:00",
        })

    # ── 可行性测算留痕 FEASIBILITY_LOGS（7 条，PD-2 交期快照）──
    feasibility_specs = [
        # (suffix, style_code, fabric_code, supplier, qty, cost_est, leadtime, cap, decision, off)
        (1, "P-FW2026-001", "F-WOOL-DBL-360", "XS-FAB-003", 480, 80640.0, 45, 500, "通过", -90),
        (2, "P-FW2026-002", "F-SHELL-3L-150", "XS-FAB-001", 600, 55200.0, 30, 800, "通过", -80),
        (3, "P-SS2026-010", "F-TC-180", "XS-FAB-002", 1300, 24050.0, 15, 2000, "通过", -70),
        (4, "P-SS2026-011", "F-FLEECE-280", "XS-FAB-001", 900, 31500.0, 20, 1200, "通过", -60),
        (5, "P-SS2026-020", "F-DNIM-320", "XS-FAB-002", 1120, 31360.0, 25, 1500, "通过", -55),
        (6, "P-AP2026-030", "F-MIX-200", "XS-FAB-001", 880, 36960.0, 22, 1500, "通过-预警交期", -30),
        (7, "P-AP2026-031", "F-LINEN-160", "XS-FAB-002", 1120, 29120.0, 18, 1800, "通过", -20),
    ]
    feasibility_logs: list[dict] = []
    for suffix, style_code, fab_code, sup, qty, cost_est, leadtime, cap, decision, off in feasibility_specs:
        feasibility_logs.append({
            "log_no": f"FL20260{suffix:03d}",
            "style_code": style_code,
            "fabric_code": fab_code,
            "supplier_code": sup,
            "qty_requested": qty,
            "cost_estimated": cost_est,
            "leadtime_estimated": leadtime,
            "capacity_available": cap,
            "snapshot_at": f"{BASE_DATE + timedelta(days=off)}T09:00:00",
            "decision": decision,
        })

    return PlmData(
        styles=styles, style_by_code=style_by_code,
        boms=boms, bom_by_style=bom_by_style,
        fabrics=fabrics, fabric_by_code=fabric_by_code,
        sampling_orders=sampling_orders, sampling_order_by_no=sampling_order_by_no,
        bulk_orders=bulk_orders, bulk_order_by_no=bulk_order_by_no,
        qc_reports=qc_reports, defect_history=defect_history,
        material_inventory=material_inventory, pickings=pickings,
        payables=payables, receivables=receivables,
        vouchers=vouchers, cost_ledger=cost_ledger,
        feasibility_logs=feasibility_logs,
    )


# ───────────────────────── agileac（敏睿空调） ─────────────────────────


def _build_agileac() -> PlmData:
    """敏睿空调 PLM 数据：6 款空调产品（家用壁挂/柜机/移动 + 商用多联机/风管/模块）
    + 5 类配件（压缩机/冷凝器/蒸发器/电子膨胀阀/制冷剂）+ BOM + 工程变更 +
    故障案例（8 类空调故障）+ 成本台账 + 卖点库。"""
    R = D.rng(20260101)

    # ── 产品 STYLES（6 款空调，style_code 兼作产品款号）──
    styles = [
        {
            "style_code": "P-RC-WALL-15", "name": "1.5匹壁挂式家用空调", "category": "家用·壁挂",
            "season": "2026夏季", "fabric_main": "M-COMP-GT-24K", "material_composition": "R410A/转子压缩机",
            "qty_per_batch": 500, "unit_cost": 1880.0, "status": "已量产",
            "designer": "电气-陈", "developer": "结构-林",
            "sample_due_date": f"{BASE_DATE - timedelta(days=180)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=30)}",
        },
        {
            "style_code": "P-RC-CAB-30", "name": "3匹立柜式家用空调", "category": "家用·柜机",
            "season": "2026夏季", "fabric_main": "M-COMP-GT-24K", "material_composition": "R410A/转子压缩机",
            "qty_per_batch": 300, "unit_cost": 3680.0, "status": "已量产",
            "designer": "电气-陈", "developer": "结构-周",
            "sample_due_date": f"{BASE_DATE - timedelta(days=150)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=20)}",
        },
        {
            "style_code": "P-RC-MOVE-10", "name": "1匹移动空调", "category": "家用·移动",
            "season": "2026夏季", "fabric_main": "M-COMP-GT-24K", "material_composition": "R410A/转子压缩机",
            "qty_per_batch": 200, "unit_cost": 1280.0, "status": "已量产",
            "designer": "电气-王", "developer": "结构-孙",
            "sample_due_date": f"{BASE_DATE - timedelta(days=120)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=15)}",
        },
        {
            "style_code": "P-CC-VRV-360", "name": "360型家用商用多联机外机", "category": "商用·多联机",
            "season": "2026商用", "fabric_main": "M-COMP-GT-24K", "material_composition": "R410A/涡旋压缩机",
            "qty_per_batch": 80, "unit_cost": 12800.0, "status": "已量产",
            "designer": "电气-赵", "developer": "结构-李",
            "sample_due_date": f"{BASE_DATE - timedelta(days=200)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=45)}",
        },
        {
            "style_code": "P-CC-DUCT-50", "name": "50型商用风管机", "category": "商用·风管",
            "season": "2026商用", "fabric_main": "M-COMP-GT-24K", "material_composition": "R410A/转子压缩机",
            "qty_per_batch": 120, "unit_cost": 6800.0, "status": "已量产",
            "designer": "电气-赵", "developer": "结构-钱",
            "sample_due_date": f"{BASE_DATE - timedelta(days=160)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=25)}",
        },
        {
            "style_code": "P-CC-CHILL-100", "name": "100RT模块冷水机组", "category": "商用·模块",
            "season": "2026商用", "fabric_main": "M-COMP-GT-24K", "material_composition": "R410A/涡旋压缩机",
            "qty_per_batch": 30, "unit_cost": 38800.0, "status": "已量产",
            "designer": "电气-赵", "developer": "结构-周",
            "sample_due_date": f"{BASE_DATE - timedelta(days=240)}",
            "bulk_due_date": f"{BASE_DATE + timedelta(days=60)}",
        },
    ]
    style_by_code = {s["style_code"]: s for s in styles}

    # ── BOM：每款 5 行（5 类配件各 1 行），material_code 与 ERP agileac materials 对齐 ──
    bom_spec: dict[str, list[tuple[str, float, float]]] = {
        # style_code -> [(material_code, qty_per_unit, loss_rate%), ...]
        "P-RC-WALL-15": [
            ("M-COMP-GT-24K", 1.0, 0.5),
            ("M-COND-FIN-30", 1.0, 1.0),
            ("M-EVAP-FIN-30", 1.0, 1.0),
            ("M-EEV-15", 1.0, 0.5),
            ("M-RF-R410A", 0.8, 2.0),
        ],
        "P-RC-CAB-30": [
            ("M-COMP-GT-24K", 1.0, 0.5),
            ("M-COND-FIN-30", 1.2, 1.0),
            ("M-EVAP-FIN-30", 1.0, 1.0),
            ("M-EEV-15", 1.0, 0.5),
            ("M-RF-R410A", 1.5, 2.0),
        ],
        "P-RC-MOVE-10": [
            ("M-COMP-GT-24K", 1.0, 0.5),
            ("M-COND-FIN-30", 0.8, 1.0),
            ("M-EVAP-FIN-30", 0.8, 1.0),
            ("M-EEV-15", 1.0, 0.5),
            ("M-RF-R410A", 0.4, 2.0),
        ],
        "P-CC-VRV-360": [
            ("M-COMP-GT-24K", 2.0, 0.5),
            ("M-COND-FIN-30", 4.0, 1.0),
            ("M-EVAP-FIN-30", 3.0, 1.0),
            ("M-EEV-15", 4.0, 0.5),
            ("M-RF-R410A", 12.0, 2.0),
        ],
        "P-CC-DUCT-50": [
            ("M-COMP-GT-24K", 1.0, 0.5),
            ("M-COND-FIN-30", 2.0, 1.0),
            ("M-EVAP-FIN-30", 1.5, 1.0),
            ("M-EEV-15", 2.0, 0.5),
            ("M-RF-R410A", 5.0, 2.0),
        ],
        "P-CC-CHILL-100": [
            ("M-COMP-GT-24K", 4.0, 0.5),
            ("M-COND-FIN-30", 8.0, 1.0),
            ("M-EVAP-FIN-30", 6.0, 1.0),
            ("M-EEV-15", 8.0, 0.5),
            ("M-RF-R410A", 40.0, 2.0),
        ],
    }
    boms: list[dict] = []
    bom_by_style: dict[str, list[dict]] = {}
    for style_code, rows in bom_spec.items():
        lines: list[dict] = []
        for li, (mat_code, qty, loss) in enumerate(rows, start=1):
            line = {
                "style_code": style_code, "line_no": li,
                "material_code": mat_code, "qty_per_garment": qty,
                "uom": "台" if mat_code.startswith("M-COMP") else (
                    "套" if mat_code.startswith(("M-COND", "M-EVAP")) else (
                        "只" if mat_code.startswith("M-EEV") else "kg")),
                "loss_rate_pct": loss,
            }
            boms.append(line)
            lines.append(line)
        bom_by_style[style_code] = lines

    # ── 配件库 FABRICS（5 类，复用 fabric 字段名表示配件主数据）──
    fabrics = [
        {
            "fabric_code": "M-COMP-GT-24K", "name": "24K转子压缩机", "composition": "转子式/直流变频/R410A",
            "weight_gsm": 0, "width_mm": 0, "category": "核心配件",
            "supplier_code": "S-COMP-001", "moq": 100, "leadtime_days": 30,
            "capacity_per_day": 50, "unit_cost": 580.0, "loss_rate": 0.5, "available_stock": 320,
        },
        {
            "fabric_code": "M-COND-FIN-30", "name": "30平方英寸翅片冷凝器", "composition": "铜管+铝翅片",
            "weight_gsm": 0, "width_mm": 0, "category": "热交换器",
            "supplier_code": "S-HEX-001", "moq": 200, "leadtime_days": 18,
            "capacity_per_day": 200, "unit_cost": 280.0, "loss_rate": 1.0, "available_stock": 850,
        },
        {
            "fabric_code": "M-EVAP-FIN-30", "name": "30平方英寸翅片蒸发器", "composition": "铜管+铝翅片",
            "weight_gsm": 0, "width_mm": 0, "category": "热交换器",
            "supplier_code": "S-HEX-001", "moq": 200, "leadtime_days": 18,
            "capacity_per_day": 200, "unit_cost": 260.0, "loss_rate": 1.0, "available_stock": 780,
        },
        {
            "fabric_code": "M-EEV-15", "name": "15步电子膨胀阀", "composition": "步进电机+阀体",
            "weight_gsm": 0, "width_mm": 0, "category": "阀件",
            "supplier_code": "S-VALVE-001", "moq": 300, "leadtime_days": 15,
            "capacity_per_day": 500, "unit_cost": 95.0, "loss_rate": 0.5, "available_stock": 1200,
        },
        {
            "fabric_code": "M-RF-R410A", "name": "R410A环保冷媒", "composition": "R32/R125 50/50",
            "weight_gsm": 0, "width_mm": 0, "category": "制冷剂",
            "supplier_code": "S-REF-001", "moq": 500, "leadtime_days": 10,
            "capacity_per_day": 2000, "unit_cost": 65.0, "loss_rate": 2.0, "available_stock": 3500,
        },
    ]
    fabric_by_code = {f["fabric_code"]: f for f in fabrics}

    # ── 工程变更 SAMPLING_ORDERS（6 条，复用作 ECN 工程变更单）──
    sampling_orders: list[dict] = []
    ecn_rows = [
        # (suffix, style_code, factory, stage, status, plan_off, actual_off)
        (1, "P-RC-WALL-15", "F-AG-HZ", "ECN-电容升级", "已闭环", -90, -92),
        (2, "P-RC-CAB-30", "F-AG-HZ", "ECN-风叶动平衡", "已闭环", -60, -58),
        (3, "P-CC-VRV-360", "F-AG-SH", "ECN-通讯板固件", "已确认", -30, -32),
        (4, "P-CC-DUCT-50", "F-AG-SH", "ECN-排水盘", "实施中", -10, None),       # 进行中
        (5, "P-CC-CHILL-100", "F-AG-GZ", "ECN-压缩机选型", "待批", 5, None),      # 未到计划日
        (6, "P-RC-MOVE-10", "F-AG-HZ", "ECN-外壳模具", "已确认", -20, -22),
    ]
    for suffix, style_code, factory, stage, status, plan_off, actual_off in ecn_rows:
        plan_date = BASE_DATE + timedelta(days=plan_off)
        actual_date = (BASE_DATE + timedelta(days=actual_off)) if actual_off is not None else None
        if actual_date is not None:
            days_late = max(0, (actual_date - plan_date).days)
        else:
            days_late = max(0, (BASE_DATE - plan_date).days)
        sampling_orders.append({
            "sampling_no": f"ECN20260{suffix:03d}",
            "style_code": style_code,
            "style_name": style_by_code[style_code]["name"],
            "factory": factory,
            "stage": stage,
            "status": status,
            "plan_date": f"{plan_date}",
            "actual_date": f"{actual_date}" if actual_date else None,
            "days_late": days_late,
            "overdue": days_late > 0,
        })
    sampling_order_by_no = {s["sampling_no"]: s for s in sampling_orders}

    # ── 大货单 BULK_ORDERS（6 条，每款 1 条）──
    bulk_orders: list[dict] = []
    bulk_rows = [
        # (suffix, style_code, customer_code, factory, qty, plan_start_off, plan_end_off, actual_end_off, cap, delivery_off, qc_status)
        (1, "P-RC-WALL-15", "C-AG-RETAIL-01", "F-AG-HZ", 500, -25, 5, 3, 30, 10, "PASS"),
        (2, "P-RC-CAB-30", "C-AG-RETAIL-02", "F-AG-HZ", 300, -20, 10, None, 20, 15, "PENDING"),  # 进行中
        (3, "P-RC-MOVE-10", "C-AG-ECOM-01", "F-AG-HZ", 200, -18, 8, 5, 25, 12, "PASS"),
        (4, "P-CC-VRV-360", "C-AG-PROJ-01", "F-AG-SH", 80, -30, 20, None, 5, 25, "PENDING"),    # 进行中
        (5, "P-CC-DUCT-50", "C-AG-PROJ-02", "F-AG-SH", 120, -22, 12, None, 8, 18, "PENDING"),    # 进行中
        (6, "P-CC-CHILL-100", "C-AG-PROJ-03", "F-AG-GZ", 30, -40, 30, None, 3, 40, "PENDING"),   # 进行中
    ]
    for suffix, style_code, customer_code, factory, qty, ps_off, pe_off, ae_off, cap, del_off, qc_status in bulk_rows:
        plan_start = BASE_DATE + timedelta(days=ps_off)
        plan_end = BASE_DATE + timedelta(days=pe_off)
        actual_end = (BASE_DATE + timedelta(days=ae_off)) if ae_off is not None else None
        delivery_date = BASE_DATE + timedelta(days=del_off)
        if actual_end is not None:
            days_late = max(0, (actual_end - plan_end).days)
        else:
            days_late = max(0, (BASE_DATE - plan_end).days)
        bulk_orders.append({
            "bulk_no": f"BLK20260{suffix:03d}",
            "style_code": style_code,
            "style_name": style_by_code[style_code]["name"],
            "customer_code": customer_code,
            "factory": factory,
            "qty": qty,
            "plan_start": f"{plan_start}",
            "plan_end": f"{plan_end}",
            "actual_end": f"{actual_end}" if actual_end else None,
            "capacity_per_day": cap,
            "delivery_date": f"{delivery_date}",
            "qc_status": qc_status,
            "days_late": days_late,
            "overdue": days_late > 0,
        })
    bulk_order_by_no = {b["bulk_no"]: b for b in bulk_orders}

    # ── 质检报告 QC_REPORTS（6 条，每款 1 条）──
    qc_rows = [
        # (suffix, bulk_no, style_code, check_off, aql, sample, defect, pass, summary)
        (1, "BLK2026001", "P-RC-WALL-15", 2, "AQL1.0", 32, 1, True, "外观划痕 1 处，已返修"),
        (2, "BLK2026002", "P-RC-CAB-30", 0, "AQL1.0", 32, 0, True, "合格"),
        (3, "BLK2026003", "P-RC-MOVE-10", -1, "AQL1.0", 32, 2, True, "外壳装配缝隙 2 处，让步接收"),
        (4, "BLK2026004", "P-CC-VRV-360", 12, "AQL0.65", 25, 3, False, "通讯板焊接虚焊 3 处"),
        (5, "BLK2026005", "P-CC-DUCT-50", 5, "AQL1.0", 32, 1, True, "翅片倒片 1 处，已返修"),
        (6, "BLK2026006", "P-CC-CHILL-100", 18, "AQL0.65", 20, 0, True, "合格"),
    ]
    qc_reports: list[dict] = []
    for suffix, bulk_no, style_code, check_off, aql, sample, defect, passed, summary in qc_rows:
        qc_reports.append({
            "qc_no": f"QC20260{suffix:03d}",
            "bulk_no": bulk_no,
            "style_code": style_code,
            "inspector": D.pick(R, ["QC-周", "QC-吴", "QC-郑"]),
            "check_date": f"{BASE_DATE + timedelta(days=check_off)}",
            "aql_level": aql,
            "sample_size": sample,
            "defect_count": defect,
            "pass": passed,
            "defect_summary": summary,
        })

    # ── 故障案例 DEFECT_HISTORY（18 条，覆盖 8 类空调故障 + AG-SVC-01 3 条重点工单）──
    defect_rows = [
        # (case_id, style_code, category, defect_type, severity, root_cause, corrective, avoidance, date_off, work_order_no)
        # AG-SVC-01 重点工单 3 条
        ("DF-AG-2026-001", "P-RC-WALL-15", "家用壁挂", "不制冷", "严重",
         "压缩机启动电容容量衰减（标称 30μF，实测 22μF）",
         "更换 30μF 工业级电容+清洗冷凝器", "电容来料 100% 容量分选", -8, "AWO20260101"),
        ("DF-AG-2026-002", "P-CC-VRV-360", "商用多联机", "通讯故障", "致命",
         "室内外机通讯线接地不良+心跳重连缺失",
         "重新压接通讯线+固件升级增加心跳重连", "通讯接口出厂必做阻抗测试", -6, "AWO20260210"),
        ("DF-AG-2026-003", "P-RC-CAB-30", "家用柜机", "漏水", "严重",
         "蒸发器接水盘排水口堵塞+总装未做排水试漏",
         "清洗接水盘+总装后必做排水试漏 5min", "总装后必做排水试漏 SOP", -5, "AWO20260105"),
        # 其余 15 条覆盖 8 类故障
        ("DF-AG-2026-004", "P-RC-WALL-15", "家用壁挂", "异音", "一般",
         "压缩机减振垫老化", "更换减振垫+紧固螺栓", "总装后必做振动测试", -25, "AWO20260102"),
        ("DF-AG-2026-005", "P-RC-CAB-30", "家用柜机", "异音", "一般",
         "风叶动平衡失调", "重新做动平衡校准", "风叶出厂前 100% 动平衡", -22, "AWO20260106"),
        ("DF-AG-2026-006", "P-RC-MOVE-10", "家用移动", "异音", "一般",
         "外壳螺丝松动", "重新紧固+涂螺纹胶", "总装后必做扭矩抽检", -20, "AWO20260108"),
        ("DF-AG-2026-007", "P-RC-WALL-15", "家用壁挂", "控制板故障", "严重",
         "控制板 MCU 焊接虚焊", "更换控制板+回流焊工艺改进", "PCB 出厂必做 ICT 测试", -18, "AWO20260103"),
        ("DF-AG-2026-008", "P-CC-VRV-360", "商用多联机", "高压保护", "严重",
         "冷凝器翅片积灰+室外机散热不良",
         "清洗冷凝器+安装位置通风改进", "商用机安装必做散热评估", -16, "AWO20260211"),
        ("DF-AG-2026-009", "P-CC-CHILL-100", "商用模块", "高压保护", "严重",
         "冷却水流量不足", "检查水泵+清洗 Y 型过滤器", "模块机调试必做水流量测试", -14, "AWO20260220"),
        ("DF-AG-2026-010", "P-CC-DUCT-50", "商用风管", "冷媒泄漏", "严重",
         "电子膨胀阀焊接点泄漏",
         "补焊+电子检漏仪扫描", "总装后必做氦检漏保压 5min", -12, "AWO20260215"),
        ("DF-AG-2026-011", "P-CC-VRV-360", "商用多联机", "冷媒泄漏", "严重",
         "室内机连接管喇叭口裂纹",
         "更换连接管+重新扩喇叭口", "喇叭口出厂必做气密性测试", -10, "AWO20260212"),
        ("DF-AG-2026-012", "P-RC-CAB-30", "家用柜机", "冷媒泄漏", "严重",
         "蒸发器铜管焊点泄漏", "补焊+检漏", "蒸发器出厂必做水检漏 3min", -8, "AWO20260107"),
        ("DF-AG-2026-013", "P-CC-VRV-360", "商用多联机", "化霜失效", "一般",
         "化霜传感器故障", "更换化霜传感器", "冬季必做化霜功能测试", -6, "AWO20260213"),
        ("DF-AG-2026-014", "P-CC-DUCT-50", "商用风管", "化霜失效", "一般",
         "化霜逻辑参数错误", "升级固件+调整化霜参数", "新机型必做低温工况测试", -5, "AWO20260216"),
        ("DF-AG-2026-015", "P-RC-WALL-15", "家用壁挂", "不制冷", "一般",
         "制冷剂不足（系统泄漏）", "查漏补焊+补 R410A 0.8kg", "出厂必做保压 24h 测试", -3, "AWO20260104"),
        ("DF-AG-2026-016", "P-RC-CAB-30", "家用柜机", "控制板故障", "严重",
         "电源板保险丝烧毁", "更换保险丝+电源板", "电源板出厂必做过流测试", -2, "AWO20260109"),
        ("DF-AG-2026-017", "P-CC-CHILL-100", "商用模块", "通讯故障", "严重",
         "主控板与模块间 CAN 总线故障", "更换主控板+重新配置总线", "模块机组装后必做总线测试", -1, "AWO20260221"),
        ("DF-AG-2026-018", "P-CC-VRV-360", "商用多联机", "漏水", "严重",
         "冷凝水管堵塞", "清洗冷凝水管+排水泵", "商用机必做排水泵测试", 0, "AWO20260214"),
    ]
    defect_history: list[dict] = []
    for case_id, style_code, category, dtype, sev, root, corr, avoid, off, won in defect_rows:
        defect_history.append({
            "case_id": case_id,
            "style_code": style_code,
            "category": category,
            "defect_type": dtype,
            "severity": sev,
            "root_cause": root,
            "corrective_action": corr,
            "avoidance_hint": avoid,
            "date_reported": f"{BASE_DATE + timedelta(days=off)}",
            "work_order_no": won,
        })

    # ── 物料库存 MATERIAL_INVENTORY：每配件一条 ──
    material_inventory: list[dict] = []
    for f in fabrics:
        wh = "WH-AG-COMP" if f["fabric_code"].startswith("M-COMP") else (
            "WH-AG-HEX" if f["fabric_code"].startswith(("M-COND", "M-EVAP")) else (
                "WH-AG-VALVE" if f["fabric_code"].startswith("M-EEV") else "WH-AG-REF"))
        material_inventory.append({
            "material_code": f["fabric_code"],
            "material_name": f["name"],
            "warehouse": wh,
            "stock_qty": f["available_stock"],
            "available_qty": max(0, f["available_stock"] - D.randint(R, 0, 50)),
            "safety_stock": f["moq"],
            "uom": "台" if f["fabric_code"].startswith("M-COMP") else (
                "套" if f["fabric_code"].startswith(("M-COND", "M-EVAP")) else (
                    "只" if f["fabric_code"].startswith("M-EEV") else "kg")),
        })

    # ── 领料流水 PICKINGS（12 条）──
    mes_wos = _mes_work_orders("agileac")
    pickings: list[dict] = []
    picking_specs = [
        # (suffix, bulk_no, style_code, material_code, qty, warehouse, picker, off)
        (1, "BLK2026001", "P-RC-WALL-15", "M-COMP-GT-24K", 500, "WH-AG-COMP", "仓管-陈", -8),
        (2, "BLK2026001", "P-RC-WALL-15", "M-COND-FIN-30", 500, "WH-AG-HEX", "仓管-陈", -8),
        (3, "BLK2026001", "P-RC-WALL-15", "M-EVAP-FIN-30", 500, "WH-AG-HEX", "仓管-陈", -7),
        (4, "BLK2026001", "P-RC-WALL-15", "M-EEV-15", 500, "WH-AG-VALVE", "仓管-陈", -7),
        (5, "BLK2026001", "P-RC-WALL-15", "M-RF-R410A", 400, "WH-AG-REF", "仓管-陈", -6),
        (6, "BLK2026002", "P-RC-CAB-30", "M-COMP-GT-24K", 300, "WH-AG-COMP", "仓管-周", -5),
        (7, "BLK2026003", "P-RC-MOVE-10", "M-COMP-GT-24K", 200, "WH-AG-COMP", "仓管-林", -4),
        (8, "BLK2026004", "P-CC-VRV-360", "M-COMP-GT-24K", 160, "WH-AG-COMP", "仓管-周", -3),
        (9, "BLK2026004", "P-CC-VRV-360", "M-COND-FIN-30", 320, "WH-AG-HEX", "仓管-周", -3),
        (10, "BLK2026004", "P-CC-VRV-360", "M-RF-R410A", 960, "WH-AG-REF", "仓管-周", -2),
        (11, "BLK2026006", "P-CC-CHILL-100", "M-COMP-GT-24K", 120, "WH-AG-COMP", "仓管-邓", -2),
        (12, "BLK2026006", "P-CC-CHILL-100", "M-RF-R410A", 1200, "WH-AG-REF", "仓管-邓", -1),
    ]
    for suffix, bulk_no, style_code, mat_code, qty, wh, picker, off in picking_specs:
        won = mes_wos[(suffix - 1) % len(mes_wos)] if mes_wos else "AWO20260101"
        pickings.append({
            "picking_no": f"PK20260{suffix:03d}",
            "bulk_no": bulk_no,
            "style_code": style_code,
            "material_code": mat_code,
            "qty": qty,
            "uom": "台" if mat_code.startswith("M-COMP") else (
                "套" if mat_code.startswith(("M-COND", "M-EVAP")) else (
                    "只" if mat_code.startswith("M-EEV") else "kg")),
            "warehouse": wh,
            "ref_work_order": won,
            "picker": picker,
            "date": f"{BASE_DATE + timedelta(days=off)}",
        })

    # ── 应付 PAYABLES（6 条，按配件归集）──
    payable_specs = [
        # (suffix, supplier_code, style_code, amount, billing_off, due_off, status)
        (1, "S-COMP-001", "P-RC-WALL-15", 290_000, -45, 5, "未到期"),
        (2, "S-HEX-001", "P-RC-CAB-30", 168_000, -40, -5, "逾期"),
        (3, "S-VALVE-001", "P-RC-WALL-15", 57_000, -35, 10, "未到期"),
        (4, "S-REF-001", "P-CC-VRV-360", 78_000, -30, -2, "逾期"),
        (5, "S-HEX-001", "P-CC-CHILL-100", 224_000, -25, 8, "未到期"),
        (6, "S-COMP-001", "P-CC-DUCT-50", 116_000, -20, 15, "未到期"),
    ]
    payables: list[dict] = []
    for suffix, sup, style_code, amt, b_off, d_off, status in payable_specs:
        due = BASE_DATE + timedelta(days=d_off)
        payables.append({
            "payable_id": f"AGPAP20260{suffix:03d}",
            "supplier_code": sup,
            "style_code": style_code,
            "invoice_no": f"AGINV20260{suffix:03d}",
            "amount": amt, "currency": "CNY",
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": status,
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    # ── 应收 RECEIVABLES（6 条）──
    receivable_specs = [
        # (suffix, customer_code, style_code, amount, billing_off, due_off, status)
        (1, "C-AG-RETAIL-01", "P-RC-WALL-15", 940_000, -25, 20, "未到期"),
        (2, "C-AG-RETAIL-02", "P-RC-CAB-30", 1_104_000, -22, -3, "逾期"),
        (3, "C-AG-ECOM-01", "P-RC-MOVE-10", 256_000, -20, 25, "未到期"),
        (4, "C-AG-PROJ-01", "P-CC-VRV-360", 1_024_000, -18, -1, "逾期"),
        (5, "C-AG-PROJ-02", "P-CC-DUCT-50", 816_000, -15, 30, "未到期"),
        (6, "C-AG-PROJ-03", "P-CC-CHILL-100", 1_164_000, -10, 35, "未到期"),
    ]
    receivables: list[dict] = []
    for suffix, cust, style_code, amt, b_off, d_off, status in receivable_specs:
        due = BASE_DATE + timedelta(days=d_off)
        receivables.append({
            "receivable_id": f"AGAR20260{suffix:03d}",
            "customer_code": cust,
            "style_code": style_code,
            "invoice_no": f"AGARINV20260{suffix:03d}",
            "amount": amt, "currency": "CNY",
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": status,
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    # ── 凭证 VOUCHERS（6 条，含 AG-IT-01 演示用 BV-AG-2026-0512）──
    voucher_specs = [
        # (suffix, period, summary_off, debit, credit, status, voucher_no)
        (1, "2026-04", -70, 290_000, 290_000, "已过账", "BV-AG-2026-0501"),
        (2, "2026-05", -50, 168_000, 168_000, "已过账", "BV-AG-2026-0502"),
        (3, "2026-05", -40, 78_000, 78_000, "已复核", "BV-AG-2026-0503"),
        (4, "2026-06", -8, 6_800, 6_800, "财务复核中", "BV-AG-2026-0512"),  # ← AG-IT-01 Q5 演示凭证
        (5, "2026-06", -5, 224_000, 224_000, "草稿", "BV-AG-2026-0513"),
        (6, "2026-06", -3, 116_000, 116_000, "草稿", "BV-AG-2026-0514"),
    ]
    summaries = ["压缩机采购入库核算", "冷凝器采购入库核算", "R410A 冷媒采购入库核算",
                 "差旅费报销-7月", "模块机冷凝器采购入库", "风管机压缩机采购入库"]
    vouchers: list[dict] = []
    for suffix, period, off, debit, credit, status, vno in voucher_specs:
        vouchers.append({
            "voucher_no": vno,
            "period": period,
            "entry_date": f"{BASE_DATE + timedelta(days=off)}",
            "summary": summaries[suffix - 1],
            "debit_total": debit, "credit_total": credit,
            "status": status,
        })

    # ── 成本台账 COST_LEDGER（10 条）──
    cost_specs = [
        # (suffix, style_code, material_code, period, mat, labor, oh)
        (1, "P-RC-WALL-15", "M-COMP-GT-24K", "2026-04", 580.0, 180.0, 90.0),
        (2, "P-RC-WALL-15", "M-COND-FIN-30", "2026-04", 280.0, 60.0, 30.0),
        (3, "P-RC-WALL-15", "M-EVAP-FIN-30", "2026-04", 260.0, 60.0, 30.0),
        (4, "P-RC-CAB-30", "M-COMP-GT-24K", "2026-05", 580.0, 220.0, 110.0),
        (5, "P-RC-MOVE-10", "M-COMP-GT-24K", "2026-05", 580.0, 150.0, 75.0),
        (6, "P-CC-VRV-360", "M-COMP-GT-24K", "2026-06", 1160.0, 480.0, 240.0),
        (7, "P-CC-VRV-360", "M-COND-FIN-30", "2026-06", 1120.0, 240.0, 120.0),
        (8, "P-CC-DUCT-50", "M-COMP-GT-24K", "2026-06", 580.0, 260.0, 130.0),
        (9, "P-CC-CHILL-100", "M-COMP-GT-24K", "2026-06", 2320.0, 960.0, 480.0),
        (10, "P-CC-CHILL-100", "M-COND-FIN-30", "2026-06", 2240.0, 480.0, 240.0),
    ]
    cost_ledger: list[dict] = []
    for suffix, style_code, mat_code, period, mat, labor, oh in cost_specs:
        cost_ledger.append({
            "ledger_no": f"AGCL20260{suffix:03d}",
            "style_code": style_code,
            "material_code": mat_code,
            "period": period,
            "cost_material": round(mat, 2),
            "cost_labor": round(labor, 2),
            "cost_overhead": round(oh, 2),
            "cost_total": round(mat + labor + oh, 2),
            "updated_at": f"{BASE_DATE + timedelta(days=D.randint(R, -5, 0))}T10:00:00",
        })

    # ── 可行性测算留痕 FEASIBILITY_LOGS（6 条，复用作配件可行性交期测算）──
    feasibility_specs = [
        # (suffix, style_code, fabric_code, supplier, qty, cost_est, leadtime, cap, decision, off)
        (1, "P-RC-WALL-15", "M-COMP-GT-24K", "S-COMP-001", 500, 290_000.0, 30, 50, "通过", -90),
        (2, "P-RC-CAB-30", "M-COMP-GT-24K", "S-COMP-001", 300, 174_000.0, 30, 50, "通过", -80),
        (3, "P-CC-VRV-360", "M-COMP-GT-24K", "S-COMP-001", 160, 92_800.0, 35, 50, "通过-预警交期", -60),
        (4, "P-CC-VRV-360", "M-COND-FIN-30", "S-HEX-001", 320, 89_600.0, 18, 200, "通过", -50),
        (5, "P-CC-CHILL-100", "M-COMP-GT-24K", "S-COMP-001", 120, 69_600.0, 35, 50, "通过", -30),
        (6, "P-CC-CHILL-100", "M-RF-R410A", "S-REF-001", 1200, 78_000.0, 10, 2000, "通过", -20),
    ]
    feasibility_logs: list[dict] = []
    for suffix, style_code, fab_code, sup, qty, cost_est, leadtime, cap, decision, off in feasibility_specs:
        feasibility_logs.append({
            "log_no": f"AGFL20260{suffix:03d}",
            "style_code": style_code,
            "fabric_code": fab_code,
            "supplier_code": sup,
            "qty_requested": qty,
            "cost_estimated": cost_est,
            "leadtime_estimated": leadtime,
            "capacity_available": cap,
            "snapshot_at": f"{BASE_DATE + timedelta(days=off)}T09:00:00",
            "decision": decision,
        })

    return PlmData(
        styles=styles, style_by_code=style_by_code,
        boms=boms, bom_by_style=bom_by_style,
        fabrics=fabrics, fabric_by_code=fabric_by_code,
        sampling_orders=sampling_orders, sampling_order_by_no=sampling_order_by_no,
        bulk_orders=bulk_orders, bulk_order_by_no=bulk_order_by_no,
        qc_reports=qc_reports, defect_history=defect_history,
        material_inventory=material_inventory, pickings=pickings,
        payables=payables, receivables=receivables,
        vouchers=vouchers, cost_ledger=cost_ledger,
        feasibility_logs=feasibility_logs,
    )


# ───────────────────────── agilesteel（敏睿钢铁） ─────────────────────────


def _build_agilesteel() -> PlmData:
    """敏睿钢铁 PLM 数据：钢种主数据(P-ST-) + 钢种质量历史案例(DF-AS-) + 分钢种成本台账。
    钢种码 P-ST- 与 HR 岗位 P- 不同码空间（identifiers.md 消歧）；质量历史按钢种回流，
    下次同钢种开炉规避。服装款相关字段留空（钢铁不用）。"""
    steel_grades = [
        {"grade_code": "P-ST-Q345B", "name": "Q345B 低合金高强钢", "category": "低合金钢",
         "standard": "GB/T 1591", "typical_use": "桥梁/建筑结构/铁塔",
         "carbon_range": "≤0.20%", "yield_strength": "≥345MPa", "status": "量产"},
        {"grade_code": "P-ST-45#", "name": "45# 优质碳素钢", "category": "优质碳素钢",
         "standard": "GB/T 699", "typical_use": "机械零件/齿轮/轴",
         "carbon_range": "0.42-0.50%", "yield_strength": "≥355MPa", "status": "量产"},
        {"grade_code": "P-ST-40Cr", "name": "40Cr 合金结构钢", "category": "合金结构钢",
         "standard": "GB/T 3077", "typical_use": "机械制造/曲轴/连杆",
         "carbon_range": "0.37-0.44%", "yield_strength": "≥785MPa", "status": "量产"},
        {"grade_code": "P-ST-20MnSi", "name": "20MnSi 建筑用钢", "category": "钢筋钢",
         "standard": "GB/T 1499.2", "typical_use": "混凝土结构/螺纹钢",
         "carbon_range": "0.17-0.25%", "yield_strength": "≥400MPa", "status": "量产"},
        {"grade_code": "P-ST-Q235B", "name": "Q235B 普碳钢", "category": "碳素结构钢",
         "standard": "GB/T 700", "typical_use": "普通结构件/型材",
         "carbon_range": "≤0.20%", "yield_strength": "≥235MPa", "status": "量产"},
        {"grade_code": "P-ST-42CrMo", "name": "42CrMo 高性能合金钢", "category": "合金结构钢",
         "standard": "GB/T 3077", "typical_use": "高强度齿轮/风电主轴",
         "carbon_range": "0.38-0.45%", "yield_strength": "≥930MPa", "status": "优特钢"},
    ]
    steel_grade_by_code = {g["grade_code"]: g for g in steel_grades}

    # 钢种质量历史案例（DF-AS-，回流自 MES 表面缺陷，按钢种归集）
    defect_history = [
        {"case_id": "DF-AS-2026001", "style_code": "P-ST-Q345B", "category": "低合金钢",
         "defect_type": "表面裂纹", "severity": "严重", "root_cause": "连铸坯温应力导致裂纹扩展",
         "corrective": "优化二冷配水/提高连铸拉速稳定性",
         "avoidance": "下次同钢种开炉前校核二冷制度", "occurred_at": "2026-05-12", "status": "已闭环"},
        {"case_id": "DF-AS-2026002", "style_code": "P-ST-45#", "category": "优质碳素钢",
         "defect_type": "非金属夹杂", "severity": "严重", "root_cause": "精炼洁净度不足/连铸保护渣卷入",
         "corrective": "提升 RH 真空脱气时间/优化中间包挡墙",
         "avoidance": "洁净钢种延长精炼时间≥15min", "occurred_at": "2026-05-20", "status": "已闭环"},
        {"case_id": "DF-AS-2026003", "style_code": "P-ST-40Cr", "category": "合金结构钢",
         "defect_type": "成分偏析", "severity": "一般", "root_cause": "连铸凝固组织不均",
         "corrective": "调整连铸电磁搅拌参数",
         "avoidance": "合金钢种启用 EMS", "occurred_at": "2026-06-02", "status": "整改中"},
        {"case_id": "DF-AS-2026004", "style_code": "P-ST-20MnSi", "category": "钢筋钢",
         "defect_type": "尺寸超差", "severity": "一般", "root_cause": "轧制孔型磨损",
         "corrective": "更换轧辊/调整张力",
         "avoidance": "批量生产达 2000t 后检查孔型", "occurred_at": "2026-06-08", "status": "已闭环"},
        {"case_id": "DF-AS-2026005", "style_code": "P-ST-42CrMo", "category": "合金结构钢",
         "defect_type": "力学性能不达标", "severity": "严重", "root_cause": "终轧温度/冷却制度偏差",
         "corrective": "优化控冷工艺/调整终轧温度",
         "avoidance": "高性能钢种按控冷曲线执行", "occurred_at": "2026-06-15", "status": "整改中"},
        {"case_id": "DF-AS-2026006", "style_code": "P-ST-Q345B", "category": "低合金钢",
         "defect_type": "氧化铁皮", "severity": "一般", "root_cause": "加热炉氧化严重/除鳞不净",
         "corrective": "提高除鳞水压/缩短加热时间",
         "avoidance": "定期校核除鳞压力", "occurred_at": "2026-06-20", "status": "已闭环"},
    ]

    # 分钢种成本台账（FIN-01 getCostLedger，style_code 即钢种码 P-ST-）
    cost_ledger = [
        {"ledger_id": "CL-AS-202606-Q345B", "style_code": "P-ST-Q345B",
         "material_code": "M-ST-Q345B-Bar", "period": "2026-06",
         "unit_cost": 4280.0, "cost_breakdown": "铁水62%+废钢18%+合金5%+能耗10%+人工5%",
         "updated_at": "2026-06-29"},
        {"ledger_id": "CL-AS-202606-45", "style_code": "P-ST-45#",
         "material_code": "M-ST-45-Bar", "period": "2026-06",
         "unit_cost": 4650.0, "cost_breakdown": "铁水58%+废钢22%+合金6%+能耗9%+人工5%",
         "updated_at": "2026-06-29"},
        {"ledger_id": "CL-AS-202606-40Cr", "style_code": "P-ST-40Cr",
         "material_code": "M-ST-40Cr-Bar", "period": "2026-06",
         "unit_cost": 5280.0, "cost_breakdown": "铁水55%+废钢20%+合金12%+能耗8%+人工5%",
         "updated_at": "2026-06-29"},
        {"ledger_id": "CL-AS-202606-42CrMo", "style_code": "P-ST-42CrMo",
         "material_code": "M-ST-42CrMo-Bar", "period": "2026-06",
         "unit_cost": 6800.0, "cost_breakdown": "铁水50%+废钢18%+合金18%+能耗9%+人工5%",
         "updated_at": "2026-06-29"},
    ]

    return PlmData(
        styles=[], style_by_code={}, boms=[], bom_by_style={},
        fabrics=[], fabric_by_code={},
        sampling_orders=[], sampling_order_by_no={},
        bulk_orders=[], bulk_order_by_no={},
        qc_reports=[], defect_history=defect_history,
        material_inventory=[], pickings=[],
        payables=[], receivables=[],
        vouchers=[], cost_ledger=cost_ledger, feasibility_logs=[],
        steel_grades=steel_grades, steel_grade_by_code=steel_grade_by_code,
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[PlmData]({
    "starclothing": _build_starclothing,
    "agileac": _build_agileac,
    "agilesteel": _build_agilesteel,
})


def load(tenant: str) -> PlmData:
    """按 tenant 取数据集；首次调用时触发构建并缓存。PLM 仅支持 starclothing。"""
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()
