"""ERP 多租户确定性种子数据——minrui（机械/电子制造）+ starclothing（服装）。

固定种子 + 固定基准日，重启可复现。每个 tenant 一份 ``ErpData``，覆盖供应商 /
采购订单 / 物料 / 库存 / 仓库 / 库存出入库 / 应付 / 财务凭证 / 成本中心 / 生产成本。
生产成本 ``work_order_no`` 与销售出库 ``so_no`` 跨系统引用同 tenant 的 MES 工单
与 CRM 销售订单，形成联动。

多租户访问：``load(tenant) -> ErpData``。模块级别名（``SUPPLIERS`` 等）默认指向 minrui，
向后兼容未改造的调用方与跨系统延迟导入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry, TenantBuilding

BASE_DATE: date = date(2026, 6, 29)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class ErpData:
    suppliers: list[dict]
    supplier_by_code: dict[str, dict]
    materials: list[dict]
    material_by_code: dict[str, dict]
    warehouses: list[dict]
    warehouse_by_code: dict[str, dict]
    purchase_orders: list[dict]
    purchase_order_lines: list[dict]
    po_by_no: dict[str, dict]
    inventory: list[dict]
    stock_movements: list[dict]
    payables: list[dict]
    vouchers: list[dict]
    cost_centers: list[dict]
    production_costs: list[dict]


# ───────────────────────── 跨系统取数（同 tenant） ─────────────────────────


def _mes_work_orders(tenant: str) -> list[str]:
    """跨系统取同 tenant 的 MES 工单号；MES 未就绪或循环构造中时回退占位。"""
    try:
        from mock.systems.mes.data import load as _load_mes
        d = _load_mes(tenant)
        return [w["work_order_no"] for w in d.work_orders]
    except (Exception, TenantBuilding):  # noqa: BLE001
        return ["WO20260607"]


def _crm_sales_orders(tenant: str) -> list[str]:
    try:
        from mock.systems.crm.data import load as _load_crm
        d = _load_crm(tenant)
        return [s["so_no"] for s in d.sales_orders]
    except (Exception, TenantBuilding):  # noqa: BLE001
        return ["SO20260005"]


# ───────────────────────── minrui（机械/电子制造） ─────────────────────────


def _build_minrui() -> ErpData:
    R = D.rng(20240820)

    suppliers = [
        {"code": "S-MAT-001", "name": "宁波金田铜业", "category": "原材料", "contact": "李采购",
         "phone": "13800001111", "payment_terms_days": 45, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-MAT-002", "name": "深圳崇达电路", "category": "原材料", "contact": "赵采购",
         "phone": "13800002222", "payment_terms_days": 30, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-OUT-010", "name": "东莞鸿辉外协", "category": "外协加工", "contact": "孙采购",
         "phone": "13800003333", "payment_terms_days": 30, "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "S-AUX-021", "name": "苏州包装制品", "category": "辅料包装", "contact": "周采购",
         "phone": "13800004444", "payment_terms_days": 60, "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "S-FRG-051", "name": "Bosch Rexroth Supply", "category": "原材料", "contact": "Chen Yu",
         "phone": "+49-9352-xxx", "payment_terms_days": 30, "currency": "USD", "rating": "A", "status": "合作中"},
    ]
    supplier_by_code = {s["code"]: s for s in suppliers}

    materials = [
        {"material_code": "M-COPPER-01", "name": "紫铜线材 φ0.5", "category": "原材料", "uom": "kg",
         "default_supplier": "S-MAT-001", "safety_stock": 200, "unit_cost": 58.0},
        {"material_code": "M-PCB-02", "name": "控制板 PCB", "category": "原材料", "uom": "片",
         "default_supplier": "S-MAT-002", "safety_stock": 150, "unit_cost": 42.0},
        {"material_code": "M-STEEL-03", "name": "铝合金外壳坯料", "category": "原材料", "uom": "件",
         "default_supplier": "S-MAT-001", "safety_stock": 80, "unit_cost": 35.0},
        {"material_code": "M-BOX-04", "name": "成品包装箱", "category": "辅料包装", "uom": "个",
         "default_supplier": "S-AUX-021", "safety_stock": 300, "unit_cost": 6.5},
        {"material_code": "P-MOTOR-100", "name": "伺服电机 100W（成品）", "category": "半成品/成品", "uom": "台",
         "default_supplier": None, "safety_stock": 50, "unit_cost": 0.0},
        {"material_code": "P-DRIVE-200", "name": "驱动器 200W（成品）", "category": "半成品/成品", "uom": "台",
         "default_supplier": None, "safety_stock": 40, "unit_cost": 0.0},
        {"material_code": "P-SENSOR-50", "name": "位移传感器 50mm（成品）", "category": "半成品/成品", "uom": "支",
         "default_supplier": None, "safety_stock": 60, "unit_cost": 0.0},
    ]
    material_by_code = {m["material_code"]: m for m in materials}

    warehouses = [
        {"code": "WH-RAW", "name": "原料仓", "type": "原料仓"},
        {"code": "WH-WIP", "name": "半成品仓", "type": "半成品仓"},
        {"code": "WH-FG", "name": "成品仓", "type": "成品仓"},
        {"code": "WH-AUX", "name": "辅料仓", "type": "辅料仓"},
    ]
    warehouse_by_code = {w["code"]: w for w in warehouses}

    po_status = ["草稿", "已下单", "部分到货", "已入库", "关闭"]
    purchase_orders: list[dict] = []
    purchase_order_lines: list[dict] = []
    for i in range(6):
        sup = D.pick(R, suppliers)
        po_no = f"PR{D.pad(20260000 + i * 71 + 13)}"
        line_count = D.randint(R, 1, 3)
        total = 0.0
        for li in range(line_count):
            mat = D.pick(R, [m for m in materials if m["default_supplier"] in (sup["code"], None)])
            qty = D.randint(R, 50, 500)
            price = D.randfloat(R, 5.0, 120.0)
            received = D.randint(R, 0, qty)
            total += round(price * qty, 2)
            purchase_order_lines.append({
                "po_no": po_no, "line_no": li + 1,
                "material_code": mat["material_code"], "material_name": mat["name"],
                "qty": qty, "uom": mat["uom"], "unit_price": price, "received_qty": received,
            })
        purchase_orders.append({
            "po_no": po_no, "supplier_code": sup["code"], "supplier_name": sup["name"],
            "buyer": D.pick(R, ["采购-张", "采购-王", "采购-陈"]),
            "currency": sup["currency"], "total_amount": round(total, 2),
            "status": D.pick(R, po_status),
            "order_date": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 40))}",
            "expected_date": f"{BASE_DATE + timedelta(days=D.randint(R, -3, 15))}",
        })
    po_by_no = {p["po_no"]: p for p in purchase_orders}

    inventory: list[dict] = []
    for mat in materials:
        wh = "WH-FG" if mat["material_code"].startswith("P-") else (
            "WH-AUX" if mat["category"] == "辅料包装" else "WH-RAW")
        stock = D.randint(R, 0, 600)
        inventory.append({
            "material_code": mat["material_code"], "material_name": mat["name"],
            "warehouse": wh, "stock_qty": stock,
            "available_qty": max(0, stock - D.randint(R, 0, 50)),
            "safety_stock": mat["safety_stock"], "uom": mat["uom"],
        })

    move_types = ["采购入库", "生产领料", "生产入库", "销售出库", "调拨"]
    mes_wos = _mes_work_orders("minrui")
    crm_sos = _crm_sales_orders("minrui")
    stock_movements: list[dict] = []
    for i in range(14):
        mt = D.pick(R, move_types)
        if mt == "采购入库":
            pol = D.pick(R, purchase_order_lines)
            mat = pol["material_code"]; ref = pol["po_no"]; wh = "WH-RAW"
        elif mt == "销售出库":
            mat = D.pick(R, [m for m in materials if m["material_code"].startswith("P-")])["material_code"]
            ref = D.pick(R, crm_sos); wh = "WH-FG"
        elif mt == "生产入库":
            mat = D.pick(R, [m for m in materials if m["material_code"].startswith("P-")])["material_code"]
            ref = D.pick(R, mes_wos); wh = "WH-FG"
        elif mt == "生产领料":
            mat = D.pick(R, [m for m in materials if not m["material_code"].startswith("P-")])["material_code"]
            ref = D.pick(R, mes_wos); wh = "WH-RAW"
        else:
            mat = D.pick(R, materials)["material_code"]
            ref = "TR" + D.pad(D.randint(R, 1000, 9999)); wh = D.pick(R, warehouses)["code"]
        stock_movements.append({
            "movement_id": f"MV{D.pad(20260000 + i * 29)}",
            "type": mt, "material_code": mat, "warehouse": wh,
            "qty": D.randint(R, 5, 200), "uom": material_by_code[mat]["uom"], "ref_no": ref,
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 12))}T{D.pad(D.randint(R, 8, 18))}:00:00",
        })

    payables: list[dict] = []
    for i in range(6):
        sup = D.pick(R, suppliers)
        amt = D.randint(R, 20_000, 400_000)
        due = BASE_DATE + timedelta(days=D.randint(R, -20, 35))
        overdue = (BASE_DATE - due).days > 0
        payables.append({
            "payable_id": f"AP{D.pad(20260000 + i * 19)}",
            "supplier_code": sup["code"], "supplier_name": sup["name"],
            "invoice_no": f"INV{D.pad(D.randint(R, 20250000, 20269999))}",
            "amount": amt, "currency": sup["currency"],
            "billing_date": f"{BASE_DATE - timedelta(days=D.randint(R, 20, 60))}",
            "due_date": f"{due}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已付款"]),
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    vouchers: list[dict] = []
    for i in range(5):
        period = f"{BASE_DATE.year}-{D.pad(D.randint(R, 1, 6))}"
        vouchers.append({
            "voucher_no": f"FV{D.pad(20260000 + i * 37)}",
            "period": period,
            "entry_date": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 25))}",
            "summary": D.pick(R, ["采购入库核算", "销售出库核算", "领料成本结转", "薪酬计提", "折旧计提"]),
            "debit_total": D.randint(R, 10_000, 300_000),
            "credit_total": D.randint(R, 10_000, 300_000),
            "status": D.pick(R, ["草稿", "已复核", "已过账"]),
        })

    cost_centers = [
        {"code": "CC-MACH", "name": "机加工车间", "type": "车间"},
        {"code": "CC-ASSY", "name": "装配车间", "type": "车间"},
        {"code": "CC-SURF", "name": "表面处理车间", "type": "车间"},
        {"code": "CC-SA", "name": "销售部", "type": "部门"},
        {"code": "CC-ADM", "name": "管理部", "type": "部门"},
    ]

    production_costs: list[dict] = []
    for i in range(8):
        won = D.pick(R, mes_wos)
        mat_cost = D.randfloat(R, 2000, 30000)
        labor = D.randfloat(R, 800, 6000)
        oh = D.randfloat(R, 500, 4000)
        production_costs.append({
            "cost_id": f"PC{D.pad(20260000 + i * 23)}",
            "work_order_no": won,
            "cost_center": D.pick(R, [c["code"] for c in cost_centers if c["type"] == "车间"]),
            "period": f"{BASE_DATE.year}-{D.pad(D.randint(R, 1, 6))}",
            "material_cost": mat_cost, "labor_cost": labor, "overhead": oh,
            "total_cost": round(mat_cost + labor + oh, 2),
        })

    return ErpData(
        suppliers=suppliers, supplier_by_code=supplier_by_code,
        materials=materials, material_by_code=material_by_code,
        warehouses=warehouses, warehouse_by_code=warehouse_by_code,
        purchase_orders=purchase_orders, purchase_order_lines=purchase_order_lines,
        po_by_no=po_by_no, inventory=inventory, stock_movements=stock_movements,
        payables=payables, vouchers=vouchers, cost_centers=cost_centers,
        production_costs=production_costs,
    )


# ───────────────────────── starclothing（服装） ─────────────────────────


def _build_starclothing() -> ErpData:
    """星图服装口径 ERP 数据：面料/辅料供应商、面料采购、库存与出入库、应付与成本。"""
    R = D.rng(20241115)

    suppliers = [
        {"code": "XS-FAB-001", "name": "绍兴盛峰纺织", "category": "面料", "contact": "陈布料",
         "phone": "13900001111", "payment_terms_days": 45, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "XS-FAB-002", "name": "吴江恒宇面料", "category": "面料", "contact": "林面料",
         "phone": "13900002222", "payment_terms_days": 30, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "XS-FAB-003", "name": "桐乡羊毛纺织", "category": "面料", "contact": "沈羊绒",
         "phone": "13900003333", "payment_terms_days": 30, "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "XS-ACC-010", "name": "YKK 拉链（深圳）", "category": "辅料", "contact": "赵辅料",
         "phone": "13900004444", "payment_terms_days": 30, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "XS-ACC-011", "name": "福建浔兴拉链", "category": "辅料", "contact": "施拉链",
         "phone": "13900005555", "payment_terms_days": 60, "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "XS-ACC-020", "name": "温州纽扣五金", "category": "辅料", "contact": "胡纽扣",
         "phone": "13900006666", "payment_terms_days": 45, "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "XS-PRT-030", "name": "广州印花外协", "category": "外协加工", "contact": "潘印花",
         "phone": "13900007777", "payment_terms_days": 30, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "XS-WSH-031", "name": "东莞水洗厂", "category": "外协加工", "contact": "邓水洗",
         "phone": "13900008888", "payment_terms_days": 30, "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "XS-PKG-040", "name": "苏州包装制品", "category": "辅料包装", "contact": "周包装",
         "phone": "13900009999", "payment_terms_days": 60, "currency": "CNY", "rating": "B", "status": "合作中"},
    ]
    supplier_by_code = {s["code"]: s for s in suppliers}

    materials = [
        {"material_code": "M-WOOL-DBL-360", "name": "双面呢 360g/㎡ 30%羊绒 70%羊毛", "category": "面料", "uom": "m",
         "default_supplier": "XS-FAB-003", "safety_stock": 300, "unit_cost": 168.0},
        {"material_code": "M-SHELL-3L-150", "name": "三层复合面料 150D 防水透气膜", "category": "面料", "uom": "m",
         "default_supplier": "XS-FAB-001", "safety_stock": 500, "unit_cost": 92.0},
        {"material_code": "M-TC-180", "name": "T/C 布 65/35 180g 平纹", "category": "面料", "uom": "m",
         "default_supplier": "XS-FAB-002", "safety_stock": 1000, "unit_cost": 18.5},
        {"material_code": "M-FLEECE-280", "name": "摇粒绒 280g 抓绒", "category": "面料", "uom": "m",
         "default_supplier": "XS-FAB-001", "safety_stock": 400, "unit_cost": 35.0},
        {"material_code": "M-ZIP-YKK-5", "name": "YKK 5# 树脂拉链 3:1 双开", "category": "辅料", "uom": "条",
         "default_supplier": "XS-ACC-010", "safety_stock": 2000, "unit_cost": 6.8},
        {"material_code": "M-ZIP-XJ-3", "name": "浔兴 3# 尼龙拉链 单开", "category": "辅料", "uom": "条",
         "default_supplier": "XS-ACC-011", "safety_stock": 3000, "unit_cost": 1.2},
        {"material_code": "M-BTN-RESIN", "name": "树脂四眼纽扣 18L", "category": "辅料", "uom": "粒",
         "default_supplier": "XS-ACC-020", "safety_stock": 5000, "unit_cost": 0.45},
        {"material_code": "M-INTER-030", "name": "30D 有光衬 18g/㎡", "category": "辅料", "uom": "m",
         "default_supplier": "XS-FAB-002", "safety_stock": 800, "unit_cost": 2.8},
        {"material_code": "M-PKG-POLY", "name": "PE 平口袋 30×40", "category": "辅料包装", "uom": "个",
         "default_supplier": "XS-PKG-040", "safety_stock": 5000, "unit_cost": 0.18},
        {"material_code": "M-PKG-CTN", "name": "5 层瓦楞纸箱 50×35×30", "category": "辅料包装", "uom": "个",
         "default_supplier": "XS-PKG-040", "safety_stock": 800, "unit_cost": 4.2},
    ]
    material_by_code = {m["material_code"]: m for m in materials}

    warehouses = [
        {"code": "WH-FAB", "name": "面料仓", "type": "原料仓"},
        {"code": "WH-ACC", "name": "辅料仓", "type": "原料仓"},
        {"code": "WH-WIP", "name": "半成品仓", "type": "半成品仓"},
        {"code": "WH-FG", "name": "成品仓", "type": "成品仓"},
        {"code": "WH-PKG", "name": "包装辅料仓", "type": "辅料仓"},
    ]
    warehouse_by_code = {w["code"]: w for w in warehouses}

    po_status = ["草稿", "已下单", "部分到货", "已入库", "关闭"]
    purchase_orders: list[dict] = []
    purchase_order_lines: list[dict] = []
    for i in range(8):
        sup = D.pick(R, suppliers)
        po_no = f"XPO{D.pad(20260000 + i * 53 + 7)}"
        line_count = D.randint(R, 1, 3)
        total = 0.0
        candidates = [m for m in materials if m["default_supplier"] in (sup["code"], None)]
        if not candidates:
            candidates = materials
        for li in range(line_count):
            mat = D.pick(R, candidates)
            qty = D.randint(R, 100, 2000)
            price = D.randfloat(R, 0.5, 200.0)
            received = D.randint(R, 0, qty)
            total += round(price * qty, 2)
            purchase_order_lines.append({
                "po_no": po_no, "line_no": li + 1,
                "material_code": mat["material_code"], "material_name": mat["name"],
                "qty": qty, "uom": mat["uom"], "unit_price": price, "received_qty": received,
            })
        purchase_orders.append({
            "po_no": po_no, "supplier_code": sup["code"], "supplier_name": sup["name"],
            "buyer": D.pick(R, ["采购-陈", "采购-周", "采购-林"]),
            "currency": sup["currency"], "total_amount": round(total, 2),
            "status": D.pick(R, po_status),
            "order_date": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 45))}",
            "expected_date": f"{BASE_DATE + timedelta(days=D.randint(R, -5, 20))}",
        })
    po_by_no = {p["po_no"]: p for p in purchase_orders}

    inventory: list[dict] = []
    for mat in materials:
        if mat["category"] == "面料":
            wh = "WH-FAB"
        elif mat["category"] == "辅料":
            wh = "WH-ACC"
        elif mat["category"] == "辅料包装":
            wh = "WH-PKG"
        else:
            wh = "WH-WIP"
        stock = D.randint(R, 0, 1200)
        inventory.append({
            "material_code": mat["material_code"], "material_name": mat["name"],
            "warehouse": wh, "stock_qty": stock,
            "available_qty": max(0, stock - D.randint(R, 0, 80)),
            "safety_stock": mat["safety_stock"], "uom": mat["uom"],
        })

    move_types = ["采购入库", "生产领料", "调拨"]
    mes_wos = _mes_work_orders("starclothing")
    crm_sos = _crm_sales_orders("starclothing")
    stock_movements: list[dict] = []
    for i in range(18):
        mt = D.pick(R, move_types)
        if mt == "采购入库":
            pol = D.pick(R, purchase_order_lines)
            mat = pol["material_code"]; ref = pol["po_no"]
            cat = material_by_code[mat]["category"]
            wh = "WH-PKG" if cat == "辅料包装" else ("WH-ACC" if cat == "辅料" else "WH-FAB")
        elif mt == "生产领料":
            mat = D.pick(R, [m for m in materials if m["category"] in ("面料", "辅料")])["material_code"]
            ref = D.pick(R, mes_wos)
            cat = material_by_code[mat]["category"]
            wh = "WH-ACC" if cat == "辅料" else "WH-FAB"
        else:
            mat = D.pick(R, materials)["material_code"]
            ref = "TR" + D.pad(D.randint(R, 1000, 9999)); wh = D.pick(R, warehouses)["code"]
        stock_movements.append({
            "movement_id": f"XMV{D.pad(20260000 + i * 31)}",
            "type": mt, "material_code": mat, "warehouse": wh,
            "qty": D.randint(R, 10, 600), "uom": material_by_code[mat]["uom"], "ref_no": ref,
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 14))}T{D.pad(D.randint(R, 8, 18))}:00:00",
        })

    payables: list[dict] = []
    for i in range(8):
        sup = D.pick(R, suppliers)
        amt = D.randint(R, 30_000, 600_000)
        due = BASE_DATE + timedelta(days=D.randint(R, -25, 40))
        overdue = (BASE_DATE - due).days > 0
        payables.append({
            "payable_id": f"XAP{D.pad(20260000 + i * 17)}",
            "supplier_code": sup["code"], "supplier_name": sup["name"],
            "invoice_no": f"XINV{D.pad(D.randint(R, 20250000, 20269999))}",
            "amount": amt, "currency": sup["currency"],
            "billing_date": f"{BASE_DATE - timedelta(days=D.randint(R, 20, 70))}",
            "due_date": f"{due}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已付款"]),
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    vouchers: list[dict] = []
    for i in range(7):
        period = f"{BASE_DATE.year}-{D.pad(D.randint(R, 1, 6))}"
        vouchers.append({
            "voucher_no": f"XFV{D.pad(20260000 + i * 29)}",
            "period": period,
            "entry_date": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 30))}",
            "summary": D.pick(R, ["面料采购入库核算", "成衣销售出库核算", "辅料领料结转", "外协加工费计提", "包装辅料领用"]),
            "debit_total": D.randint(R, 15_000, 400_000),
            "credit_total": D.randint(R, 15_000, 400_000),
            "status": D.pick(R, ["草稿", "已复核", "已过账"]),
        })

    cost_centers = [
        {"code": "CC-CUT", "name": "裁剪车间", "type": "车间"},
        {"code": "CC-SEW", "name": "车缝车间", "type": "车间"},
        {"code": "CC-PRT", "name": "印花车间", "type": "车间"},
        {"code": "CC-FIN", "name": "后整车间", "type": "车间"},
        {"code": "CC-PKG", "name": "包装车间", "type": "车间"},
        {"code": "CC-DESIGN", "name": "设计开发部", "type": "部门"},
        {"code": "CC-SA", "name": "销售部", "type": "部门"},
    ]

    production_costs: list[dict] = []
    for i in range(10):
        won = D.pick(R, mes_wos)
        mat_cost = D.randfloat(R, 3000, 80000)
        labor = D.randfloat(R, 1200, 9000)
        oh = D.randfloat(R, 600, 5000)
        production_costs.append({
            "cost_id": f"XPC{D.pad(20260000 + i * 19)}",
            "work_order_no": won,
            "cost_center": D.pick(R, [c["code"] for c in cost_centers if c["type"] == "车间"]),
            "period": f"{BASE_DATE.year}-{D.pad(D.randint(R, 1, 6))}",
            "material_cost": mat_cost, "labor_cost": labor, "overhead": oh,
            "total_cost": round(mat_cost + labor + oh, 2),
        })

    return ErpData(
        suppliers=suppliers, supplier_by_code=supplier_by_code,
        materials=materials, material_by_code=material_by_code,
        warehouses=warehouses, warehouse_by_code=warehouse_by_code,
        purchase_orders=purchase_orders, purchase_order_lines=purchase_order_lines,
        po_by_no=po_by_no, inventory=inventory, stock_movements=stock_movements,
        payables=payables, vouchers=vouchers, cost_centers=cost_centers,
        production_costs=production_costs,
    )


# ───────────────────────── agileac（敏睿空调） ─────────────────────────


def _build_agileac() -> ErpData:
    """敏睿空调 ERP 数据：压缩机/换热器/阀件/制冷剂供应商 + 5 类配件物料 +
    采购订单/库存/出入库/应付/凭证（含 SAL-02 演示凭证 BV-AG-2026-0512）/成本中心/生产成本。"""
    R = D.rng(20260104)

    suppliers = [
        {"code": "S-COMP-001", "name": "上海海立压缩机", "category": "核心配件", "contact": "陈采购",
         "phone": "13800001111", "payment_terms_days": 45, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-COMP-002", "name": "广州万宝压缩机", "category": "核心配件", "contact": "周采购",
         "phone": "13800002222", "payment_terms_days": 30, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-HEX-001", "name": "江苏双良换热器", "category": "热交换器", "contact": "林采购",
         "phone": "13800003333", "payment_terms_days": 30, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-HEX-002", "name": "浙江盾安换热器", "category": "热交换器", "contact": "邓采购",
         "phone": "13800004444", "payment_terms_days": 45, "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "S-VALVE-001", "name": "浙江三花电子膨胀阀", "category": "阀件", "contact": "赵采购",
         "phone": "13800005555", "payment_terms_days": 30, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-REF-001", "name": "中化蓝天制冷剂", "category": "制冷剂", "contact": "黄采购",
         "phone": "13800006666", "payment_terms_days": 30, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-PSB-001", "name": "深圳鸿信电源板", "category": "电气件", "contact": "吴采购",
         "phone": "13800007777", "payment_terms_days": 45, "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "S-PKG-001", "name": "苏州瓦楞包装", "category": "辅料包装", "contact": "孙包装",
         "phone": "13800008888", "payment_terms_days": 60, "currency": "CNY", "rating": "B", "status": "合作中"},
    ]
    supplier_by_code = {s["code"]: s for s in suppliers}

    # 5 类配件主数据（与 PLM agileac fabrics 同码，对齐跨系统 BOM）
    materials = [
        {"material_code": "M-COMP-GT-24K", "name": "24K 转子压缩机", "category": "核心配件", "uom": "台",
         "default_supplier": "S-COMP-001", "safety_stock": 100, "unit_cost": 580.0},
        {"material_code": "M-COND-FIN-30", "name": "30 平方英寸翅片冷凝器", "category": "热交换器", "uom": "套",
         "default_supplier": "S-HEX-001", "safety_stock": 200, "unit_cost": 280.0},
        {"material_code": "M-EVAP-FIN-30", "name": "30 平方英寸翅片蒸发器", "category": "热交换器", "uom": "套",
         "default_supplier": "S-HEX-001", "safety_stock": 200, "unit_cost": 260.0},
        {"material_code": "M-EEV-15", "name": "15 步电子膨胀阀", "category": "阀件", "uom": "只",
         "default_supplier": "S-VALVE-001", "safety_stock": 300, "unit_cost": 95.0},
        {"material_code": "M-RF-R410A", "name": "R410A 环保冷媒", "category": "制冷剂", "uom": "kg",
         "default_supplier": "S-REF-001", "safety_stock": 500, "unit_cost": 65.0},
        {"material_code": "M-PSB-CTL", "name": "空调主控板", "category": "电气件", "uom": "块",
         "default_supplier": "S-PSB-001", "safety_stock": 100, "unit_cost": 220.0},
        {"material_code": "M-CAP-30UF", "name": "30μF 启动电容", "category": "电气件", "uom": "只",
         "default_supplier": "S-PSB-001", "safety_stock": 500, "unit_cost": 18.0},
        {"material_code": "M-PKG-CTN-AC", "name": "空调包装箱 60×40×35", "category": "辅料包装", "uom": "个",
         "default_supplier": "S-PKG-001", "safety_stock": 800, "unit_cost": 8.5},
    ]
    material_by_code = {m["material_code"]: m for m in materials}

    warehouses = [
        {"code": "WH-AG-COMP", "name": "压缩机仓", "type": "原料仓"},
        {"code": "WH-AG-HEX", "name": "换热器仓", "type": "原料仓"},
        {"code": "WH-AG-VALVE", "name": "阀件仓", "type": "原料仓"},
        {"code": "WH-AG-REF", "name": "制冷剂仓", "type": "原料仓"},
        {"code": "WH-AG-PSB", "name": "电气件仓", "type": "原料仓"},
        {"code": "WH-AG-WIP", "name": "半成品仓", "type": "半成品仓"},
        {"code": "WH-AG-FG", "name": "成品仓", "type": "成品仓"},
        {"code": "WH-AG-PKG", "name": "包装辅料仓", "type": "辅料仓"},
    ]
    warehouse_by_code = {w["code"]: w for w in warehouses}

    po_status = ["草稿", "已下单", "部分到货", "已入库", "关闭"]
    purchase_orders: list[dict] = []
    purchase_order_lines: list[dict] = []
    po_specs = [
        ("AGPO20260001", "S-COMP-001", "M-COMP-GT-24K", 500, 580.0, "已入库"),
        ("AGPO20260002", "S-COMP-001", "M-COMP-GT-24K", 300, 580.0, "部分到货"),
        ("AGPO20260003", "S-HEX-001", "M-COND-FIN-30", 800, 280.0, "已入库"),
        ("AGPO20260004", "S-HEX-001", "M-EVAP-FIN-30", 800, 260.0, "已入库"),
        ("AGPO20260005", "S-VALVE-001", "M-EEV-15", 1000, 95.0, "已入库"),
        ("AGPO20260006", "S-REF-001", "M-RF-R410A", 3500, 65.0, "部分到货"),
        ("AGPO20260007", "S-PSB-001", "M-PSB-CTL", 200, 220.0, "已下单"),
        ("AGPO20260008", "S-PSB-001", "M-CAP-30UF", 2000, 18.0, "已入库"),
    ]
    for po_no, sup_code, mat_code, qty, price, status in po_specs:
        sup = supplier_by_code[sup_code]
        mat = material_by_code[mat_code]
        purchase_order_lines.append({
            "po_no": po_no, "line_no": 1,
            "material_code": mat_code, "material_name": mat["name"],
            "qty": qty, "uom": mat["uom"], "unit_price": price,
            "received_qty": int(qty * (1.0 if status == "已入库" else (0.5 if status == "部分到货" else 0))),
        })
        purchase_orders.append({
            "po_no": po_no, "supplier_code": sup_code, "supplier_name": sup["name"],
            "buyer": D.pick(R, ["采购-陈", "采购-周", "采购-林"]),
            "currency": sup["currency"], "total_amount": round(qty * price, 2),
            "status": status,
            "order_date": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 45))}",
            "expected_date": f"{BASE_DATE + timedelta(days=D.randint(R, -5, 20))}",
        })
    po_by_no = {p["po_no"]: p for p in purchase_orders}

    inventory: list[dict] = []
    inv_specs = [
        ("M-COMP-GT-24K", "WH-AG-COMP", 320, 100),
        ("M-COND-FIN-30", "WH-AG-HEX", 850, 200),
        ("M-EVAP-FIN-30", "WH-AG-HEX", 780, 200),
        ("M-EEV-15", "WH-AG-VALVE", 1200, 300),
        ("M-RF-R410A", "WH-AG-REF", 3500, 500),
        ("M-PSB-CTL", "WH-AG-PSB", 180, 100),
        ("M-CAP-30UF", "WH-AG-PSB", 1900, 500),
        ("M-PKG-CTN-AC", "WH-AG-PKG", 1200, 800),
    ]
    for mat_code, wh, stock, safety in inv_specs:
        mat = material_by_code[mat_code]
        inventory.append({
            "material_code": mat_code, "material_name": mat["name"],
            "warehouse": wh, "stock_qty": stock,
            "available_qty": max(0, stock - D.randint(R, 0, 80)),
            "safety_stock": safety, "uom": mat["uom"],
        })

    move_types = ["采购入库", "生产领料", "调拨"]
    mes_wos = _mes_work_orders("agileac")
    crm_sos = _crm_sales_orders("agileac")
    stock_movements: list[dict] = []
    for i in range(18):
        mt = D.pick(R, move_types)
        if mt == "采购入库":
            pol = D.pick(R, purchase_order_lines)
            mat = pol["material_code"]; ref = pol["po_no"]
            cat = material_by_code[mat]["category"]
            wh = ("WH-AG-COMP" if cat == "核心配件" else
                  "WH-AG-HEX" if cat == "热交换器" else
                  "WH-AG-VALVE" if cat == "阀件" else
                  "WH-AG-REF" if cat == "制冷剂" else
                  "WH-AG-PSB" if cat == "电气件" else "WH-AG-PKG")
        elif mt == "生产领料":
            mat = D.pick(R, [m for m in materials if m["category"] in ("核心配件", "热交换器", "阀件", "制冷剂", "电气件")])["material_code"]
            ref = D.pick(R, mes_wos)
            cat = material_by_code[mat]["category"]
            wh = ("WH-AG-COMP" if cat == "核心配件" else
                  "WH-AG-HEX" if cat == "热交换器" else
                  "WH-AG-VALVE" if cat == "阀件" else
                  "WH-AG-REF" if cat == "制冷剂" else "WH-AG-PSB")
        else:
            mat = D.pick(R, materials)["material_code"]
            ref = "TR" + D.pad(D.randint(R, 1000, 9999)); wh = D.pick(R, warehouses)["code"]
        stock_movements.append({
            "movement_id": f"AGMV{D.pad(20260000 + i * 31)}",
            "type": mt, "material_code": mat, "warehouse": wh,
            "qty": D.randint(R, 10, 600), "uom": material_by_code[mat]["uom"], "ref_no": ref,
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 14))}T{D.pad(D.randint(R, 8, 18), 2)}:00:00",
        })

    # 应付：含 2 条逾期，对应 AG-FIN-01 对账子任务
    payables: list[dict] = []
    payable_specs = [
        ("AGAP20260001", "S-COMP-001", 290_000, -45, 5),
        ("AGAP20260002", "S-HEX-001", 168_000, -40, -5),     # 逾期
        ("AGAP20260003", "S-VALVE-001", 95_000, -35, 10),
        ("AGAP20260004", "S-REF-001", 78_000, -30, -2),      # 逾期
        ("AGAP20260005", "S-HEX-001", 224_000, -25, 8),
        ("AGAP20260006", "S-COMP-001", 174_000, -20, 15),
        ("AGAP20260007", "S-PSB-001", 44_000, -15, 12),
        ("AGAP20260008", "S-PSB-001", 36_000, -10, 18),
    ]
    for pid, sup_code, amt, b_off, d_off in payable_specs:
        sup = supplier_by_code[sup_code]
        due = BASE_DATE + timedelta(days=d_off)
        overdue = (BASE_DATE - due).days > 0
        payables.append({
            "payable_id": pid,
            "supplier_code": sup_code, "supplier_name": sup["name"],
            "invoice_no": f"AGINV{D.pad(D.randint(R, 20250000, 20269999))}",
            "amount": amt, "currency": sup["currency"],
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已付款"]),
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    # 凭证：含 SAL-02 报销进度问答演示凭证 BV-AG-2026-0512（财务复核中，上周提交）
    voucher_specs = [
        ("BV-AG-2026-0501", "2026-04", -70, 290_000, 290_000, "已过账", "压缩机采购入库核算"),
        ("BV-AG-2026-0502", "2026-05", -50, 168_000, 168_000, "已过账", "冷凝器采购入库核算"),
        ("BV-AG-2026-0503", "2026-05", -40, 78_000, 78_000, "已复核", "R410A 冷媒采购入库核算"),
        ("BV-AG-2026-0512", "2026-07", 9, 6800, 6800, "财务复核中", "差旅费报销-7月"),
        ("BV-AG-2026-0513", "2026-06", -5, 224_000, 224_000, "草稿", "模块机冷凝器采购入库"),
        ("BV-AG-2026-0514", "2026-06", -3, 116_000, 116_000, "草稿", "风管机压缩机采购入库"),
    ]
    vouchers: list[dict] = []
    for vno, period, off, debit, credit, status, summary in voucher_specs:
        vouchers.append({
            "voucher_no": vno,
            "period": period,
            "entry_date": f"{BASE_DATE + timedelta(days=off)}",
            "summary": summary,
            "debit_total": debit, "credit_total": credit,
            "status": status,
        })

    cost_centers = [
        {"code": "CC-AG-RC", "name": "家用总装车间", "type": "车间"},
        {"code": "CC-AG-CC", "name": "商用总装车间", "type": "车间"},
        {"code": "CC-AG-TST", "name": "测试车间", "type": "车间"},
        {"code": "CC-AG-PIP", "name": "配管车间", "type": "车间"},
        {"code": "CC-AG-RND", "name": "研发部", "type": "部门"},
        {"code": "CC-AG-SA", "name": "销售部", "type": "部门"},
        {"code": "CC-AG-FIN", "name": "财务部", "type": "部门"},
        {"code": "CC-AG-HR", "name": "人力资源部", "type": "部门"},
        {"code": "CC-AG-IT", "name": "信息技术部", "type": "部门"},
        {"code": "CC-AG-ADM", "name": "管理部", "type": "部门"},
    ]

    # 生产成本：每条对应一条 MES agileac 工单
    production_costs: list[dict] = []
    cost_specs = [
        ("AGPC20260001", "AWO20260101", "CC-AG-RC", "2026-06", 290_000, 60_000, 30_000),
        ("AGPC20260002", "AWO20260103", "CC-AG-RC", "2026-06", 58_000, 15_000, 7_500),
        ("AGPC20260003", "AWO20260105", "CC-AG-RC", "2026-06", 174_000, 30_000, 15_000),
        ("AGPC20260004", "AWO20260108", "CC-AG-RC", "2026-06", 90_000, 20_000, 10_000),
        ("AGPC20260005", "AWO20260210", "CC-AG-CC", "2026-06", 410_000, 100_000, 50_000),
        ("AGPC20260006", "AWO20260215", "CC-AG-CC", "2026-06", 168_000, 40_000, 20_000),
        ("AGPC20260007", "AWO20260220", "CC-AG-CC", "2026-06", 1_045_000, 180_000, 90_000),
        ("AGPC20260008", "AWO20260211", "CC-AG-CC", "2026-06", 92_000, 25_000, 12_500),
    ]
    for cost_id, won, cc, period, mat_cost, labor, oh in cost_specs:
        production_costs.append({
            "cost_id": cost_id,
            "work_order_no": won,
            "cost_center": cc,
            "period": period,
            "material_cost": float(mat_cost),
            "labor_cost": float(labor),
            "overhead": float(oh),
            "total_cost": round(mat_cost + labor + oh, 2),
        })

    return ErpData(
        suppliers=suppliers, supplier_by_code=supplier_by_code,
        materials=materials, material_by_code=material_by_code,
        warehouses=warehouses, warehouse_by_code=warehouse_by_code,
        purchase_orders=purchase_orders, purchase_order_lines=purchase_order_lines,
        po_by_no=po_by_no, inventory=inventory, stock_movements=stock_movements,
        payables=payables, vouchers=vouchers, cost_centers=cost_centers,
        production_costs=production_costs,
    )


# ───────────────────────── agilesteel（敏睿钢铁） ─────────────────────────


def _build_agilesteel() -> ErpData:
    """敏睿钢铁 ERP 数据：铁矿石/焦炭/废钢/合金供应商 + 钢铁料主数据 + 采购订单/
    库存/出入库/应付/凭证（BV-AS-）/成本中心/分钢种炉次生产成本（PC-AS-，按炉次归集）。"""
    R = D.rng(20260620)

    suppliers = [
        {"code": "S-STEEL-ORE-01", "name": "澳大利亚 BHP 铁矿石", "category": "铁矿石",
         "contact": "王矿石", "phone": "13800010001", "payment_terms_days": 60,
         "currency": "USD", "rating": "A", "status": "合作中"},
        {"code": "S-STEEL-ORE-02", "name": "巴西淡水河谷铁矿石", "category": "铁矿石",
         "contact": "李矿石", "phone": "13800010002", "payment_terms_days": 60,
         "currency": "USD", "rating": "A", "status": "合作中"},
        {"code": "S-STEEL-COKE-01", "name": "山西焦煤集团", "category": "焦炭",
         "contact": "张焦炭", "phone": "13800010003", "payment_terms_days": 45,
         "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-STEEL-SCR-01", "name": "长三角废钢回收", "category": "废钢",
         "contact": "陈废钢", "phone": "13800010004", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "S-STEEL-SCR-02", "name": "华中再生资源", "category": "废钢",
         "contact": "周废钢", "phone": "13800010005", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "S-STEEL-ALY-01", "name": "中信合金材料", "category": "合金",
         "contact": "刘合金", "phone": "13800010006", "payment_terms_days": 45,
         "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-STEEL-REF-01", "name": "辽宁耐火材料", "category": "耐材",
         "contact": "赵耐材", "phone": "13800010007", "payment_terms_days": 45,
         "currency": "CNY", "rating": "B", "status": "合作中"},
    ]
    supplier_by_code = {s["code"]: s for s in suppliers}

    # 钢铁料主数据：铁矿石/焦炭/废钢/合金 + 钢坯/钢材成品
    materials = [
        {"material_code": "M-ORE-FINE", "name": "进口粉矿 62%", "category": "铁矿石", "uom": "吨",
         "default_supplier": "S-STEEL-ORE-01", "safety_stock": 50000, "unit_cost": 880.0},
        {"material_code": "M-ORE-LUMP", "name": "块矿 62%", "category": "铁矿石", "uom": "吨",
         "default_supplier": "S-STEEL-ORE-02", "safety_stock": 15000, "unit_cost": 960.0},
        {"material_code": "M-COKE", "name": "冶金焦炭", "category": "焦炭", "uom": "吨",
         "default_supplier": "S-STEEL-COKE-01", "safety_stock": 20000, "unit_cost": 2450.0},
        {"material_code": "M-SCR-HMS1", "name": "废钢 重废1型", "category": "废钢", "uom": "吨",
         "default_supplier": "S-STEEL-SCR-01", "safety_stock": 8000, "unit_cost": 2680.0},
        {"material_code": "M-SCR-HMS2", "name": "废钢 重废2型", "category": "废钢", "uom": "吨",
         "default_supplier": "S-STEEL-SCR-02", "safety_stock": 5000, "unit_cost": 2520.0},
        {"material_code": "M-ALY-SI", "name": "硅铁合金", "category": "合金", "uom": "吨",
         "default_supplier": "S-STEEL-ALY-01", "safety_stock": 800, "unit_cost": 6800.0},
        {"material_code": "M-ALY-MN", "name": "锰铁合金", "category": "合金", "uom": "吨",
         "default_supplier": "S-STEEL-ALY-01", "safety_stock": 600, "unit_cost": 8200.0},
        {"material_code": "M-ST-Q345B-Billet", "name": "Q345B 钢坯", "category": "钢坯", "uom": "吨",
         "default_supplier": None, "safety_stock": 3000, "unit_cost": 3950.0},
        {"material_code": "M-ST-45-Billet", "name": "45# 钢坯", "category": "钢坯", "uom": "吨",
         "default_supplier": None, "safety_stock": 2000, "unit_cost": 4100.0},
        {"material_code": "M-ST-Q345B-Bar", "name": "Q345B 螺纹钢成品", "category": "钢材成品", "uom": "吨",
         "default_supplier": None, "safety_stock": 5000, "unit_cost": 4280.0},
        {"material_code": "M-ST-45-Bar", "name": "45# 优质碳素钢成品", "category": "钢材成品", "uom": "吨",
         "default_supplier": None, "safety_stock": 3000, "unit_cost": 4650.0},
    ]
    material_by_code = {m["material_code"]: m for m in materials}

    warehouses = [
        {"code": "WH-AS-ORE", "name": "铁矿石料场", "type": "原料仓"},
        {"code": "WH-AS-COKE", "name": "焦炭仓", "type": "原料仓"},
        {"code": "WH-AS-SCR", "name": "废钢料场", "type": "原料仓"},
        {"code": "WH-AS-ALY", "name": "合金仓", "type": "原料仓"},
        {"code": "WH-AS-BILLET", "name": "钢坯库", "type": "半成品仓"},
        {"code": "WH-AS-FG", "name": "成品库", "type": "成品仓"},
    ]
    warehouse_by_code = {w["code"]: w for w in warehouses}

    po_status = ["草稿", "已下单", "部分到货", "已入库", "关闭"]
    purchase_orders: list[dict] = []
    purchase_order_lines: list[dict] = []
    po_specs = [
        ("ASPO20260001", "S-STEEL-ORE-01", "M-ORE-FINE", 50000, 880.0, "已入库"),
        ("ASPO20260002", "S-STEEL-ORE-02", "M-ORE-LUMP", 12000, 960.0, "部分到货"),
        ("ASPO20260003", "S-STEEL-COKE-01", "M-COKE", 15000, 2450.0, "已入库"),
        ("ASPO20260004", "S-STEEL-SCR-01", "M-SCR-HMS1", 8000, 2680.0, "部分到货"),
        ("ASPO20260005", "S-STEEL-SCR-02", "M-SCR-HMS2", 6000, 2520.0, "已下单"),
        ("ASPO20260006", "S-STEEL-ALY-01", "M-ALY-SI", 500, 6800.0, "已入库"),
        ("ASPO20260007", "S-STEEL-ALY-01", "M-ALY-MN", 400, 8200.0, "已入库"),
    ]
    for po_no, sup_code, mat_code, qty, price, status in po_specs:
        sup = supplier_by_code[sup_code]
        mat = material_by_code[mat_code]
        purchase_order_lines.append({
            "po_no": po_no, "line_no": 1,
            "material_code": mat_code, "material_name": mat["name"],
            "qty": qty, "uom": mat["uom"], "unit_price": price,
            "received_qty": int(qty * (1.0 if status == "已入库" else (0.5 if status == "部分到货" else 0))),
        })
        purchase_orders.append({
            "po_no": po_no, "supplier_code": sup_code, "supplier_name": sup["name"],
            "buyer": D.pick(R, ["采购-王", "采购-张", "采购-陈"]),
            "currency": sup["currency"], "total_amount": round(qty * price, 2),
            "status": status,
            "order_date": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 45))}",
            "expected_date": f"{BASE_DATE + timedelta(days=D.randint(R, -5, 20))}",
        })
    po_by_no = {p["po_no"]: p for p in purchase_orders}

    inventory: list[dict] = []
    inv_specs = [
        ("M-ORE-FINE", "WH-AS-ORE", 48000, 50000),
        ("M-ORE-LUMP", "WH-AS-ORE", 9000, 15000),
        ("M-COKE", "WH-AS-COKE", 14000, 20000),
        ("M-SCR-HMS1", "WH-AS-SCR", 4200, 8000),
        ("M-SCR-HMS2", "WH-AS-SCR", 3500, 5000),
        ("M-ALY-SI", "WH-AS-ALY", 450, 800),
        ("M-ALY-MN", "WH-AS-ALY", 380, 600),
        ("M-ST-Q345B-Billet", "WH-AS-BILLET", 2800, 3000),
        ("M-ST-45-Billet", "WH-AS-BILLET", 1900, 2000),
        ("M-ST-Q345B-Bar", "WH-AS-FG", 4600, 5000),
        ("M-ST-45-Bar", "WH-AS-FG", 2700, 3000),
    ]
    for mat_code, wh, stock, safety in inv_specs:
        mat = material_by_code[mat_code]
        inventory.append({
            "material_code": mat_code, "material_name": mat["name"],
            "warehouse": wh, "stock_qty": stock,
            "available_qty": max(0, stock - D.randint(R, 0, 200)),
            "safety_stock": safety, "uom": mat["uom"],
        })

    move_types = ["采购入库", "生产领料", "调拨"]
    mes_wos = _mes_work_orders("agilesteel")
    stock_movements: list[dict] = []
    for i in range(18):
        mt = D.pick(R, move_types)
        if mt == "采购入库":
            pol = D.pick(R, purchase_order_lines)
            mat = pol["material_code"]; ref = pol["po_no"]
            cat = material_by_code[mat]["category"]
            wh = ("WH-AS-ORE" if cat in ("铁矿石",) else
                  "WH-AS-COKE" if cat == "焦炭" else
                  "WH-AS-SCR" if cat == "废钢" else
                  "WH-AS-ALY" if cat == "合金" else "WH-AS-BILLET")
        elif mt == "生产领料":
            mat = D.pick(R, [m for m in materials
                             if m["category"] in ("铁矿石", "焦炭", "废钢", "合金")])["material_code"]
            ref = D.pick(R, mes_wos)
            cat = material_by_code[mat]["category"]
            wh = ("WH-AS-ORE" if cat in ("铁矿石",) else
                  "WH-AS-COKE" if cat == "焦炭" else
                  "WH-AS-SCR" if cat == "废钢" else "WH-AS-ALY")
        else:
            mat = D.pick(R, materials)["material_code"]
            ref = "TR" + D.pad(D.randint(R, 1000, 9999)); wh = D.pick(R, warehouses)["code"]
        stock_movements.append({
            "movement_id": f"ASMV{D.pad(20260000 + i * 31)}",
            "type": mt, "material_code": mat, "warehouse": wh,
            "qty": D.randint(R, 50, 2000), "uom": material_by_code[mat]["uom"], "ref_no": ref,
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 14))}T{D.pad(D.randint(R, 8, 18), 2)}:00:00",
        })

    # 应付：含 2 条逾期
    payables: list[dict] = []
    payable_specs = [
        ("ASAP20260001", "S-STEEL-ORE-01", 44_000_000, -60, 5),
        ("ASAP20260002", "S-STEEL-ORE-02", 11_520_000, -55, -8),     # 逾期
        ("ASAP20260003", "S-STEEL-COKE-01", 36_750_000, -45, 10),
        ("ASAP20260004", "S-STEEL-SCR-01", 21_440_000, -30, -3),    # 逾期
        ("ASAP20260005", "S-STEEL-SCR-02", 15_120_000, -30, 8),
        ("ASAP20260006", "S-STEEL-ALY-01", 3_400_000, -45, 12),
        ("ASAP20260007", "S-STEEL-ALY-01", 3_280_000, -45, 15),
    ]
    for pid, sup_code, amt, b_off, d_off in payable_specs:
        sup = supplier_by_code[sup_code]
        due = BASE_DATE + timedelta(days=d_off)
        overdue = (BASE_DATE - due).days > 0
        payables.append({
            "payable_id": pid,
            "supplier_code": sup_code, "supplier_name": sup["name"],
            "invoice_no": f"ASIV{D.pad(D.randint(R, 20250000, 20269999))}",
            "amount": amt, "currency": sup["currency"],
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已付款"]),
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    # 凭证：含 1 条财务复核中
    voucher_specs = [
        ("BV-AS-2026-0501", "2026-04", -70, 44_000_000, 44_000_000, "已过账", "铁矿石采购入库核算"),
        ("BV-AS-2026-0502", "2026-05", -50, 36_750_000, 36_750_000, "已过账", "焦炭采购入库核算"),
        ("BV-AS-2026-0512", "2026-07", 9, 6_800, 6_800, "财务复核中", "差旅费报销-7月"),
        ("BV-AS-2026-0513", "2026-06", -5, 21_440_000, 21_440_000, "草稿", "废钢采购入库核算"),
        ("BV-AS-2026-0514", "2026-06", -3, 11_520_000, 11_520_000, "草稿", "块矿采购入库核算"),
    ]
    vouchers: list[dict] = []
    for vno, period, off, debit, credit, status, summary in voucher_specs:
        vouchers.append({
            "voucher_no": vno,
            "period": period,
            "entry_date": f"{BASE_DATE + timedelta(days=off)}",
            "summary": summary,
            "debit_total": debit, "credit_total": credit,
            "status": status,
        })

    cost_centers = [
        {"code": "CC-AS-IRON", "name": "炼铁厂", "type": "车间"},
        {"code": "CC-AS-STEEL", "name": "炼钢厂", "type": "车间"},
        {"code": "CC-AS-ROLL", "name": "轧钢厂", "type": "车间"},
        {"code": "CC-AS-SPECIAL", "name": "特钢厂", "type": "车间"},
        {"code": "CC-AS-PUB", "name": "公辅", "type": "车间"},
        {"code": "CC-AS-SA", "name": "销售公司", "type": "部门"},
        {"code": "CC-AS-FIN", "name": "财务部", "type": "部门"},
        {"code": "CC-AS-HR", "name": "人力资源部", "type": "部门"},
    ]

    # 分钢种炉次生产成本（PC-AS-，按炉次 heat_no 归集；work_order_no 同步给对账口径）
    production_costs: list[dict] = []
    cost_specs = [
        ("PC-AS-2026062901", "HT2026062901", "SWO202607001", "CC-AS-STEEL", "2026-06",
         "P-ST-Q345B", 1_850_000, 320_000, 410_000),
        ("PC-AS-2026062902", "HT2026062902", "SWO202607002", "CC-AS-STEEL", "2026-06",
         "P-ST-45#", 1_720_000, 305_000, 395_000),
        ("PC-AS-2026062903", "HT2026062903", "SWO202607003", "CC-AS-STEEL", "2026-06",
         "P-ST-40Cr", 2_050_000, 360_000, 460_000),
        ("PC-AS-2026063001", "HT2026063001", "SWO202607004", "CC-AS-STEEL", "2026-06",
         "P-ST-Q345B", 1_880_000, 325_000, 415_000),
        ("PC-AS-2026063002", "HT2026063002", "SWO202607005", "CC-AS-ROLL", "2026-06",
         "P-ST-45#", 1_690_000, 298_000, 388_000),
    ]
    for cost_id, heat_no, won, cc, period, grade, mat_cost, labor, oh in cost_specs:
        production_costs.append({
            "cost_id": cost_id,
            "heat_no": heat_no,
            "work_order_no": won,
            "cost_center": cc,
            "period": period,
            "steel_grade": grade,
            "material_cost": float(mat_cost),
            "labor_cost": float(labor),
            "overhead": float(oh),
            "total_cost": round(mat_cost + labor + oh, 2),
        })

    return ErpData(
        suppliers=suppliers, supplier_by_code=supplier_by_code,
        materials=materials, material_by_code=material_by_code,
        warehouses=warehouses, warehouse_by_code=warehouse_by_code,
        purchase_orders=purchase_orders, purchase_order_lines=purchase_order_lines,
        po_by_no=po_by_no, inventory=inventory, stock_movements=stock_movements,
        payables=payables, vouchers=vouchers, cost_centers=cost_centers,
        production_costs=production_costs,
    )


# ───────────────────────── agilestationery（敏睿文具） ─────────────────────────


def _build_agilestationery() -> ErpData:
    """敏睿文具 ERP 口径：日本敏睿进口供应商 + 文具 SKU 物料主数据（M-ZB-，与 PIM
    ``SKU-ZB-`` 不同码空间，按 product_code/material_code 关联需 prefix 转换）+
    采购单（PO-，与 CST 报关单 CD- 按 po_no 关联）+ 库存/出入库/应付/凭证（BV-AS-，
    与 CST 发票 INV- 按 invoice_no/voucher_no 关联）+ 成本中心 + 进口批次成本（PC-ZB-）。"""
    R = D.rng(20260717)

    suppliers = [
        {"code": "S-ZB-JP", "name": "敏睿文具·日本进口品牌厂商", "category": "进口供货",
         "contact": "田中采购", "phone": "13800020001", "payment_terms_days": 60,
         "currency": "JPY", "rating": "A", "status": "合作中"},
        {"code": "S-ZB-LOG", "name": "深圳盐田港物流", "category": "物流",
         "contact": "孙物流", "phone": "13800020002", "payment_terms_days": 30,
         "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-ZB-CBR", "name": "上海外代报关行", "category": "报关",
         "contact": "赵报关", "phone": "13800020003", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "S-ZB-CBR2", "name": "深圳关贸报关行", "category": "报关",
         "contact": "钱关贸", "phone": "13800020004", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "S-ZB-PKG", "name": "东莞文具包装制品", "category": "包材",
         "contact": "周包装", "phone": "13800020005", "payment_terms_days": 30,
         "currency": "CNY", "rating": "B", "status": "合作中"},
    ]
    supplier_by_code = {s["code"]: s for s in suppliers}

    # 文具 SKU 物料主数据（M-ZB- 前缀，与 PIM SKU-ZB- 对齐，prefix 转换关联）
    materials = [
        {"material_code": "M-ZB-G001", "name": "敏睿中性笔 0.5 黑", "category": "中性笔",
         "uom": "支", "default_supplier": "S-ZB-JP", "safety_stock": 30000, "unit_cost": 2.80},
        {"material_code": "M-ZB-G002", "name": "敏睿中性笔 0.5 红", "category": "中性笔",
         "uom": "支", "default_supplier": "S-ZB-JP", "safety_stock": 15000, "unit_cost": 2.80},
        {"material_code": "M-ZB-G010", "name": "敏睿中性笔 0.4 蓝", "category": "中性笔",
         "uom": "支", "default_supplier": "S-ZB-JP", "safety_stock": 12000, "unit_cost": 3.50},
        {"material_code": "M-ZB-G011", "name": "敏睿中性笔 0.4 黑", "category": "中性笔",
         "uom": "支", "default_supplier": "S-ZB-JP", "safety_stock": 12000, "unit_cost": 3.50},
        {"material_code": "M-ZB-B001", "name": "敏睿金属圆珠笔", "category": "圆珠笔",
         "uom": "支", "default_supplier": "S-ZB-JP", "safety_stock": 5000, "unit_cost": 12.50},
        {"material_code": "M-ZB-B002", "name": "敏睿细字圆珠笔", "category": "圆珠笔",
         "uom": "支", "default_supplier": "S-ZB-JP", "safety_stock": 4000, "unit_cost": 2.50},
        {"material_code": "M-ZB-M001", "name": "敏睿油性记号笔", "category": "记号笔",
         "uom": "支", "default_supplier": "S-ZB-JP", "safety_stock": 15000, "unit_cost": 4.20},
        {"material_code": "M-ZB-H001", "name": "敏睿荧光笔 黄", "category": "荧光笔",
         "uom": "支", "default_supplier": "S-ZB-JP", "safety_stock": 10000, "unit_cost": 3.10},
        {"material_code": "M-ZB-R001", "name": "敏睿替换芯 0.5", "category": "笔芯",
         "uom": "支", "default_supplier": "S-ZB-JP", "safety_stock": 20000, "unit_cost": 1.20},
        {"material_code": "M-PKG-BOX", "name": "文具塑料包装盒", "category": "包材",
         "uom": "个", "default_supplier": "S-ZB-PKG", "safety_stock": 8000, "unit_cost": 0.80},
    ]
    material_by_code = {m["material_code"]: m for m in materials}

    warehouses = [
        {"code": "WH-ZB-FG", "name": "成品仓（深圳总仓）", "type": "成品仓"},
        {"code": "WH-ZB-EC", "name": "电商分仓", "type": "成品仓"},
        {"code": "WH-ZB-RG", "name": "华东区域仓", "type": "区域仓"},
        {"code": "WH-ZB-PKG", "name": "包材仓", "type": "包材仓"},
    ]
    warehouse_by_code = {w["code"]: w for w in warehouses}

    # 进口采购单（PO-，po_no 与 CST 报关单 CD-.po_no 对齐）
    purchase_orders: list[dict] = []
    purchase_order_lines: list[dict] = []
    po_specs = [
        ("PO202607001", "S-ZB-JP", "M-ZB-G001", 120000, 2.80, "已入库", "WH-ZB-FG"),
        ("PO202607002", "S-ZB-JP", "M-ZB-B001", 20000, 12.50, "部分到货", "WH-ZB-FG"),
        ("PO202607003", "S-ZB-JP", "M-ZB-M001", 80000, 4.20, "已入库", "WH-ZB-FG"),
        ("PO202607004", "S-ZB-JP", "M-ZB-R001", 100000, 1.20, "已入库", "WH-ZB-FG"),
        ("PO202607005", "S-ZB-JP", "M-ZB-G010", 60000, 3.50, "在途", "WH-ZB-FG"),
        ("PO202606020", "S-ZB-PKG", "M-PKG-BOX", 5000, 0.80, "已入库", "WH-ZB-PKG"),
    ]
    for po_no, sup_code, mat_code, qty, price, status, wh in po_specs:
        sup = supplier_by_code[sup_code]
        mat = material_by_code[mat_code]
        purchase_order_lines.append({
            "po_no": po_no, "line_no": 1,
            "material_code": mat_code, "material_name": mat["name"],
            "qty": qty, "uom": mat["uom"], "unit_price": price,
            "received_qty": int(qty * (1.0 if status == "已入库" else (0.5 if status == "部分到货" else 0))),
        })
        purchase_orders.append({
            "po_no": po_no, "supplier_code": sup_code, "supplier_name": sup["name"],
            "buyer": D.pick(R, ["采购-王", "采购-陈"]),
            "currency": sup["currency"], "total_amount": round(qty * price, 2),
            "status": status,
            "order_date": f"{BASE_DATE - timedelta(days=D.randint(R, 10, 40))}",
            "expected_date": f"{BASE_DATE + timedelta(days=D.randint(R, -5, 15))}",
        })
    po_by_no = {p["po_no"]: p for p in purchase_orders}

    # 库存（含滞销/临期标记）
    inventory: list[dict] = []
    inv_specs = [
        ("M-ZB-G001", "WH-ZB-FG", 28000, 30000),
        ("M-ZB-G002", "WH-ZB-FG", 9000, 15000),
        ("M-ZB-G010", "WH-ZB-FG", 4000, 12000),
        ("M-ZB-G011", "WH-ZB-FG", 3000, 12000),
        ("M-ZB-B001", "WH-ZB-FG", 3200, 5000),
        ("M-ZB-B002", "WH-ZB-FG", 6000, 4000),       # 滞销超储
        ("M-ZB-M001", "WH-ZB-FG", 18000, 15000),
        ("M-ZB-H001", "WH-ZB-FG", 7500, 10000),
        ("M-ZB-R001", "WH-ZB-FG", 15000, 20000),
        ("M-ZB-G001", "WH-ZB-EC", 6000, 8000),
        ("M-ZB-G001", "WH-ZB-RG", 9000, 10000),
        ("M-PKG-BOX", "WH-ZB-PKG", 9000, 8000),
    ]
    for mat_code, wh, stock, safety in inv_specs:
        mat = material_by_code[mat_code]
        inventory.append({
            "material_code": mat_code, "material_name": mat["name"],
            "warehouse": wh, "stock_qty": stock,
            "available_qty": max(0, stock - D.randint(R, 0, 150)),
            "safety_stock": safety, "uom": mat["uom"],
        })

    # 出入库流水（采购入库 / 销售出库 / 调拨；销售出库引用 CRM 销售订单 so_no）
    move_types = ["采购入库", "销售出库", "调拨"]
    crm_sos = _crm_sales_orders("agilestationery")
    stock_movements: list[dict] = []
    for i in range(18):
        mt = D.pick(R, move_types)
        if mt == "采购入库":
            pol = D.pick(R, purchase_order_lines)
            mat = pol["material_code"]; ref = pol["po_no"]; wh = "WH-ZB-FG"
        elif mt == "销售出库":
            mat = D.pick(R, [m for m in materials if m["category"] != "包材"])["material_code"]
            ref = D.pick(R, crm_sos); wh = D.pick(R, ["WH-ZB-FG", "WH-ZB-EC", "WH-ZB-RG"])
        else:
            mat = D.pick(R, materials)["material_code"]
            ref = "TR" + D.pad(D.randint(R, 1000, 9999)); wh = D.pick(R, warehouses)["code"]
        stock_movements.append({
            "movement_id": f"ASMV{D.pad(20260000 + i * 31)}",
            "type": mt, "material_code": mat, "warehouse": wh,
            "qty": D.randint(R, 50, 2000), "uom": material_by_code[mat]["uom"], "ref_no": ref,
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 14))}T{D.pad(D.randint(R, 8, 18), 2)}:00:00",
        })

    # 应付（含 2 条逾期）
    payables: list[dict] = []
    payable_specs = [
        ("ASAP202607001", "S-ZB-JP", 161280.0, -40, 5, "INV202607001"),
        ("ASAP202607002", "S-ZB-JP", 12000.0, -35, -8, "INV202607003"),      # 逾期
        ("ASAP202607003", "S-ZB-CBR", 4200.0, -30, 10, "INV202607002"),
        ("ASAP202607004", "S-ZB-CBR2", 2800.0, -28, -3, "INV202607004"),     # 逾期
        ("ASAP202607005", "S-ZB-LOG", 4200.0, -25, 8, "INV202607006"),
        ("ASAP202607006", "S-ZB-PKG", 4000.0, -20, 12, None),
    ]
    for pid, sup_code, amt, b_off, d_off, inv_no in payable_specs:
        sup = supplier_by_code[sup_code]
        due = BASE_DATE + timedelta(days=d_off)
        overdue = (BASE_DATE - due).days > 0
        payables.append({
            "payable_id": pid,
            "supplier_code": sup_code, "supplier_name": sup["name"],
            "invoice_no": inv_no or f"ASIV{D.pad(D.randint(R, 20260000, 20269999))}",
            "amount": amt, "currency": sup["currency"],
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已付款"]),
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    # 凭证（BV-AS-，voucher_no 与 CST 发票 INV.voucher_no 对齐）
    voucher_specs = [
        ("BV-AS-2026-0701", "2026-07", -9, 182246.40, 182246.40, "已过账", "中性笔 进口采购入库核算"),
        ("BV-AS-2026-0702", "2026-07", -8, 4452.00, 4452.00, "已过账", "报关费入账"),
        ("BV-AS-2026-0703", "2026-07", -11, 18224.64, 18224.64, "已过账", "记号笔进口采购入库核算"),
        ("BV-AS-2026-0704", "2026-07", -10, 2834.00, 2834.00, "草稿", "盐田港物流费入账"),
        ("BV-AS-2026-0710", "2026-07", 5, 74580.00, 74580.00, "财务复核中", "华东经销商销项开票"),
        ("BV-AS-2026-0711", "2026-07", 2, 0, 0, "草稿", "差旅费报销-7月"),
    ]
    vouchers: list[dict] = []
    for vno, period, off, debit, credit, status, summary in voucher_specs:
        vouchers.append({
            "voucher_no": vno, "period": period,
            "entry_date": f"{BASE_DATE + timedelta(days=off)}",
            "summary": summary, "debit_total": debit, "credit_total": credit,
            "status": status,
        })

    cost_centers = [
        {"code": "CC-ZB-SA", "name": "销售管理部", "type": "部门"},
        {"code": "CC-ZB-EC", "name": "电商渠道部", "type": "部门"},
        {"code": "CC-ZB-MKT", "name": "市场营销部", "type": "部门"},
        {"code": "CC-ZB-SCM", "name": "供应链与物流部", "type": "部门"},
        {"code": "CC-ZB-PRD", "name": "产品管理部", "type": "部门"},
        {"code": "CC-ZB-SVC", "name": "客户服务部", "type": "部门"},
        {"code": "CC-ZB-FIN", "name": "财务部", "type": "部门"},
        {"code": "CC-ZB-HR", "name": "人力资源部", "type": "部门"},
        {"code": "CC-ZB-LEG", "name": "法务合规部", "type": "部门"},
    ]

    # 进口批次成本（PC-ZB-，按进口批次归集；heat_no 字段在此租户承载批次号 BAT，
    # steel_grade 字段承载产品 SKU-ZB-，列表未对任何技能暴露，仅供对账兜底）
    production_costs: list[dict] = []
    cost_specs = [
        ("PC-ZB-202607001", "BAT202607001", "PO202607001", "CC-ZB-SCM", "2026-07",
         "SKU-ZB-G001", 336000.0, 12000.0, 4500.0),
        ("PC-ZB-202607002", "BAT202607002", "PO202607002", "CC-ZB-SCM", "2026-07",
         "SKU-ZB-B001", 250000.0, 8000.0, 3000.0),
        ("PC-ZB-202607003", "BAT202607003", "PO202607003", "CC-ZB-SCM", "2026-07",
         "SKU-ZB-M001", 336000.0, 10000.0, 3500.0),
        ("PC-ZB-202607004", "BAT202607004", "PO202607004", "CC-ZB-SCM", "2026-07",
         "SKU-ZB-R001", 120000.0, 6000.0, 2000.0),
    ]
    for cost_id, batch, won, cc, period, grade, mat_cost, labor, oh in cost_specs:
        production_costs.append({
            "cost_id": cost_id, "heat_no": batch, "work_order_no": won,
            "cost_center": cc, "period": period, "steel_grade": grade,
            "material_cost": float(mat_cost), "labor_cost": float(labor),
            "overhead": float(oh), "total_cost": round(mat_cost + labor + oh, 2),
        })

    return ErpData(
        suppliers=suppliers, supplier_by_code=supplier_by_code,
        materials=materials, material_by_code=material_by_code,
        warehouses=warehouses, warehouse_by_code=warehouse_by_code,
        purchase_orders=purchase_orders, purchase_order_lines=purchase_order_lines,
        po_by_no=po_by_no, inventory=inventory, stock_movements=stock_movements,
        payables=payables, vouchers=vouchers, cost_centers=cost_centers,
        production_costs=production_costs,
    )


def _build_starexploration() -> ErpData:
    """星途勘探 ERP 口径：工程供应商 + 设计/施工物料（M-CON-/M-STE-/M-ARC-，与 DES
    算量项 QTI-CON-/QTI-STE- 按 material_code 关联，prefix 转换）+ 工程采购单 +
    项目现场仓 + 应付（工程款，invoice_no 与 CRM 发票 INV- 对齐）+ 凭证（BV-SE-，
    与 CRM 发票按 invoice_no/voucher_no 关联）+ 成本中心（CC-IND-/CC-BAT-/CC-CIV-，
    与 EPC project.cost_center_code 对齐）+ 项目成本（PC-SE-，引用 CRM 销售订单/合同号）。"""
    R = D.rng(20260723)

    suppliers = [
        {"code": "S-SE-CON", "name": "中建商混长沙站", "category": "混凝土", "contact": "李材料",
         "phone": "13800030001", "payment_terms_days": 45, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-SE-STE", "name": "湖南华菱钢铁", "category": "钢筋钢材", "contact": "王钢材",
         "phone": "13800030002", "payment_terms_days": 30, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-SE-EQP", "name": "中机设备成套", "category": "工程设备", "contact": "赵设备",
         "phone": "13800030003", "payment_terms_days": 60, "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "S-SE-ARC", "name": "湖南建工装饰", "category": "建筑做法", "contact": "孙装饰",
         "phone": "13800030004", "payment_terms_days": 30, "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "S-SE-LOG", "name": "长沙城投物流", "category": "物流", "contact": "周物流",
         "phone": "13800030005", "payment_terms_days": 30, "currency": "CNY", "rating": "B", "status": "合作中"},
    ]
    supplier_by_code = {s["code"]: s for s in suppliers}

    # 物料（M-CON-/M-STE-/M-ARC-，与 DES 算量项 material_code 对齐）
    materials = [
        {"material_code": "M-CON-001", "name": "C35 商品混凝土", "category": "混凝土", "uom": "m³",
         "default_supplier": "S-SE-CON", "safety_stock": 2000, "unit_cost": 580.0},
        {"material_code": "M-CON-002", "name": "C30 商品混凝土", "category": "混凝土", "uom": "m³",
         "default_supplier": "S-SE-CON", "safety_stock": 3000, "unit_cost": 540.0},
        {"material_code": "M-STE-001", "name": "HRB400 钢筋", "category": "钢筋钢材", "uom": "t",
         "default_supplier": "S-SE-STE", "safety_stock": 80, "unit_cost": 4200.0},
        {"material_code": "M-STE-002", "name": "HRB500 钢筋", "category": "钢筋钢材", "uom": "t",
         "default_supplier": "S-SE-STE", "safety_stock": 100, "unit_cost": 4350.0},
        {"material_code": "M-ARC-001", "name": "环氧地坪做法", "category": "建筑做法", "uom": "m²",
         "default_supplier": "S-SE-ARC", "safety_stock": 5000, "unit_cost": 165.0},
    ]
    material_by_code = {m["material_code"]: m for m in materials}

    warehouses = [
        {"code": "WH-SE-IND", "name": "电工装备厂房现场仓", "type": "项目现场仓"},
        {"code": "WH-SE-BAT", "name": "电池工厂现场仓", "type": "项目现场仓"},
        {"code": "WH-SE-CIV", "name": "市政水厂现场仓", "type": "项目现场仓"},
        {"code": "WH-SE-CEN", "name": "中心料库", "type": "中心仓"},
    ]
    warehouse_by_code = {w["code"]: w for w in warehouses}

    # 工程采购单（POSE-，po_no）
    purchase_orders: list[dict] = []
    purchase_order_lines: list[dict] = []
    po_specs = [
        ("POSE202607001", "S-SE-CON", "M-CON-001", 1280, 580.0, "已入库", "WH-SE-IND"),
        ("POSE202607002", "S-SE-STE", "M-STE-001", 186, 4200.0, "部分到货", "WH-SE-IND"),
        ("POSE202607003", "S-SE-CON", "M-CON-002", 4600, 540.0, "在途", "WH-SE-IND"),
        ("POSE202607004", "S-SE-ARC", "M-ARC-001", 12000, 165.0, "已入库", "WH-SE-IND"),
        ("POSE202607005", "S-SE-CON", "M-CON-001", 9200, 610.0, "在途", "WH-SE-BAT"),
        ("POSE202607006", "S-SE-STE", "M-STE-002", 412, 4350.0, "未到货", "WH-SE-BAT"),
        ("POSE202607007", "S-SE-CON", "M-CON-002", 3200, 560.0, "未到货", "WH-SE-CIV"),
        ("POSE202606020", "S-SE-EQP", "M-STE-001", 12, 4200.0, "已入库", "WH-SE-CEN"),
    ]
    for po_no, sup_code, mat_code, qty, price, status, wh in po_specs:
        sup = supplier_by_code[sup_code]
        mat = material_by_code[mat_code]
        purchase_order_lines.append({
            "po_no": po_no, "line_no": 1,
            "material_code": mat_code, "material_name": mat["name"],
            "qty": qty, "uom": mat["uom"], "unit_price": price,
            "received_qty": int(qty * (1.0 if status == "已入库" else (0.5 if status == "部分到货" else 0))),
        })
        purchase_orders.append({
            "po_no": po_no, "supplier_code": sup_code, "supplier_name": sup["name"],
            "buyer": D.pick(R, ["采购-陈", "采购-周"]),
            "currency": sup["currency"], "total_amount": round(qty * price, 2),
            "status": status,
            "order_date": f"{BASE_DATE - timedelta(days=D.randint(R, 10, 40))}",
            "expected_date": f"{BASE_DATE + timedelta(days=D.randint(R, -5, 20))}",
        })
    po_by_no = {p["po_no"]: p for p in purchase_orders}

    # 库存
    inventory: list[dict] = []
    inv_specs = [
        ("M-CON-001", "WH-SE-IND", 800, 2000),
        ("M-CON-002", "WH-SE-IND", 2400, 3000),
        ("M-STE-001", "WH-SE-IND", 60, 80),       # 低于安全库存
        ("M-ARC-001", "WH-SE-IND", 9000, 5000),
        ("M-CON-001", "WH-SE-BAT", 1200, 2000),
        ("M-STE-002", "WH-SE-BAT", 90, 100),
        ("M-CON-002", "WH-SE-CIV", 600, 3000),    # 低于安全库存
        ("M-STE-001", "WH-SE-CEN", 40, 80),
    ]
    for mat_code, wh, stock, safety in inv_specs:
        mat = material_by_code[mat_code]
        inventory.append({
            "material_code": mat_code, "material_name": mat["name"],
            "warehouse": wh, "stock_qty": stock,
            "available_qty": max(0, stock - D.randint(R, 0, 80)),
            "safety_stock": safety, "uom": mat["uom"],
        })

    # 出入库流水（采购入库 / 工程领料 / 调拨；工程领料引用项目号 PRJ-）
    move_types = ["采购入库", "工程领料", "调拨"]
    stock_movements: list[dict] = []
    project_refs = ["PRJ-IND-001", "PRJ-BAT-001", "PRJ-CIV-001"]
    for i in range(18):
        mt = D.pick(R, move_types)
        if mt == "采购入库":
            pol = D.pick(R, purchase_order_lines)
            mat = pol["material_code"]; ref = pol["po_no"]; wh = D.pick(R, ["WH-SE-IND", "WH-SE-BAT", "WH-SE-CEN"])
        elif mt == "工程领料":
            mat = D.pick(R, materials)["material_code"]
            ref = D.pick(R, project_refs); wh = D.pick(R, ["WH-SE-IND", "WH-SE-BAT", "WH-SE-CIV"])
        else:
            mat = D.pick(R, materials)["material_code"]
            ref = "TR" + D.pad(D.randint(R, 1000, 9999)); wh = D.pick(R, warehouses)["code"]
        stock_movements.append({
            "movement_id": f"SEMV{D.pad(20260000 + i * 31)}",
            "type": mt, "material_code": mat, "warehouse": wh,
            "qty": D.randint(R, 20, 800), "uom": material_by_code[mat]["uom"], "ref_no": ref,
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 14))}T{D.pad(D.randint(R, 8, 18), 2)}:00:00",
        })

    # 应付（工程款，含 2 条逾期；invoice_no 与 CRM 发票 INV- 对齐）
    payables: list[dict] = []
    payable_specs = [
        ("SEAP202607001", "S-SE-CON", 742400.0, -40, 5, "INV202607001"),
        ("SEAP202607002", "S-SE-STE", 781200.0, -35, -8, "INV202607002"),    # 逾期
        ("SEAP202607003", "S-SE-ARC", 1980000.0, -30, 10, "INV202607003"),
        ("SEAP202607004", "S-SE-CON", 5612000.0, -28, -3, "INV202607004"),   # 逾期
        ("SEAP202607005", "S-SE-EQP", 50400.0, -25, 12, None),
        ("SEAP202607006", "S-SE-LOG", 12600.0, -20, 8, None),
    ]
    for pid, sup_code, amt, b_off, d_off, inv_no in payable_specs:
        sup = supplier_by_code[sup_code]
        due = BASE_DATE + timedelta(days=d_off)
        overdue = (BASE_DATE - due).days > 0
        payables.append({
            "payable_id": pid,
            "supplier_code": sup_code, "supplier_name": sup["name"],
            "invoice_no": inv_no or f"SEIV{D.pad(D.randint(R, 20260000, 20269999))}",
            "amount": amt, "currency": sup["currency"],
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已付款"]),
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    # 凭证（BV-SE-，voucher_no 与 CRM 发票 INV.voucher_no 对齐）
    voucher_specs = [
        ("BV-SE-2026-0701", "2026-07", -9, 742400.0, 742400.0, "已过账", "电工厂房混凝土采购入库核算"),
        ("BV-SE-2026-0702", "2026-07", -8, 781200.0, 781200.0, "已过账", "钢筋采购入库核算"),
        ("BV-SE-2026-0703", "2026-07", -11, 1980000.0, 1980000.0, "已过账", "环氧地坪做法采购核算"),
        ("BV-SE-2026-0704", "2026-07", -10, 5612000.0, 5612000.0, "财务复核中", "电池工厂混凝土采购核算"),
        ("BV-SE-2026-0710", "2026-07", 5, 9200000.0, 9200000.0, "财务复核中", "电池工厂 EPC 合同进度款确认"),
        ("BV-SE-2026-0711", "2026-07", 2, 0, 0, "草稿", "项目差旅费报销-7月"),
    ]
    vouchers: list[dict] = []
    for vno, period, off, debit, credit, status, summary in voucher_specs:
        vouchers.append({
            "voucher_no": vno, "period": period,
            "entry_date": f"{BASE_DATE + timedelta(days=off)}",
            "summary": summary, "debit_total": debit, "credit_total": credit,
            "status": status,
        })

    cost_centers = [
        {"code": "CC-IND-001", "name": "电工装备厂房 EPC 项目组", "type": "项目"},
        {"code": "CC-BAT-001", "name": "电池工厂 EPC 项目组", "type": "项目"},
        {"code": "CC-CIV-001", "name": "市政水厂 EPC 项目组", "type": "项目"},
        {"code": "CC-SE-DES", "name": "设计研究院", "type": "部门"},
        {"code": "CC-SE-FIN", "name": "资产财务部", "type": "部门"},
        {"code": "CC-SE-HR", "name": "人力资源部", "type": "部门"},
        {"code": "CC-SE-LEG", "name": "法律合规部", "type": "部门"},
        {"code": "CC-SE-ADM", "name": "综合管理部", "type": "部门"},
    ]

    # 项目成本（PC-SE-，cost_center 与 EPC project.cost_center_code 对齐；
    # work_order_no 引用 CRM 销售订单/合同号，heat_no 承载项目号 PRJ-）
    crm_refs = _crm_sales_orders("starexploration")
    production_costs: list[dict] = []
    cost_specs = [
        ("PC-SE-202607001", "PRJ-IND-001", crm_refs[0] if crm_refs else "CT-SE-001", "CC-IND-001", "2026-07", "混凝土/钢筋", 1523600.0, 180000.0, 92000.0),
        ("PC-SE-202607002", "PRJ-BAT-001", crm_refs[1] if len(crm_refs) > 1 else "CT-SE-002", "CC-BAT-001", "2026-07", "洁净车间主体", 5612000.0, 420000.0, 210000.0),
        ("PC-SE-202607003", "PRJ-CIV-001", crm_refs[2] if len(crm_refs) > 2 else "CT-SE-003", "CC-CIV-001", "2026-07", "水池主体", 1792000.0, 130000.0, 65000.0),
    ]
    for cost_id, project, won, cc, period, grade, mat_cost, labor, oh in cost_specs:
        production_costs.append({
            "cost_id": cost_id, "heat_no": project, "work_order_no": won,
            "cost_center": cc, "period": period, "steel_grade": grade,
            "material_cost": float(mat_cost), "labor_cost": float(labor),
            "overhead": float(oh), "total_cost": round(mat_cost + labor + oh, 2),
        })

    return ErpData(
        suppliers=suppliers, supplier_by_code=supplier_by_code,
        materials=materials, material_by_code=material_by_code,
        warehouses=warehouses, warehouse_by_code=warehouse_by_code,
        purchase_orders=purchase_orders, purchase_order_lines=purchase_order_lines,
        po_by_no=po_by_no, inventory=inventory, stock_movements=stock_movements,
        payables=payables, vouchers=vouchers, cost_centers=cost_centers,
        production_costs=production_costs,
    )


def _build_starhma() -> ErpData:
    """星途热熔胶 ERP 口径：化工原料供应商（树脂/增粘剂/蜡/抗氧剂）+ 原料与成品胶物料
    （M-RES-/M-TK-/M-WAX-/M-AO-/M-FG-，与 FRM 组分 ING-RES-/ING-TK-/ING-WAX-/ING-AO- 按
    material_code 关联，prefix 转换）+ 原料仓/成品仓 + 采购单（POHMA）+ 原料与成品库存
    （含低于安全库存的预警项）+ 应付（HMAAP，invoice_no 与 CRM 发票 INV 对齐）+ 凭证
    （BV-HMA-）+ 成本中心（CC-HMA-RD/MFG/SCM/QAS/ADM）+ 生产成本（PC-HMA-，引用 MES
    工单与 CRM 合同号）。"""
    R = D.rng(20260725)

    suppliers = [
        {"code": "S-HMA-RES", "name": "杭州树脂科技", "category": "EVA/APAO 树脂", "contact": "李树脂",
         "phone": "13800010001", "payment_terms_days": 45, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-HMA-TK", "name": "上海增粘材料", "category": "石油树脂/萜烯树脂", "contact": "王增粘",
         "phone": "13800010002", "payment_terms_days": 30, "currency": "CNY", "rating": "A", "status": "合作中"},
        {"code": "S-HMA-WAX", "name": "宁波蜡业化工", "category": "费托蜡/PE 蜡", "contact": "赵蜡",
         "phone": "13800010003", "payment_terms_days": 30, "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "S-HMA-AO", "name": "南京助剂供应", "category": "抗氧剂/助剂", "contact": "孙助剂",
         "phone": "13800010004", "payment_terms_days": 30, "currency": "CNY", "rating": "B", "status": "合作中"},
        {"code": "S-HMA-PKG", "name": "杭州包装材料", "category": "包装耗材", "contact": "周包装",
         "phone": "13800010005", "payment_terms_days": 30, "currency": "CNY", "rating": "B", "status": "合作中"},
    ]
    supplier_by_code = {s["code"]: s for s in suppliers}

    # 物料（原料 M-RES-/M-TK-/M-WAX-/M-AO- 与 FRM 组分 material_code 对齐；成品胶 M-FG-）
    materials = [
        {"material_code": "M-RES-001", "name": "EVA 树脂 28-150", "category": "树脂", "uom": "kg",
         "default_supplier": "S-HMA-RES", "safety_stock": 20000, "unit_cost": 13.5},
        {"material_code": "M-RES-002", "name": "APAO 乙烯-丙烯共聚物", "category": "树脂", "uom": "kg",
         "default_supplier": "S-HMA-RES", "safety_stock": 8000, "unit_cost": 18.0},
        {"material_code": "M-TK-001", "name": "石油树脂 C5", "category": "增粘剂", "uom": "kg",
         "default_supplier": "S-HMA-TK", "safety_stock": 15000, "unit_cost": 12.0},
        {"material_code": "M-TK-002", "name": "萜烯树脂 T100", "category": "增粘剂", "uom": "kg",
         "default_supplier": "S-HMA-TK", "safety_stock": 5000, "unit_cost": 22.0},
        {"material_code": "M-WAX-001", "name": "费托蜡 FT-100", "category": "蜡", "uom": "kg",
         "default_supplier": "S-HMA-WAX", "safety_stock": 6000, "unit_cost": 9.5},
        {"material_code": "M-WAX-002", "name": "PE 微粉蜡", "category": "蜡", "uom": "kg",
         "default_supplier": "S-HMA-WAX", "safety_stock": 4000, "unit_cost": 11.0},
        {"material_code": "M-AO-001", "name": "抗氧剂 BHT/1010", "category": "抗氧剂", "uom": "kg",
         "default_supplier": "S-HMA-AO", "safety_stock": 500, "unit_cost": 85.0},
        {"material_code": "M-FG-001", "name": "环保型书刊装订热熔胶", "category": "成品胶", "uom": "kg",
         "default_supplier": None, "safety_stock": 10000, "unit_cost": 18.5},
        {"material_code": "M-FG-002", "name": "物流快递袋压敏胶", "category": "成品胶", "uom": "kg",
         "default_supplier": None, "safety_stock": 12000, "unit_cost": 21.0},
        {"material_code": "M-FG-003", "name": "食品日化包装用热熔胶", "category": "成品胶", "uom": "kg",
         "default_supplier": None, "safety_stock": 6000, "unit_cost": 26.5},
    ]
    material_by_code = {m["material_code"]: m for m in materials}

    warehouses = [
        {"code": "WH-HMA-RAW", "name": "原料仓", "type": "原料仓"},
        {"code": "WH-HMA-FG", "name": "成品仓", "type": "成品仓"},
        {"code": "WH-HMA-CEN", "name": "中心仓", "type": "中心仓"},
    ]
    warehouse_by_code = {w["code"]: w for w in warehouses}

    # 采购单（POHMA）
    purchase_orders: list[dict] = []
    purchase_order_lines: list[dict] = []
    po_specs = [
        ("POHMA202607001", "S-HMA-RES", "M-RES-001", 12000, 13.5, "已入库", "WH-HMA-RAW"),
        ("POHMA202607002", "S-HMA-TK", "M-TK-001", 10000, 12.0, "部分到货", "WH-HMA-RAW"),
        ("POHMA202607003", "S-HMA-WAX", "M-WAX-001", 4000, 9.5, "在途", "WH-HMA-RAW"),
        ("POHMA202607004", "S-HMA-RES", "M-RES-002", 5000, 18.0, "在途", "WH-HMA-RAW"),
        ("POHMA202607005", "S-HMA-TK", "M-TK-002", 2000, 22.0, "未到货", "WH-HMA-RAW"),
        ("POHMA202607006", "S-HMA-AO", "M-AO-001", 300, 85.0, "已入库", "WH-HMA-RAW"),
        ("POHMA202606018", "S-HMA-PKG", "M-WAX-002", 1500, 11.0, "已入库", "WH-HMA-CEN"),
    ]
    for po_no, sup_code, mat_code, qty, price, status, wh in po_specs:
        sup = supplier_by_code[sup_code]
        mat = material_by_code[mat_code]
        purchase_order_lines.append({
            "po_no": po_no, "line_no": 1,
            "material_code": mat_code, "material_name": mat["name"],
            "qty": qty, "uom": mat["uom"], "unit_price": price,
            "received_qty": int(qty * (1.0 if status == "已入库" else (0.5 if status == "部分到货" else 0))),
        })
        purchase_orders.append({
            "po_no": po_no, "supplier_code": sup_code, "supplier_name": sup["name"],
            "buyer": D.pick(R, ["采购-陈", "采购-周"]),
            "currency": sup["currency"], "total_amount": round(qty * price, 2),
            "status": status,
            "order_date": f"{BASE_DATE - timedelta(days=D.randint(R, 8, 40))}",
            "expected_date": f"{BASE_DATE + timedelta(days=D.randint(R, -5, 20))}",
        })
    po_by_no = {p["po_no"]: p for p in purchase_orders}

    # 库存（原料 + 成品；含低于安全库存的预警项）
    inventory: list[dict] = []
    inv_specs = [
        ("M-RES-001", "WH-HMA-RAW", 8000, 20000),    # 低于安全库存
        ("M-RES-002", "WH-HMA-RAW", 3200, 8000),      # 低于安全库存
        ("M-TK-001", "WH-HMA-RAW", 14000, 15000),     # 接近安全库存
        ("M-TK-002", "WH-HMA-RAW", 1800, 5000),       # 低于安全库存
        ("M-WAX-001", "WH-HMA-RAW", 5500, 6000),
        ("M-WAX-002", "WH-HMA-RAW", 4200, 4000),
        ("M-AO-001", "WH-HMA-RAW", 480, 500),         # 低于安全库存
        ("M-FG-001", "WH-HMA-FG", 9000, 10000),
        ("M-FG-002", "WH-HMA-FG", 6200, 12000),       # 低于安全库存
        ("M-FG-003", "WH-HMA-FG", 7100, 6000),
    ]
    for mat_code, wh, stock, safety in inv_specs:
        mat = material_by_code[mat_code]
        inventory.append({
            "material_code": mat_code, "material_name": mat["name"],
            "warehouse": wh, "stock_qty": stock,
            "available_qty": max(0, stock - D.randint(R, 0, 200)),
            "safety_stock": safety, "uom": mat["uom"],
            "category": mat["category"],
        })

    # 出入库流水（采购入库 / 生产领料 / 调拨；生产领料引用 MES 批次 BAT-）
    move_types = ["采购入库", "生产领料", "调拨"]
    stock_movements: list[dict] = []
    batch_refs = ["BAT-2026-0701", "BAT-2026-0702", "BAT-2026-0703", "BAT-2026-0704"]
    for i in range(18):
        mt = D.pick(R, move_types)
        if mt == "采购入库":
            pol = D.pick(R, purchase_order_lines)
            mat = pol["material_code"]; ref = pol["po_no"]; wh = "WH-HMA-RAW"
        elif mt == "生产领料":
            mat = D.pick(R, [m for m in materials if m["category"] != "成品胶"])["material_code"]
            ref = D.pick(R, batch_refs); wh = "WH-HMA-RAW"
        else:
            mat = D.pick(R, materials)["material_code"]
            ref = "TR" + D.pad(D.randint(R, 1000, 9999)); wh = D.pick(R, warehouses)["code"]
        stock_movements.append({
            "movement_id": f"HMAMV{D.pad(20260000 + i * 31)}",
            "type": mt, "material_code": mat, "warehouse": wh,
            "qty": D.randint(R, 50, 2000), "uom": material_by_code[mat]["uom"], "ref_no": ref,
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 14))}T{D.pad(D.randint(R, 8, 18), 2)}:00:00",
        })

    # 应付（含 2 条逾期；invoice_no 与 CRM 发票 INV 对齐）
    payables: list[dict] = []
    payable_specs = [
        ("HMAAP202607001", "S-HMA-RES", 162000.0, -40, 5, "INV202607001"),
        ("HMAAP202607002", "S-HMA-TK", 120000.0, -35, -8, "INV202607002"),    # 逾期
        ("HMAAP202607003", "S-HMA-WAX", 38000.0, -28, 12, "INV202607003"),
        ("HMAAP202607004", "S-HMA-RES", 90000.0, -25, -3, "INV202607004"),   # 逾期
        ("HMAAP202607005", "S-HMA-AO", 25500.0, -20, 8, None),
        ("HMAAP202607006", "S-HMA-TK", 44000.0, -18, 15, None),
    ]
    for pid, sup_code, amt, b_off, d_off, inv_no in payable_specs:
        sup = supplier_by_code[sup_code]
        due = BASE_DATE + timedelta(days=d_off)
        overdue = (BASE_DATE - due).days > 0
        payables.append({
            "payable_id": pid,
            "supplier_code": sup_code, "supplier_name": sup["name"],
            "invoice_no": inv_no or f"HMAIV{D.pad(D.randint(R, 20260000, 20269999))}",
            "amount": amt, "currency": sup["currency"],
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已付款"]),
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    # 凭证（BV-HMA-，voucher_no 与 CRM 发票 INV.voucher_no 对齐）
    voucher_specs = [
        ("BV-HMA-2026-0701", "2026-07", -9, 162000.0, 162000.0, "已过账", "EVA 树脂采购入库核算"),
        ("BV-HMA-2026-0702", "2026-07", -8, 120000.0, 120000.0, "已过账", "石油树脂采购入库核算"),
        ("BV-HMA-2026-0703", "2026-07", -11, 38000.0, 38000.0, "已过账", "费托蜡采购核算"),
        ("BV-HMA-2026-0704", "2026-07", -10, 90000.0, 90000.0, "财务复核中", "APAO 树脂采购核算"),
        ("BV-HMA-2026-0710", "2026-07", 5, 0, 0, "草稿", "生产辅料领用分摊-7月"),
        ("BV-HMA-2026-0711", "2026-07", 2, 0, 0, "草稿", "差旅费报销-7月"),
    ]
    vouchers: list[dict] = []
    for vno, period, off, debit, credit, status, summary in voucher_specs:
        vouchers.append({
            "voucher_no": vno, "period": period,
            "entry_date": f"{BASE_DATE + timedelta(days=off)}",
            "summary": summary, "debit_total": debit, "credit_total": credit,
            "status": status,
        })

    cost_centers = [
        {"code": "CC-HMA-RD", "name": "研发中心", "type": "部门"},
        {"code": "CC-HMA-SAL", "name": "营销销售中心", "type": "部门"},
        {"code": "CC-HMA-MFG", "name": "生产制造部", "type": "部门"},
        {"code": "CC-HMA-SCM", "name": "供应链部", "type": "部门"},
        {"code": "CC-HMA-QAS", "name": "品质与技术服务部", "type": "部门"},
        {"code": "CC-HMA-ADM", "name": "综合管理部", "type": "部门"},
    ]

    # 生产成本（PC-HMA-，work_order_no 引用 MES 工单；CRM 合同号回挂）
    crm_refs = _crm_sales_orders("starhma")
    production_costs: list[dict] = []
    cost_specs = [
        ("PC-HMA-202607001", "BAT-2026-0701", crm_refs[0] if crm_refs else "CT-HMA-001", "CC-HMA-MFG", "2026-07", "FORM-STD-001", 186000.0, 24000.0, 12000.0),
        ("PC-HMA-202607002", "BAT-2026-0702", crm_refs[1] if len(crm_refs) > 1 else "CT-HMA-002", "CC-HMA-MFG", "2026-07", "FORM-STD-002", 168000.0, 22000.0, 11000.0),
        ("PC-HMA-202607003", "BAT-2026-0703", crm_refs[2] if len(crm_refs) > 2 else "CT-HMA-001", "CC-HMA-MFG", "2026-07", "FORM-CUS-001", 96000.0, 18000.0, 9000.0),
    ]
    for cost_id, batch, won, cc, period, grade, mat_cost, labor, oh in cost_specs:
        production_costs.append({
            "cost_id": cost_id, "heat_no": batch, "work_order_no": won,
            "cost_center": cc, "period": period, "steel_grade": grade,
            "material_cost": float(mat_cost), "labor_cost": float(labor),
            "overhead": float(oh), "total_cost": round(mat_cost + labor + oh, 2),
        })

    return ErpData(
        suppliers=suppliers, supplier_by_code=supplier_by_code,
        materials=materials, material_by_code=material_by_code,
        warehouses=warehouses, warehouse_by_code=warehouse_by_code,
        purchase_orders=purchase_orders, purchase_order_lines=purchase_order_lines,
        po_by_no=po_by_no, inventory=inventory, stock_movements=stock_movements,
        payables=payables, vouchers=vouchers, cost_centers=cost_centers,
        production_costs=production_costs,
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[ErpData]({
    "minrui": _build_minrui,
    "starclothing": _build_starclothing,
    "agileac": _build_agileac,
    "agilesteel": _build_agilesteel,
    "agilestationery": _build_agilestationery,
    "starexploration": _build_starexploration,
    "starhma": _build_starhma,
})


def load(tenant: str) -> ErpData:
    """按 tenant 取数据集；首次调用时触发构建并缓存。未知 tenant 抛 KeyError。"""
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()
