"""SCM 多租户确定性种子数据——starclothing（星图服装）。

固定种子 + 固定基准日，重启可复现。每个 tenant 一份 ``ScmData``，覆盖供应商 /
报价单（多家对比）/ 产能日历 / 面料到货计划 / 补单节奏建议 / 交期快照 / 物料校验。

SCM 是叶系统（其他 mock 不引用 SCM），无循环依赖，但仍用 ``LazyTenantRegistry``
保持与 ERP/MES/CRM 一致的懒构建模式。``LazyTenantRegistry`` 仅含 starclothing。

供应商编码与 ERP starclothing suppliers 对齐（XS-FAB-001/002/003、XS-ACC-010/011/020、
XS-PRT-030、XS-WSH-031、XS-PKG-040），新增产能/起订/主营字段；另补 1 家面料
供应商 XS-FAB-004 以支撑「双面呢 360g」4 家比价（SC-4）。

物料编码引用 ERP starclothing materials（M-WOOL-DBL-360 / M-ZIP-YKK-5 等），
工单号引用 MES starclothing work_orders，采购单号引用 ERP starclothing purchase_orders。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry, TenantBuilding

BASE_DATE: date = date(2026, 6, 29)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class ScmData:
    suppliers: list[dict]
    supplier_by_code: dict[str, dict]
    quotations: list[dict]                       # 供应商报价单（按面料/规格多家对比）
    quotation_by_no: dict[str, dict]
    capacity_calendar: list[dict]               # 供应商产能日历（按工厂/日期/占用率）
    fabric_arrival_plans: list[dict]            # 面料在途到货计划
    replenishment_suggestions: list[dict]       # 补单节奏建议
    leadtime_snapshots: list[dict]              # 交期快照（用于"实时交期异动检测"）
    material_validations: list[dict]            # 物料校验记录（双向：工厂端/我方端）
    scrap_grades: list[dict] = field(default_factory=list)        # 废钢分级（agilesteel）
    scrap_grade_by_code: dict[str, dict] = field(default_factory=dict)


# ───────────────────────── 跨系统取数（同 tenant） ─────────────────────────


def _mes_work_orders(tenant: str) -> list[str]:
    """跨系统取同 tenant 的 MES 工单号；MES 未就绪或循环构造中时回退占位。"""
    try:
        from mock.systems.mes.data import load as _load_mes
        d = _load_mes(tenant)
        return [w["work_order_no"] for w in d.work_orders]
    except (Exception, TenantBuilding):  # noqa: BLE001
        return ["WO20260607"]


def _erp_purchase_orders(tenant: str) -> list[str]:
    """跨系统取同 tenant 的 ERP 采购单号；未就绪时回退占位。"""
    try:
        from mock.systems.erp.data import load as _load_erp
        d = _load_erp(tenant)
        return [p["po_no"] for p in d.purchase_orders]
    except (Exception, TenantBuilding):  # noqa: BLE001
        return ["XPO20260007"]


# ───────────────────────── starclothing（服装供应链） ─────────────────────────


def _build_starclothing() -> ScmData:
    """星图服装供应链口径数据：供应商/报价/产能/到货/补单/交期/校验。"""
    R = D.rng(20241210)

    suppliers = [
        {"code": "XS-FAB-001", "name": "绍兴盛峰纺织", "category": "面料",
         "contact": "陈布料", "phone": "13900001111", "payment_terms_days": 45,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 800, "moq": 500, "specialty": "双面呢/羊毛"},
        {"code": "XS-FAB-002", "name": "吴江恒宇面料", "category": "面料",
         "contact": "林面料", "phone": "13900002222", "payment_terms_days": 30,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 2000, "moq": 1000, "specialty": "T/C 布/衬布"},
        {"code": "XS-FAB-003", "name": "桐乡羊毛纺织", "category": "面料",
         "contact": "沈羊绒", "phone": "13900003333", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 500, "moq": 300, "specialty": "羊绒/羊毛混纺"},
        {"code": "XS-FAB-004", "name": "张家港华纺毛纺", "category": "面料",
         "contact": "顾毛纺", "phone": "13900001234", "payment_terms_days": 45,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 1200, "moq": 600, "specialty": "羊毛/双面呢"},
        {"code": "XS-ACC-010", "name": "YKK 拉链（深圳）", "category": "辅料",
         "contact": "赵辅料", "phone": "13900004444", "payment_terms_days": 30,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 50000, "moq": 5000, "specialty": "拉链"},
        {"code": "XS-ACC-011", "name": "福建浔兴拉链", "category": "辅料",
         "contact": "施拉链", "phone": "13900005555", "payment_terms_days": 60,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 80000, "moq": 10000, "specialty": "拉链"},
        {"code": "XS-ACC-020", "name": "温州纽扣五金", "category": "辅料",
         "contact": "胡纽扣", "phone": "13900006666", "payment_terms_days": 45,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 30000, "moq": 5000, "specialty": "纽扣/撞针"},
        {"code": "XS-PRT-030", "name": "广州印花外协", "category": "外协",
         "contact": "潘印花", "phone": "13900007777", "payment_terms_days": 30,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 2000, "moq": 500, "specialty": "丝网印花"},
        {"code": "XS-WSH-031", "name": "东莞水洗厂", "category": "外协",
         "contact": "邓水洗", "phone": "13900008888", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 1500, "moq": 500, "specialty": "水洗"},
        {"code": "XS-PKG-040", "name": "苏州包装制品", "category": "辅料包装",
         "contact": "周包装", "phone": "13900009999", "payment_terms_days": 60,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 10000, "moq": 1000, "specialty": "胶袋/纸箱"},
    ]
    supplier_by_code = {s["code"]: s for s in suppliers}

    # ── 报价单 QUOTATIONS（17 条，含双面呢 4 家 + YKK 5# 拉链 3 家对比） ──
    quotations = [
        # 双面呢 360g（M-WOOL-DBL-360）4 家对比
        {"quotation_no": "Q202607001", "supplier_code": "XS-FAB-001", "supplier_name": "绍兴盛峰纺织",
         "material_code": "M-WOOL-DBL-360", "material_name": "双面呢 360g/㎡ 30%羊绒 70%羊毛",
         "spec": "360g/㎡ 30%羊绒 70%羊毛 门幅150cm", "unit_price": 178.0, "moq": 500,
         "leadtime_days": 25, "payment_terms_days": 45, "valid_until": "2026-08-15",
         "status": "有效", "submitted_at": "2026-06-20T09:30:00"},
        {"quotation_no": "Q202607002", "supplier_code": "XS-FAB-002", "supplier_name": "吴江恒宇面料",
         "material_code": "M-WOOL-DBL-360", "material_name": "双面呢 360g/㎡ 30%羊绒 70%羊毛",
         "spec": "360g/㎡ 30%羊绒 70%羊毛 门幅150cm", "unit_price": 165.0, "moq": 800,
         "leadtime_days": 20, "payment_terms_days": 30, "valid_until": "2026-08-10",
         "status": "有效", "submitted_at": "2026-06-18T14:00:00"},
        {"quotation_no": "Q202607003", "supplier_code": "XS-FAB-003", "supplier_name": "桐乡羊毛纺织",
         "material_code": "M-WOOL-DBL-360", "material_name": "双面呢 360g/㎡ 30%羊绒 70%羊毛",
         "spec": "360g/㎡ 30%羊绒 70%羊毛 门幅150cm", "unit_price": 195.0, "moq": 300,
         "leadtime_days": 30, "payment_terms_days": 30, "valid_until": "2026-08-20",
         "status": "有效", "submitted_at": "2026-06-22T10:00:00"},
        {"quotation_no": "Q202607004", "supplier_code": "XS-FAB-004", "supplier_name": "张家港华纺毛纺",
         "material_code": "M-WOOL-DBL-360", "material_name": "双面呢 360g/㎡ 30%羊绒 70%羊毛",
         "spec": "360g/㎡ 30%羊绒 70%羊毛 门幅150cm", "unit_price": 172.0, "moq": 600,
         "leadtime_days": 28, "payment_terms_days": 45, "valid_until": "2026-08-18",
         "status": "有效", "submitted_at": "2026-06-21T11:00:00"},
        # YKK 5# 拉链（M-ZIP-YKK-5）3 家对比
        {"quotation_no": "Q202607010", "supplier_code": "XS-ACC-010", "supplier_name": "YKK 拉链（深圳）",
         "material_code": "M-ZIP-YKK-5", "material_name": "YKK 5# 树脂拉链 3:1 双开",
         "spec": "5# 树脂 3:1 双开 长度按订单", "unit_price": 6.8, "moq": 5000,
         "leadtime_days": 15, "payment_terms_days": 30, "valid_until": "2026-08-10",
         "status": "有效", "submitted_at": "2026-06-19T09:00:00"},
        {"quotation_no": "Q202607011", "supplier_code": "XS-ACC-011", "supplier_name": "福建浔兴拉链",
         "material_code": "M-ZIP-YKK-5", "material_name": "YKK 5# 树脂拉链 3:1 双开（替代料）",
         "spec": "5# 树脂 3:1 双开 浔兴等同规格", "unit_price": 4.5, "moq": 8000,
         "leadtime_days": 12, "payment_terms_days": 60, "valid_until": "2026-08-05",
         "status": "有效", "submitted_at": "2026-06-20T15:00:00"},
        {"quotation_no": "Q202607012", "supplier_code": "XS-ACC-020", "supplier_name": "温州纽扣五金",
         "material_code": "M-ZIP-YKK-5", "material_name": "YKK 5# 树脂拉链 3:1 双开（渠道货）",
         "spec": "5# 树脂 3:1 双开 渠道采购等同规格", "unit_price": 5.2, "moq": 5000,
         "leadtime_days": 18, "payment_terms_days": 45, "valid_until": "2026-07-25",
         "status": "有效", "submitted_at": "2026-06-21T16:00:00"},
        # 其他物料报价
        {"quotation_no": "Q202606015", "supplier_code": "XS-FAB-001", "supplier_name": "绍兴盛峰纺织",
         "material_code": "M-SHELL-3L-150", "material_name": "三层复合面料 150D 防水透气膜",
         "spec": "150D 三层复合 防水透气膜 门幅148cm", "unit_price": 95.0, "moq": 500,
         "leadtime_days": 22, "payment_terms_days": 45, "valid_until": "2026-08-10",
         "status": "有效", "submitted_at": "2026-06-17T10:00:00"},
        {"quotation_no": "Q202606016", "supplier_code": "XS-FAB-002", "supplier_name": "吴江恒宇面料",
         "material_code": "M-SHELL-3L-150", "material_name": "三层复合面料 150D 防水透气膜",
         "spec": "150D 三层复合 防水透气膜 门幅148cm", "unit_price": 88.0, "moq": 1000,
         "leadtime_days": 18, "payment_terms_days": 30, "valid_until": "2026-08-05",
         "status": "有效", "submitted_at": "2026-06-16T13:00:00"},
        {"quotation_no": "Q202606017", "supplier_code": "XS-FAB-002", "supplier_name": "吴江恒宇面料",
         "material_code": "M-TC-180", "material_name": "T/C 布 65/35 180g 平纹",
         "spec": "65/35 180g 平纹 门幅160cm", "unit_price": 18.0, "moq": 1000,
         "leadtime_days": 10, "payment_terms_days": 30, "valid_until": "2026-08-01",
         "status": "有效", "submitted_at": "2026-06-15T09:00:00"},
        {"quotation_no": "Q202606018", "supplier_code": "XS-FAB-001", "supplier_name": "绍兴盛峰纺织",
         "material_code": "M-TC-180", "material_name": "T/C 布 65/35 180g 平纹",
         "spec": "65/35 180g 平纹 门幅160cm", "unit_price": 19.5, "moq": 800,
         "leadtime_days": 14, "payment_terms_days": 45, "valid_until": "2026-07-28",
         "status": "有效", "submitted_at": "2026-06-14T11:00:00"},
        {"quotation_no": "Q202606019", "supplier_code": "XS-FAB-001", "supplier_name": "绍兴盛峰纺织",
         "material_code": "M-FLEECE-280", "material_name": "摇粒绒 280g 抓绒",
         "spec": "280g 抓绒 门幅150cm", "unit_price": 36.0, "moq": 400,
         "leadtime_days": 16, "payment_terms_days": 45, "valid_until": "2026-08-10",
         "status": "有效", "submitted_at": "2026-06-13T10:00:00"},
        {"quotation_no": "Q202606023", "supplier_code": "XS-FAB-002", "supplier_name": "吴江恒宇面料",
         "material_code": "M-FLEECE-280", "material_name": "摇粒绒 280g 抓绒",
         "spec": "280g 抓绒 门幅150cm", "unit_price": 33.0, "moq": 600,
         "leadtime_days": 16, "payment_terms_days": 30, "valid_until": "2026-08-12",
         "status": "有效", "submitted_at": "2026-06-13T11:00:00"},
        {"quotation_no": "Q202606020", "supplier_code": "XS-ACC-011", "supplier_name": "福建浔兴拉链",
         "material_code": "M-ZIP-XJ-3", "material_name": "浔兴 3# 尼龙拉链 单开",
         "spec": "3# 尼龙 单开 长度按订单", "unit_price": 1.2, "moq": 10000,
         "leadtime_days": 10, "payment_terms_days": 60, "valid_until": "2026-08-01",
         "status": "有效", "submitted_at": "2026-06-12T14:00:00"},
        {"quotation_no": "Q202606021", "supplier_code": "XS-ACC-020", "supplier_name": "温州纽扣五金",
         "material_code": "M-BTN-RESIN", "material_name": "树脂四眼纽扣 18L",
         "spec": "18L 树脂四眼 颜色按订单", "unit_price": 0.45, "moq": 5000,
         "leadtime_days": 12, "payment_terms_days": 45, "valid_until": "2026-08-05",
         "status": "有效", "submitted_at": "2026-06-11T09:00:00"},
        {"quotation_no": "Q202606022", "supplier_code": "XS-FAB-002", "supplier_name": "吴江恒宇面料",
         "material_code": "M-INTER-030", "material_name": "30D 有光衬 18g/㎡",
         "spec": "30D 有光衬 18g/㎡ 门幅150cm", "unit_price": 2.8, "moq": 800,
         "leadtime_days": 12, "payment_terms_days": 30, "valid_until": "2026-08-01",
         "status": "有效", "submitted_at": "2026-06-10T10:00:00"},
        {"quotation_no": "Q202606023", "supplier_code": "XS-PKG-040", "supplier_name": "苏州包装制品",
         "material_code": "M-PKG-POLY", "material_name": "PE 平口袋 30×40",
         "spec": "30×40 PE 平口袋", "unit_price": 0.18, "moq": 1000,
         "leadtime_days": 7, "payment_terms_days": 60, "valid_until": "2026-07-30",
         "status": "有效", "submitted_at": "2026-06-12T09:00:00"},
        {"quotation_no": "Q202606024", "supplier_code": "XS-PKG-040", "supplier_name": "苏州包装制品",
         "material_code": "M-PKG-CTN", "material_name": "5 层瓦楞纸箱 50×35×30",
         "spec": "5 层瓦楞 50×35×30", "unit_price": 4.2, "moq": 200,
         "leadtime_days": 10, "payment_terms_days": 60, "valid_until": "2026-08-01",
         "status": "已下单", "submitted_at": "2026-06-09T10:00:00"},
        # 已过期报价（用于历史对照）
        {"quotation_no": "Q202605010", "supplier_code": "XS-FAB-003", "supplier_name": "桐乡羊毛纺织",
         "material_code": "M-WOOL-DBL-360", "material_name": "双面呢 360g/㎡ 30%羊绒 70%羊毛",
         "spec": "360g/㎡ 30%羊绒 70%羊毛 门幅150cm", "unit_price": 188.0, "moq": 300,
         "leadtime_days": 35, "payment_terms_days": 30, "valid_until": "2026-06-15",
         "status": "已过期", "submitted_at": "2026-05-10T10:00:00"},
        {"quotation_no": "Q202605011", "supplier_code": "XS-ACC-010", "supplier_name": "YKK 拉链（深圳）",
         "material_code": "M-ZIP-YKK-5", "material_name": "YKK 5# 树脂拉链 3:1 双开",
         "spec": "5# 树脂 3:1 双开 长度按订单", "unit_price": 7.2, "moq": 5000,
         "leadtime_days": 18, "payment_terms_days": 30, "valid_until": "2026-06-20",
         "status": "已过期", "submitted_at": "2026-05-12T10:00:00"},
    ]
    quotation_by_no = {q["quotation_no"]: q for q in quotations}

    # ── 产能日历 CAPACITY_CALENDAR（按工厂+日期，含满载/空闲对比） ──
    capacity_calendar: list[dict] = []
    full_load_suppliers = {"XS-FAB-003", "XS-WSH-031"}      # 满载 utilization > 90%
    idle_suppliers = {"XS-FAB-002", "XS-PKG-040"}            # 空闲 utilization < 50%
    entry_seq = 1
    for sup in suppliers:
        cap = sup["capacity_per_day"]
        # 每供应商 3-4 天，分布在 BASE_DATE 前 7 天到后 13 天
        offsets = sorted(D.sample(R, list(range(-7, 14)), D.randint(R, 3, 4)))
        for off in offsets:
            d = BASE_DATE + timedelta(days=off)
            if sup["code"] in full_load_suppliers:
                util = D.randfloat(R, 0.88, 0.98)
            elif sup["code"] in idle_suppliers:
                util = D.randfloat(R, 0.25, 0.48)
            else:
                util = D.randfloat(R, 0.55, 0.85)
            used = int(cap * util)
            available = max(0, cap - used)
            capacity_calendar.append({
                "entry_id": f"CC{D.pad(entry_seq)}",
                "supplier_code": sup["code"], "supplier_name": sup["name"],
                "date": f"{d}", "total_capacity": cap, "used": used,
                "available": available, "utilization_pct": round(util * 100, 1),
                "uom": sup["specialty"].split("/")[0] if sup["category"] in ("面料",) else
                       ("条" if "拉链" in sup["specialty"] else
                        ("粒" if "纽扣" in sup["specialty"] else
                         ("件" if "水洗" in sup["specialty"] else "个"))),
            })
            entry_seq += 1

    # ── 面料到货计划 FABRIC_ARRIVAL_PLANS（含 3 条延误） ──
    fabric_arrival_plans = [
        {"plan_id": "FAP-001", "supplier_code": "XS-FAB-001", "supplier_name": "绍兴盛峰纺织",
         "material_code": "M-WOOL-DBL-360", "po_ref": "XPO20260113", "qty": 1500, "uom": "m",
         "ship_date": "2026-06-22", "eta": "2026-06-28", "status": "已到货", "delay_days": 0},
        {"plan_id": "FAP-002", "supplier_code": "XS-FAB-003", "supplier_name": "桐乡羊毛纺织",
         "material_code": "M-WOOL-DBL-360", "po_ref": "XPO20260166", "qty": 800, "uom": "m",
         "ship_date": "2026-06-25", "eta": "2026-07-06", "status": "延误", "delay_days": 4},
        {"plan_id": "FAP-003", "supplier_code": "XS-FAB-002", "supplier_name": "吴江恒宇面料",
         "material_code": "M-TC-180", "po_ref": "XPO20260219", "qty": 3000, "uom": "m",
         "ship_date": "2026-06-26", "eta": "2026-07-01", "status": "已到货", "delay_days": 0},
        {"plan_id": "FAP-004", "supplier_code": "XS-FAB-001", "supplier_name": "绍兴盛峰纺织",
         "material_code": "M-SHELL-3L-150", "po_ref": "XPO20260272", "qty": 1200, "uom": "m",
         "ship_date": "2026-06-27", "eta": "2026-07-04", "status": "在途", "delay_days": 0},
        {"plan_id": "FAP-005", "supplier_code": "XS-ACC-010", "supplier_name": "YKK 拉链（深圳）",
         "material_code": "M-ZIP-YKK-5", "po_ref": "XPO20260325", "qty": 8000, "uom": "条",
         "ship_date": "2026-06-28", "eta": "2026-07-03", "status": "已到货", "delay_days": 0},
        {"plan_id": "FAP-006", "supplier_code": "XS-ACC-011", "supplier_name": "福建浔兴拉链",
         "material_code": "M-ZIP-XJ-3", "po_ref": "XPO20260378", "qty": 15000, "uom": "条",
         "ship_date": "2026-06-29", "eta": "2026-07-06", "status": "在途", "delay_days": 0},
        {"plan_id": "FAP-007", "supplier_code": "XS-FAB-002", "supplier_name": "吴江恒宇面料",
         "material_code": "M-INTER-030", "po_ref": "XPO20260378", "qty": 2000, "uom": "m",
         "ship_date": "2026-06-20", "eta": "2026-07-02", "status": "延误", "delay_days": 6},
        {"plan_id": "FAP-008", "supplier_code": "XS-ACC-020", "supplier_name": "温州纽扣五金",
         "material_code": "M-BTN-RESIN", "po_ref": "XPO20260325", "qty": 12000, "uom": "粒",
         "ship_date": "2026-06-30", "eta": "2026-07-05", "status": "在途", "delay_days": 0},
        {"plan_id": "FAP-009", "supplier_code": "XS-FAB-001", "supplier_name": "绍兴盛峰纺织",
         "material_code": "M-FLEECE-280", "po_ref": "XPO20260113", "qty": 1000, "uom": "m",
         "ship_date": "2026-07-01", "eta": "2026-07-07", "status": "在途", "delay_days": 0},
        {"plan_id": "FAP-010", "supplier_code": "XS-PKG-040", "supplier_name": "苏州包装制品",
         "material_code": "M-PKG-CTN", "po_ref": "XPO20260378", "qty": 600, "uom": "个",
         "ship_date": "2026-06-25", "eta": "2026-06-30", "status": "已到货", "delay_days": 0},
        {"plan_id": "FAP-011", "supplier_code": "XS-PRT-030", "supplier_name": "广州印花外协",
         "material_code": "M-SHELL-3L-150", "po_ref": "XPO20260272", "qty": 800, "uom": "m",
         "ship_date": "2026-06-28", "eta": "2026-07-08", "status": "延误", "delay_days": 3},
        {"plan_id": "FAP-012", "supplier_code": "XS-FAB-003", "supplier_name": "桐乡羊毛纺织",
         "material_code": "M-WOOL-DBL-360", "po_ref": "XPO20260166", "qty": 500, "uom": "m",
         "ship_date": "2026-07-02", "eta": "2026-07-10", "status": "在途", "delay_days": 0},
    ]

    # ── 补单节奏建议 REPLENISHMENT_SUGGESTIONS（6 条） ──
    replenishment_suggestions = [
        {"suggestion_id": "SUG-001", "style_code": "P-FW2026-001", "bulk_no": "BLK20260001",
         "total_qty": 3000, "first_batch_qty": 1200, "first_batch_date": "2026-07-05",
         "replenish_1_qty": 1000, "replenish_1_date": "2026-07-15",
         "replenish_2_qty": 800, "replenish_2_date": "2026-07-25",
         "fabric_arrival_date": "2026-06-28",
         "factory_capacity_note": "F-XT-HZ 车缝车间 7/5-7/8 可用产能 1200 件",
         "risks": ["面料 FAP-002 延误 4 天，首批 7/5 可能推迟至 7/9"]},
        {"suggestion_id": "SUG-002", "style_code": "P-FW2026-002", "bulk_no": "BLK20260002",
         "total_qty": 2000, "first_batch_qty": 800, "first_batch_date": "2026-07-08",
         "replenish_1_qty": 700, "replenish_1_date": "2026-07-18",
         "replenish_2_qty": 500, "replenish_2_date": "2026-07-28",
         "fabric_arrival_date": "2026-07-01",
         "factory_capacity_note": "F-XT-HZ 车缝车间 7/8-7/10 可用产能 800 件",
         "risks": ["XS-FAB-003 产能满载，补 2 面料可能需调 XS-FAB-004"]},
        {"suggestion_id": "SUG-003", "style_code": "P-AP2026-030", "bulk_no": "BLK20260003",
         "total_qty": 5000, "first_batch_qty": 2000, "first_batch_date": "2026-07-06",
         "replenish_1_qty": 1800, "replenish_1_date": "2026-07-16",
         "replenish_2_qty": 1200, "replenish_2_date": "2026-07-26",
         "fabric_arrival_date": "2026-07-01",
         "factory_capacity_note": "F-XT-HZ 车缝车间 7/6-7/9 可用产能 2000 件",
         "risks": []},
        {"suggestion_id": "SUG-004", "style_code": "P-SS2026-011", "bulk_no": "BLK20260004",
         "total_qty": 1500, "first_batch_qty": 600, "first_batch_date": "2026-07-04",
         "replenish_1_qty": 500, "replenish_1_date": "2026-07-14",
         "replenish_2_qty": 400, "replenish_2_date": "2026-07-22",
         "fabric_arrival_date": "2026-06-30",
         "factory_capacity_note": "F-XT-SZ 车缝车间 7/4-7/6 可用产能 600 件",
         "risks": ["摇粒绒 FAP-009 在途，7/7 到货前不可超额投产"]},
        {"suggestion_id": "SUG-005", "style_code": "P-SS2026-010", "bulk_no": "BLK20260005",
         "total_qty": 1200, "first_batch_qty": 500, "first_batch_date": "2026-07-10",
         "replenish_1_qty": 400, "replenish_1_date": "2026-07-20",
         "replenish_2_qty": 300, "replenish_2_date": "2026-07-30",
         "fabric_arrival_date": "2026-07-04",
         "factory_capacity_note": "F-XT-SZ 车缝车间 7/10-7/12 可用产能 500 件",
         "risks": ["三层复合面料印花 FAP-011 延误 3 天，首批面料 7/8 才齐"]},
        {"suggestion_id": "SUG-006", "style_code": "XT-DS2026-001", "bulk_no": "BULK-006",
         "total_qty": 1800, "first_batch_qty": 700, "first_batch_date": "2026-07-12",
         "replenish_1_qty": 600, "replenish_1_date": "2026-07-22",
         "replenish_2_qty": 500, "replenish_2_date": "2026-08-01",
         "fabric_arrival_date": "2026-07-06",
         "factory_capacity_note": "车缝车间 7/12-7/14 可用产能 700 件",
         "risks": ["XS-FAB-003 产能满载且交期异动 +15 天，建议改派 XS-FAB-002"]},
    ]

    # ── 交期快照 LEADTIME_SNAPSHOTS（含 3 组初测→复测异动） ──
    leadtime_snapshots = [
        # M-WOOL-DBL-360 / XS-FAB-001：25 → 32（Δ +7）
        {"snapshot_id": "LS-001", "material_code": "M-WOOL-DBL-360", "supplier_code": "XS-FAB-001",
         "leadtime_days": 25, "captured_at": "2026-06-10", "snapshot_at": "2026-06-10T09:00:00",
         "source": "初测"},
        {"snapshot_id": "LS-002", "material_code": "M-WOOL-DBL-360", "supplier_code": "XS-FAB-001",
         "leadtime_days": 32, "captured_at": "2026-06-25", "snapshot_at": "2026-06-25T14:00:00",
         "source": "复测"},
        # M-WOOL-DBL-360 / XS-FAB-003：30 → 45（Δ +15）—— PD-2 关键异动
        {"snapshot_id": "LS-003", "material_code": "M-WOOL-DBL-360", "supplier_code": "XS-FAB-003",
         "leadtime_days": 30, "captured_at": "2026-06-12", "snapshot_at": "2026-06-12T10:00:00",
         "source": "初测"},
        {"snapshot_id": "LS-004", "material_code": "M-WOOL-DBL-360", "supplier_code": "XS-FAB-003",
         "leadtime_days": 45, "captured_at": "2026-06-26", "snapshot_at": "2026-06-26T15:00:00",
         "source": "复测"},
        # M-ZIP-YKK-5 / XS-ACC-010：15 → 18（Δ +3）
        {"snapshot_id": "LS-005", "material_code": "M-ZIP-YKK-5", "supplier_code": "XS-ACC-010",
         "leadtime_days": 15, "captured_at": "2026-06-11", "snapshot_at": "2026-06-11T09:30:00",
         "source": "初测"},
        {"snapshot_id": "LS-006", "material_code": "M-ZIP-YKK-5", "supplier_code": "XS-ACC-010",
         "leadtime_days": 18, "captured_at": "2026-06-27", "snapshot_at": "2026-06-27T11:00:00",
         "source": "复测"},
        # M-TC-180 / XS-FAB-002：10 → 12（Δ +2）
        {"snapshot_id": "LS-007", "material_code": "M-TC-180", "supplier_code": "XS-FAB-002",
         "leadtime_days": 10, "captured_at": "2026-06-10", "snapshot_at": "2026-06-10T08:00:00",
         "source": "初测"},
        {"snapshot_id": "LS-008", "material_code": "M-TC-180", "supplier_code": "XS-FAB-002",
         "leadtime_days": 12, "captured_at": "2026-06-24", "snapshot_at": "2026-06-24T10:00:00",
         "source": "复测"},
        # M-WOOL-DBL-360 / XS-FAB-002（compareQuotations 首选）：20 → 25（Δ +5）
        {"snapshot_id": "LS-013", "material_code": "M-WOOL-DBL-360", "supplier_code": "XS-FAB-002",
         "leadtime_days": 20, "captured_at": "2026-06-11", "snapshot_at": "2026-06-11T09:00:00",
         "source": "初测"},
        {"snapshot_id": "LS-014", "material_code": "M-WOOL-DBL-360", "supplier_code": "XS-FAB-002",
         "leadtime_days": 25, "captured_at": "2026-06-26", "snapshot_at": "2026-06-26T11:00:00",
         "source": "复测"},
        # M-SHELL-3L-150 / XS-FAB-002（compareQuotations 首选）：18 → 22（Δ +4）
        {"snapshot_id": "LS-015", "material_code": "M-SHELL-3L-150", "supplier_code": "XS-FAB-002",
         "leadtime_days": 18, "captured_at": "2026-06-12", "snapshot_at": "2026-06-12T09:00:00",
         "source": "初测"},
        {"snapshot_id": "LS-016", "material_code": "M-SHELL-3L-150", "supplier_code": "XS-FAB-002",
         "leadtime_days": 22, "captured_at": "2026-06-27", "snapshot_at": "2026-06-27T10:00:00",
         "source": "复测"},
        # M-FLEECE-280 / XS-FAB-002（compareQuotations 首选）：16 → 20（Δ +4）
        {"snapshot_id": "LS-017", "material_code": "M-FLEECE-280", "supplier_code": "XS-FAB-002",
         "leadtime_days": 16, "captured_at": "2026-06-13", "snapshot_at": "2026-06-13T09:00:00",
         "source": "初测"},
        {"snapshot_id": "LS-018", "material_code": "M-FLEECE-280", "supplier_code": "XS-FAB-002",
         "leadtime_days": 20, "captured_at": "2026-06-28", "snapshot_at": "2026-06-28T10:00:00",
         "source": "复测"},
        # 单快照
        {"snapshot_id": "LS-009", "material_code": "M-SHELL-3L-150", "supplier_code": "XS-FAB-001",
         "leadtime_days": 22, "captured_at": "2026-06-13", "snapshot_at": "2026-06-13T09:00:00",
         "source": "初测"},
        {"snapshot_id": "LS-010", "material_code": "M-FLEECE-280", "supplier_code": "XS-FAB-001",
         "leadtime_days": 16, "captured_at": "2026-06-14", "snapshot_at": "2026-06-14T09:00:00",
         "source": "初测"},
        {"snapshot_id": "LS-011", "material_code": "M-INTER-030", "supplier_code": "XS-FAB-002",
         "leadtime_days": 12, "captured_at": "2026-06-15", "snapshot_at": "2026-06-15T09:00:00",
         "source": "初测"},
        {"snapshot_id": "LS-012", "material_code": "M-BTN-RESIN", "supplier_code": "XS-ACC-020",
         "leadtime_days": 12, "captured_at": "2026-06-16", "snapshot_at": "2026-06-16T09:00:00",
         "source": "初测"},
        # M-WOOL-DBL-360 / XS-FAB-004（compareQuotations 候选 4 家之一）：26 → 30（Δ +4）
        {"snapshot_id": "LS-019", "material_code": "M-WOOL-DBL-360", "supplier_code": "XS-FAB-004",
         "leadtime_days": 26, "captured_at": "2026-06-11", "snapshot_at": "2026-06-11T09:00:00",
         "source": "初测"},
        {"snapshot_id": "LS-020", "material_code": "M-WOOL-DBL-360", "supplier_code": "XS-FAB-004",
         "leadtime_days": 30, "captured_at": "2026-06-26", "snapshot_at": "2026-06-26T11:00:00",
         "source": "复测"},
        # M-TC-180 / XS-FAB-001（compareQuotations 候选 2 家之一）：12 → 14（Δ +2）
        {"snapshot_id": "LS-021", "material_code": "M-TC-180", "supplier_code": "XS-FAB-001",
         "leadtime_days": 12, "captured_at": "2026-06-10", "snapshot_at": "2026-06-10T08:00:00",
         "source": "初测"},
        {"snapshot_id": "LS-022", "material_code": "M-TC-180", "supplier_code": "XS-FAB-001",
         "leadtime_days": 14, "captured_at": "2026-06-24", "snapshot_at": "2026-06-24T10:00:00",
         "source": "复测"},
    ]

    # ── 物料校验记录 MATERIAL_VALIDATIONS（3 缺料 / 2 超领，双向发起） ──
    material_validations = [
        {"validation_id": "MV-001", "initiated_by": "factory", "work_order_no": "WO20260607",
         "style_code": "XT-DS2026-001", "bom_material_code": "M-WOOL-DBL-360",
         "required_qty": 1500, "actual_qty": 1500, "variance_qty": 0, "variance_pct": 0.0,
         "status": "正常", "operator": "裁剪-王", "check_date": "2026-06-28"},
        {"validation_id": "MV-002", "initiated_by": "internal", "work_order_no": "WO20260607",
         "style_code": "XT-DS2026-001", "bom_material_code": "M-ZIP-YKK-5",
         "required_qty": 800, "actual_qty": 800, "variance_qty": 0, "variance_pct": 0.0,
         "status": "正常", "operator": "IQC-李", "check_date": "2026-06-28"},
        {"validation_id": "MV-003", "initiated_by": "factory", "work_order_no": "WO20260608",
         "style_code": "XT-DS2026-002", "bom_material_code": "M-WOOL-DBL-360",
         "required_qty": 1200, "actual_qty": 1080, "variance_qty": -120, "variance_pct": -10.0,
         "status": "缺料", "operator": "裁剪-张", "check_date": "2026-06-27"},
        {"validation_id": "MV-004", "initiated_by": "internal", "work_order_no": "WO20260608",
         "style_code": "XT-DS2026-002", "bom_material_code": "M-INTER-030",
         "required_qty": 600, "actual_qty": 540, "variance_qty": -60, "variance_pct": -10.0,
         "status": "缺料", "operator": "IQC-李", "check_date": "2026-06-27"},
        {"validation_id": "MV-005", "initiated_by": "factory", "work_order_no": "WO20260609",
         "style_code": "XT-TC2026-010", "bom_material_code": "M-TC-180",
         "required_qty": 2000, "actual_qty": 2150, "variance_qty": 150, "variance_pct": 7.5,
         "status": "超领", "operator": "裁剪-陈", "check_date": "2026-06-26"},
        {"validation_id": "MV-006", "initiated_by": "factory", "work_order_no": "WO20260610",
         "style_code": "XT-FL2026-005", "bom_material_code": "M-FLEECE-280",
         "required_qty": 800, "actual_qty": 850, "variance_qty": 50, "variance_pct": 6.25,
         "status": "超领", "operator": "裁剪-王", "check_date": "2026-06-25"},
        {"validation_id": "MV-007", "initiated_by": "internal", "work_order_no": "WO20260610",
         "style_code": "XT-FL2026-005", "bom_material_code": "M-ZIP-XJ-3",
         "required_qty": 5000, "actual_qty": 5000, "variance_qty": 0, "variance_pct": 0.0,
         "status": "正常", "operator": "IQC-周", "check_date": "2026-06-25"},
        {"validation_id": "MV-008", "initiated_by": "factory", "work_order_no": "WO20260611",
         "style_code": "XT-SH2026-008", "bom_material_code": "M-SHELL-3L-150",
         "required_qty": 600, "actual_qty": 540, "variance_qty": -60, "variance_pct": -10.0,
         "status": "缺料", "operator": "裁剪-张", "check_date": "2026-06-24"},
        {"validation_id": "MV-009", "initiated_by": "internal", "work_order_no": "WO20260611",
         "style_code": "XT-SH2026-008", "bom_material_code": "M-BTN-RESIN",
         "required_qty": 3000, "actual_qty": 3000, "variance_qty": 0, "variance_pct": 0.0,
         "status": "正常", "operator": "IQC-周", "check_date": "2026-06-24"},
        {"validation_id": "MV-010", "initiated_by": "factory", "work_order_no": "WO20260612",
         "style_code": "XT-DS2026-001", "bom_material_code": "M-INTER-030",
         "required_qty": 400, "actual_qty": 400, "variance_qty": 0, "variance_pct": 0.0,
         "status": "正常", "operator": "裁剪-王", "check_date": "2026-06-23"},
    ]

    return ScmData(
        suppliers=suppliers, supplier_by_code=supplier_by_code,
        quotations=quotations, quotation_by_no=quotation_by_no,
        capacity_calendar=capacity_calendar,
        fabric_arrival_plans=fabric_arrival_plans,
        replenishment_suggestions=replenishment_suggestions,
        leadtime_snapshots=leadtime_snapshots,
        material_validations=material_validations,
    )


# ───────────────────────── agileac（敏睿空调供应链） ─────────────────────────


def _build_agileac() -> ScmData:
    """敏睿空调供应链口径数据：8 大物料品类供应商 / 多家比价 / 产能 / 在途 / 补单 /
    交期异动 / 物料校验。

    供应商编码、物料编码、采购单号、工单号与 ERP/MES agileac 完全对齐，跨系统拉数闭环。
    """
    R = D.rng(20260213)

    # ── 供应商 SUPPLIERS（10 家：覆盖 6 大品类 + 2 家备选以支撑比价） ──
    suppliers = [
        {"code": "S-COMP-001", "name": "上海海立压缩机", "category": "压缩机",
         "contact": "陈压缩", "phone": "13900100001", "payment_terms_days": 60,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 200, "moq": 100, "specialty": "转子压缩机/变频压缩机"},
        {"code": "S-COMP-002", "name": "广州万宝压缩机", "category": "压缩机",
         "contact": "林压缩", "phone": "13900100002", "payment_terms_days": 45,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 300, "moq": 200, "specialty": "转子压缩机/定速"},
        {"code": "S-HEX-001", "name": "江苏双良换热器", "category": "热交换器",
         "contact": "沈换热", "phone": "13900100003", "payment_terms_days": 45,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 500, "moq": 200, "specialty": "翅片冷凝器/蒸发器"},
        {"code": "S-HEX-002", "name": "浙江盾安换热器", "category": "热交换器",
         "contact": "顾换热", "phone": "13900100004", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 400, "moq": 150, "specialty": "翅片冷凝器/微通道"},
        {"code": "S-VALVE-001", "name": "浙江三花电子膨胀阀", "category": "阀件",
         "contact": "赵阀件", "phone": "13900100005", "payment_terms_days": 30,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 2000, "moq": 500, "specialty": "EEV/四通阀/球阀"},
        {"code": "S-REF-001", "name": "中化蓝天制冷剂", "category": "制冷剂",
         "contact": "孙制冷", "phone": "13900100006", "payment_terms_days": 30,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 5000, "moq": 1000, "specialty": "R410A/R32/R290"},
        {"code": "S-PSB-001", "name": "深圳拓邦控制板", "category": "电控",
         "contact": "周电控", "phone": "13900100007", "payment_terms_days": 60,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 1000, "moq": 300, "specialty": "主控板/驱动板/逆变器"},
        {"code": "S-PSB-002", "name": "杭州固拓电子", "category": "电控",
         "contact": "郑电控", "phone": "13900100008", "payment_terms_days": 45,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 800, "moq": 200, "specialty": "主控板/电源板"},
        {"code": "S-PKG-001", "name": "苏州包装制品", "category": "包装",
         "contact": "钱包装", "phone": "13900100009", "payment_terms_days": 60,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 5000, "moq": 1000, "specialty": "纸箱/珍珠棉/EPE"},
        {"code": "S-LOG-001", "name": "顺丰冷链物流", "category": "物流",
         "contact": "孙物流", "phone": "13900100010", "payment_terms_days": 30,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 2000, "moq": 50, "specialty": "整车/零担/冷链"},
    ]
    supplier_by_code = {s["code"]: s for s in suppliers}

    # ── 报价单 QUOTATIONS（含 4 物料多家对比） ──
    quotations = [
        # 24K 转子压缩机（M-COMP-GT-24K）3 家对比
        {"quotation_no": "AGQ202607001", "supplier_code": "S-COMP-001",
         "supplier_name": "上海海立压缩机",
         "material_code": "M-COMP-GT-24K", "material_name": "24K 转子压缩机 R410A",
         "spec": "排量 24cc R410A 220V/50Hz", "unit_price": 580.0, "moq": 100,
         "leadtime_days": 25, "payment_terms_days": 60, "valid_until": "2026-08-31",
         "status": "有效", "submitted_at": "2026-06-20T09:30:00"},
        {"quotation_no": "AGQ202607002", "supplier_code": "S-COMP-002",
         "supplier_name": "广州万宝压缩机",
         "material_code": "M-COMP-GT-24K", "material_name": "24K 转子压缩机 R410A（替代）",
         "spec": "排量 24cc R410A 220V/50Hz", "unit_price": 545.0, "moq": 200,
         "leadtime_days": 20, "payment_terms_days": 45, "valid_until": "2026-08-25",
         "status": "有效", "submitted_at": "2026-06-18T14:00:00"},
        # 翅片冷凝器（M-COND-FIN-30）2 家对比
        {"quotation_no": "AGQ202607010", "supplier_code": "S-HEX-001",
         "supplier_name": "江苏双良换热器",
         "material_code": "M-COND-FIN-30", "material_name": "30 平方英寸翅片冷凝器",
         "spec": "30in² 9.52mm 铜管 翅片冷凝器", "unit_price": 280.0, "moq": 200,
         "leadtime_days": 18, "payment_terms_days": 45, "valid_until": "2026-08-20",
         "status": "有效", "submitted_at": "2026-06-19T09:00:00"},
        {"quotation_no": "AGQ202607011", "supplier_code": "S-HEX-002",
         "supplier_name": "浙江盾安换热器",
         "material_code": "M-COND-FIN-30", "material_name": "30 平方英寸翅片冷凝器（微通道）",
         "spec": "30in² 微通道 全铝冷凝器", "unit_price": 320.0, "moq": 150,
         "leadtime_days": 22, "payment_terms_days": 30, "valid_until": "2026-08-22",
         "status": "有效", "submitted_at": "2026-06-20T11:00:00"},
        # 蒸发器（M-EVAP-FIN-30）2 家对比
        {"quotation_no": "AGQ202607020", "supplier_code": "S-HEX-001",
         "supplier_name": "江苏双良换热器",
         "material_code": "M-EVAP-FIN-30", "material_name": "30 平方英寸翅片蒸发器",
         "spec": "30in² 7mm 铜管 翅片蒸发器", "unit_price": 240.0, "moq": 200,
         "leadtime_days": 18, "payment_terms_days": 45, "valid_until": "2026-08-18",
         "status": "有效", "submitted_at": "2026-06-19T10:00:00"},
        {"quotation_no": "AGQ202607021", "supplier_code": "S-HEX-002",
         "supplier_name": "浙江盾安换热器",
         "material_code": "M-EVAP-FIN-30", "material_name": "30 平方英寸翅片蒸发器（替代）",
         "spec": "30in² 7mm 铜管 翅片蒸发器", "unit_price": 265.0, "moq": 150,
         "leadtime_days": 22, "payment_terms_days": 30, "valid_until": "2026-08-25",
         "status": "有效", "submitted_at": "2026-06-20T11:30:00"},
        # 电子膨胀阀 EEV（M-EEV-15）2 家对比
        {"quotation_no": "AGQ202607030", "supplier_code": "S-VALVE-001",
         "supplier_name": "浙江三花电子膨胀阀",
         "material_code": "M-EEV-15", "material_name": "EEV 电子膨胀阀 15 步",
         "spec": "15 步 0~3.0mm 阀口 R410A", "unit_price": 95.0, "moq": 500,
         "leadtime_days": 15, "payment_terms_days": 30, "valid_until": "2026-08-15",
         "status": "有效", "submitted_at": "2026-06-18T10:00:00"},
        # 制冷剂 R410A（M-RF-R410A）2 家对比
        {"quotation_no": "AGQ202607040", "supplier_code": "S-REF-001",
         "supplier_name": "中化蓝天制冷剂",
         "material_code": "M-RF-R410A", "material_name": "制冷剂 R410A 10kg 瓶",
         "spec": "R410A 10kg 一次性钢瓶", "unit_price": 480.0, "moq": 100,
         "leadtime_days": 10, "payment_terms_days": 30, "valid_until": "2026-08-10",
         "status": "有效", "submitted_at": "2026-06-17T09:00:00"},
        # 主控板（M-PSB-CTL）2 家对比
        {"quotation_no": "AGQ202607050", "supplier_code": "S-PSB-001",
         "supplier_name": "深圳拓邦控制板",
         "material_code": "M-PSB-CTL", "material_name": "空调主控板 V2.1",
         "spec": "STM32F1 485 通讯 + WiFi 模组", "unit_price": 180.0, "moq": 300,
         "leadtime_days": 20, "payment_terms_days": 60, "valid_until": "2026-08-30",
         "status": "有效", "submitted_at": "2026-06-19T15:00:00"},
        {"quotation_no": "AGQ202607051", "supplier_code": "S-PSB-002",
         "supplier_name": "杭州固拓电子",
         "material_code": "M-PSB-CTL", "material_name": "空调主控板 V2.1（替代）",
         "spec": "STM32F1 485 通讯 + WiFi 模组", "unit_price": 165.0, "moq": 200,
         "leadtime_days": 25, "payment_terms_days": 45, "valid_until": "2026-08-25",
         "status": "有效", "submitted_at": "2026-06-20T15:30:00"},
        # 启动电容（M-CAP-30UF）
        {"quotation_no": "AGQ202607060", "supplier_code": "S-PSB-002",
         "supplier_name": "杭州固拓电子",
         "material_code": "M-CAP-30UF", "material_name": "启动电容 30μF 450V",
         "spec": "CBB65 30μF 450VAC", "unit_price": 18.0, "moq": 500,
         "leadtime_days": 12, "payment_terms_days": 45, "valid_until": "2026-08-10",
         "status": "有效", "submitted_at": "2026-06-16T09:30:00"},
        # 包装箱（M-PKG-CTN-AC）
        {"quotation_no": "AGQ202607070", "supplier_code": "S-PKG-001",
         "supplier_name": "苏州包装制品",
         "material_code": "M-PKG-CTN-AC", "material_name": "空调包装箱 5 层瓦楞",
         "spec": "5 层瓦楞 800×400×320 含珍珠棉", "unit_price": 22.0, "moq": 500,
         "leadtime_days": 7, "payment_terms_days": 60, "valid_until": "2026-08-01",
         "status": "已下单", "submitted_at": "2026-06-09T10:00:00"},
        # 已过期报价
        {"quotation_no": "AGQ202605010", "supplier_code": "S-COMP-001",
         "supplier_name": "上海海立压缩机",
         "material_code": "M-COMP-GT-24K", "material_name": "24K 转子压缩机 R410A",
         "spec": "排量 24cc R410A 220V/50Hz", "unit_price": 620.0, "moq": 100,
         "leadtime_days": 30, "payment_terms_days": 60, "valid_until": "2026-06-15",
         "status": "已过期", "submitted_at": "2026-05-10T10:00:00"},
        {"quotation_no": "AGQ202605011", "supplier_code": "S-HEX-002",
         "supplier_name": "浙江盾安换热器",
         "material_code": "M-COND-FIN-30", "material_name": "30 平方英寸翅片冷凝器（微通道）",
         "spec": "30in² 微通道 全铝冷凝器", "unit_price": 350.0, "moq": 150,
         "leadtime_days": 28, "payment_terms_days": 30, "valid_until": "2026-06-20",
         "status": "已过期", "submitted_at": "2026-05-12T10:00:00"},
    ]
    quotation_by_no = {q["quotation_no"]: q for q in quotations}

    # ── 产能日历 CAPACITY_CALENDAR ──
    capacity_calendar: list[dict] = []
    full_load_suppliers = {"S-COMP-001", "S-HEX-001"}      # 满载 utilization > 88%
    idle_suppliers = {"S-PSB-002", "S-LOG-001"}             # 空闲 utilization < 50%
    entry_seq = 1
    for sup in suppliers:
        cap = sup["capacity_per_day"]
        offsets = sorted(D.sample(R, list(range(-7, 14)), D.randint(R, 3, 4)))
        for off in offsets:
            d_ = BASE_DATE + timedelta(days=off)
            if sup["code"] in full_load_suppliers:
                util = D.randfloat(R, 0.88, 0.98)
            elif sup["code"] in idle_suppliers:
                util = D.randfloat(R, 0.25, 0.48)
            else:
                util = D.randfloat(R, 0.55, 0.85)
            used = int(cap * util)
            available = max(0, cap - used)
            uom = ("台" if "压缩机" in sup["category"] else
                   ("套" if "热交换" in sup["category"] else
                    ("只" if "阀" in sup["category"] or "电控" in sup["category"] else
                     ("瓶" if "制冷剂" in sup["category"] else
                      ("个" if "包装" in sup["category"] else "件")))))
            capacity_calendar.append({
                "entry_id": f"AGCC{D.pad(entry_seq)}",
                "supplier_code": sup["code"], "supplier_name": sup["name"],
                "date": f"{d_}", "total_capacity": cap, "used": used,
                "available": available, "utilization_pct": round(util * 100, 1),
                "uom": uom,
            })
            entry_seq += 1

    # ── 在途到货计划 PARTS_ARRIVAL_PLANS（含 3 条延误） ──
    fabric_arrival_plans = [
        {"plan_id": "AGFAP-001", "supplier_code": "S-COMP-001", "supplier_name": "上海海立压缩机",
         "material_code": "M-COMP-GT-24K", "po_ref": "AGPO20260001", "qty": 500, "uom": "台",
         "ship_date": "2026-06-22", "eta": "2026-06-28", "status": "已到货", "delay_days": 0},
        {"plan_id": "AGFAP-002", "supplier_code": "S-COMP-002", "supplier_name": "广州万宝压缩机",
         "material_code": "M-COMP-GT-24K", "po_ref": "AGPO20260002", "qty": 300, "uom": "台",
         "ship_date": "2026-06-25", "eta": "2026-07-06", "status": "延误", "delay_days": 4},
        {"plan_id": "AGFAP-003", "supplier_code": "S-HEX-001", "supplier_name": "江苏双良换热器",
         "material_code": "M-COND-FIN-30", "po_ref": "AGPO20260003", "qty": 600, "uom": "套",
         "ship_date": "2026-06-26", "eta": "2026-07-01", "status": "已到货", "delay_days": 0},
        {"plan_id": "AGFAP-004", "supplier_code": "S-HEX-001", "supplier_name": "江苏双良换热器",
         "material_code": "M-EVAP-FIN-30", "po_ref": "AGPO20260004", "qty": 600, "uom": "套",
         "ship_date": "2026-06-27", "eta": "2026-07-04", "status": "在途", "delay_days": 0},
        {"plan_id": "AGFAP-005", "supplier_code": "S-VALVE-001", "supplier_name": "浙江三花电子膨胀阀",
         "material_code": "M-EEV-15", "po_ref": "AGPO20260005", "qty": 2000, "uom": "只",
         "ship_date": "2026-06-28", "eta": "2026-07-03", "status": "已到货", "delay_days": 0},
        {"plan_id": "AGFAP-006", "supplier_code": "S-REF-001", "supplier_name": "中化蓝天制冷剂",
         "material_code": "M-RF-R410A", "po_ref": "AGPO20260006", "qty": 800, "uom": "瓶",
         "ship_date": "2026-06-29", "eta": "2026-07-08", "status": "延误", "delay_days": 5},
        {"plan_id": "AGFAP-007", "supplier_code": "S-PSB-001", "supplier_name": "深圳拓邦控制板",
         "material_code": "M-PSB-CTL", "po_ref": "AGPO20260007", "qty": 800, "uom": "只",
         "ship_date": "2026-06-29", "eta": "2026-07-09", "status": "在途", "delay_days": 0},
        {"plan_id": "AGFAP-008", "supplier_code": "S-PKG-001", "supplier_name": "苏州包装制品",
         "material_code": "M-PKG-CTN-AC", "po_ref": "AGPO20260008", "qty": 3000, "uom": "个",
         "ship_date": "2026-06-25", "eta": "2026-06-30", "status": "已到货", "delay_days": 0},
        {"plan_id": "AGFAP-009", "supplier_code": "S-PSB-002", "supplier_name": "杭州固拓电子",
         "material_code": "M-CAP-30UF", "po_ref": "AGPO20260007", "qty": 1500, "uom": "只",
         "ship_date": "2026-06-26", "eta": "2026-07-04", "status": "延误", "delay_days": 3},
        {"plan_id": "AGFAP-010", "supplier_code": "S-HEX-002", "supplier_name": "浙江盾安换热器",
         "material_code": "M-COND-FIN-30", "po_ref": "AGPO20260002", "qty": 200, "uom": "套",
         "ship_date": "2026-07-01", "eta": "2026-07-10", "status": "在途", "delay_days": 0},
    ]

    # ── 补单节奏建议 REPLENISHMENT_SUGGESTIONS（6 款空调产品） ──
    replenishment_suggestions = [
        {"suggestion_id": "AGSUG-001", "style_code": "P-RC-WALL-15", "bulk_no": "AWO20260101",
         "total_qty": 1500, "first_batch_qty": 600, "first_batch_date": "2026-07-05",
         "replenish_1_qty": 500, "replenish_1_date": "2026-07-15",
         "replenish_2_qty": 400, "replenish_2_date": "2026-07-25",
         "fabric_arrival_date": "2026-06-28",
         "factory_capacity_note": "LINE-RC-ASSY 7/5-7/8 可用产能 600 台",
         "risks": ["压缩机 AGFAP-002 延误 4 天，首批可能推迟至 7/9"]},
        {"suggestion_id": "AGSUG-002", "style_code": "P-RC-CAB-30", "bulk_no": "AWO20260105",
         "total_qty": 800, "first_batch_qty": 300, "first_batch_date": "2026-07-08",
         "replenish_1_qty": 300, "replenish_1_date": "2026-07-18",
         "replenish_2_qty": 200, "replenish_2_date": "2026-07-28",
         "fabric_arrival_date": "2026-07-01",
         "factory_capacity_note": "LINE-RC-ASSY 7/8-7/10 可用产能 300 台",
         "risks": ["S-COMP-001 产能满载，补 2 可能需调 S-COMP-002"]},
        {"suggestion_id": "AGSUG-003", "style_code": "P-RC-MOVE-10", "bulk_no": "AWO20260108",
         "total_qty": 2000, "first_batch_qty": 800, "first_batch_date": "2026-07-06",
         "replenish_1_qty": 700, "replenish_1_date": "2026-07-16",
         "replenish_2_qty": 500, "replenish_2_date": "2026-07-26",
         "fabric_arrival_date": "2026-07-01",
         "factory_capacity_note": "LINE-RC-ASSY 7/6-7/9 可用产能 800 台",
         "risks": []},
        {"suggestion_id": "AGSUG-004", "style_code": "P-CC-VRV-360", "bulk_no": "AWO20260210",
         "total_qty": 600, "first_batch_qty": 240, "first_batch_date": "2026-07-04",
         "replenish_1_qty": 200, "replenish_1_date": "2026-07-14",
         "replenish_2_qty": 160, "replenish_2_date": "2026-07-22",
         "fabric_arrival_date": "2026-06-30",
         "factory_capacity_note": "LINE-CC-ASSY 7/4-7/6 可用产能 240 台",
         "risks": ["主控板 AGFAP-007 在途，7/9 前不可超额投产"]},
        {"suggestion_id": "AGSUG-005", "style_code": "P-CC-DUCT-50", "bulk_no": "AWO20260215",
         "total_qty": 500, "first_batch_qty": 200, "first_batch_date": "2026-07-10",
         "replenish_1_qty": 180, "replenish_1_date": "2026-07-20",
         "replenish_2_qty": 120, "replenish_2_date": "2026-07-30",
         "fabric_arrival_date": "2026-07-04",
         "factory_capacity_note": "LINE-CC-ASSY 7/10-7/12 可用产能 200 台",
         "risks": ["制冷剂 AGFAP-006 延误 5 天，首批可能推迟"]},
        {"suggestion_id": "AGSUG-006", "style_code": "P-CC-CHILL-100", "bulk_no": "AWO20260220",
         "total_qty": 300, "first_batch_qty": 120, "first_batch_date": "2026-07-12",
         "replenish_1_qty": 100, "replenish_1_date": "2026-07-22",
         "replenish_2_qty": 80, "replenish_2_date": "2026-08-01",
         "fabric_arrival_date": "2026-07-06",
         "factory_capacity_note": "LINE-CC-ASSY 7/12-7/14 可用产能 120 台",
         "risks": ["S-HEX-001 产能满载且交期异动 +7 天，建议改派 S-HEX-002"]},
    ]

    # ── 交期快照 LEADTIME_SNAPSHOTS（含 3 组初测→复测异动） ──
    leadtime_snapshots = [
        # M-COMP-GT-24K / S-COMP-001：25 → 32（Δ +7）
        {"snapshot_id": "AGLS-001", "material_code": "M-COMP-GT-24K", "supplier_code": "S-COMP-001",
         "leadtime_days": 25, "captured_at": "2026-06-10", "snapshot_at": "2026-06-10T09:00:00",
         "source": "初测"},
        {"snapshot_id": "AGLS-002", "material_code": "M-COMP-GT-24K", "supplier_code": "S-COMP-001",
         "leadtime_days": 32, "captured_at": "2026-06-25", "snapshot_at": "2026-06-25T14:00:00",
         "source": "复测"},
        # M-COMP-GT-24K / S-COMP-002：20 → 35（Δ +15）—— 关键异动
        {"snapshot_id": "AGLS-003", "material_code": "M-COMP-GT-24K", "supplier_code": "S-COMP-002",
         "leadtime_days": 20, "captured_at": "2026-06-12", "snapshot_at": "2026-06-12T10:00:00",
         "source": "初测"},
        {"snapshot_id": "AGLS-004", "material_code": "M-COMP-GT-24K", "supplier_code": "S-COMP-002",
         "leadtime_days": 35, "captured_at": "2026-06-26", "snapshot_at": "2026-06-26T15:00:00",
         "source": "复测"},
        # M-COND-FIN-30 / S-HEX-001：18 → 22（Δ +4）
        {"snapshot_id": "AGLS-005", "material_code": "M-COND-FIN-30", "supplier_code": "S-HEX-001",
         "leadtime_days": 18, "captured_at": "2026-06-11", "snapshot_at": "2026-06-11T09:30:00",
         "source": "初测"},
        {"snapshot_id": "AGLS-006", "material_code": "M-COND-FIN-30", "supplier_code": "S-HEX-001",
         "leadtime_days": 22, "captured_at": "2026-06-27", "snapshot_at": "2026-06-27T11:00:00",
         "source": "复测"},
        # M-EEV-15 / S-VALVE-001：15 → 18（Δ +3）
        {"snapshot_id": "AGLS-007", "material_code": "M-EEV-15", "supplier_code": "S-VALVE-001",
         "leadtime_days": 15, "captured_at": "2026-06-11", "snapshot_at": "2026-06-11T09:00:00",
         "source": "初测"},
        {"snapshot_id": "AGLS-008", "material_code": "M-EEV-15", "supplier_code": "S-VALVE-001",
         "leadtime_days": 18, "captured_at": "2026-06-24", "snapshot_at": "2026-06-24T10:00:00",
         "source": "复测"},
        # M-RF-R410A / S-REF-001：10 → 12（Δ +2）
        {"snapshot_id": "AGLS-009", "material_code": "M-RF-R410A", "supplier_code": "S-REF-001",
         "leadtime_days": 10, "captured_at": "2026-06-10", "snapshot_at": "2026-06-10T08:00:00",
         "source": "初测"},
        {"snapshot_id": "AGLS-010", "material_code": "M-RF-R410A", "supplier_code": "S-REF-001",
         "leadtime_days": 12, "captured_at": "2026-06-24", "snapshot_at": "2026-06-24T10:00:00",
         "source": "复测"},
        # M-PSB-CTL / S-PSB-001：20 → 25（Δ +5）
        {"snapshot_id": "AGLS-011", "material_code": "M-PSB-CTL", "supplier_code": "S-PSB-001",
         "leadtime_days": 20, "captured_at": "2026-06-13", "snapshot_at": "2026-06-13T09:00:00",
         "source": "初测"},
        {"snapshot_id": "AGLS-012", "material_code": "M-PSB-CTL", "supplier_code": "S-PSB-001",
         "leadtime_days": 25, "captured_at": "2026-06-28", "snapshot_at": "2026-06-28T10:00:00",
         "source": "复测"},
        # M-PSB-CTL / S-PSB-002（compareQuotations 首选）：25 → 30（Δ +5）
        {"snapshot_id": "AGLS-013", "material_code": "M-PSB-CTL", "supplier_code": "S-PSB-002",
         "leadtime_days": 25, "captured_at": "2026-06-12", "snapshot_at": "2026-06-12T09:00:00",
         "source": "初测"},
        {"snapshot_id": "AGLS-014", "material_code": "M-PSB-CTL", "supplier_code": "S-PSB-002",
         "leadtime_days": 30, "captured_at": "2026-06-27", "snapshot_at": "2026-06-27T10:00:00",
         "source": "复测"},
        # 单快照
        {"snapshot_id": "AGLS-015", "material_code": "M-CAP-30UF", "supplier_code": "S-PSB-002",
         "leadtime_days": 12, "captured_at": "2026-06-15", "snapshot_at": "2026-06-15T09:00:00",
         "source": "初测"},
        {"snapshot_id": "AGLS-016", "material_code": "M-PKG-CTN-AC", "supplier_code": "S-PKG-001",
         "leadtime_days": 7, "captured_at": "2026-06-16", "snapshot_at": "2026-06-16T09:00:00",
         "source": "初测"},
    ]

    # ── 物料校验记录 MATERIAL_VALIDATIONS（3 缺料 / 2 超领） ──
    material_validations = [
        {"validation_id": "AGMV-001", "initiated_by": "factory", "work_order_no": "AWO20260101",
         "style_code": "P-RC-WALL-15", "bom_material_code": "M-COMP-GT-24K",
         "required_qty": 600, "actual_qty": 600, "variance_qty": 0, "variance_pct": 0.0,
         "status": "正常", "operator": "装配-王", "check_date": "2026-06-28"},
        {"validation_id": "AGMV-002", "initiated_by": "internal", "work_order_no": "AWO20260101",
         "style_code": "P-RC-WALL-15", "bom_material_code": "M-COND-FIN-30",
         "required_qty": 600, "actual_qty": 600, "variance_qty": 0, "variance_pct": 0.0,
         "status": "正常", "operator": "IQC-李", "check_date": "2026-06-28"},
        {"validation_id": "AGMV-003", "initiated_by": "factory", "work_order_no": "AWO20260105",
         "style_code": "P-RC-CAB-30", "bom_material_code": "M-COMP-GT-24K",
         "required_qty": 300, "actual_qty": 270, "variance_qty": -30, "variance_pct": -10.0,
         "status": "缺料", "operator": "装配-张", "check_date": "2026-06-27"},
        {"validation_id": "AGMV-004", "initiated_by": "internal", "work_order_no": "AWO20260105",
         "style_code": "P-RC-CAB-30", "bom_material_code": "M-EVAP-FIN-30",
         "required_qty": 300, "actual_qty": 270, "variance_qty": -30, "variance_pct": -10.0,
         "status": "缺料", "operator": "IQC-李", "check_date": "2026-06-27"},
        {"validation_id": "AGMV-005", "initiated_by": "factory", "work_order_no": "AWO20260108",
         "style_code": "P-RC-MOVE-10", "bom_material_code": "M-COMP-GT-24K",
         "required_qty": 800, "actual_qty": 860, "variance_qty": 60, "variance_pct": 7.5,
         "status": "超领", "operator": "装配-陈", "check_date": "2026-06-26"},
        {"validation_id": "AGMV-006", "initiated_by": "factory", "work_order_no": "AWO20260210",
         "style_code": "P-CC-VRV-360", "bom_material_code": "M-PSB-CTL",
         "required_qty": 240, "actual_qty": 255, "variance_qty": 15, "variance_pct": 6.25,
         "status": "超领", "operator": "电控-王", "check_date": "2026-06-25"},
        {"validation_id": "AGMV-007", "initiated_by": "internal", "work_order_no": "AWO20260210",
         "style_code": "P-CC-VRV-360", "bom_material_code": "M-EEV-15",
         "required_qty": 960, "actual_qty": 960, "variance_qty": 0, "variance_pct": 0.0,
         "status": "正常", "operator": "IQC-周", "check_date": "2026-06-25"},
        {"validation_id": "AGMV-008", "initiated_by": "factory", "work_order_no": "AWO20260215",
         "style_code": "P-CC-DUCT-50", "bom_material_code": "M-RF-R410A",
         "required_qty": 100, "actual_qty": 90, "variance_qty": -10, "variance_pct": -10.0,
         "status": "缺料", "operator": "装配-张", "check_date": "2026-06-24"},
        {"validation_id": "AGMV-009", "initiated_by": "internal", "work_order_no": "AWO20260220",
         "style_code": "P-CC-CHILL-100", "bom_material_code": "M-COND-FIN-30",
         "required_qty": 120, "actual_qty": 120, "variance_qty": 0, "variance_pct": 0.0,
         "status": "正常", "operator": "IQC-周", "check_date": "2026-06-24"},
        {"validation_id": "AGMV-010", "initiated_by": "factory", "work_order_no": "AWO20260221",
         "style_code": "P-CC-CHILL-100", "bom_material_code": "M-PSB-CTL",
         "required_qty": 100, "actual_qty": 100, "variance_qty": 0, "variance_pct": 0.0,
         "status": "正常", "operator": "电控-王", "check_date": "2026-06-23"},
    ]

    return ScmData(
        suppliers=suppliers, supplier_by_code=supplier_by_code,
        quotations=quotations, quotation_by_no=quotation_by_no,
        capacity_calendar=capacity_calendar,
        fabric_arrival_plans=fabric_arrival_plans,
        replenishment_suggestions=replenishment_suggestions,
        leadtime_snapshots=leadtime_snapshots,
        material_validations=material_validations,
    )


# ───────────────────────── agilesteel（敏睿钢铁） ─────────────────────────


def _build_agilesteel() -> ScmData:
    """敏睿钢铁供应链口径数据：铁矿石/焦炭/废钢/合金/耐材/物流供应商 + 大宗原料多家比价(ASQ) +
    产能/到货/补单/交期异动 + 物料校验 + 废钢分级(SCR-)。供应商码 S-STEEL- 与 ERP 对齐。"""
    R = D.rng(20260624)

    suppliers = [
        {"code": "S-STEEL-ORE-01", "name": "澳大利亚 BHP 铁矿石", "category": "铁矿石",
         "contact": "王矿石", "phone": "13900100001", "payment_terms_days": 60,
         "currency": "USD", "rating": "A", "status": "合作中",
         "capacity_per_day": 5000, "moq": 10000, "specialty": "62% 粉矿/块矿"},
        {"code": "S-STEEL-ORE-02", "name": "巴西淡水河谷铁矿石", "category": "铁矿石",
         "contact": "李矿石", "phone": "13900100002", "payment_terms_days": 60,
         "currency": "USD", "rating": "A", "status": "合作中",
         "capacity_per_day": 4000, "moq": 8000, "specialty": "62% 卡粉/球团"},
        {"code": "S-STEEL-COKE-01", "name": "山西焦煤集团", "category": "焦炭",
         "contact": "张焦炭", "phone": "13900100003", "payment_terms_days": 45,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 1500, "moq": 2000, "specialty": "冶金焦/一级焦"},
        {"code": "S-STEEL-SCR-01", "name": "长三角废钢回收", "category": "废钢",
         "contact": "陈废钢", "phone": "13900100004", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 800, "moq": 500, "specialty": "重废1/重废2/剪切料"},
        {"code": "S-STEEL-SCR-02", "name": "华中再生资源", "category": "废钢",
         "contact": "周废钢", "phone": "13900100005", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 600, "moq": 400, "specialty": "破碎料/车屑"},
        {"code": "S-STEEL-ALY-01", "name": "中信合金材料", "category": "合金",
         "contact": "刘合金", "phone": "13900100006", "payment_terms_days": 45,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 200, "moq": 100, "specialty": "硅铁/锰铁/铬铁"},
        {"code": "S-STEEL-REF-01", "name": "辽宁耐火材料", "category": "耐材",
         "contact": "赵耐材", "phone": "13900100007", "payment_terms_days": 45,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 150, "moq": 100, "specialty": "镁碳砖/滑板"},
        {"code": "S-STEEL-LOG-01", "name": "长江航运物流", "category": "物流",
         "contact": "孙物流", "phone": "13900100008", "payment_terms_days": 30,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 10000, "moq": 1000, "specialty": "长江散货船/海进江"},
    ]
    supplier_by_code = {s["code"]: s for s in suppliers}

    # 废钢分级（SCR-，支撑 SCM-01 智能废钢判级 + 与 ERP M-SCR- / MES 配料对齐）
    scrap_grades = [
        {"scrap_code": "SCR-HMS1", "name": "重废1型", "category": "重废",
         "density_t_per_m3": 1.2, "impurity_limit": "≤1.0%", "price_per_t": 2680.0,
         "status": "在用", "applicable_steel": "P-ST-Q345B/P-ST-45#"},
        {"scrap_code": "SCR-HMS2", "name": "重废2型", "category": "重废",
         "density_t_per_m3": 1.0, "impurity_limit": "≤1.5%", "price_per_t": 2520.0,
         "status": "在用", "applicable_steel": "P-ST-Q235B/P-ST-20MnSi"},
        {"scrap_code": "SCR-BROKEN", "name": "破碎料", "category": "破碎料",
         "density_t_per_m3": 0.9, "impurity_limit": "≤2.0%", "price_per_t": 2380.0,
         "status": "在用", "applicable_steel": "P-ST-Q235B"},
        {"scrap_code": "SCR-TURNINGS", "name": "车屑", "category": "车屑",
         "density_t_per_m3": 0.7, "impurity_limit": "≤3.0%", "price_per_t": 1980.0,
         "status": "限用", "applicable_steel": "P-ST-Q235B(限量)"},
    ]
    scrap_grade_by_code = {g["scrap_code"]: g for g in scrap_grades}

    # 大宗原料报价单（ASQ，多家比价）
    quotations = [
        # 62% 粉矿（M-ORE-FINE）2 家对比
        {"quotation_no": "ASQ202607001", "supplier_code": "S-STEEL-ORE-01",
         "supplier_name": "澳大利亚 BHP 铁矿石",
         "material_code": "M-ORE-FINE", "material_name": "进口粉矿 62%",
         "spec": "Fe 62% 粉矿 CFR", "unit_price": 880.0, "moq": 10000,
         "leadtime_days": 35, "payment_terms_days": 60, "valid_until": "2026-08-31",
         "status": "有效", "submitted_at": "2026-06-20T09:30:00"},
        {"quotation_no": "ASQ202607002", "supplier_code": "S-STEEL-ORE-02",
         "supplier_name": "巴西淡水河谷铁矿石",
         "material_code": "M-ORE-FINE", "material_name": "进口粉矿 62%（巴西卡粉）",
         "spec": "Fe 62% 卡粉 CFR", "unit_price": 855.0, "moq": 8000,
         "leadtime_days": 45, "payment_terms_days": 60, "valid_until": "2026-08-25",
         "status": "有效", "submitted_at": "2026-06-18T14:00:00"},
        # 冶金焦炭（M-COKE）2 家对比
        {"quotation_no": "ASQ202607010", "supplier_code": "S-STEEL-COKE-01",
         "supplier_name": "山西焦煤集团",
         "material_code": "M-COKE", "material_name": "冶金焦炭",
         "spec": "灰分≤12% S≤0.6% 粒度25-40mm", "unit_price": 2450.0, "moq": 2000,
         "leadtime_days": 12, "payment_terms_days": 45, "valid_until": "2026-08-20",
         "status": "有效", "submitted_at": "2026-06-19T09:00:00"},
        # 重废1型（M-SCR-HMS1）2 家对比
        {"quotation_no": "ASQ202607020", "supplier_code": "S-STEEL-SCR-01",
         "supplier_name": "长三角废钢回收",
         "material_code": "M-SCR-HMS1", "material_name": "废钢 重废1型",
         "spec": "厚度≥6mm 长<800mm", "unit_price": 2680.0, "moq": 500,
         "leadtime_days": 5, "payment_terms_days": 30, "valid_until": "2026-08-18",
         "status": "有效", "submitted_at": "2026-06-19T10:00:00"},
        {"quotation_no": "ASQ202607021", "supplier_code": "S-STEEL-SCR-02",
         "supplier_name": "华中再生资源",
         "material_code": "M-SCR-HMS1", "material_name": "废钢 重废1型（华中）",
         "spec": "厚度≥6mm 长<800mm", "unit_price": 2610.0, "moq": 400,
         "leadtime_days": 7, "payment_terms_days": 30, "valid_until": "2026-08-22",
         "status": "有效", "submitted_at": "2026-06-20T11:00:00"},
        # 硅铁合金（M-ALY-SI）1 家
        {"quotation_no": "ASQ202607030", "supplier_code": "S-STEEL-ALY-01",
         "supplier_name": "中信合金材料",
         "material_code": "M-ALY-SI", "material_name": "硅铁合金 FeSi75",
         "spec": "Si 75% 粒度10-50mm", "unit_price": 6800.0, "moq": 100,
         "leadtime_days": 10, "payment_terms_days": 45, "valid_until": "2026-08-15",
         "status": "有效", "submitted_at": "2026-06-18T10:00:00"},
    ]
    quotation_by_no = {q["quotation_no"]: q for q in quotations}

    # 产能日历
    capacity_calendar = [
        {"supplier_code": "S-STEEL-ORE-01", "date": f"{BASE_DATE + timedelta(days=i)}",
         "utilization_pct": D.randint(R, 70, 95), "available_t": D.randint(R, 1000, 5000)}
        for i in range(7)
    ] + [
        {"supplier_code": "S-STEEL-SCR-01", "date": f"{BASE_DATE + timedelta(days=i)}",
         "utilization_pct": D.randint(R, 60, 90), "available_t": D.randint(R, 200, 800)}
        for i in range(7)
    ]

    # 原料在途到货计划
    fabric_arrival_plans = [
        {"plan_no": "ASAP20260001", "supplier_code": "S-STEEL-ORE-01",
         "material_code": "M-ORE-FINE", "material_name": "进口粉矿 62%",
         "qty": 50000, "uom": "吨", "status": "在途",
         "eta": f"{BASE_DATE + timedelta(days=10)}", "vessel": "长江号", "port": "宁波舟山港"},
        {"plan_no": "ASAP20260002", "supplier_code": "S-STEEL-SCR-01",
         "material_code": "M-SCR-HMS1", "material_name": "废钢 重废1型",
         "qty": 800, "uom": "吨", "status": "待发",
         "eta": f"{BASE_DATE + timedelta(days=3)}", "vessel": "车运", "port": "厂区"},
        {"plan_no": "ASAP20260003", "supplier_code": "S-STEEL-COKE-01",
         "material_code": "M-COKE", "material_name": "冶金焦炭",
         "qty": 2000, "uom": "吨", "status": "已到货",
         "eta": f"{BASE_DATE - timedelta(days=1)}", "vessel": "铁路", "port": "厂区"},
    ]

    # 补单节奏建议
    replenishment_suggestions = [
        {"suggestion_no": "ASRS20260001", "material_code": "M-ORE-FINE",
         "material_name": "进口粉矿 62%", "current_stock": 48000, "safety_stock": 50000,
         "suggested_qty": 20000, "suggested_supplier": "S-STEEL-ORE-01",
         "reason": "库存低于安全线+下月排产增量", "urgency": "高"},
        {"suggestion_no": "ASRS20260002", "material_code": "M-SCR-HMS1",
         "material_name": "废钢 重废1型", "current_stock": 4200, "safety_stock": 8000,
         "suggested_qty": 5000, "suggested_supplier": "S-STEEL-SCR-01",
         "reason": "废钢库存偏低+优特钢排产", "urgency": "高"},
        {"suggestion_no": "ASRS20260003", "material_code": "M-ALY-SI",
         "material_name": "硅铁合金", "current_stock": 450, "safety_stock": 800,
         "suggested_qty": 400, "suggested_supplier": "S-STEEL-ALY-01",
         "reason": "合金常规补货", "urgency": "常规"},
    ]

    # 交期快照（异动检测）
    leadtime_snapshots = [
        {"snapshot_no": "ASLS20260001", "supplier_code": "S-STEEL-ORE-01",
         "material_code": "M-ORE-FINE", "committed_leadtime": 35,
         "actual_leadtime": 42, "diff_days": 7, "snapshot_date": f"{BASE_DATE}",
         "note": "澳矿船期延后+港口压港"},
        {"snapshot_no": "ASLS20260002", "supplier_code": "S-STEEL-COKE-01",
         "material_code": "M-COKE", "committed_leadtime": 12,
         "actual_leadtime": 11, "diff_days": -1, "snapshot_date": f"{BASE_DATE}",
         "note": "正常"},
        {"snapshot_no": "ASLS20260003", "supplier_code": "S-STEEL-SCR-01",
         "material_code": "M-SCR-HMS1", "committed_leadtime": 5,
         "actual_leadtime": 8, "diff_days": 3, "snapshot_date": f"{BASE_DATE}",
         "note": "废钢资源紧张回收延迟"},
    ]

    # 物料校验
    material_validations = [
        {"validation_no": "ASMV20260001", "material_code": "M-ORE-FINE",
         "supplier_code": "S-STEEL-ORE-01", "batch_no": "ASB202606001",
         "declared_spec": "Fe 62%", "actual_spec": "Fe 61.8%", "result": "合格",
         "validated_at": f"{BASE_DATE - timedelta(days=2)}T10:00:00", "validator": "scm-buyer"},
        {"validation_no": "ASMV20260002", "material_code": "M-SCR-HMS1",
         "supplier_code": "S-STEEL-SCR-01", "batch_no": "ASB202606002",
         "declared_spec": "重废1型 厚度≥6mm", "actual_spec": "重废1型 厚度≥6mm", "result": "合格",
         "validated_at": f"{BASE_DATE - timedelta(days=1)}T14:00:00", "validator": "scm-buyer"},
        {"validation_no": "ASMV20260003", "material_code": "M-SCR-HMS2",
         "supplier_code": "S-STEEL-SCR-02", "batch_no": "ASB202606003",
         "declared_spec": "重废2型", "actual_spec": "含破碎料超标", "result": "不合格",
         "validated_at": f"{BASE_DATE}T09:00:00", "validator": "scm-buyer"},
    ]

    return ScmData(
        suppliers=suppliers, supplier_by_code=supplier_by_code,
        quotations=quotations, quotation_by_no=quotation_by_no,
        capacity_calendar=capacity_calendar, fabric_arrival_plans=fabric_arrival_plans,
        replenishment_suggestions=replenishment_suggestions,
        leadtime_snapshots=leadtime_snapshots,
        material_validations=material_validations,
        scrap_grades=scrap_grades, scrap_grade_by_code=scrap_grade_by_code,
    )


# ───────────────────────── agilestationery（敏睿文具） ─────────────────────────


def _build_agilestationery() -> ScmData:
    """敏睿文具供应链口径：日本进口供货 + 物流/报关/包材供应商 + 多家比价(ASQ，物流与报关服务) +
    在途到货计划 + 补货建议 + 进口交期异动 + 到货验收。供应商码 S-ZB- 与 ERP 对齐。

    废钢分级 ``scrap_grades`` 留空（文具贸易无废钢判级）。"""
    R = D.rng(20260719)

    suppliers = [
        {"code": "S-ZB-JP", "name": "敏睿文具·日本进口品牌厂商", "category": "进口供货",
         "contact": "田中采购", "phone": "13900200001", "payment_terms_days": 60,
         "currency": "JPY", "rating": "A", "status": "合作中",
         "capacity_per_day": 200000, "moq": 10000, "specialty": "全系列书写工具进口"},
        {"code": "S-ZB-LOG", "name": "深圳盐田港物流", "category": "物流",
         "contact": "孙物流", "phone": "13900200002", "payment_terms_days": 30,
         "currency": "CNY", "rating": "A", "status": "合作中",
         "capacity_per_day": 50000, "moq": 1000, "specialty": "海运/空运/港口拖车"},
        {"code": "S-ZB-LOG2", "name": "上海浦东空运物流", "category": "物流",
         "contact": "钱空运", "phone": "13900200009", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 30000, "moq": 500, "specialty": "中日空运专线"},
        {"code": "S-ZB-CBR", "name": "上海外代报关行", "category": "报关",
         "contact": "赵报关", "phone": "13900200003", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 20, "moq": 1, "specialty": "上海口岸报关/归类"},
        {"code": "S-ZB-CBR2", "name": "深圳关贸报关行", "category": "报关",
         "contact": "钱关贸", "phone": "13900200004", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 20, "moq": 1, "specialty": "深圳口岸报关/归类"},
        {"code": "S-ZB-PKG", "name": "东莞文具包装制品", "category": "包材",
         "contact": "周包装", "phone": "13900200005", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中",
         "capacity_per_day": 20000, "moq": 1000, "specialty": "塑料包装盒/彩盒"},
    ]
    supplier_by_code = {s["code"]: s for s in suppliers}

    # 多家比价（ASQ，物流空运 vs 海运、报关行、包材）
    quotations = [
        # 上海-深圳海运 2 家对比
        {"quotation_no": "ASQ202607001", "supplier_code": "S-ZB-LOG",
         "supplier_name": "深圳盐田港物流", "material_code": "SVC-FREIGHT-SEA",
         "material_name": "中日海运散货", "spec": "上海→深圳 海运 20GP",
         "unit_price": 3200.0, "moq": 1000, "leadtime_days": 12,
         "payment_terms_days": 30, "valid_until": "2026-08-31",
         "status": "有效", "submitted_at": "2026-07-08T09:30:00"},
        {"quotation_no": "ASQ202607002", "supplier_code": "S-ZB-LOG2",
         "supplier_name": "上海浦东空运物流", "material_code": "SVC-FREIGHT-AIR",
         "material_name": "中日空运专线", "spec": "东京→上海 空运 100kg+",
         "unit_price": 18.5, "moq": 100, "leadtime_days": 3,
         "payment_terms_days": 30, "valid_until": "2026-08-25",
         "status": "有效", "submitted_at": "2026-07-08T14:00:00"},
        # 报关行 2 家对比
        {"quotation_no": "ASQ202607010", "supplier_code": "S-ZB-CBR",
         "supplier_name": "上海外代报关行", "material_code": "SVC-CUSTOMS-SHA",
         "material_name": "上海口岸报关服务", "spec": "进口报关+归类+查验配合",
         "unit_price": 450.0, "moq": 1, "leadtime_days": 2,
         "payment_terms_days": 30, "valid_until": "2026-08-20",
         "status": "有效", "submitted_at": "2026-07-07T09:00:00"},
        {"quotation_no": "ASQ202607011", "supplier_code": "S-ZB-CBR2",
         "supplier_name": "深圳关贸报关行", "material_code": "SVC-CUSTOMS-SZX",
         "material_name": "深圳口岸报关服务", "spec": "进口报关+归类+查验配合",
         "unit_price": 420.0, "moq": 1, "leadtime_days": 2,
         "payment_terms_days": 30, "valid_until": "2026-08-22",
         "status": "有效", "submitted_at": "2026-07-07T10:00:00"},
        # 包材 1 家
        {"quotation_no": "ASQ202607020", "supplier_code": "S-ZB-PKG",
         "supplier_name": "东莞文具包装制品", "material_code": "M-PKG-BOX",
         "material_name": "文具塑料包装盒", "spec": "彩盒 100×60×20mm",
         "unit_price": 0.80, "moq": 1000, "leadtime_days": 7,
         "payment_terms_days": 30, "valid_until": "2026-08-15",
         "status": "有效", "submitted_at": "2026-07-06T10:00:00"},
    ]
    quotation_by_no = {q["quotation_no"]: q for q in quotations}

    # 物流运力日历
    capacity_calendar = [
        {"supplier_code": "S-ZB-LOG", "date": f"{BASE_DATE + timedelta(days=i)}",
         "utilization_pct": D.randint(R, 65, 92), "available_t": D.randint(R, 5000, 40000)}
        for i in range(7)
    ] + [
        {"supplier_code": "S-ZB-LOG2", "date": f"{BASE_DATE + timedelta(days=i)}",
         "utilization_pct": D.randint(R, 55, 85), "available_t": D.randint(R, 2000, 25000)}
        for i in range(7)
    ]

    # 进口在途到货计划（关联 ERP 采购单 PO）
    fabric_arrival_plans = [
        {"plan_no": "ASAP202607001", "supplier_code": "S-ZB-JP",
         "material_code": "M-ZB-G001", "material_name": "敏睿中性笔 0.5 黑",
         "qty": 120000, "uom": "支", "status": "在途",
         "eta": f"{BASE_DATE + timedelta(days=10)}", "vessel": "海运 长江号", "port": "深圳盐田港"},
        {"plan_no": "ASAP202607002", "supplier_code": "S-ZB-JP",
         "material_code": "M-ZB-G010", "material_name": "敏睿中性笔 0.4 蓝",
         "qty": 60000, "uom": "支", "status": "待发",
         "eta": f"{BASE_DATE + timedelta(days=3)}", "vessel": "空运", "port": "上海浦东"},
        {"plan_no": "ASAP202607003", "supplier_code": "S-ZB-JP",
         "material_code": "M-ZB-M001", "material_name": "敏睿油性记号笔",
         "qty": 80000, "uom": "支", "status": "已到货",
         "eta": f"{BASE_DATE - timedelta(days=1)}", "vessel": "海运 长江号", "port": "深圳盐田港"},
    ]

    # 补货建议（关联 ERP 库存 M-ZB-）
    replenishment_suggestions = [
        {"suggestion_no": "ASRS202607001", "material_code": "M-ZB-G001",
         "material_name": "敏睿中性笔 0.5 黑", "current_stock": 28000, "safety_stock": 30000,
         "suggested_qty": 120000, "suggested_supplier": "S-ZB-JP",
         "reason": "库存低于安全线+开学季备货", "urgency": "高"},
        {"suggestion_no": "ASRS202607002", "material_code": "M-ZB-G010",
         "material_name": "敏睿中性笔 0.4 蓝", "current_stock": 4000, "safety_stock": 12000,
         "suggested_qty": 60000, "suggested_supplier": "S-ZB-JP",
         "reason": "新品库存偏低+电商大促", "urgency": "高"},
        {"suggestion_no": "ASRS202607003", "material_code": "M-ZB-B002",
         "material_name": "敏睿细字圆珠笔", "current_stock": 6000, "safety_stock": 4000,
         "suggested_qty": 0, "suggested_supplier": None,
         "reason": "滞销超储，建议缓采+定向清库", "urgency": "缓采"},
        {"suggestion_no": "ASRS202607004", "material_code": "M-ZB-R001",
         "material_name": "敏睿替换芯 0.5", "current_stock": 15000, "safety_stock": 20000,
         "suggested_qty": 100000, "suggested_supplier": "S-ZB-JP",
         "reason": "常规补货", "urgency": "常规"},
    ]

    # 进口交期快照（异动检测）
    leadtime_snapshots = [
        {"snapshot_no": "ASLS202607001", "supplier_code": "S-ZB-LOG",
         "material_code": "M-ZB-G001", "committed_leadtime": 12,
         "actual_leadtime": 16, "diff_days": 4, "snapshot_date": f"{BASE_DATE}",
         "note": "海运船期延后+港口压港"},
        {"snapshot_no": "ASLS202607002", "supplier_code": "S-ZB-LOG2",
         "material_code": "M-ZB-G010", "committed_leadtime": 3,
         "actual_leadtime": 2, "diff_days": -1, "snapshot_date": f"{BASE_DATE}",
         "note": "空运正常"},
        {"snapshot_no": "ASLS202607003", "supplier_code": "S-ZB-JP",
         "material_code": "M-ZB-M001", "committed_leadtime": 12,
         "actual_leadtime": 14, "diff_days": 2, "snapshot_date": f"{BASE_DATE}",
         "note": "日本发货端排产延迟"},
    ]

    # 到货验收（货物校验）
    material_validations = [
        {"validation_no": "ASMV202607001", "material_code": "M-ZB-G001",
         "supplier_code": "S-ZB-JP", "batch_no": "BAT202607001",
         "declared_spec": "中性笔 0.5 黑 12 万支", "actual_spec": "中性笔 0.5 黑 12 万支",
         "result": "合格", "validated_at": f"{BASE_DATE - timedelta(days=2)}T10:00:00", "validator": "scm-customs"},
        {"validation_no": "ASMV202607002", "material_code": "M-ZB-M001",
         "supplier_code": "S-ZB-JP", "batch_no": "BAT202607003",
         "declared_spec": "油性记号笔 8 万支", "actual_spec": "油性记号笔 8 万支",
         "result": "合格", "validated_at": f"{BASE_DATE - timedelta(days=1)}T14:00:00", "validator": "scm-customs"},
        {"validation_no": "ASMV202607003", "material_code": "M-ZB-B001",
         "supplier_code": "S-ZB-JP", "batch_no": "BAT202607002",
         "declared_spec": "金属圆珠笔 2 万支", "actual_spec": "实到 1 万支（短装）",
         "result": "不合格", "validated_at": f"{BASE_DATE}T09:00:00", "validator": "scm-customs"},
    ]

    return ScmData(
        suppliers=suppliers, supplier_by_code=supplier_by_code,
        quotations=quotations, quotation_by_no=quotation_by_no,
        capacity_calendar=capacity_calendar, fabric_arrival_plans=fabric_arrival_plans,
        replenishment_suggestions=replenishment_suggestions,
        leadtime_snapshots=leadtime_snapshots,
        material_validations=material_validations,
        scrap_grades=[], scrap_grade_by_code={},
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[ScmData]({
    "starclothing": _build_starclothing,
    "agileac": _build_agileac,
    "agilesteel": _build_agilesteel,
    "agilestationery": _build_agilestationery,
})


def load(tenant: str) -> ScmData:
    """按 tenant 取数据集；首次调用时触发构建并缓存。未知 tenant 抛 KeyError。"""
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()
