"""MES 多租户确定性种子数据——minrui（机械/电子制造）+ starclothing（服装）。

固定种子 + 固定基准日，重启可复现。每个 tenant 一份 ``MesData``，覆盖产线 /
设备 / 工艺路线 / 生产订单 / 工单 / 报工 / 不良 / 班次产量 / 在制品 / OEE。
工单 ``work_order_no`` 被同 tenant 的 ERP 生产成本与库存出入库引用，形成联动。

多租户访问：``load(tenant) -> MesData``。模块级别名（``WORK_ORDERS`` 等）默认
指向 minrui，向后兼容未改造的调用方（HRM 直接 ``from mock.systems.mes.data
import WORK_ORDERS``）与跨系统延迟导入（CRM 经 ``all_work_order_nos()`` 取工单号）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry, TenantBuilding

BASE_DATE: date = date(2026, 6, 29)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class MesData:
    lines: list[dict]
    line_by_code: dict[str, dict]
    equipment: list[dict]
    equip_by_code: dict[str, dict]
    equip_faults: dict[str, dict]
    products: list[dict]
    product_by_code: dict[str, dict]
    production_orders: list[dict]
    production_order_by_no: dict[str, dict]
    work_orders: list[dict]
    work_order_by_no: dict[str, dict]
    work_reports: list[dict]
    defects: list[dict]
    shift_outputs: list[dict]
    wip: list[dict]
    heats: list[dict] = field(default_factory=list)
    heat_by_no: dict[str, dict] = field(default_factory=dict)


# ───────────────────────── 跨系统取数（同 tenant） ─────────────────────────


def _crm_sales_orders(tenant: str) -> list[str]:
    """跨系统取同 tenant 的 CRM 销售订单号；CRM 未就绪或循环构造中时回退占位。"""
    try:
        from mock.systems.crm.data import load as _load_crm
        d = _load_crm(tenant)
        return [s["so_no"] for s in d.sales_orders]
    except (Exception, TenantBuilding):  # noqa: BLE001
        return ["XSO20260005"]


# ───────────────────────── minrui（机械/电子制造） ─────────────────────────


def _build_minrui() -> MesData:
    R = D.rng(20240601)

    lines = [
        {"code": "LINE-A", "name": "装配 A 线", "workshop": "总装车间", "product_type": "成品装配"},
        {"code": "LINE-B", "name": "机加工 B 线", "workshop": "机加工车间", "product_type": "数控加工"},
        {"code": "LINE-C", "name": "表面处理 C 线", "workshop": "表面处理车间", "product_type": "喷涂氧化"},
    ]
    line_by_code = {l["code"]: l for l in lines}

    equipment = [
        {"code": "EQ-A01", "name": "装配台 A01", "line": "LINE-A", "type": "装配工位", "status": "running"},
        {"code": "EQ-A02", "name": "拧紧机 A02", "line": "LINE-A", "type": "电动拧紧", "status": "running"},
        {"code": "EQ-B01", "name": "CNC 加工中心 B01", "line": "LINE-B", "type": "立式加工中心", "status": "idle"},
        {"code": "EQ-B02", "name": "CNC 车床 B02", "line": "LINE-B", "type": "数控车床", "status": "fault"},
        {"code": "EQ-C01", "name": "喷涂线 C01", "line": "LINE-C", "type": "自动喷涂", "status": "running"},
        {"code": "EQ-C02", "name": "氧化槽 C02", "line": "LINE-C", "type": "阳极氧化", "status": "maintenance"},
    ]
    equip_by_code = {e["code"]: e for e in equipment}
    equip_faults = {
        "EQ-B02": {"code": "F-SP-013", "desc": "主轴伺服报警", "since": f"{BASE_DATE - timedelta(days=1)}T08:20:00"},
    }

    products = [
        {
            "product_code": "P-MOTOR-100",
            "name": "伺服电机 100W",
            "uom": "台",
            "routing": [
                {"seq": 10, "name": "绕线", "line": "LINE-B", "std_minutes": 6.0},
                {"seq": 20, "name": "机加工外壳", "line": "LINE-B", "std_minutes": 9.0},
                {"seq": 30, "name": "表面喷涂", "line": "LINE-C", "std_minutes": 4.0},
                {"seq": 40, "name": "总装", "line": "LINE-A", "std_minutes": 7.5},
                {"seq": 50, "name": "试运行", "line": "LINE-A", "std_minutes": 3.0},
            ],
        },
        {
            "product_code": "P-DRIVE-200",
            "name": "驱动器 200W",
            "uom": "台",
            "routing": [
                {"seq": 10, "name": "PCB 贴片", "line": "LINE-B", "std_minutes": 5.0},
                {"seq": 20, "name": "外壳机加工", "line": "LINE-B", "std_minutes": 8.0},
                {"seq": 30, "name": "氧化", "line": "LINE-C", "std_minutes": 6.0},
                {"seq": 40, "name": "总装调试", "line": "LINE-A", "std_minutes": 10.0},
            ],
        },
        {
            "product_code": "P-SENSOR-50",
            "name": "位移传感器 50mm",
            "uom": "支",
            "routing": [
                {"seq": 10, "name": "机加工壳体", "line": "LINE-B", "std_minutes": 4.5},
                {"seq": 20, "name": "喷涂", "line": "LINE-C", "std_minutes": 3.0},
                {"seq": 30, "name": "装配标定", "line": "LINE-A", "std_minutes": 6.0},
            ],
        },
    ]
    product_by_code = {p["product_code"]: p for p in products}

    shifts = ["早班", "中班", "晚班"]
    order_status = ["已下达", "在制", "完工", "关闭"]
    wo_status = ["待开工", "在制", "暂停", "完工"]

    production_orders: list[dict] = []
    for i in range(5):
        product = D.pick(R, products)
        plan_qty = D.randint(R, 200, 1200)
        done_qty = D.randint(R, int(plan_qty * 0.3), plan_qty)
        due = BASE_DATE + timedelta(days=D.randint(R, -2, 10))
        order_no = f"PO{D.pad(20260000 + i * 137 + 11)}"
        production_orders.append({
            "order_no": order_no,
            "product_code": product["product_code"],
            "product_name": product["name"],
            "plan_qty": plan_qty,
            "done_qty": done_qty,
            "uom": product["uom"],
            "status": D.pick(R, order_status),
            "line": D.pick(R, lines)["code"],
            "planned_start": f"{BASE_DATE - timedelta(days=D.randint(R, 1, 5))}",
            "due_date": f"{due}",
        })
    production_order_by_no = {p["order_no"]: p for p in production_orders}

    work_orders: list[dict] = []
    for i in range(12):
        product = D.pick(R, products)
        line = D.pick(R, lines)["code"]
        plan_qty = D.randint(R, 50, 400)
        done_qty = D.randint(R, 0, plan_qty)
        won = f"WO{D.pad(20260600 + i * 91 + 7)}"
        work_orders.append({
            "work_order_no": won,
            "order_no": D.pick(R, production_orders)["order_no"],
            "product_code": product["product_code"],
            "product_name": product["name"],
            "line": line,
            "plan_qty": plan_qty,
            "done_qty": done_qty,
            "defect_qty": D.randint(R, 0, max(1, done_qty // 20)),
            "uom": product["uom"],
            "status": D.pick(R, wo_status),
            "shift": D.pick(R, shifts),
            "planned_start": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 3))}T08:00:00",
            "operator": f"OP{D.pad(D.randint(R, 1, 40))}",
        })
    work_order_by_no = {w["work_order_no"]: w for w in work_orders}

    # 报工（按工单 + 工序派生）
    work_reports: list[dict] = []
    for i in range(12):
        wo = D.pick(R, work_orders)
        routing = product_by_code[wo["product_code"]]["routing"]
        op = D.pick(R, routing)
        plan = D.randint(R, 20, 80)
        accepted = D.randint(R, int(plan * 0.7), plan)
        work_reports.append({
            "report_id": f"WR{D.pad(20260600 + i * 53)}",
            "work_order_no": wo["work_order_no"],
            "product_code": wo["product_code"],
            "line": wo["line"],
            "operation_seq": op["seq"],
            "operation_name": op["name"],
            "plan_qty": plan,
            "reported_qty": accepted,
            "defect_qty": D.randint(R, 0, max(1, accepted // 12)),
            "operator": f"OP{D.pad(D.randint(R, 1, 40))}",
            "shift": D.pick(R, shifts),
            "reported_at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 3))}T{D.pad(D.randint(R, 8, 20))}:30:00",
        })

    defect_types = [
        {"code": "D-DIM-01", "name": "尺寸超差"},
        {"code": "D-SURF-02", "name": "表面划伤"},
        {"code": "D-ELEC-03", "name": "电气性能不合格"},
        {"code": "D-ASSY-04", "name": "装配错件"},
        {"code": "D-LEAK-05", "name": "密封泄漏"},
    ]
    defects: list[dict] = []
    for i in range(10):
        wo = D.pick(R, work_orders)
        dt = D.pick(R, defect_types)
        defects.append({
            "defect_id": f"DF{D.pad(20260600 + i * 53)}",
            "work_order_no": wo["work_order_no"],
            "product_code": wo["product_code"],
            "line": wo["line"],
            "defect_code": dt["code"],
            "defect_name": dt["name"],
            "defect_type": dt["name"],
            "qty": D.randint(R, 1, 12),
            "severity": D.pick(R, ["轻微", "一般", "严重"]),
            "found_at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 2))}T{D.pad(D.randint(R, 8, 20))}:30:00",
            "station": D.pick(R, ["IPQC", "OQC", "自检"]),
            "status": D.pick(R, ["待处理", "已返工", "已让步"]),
        })

    shift_outputs: list[dict] = []
    for d_off in range(-2, 2):
        for line in lines:
            for sh in shifts:
                plan = D.randint(R, 80, 200)
                actual = D.randint(R, int(plan * 0.6), plan)
                shift_outputs.append({
                    "date": f"{BASE_DATE + timedelta(days=d_off)}",
                    "line": line["code"],
                    "shift": sh,
                    "plan_qty": plan,
                    "actual_qty": actual,
                    "defect_qty": D.randint(R, 0, max(1, actual // 15)),
                })

    wip: list[dict] = []
    for wo in work_orders:
        if wo["status"] in ("在制", "暂停"):
            seqs = product_by_code[wo["product_code"]]["routing"]
            st = D.pick(R, seqs)
            wip.append({
                "work_order_no": wo["work_order_no"],
                "product_code": wo["product_code"],
                "line": wo["line"],
                "current_seq": st["seq"],
                "current_station": st["name"],
                "in_process_qty": D.randint(R, 5, max(6, wo["plan_qty"] // 4)),
                "hold": wo["status"] == "暂停",
            })

    return MesData(
        lines=lines, line_by_code=line_by_code,
        equipment=equipment, equip_by_code=equip_by_code, equip_faults=equip_faults,
        products=products, product_by_code=product_by_code,
        production_orders=production_orders, production_order_by_no=production_order_by_no,
        work_orders=work_orders, work_order_by_no=work_order_by_no,
        work_reports=work_reports, defects=defects,
        shift_outputs=shift_outputs, wip=wip,
    )


# ───────────────────────── starclothing（服装） ─────────────────────────


_XINGTU_DEFECT_TYPES = [
    {"code": "D-LEAK", "name": "漏水", "cause": "压胶处渗水"},
    {"code": "D-GLUE", "name": "压胶脱落", "cause": "高温熨烫/胶水固化不足"},
    {"code": "D-PILL", "name": "面料起球", "cause": "摩擦起毛"},
    {"code": "D-FADE", "name": "掉色", "cause": "染料色牢度不足"},
    {"code": "D-DIM", "name": "尺寸偏差", "cause": "裁剪/车缝公差超标"},
    {"code": "D-SKIP", "name": "跳针/断线", "cause": "车缝设备故障"},
    {"code": "D-PRT", "name": "印花错位", "cause": "丝网对位偏差"},
    {"code": "D-BURN", "name": "整烫烫花", "cause": "温度过高"},
]


def _build_starclothing() -> MesData:
    """星图服装口径 MES 数据：裁剪/车缝/印花/后整/包装产线，服装工艺与缺陷口径。"""
    R = D.rng(20241120)

    lines = [
        {"code": "LINE-CUT", "name": "裁剪车间", "workshop": "裁剪车间", "product_type": "裁剪"},
        {"code": "LINE-SEW-A", "name": "车缝 A 线", "workshop": "车缝车间", "product_type": "平车"},
        {"code": "LINE-SEW-B", "name": "车缝 B 线", "workshop": "车缝车间", "product_type": "包缝"},
        {"code": "LINE-PRT", "name": "印花车间", "workshop": "印花车间", "product_type": "丝网印花"},
        {"code": "LINE-FIN", "name": "后整车间", "workshop": "后整车间", "product_type": "整烫包装"},
        {"code": "LINE-PKG", "name": "包装车间", "workshop": "包装车间", "product_type": "折叠入箱"},
    ]
    line_by_code = {l["code"]: l for l in lines}

    equipment = [
        {"code": "EQ-CUT-01", "name": "自动裁床 CUT-01", "line": "LINE-CUT", "type": "自动裁床", "status": "running"},
        {"code": "EQ-CUT-02", "name": "手动裁刀 CUT-02", "line": "LINE-CUT", "type": "手动裁刀", "status": "idle"},
        {"code": "EQ-SEW-01", "name": "平缝机 SEW-01", "line": "LINE-SEW-A", "type": "平缝机", "status": "running"},
        {"code": "EQ-SEW-02", "name": "平缝机 SEW-02", "line": "LINE-SEW-A", "type": "平缝机", "status": "fault"},
        {"code": "EQ-SEW-03", "name": "包缝机 SEW-03", "line": "LINE-SEW-B", "type": "包缝机", "status": "running"},
        {"code": "EQ-SEW-04", "name": "包缝机 SEW-04", "line": "LINE-SEW-B", "type": "包缝机", "status": "running"},
        {"code": "EQ-PRT-01", "name": "丝网印花台 PRT-01", "line": "LINE-PRT", "type": "丝网印花台", "status": "running"},
        {"code": "EQ-FIN-01", "name": "整烫台 FIN-01", "line": "LINE-FIN", "type": "整烫台", "status": "running"},
        {"code": "EQ-FIN-02", "name": "整烫台 FIN-02", "line": "LINE-FIN", "type": "整烫台", "status": "maintenance"},
        {"code": "EQ-PKG-01", "name": "折叠包装机 PKG-01", "line": "LINE-PKG", "type": "折叠包装机", "status": "running"},
    ]
    equip_by_code = {e["code"]: e for e in equipment}
    equip_faults = {
        "EQ-SEW-02": {"code": "F-SEW-021", "desc": "跳针报警", "since": f"{BASE_DATE - timedelta(days=1)}T08:20:00"},
        "EQ-FIN-02": {"code": "F-FIN-022", "desc": "温控异常待维护", "since": f"{BASE_DATE - timedelta(days=2)}T10:00:00"},
    }

    products = [
        {
            "product_code": "P-FW2026-001",
            "name": "双面呢长大衣",
            "uom": "件",
            "routing": [
                {"seq": 10, "name": "裁剪", "line": "LINE-CUT", "std_minutes": 30.0},
                {"seq": 20, "name": "粘衬", "line": "LINE-CUT", "std_minutes": 15.0},
                {"seq": 30, "name": "车缝", "line": "LINE-SEW-A", "std_minutes": 90.0},
                {"seq": 40, "name": "手缝", "line": "LINE-SEW-A", "std_minutes": 25.0},
                {"seq": 50, "name": "整烫", "line": "LINE-FIN", "std_minutes": 20.0},
            ],
        },
        {
            "product_code": "P-FW2026-002",
            "name": "压胶冲锋衣",
            "uom": "件",
            "routing": [
                {"seq": 10, "name": "裁剪", "line": "LINE-CUT", "std_minutes": 20.0},
                {"seq": 20, "name": "压胶", "line": "LINE-SEW-A", "std_minutes": 40.0},
                {"seq": 30, "name": "车缝", "line": "LINE-SEW-A", "std_minutes": 60.0},
                {"seq": 40, "name": "质检", "line": "LINE-SEW-A", "std_minutes": 15.0},
                {"seq": 50, "name": "整烫", "line": "LINE-FIN", "std_minutes": 15.0},
            ],
        },
        {
            "product_code": "P-SS2026-010",
            "name": "纯棉T恤",
            "uom": "件",
            "routing": [
                {"seq": 10, "name": "裁剪", "line": "LINE-CUT", "std_minutes": 5.0},
                {"seq": 20, "name": "车缝", "line": "LINE-SEW-A", "std_minutes": 10.0},
                {"seq": 30, "name": "包边", "line": "LINE-SEW-B", "std_minutes": 5.0},
                {"seq": 40, "name": "整烫", "line": "LINE-FIN", "std_minutes": 5.0},
            ],
        },
        {
            "product_code": "P-SS2026-011",
            "name": "摇粒绒开衫",
            "uom": "件",
            "routing": [
                {"seq": 10, "name": "裁剪", "line": "LINE-CUT", "std_minutes": 8.0},
                {"seq": 20, "name": "车缝", "line": "LINE-SEW-A", "std_minutes": 16.0},
                {"seq": 30, "name": "包边", "line": "LINE-SEW-B", "std_minutes": 8.0},
                {"seq": 40, "name": "整烫", "line": "LINE-FIN", "std_minutes": 8.0},
            ],
        },
        {
            "product_code": "P-SS2026-020",
            "name": "牛仔裤",
            "uom": "条",
            "routing": [
                {"seq": 10, "name": "裁剪", "line": "LINE-CUT", "std_minutes": 15.0},
                {"seq": 20, "name": "车缝", "line": "LINE-SEW-A", "std_minutes": 40.0},
                {"seq": 30, "name": "包边", "line": "LINE-SEW-B", "std_minutes": 10.0},
                {"seq": 40, "name": "水洗", "line": "LINE-FIN", "std_minutes": 15.0},
                {"seq": 50, "name": "整烫", "line": "LINE-FIN", "std_minutes": 15.0},
            ],
        },
        {
            "product_code": "P-AP2026-030",
            "name": "风衣",
            "uom": "件",
            "routing": [
                {"seq": 10, "name": "裁剪", "line": "LINE-CUT", "std_minutes": 20.0},
                {"seq": 20, "name": "粘衬", "line": "LINE-CUT", "std_minutes": 15.0},
                {"seq": 30, "name": "车缝", "line": "LINE-SEW-A", "std_minutes": 55.0},
                {"seq": 40, "name": "手缝", "line": "LINE-SEW-A", "std_minutes": 15.0},
                {"seq": 50, "name": "整烫", "line": "LINE-FIN", "std_minutes": 15.0},
            ],
        },
        {
            "product_code": "P-AP2026-031",
            "name": "衬衫",
            "uom": "件",
            "routing": [
                {"seq": 10, "name": "裁剪", "line": "LINE-CUT", "std_minutes": 8.0},
                {"seq": 20, "name": "粘衬", "line": "LINE-CUT", "std_minutes": 6.0},
                {"seq": 30, "name": "车缝", "line": "LINE-SEW-A", "std_minutes": 25.0},
                {"seq": 40, "name": "钉扣", "line": "LINE-SEW-B", "std_minutes": 6.0},
                {"seq": 50, "name": "整烫", "line": "LINE-FIN", "std_minutes": 10.0},
            ],
        },
        {
            "product_code": "P-AP2026-032",
            "name": "卫衣",
            "uom": "件",
            "routing": [
                {"seq": 10, "name": "裁剪", "line": "LINE-CUT", "std_minutes": 8.0},
                {"seq": 20, "name": "车缝", "line": "LINE-SEW-A", "std_minutes": 18.0},
                {"seq": 30, "name": "印花", "line": "LINE-PRT", "std_minutes": 12.0},
                {"seq": 40, "name": "整烫", "line": "LINE-FIN", "std_minutes": 7.0},
            ],
        },
    ]
    product_by_code = {p["product_code"]: p for p in products}

    shifts = ["早班", "中班", "晚班"]
    order_status = ["已排产", "进行中", "已完工", "暂停"]
    wo_status = ["待开工", "进行中", "已完工", "暂停"]
    customers = ["星图自营", "天猫旗舰", "京东自营", "唯品会", "海外ODM"]

    production_orders: list[dict] = []
    for i in range(9):
        product = D.pick(R, products)
        plan_qty = D.randint(R, 200, 1500)
        done_qty = D.randint(R, int(plan_qty * 0.3), plan_qty)
        due = BASE_DATE + timedelta(days=D.randint(R, -30, 30))
        order_no = f"XPO{D.pad(20260000 + i * 137 + 11)}"
        production_orders.append({
            "order_no": order_no,
            "product_code": product["product_code"],
            "product_name": product["name"],
            "plan_qty": plan_qty,
            "done_qty": done_qty,
            "uom": product["uom"],
            "status": D.pick(R, order_status),
            "line": D.pick(R, lines)["code"],
            "customer": D.pick(R, customers),
            "factory": "星图杭州工厂",
            "planned_start": f"{BASE_DATE - timedelta(days=D.randint(R, 1, 30))}",
            "due_date": f"{due}",
        })
    production_order_by_no = {p["order_no"]: p for p in production_orders}

    crm_sos = _crm_sales_orders("starclothing")
    work_orders: list[dict] = []
    for i in range(14):
        product = D.pick(R, products)
        line = D.pick(R, lines)["code"]
        plan_qty = D.randint(R, 50, 600)
        done_qty = D.randint(R, 0, plan_qty)
        won = f"XWO{D.pad(20260600 + i * 91 + 7)}"
        po = D.pick(R, production_orders)
        work_orders.append({
            "work_order_no": won,
            "order_no": po["order_no"],
            "sales_order_no": D.pick(R, crm_sos),
            "product_code": product["product_code"],
            "product_name": product["name"],
            "line": line,
            "plan_qty": plan_qty,
            "done_qty": done_qty,
            "defect_qty": D.randint(R, 0, max(1, done_qty // 15)),
            "uom": product["uom"],
            "status": D.pick(R, wo_status),
            "shift": D.pick(R, shifts),
            "planned_start": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 20))}T08:00:00",
            "planned_end": f"{BASE_DATE + timedelta(days=D.randint(R, 0, 15))}T17:00:00",
            "actual_start": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 15))}T08:00:00" if done_qty > 0 else None,
            "operator": f"OP{D.pad(D.randint(R, 1, 60))}",
        })
    work_order_by_no = {w["work_order_no"]: w for w in work_orders}

    # 报工：按工单 + 工序，20-30 条
    work_reports: list[dict] = []
    for i in range(26):
        wo = D.pick(R, work_orders)
        routing = product_by_code[wo["product_code"]]["routing"]
        op = D.pick(R, routing)
        plan = D.randint(R, 20, 100)
        accepted = D.randint(R, int(plan * 0.7), plan)
        work_reports.append({
            "report_id": f"XWR{D.pad(20260600 + i * 37)}",
            "work_order_no": wo["work_order_no"],
            "product_code": wo["product_code"],
            "line": wo["line"],
            "operation_seq": op["seq"],
            "operation_name": op["name"],
            "plan_qty": plan,
            "reported_qty": accepted,
            "defect_qty": D.randint(R, 0, max(1, accepted // 12)),
            "operator": f"OP{D.pad(D.randint(R, 1, 60))}",
            "shift": D.pick(R, shifts),
            "reported_at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 14))}T{D.pad(D.randint(R, 8, 20))}:30:00",
        })

    defects: list[dict] = []
    for i in range(18):
        wo = D.pick(R, work_orders)
        dt = D.pick(R, _XINGTU_DEFECT_TYPES)
        routing = product_by_code[wo["product_code"]]["routing"]
        op = D.pick(R, routing)
        defects.append({
            "defect_id": f"XDF{D.pad(20260600 + i * 29)}",
            "work_order_no": wo["work_order_no"],
            "product_code": wo["product_code"],
            "line": wo["line"],
            "defect_code": dt["code"],
            "defect_name": dt["name"],
            "defect_type": dt["name"],
            "severity": D.pick(R, ["轻", "中", "重"]),
            "qty": D.randint(R, 1, 20),
            "operation": op["name"],
            "found_at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 12))}T{D.pad(D.randint(R, 8, 20))}:30:00",
            "root_cause": dt["cause"],
            "status": D.pick(R, ["待处理", "已返工", "已让步"]),
        })

    # 班次产量：18 条（产线 + 班次 + 日期组合抽样）
    shift_outputs: list[dict] = []
    date_pool = [BASE_DATE + timedelta(days=d_off) for d_off in range(-2, 3)]
    combos = [(d, l, s) for d in date_pool for l in lines for s in shifts]
    for d, l, sh in D.sample(R, combos, 18):
        plan = D.randint(R, 80, 300)
        actual = D.randint(R, int(plan * 0.6), plan)
        shift_outputs.append({
            "date": f"{d}",
            "line": l["code"],
            "shift": sh,
            "plan_qty": plan,
            "actual_qty": actual,
            "defect_qty": D.randint(R, 0, max(1, actual // 15)),
            "yield_rate": round(actual / plan, 4) if plan else 0.0,
        })

    # 在制品：10 条（抽样工单）
    wip: list[dict] = []
    for wo in D.sample(R, work_orders, min(10, len(work_orders))):
        routing = product_by_code[wo["product_code"]]["routing"]
        st = D.pick(R, routing)
        wip.append({
            "work_order_no": wo["work_order_no"],
            "product_code": wo["product_code"],
            "line": wo["line"],
            "current_seq": st["seq"],
            "current_station": st["name"],
            "in_process_qty": D.randint(R, 5, max(6, wo["plan_qty"] // 4)),
            "hold": wo["status"] == "暂停",
        })

    return MesData(
        lines=lines, line_by_code=line_by_code,
        equipment=equipment, equip_by_code=equip_by_code, equip_faults=equip_faults,
        products=products, product_by_code=product_by_code,
        production_orders=production_orders, production_order_by_no=production_order_by_no,
        work_orders=work_orders, work_order_by_no=work_order_by_no,
        work_reports=work_reports, defects=defects,
        shift_outputs=shift_outputs, wip=wip,
    )


# ───────────────────────── agileac（敏睿空调） ─────────────────────────


_AGILEAC_DEFECT_TYPES = [
    {"code": "D-NOCOOL", "name": "不制冷", "cause": "压缩机/冷媒/控制板故障导致制冷失效"},
    {"code": "D-LEAK", "name": "漏水", "cause": "蒸发器接水盘/排水管/冷凝水管异常"},
    {"code": "D-NOISE", "name": "异音", "cause": "压缩机减振/风叶动平衡/螺丝松动"},
    {"code": "D-COMM", "name": "通讯故障", "cause": "室内外机通讯线/CAN 总线/控制板故障"},
    {"code": "D-HP", "name": "高压保护", "cause": "冷凝器散热不良/冷却水流量不足"},
    {"code": "D-REF", "name": "冷媒泄漏", "cause": "焊点/喇叭口/电子膨胀阀泄漏"},
    {"code": "D-DEFROST", "name": "化霜失效", "cause": "化霜传感器/化霜逻辑参数错误"},
    {"code": "D-BOARD", "name": "控制板故障", "cause": "MCU 虚焊/保险丝烧毁/电源板故障"},
]


def _build_agileac() -> MesData:
    """敏睿空调 MES 数据：家用总装线/商用总装线/测试线 + 6 款空调产品工艺路线 +
    工单（含 AG-SVC-01 3 条重点故障工单 AWO20260101/0105/0210）+ 8 类空调故障缺陷。"""
    R = D.rng(20260102)

    lines = [
        {"code": "LINE-RC-ASSY", "name": "家用总装线", "workshop": "家用总装车间", "product_type": "家用空调总装"},
        {"code": "LINE-CC-ASSY", "name": "商用总装线", "workshop": "商用总装车间", "product_type": "商用空调总装"},
        {"code": "LINE-TEST", "name": "测试线", "workshop": "测试车间", "product_type": "全性能测试"},
        {"code": "LINE-PIP", "name": "配管预制线", "workshop": "配管车间", "product_type": "铜管预制+焊接"},
    ]
    line_by_code = {l["code"]: l for l in lines}

    equipment = [
        {"code": "EQ-RC-01", "name": "家用总装台 RC-01", "line": "LINE-RC-ASSY", "type": "总装工位", "status": "running"},
        {"code": "EQ-RC-02", "name": "冷媒充注机 RC-02", "line": "LINE-RC-ASSY", "type": "冷媒充注", "status": "running"},
        {"code": "EQ-RC-03", "name": "真空泵 RC-03", "line": "LINE-RC-ASSY", "type": "抽真空", "status": "idle"},
        {"code": "EQ-CC-01", "name": "商用总装台 CC-01", "line": "LINE-CC-ASSY", "type": "总装工位", "status": "running"},
        {"code": "EQ-CC-02", "name": "商用冷媒充注机 CC-02", "line": "LINE-CC-ASSY", "type": "冷媒充注", "status": "fault"},
        {"code": "EQ-CC-03", "name": "商用焊接机 CC-03", "line": "LINE-CC-ASSY", "type": "铜管焊接", "status": "running"},
        {"code": "EQ-TST-01", "name": "氦检漏仪 TST-01", "line": "LINE-TEST", "type": "氦检漏", "status": "running"},
        {"code": "EQ-TST-02", "name": "水检漏槽 TST-02", "line": "LINE-TEST", "type": "水检漏", "status": "running"},
        {"code": "EQ-TST-03", "name": "电子检漏仪 TST-03", "line": "LINE-TEST", "type": "电子检漏", "status": "running"},
        {"code": "EQ-TST-04", "name": "性能测试台 TST-04", "line": "LINE-TEST", "type": "全性能测试", "status": "maintenance"},
        {"code": "EQ-PIP-01", "name": "弯管机 PIP-01", "line": "LINE-PIP", "type": "数控弯管", "status": "running"},
        {"code": "EQ-PIP-02", "name": "扩口机 PIP-02", "line": "LINE-PIP", "type": "喇叭口扩口", "status": "running"},
    ]
    equip_by_code = {e["code"]: e for e in equipment}
    equip_faults = {
        "EQ-CC-02": {"code": "F-CC-021", "desc": "冷媒充注压力异常", "since": f"{BASE_DATE - timedelta(days=1)}T08:20:00"},
        "EQ-TST-04": {"code": "F-TST-041", "desc": "性能测试台温控故障待维护", "since": f"{BASE_DATE - timedelta(days=2)}T10:00:00"},
    }

    products = [
        {
            "product_code": "P-RC-WALL-15",
            "name": "1.5匹壁挂式家用空调",
            "uom": "台",
            "routing": [
                {"seq": 10, "name": "配管预制", "line": "LINE-PIP", "std_minutes": 8.0},
                {"seq": 20, "name": "换热器装配", "line": "LINE-RC-ASSY", "std_minutes": 12.0},
                {"seq": 30, "name": "压缩机装配", "line": "LINE-RC-ASSY", "std_minutes": 10.0},
                {"seq": 40, "name": "焊接+检漏", "line": "LINE-RC-ASSY", "std_minutes": 15.0},
                {"seq": 50, "name": "冷媒充注", "line": "LINE-RC-ASSY", "std_minutes": 6.0},
                {"seq": 60, "name": "性能测试", "line": "LINE-TEST", "std_minutes": 12.0},
            ],
        },
        {
            "product_code": "P-RC-CAB-30",
            "name": "3匹立柜式家用空调",
            "uom": "台",
            "routing": [
                {"seq": 10, "name": "配管预制", "line": "LINE-PIP", "std_minutes": 10.0},
                {"seq": 20, "name": "换热器装配", "line": "LINE-RC-ASSY", "std_minutes": 16.0},
                {"seq": 30, "name": "压缩机装配", "line": "LINE-RC-ASSY", "std_minutes": 12.0},
                {"seq": 40, "name": "焊接+检漏", "line": "LINE-RC-ASSY", "std_minutes": 18.0},
                {"seq": 50, "name": "冷媒充注", "line": "LINE-RC-ASSY", "std_minutes": 8.0},
                {"seq": 60, "name": "性能测试", "line": "LINE-TEST", "std_minutes": 14.0},
            ],
        },
        {
            "product_code": "P-RC-MOVE-10",
            "name": "1匹移动空调",
            "uom": "台",
            "routing": [
                {"seq": 10, "name": "外壳装配", "line": "LINE-RC-ASSY", "std_minutes": 14.0},
                {"seq": 20, "name": "换热器装配", "line": "LINE-RC-ASSY", "std_minutes": 10.0},
                {"seq": 30, "name": "压缩机装配", "line": "LINE-RC-ASSY", "std_minutes": 8.0},
                {"seq": 40, "name": "焊接+检漏", "line": "LINE-RC-ASSY", "std_minutes": 12.0},
                {"seq": 50, "name": "性能测试", "line": "LINE-TEST", "std_minutes": 10.0},
            ],
        },
        {
            "product_code": "P-CC-VRV-360",
            "name": "360型家用商用多联机外机",
            "uom": "台",
            "routing": [
                {"seq": 10, "name": "配管预制", "line": "LINE-PIP", "std_minutes": 20.0},
                {"seq": 20, "name": "换热器装配", "line": "LINE-CC-ASSY", "std_minutes": 35.0},
                {"seq": 30, "name": "压缩机装配", "line": "LINE-CC-ASSY", "std_minutes": 25.0},
                {"seq": 40, "name": "焊接+检漏", "line": "LINE-CC-ASSY", "std_minutes": 45.0},
                {"seq": 50, "name": "冷媒充注", "line": "LINE-CC-ASSY", "std_minutes": 18.0},
                {"seq": 60, "name": "通讯板装配", "line": "LINE-CC-ASSY", "std_minutes": 15.0},
                {"seq": 70, "name": "性能测试", "line": "LINE-TEST", "std_minutes": 30.0},
            ],
        },
        {
            "product_code": "P-CC-DUCT-50",
            "name": "50型商用风管机",
            "uom": "台",
            "routing": [
                {"seq": 10, "name": "配管预制", "line": "LINE-PIP", "std_minutes": 15.0},
                {"seq": 20, "name": "换热器装配", "line": "LINE-CC-ASSY", "std_minutes": 22.0},
                {"seq": 30, "name": "压缩机装配", "line": "LINE-CC-ASSY", "std_minutes": 18.0},
                {"seq": 40, "name": "焊接+检漏", "line": "LINE-CC-ASSY", "std_minutes": 25.0},
                {"seq": 50, "name": "冷媒充注", "line": "LINE-CC-ASSY", "std_minutes": 12.0},
                {"seq": 60, "name": "性能测试", "line": "LINE-TEST", "std_minutes": 20.0},
            ],
        },
        {
            "product_code": "P-CC-CHILL-100",
            "name": "100RT模块冷水机组",
            "uom": "台",
            "routing": [
                {"seq": 10, "name": "配管预制", "line": "LINE-PIP", "std_minutes": 30.0},
                {"seq": 20, "name": "换热器装配", "line": "LINE-CC-ASSY", "std_minutes": 50.0},
                {"seq": 30, "name": "压缩机装配", "line": "LINE-CC-ASSY", "std_minutes": 40.0},
                {"seq": 40, "name": "焊接+检漏", "line": "LINE-CC-ASSY", "std_minutes": 60.0},
                {"seq": 50, "name": "冷媒充注", "line": "LINE-CC-ASSY", "std_minutes": 30.0},
                {"seq": 60, "name": "主控板+CAN 总线", "line": "LINE-CC-ASSY", "std_minutes": 25.0},
                {"seq": 70, "name": "水力测试", "line": "LINE-TEST", "std_minutes": 40.0},
                {"seq": 80, "name": "性能测试", "line": "LINE-TEST", "std_minutes": 45.0},
            ],
        },
    ]
    product_by_code = {p["product_code"]: p for p in products}

    shifts = ["早班", "中班", "晚班"]
    order_status = ["已排产", "进行中", "已完工", "暂停"]
    wo_status = ["待开工", "进行中", "已完工", "暂停"]

    production_orders: list[dict] = []
    po_specs = [
        ("PO20260101", "P-RC-WALL-15", "家用空调经销商", "敏睿空调杭州工厂", 500, 500, "已完工", "LINE-RC-ASSY"),
        ("PO20260102", "P-RC-CAB-30", "家用空调经销商", "敏睿空调杭州工厂", 300, 180, "进行中", "LINE-RC-ASSY"),
        ("PO20260103", "P-RC-MOVE-10", "电商平台", "敏睿空调杭州工厂", 200, 200, "已完工", "LINE-RC-ASSY"),
        ("PO20260201", "P-CC-VRV-360", "工程项目", "敏睿空调上海工厂", 80, 50, "进行中", "LINE-CC-ASSY"),
        ("PO20260202", "P-CC-DUCT-50", "工程项目", "敏睿空调上海工厂", 120, 70, "进行中", "LINE-CC-ASSY"),
        ("PO20260203", "P-CC-CHILL-100", "工程项目", "敏睿空调广州工厂", 30, 12, "进行中", "LINE-CC-ASSY"),
    ]
    for order_no, pcode, customer, factory, plan, done, status, line in po_specs:
        due = BASE_DATE + timedelta(days=D.randint(R, 5, 30))
        production_orders.append({
            "order_no": order_no,
            "product_code": pcode,
            "product_name": product_by_code[pcode]["name"],
            "plan_qty": plan,
            "done_qty": done,
            "uom": "台",
            "status": status,
            "line": line,
            "customer": customer,
            "factory": factory,
            "planned_start": f"{BASE_DATE - timedelta(days=D.randint(R, 5, 30))}",
            "due_date": f"{due}",
        })
    production_order_by_no = {p["order_no"]: p for p in production_orders}

    # 工单：6 条主工单（AG-SVC-01 重点工单 AWO20260101/0105/0210）+ 6 条辅助工单
    wo_specs = [
        # (won, order_no, product_code, line, plan, done, status, off_start)
        ("AWO20260101", "PO20260101", "P-RC-WALL-15", "LINE-RC-ASSY", 500, 500, "已完工", -15),
        ("AWO20260102", "PO20260101", "P-RC-WALL-15", "LINE-RC-ASSY", 200, 200, "已完工", -10),
        ("AWO20260103", "PO20260101", "P-RC-WALL-15", "LINE-RC-ASSY", 100, 80, "进行中", -5),
        ("AWO20260104", "PO20260101", "P-RC-WALL-15", "LINE-RC-ASSY", 100, 100, "已完工", -3),
        ("AWO20260105", "PO20260102", "P-RC-CAB-30", "LINE-RC-ASSY", 300, 150, "进行中", -8),
        ("AWO20260106", "PO20260102", "P-RC-CAB-30", "LINE-RC-ASSY", 150, 120, "进行中", -5),
        ("AWO20260107", "PO20260102", "P-RC-CAB-30", "LINE-RC-ASSY", 50, 50, "已完工", -2),
        ("AWO20260108", "PO20260103", "P-RC-MOVE-10", "LINE-RC-ASSY", 200, 200, "已完工", -6),
        ("AWO20260109", "PO20260103", "P-RC-MOVE-10", "LINE-RC-ASSY", 100, 60, "进行中", -2),
        ("AWO20260210", "PO20260201", "P-CC-VRV-360", "LINE-CC-ASSY", 80, 40, "进行中", -10),
        ("AWO20260211", "PO20260201", "P-CC-VRV-360", "LINE-CC-ASSY", 20, 10, "进行中", -3),
        ("AWO20260212", "PO20260201", "P-CC-VRV-360", "LINE-CC-ASSY", 20, 0, "待开工", 2),
        ("AWO20260213", "PO20260201", "P-CC-VRV-360", "LINE-CC-ASSY", 10, 0, "暂停", -1),
        ("AWO20260214", "PO20260201", "P-CC-VRV-360", "LINE-TEST", 5, 0, "待开工", 5),
        ("AWO20260215", "PO20260202", "P-CC-DUCT-50", "LINE-CC-ASSY", 120, 70, "进行中", -7),
        ("AWO20260216", "PO20260202", "P-CC-DUCT-50", "LINE-CC-ASSY", 50, 30, "进行中", -3),
        ("AWO20260220", "PO20260203", "P-CC-CHILL-100", "LINE-CC-ASSY", 30, 12, "进行中", -15),
        ("AWO20260221", "PO20260203", "P-CC-CHILL-100", "LINE-CC-ASSY", 5, 0, "待开工", 5),
    ]
    crm_sos = _crm_sales_orders("agileac")
    work_orders: list[dict] = []
    for won, order_no, pcode, line, plan, done, status, off_start in wo_specs:
        product = product_by_code[pcode]
        work_orders.append({
            "work_order_no": won,
            "order_no": order_no,
            "sales_order_no": crm_sos[(hash(won) & 0xFFFFFFFF) % len(crm_sos)] if crm_sos else None,
            "product_code": pcode,
            "product_name": product["name"],
            "line": line,
            "plan_qty": plan,
            "done_qty": done,
            "defect_qty": D.randint(R, 0, max(1, done // 15)) if done > 0 else 0,
            "uom": "台",
            "status": status,
            "shift": D.pick(R, shifts),
            "planned_start": f"{BASE_DATE + timedelta(days=off_start)}T08:00:00",
            "planned_end": f"{BASE_DATE + timedelta(days=off_start + 3)}T17:00:00",
            "actual_start": f"{BASE_DATE + timedelta(days=off_start)}T08:30:00" if done > 0 else None,
            "operator": f"OP{D.pad(D.randint(R, 1, 40))}",
        })
    work_order_by_no = {w["work_order_no"]: w for w in work_orders}

    # 报工：18 条
    work_reports: list[dict] = []
    for i in range(18):
        wo = D.pick(R, work_orders)
        routing = product_by_code[wo["product_code"]]["routing"]
        op = D.pick(R, routing)
        plan = D.randint(R, 20, 100)
        accepted = D.randint(R, int(plan * 0.7), plan) if plan > 0 else 0
        work_reports.append({
            "report_id": f"AGWR{D.pad(20260100 + i * 37)}",
            "work_order_no": wo["work_order_no"],
            "product_code": wo["product_code"],
            "line": wo["line"],
            "operation_seq": op["seq"],
            "operation_name": op["name"],
            "plan_qty": plan,
            "reported_qty": accepted,
            "defect_qty": D.randint(R, 0, max(1, accepted // 12)),
            "operator": wo["operator"],
            "shift": D.pick(R, shifts),
            "reported_at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 14))}T{D.pad(D.randint(R, 8, 20), 2)}:30:00",
        })

    # 缺陷：12 条（覆盖 8 类空调故障，含 AG-SVC-01 重点工单的缺陷）
    defect_specs = [
        # (defect_id, won, product_code, line, defect_code, severity, qty, op_name, off)
        ("DF20260101", "AWO20260101", "P-RC-WALL-15", "LINE-RC-ASSY", "D-NOCOOL", "严重", 1, "压缩机装配", -8),
        ("DF20260102", "AWO20260101", "P-RC-WALL-15", "LINE-RC-ASSY", "D-NOISE", "一般", 2, "压缩机装配", -8),
        ("DF20260103", "AWO20260103", "P-RC-WALL-15", "LINE-RC-ASSY", "D-NOCOOL", "一般", 1, "性能测试", -3),
        ("DF20260104", "AWO20260104", "P-RC-WALL-15", "LINE-RC-ASSY", "D-REF", "一般", 1, "焊接+检漏", -2),
        ("DF20260105", "AWO20260105", "P-RC-CAB-30", "LINE-RC-ASSY", "D-LEAK", "严重", 1, "焊接+检漏", -5),
        ("DF20260106", "AWO20260106", "P-RC-CAB-30", "LINE-RC-ASSY", "D-NOISE", "一般", 1, "压缩机装配", -3),
        ("DF20260107", "AWO20260107", "P-RC-CAB-30", "LINE-RC-ASSY", "D-BOARD", "严重", 1, "性能测试", -2),
        ("DF20260108", "AWO20260108", "P-RC-MOVE-10", "LINE-RC-ASSY", "D-NOISE", "一般", 2, "外壳装配", -4),
        ("DF20260109", "AWO20260109", "P-RC-MOVE-10", "LINE-RC-ASSY", "D-BOARD", "一般", 1, "压缩机装配", -1),
        ("DF20260210", "AWO20260210", "P-CC-VRV-360", "LINE-CC-ASSY", "D-COMM", "致命", 1, "通讯板装配", -6),
        ("DF20260211", "AWO20260211", "P-CC-VRV-360", "LINE-CC-ASSY", "D-HP", "严重", 1, "性能测试", -2),
        ("DF20260212", "AWO20260213", "P-CC-VRV-360", "LINE-CC-ASSY", "D-DEFROST", "一般", 1, "性能测试", 0),
        ("DF20260215", "AWO20260215", "P-CC-DUCT-50", "LINE-CC-ASSY", "D-REF", "严重", 1, "焊接+检漏", -5),
        ("DF20260220", "AWO20260220", "P-CC-CHILL-100", "LINE-CC-ASSY", "D-HP", "严重", 1, "性能测试", -10),
        ("DF20260221", "AWO20260220", "P-CC-CHILL-100", "LINE-CC-ASSY", "D-COMM", "严重", 1, "主控板+CAN 总线", -10),
        ("DF20260222", "AWO20260214", "P-CC-VRV-360", "LINE-TEST", "D-LEAK", "严重", 1, "性能测试", 0),
    ]
    defects: list[dict] = []
    for did, won, pcode, line, dcode, sev, qty, op_name, off in defect_specs:
        dt = next(d for d in _AGILEAC_DEFECT_TYPES if d["code"] == dcode)
        defects.append({
            "defect_id": did,
            "work_order_no": won,
            "product_code": pcode,
            "line": line,
            "defect_code": dt["code"],
            "defect_name": dt["name"],
            "defect_type": dt["name"],
            "severity": sev,
            "qty": qty,
            "operation": op_name,
            "found_at": f"{BASE_DATE + timedelta(days=off)}T{D.pad(D.randint(R, 8, 20), 2)}:30:00",
            "root_cause": dt["cause"],
            "status": D.pick(R, ["待处理", "已返工", "已让步"]),
        })

    # 班次产量：18 条
    shift_outputs: list[dict] = []
    date_pool = [BASE_DATE + timedelta(days=d_off) for d_off in range(-2, 3)]
    combos = [(d, l, s) for d in date_pool for l in lines for s in shifts]
    for d, l, sh in D.sample(R, combos, 18):
        plan = D.randint(R, 30, 150)
        actual = D.randint(R, int(plan * 0.6), plan)
        shift_outputs.append({
            "date": f"{d}",
            "line": l["code"],
            "shift": sh,
            "plan_qty": plan,
            "actual_qty": actual,
            "defect_qty": D.randint(R, 0, max(1, actual // 15)),
            "yield_rate": round(actual / plan, 4) if plan else 0.0,
        })

    # 在制品：6 条
    wip: list[dict] = []
    for wo in D.sample(R, [w for w in work_orders if w["status"] == "进行中"], 6):
        routing = product_by_code[wo["product_code"]]["routing"]
        st = D.pick(R, routing)
        wip.append({
            "work_order_no": wo["work_order_no"],
            "product_code": wo["product_code"],
            "line": wo["line"],
            "current_seq": st["seq"],
            "current_station": st["name"],
            "in_process_qty": D.randint(R, 5, max(6, wo["plan_qty"] // 4)),
            "hold": wo["status"] == "暂停",
        })

    return MesData(
        lines=lines, line_by_code=line_by_code,
        equipment=equipment, equip_by_code=equip_by_code, equip_faults=equip_faults,
        products=products, product_by_code=product_by_code,
        production_orders=production_orders, production_order_by_no=production_order_by_no,
        work_orders=work_orders, work_order_by_no=work_order_by_no,
        work_reports=work_reports, defects=defects,
        shift_outputs=shift_outputs, wip=wip,
    )


# ───────────────────────── agilesteel（敏睿钢铁） ─────────────────────────


_AGILESTEEL_DEFECT_TYPES = [
    {"code": "D-CRACK", "name": "表面裂纹", "cause": "连铸坯温应力/轧后冷却过快导致裂纹扩展"},
    {"code": "D-SCRATCH", "name": "表面划伤", "cause": "轧制导卫/输送辊道擦伤"},
    {"code": "D-INCL", "name": "非金属夹杂", "cause": "精炼洁净度不足/连铸保护渣卷入"},
    {"code": "D-SEG", "name": "成分偏析", "cause": "连铸凝固组织不均/浇温控制偏差"},
    {"code": "D-DIM", "name": "尺寸超差", "cause": "轧制孔型磨损/张力控制失稳"},
    {"code": "D-SCALE", "name": "氧化铁皮", "cause": "加热炉氧化严重/除鳞不净"},
    {"code": "D-LAP", "name": "折叠", "cause": "轧件表面缺陷被压入折叠"},
    {"code": "D-MECH", "name": "力学性能不达标", "cause": "成分微调/终轧温度/冷却制度偏差"},
]


def _build_agilesteel() -> MesData:
    """敏睿钢铁 MES 数据：炼铁/炼钢/轧材/特钢产线 + 6 钢种工艺路线 + 炉次(HT 钢铁主实体) +
    工单(SWO)/生产订单(SPO) + 8 类钢材表面缺陷(DF)。炉次 steel_grade 回挂 PLM P-ST- 钢种，
    scrap 配料 SCR- 引 SCM，equipment EQ- 与 EQM 共享码空间。"""
    R = D.rng(20260623)

    lines = [
        {"code": "LINE-IRON", "name": "炼铁产线", "workshop": "炼铁厂", "product_type": "高炉炼铁"},
        {"code": "LINE-STEEL", "name": "炼钢产线", "workshop": "炼钢厂", "product_type": "转炉炼钢+连铸"},
        {"code": "LINE-ROLL", "name": "轧材产线", "workshop": "轧钢厂", "product_type": "连轧"},
        {"code": "LINE-SPECIAL", "name": "特钢产线", "workshop": "特钢厂", "product_type": "特钢深加工"},
    ]
    line_by_code = {l["code"]: l for l in lines}

    equipment = [
        {"code": "EQ-BF-1", "name": "1#高炉", "line": "LINE-IRON", "type": "高炉", "status": "running"},
        {"code": "EQ-BF-2", "name": "2#高炉", "line": "LINE-IRON", "type": "高炉", "status": "running"},
        {"code": "EQ-CV-1", "name": "1#转炉", "line": "LINE-STEEL", "type": "转炉", "status": "running"},
        {"code": "EQ-CV-2", "name": "2#转炉", "line": "LINE-STEEL", "type": "转炉", "status": "fault"},
        {"code": "EQ-CCM-1", "name": "1#连铸机", "line": "LINE-STEEL", "type": "连铸机", "status": "running"},
        {"code": "EQ-LF-1", "name": "1#精炼炉LF", "line": "LINE-STEEL", "type": "精炼炉", "status": "running"},
        {"code": "EQ-RM-1", "name": "1#连轧机", "line": "LINE-ROLL", "type": "连轧机", "status": "running"},
        {"code": "EQ-RM-3", "name": "3#连轧机", "line": "LINE-ROLL", "type": "连轧机", "status": "maintenance"},
        {"code": "EQ-FAN-1", "name": "1#除尘风机", "line": "LINE-SPECIAL", "type": "除尘风机", "status": "running"},
    ]
    equip_by_code = {e["code"]: e for e in equipment}
    equip_faults = {
        "EQ-CV-2": {"code": "F-CV-021", "desc": "氧枪漏水待维护", "since": f"{BASE_DATE - timedelta(days=1)}T08:20:00"},
        "EQ-RM-3": {"code": "F-RM-031", "desc": "轧辊磨削待维护", "since": f"{BASE_DATE - timedelta(days=2)}T10:00:00"},
    }

    # 钢种工艺路线（product_code 即 PLM 钢种 P-ST-，与 ERP 钢坯 M-ST- 对齐）
    products = [
        {
            "product_code": "P-ST-Q345B", "name": "Q345B 低合金高强钢", "uom": "吨",
            "routing": [
                {"seq": 10, "name": "铁水预处理", "line": "LINE-IRON", "std_minutes": 30.0},
                {"seq": 20, "name": "转炉冶炼", "line": "LINE-STEEL", "std_minutes": 38.0},
                {"seq": 30, "name": "LF 精炼", "line": "LINE-STEEL", "std_minutes": 35.0},
                {"seq": 40, "name": "连铸", "line": "LINE-STEEL", "std_minutes": 45.0},
                {"seq": 50, "name": "连轧", "line": "LINE-ROLL", "std_minutes": 28.0},
            ],
        },
        {
            "product_code": "P-ST-45#", "name": "45# 优质碳素钢", "uom": "吨",
            "routing": [
                {"seq": 10, "name": "铁水预处理", "line": "LINE-IRON", "std_minutes": 28.0},
                {"seq": 20, "name": "转炉冶炼", "line": "LINE-STEEL", "std_minutes": 36.0},
                {"seq": 30, "name": "LF+RH 精炼", "line": "LINE-STEEL", "std_minutes": 50.0},
                {"seq": 40, "name": "连铸", "line": "LINE-STEEL", "std_minutes": 42.0},
                {"seq": 50, "name": "连轧", "line": "LINE-ROLL", "std_minutes": 26.0},
            ],
        },
        {
            "product_code": "P-ST-40Cr", "name": "40Cr 合金结构钢", "uom": "吨",
            "routing": [
                {"seq": 10, "name": "铁水预处理", "line": "LINE-IRON", "std_minutes": 30.0},
                {"seq": 20, "name": "转炉冶炼", "line": "LINE-STEEL", "std_minutes": 40.0},
                {"seq": 30, "name": "LF 精炼", "line": "LINE-STEEL", "std_minutes": 48.0},
                {"seq": 40, "name": "连铸", "line": "LINE-STEEL", "std_minutes": 44.0},
                {"seq": 50, "name": "连轧", "line": "LINE-ROLL", "std_minutes": 30.0},
            ],
        },
        {
            "product_code": "P-ST-20MnSi", "name": "20MnSi 建筑用钢", "uom": "吨",
            "routing": [
                {"seq": 10, "name": "转炉冶炼", "line": "LINE-STEEL", "std_minutes": 34.0},
                {"seq": 20, "name": "LF 精炼", "line": "LINE-STEEL", "std_minutes": 28.0},
                {"seq": 30, "name": "连铸", "line": "LINE-STEEL", "std_minutes": 38.0},
                {"seq": 40, "name": "连轧", "line": "LINE-ROLL", "std_minutes": 24.0},
            ],
        },
        {
            "product_code": "P-ST-Q235B", "name": "Q235B 普碳钢", "uom": "吨",
            "routing": [
                {"seq": 10, "name": "转炉冶炼", "line": "LINE-STEEL", "std_minutes": 32.0},
                {"seq": 20, "name": "连铸", "line": "LINE-STEEL", "std_minutes": 36.0},
                {"seq": 30, "name": "连轧", "line": "LINE-ROLL", "std_minutes": 22.0},
            ],
        },
        {
            "product_code": "P-ST-42CrMo", "name": "42CrMo 高性能合金钢", "uom": "吨",
            "routing": [
                {"seq": 10, "name": "铁水预处理", "line": "LINE-IRON", "std_minutes": 32.0},
                {"seq": 20, "name": "转炉冶炼", "line": "LINE-STEEL", "std_minutes": 42.0},
                {"seq": 30, "name": "LF+RH 精炼", "line": "LINE-STEEL", "std_minutes": 60.0},
                {"seq": 40, "name": "连铸", "line": "LINE-STEEL", "std_minutes": 46.0},
                {"seq": 50, "name": "特钢连轧", "line": "LINE-SPECIAL", "std_minutes": 38.0},
            ],
        },
    ]
    product_by_code = {p["product_code"]: p for p in products}

    shifts = ["早班", "中班", "晚班"]
    order_status = ["已排产", "进行中", "已完工", "暂停"]
    wo_status = ["待开工", "进行中", "已完工", "暂停"]

    # 生产订单（SPO，由 CRM 销售订单 ASSO 驱动——按单排产）
    crm_sos = _crm_sales_orders("agilesteel")
    po_specs = [
        ("SPO20260701", "P-ST-Q345B", "中建三局·市政桥梁项目", "敏睿钢铁一炼钢厂", 3000, 1800, "进行中", "LINE-STEEL"),
        ("SPO20260702", "P-ST-Q345B", "中交二航局·跨海大桥", "敏睿钢铁一炼钢厂", 5000, 0, "已排产", "LINE-STEEL"),
        ("SPO20260703", "P-ST-20MnSi", "长三角钢贸·建材分销", "敏睿钢铁一炼钢厂", 2000, 2000, "已完工", "LINE-ROLL"),
        ("SPO20260704", "P-ST-45#", "西南钢材市场·优特钢", "敏睿钢铁二炼钢厂", 1500, 900, "进行中", "LINE-ROLL"),
        ("SPO20260705", "P-ST-40Cr", "三一重工·机械用钢", "敏睿钢铁特钢厂", 800, 320, "进行中", "LINE-SPECIAL"),
        ("SPO20260706", "P-ST-42CrMo", "东风汽车·齿轮钢", "敏睿钢铁特钢厂", 600, 0, "已排产", "LINE-SPECIAL"),
    ]
    production_orders: list[dict] = []
    for order_no, pcode, customer, factory, plan, done, status, line in po_specs:
        due = BASE_DATE + timedelta(days=D.randint(R, 5, 30))
        production_orders.append({
            "order_no": order_no,
            "product_code": pcode,
            "product_name": product_by_code[pcode]["name"],
            "plan_qty": plan,
            "done_qty": done,
            "uom": "吨",
            "status": status,
            "line": line,
            "customer": customer,
            "factory": factory,
            "sales_order_no": crm_sos[(hash(order_no) & 0xFFFFFFFF) % len(crm_sos)] if crm_sos else None,
            "planned_start": f"{BASE_DATE - timedelta(days=D.randint(R, 1, 5))}",
            "due_date": f"{due}",
        })
    production_order_by_no = {p["order_no"]: p for p in production_orders}

    # 炉次（HT，钢铁主实体）：每炉次一炉钢，回挂钢种 + 配料废钢 + 设备
    heat_specs = [
        # (heat_no, steel_grade, converter, plan_t, done_t, status, scrap, off)
        ("HT2026062901", "P-ST-Q345B", "EQ-CV-1", 120, 120, "已完工", "M-SCR-HMS1", -1),
        ("HT2026062902", "P-ST-45#", "EQ-CV-1", 120, 120, "已完工", "M-SCR-HMS2", -1),
        ("HT2026062903", "P-ST-40Cr", "EQ-CV-1", 110, 110, "已完工", "M-SCR-HMS1", 0),
        ("HT2026063001", "P-ST-Q345B", "EQ-CV-1", 120, 95, "进行中", "M-SCR-HMS1", 0),
        ("HT2026063002", "P-ST-45#", "EQ-CV-2", 120, 0, "待吹炼", "M-SCR-HMS2", 0),
    ]
    heats: list[dict] = []
    for heat_no, grade, converter, plan_t, done_t, status, scrap, off in heat_specs:
        heats.append({
            "heat_no": heat_no,
            "steel_grade": grade,
            "converter_code": converter,
            "plan_tonnage": plan_t,
            "actual_tonnage": done_t,
            "charging_scrap": scrap,
            "status": status,
            "shift": D.pick(R, shifts),
            "operator": f"OP{D.pad(D.randint(R, 1, 40))}",
            "started_at": f"{BASE_DATE + timedelta(days=off)}T08:00:00" if status != "待吹炼" else None,
            "endpoint_carbon_target": 0.18 if "Q345B" in grade else (0.42 if "45#" in grade else 0.40),
            "endpoint_carbon_actual": 0.17 if status == "已完工" and "Q345B" in grade
            else (0.41 if status == "已完工" and "45#" in grade
                  else (0.40 if status == "已完工" else None)),
            "endpoint_temp_target": 1660,
            "endpoint_temp_actual": 1658 if status == "已完工" else None,
            "phosphorus_target": 0.025,
            "phosphorus_actual": 0.020 if status == "已完工" else None,
            "hit_carbon_temp": status == "已完工",
            "linked_production_order": f"SPO2026070{1 + (hash(heat_no) & 3)}",
        })
    heat_by_no = {h["heat_no"]: h for h in heats}

    # 工单（SWO，钢铁工单）
    wo_specs = [
        ("SWO202607001", "SPO20260701", "P-ST-Q345B", "LINE-ROLL", 3000, 1800, "进行中", -2),
        ("SWO202607002", "SPO20260702", "P-ST-Q345B", "LINE-ROLL", 5000, 0, "待开工", 2),
        ("SWO202607003", "SPO20260703", "P-ST-20MnSi", "LINE-ROLL", 2000, 2000, "已完工", -5),
        ("SWO202607004", "SPO20260704", "P-ST-45#", "LINE-ROLL", 1500, 900, "进行中", -3),
        ("SWO202607005", "SPO20260705", "P-ST-40Cr", "LINE-SPECIAL", 800, 320, "进行中", -4),
        ("SWO202607006", "SPO20260706", "P-ST-42CrMo", "LINE-SPECIAL", 600, 0, "待开工", 3),
        ("SWO202607007", "SPO20260701", "P-ST-Q345B", "LINE-STEEL", 1200, 1200, "已完工", -6),
        ("SWO202607008", "SPO20260704", "P-ST-45#", "LINE-STEEL", 1000, 600, "进行中", -1),
    ]
    work_orders: list[dict] = []
    for won, order_no, pcode, line, plan, done, status, off_start in wo_specs:
        product = product_by_code[pcode]
        work_orders.append({
            "work_order_no": won,
            "order_no": order_no,
            "sales_order_no": production_order_by_no[order_no]["sales_order_no"],
            "product_code": pcode,
            "product_name": product["name"],
            "line": line,
            "plan_qty": plan,
            "done_qty": done,
            "defect_qty": D.randint(R, 0, max(1, done // 30)) if done > 0 else 0,
            "uom": "吨",
            "status": status,
            "shift": D.pick(R, shifts),
            "planned_start": f"{BASE_DATE + timedelta(days=off_start)}T08:00:00",
            "planned_end": f"{BASE_DATE + timedelta(days=off_start + 2)}T17:00:00",
            "actual_start": f"{BASE_DATE + timedelta(days=off_start)}T08:30:00" if done > 0 else None,
            "operator": f"OP{D.pad(D.randint(R, 1, 60))}",
        })
    work_order_by_no = {w["work_order_no"]: w for w in work_orders}

    # 报工
    work_reports: list[dict] = []
    for i in range(18):
        wo = D.pick(R, work_orders)
        routing = product_by_code[wo["product_code"]]["routing"]
        op = D.pick(R, routing)
        plan = D.randint(R, 50, 400)
        accepted = D.randint(R, int(plan * 0.7), plan) if plan > 0 else 0
        work_reports.append({
            "report_id": f"ASWR{D.pad(20260600 + i * 37)}",
            "work_order_no": wo["work_order_no"],
            "product_code": wo["product_code"],
            "line": wo["line"],
            "operation_seq": op["seq"],
            "operation_name": op["name"],
            "plan_qty": plan,
            "reported_qty": accepted,
            "defect_qty": D.randint(R, 0, max(1, accepted // 15)),
            "operator": wo["operator"],
            "shift": D.pick(R, shifts),
            "reported_at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 7))}T{D.pad(D.randint(R, 8, 20), 2)}:30:00",
        })

    # 钢材表面缺陷（DF，回流 PLM 钢种质量历史 DF-AS-）
    defect_specs = [
        # (defect_id, won, product_code, line, defect_code, severity, qty, op_name, off)
        ("DF20260701", "SWO202607001", "P-ST-Q345B", "LINE-ROLL", "D-CRACK", "严重", 5, "连轧", -2),
        ("DF20260702", "SWO202607004", "P-ST-45#", "LINE-ROLL", "D-SCRATCH", "一般", 8, "连轧", -3),
        ("DF20260703", "SWO202607005", "P-ST-40Cr", "LINE-SPECIAL", "D-INCL", "严重", 3, "特钢连轧", -4),
        ("DF20260704", "SWO202607001", "P-ST-Q345B", "LINE-STEEL", "D-SEG", "一般", 4, "连铸", -1),
        ("DF20260705", "SWO202607003", "P-ST-20MnSi", "LINE-ROLL", "D-DIM", "一般", 6, "连轧", -5),
        ("DF20260706", "SWO202607002", "P-ST-Q345B", "LINE-ROLL", "D-SCALE", "一般", 10, "连轧", 0),
        ("DF20260707", "SWO202607006", "P-ST-42CrMo", "LINE-SPECIAL", "D-LAP", "严重", 2, "特钢连轧", 0),
        ("DF20260708", "SWO202607007", "P-ST-Q345B", "LINE-STEEL", "D-MECH", "严重", 3, "连铸", -6),
        ("DF20260709", "SWO202607008", "P-ST-45#", "LINE-STEEL", "D-INCL", "一般", 4, "连铸", -1),
        ("DF20260710", "SWO202607005", "P-ST-40Cr", "LINE-SPECIAL", "D-MECH", "严重", 2, "特钢连轧", -2),
    ]
    defects: list[dict] = []
    for did, won, pcode, line, dcode, sev, qty, op_name, off in defect_specs:
        dt = next(d for d in _AGILESTEEL_DEFECT_TYPES if d["code"] == dcode)
        defects.append({
            "defect_id": did,
            "work_order_no": won,
            "product_code": pcode,
            "line": line,
            "defect_code": dt["code"],
            "defect_name": dt["name"],
            "defect_type": dt["name"],
            "severity": sev,
            "qty": qty,
            "operation": op_name,
            "found_at": f"{BASE_DATE + timedelta(days=off)}T{D.pad(D.randint(R, 8, 20), 2)}:30:00",
            "root_cause": dt["cause"],
            "status": D.pick(R, ["待处理", "已返工", "已让步"]),
        })

    # 班次产量
    shift_outputs: list[dict] = []
    date_pool = [BASE_DATE + timedelta(days=d_off) for d_off in range(-2, 2)]
    combos = [(d, l, s) for d in date_pool for l in lines for s in shifts]
    for d, l, sh in D.sample(R, combos, 16):
        plan = D.randint(R, 300, 1500)
        actual = D.randint(R, int(plan * 0.6), plan)
        shift_outputs.append({
            "date": f"{d}",
            "line": l["code"],
            "shift": sh,
            "plan_qty": plan,
            "actual_qty": actual,
            "defect_qty": D.randint(R, 0, max(1, actual // 30)),
            "yield_rate": round(actual / plan, 4) if plan else 0.0,
        })

    # 在制品
    wip: list[dict] = []
    for wo in D.sample(R, [w for w in work_orders if w["status"] == "进行中"],
                        min(5, len([w for w in work_orders if w["status"] == "进行中"]) or 1)):
        routing = product_by_code[wo["product_code"]]["routing"]
        st = D.pick(R, routing)
        wip.append({
            "work_order_no": wo["work_order_no"],
            "product_code": wo["product_code"],
            "line": wo["line"],
            "current_seq": st["seq"],
            "current_station": st["name"],
            "in_process_qty": D.randint(R, 50, max(60, wo["plan_qty"] // 4)),
            "hold": wo["status"] == "暂停",
        })

    return MesData(
        lines=lines, line_by_code=line_by_code,
        equipment=equipment, equip_by_code=equip_by_code, equip_faults=equip_faults,
        products=products, product_by_code=product_by_code,
        production_orders=production_orders, production_order_by_no=production_order_by_no,
        work_orders=work_orders, work_order_by_no=work_order_by_no,
        work_reports=work_reports, defects=defects,
        shift_outputs=shift_outputs, wip=wip,
        heats=heats, heat_by_no=heat_by_no,
    )


def _build_starhma() -> MesData:
    """星途热熔胶 MES 口径：13 条产线（2 全自动 LINE-AUTO-01/02 + 半自动 LINE-03/04）+
    反应釜/电机/造粒机设备（EQ- 与 PCM 共享码空间，line 关联产线）+ 热熔胶工艺路线
    （投料/搅拌/反应/冷却/造粒/包装）+ 生产订单（SPOHMA，由 CRM 合同 CT-HMA- 驱动）+
    工单（WO，batch_no 承载批次 BAT-2026-0701..0704，formula_no 回挂 FRM 配方 FORM-）+
    报工/不良/班次产量/在制。工单 work_order_no 被 ERP 生产成本与 PCM 排产引用，形成联动。"""
    R = D.rng(20260725)
    TODAY = date(2026, 7, 25)

    lines = [
        {"code": "LINE-AUTO-01", "name": "1# 全自动产线", "workshop": "一车间", "product_type": "全自动热熔胶产线"},
        {"code": "LINE-AUTO-02", "name": "2# 全自动产线", "workshop": "一车间", "product_type": "全自动热熔胶产线"},
        {"code": "LINE-03", "name": "3# 半自动产线", "workshop": "二车间", "product_type": "半自动热熔胶产线"},
        {"code": "LINE-04", "name": "4# 半自动产线", "workshop": "二车间", "product_type": "半自动热熔胶产线"},
    ]
    line_by_code = {l["code"]: l for l in lines}

    # 设备（EQ- 与 PCM 共享码空间，line 关联产线）
    equipment = [
        {"code": "EQ-RX-01", "name": "1# 反应釜", "line": "LINE-AUTO-01", "type": "反应釜", "status": "running"},
        {"code": "EQ-RX-02", "name": "2# 反应釜", "line": "LINE-AUTO-02", "type": "反应釜", "status": "warning"},
        {"code": "EQ-RX-03", "name": "3# 反应釜", "line": "LINE-03", "type": "反应釜", "status": "running"},
        {"code": "EQ-MTR-01", "name": "1# 搅拌电机", "line": "LINE-AUTO-01", "type": "电机", "status": "running"},
        {"code": "EQ-MTR-02", "name": "2# 搅拌电机", "line": "LINE-AUTO-02", "type": "电机", "status": "warning"},
        {"code": "EQ-GRN-01", "name": "1# 造粒机", "line": "LINE-AUTO-01", "type": "造粒机", "status": "running"},
        {"code": "EQ-GRN-02", "name": "2# 造粒机", "line": "LINE-AUTO-02", "type": "造粒机", "status": "running"},
    ]
    equip_by_code = {e["code"]: e for e in equipment}
    equip_faults = {
        "EQ-RX-02": {"code": "F-RX-021", "desc": "振动预警待保养", "since": f"{TODAY - timedelta(days=2)}T08:20:00"},
        "EQ-MTR-02": {"code": "F-MTR-022", "desc": "温升/振动预警待保养", "since": f"{TODAY - timedelta(days=1)}T10:00:00"},
    }

    # 工艺路线（product_code 即 ERP 成品胶 M-FG- / FRM 配方 FORM-CUS-）
    products = [
        {"product_code": "M-FG-001", "name": "环保型书刊装订热熔胶", "uom": "kg", "formula_no": "FORM-STD-001",
         "routing": [
             {"seq": 10, "name": "投料预混", "line": "LINE-AUTO-01", "std_minutes": 15.0},
             {"seq": 20, "name": "搅拌熔融", "line": "LINE-AUTO-01", "std_minutes": 20.0},
             {"seq": 30, "name": "反应", "line": "LINE-AUTO-01", "std_minutes": 90.0},
             {"seq": 40, "name": "冷却", "line": "LINE-AUTO-01", "std_minutes": 25.0},
             {"seq": 50, "name": "造粒包装", "line": "LINE-AUTO-01", "std_minutes": 18.0},
         ]},
        {"product_code": "M-FG-002", "name": "物流快递袋压敏胶", "uom": "kg", "formula_no": "FORM-STD-002",
         "routing": [
             {"seq": 10, "name": "投料预混", "line": "LINE-AUTO-02", "std_minutes": 15.0},
             {"seq": 20, "name": "搅拌熔融", "line": "LINE-AUTO-02", "std_minutes": 22.0},
             {"seq": 30, "name": "反应", "line": "LINE-AUTO-02", "std_minutes": 100.0},
             {"seq": 40, "name": "冷却", "line": "LINE-AUTO-02", "std_minutes": 25.0},
             {"seq": 50, "name": "造粒包装", "line": "LINE-AUTO-02", "std_minutes": 18.0},
         ]},
        {"product_code": "M-FG-003", "name": "食品日化包装用热熔胶", "uom": "kg", "formula_no": "FORM-STD-003",
         "routing": [
             {"seq": 10, "name": "投料预混", "line": "LINE-AUTO-02", "std_minutes": 15.0},
             {"seq": 20, "name": "搅拌熔融", "line": "LINE-AUTO-02", "std_minutes": 18.0},
             {"seq": 30, "name": "反应", "line": "LINE-AUTO-02", "std_minutes": 80.0},
             {"seq": 40, "name": "冷却", "line": "LINE-AUTO-02", "std_minutes": 25.0},
             {"seq": 50, "name": "造粒包装", "line": "LINE-AUTO-02", "std_minutes": 18.0},
         ]},
        {"product_code": "FORM-CUS-001", "name": "汽车内饰植绒用压敏胶", "uom": "kg", "formula_no": "FORM-CUS-001",
         "routing": [
             {"seq": 10, "name": "投料预混", "line": "LINE-03", "std_minutes": 18.0},
             {"seq": 20, "name": "搅拌熔融", "line": "LINE-03", "std_minutes": 22.0},
             {"seq": 30, "name": "反应", "line": "LINE-03", "std_minutes": 95.0},
             {"seq": 40, "name": "冷却", "line": "LINE-03", "std_minutes": 28.0},
             {"seq": 50, "name": "造粒包装", "line": "LINE-03", "std_minutes": 20.0},
         ]},
    ]
    product_by_code = {p["product_code"]: p for p in products}

    shifts = ["早班", "中班", "晚班"]

    # 生产订单（SPOHMA，由 CRM 合同 CT-HMA- 驱动）
    crm_sos = _crm_sales_orders("starhma")
    po_specs = [
        ("SPOHMA20260701", "M-FG-001", "书刊装订胶·国内订单", "一车间", 8000, 5200, "进行中", "LINE-AUTO-01",
         crm_sos[0] if crm_sos else "CT-HMA-001"),
        ("SPOHMA20260702", "M-FG-002", "快递袋胶·旺季订单", "一车间", 12000, 6000, "进行中", "LINE-AUTO-02",
         crm_sos[2] if len(crm_sos) > 2 else "CT-HMA-003"),
        ("SPOHMA20260703", "FORM-CUS-001", "汽车内饰胶·定制订单", "二车间", 3000, 1800, "进行中", "LINE-03",
         crm_sos[0] if crm_sos else "CT-HMA-001"),
        ("SPOHMA20260704", "M-FG-003", "食品包装胶·外贸订单", "一车间", 4000, 0, "待开工", "LINE-AUTO-02",
         crm_sos[1] if len(crm_sos) > 1 else "CT-HMA-002"),
    ]
    production_orders: list[dict] = []
    production_order_by_no: dict[str, dict] = {}
    for po_no, pcode, desc, ws, plan, done, status, line, so in po_specs:
        product = product_by_code[pcode]
        production_orders.append({
            "order_no": po_no, "sales_order_no": so,
            "product_code": pcode, "product_name": product["name"],
            "workshop": ws, "plan_qty": plan, "uom": "kg",
            "status": status, "line": line,
            "order_date": f"{TODAY - timedelta(days=D.randint(R, 6, 20))}",
            "due_date": f"{TODAY + timedelta(days=D.randint(R, 5, 30))}",
        })
        production_order_by_no[po_no] = production_orders[-1]

    # 工单（WO，batch_no 承载批次 BAT-2026-0701..0704，formula_no 回挂 FRM 配方）
    wo_specs = [
        ("WO202607001", "SPOHMA20260701", "M-FG-001", "LINE-AUTO-01", 8000, 5200, "进行中", -2, "BAT-2026-0701", "FORM-STD-001"),
        ("WO202607002", "SPOHMA20260702", "M-FG-002", "LINE-AUTO-02", 12000, 6000, "进行中", -1, "BAT-2026-0702", "FORM-STD-002"),
        ("WO202607003", "SPOHMA20260703", "FORM-CUS-001", "LINE-03", 3000, 1800, "进行中", -1, "BAT-2026-0703", "FORM-CUS-001"),
        ("WO202607004", "SPOHMA20260704", "M-FG-003", "LINE-AUTO-02", 4000, 0, "待开工", 2, "BAT-2026-0704", "FORM-STD-003"),
        ("WO202607005", "SPOHMA20260701", "M-FG-001", "LINE-AUTO-01", 2000, 2000, "已完工", -6, "BAT-2026-0699", "FORM-STD-001"),
    ]
    work_orders: list[dict] = []
    for won, order_no, pcode, line, plan, done, status, off_start, batch, formula in wo_specs:
        product = product_by_code[pcode]
        work_orders.append({
            "work_order_no": won,
            "order_no": order_no,
            "sales_order_no": production_order_by_no[order_no]["sales_order_no"],
            "product_code": pcode,
            "product_name": product["name"],
            "line": line,
            "batch_no": batch,
            "formula_no": formula,
            "plan_qty": plan,
            "done_qty": done,
            "defect_qty": D.randint(R, 0, max(1, done // 40)) if done > 0 else 0,
            "uom": "kg",
            "status": status,
            "shift": D.pick(R, shifts),
            "planned_start": f"{TODAY + timedelta(days=off_start)}T08:00:00",
            "planned_end": f"{TODAY + timedelta(days=off_start + 1)}T17:00:00",
            "actual_start": f"{TODAY + timedelta(days=off_start)}T08:30:00" if done > 0 else None,
            "operator": f"OP{D.pad(D.randint(R, 1, 40))}",
        })
    work_order_by_no = {w["work_order_no"]: w for w in work_orders}

    # 报工
    work_reports: list[dict] = []
    for i in range(14):
        wo = D.pick(R, work_orders)
        routing = product_by_code[wo["product_code"]]["routing"]
        op = D.pick(R, routing)
        plan = D.randint(R, 200, 1500)
        accepted = D.randint(R, int(plan * 0.7), plan) if plan > 0 else 0
        work_reports.append({
            "report_id": f"HMAWR{D.pad(20260700 + i * 37)}",
            "work_order_no": wo["work_order_no"],
            "product_code": wo["product_code"],
            "line": wo["line"],
            "operation_seq": op["seq"],
            "operation_name": op["name"],
            "plan_qty": plan,
            "reported_qty": accepted,
            "defect_qty": D.randint(R, 0, max(1, accepted // 20)),
            "operator": wo["operator"],
            "shift": D.pick(R, shifts),
            "reported_at": f"{TODAY - timedelta(days=D.randint(R, 0, 6))}T{D.pad(D.randint(R, 8, 20), 2)}:30:00",
        })

    # 不良（DF，关联工单/批次；QAS NG- 回挂同批次）
    defect_specs = [
        ("DF20260701", "WO202607002", "M-FG-002", "LINE-AUTO-02", "软化点偏低", "严重", 320, "反应", -1, "BAT-2026-0702"),
        ("DF20260702", "WO202607003", "FORM-CUS-001", "LINE-03", "高温剥离衰减", "严重", 80, "反应", -5, "BAT-2026-0703"),
        ("DF20260703", "WO202607001", "M-FG-001", "LINE-AUTO-01", "色差", "一般", 45, "造粒", -2, "BAT-2026-0701"),
        ("DF20260704", "WO202607002", "M-FG-002", "LINE-AUTO-02", "粘度偏高", "一般", 60, "反应", -1, "BAT-2026-0702"),
    ]
    defects: list[dict] = []
    for did, won, pcode, line, dname, sev, qty, op_name, off, batch in defect_specs:
        defects.append({
            "defect_id": did,
            "work_order_no": won,
            "product_code": pcode,
            "line": line,
            "defect_code": dname,
            "defect_name": dname,
            "defect_type": dname,
            "severity": sev,
            "qty": qty,
            "operation": op_name,
            "found_at": f"{TODAY + timedelta(days=off)}T{D.pad(D.randint(R, 8, 20), 2)}:30:00",
            "root_cause": "工艺参数漂移/设备振动",
            "status": D.pick(R, ["待处理", "已返工", "已让步"]),
        })

    # 班次产量
    shift_outputs: list[dict] = []
    date_pool = [TODAY + timedelta(days=d_off) for d_off in range(-2, 2)]
    combos = [(d, l, s) for d in date_pool for l in lines for s in shifts]
    for d, l, sh in D.sample(R, combos, 16):
        plan = D.randint(R, 2000, 8000)
        actual = D.randint(R, int(plan * 0.6), plan)
        shift_outputs.append({
            "date": f"{d}",
            "line": l["code"],
            "shift": sh,
            "plan_qty": plan,
            "actual_qty": actual,
            "defect_qty": D.randint(R, 0, max(1, actual // 40)),
            "yield_rate": round(actual / plan, 4) if plan else 0.0,
        })

    # 在制品
    wip: list[dict] = []
    for wo in [w for w in work_orders if w["status"] == "进行中"][:3]:
        routing = product_by_code[wo["product_code"]]["routing"]
        st = D.pick(R, routing)
        wip.append({
            "work_order_no": wo["work_order_no"],
            "product_code": wo["product_code"],
            "line": wo["line"],
            "current_seq": st["seq"],
            "current_station": st["name"],
            "in_process_qty": D.randint(R, 200, max(300, wo["plan_qty"] // 4)),
            "hold": wo["status"] == "暂停",
        })

    heats: list[dict] = []
    heat_by_no: dict[str, dict] = {}

    return MesData(
        lines=lines, line_by_code=line_by_code,
        equipment=equipment, equip_by_code=equip_by_code, equip_faults=equip_faults,
        products=products, product_by_code=product_by_code,
        production_orders=production_orders, production_order_by_no=production_order_by_no,
        work_orders=work_orders, work_order_by_no=work_order_by_no,
        work_reports=work_reports, defects=defects,
        shift_outputs=shift_outputs, wip=wip,
        heats=heats, heat_by_no=heat_by_no,
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[MesData]({
    "minrui": _build_minrui,
    "starclothing": _build_starclothing,
    "agileac": _build_agileac,
    "agilesteel": _build_agilesteel,
    "starhma": _build_starhma,
})


def load(tenant: str) -> MesData:
    """按 tenant 取数据集；首次调用时触发构建并缓存。"""
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量（按 tenant 派生，确定性） ───────────────────────────


def work_order_progress(tenant: str, won: str) -> list[dict]:
    """工单工序进度（确定性派生）：末道工序承袭工单状态，前序视为完工。"""
    d = load(tenant)
    wo = d.work_order_by_no.get(won)
    if wo is None:
        return []
    seqs = d.product_by_code[wo["product_code"]]["routing"]
    pg = []
    cum = wo["done_qty"]
    for idx, st in enumerate(seqs):
        rep = max(0, min(cum, wo["plan_qty"]))
        pg.append({
            "seq": st["seq"],
            "name": st["name"],
            "line": st["line"],
            "std_minutes": st["std_minutes"],
            "reported_qty": rep,
            "status": "完工" if idx < len(seqs) - 1 else wo["status"],
        })
    return pg


def equipment_runtime(tenant: str, code: str) -> dict:
    """单台设备实时参数（按 code 确定性派生）。"""
    d = load(tenant)
    eq = d.equip_by_code.get(code)
    if eq is None:
        return {}
    r = D.rng(hash(code) & 0xFFFFFFFF)
    return {
        "code": code,
        "name": eq["name"],
        "line": eq["line"],
        "type": eq["type"],
        "status": eq["status"],
        "temperature_c": D.randfloat(r, 28.0, 62.0),
        "vibration_mm_s": D.randfloat(r, 0.4, 4.5),
        "power_kw": D.randfloat(r, 1.2, 18.0),
        "utilization": D.randfloat(r, 0.55, 0.95) if eq["status"] == "running" else 0.0,
        "fault": d.equip_faults.get(code),
    }


def oee(tenant: str, line: str, day: date) -> dict:
    """OEE = 可用率 × 性能率 × 质量率（按 (line, day) 确定性派生）。"""
    r = D.rng(hash((line, day.isoformat())) & 0xFFFFFFFF)
    availability = D.randfloat(r, 0.78, 0.98)
    performance = D.randfloat(r, 0.80, 0.99)
    quality = D.randfloat(r, 0.90, 0.999)
    return {
        "line": line,
        "date": day.isoformat(),
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": round(availability * performance * quality, 4),
    }


def all_work_order_nos(tenant: str = "minrui") -> list[str]:
    """供 CRM 客诉跨系统联动引用工单号；默认 minrui（CRM 尚未多租户化）。"""
    try:
        return [w["work_order_no"] for w in load(tenant).work_orders]
    except KeyError:
        return []


# ── 向后兼容：模块级别名（默认 minrui，供跨系统延迟导入与未改造调用方） ──
_minrui = TENANTS["minrui"]
LINES = _minrui.lines
LINE_BY_CODE = _minrui.line_by_code
EQUIPMENT = _minrui.equipment
EQUIP_BY_CODE = _minrui.equip_by_code
EQUIP_FAULTS = _minrui.equip_faults
PRODUCTS = _minrui.products
PRODUCT_BY_CODE = _minrui.product_by_code
PRODUCTION_ORDERS = _minrui.production_orders
PRODUCTION_ORDER_BY_NO = _minrui.production_order_by_no
WORK_ORDERS = _minrui.work_orders
WO_BY_NO = _minrui.work_order_by_no
WORK_REPORTS = _minrui.work_reports
DEFECTS = _minrui.defects
SHIFT_OUTPUTS = _minrui.shift_outputs
WIP = _minrui.wip
