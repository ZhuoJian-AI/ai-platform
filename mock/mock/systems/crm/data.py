"""CRM 多租户确定性种子数据——minrui（工业销售）+ starclothing（服装销售）。

固定种子 + 固定基准日，重启可复现。每个 tenant 一份 ``CrmData``，覆盖客户 /
联系人 / 商机 / 报价 / 销售订单 / 跟进 / 客诉(8D) / 应收对账。客诉
``work_order_no`` 引用同 tenant 的 MES 工单号，形成跨系统联动。

多租户访问：``load(tenant) -> CrmData``。模块级别名（``CUSTOMERS`` 等）默认指向
minrui，向后兼容未改造的调用方与跨系统延迟导入。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry, TenantBuilding

BASE_DATE: date = date(2026, 6, 29)


# ───────────────────────── 多租户数据容器 ─────────────────────────


@dataclass
class CrmData:
    customers: list[dict]
    customer_by_code: dict[str, dict]
    contacts: list[dict]
    opportunities: list[dict]
    opportunity_by_no: dict[str, dict]
    quotations: list[dict]
    quotation_by_no: dict[str, dict]
    sales_orders: list[dict]
    follow_ups: list[dict]
    complaints: list[dict]
    complaint_by_no: dict[str, dict]
    receivables: list[dict]


# ───────────────────────── 跨系统取数（同 tenant） ─────────────────────────


def _mes_work_orders(tenant: str) -> list[str]:
    """跨系统取同 tenant 的 MES 工单号；MES 未就绪或循环构造中时回退占位。"""
    try:
        from mock.systems.mes.data import load as _load_mes
        d = _load_mes(tenant)
        return [w["work_order_no"] for w in d.work_orders]
    except (Exception, TenantBuilding):  # noqa: BLE001
        return ["WO20260001", "WO20260033", "WO20260067"]


# ───────────────────────── minrui（工业销售） ─────────────────────────


def _build_minrui() -> CrmData:
    """敏睿制造工业销售口径：OEM/ODM/经销商/终端/外贸客户与电机/驱动/传感器产品。"""
    R = D.rng(20240715)

    customers = [
        {"code": "C-OEM-001", "name": "苏州汇川技术有限公司", "type": "OEM", "industry": "工业自动化",
         "region": "华东", "credit_grade": "A", "payment_terms_days": 60, "currency": "CNY",
         "owner": "张磊", "address": "江苏省苏州市工业园区"},
        {"code": "C-OEM-002", "name": "深圳雷赛智能装备", "type": "OEM", "industry": "运动控制",
         "region": "华南", "credit_grade": "A", "payment_terms_days": 45, "currency": "CNY",
         "owner": "林芳", "address": "广东省深圳市宝安区"},
        {"code": "C-ODM-010", "name": "东莞立讯精密", "type": "ODM", "industry": "消费电子代工",
         "region": "华南", "credit_grade": "B", "payment_terms_days": 30, "currency": "CNY",
         "owner": "林芳", "address": "广东省东莞市"},
        {"code": "C-DIST-021", "name": "上海德马泰克经销", "type": "经销商", "industry": "物流装备",
         "region": "华东", "credit_grade": "B", "payment_terms_days": 30, "currency": "CNY",
         "owner": "张磊", "address": "上海市闵行区"},
        {"code": "C-END-033", "name": "三一重工股份有限公司", "type": "终端", "industry": "工程机械",
         "region": "华中", "credit_grade": "A", "payment_terms_days": 90, "currency": "CNY",
         "owner": "王伟", "address": "湖南省长沙市"},
        {"code": "C-END-044", "name": "宁德时代新能源", "type": "终端", "industry": "动力电池",
         "region": "华东", "credit_grade": "A", "payment_terms_days": 90, "currency": "CNY",
         "owner": "王伟", "address": "福建省宁德市"},
        {"code": "C-FRG-051", "name": "Siemens Digital Ind.", "type": "外贸", "industry": "工业自动化",
         "region": "海外-欧洲", "credit_grade": "A", "payment_terms_days": 30, "currency": "EUR",
         "owner": "Chen Yu", "address": "Erlangen, Germany"},
        {"code": "C-FRG-052", "name": "Bosch Rexroth APAC", "type": "外贸", "industry": "液压传动",
         "region": "海外-亚太", "credit_grade": "A", "payment_terms_days": 45, "currency": "USD",
         "owner": "Chen Yu", "address": "Singapore"},
    ]
    customer_by_code = {c["code"]: c for c in customers}

    contacts: list[dict] = []
    for c in customers:
        n = D.randint(R, 1, 3)
        for i in range(n):
            contacts.append({
                "contact_id": f"CT{D.pad(D.randint(R, 1000, 9999))}",
                "customer_code": c["code"],
                "name": D.pick(R, ["李明", "赵敏", "孙浩", "周婷", "吴峰", "郑洁", "黄强", "刘洋"]),
                "title": D.pick(R, ["采购经理", "技术总监", "采购专员", "研发主管", "供应链总监"]),
                "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
                "email": f"contact{i}@{c['code'].lower()}.example",
                "decision_role": D.pick(R, ["决策者", "影响者", "使用者", "把关者"]),
            })

    product_codes = ["P-MOTOR-100", "P-DRIVE-200", "P-SENSOR-50"]
    stages = ["线索", "打样", "报价", "送样", "NPI", "成交", "流失"]

    opportunities: list[dict] = []
    quotations: list[dict] = []
    for i in range(12):
        cust = D.pick(R, customers)
        product = D.pick(R, product_codes)
        stage = D.pick(R, stages)
        amount = D.randint(R, 50_000, 1_200_000)
        oid = f"OPP{D.pad(20260000 + i * 79 + 3)}"
        opportunities.append({
            "opportunity_id": oid,
            "customer_code": cust["code"],
            "customer_name": cust["name"],
            "product_code": product,
            "stage": stage,
            "amount": amount,
            "currency": cust["currency"],
            "owner": cust["owner"],
            "source": D.pick(R, ["展会", "官网询盘", "老客户复购", "销售拓展", "外贸平台"]),
            "expected_close": f"{BASE_DATE + timedelta(days=D.randint(R, 10, 90))}",
        })
        qid = f"QT{D.pad(20260000 + i * 61 + 9)}"
        tiers = [
            {"min_qty": 1, "unit_price": D.randint(R, 120, 800)},
            {"min_qty": 100, "unit_price": D.randint(R, 100, 700)},
            {"min_qty": 1000, "unit_price": D.randint(R, 85, 600)},
        ]
        quotations.append({
            "quotation_id": qid,
            "opportunity_id": oid,
            "customer_code": cust["code"],
            "product_code": product,
            "customer_part_no": f"{cust['code'][-3:]}-{product[-3:]}",
            "currency": cust["currency"],
            "tiers": tiers,
            "mold_fee": D.pick(R, [0, 8000, 15000, 30000]),
            "sample_fee": D.pick(R, [0, 500, 1200]),
            "valid_until": f"{BASE_DATE + timedelta(days=30)}",
            "status": D.pick(R, ["草稿", "待审", "已发", "已接受", "已拒绝"]),
        })

    opportunity_by_no = {o["opportunity_id"]: o for o in opportunities}
    quotation_by_no = {q["quotation_id"]: q for q in quotations}

    sales_orders: list[dict] = []
    for i in range(6):
        q = D.pick(R, quotations)
        cust = customer_by_code[q["customer_code"]]
        qty = D.randint(R, 100, 2000)
        sales_orders.append({
            "so_no": f"SO{D.pad(20260000 + i * 47 + 5)}",
            "customer_code": q["customer_code"],
            "product_code": q["product_code"],
            "qty": qty,
            "unit_price": q["tiers"][0]["unit_price"],
            "currency": cust["currency"],
            "status": D.pick(R, ["已确认", "排产中", "部分发货", "已发货", "已结案"]),
            "delivery_date": f"{BASE_DATE + timedelta(days=D.randint(R, 5, 40))}",
        })

    follow_ups: list[dict] = []
    for i in range(10):
        cust = D.pick(R, customers)
        follow_ups.append({
            "followup_id": f"FU{D.pad(20260000 + i * 31)}",
            "customer_code": cust["code"],
            "opportunity_id": D.pick(R, opportunities)["opportunity_id"],
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 12))}T{D.pad(D.randint(R, 9, 18))}:00:00",
            "method": D.pick(R, ["电话", "拜访", "邮件", "微信"]),
            "owner": cust["owner"],
            "content": D.pick(R, [
                "确认打样进度，客户对尺寸公差有疑问",
                "发送最新阶梯报价，等待采购回复",
                "现场拜访，演示样品并讨论 NPI 导入",
                "客户要求提供 8D 报告，已转质量部",
                "对账确认上月发货明细，无异议",
            ]),
            "next_action": D.pick(R, ["寄送样品", "更新报价", "安排验厂", "提供测试报告", "跟进回款"]),
        })

    _wo_pool = _mes_work_orders("minrui")
    complaints: list[dict] = []
    for i in range(6):
        cust = D.pick(R, customers)
        product = D.pick(R, product_codes)
        won = D.pick(R, _wo_pool)
        complaints.append({
            "complaint_id": f"CP{D.pad(20260000 + i * 23)}",
            "customer_code": cust["code"],
            "customer_name": cust["name"],
            "product_code": product,
            "batch_no": f"B{D.pad(D.randint(R, 20250000, 20260000))}",
            "work_order_no": won,  # ← 跨系统联动点
            "defect": D.pick(R, ["运行异响", "绝缘不合格", "外观划伤", "装配松动", "标定漂移"]),
            "severity": D.pick(R, ["一般", "严重", "致命"]),
            "status": D.pick(R, ["已受理", "分析中", "8D 进行中", "已闭环"]),
            "reported_at": f"{BASE_DATE - timedelta(days=D.randint(R, 1, 20))}",
            "owner": D.pick(R, ["质量部-周", "质量部-吴", "客服-陈"]),
        })
    complaint_by_no = {c["complaint_id"]: c for c in complaints}

    receivables: list[dict] = []
    for i in range(8):
        cust = D.pick(R, customers)
        inv_amount = D.randint(R, 30_000, 600_000)
        due_date = BASE_DATE + timedelta(days=D.randint(R, -25, 40))
        overdue = (BASE_DATE - due_date).days > 0
        receivables.append({
            "receivable_id": f"AR{D.pad(20260000 + i * 17)}",
            "customer_code": cust["code"],
            "customer_name": cust["name"],
            "invoice_no": f"INV{D.pad(D.randint(R, 20260000, 20269999))}",
            "amount": inv_amount,
            "currency": cust["currency"],
            "billing_date": f"{BASE_DATE - timedelta(days=D.randint(R, 30, 80))}",
            "due_date": f"{due_date}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已收款"]),
            "days_overdue": max(0, (BASE_DATE - due_date).days),
        })

    return CrmData(
        customers=customers, customer_by_code=customer_by_code,
        contacts=contacts,
        opportunities=opportunities, opportunity_by_no=opportunity_by_no,
        quotations=quotations, quotation_by_no=quotation_by_no,
        sales_orders=sales_orders, follow_ups=follow_ups,
        complaints=complaints, complaint_by_no=complaint_by_no,
        receivables=receivables,
    )


# ───────────────────────── starclothing（服装销售） ─────────────────────────


def _build_starclothing() -> CrmData:
    """星图服装销售口径：品牌方/经销商/ODM 客户与成衣产品、服装典型客诉。"""
    R = D.rng(20241125)

    customers = [
        {"code": "C-BRAND-001", "name": "优衣库中国", "type": "品牌", "industry": "快时尚服装",
         "region": "华东", "credit_grade": "A", "payment_terms_days": 60, "currency": "CNY",
         "owner": "陈鹭", "address": "上海市静安区"},
        {"code": "C-BRAND-002", "name": "太平鸟服饰", "type": "品牌", "industry": "休闲男装",
         "region": "华东", "credit_grade": "A", "payment_terms_days": 45, "currency": "CNY",
         "owner": "陈鹭", "address": "浙江省宁波市"},
        {"code": "C-BRAND-003", "name": "波司登", "type": "品牌", "industry": "羽绒服",
         "region": "华东", "credit_grade": "A", "payment_terms_days": 60, "currency": "CNY",
         "owner": "周琰", "address": "江苏省苏州市"},
        {"code": "C-BRAND-004", "name": "安踏体育", "type": "品牌", "industry": "运动服饰",
         "region": "华南", "credit_grade": "A", "payment_terms_days": 45, "currency": "CNY",
         "owner": "周琰", "address": "福建省厦门市"},
        {"code": "C-DIST-010", "name": "上海德马泰克经销", "type": "经销商", "industry": "服装分销",
         "region": "华东", "credit_grade": "B", "payment_terms_days": 30, "currency": "CNY",
         "owner": "林苒", "address": "上海市闵行区"},
        {"code": "C-DIST-011", "name": "杭州四季青档口", "type": "经销商", "industry": "服装批发",
         "region": "华东", "credit_grade": "B", "payment_terms_days": 15, "currency": "CNY",
         "owner": "林苒", "address": "浙江省杭州市"},
        {"code": "C-ODM-020", "name": "东莞立讯服装 ODM", "type": "ODM代工", "industry": "服装代工",
         "region": "华南", "credit_grade": "B", "payment_terms_days": 45, "currency": "CNY",
         "owner": "黄淇", "address": "广东省东莞市"},
    ]
    customer_by_code = {c["code"]: c for c in customers}

    contacts: list[dict] = []
    for c in customers:
        n = D.randint(R, 1, 2)
        for i in range(n):
            contacts.append({
                "contact_id": f"XCT{D.pad(D.randint(R, 1000, 9999))}",
                "customer_code": c["code"],
                "name": D.pick(R, ["沈雯", "韩雪", "江涛", "夏琳", "范琦", "蔡伟", "陶然", "宋媛"]),
                "title": D.pick(R, ["商品总监", "采购经理", "面料主管", "供应链总监", "档口老板"]),
                "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
                "email": f"contact{i}@{c['code'].lower()}.example",
                "decision_role": D.pick(R, ["决策者", "影响者", "使用者", "把关者"]),
            })

    # 成衣产品编码（呼应 MES starclothing 工单的产品口径）
    product_codes = [
        "P-TEE-001",   # 纯棉圆领 T 恤
        "P-SHIRT-002", # 法兰绒衬衫
        "P-JKT-003",   # 摇粒绒外套
        "P-COAT-004",  # 双面呢大衣
        "P-PNT-005",   # 针织运动裤
        "P-VEST-006",  # 防风冲锋衣
    ]
    stages = ["发现", "方案", "报价", "谈判", "已签约", "输单"]
    sources = ["订货会", "档口返单", "电商直播", "品牌方直采", "ODM 招标", "老客户复购"]

    opportunities: list[dict] = []
    quotations: list[dict] = []
    for i in range(10):
        cust = D.pick(R, customers)
        product = D.pick(R, product_codes)
        stage = D.pick(R, stages)
        amount = D.randint(R, 80_000, 1_500_000)
        oid = f"XOPP{D.pad(20260000 + i * 43 + 11)}"
        opportunities.append({
            "opportunity_id": oid,
            "customer_code": cust["code"],
            "customer_name": cust["name"],
            "product_code": product,
            "stage": stage,
            "amount": amount,
            "currency": cust["currency"],
            "owner": cust["owner"],
            "source": D.pick(R, sources),
            "expected_close": f"{BASE_DATE + timedelta(days=D.randint(R, -45, 45))}",
        })
        qid = f"XQT{D.pad(20260000 + i * 29 + 7)}"
        tiers = [
            {"min_qty": 1, "unit_price": D.randint(R, 35, 280)},
            {"min_qty": 300, "unit_price": D.randint(R, 30, 240)},
            {"min_qty": 3000, "unit_price": D.randint(R, 22, 190)},
        ]
        quotations.append({
            "quotation_id": qid,
            "opportunity_id": oid,
            "customer_code": cust["code"],
            "product_code": product,
            "customer_part_no": f"{cust['code'][-3:]}-{product[-3:]}",
            "currency": cust["currency"],
            "tiers": tiers,
            "mold_fee": D.pick(R, [0, 3000, 8000, 18000]),  # 制版/打样模具费
            "sample_fee": D.pick(R, [0, 800, 1500, 3500]),  # 打样费
            "valid_until": f"{BASE_DATE + timedelta(days=30)}",
            "status": D.pick(R, ["草稿", "待审", "已发", "已接受", "已拒绝"]),
        })

    opportunity_by_no = {o["opportunity_id"]: o for o in opportunities}
    quotation_by_no = {q["quotation_id"]: q for q in quotations}

    so_status = ["已下单", "生产中", "已发货", "已收货", "已关闭"]
    sales_orders: list[dict] = []
    for i in range(12):
        q = D.pick(R, quotations)
        cust = customer_by_code[q["customer_code"]]
        qty = D.randint(R, 200, 5000)
        sales_orders.append({
            "so_no": f"XSO{D.pad(20260000 + i * 37 + 3)}",
            "customer_code": q["customer_code"],
            "customer_name": cust["name"],
            "product_code": q["product_code"],
            "qty": qty,
            "unit_price": q["tiers"][0]["unit_price"],
            "currency": cust["currency"],
            "status": D.pick(R, so_status),
            "delivery_date": f"{BASE_DATE + timedelta(days=D.randint(R, 5, 45))}",
        })

    follow_ups: list[dict] = []
    for i in range(18):
        cust = D.pick(R, customers)
        opp = D.pick(R, opportunities)
        follow_ups.append({
            "followup_id": f"XFU{D.pad(20260000 + i * 19)}",
            "customer_code": cust["code"],
            "opportunity_id": opp["opportunity_id"],
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 18))}T{D.pad(D.randint(R, 9, 18))}:00:00",
            "method": D.pick(R, ["电话", "拜访", "邮件", "微信", "直播对接"]),
            "owner": cust["owner"],
            "content": D.pick(R, [
                "确认主辅料打样色卡，客户对色差范围有疑问",
                "发送最新阶梯报价，等待采购评审",
                "现场拜访，确认订货会下季度 SKU 与备量",
                "客户反馈到货拼缝开线，已转质量部立项 8D",
                "对账确认上月发货明细，已开具增值税专用发票",
                "电商直播爆款追加返单，确认交期与产能",
                "ODM 客户要求提供面料检测报告，已联系实验室",
            ]),
            "next_action": D.pick(R, ["寄送样衣", "更新报价", "安排验厂", "提供检测报告", "跟进回款", "确认排产"]),
        })

    defect_types = [
        "拉链卡顿/掉漆",
        "压胶处渗水",
        "拼缝处开线",
        "色差超标",
        "尺码偏小/偏大",
        "面料起球",
        "印花脱落",
        "纽扣掉落",
    ]
    severity_pool = ["一般", "严重", "致命"]
    status_pool = ["待处理", "处理中", "已闭环", "已赔付"]
    _wo_pool = _mes_work_orders("starclothing")
    complaints: list[dict] = []
    for i in range(9):
        cust = D.pick(R, customers)
        product = D.pick(R, product_codes)
        won = D.pick(R, _wo_pool)
        defect = D.pick(R, defect_types)
        claim_qty = D.randint(R, 20, 800)
        unit_claim = D.randfloat(R, 15.0, 380.0)
        complaints.append({
            "complaint_id": f"XCP{D.pad(20260000 + i * 17)}",
            "complaint_no": f"XCP2026{D.pad(D.randint(R, 1000, 9999))}",
            "customer_code": cust["code"],
            "customer_name": cust["name"],
            "product_code": product,
            "batch_no": f"XB{D.pad(D.randint(R, 20250000, 20260000))}",
            "work_order_no": won,  # ← 跨系统联动点（MES starclothing 工单）
            "defect": defect,
            "defect_type": defect,
            "severity": D.pick(R, severity_pool),
            "claim_qty": claim_qty,
            "claim_amount": round(claim_qty * unit_claim, 2),
            "status": D.pick(R, status_pool),
            "reported_at": f"{BASE_DATE - timedelta(days=D.randint(R, 1, 30))}",
            "owner": D.pick(R, ["质量部-周", "客服-陈", "客服-夏", "质量部-黄"]),
        })
    complaint_by_no = {c["complaint_id"]: c for c in complaints}

    receivables: list[dict] = []
    for i in range(10):
        cust = D.pick(R, customers)
        so = D.pick(R, sales_orders)
        inv_amount = D.randint(R, 40_000, 800_000)
        due_date = BASE_DATE + timedelta(days=D.randint(R, -30, 45))
        overdue = (BASE_DATE - due_date).days > 0
        receivables.append({
            "receivable_id": f"XAR{D.pad(20260000 + i * 13)}",
            "customer_code": cust["code"],
            "customer_name": cust["name"],
            "so_no": so["so_no"],
            "invoice_no": f"XINV{D.pad(D.randint(R, 20260000, 20269999))}",
            "amount": inv_amount,
            "currency": cust["currency"],
            "billing_date": f"{BASE_DATE - timedelta(days=D.randint(R, 20, 75))}",
            "due_date": f"{due_date}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已收款"]),
            "days_overdue": max(0, (BASE_DATE - due_date).days),
        })

    return CrmData(
        customers=customers, customer_by_code=customer_by_code,
        contacts=contacts,
        opportunities=opportunities, opportunity_by_no=opportunity_by_no,
        quotations=quotations, quotation_by_no=quotation_by_no,
        sales_orders=sales_orders, follow_ups=follow_ups,
        complaints=complaints, complaint_by_no=complaint_by_no,
        receivables=receivables,
    )


# ───────────────────────── agileac（敏睿空调） ─────────────────────────


def _build_agileac() -> CrmData:
    """敏睿空调销售口径：经销商/电商平台/工程客户 + 6 款空调产品 + 8 类空调客诉
    （含 AG-SVC-01 3 条重点故障客诉 CR-AG-2026-0001/0002/0003）+ 电商退换货。"""
    R = D.rng(20260103)

    customers = [
        {"code": "C-AG-RETAIL-01", "name": "家电连锁 A（华东）", "type": "经销商",
         "industry": "家电零售", "region": "华东", "credit_grade": "A",
         "payment_terms_days": 60, "currency": "CNY", "owner": "陈鹭",
         "address": "上海市浦东新区"},
        {"code": "C-AG-RETAIL-02", "name": "家电连锁 C（华南）", "type": "经销商",
         "industry": "家电零售", "region": "华南", "credit_grade": "A",
         "payment_terms_days": 45, "currency": "CNY", "owner": "周琰",
         "address": "广东省深圳市福田区"},
        {"code": "C-AG-ECOM-01", "name": "天猫旗舰·敏睿官方店", "type": "电商",
         "industry": "电商零售", "region": "全国", "credit_grade": "A",
         "payment_terms_days": 30, "currency": "CNY", "owner": "林苒",
         "address": "浙江省杭州市余杭区"},
        {"code": "C-AG-ECOM-02", "name": "京东自营·敏睿店", "type": "电商",
         "industry": "电商零售", "region": "全国", "credit_grade": "A",
         "payment_terms_days": 30, "currency": "CNY", "owner": "林苒",
         "address": "北京市大兴区"},
        {"code": "C-AG-DEALER-01", "name": "苏州区域经销·空调专营商", "type": "经销商",
         "industry": "区域经销", "region": "华东", "credit_grade": "B",
         "payment_terms_days": 30, "currency": "CNY", "owner": "陈鹭",
         "address": "江苏省苏州市姑苏区"},
        {"code": "C-AG-PROJ-01", "name": "工程项目 B（多联机采购）", "type": "工程客户",
         "industry": "商用工程", "region": "华东", "credit_grade": "A",
         "payment_terms_days": 90, "currency": "CNY", "owner": "黄淇",
         "address": "上海市虹口区"},
        {"code": "C-AG-PROJ-02", "name": "工程项目 C（风管机采购）", "type": "工程客户",
         "industry": "商用工程", "region": "华南", "credit_grade": "A",
         "payment_terms_days": 90, "currency": "CNY", "owner": "黄淇",
         "address": "广东省广州市天河区"},
        {"code": "C-AG-PROJ-03", "name": "工程项目 D（模块机组）", "type": "工程客户",
         "industry": "商用工程", "region": "华南", "credit_grade": "A",
         "payment_terms_days": 90, "currency": "CNY", "owner": "黄淇",
         "address": "广东省广州市番禺区"},
    ]
    customer_by_code = {c["code"]: c for c in customers}

    contacts: list[dict] = []
    for c in customers:
        n = D.randint(R, 1, 3)
        for i in range(n):
            contacts.append({
                "contact_id": f"AGCT{D.pad(D.randint(R, 1000, 9999))}",
                "customer_code": c["code"],
                "name": D.pick(R, ["沈雯", "韩雪", "江涛", "夏琳", "范琦", "蔡伟", "陶然", "宋媛"]),
                "title": D.pick(R, ["采购总监", "工程部经理", "采购专员", "供应链总监", "门店店长"]),
                "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
                "email": f"contact{i}@{c['code'].lower()}.example",
                "decision_role": D.pick(R, ["决策者", "影响者", "使用者", "把关者"]),
            })

    # 空调产品编码（呼应 MES agileac 工单 + PLM agileac styles）
    product_codes = [
        "P-RC-WALL-15",   # 1.5匹壁挂
        "P-RC-CAB-30",    # 3匹柜机
        "P-RC-MOVE-10",   # 1匹移动
        "P-CC-VRV-360",   # 商用多联机
        "P-CC-DUCT-50",   # 商用风管机
        "P-CC-CHILL-100", # 商用模块机
    ]
    stages = ["发现", "方案", "报价", "谈判", "已签约", "输单"]
    sources = ["门店询价", "电商订单", "工程招标", "经销返单", "老客户复购", "展会意向"]

    opportunities: list[dict] = []
    quotations: list[dict] = []
    for i in range(10):
        cust = D.pick(R, customers)
        product = D.pick(R, product_codes)
        stage = D.pick(R, stages)
        amount = D.randint(R, 80_000, 2_000_000)
        oid = f"AGOPP{D.pad(20260000 + i * 43 + 11)}"
        opportunities.append({
            "opportunity_id": oid,
            "customer_code": cust["code"],
            "customer_name": cust["name"],
            "product_code": product,
            "stage": stage,
            "amount": amount,
            "currency": cust["currency"],
            "owner": cust["owner"],
            "source": D.pick(R, sources),
            "expected_close": f"{BASE_DATE + timedelta(days=D.randint(R, -45, 45))}",
        })
        qid = f"AGQT{D.pad(20260000 + i * 29 + 7)}"
        tiers = [
            {"min_qty": 1, "unit_price": D.randint(R, 1200, 38000)},
            {"min_qty": 50, "unit_price": D.randint(R, 1100, 35000)},
            {"min_qty": 500, "unit_price": D.randint(R, 980, 32000)},
        ]
        quotations.append({
            "quotation_id": qid,
            "opportunity_id": oid,
            "customer_code": cust["code"],
            "product_code": product,
            "customer_part_no": f"{cust['code'][-3:]}-{product[-3:]}",
            "currency": cust["currency"],
            "tiers": tiers,
            "mold_fee": D.pick(R, [0, 3000, 8000, 18000]),
            "sample_fee": D.pick(R, [0, 800, 1500, 3500]),
            "valid_until": f"{BASE_DATE + timedelta(days=30)}",
            "status": D.pick(R, ["草稿", "待审", "已发", "已接受", "已拒绝"]),
        })

    opportunity_by_no = {o["opportunity_id"]: o for o in opportunities}
    quotation_by_no = {q["quotation_id"]: q for q in quotations}

    so_status = ["已下单", "生产中", "已发货", "已收货", "已关闭"]
    sales_orders: list[dict] = []
    so_specs = [
        ("AGSO20260001", "C-AG-RETAIL-01", "P-RC-WALL-15", 500, 1880, "已收货"),
        ("AGSO20260002", "C-AG-RETAIL-02", "P-RC-CAB-30", 300, 3680, "已发货"),
        ("AGSO20260003", "C-AG-ECOM-01", "P-RC-MOVE-10", 200, 1280, "已收货"),
        ("AGSO20260004", "C-AG-ECOM-02", "P-RC-WALL-15", 800, 1880, "生产中"),
        ("AGSO20260005", "C-AG-DEALER-01", "P-RC-WALL-15", 600, 1880, "已下单"),
        ("AGSO20260201", "C-AG-PROJ-01", "P-CC-VRV-360", 80, 12800, "生产中"),
        ("AGSO20260202", "C-AG-PROJ-02", "P-CC-DUCT-50", 120, 6800, "已下单"),
        ("AGSO20260203", "C-AG-PROJ-03", "P-CC-CHILL-100", 30, 38800, "生产中"),
    ]
    for so_no, cust_code, pcode, qty, unit_price, status in so_specs:
        cust = customer_by_code[cust_code]
        sales_orders.append({
            "so_no": so_no,
            "customer_code": cust_code,
            "customer_name": cust["name"],
            "product_code": pcode,
            "qty": qty,
            "unit_price": unit_price,
            "currency": cust["currency"],
            "status": status,
            "delivery_date": f"{BASE_DATE + timedelta(days=D.randint(R, 5, 45))}",
        })

    follow_ups: list[dict] = []
    for i in range(15):
        cust = D.pick(R, customers)
        opp = D.pick(R, opportunities)
        follow_ups.append({
            "followup_id": f"AGFU{D.pad(20260000 + i * 19)}",
            "customer_code": cust["code"],
            "opportunity_id": opp["opportunity_id"],
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 18))}T{D.pad(D.randint(R, 9, 18), 2)}:00:00",
            "method": D.pick(R, ["电话", "拜访", "邮件", "微信", "工程对接"]),
            "owner": cust["owner"],
            "content": D.pick(R, [
                "客户报修不制冷，已转售后工程师 8D 立项",
                "电商退换货到货质检异常，已建退换工单",
                "工程项目招标已确认主推多联机方案",
                "区域经销追加 Q3 备货，确认交期与产能",
                "对账确认上月发货明细，已开具增值税专用发票",
                "商用机客户要求提供模块机组能效检测报告",
                "门店反馈柜机异音，已派售后工程师上门",
            ]),
            "next_action": D.pick(R, ["派售后上门", "建退换工单", "更新报价", "提供检测报告", "跟进回款", "确认排产"]),
        })

    # 客诉：含 AG-SVC-01 3 条重点故障客诉 + 电商退换货客诉
    complaint_specs = [
        # (complaint_id, complaint_no, customer_code, product_code, work_order_no, defect, severity, status, off, ctype, claim_qty)
        ("AGCP-0001", "CR-AG-2026-0001", "C-AG-RETAIL-01", "P-RC-WALL-15",
         "AWO20260101", "不制冷", "严重", "8D 进行中", -8, "fault", 1),
        ("AGCP-0002", "CR-AG-2026-0002", "C-AG-PROJ-01", "P-CC-VRV-360",
         "AWO20260210", "通讯故障", "致命", "分析中", -6, "fault", 1),
        ("AGCP-0003", "CR-AG-2026-0003", "C-AG-RETAIL-02", "P-RC-CAB-30",
         "AWO20260105", "漏水", "严重", "8D 进行中", -5, "fault", 1),
        ("AGCP-0004", "CR-AG-2026-0004", "C-AG-RETAIL-01", "P-RC-WALL-15",
         "AWO20260101", "异音", "一般", "处理中", -10, "fault", 1),
        ("AGCP-0005", "CR-AG-2026-0005", "C-AG-DEALER-01", "P-RC-WALL-15",
         "AWO20260103", "不制冷", "一般", "已闭环", -25, "fault", 1),
        ("AGCP-0006", "CR-AG-2026-0006", "C-AG-RETAIL-02", "P-RC-CAB-30",
         "AWO20260106", "异音", "一般", "已闭环", -22, "fault", 1),
        ("AGCP-0007", "CR-AG-2026-0007", "C-AG-RETAIL-01", "P-RC-WALL-15",
         "AWO20260104", "控制板故障", "严重", "已闭环", -20, "fault", 1),
        ("AGCP-0008", "CR-AG-2026-0008", "C-AG-PROJ-01", "P-CC-VRV-360",
         "AWO20260211", "高压保护", "严重", "处理中", -2, "fault", 1),
        ("AGCP-0009", "CR-AG-2026-0009", "C-AG-PROJ-03", "P-CC-CHILL-100",
         "AWO20260220", "高压保护", "严重", "8D 进行中", -10, "fault", 1),
        ("AGCP-0010", "CR-AG-2026-0010", "C-AG-PROJ-02", "P-CC-DUCT-50",
         "AWO20260215", "冷媒泄漏", "严重", "处理中", -5, "fault", 1),
        ("AGCP-0011", "CR-AG-2026-0011", "C-AG-PROJ-01", "P-CC-VRV-360",
         "AWO20260212", "冷媒泄漏", "严重", "待处理", 0, "fault", 1),
        ("AGCP-0012", "CR-AG-2026-0012", "C-AG-PROJ-01", "P-CC-VRV-360",
         "AWO20260213", "化霜失效", "一般", "待处理", 0, "fault", 1),
        ("AGCP-0013", "CR-AG-2026-0013", "C-AG-ECOM-01", "P-RC-MOVE-10",
         "AWO20260108", "异音", "一般", "已闭环", -15, "fault", 1),
        # 退换货客诉（AG-SAL-01 用）
        ("AGCP-R01", "CR-AG-2026-R01", "C-AG-ECOM-01", "P-RC-WALL-15",
         "AWO20260101", "外观划痕", "一般", "处理中", -2, "return", 1),
        ("AGCP-R02", "CR-AG-2026-R02", "C-AG-ECOM-02", "P-RC-WALL-15",
         "AWO20260102", "型号不符", "一般", "处理中", -1, "return", 1),
        ("AGCP-R03", "CR-AG-2026-R03", "C-AG-ECOM-01", "P-RC-MOVE-10",
         "AWO20260108", "运输损坏", "一般", "待处理", 0, "return", 1),
    ]
    complaints: list[dict] = []
    for cid, cno, cust_code, pcode, won, defect, sev, status, off, ctype, claim_qty in complaint_specs:
        cust = customer_by_code[cust_code]
        unit_claim = D.randfloat(R, 200.0, 8000.0)
        complaints.append({
            "complaint_id": cid,
            "complaint_no": cno,
            "customer_code": cust_code,
            "customer_name": cust["name"],
            "product_code": pcode,
            "batch_no": f"AGB{D.pad(D.randint(R, 20260000, 20269999))}",
            "work_order_no": won,  # ← 跨系统联动点（MES agileac 工单）
            "defect": defect,
            "defect_type": defect,
            "type": ctype,  # fault / return
            "severity": sev,
            "claim_qty": claim_qty,
            "claim_amount": round(claim_qty * unit_claim, 2),
            "status": status,
            "reported_at": f"{BASE_DATE + timedelta(days=off)}",
            "owner": D.pick(R, ["售后工程师-陈", "客服-夏", "售后工程师-周", "电商运营-林"]),
        })
    complaint_by_no = {c["complaint_id"]: c for c in complaints}

    # 应收：含 2 条逾期，对应 AG-FIN-01 应收催办
    receivable_specs = [
        # (suffix, customer_code, so_no, amount, billing_off, due_off)
        (1, "C-AG-RETAIL-01", "AGSO20260001", 940_000, -25, 20),    # 未到期
        (2, "C-AG-RETAIL-02", "AGSO20260002", 1_104_000, -22, -3),  # 逾期
        (3, "C-AG-ECOM-01", "AGSO20260003", 256_000, -20, 25),      # 未到期
        (4, "C-AG-ECOM-02", "AGSO20260004", 1_504_000, -18, -1),    # 逾期
        (5, "C-AG-DEALER-01", "AGSO20260005", 1_128_000, -15, 30),  # 未到期
        (6, "C-AG-PROJ-01", "AGSO20260201", 1_024_000, -12, -5),     # 逾期
        (7, "C-AG-PROJ-02", "AGSO20260202", 816_000, -10, 35),       # 未到期
        (8, "C-AG-PROJ-03", "AGSO20260203", 1_164_000, -8, 40),      # 未到期
    ]
    receivables: list[dict] = []
    for suffix, cust_code, so_no, amt, b_off, d_off in receivable_specs:
        cust = customer_by_code[cust_code]
        due = BASE_DATE + timedelta(days=d_off)
        overdue = (BASE_DATE - due).days > 0
        receivables.append({
            "receivable_id": f"AGAR{D.pad(20260000 + suffix * 13)}",
            "customer_code": cust_code,
            "customer_name": cust["name"],
            "so_no": so_no,
            "invoice_no": f"AGINV{D.pad(D.randint(R, 20260000, 20269999))}",
            "amount": amt,
            "currency": cust["currency"],
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已收款"]),
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    return CrmData(
        customers=customers, customer_by_code=customer_by_code,
        contacts=contacts,
        opportunities=opportunities, opportunity_by_no=opportunity_by_no,
        quotations=quotations, quotation_by_no=quotation_by_no,
        sales_orders=sales_orders, follow_ups=follow_ups,
        complaints=complaints, complaint_by_no=complaint_by_no,
        receivables=receivables,
    )


# ───────────────────────── agilesteel（敏睿钢铁） ─────────────────────────


def _build_agilesteel() -> CrmData:
    """敏睿钢铁销售口径：工程项目/钢贸经销商/直供终端客户 + 钢种产品 + 钢材质量异议客诉
    （ASCP，跨系统联动 MES 钢铁工单 SWO）+ 销售订单 ASSO（驱动 MES 按单排产 SPO）+ 应收 ASINV。"""
    R = D.rng(20260621)

    customers = [
        {"code": "C-AS-PROJ-01", "name": "中建三局·市政桥梁项目", "type": "工程客户",
         "industry": "建筑/交通", "region": "华中", "credit_grade": "A",
         "payment_terms_days": 90, "currency": "CNY", "owner": "黄淇",
         "address": "湖北省武汉市"},
        {"code": "C-AS-PROJ-02", "name": "中交二航局·跨海大桥项目", "type": "工程客户",
         "industry": "交通", "region": "华南", "credit_grade": "A",
         "payment_terms_days": 90, "currency": "CNY", "owner": "黄淇",
         "address": "广东省广州市"},
        {"code": "C-AS-TRADE-01", "name": "长三角钢贸·建材分销", "type": "钢贸经销商",
         "industry": "建材贸易", "region": "华东", "credit_grade": "A",
         "payment_terms_days": 45, "currency": "CNY", "owner": "陈鹭",
         "address": "上海市宝山区"},
        {"code": "C-AS-TRADE-02", "name": "西南钢材市场·优特钢分销", "type": "钢贸经销商",
         "industry": "优特钢贸易", "region": "西南", "credit_grade": "B",
         "payment_terms_days": 30, "currency": "CNY", "owner": "周琰",
         "address": "四川省成都市"},
        {"code": "C-AS-OEM-01", "name": "三一重工·机械用钢直供", "type": "直供终端",
         "industry": "机械制造", "region": "华中", "credit_grade": "A",
         "payment_terms_days": 60, "currency": "CNY", "owner": "黄淇",
         "address": "湖南省长沙市"},
        {"code": "C-AS-OEM-02", "name": "东风汽车·齿轮钢直供", "type": "直供终端",
         "industry": "汽车制造", "region": "华中", "credit_grade": "A",
         "payment_terms_days": 60, "currency": "CNY", "owner": "黄淇",
         "address": "湖北省十堰市"},
        {"code": "C-AS-ENERGY-01", "name": "国家电网·铁塔用钢直供", "type": "直供终端",
         "industry": "能源", "region": "华北", "credit_grade": "A",
         "payment_terms_days": 90, "currency": "CNY", "owner": "黄淇",
         "address": "北京市西城区"},
        {"code": "C-AS-EXP-01", "name": "东南亚建材出口·海外经销", "type": "海外出口",
         "industry": "建材出口", "region": "海外", "credit_grade": "B",
         "payment_terms_days": 60, "currency": "USD", "owner": "林苒",
         "address": "上海市浦东新区"},
    ]
    customer_by_code = {c["code"]: c for c in customers}

    contacts: list[dict] = []
    for c in customers:
        n = D.randint(R, 1, 3)
        for i in range(n):
            contacts.append({
                "contact_id": f"ASCT{D.pad(D.randint(R, 1000, 9999))}",
                "customer_code": c["code"],
                "name": D.pick(R, ["沈雯", "韩雪", "江涛", "夏琳", "范琦", "蔡伟", "陶然", "宋媛"]),
                "title": D.pick(R, ["采购总监", "工程部经理", "采购专员", "供应链总监", "项目总工"]),
                "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
                "email": f"contact{i}@{c['code'].lower()}.example",
                "decision_role": D.pick(R, ["决策者", "影响者", "使用者", "把关者"]),
            })

    # 钢种产品编码（与 MES agilesteel 炉次 steel_grade + ERP 钢坯对齐）
    product_codes = [
        "P-ST-Q345B",   # 低合金高强钢 螺纹钢
        "P-ST-45#",     # 优质碳素钢
        "P-ST-40Cr",    # 合金结构钢
        "P-ST-20MnSi",  # 建筑用钢
        "P-ST-Q235B",   # 普碳钢
        "P-ST-42CrMo",  # 高性能合金钢
    ]
    stages = ["发现", "方案", "报价", "谈判", "已签约", "输单"]
    sources = ["工程招标", "经销返单", "终端直供", "海外询价", "老客户复购", "展会意向"]

    opportunities: list[dict] = []
    quotations: list[dict] = []
    for i in range(10):
        cust = D.pick(R, customers)
        product = D.pick(R, product_codes)
        stage = D.pick(R, stages)
        amount = D.randint(R, 200_000, 8_000_000)
        oid = f"ASOPP{D.pad(20260000 + i * 43 + 11)}"
        opportunities.append({
            "opportunity_id": oid,
            "customer_code": cust["code"],
            "customer_name": cust["name"],
            "product_code": product,
            "stage": stage,
            "amount": amount,
            "currency": cust["currency"],
            "owner": cust["owner"],
            "source": D.pick(R, sources),
            "expected_close": f"{BASE_DATE + timedelta(days=D.randint(R, -45, 60))}",
        })
        qid = f"ASQT{D.pad(20260000 + i * 29 + 7)}"
        tiers = [
            {"min_qty": 1, "unit_price": D.randint(R, 3800, 5800)},
            {"min_qty": 100, "unit_price": D.randint(R, 3750, 5600)},
            {"min_qty": 1000, "unit_price": D.randint(R, 3700, 5400)},
        ]
        quotations.append({
            "quotation_id": qid,
            "opportunity_id": oid,
            "customer_code": cust["code"],
            "product_code": product,
            "customer_part_no": f"{cust['code'][-3:]}-{product[-3:]}",
            "currency": cust["currency"],
            "tiers": tiers,
            "mold_fee": 0,
            "sample_fee": D.pick(R, [0, 800, 1500]),
            "valid_until": f"{BASE_DATE + timedelta(days=30)}",
            "status": D.pick(R, ["草稿", "待审", "已发", "已接受", "已拒绝"]),
        })
    opportunity_by_no = {o["opportunity_id"]: o for o in opportunities}
    quotation_by_no = {q["quotation_id"]: q for q in quotations}

    so_status = ["已下单", "生产中", "已发货", "已收货", "已关闭"]
    sales_orders: list[dict] = []
    so_specs = [
        ("ASSO202607001", "C-AS-PROJ-01", "P-ST-Q345B", 3000, 4280, "生产中"),
        ("ASSO202607002", "C-AS-PROJ-02", "P-ST-Q345B", 5000, 4280, "已下单"),
        ("ASSO202607003", "C-AS-TRADE-01", "P-ST-20MnSi", 2000, 4150, "已发货"),
        ("ASSO202607004", "C-AS-TRADE-02", "P-ST-45#", 1500, 4650, "生产中"),
        ("ASSO202607005", "C-AS-OEM-01", "P-ST-40Cr", 800, 5280, "已下单"),
        ("ASSO202607006", "C-AS-OEM-02", "P-ST-42CrMo", 600, 6800, "生产中"),
        ("ASSO202607007", "C-AS-ENERGY-01", "P-ST-Q345B", 2500, 4280, "已下单"),
        ("ASSO202607008", "C-AS-EXP-01", "P-ST-Q235B", 1800, 3980, "已发货"),
    ]
    for so_no, cust_code, pcode, qty, unit_price, status in so_specs:
        cust = customer_by_code[cust_code]
        sales_orders.append({
            "so_no": so_no,
            "customer_code": cust_code,
            "customer_name": cust["name"],
            "product_code": pcode,
            "qty": qty,
            "unit_price": unit_price,
            "currency": cust["currency"],
            "status": status,
            "delivery_date": f"{BASE_DATE + timedelta(days=D.randint(R, 5, 45))}",
        })

    follow_ups: list[dict] = []
    for i in range(15):
        cust = D.pick(R, customers)
        opp = D.pick(R, opportunities)
        follow_ups.append({
            "followup_id": f"ASFU{D.pad(20260000 + i * 19)}",
            "customer_code": cust["code"],
            "opportunity_id": opp["opportunity_id"],
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 18))}T{D.pad(D.randint(R, 9, 18), 2)}:00:00",
            "method": D.pick(R, ["电话", "拜访", "邮件", "微信", "工程对接"]),
            "owner": cust["owner"],
            "content": D.pick(R, [
                "桥梁项目确认 Q345B 螺纹钢供货计划，需锁定产能",
                "钢贸追加 Q3 优特钢备货，确认交期与产能",
                "汽车齿轮钢客户要求提供力学性能检测报告",
                "海外出口询价 Q235B，确认 FOB 报价与船期",
                "对账确认上月发货明细，已开具增值税专用发票",
                "终端客户要求提供碳足迹与低碳认证材料",
                "工程项目招标已确认主推 42CrMo 高性能钢方案",
            ]),
            "next_action": D.pick(R, ["确认排产", "更新报价", "提供检测报告", "跟进回款", "提供低碳认证", "锁定船期"]),
        })

    # 钢材质量异议客诉（ASCP，跨系统联动 MES 钢铁工单 SWO）
    mes_wos = _mes_work_orders("agilesteel")
    complaint_specs = [
        # (cid, cno, customer_code, product_code, won, defect, sev, status, off, ctype, claim_qty)
        ("ASCP-0001", "CR-AS-2026-0001", "C-AS-PROJ-01", "P-ST-Q345B",
         mes_wos[0] if mes_wos else "SWO202607001", "表面裂纹", "严重", "8D 进行中", -8, "quality", 5),
        ("ASCP-0002", "CR-AS-2026-0002", "C-AS-OEM-01", "P-ST-40Cr",
         mes_wos[1] if len(mes_wos) > 1 else "SWO202607005", "成分偏析", "严重", "分析中", -6, "quality", 3),
        ("ASCP-0003", "CR-AS-2026-0003", "C-AS-TRADE-01", "P-ST-20MnSi",
         mes_wos[2] if len(mes_wos) > 2 else "SWO202607003", "尺寸超差", "一般", "处理中", -5, "quality", 8),
        ("ASCP-0004", "CR-AS-2026-0004", "C-AS-OEM-02", "P-ST-42CrMo",
         mes_wos[3] if len(mes_wos) > 3 else "SWO202607006", "非金属夹杂", "严重", "8D 进行中", -4, "quality", 2),
        ("ASCP-0005", "CR-AS-2026-0005", "C-AS-PROJ-02", "P-ST-Q345B",
         mes_wos[4] if len(mes_wos) > 4 else "SWO202607002", "氧化铁皮", "一般", "已闭环", -25, "quality", 6),
        ("ASCP-0006", "CR-AS-2026-0006", "C-AS-TRADE-02", "P-ST-45#",
         mes_wos[0] if mes_wos else "SWO202607001", "表面划伤", "一般", "已闭环", -22, "quality", 4),
        ("ASCP-0007", "CR-AS-2026-0007", "C-AS-ENERGY-01", "P-ST-Q345B",
         mes_wos[1] if len(mes_wos) > 1 else "SWO202607005", "力学性能不达标", "严重", "处理中", -2, "quality", 3),
    ]
    complaints: list[dict] = []
    for cid, cno, cust_code, pcode, won, defect, sev, status, off, ctype, claim_qty in complaint_specs:
        cust = customer_by_code[cust_code]
        unit_claim = D.randfloat(R, 4280.0, 6800.0)
        complaints.append({
            "complaint_id": cid,
            "complaint_no": cno,
            "customer_code": cust_code,
            "customer_name": cust["name"],
            "product_code": pcode,
            "batch_no": f"ASB{D.pad(D.randint(R, 20260000, 20269999))}",
            "work_order_no": won,  # ← 跨系统联动点（MES agilesteel 工单 SWO）
            "defect": defect,
            "defect_type": defect,
            "type": ctype,  # quality 质量异议
            "severity": sev,
            "claim_qty": claim_qty,
            "claim_amount": round(claim_qty * unit_claim, 2),
            "status": status,
            "reported_at": f"{BASE_DATE + timedelta(days=off)}",
            "owner": D.pick(R, ["质量异议-陈", "客服-夏", "质量异议-周", "销售运营-林"]),
        })
    complaint_by_no = {c["complaint_id"]: c for c in complaints}

    # 应收：含 2 条逾期
    receivable_specs = [
        # (suffix, customer_code, so_no, amount, billing_off, due_off)
        (1, "C-AS-PROJ-01", "ASSO202607001", 12_840_000, -25, 20),   # 未到期
        (2, "C-AS-PROJ-02", "ASSO202607002", 21_400_000, -22, -3),   # 逾期
        (3, "C-AS-TRADE-01", "ASSO202607003", 8_300_000, -20, 25),   # 未到期
        (4, "C-AS-TRADE-02", "ASSO202607004", 6_975_000, -18, -1),    # 逾期
        (5, "C-AS-OEM-01", "ASSO202607005", 4_224_000, -15, 30),      # 未到期
        (6, "C-AS-OEM-02", "ASSO202607006", 4_080_000, -12, -5),      # 逾期
        (7, "C-AS-ENERGY-01", "ASSO202607007", 10_700_000, -10, 35),  # 未到期
        (8, "C-AS-EXP-01", "ASSO202607008", 7_164_000, -8, 40),        # 未到期
    ]
    receivables: list[dict] = []
    for suffix, cust_code, so_no, amt, b_off, d_off in receivable_specs:
        cust = customer_by_code[cust_code]
        due = BASE_DATE + timedelta(days=d_off)
        overdue = (BASE_DATE - due).days > 0
        receivables.append({
            "receivable_id": f"ASAR{D.pad(20260000 + suffix * 13)}",
            "customer_code": cust_code,
            "customer_name": cust["name"],
            "so_no": so_no,
            "invoice_no": f"ASIV{D.pad(D.randint(R, 20260000, 20269999))}",
            "amount": amt,
            "currency": cust["currency"],
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已收款"]),
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    return CrmData(
        customers=customers, customer_by_code=customer_by_code,
        contacts=contacts,
        opportunities=opportunities, opportunity_by_no=opportunity_by_no,
        quotations=quotations, quotation_by_no=quotation_by_no,
        sales_orders=sales_orders, follow_ups=follow_ups,
        complaints=complaints, complaint_by_no=complaint_by_no,
        receivables=receivables,
    )


# ───────────────────────── agilestationery（敏睿文具） ─────────────────────────


def _build_agilestationery() -> CrmData:
    """敏睿文具销售口径：经销商(DLR-)/KA大客户(KA-)/电商授权店 + 文具 SKU 产品 +
    销售订单(SO-) + 售后工单(CASE/客诉，跨系统联动 PIM 产品反馈 + ERP 出库) +
    应收(REC-，invoice_no 与 CST 销项发票 INV- 对齐)。"""
    R = D.rng(20260718)

    customers = [
        {"code": "DLR-01", "name": "华东文具分销·上海晨光联合体", "type": "经销商",
         "industry": "文具分销", "region": "华东", "credit_grade": "A",
         "payment_terms_days": 45, "currency": "CNY", "owner": "黄淇",
         "address": "上海市嘉定区"},
        {"code": "DLR-03", "name": "华南文具批发·广州联宝", "type": "经销商",
         "industry": "文具批发", "region": "华南", "credit_grade": "A",
         "payment_terms_days": 30, "currency": "CNY", "owner": "林苒",
         "address": "广东省广州市"},
        {"code": "DLR-05", "name": "西南 KA 集采·成都世纪文具", "type": "KA大客户",
         "industry": "办公集采", "region": "西南", "credit_grade": "B",
         "payment_terms_days": 60, "currency": "CNY", "owner": "周琰",
         "address": "四川省成都市"},
        {"code": "DLR-08", "name": "华北文具分销·北京世纪文仪", "type": "经销商",
         "industry": "文具分销", "region": "华北", "credit_grade": "B",
         "payment_terms_days": 45, "currency": "CNY", "owner": "黄淇",
         "address": "北京市朝阳区"},
        {"code": "KA-01", "name": "某政企采购中心·办公文具年度集采", "type": "KA大客户",
         "industry": "政企采购", "region": "华中", "credit_grade": "A",
         "payment_terms_days": 60, "currency": "CNY", "owner": "陈鹭",
         "address": "湖北省武汉市"},
        {"code": "KA-02", "name": "某连锁零售·全国办公用品集采", "type": "KA大客户",
         "industry": "连锁零售", "region": "全国", "credit_grade": "A",
         "payment_terms_days": 45, "currency": "CNY", "owner": "黄淇",
         "address": "广东省深圳市"},
        {"code": "EC-30", "name": "天猫·敏睿官方旗舰（授权）", "type": "电商渠道",
         "industry": "电商", "region": "华东", "credit_grade": "A",
         "payment_terms_days": 30, "currency": "CNY", "owner": "林苒",
         "address": "上海市浦东新区"},
        {"code": "EXP-01", "name": "东南亚文具出口·海外经销", "type": "海外出口",
         "industry": "文具出口", "region": "海外", "credit_grade": "B",
         "payment_terms_days": 60, "currency": "USD", "owner": "陈鹭",
         "address": "上海市浦东新区"},
    ]
    customer_by_code = {c["code"]: c for c in customers}

    contacts: list[dict] = []
    for c in customers:
        n = D.randint(R, 1, 3)
        for i in range(n):
            contacts.append({
                "contact_id": f"ASCT{D.pad(D.randint(R, 1000, 9999))}",
                "customer_code": c["code"],
                "name": D.pick(R, ["沈雯", "韩雪", "江涛", "夏琳", "范琦", "蔡伟", "陶然", "宋媛"]),
                "title": D.pick(R, ["采购总监", "采购经理", "采购专员", "供应链总监", "商品总监"]),
                "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
                "email": f"contact{i}@{c['code'].lower()}.example",
                "decision_role": D.pick(R, ["决策者", "影响者", "使用者", "把关者"]),
            })

    # 文具产品码（与 PIM SKU-ZB- / ERP M-ZB- 对齐）
    product_codes = ["SKU-ZB-G001", "SKU-ZB-G002", "SKU-ZB-G010", "SKU-ZB-B001",
                     "SKU-ZB-M001", "SKU-ZB-H001", "SKU-ZB-R001"]
    stages = ["发现", "方案", "报价", "谈判", "已签约", "输单"]
    sources = ["经销返单", "政企招标", "电商大促", "KA集采", "老客户复购", "展会意向"]

    opportunities: list[dict] = []
    quotations: list[dict] = []
    for i in range(10):
        cust = D.pick(R, customers)
        product = D.pick(R, product_codes)
        stage = D.pick(R, stages)
        amount = D.randint(R, 50_000, 800_000)
        oid = f"ASOPP{D.pad(20260000 + i * 43 + 11)}"
        opportunities.append({
            "opportunity_id": oid, "customer_code": cust["code"], "customer_name": cust["name"],
            "product_code": product, "stage": stage, "amount": amount,
            "currency": cust["currency"], "owner": cust["owner"],
            "source": D.pick(R, sources),
            "expected_close": f"{BASE_DATE + timedelta(days=D.randint(R, -30, 60))}",
        })
        qid = f"ASQT{D.pad(20260000 + i * 29 + 7)}"
        base_price = {"SKU-ZB-G001": 5.50, "SKU-ZB-G002": 5.50, "SKU-ZB-G010": 7.20,
                      "SKU-ZB-B001": 28.00, "SKU-ZB-M001": 9.90, "SKU-ZB-H001": 6.80,
                      "SKU-ZB-R001": 2.80}[product]
        tiers = [
            {"min_qty": 1, "unit_price": round(base_price * 1.0, 2)},
            {"min_qty": 100, "unit_price": round(base_price * 0.92, 2)},
            {"min_qty": 1000, "unit_price": round(base_price * 0.85, 2)},
        ]
        quotations.append({
            "quotation_id": qid, "opportunity_id": oid, "customer_code": cust["code"],
            "product_code": product, "customer_part_no": f"{cust['code']}-{product[-3:]}",
            "currency": cust["currency"], "tiers": tiers, "mold_fee": 0,
            "sample_fee": D.pick(R, [0, 200, 500]),
            "valid_until": f"{BASE_DATE + timedelta(days=30)}",
            "status": D.pick(R, ["草稿", "待审", "已发", "已接受", "已拒绝"]),
        })
    opportunity_by_no = {o["opportunity_id"]: o for o in opportunities}
    quotation_by_no = {q["quotation_id"]: q for q in quotations}

    # 销售订单（SO-）
    so_status = ["已下单", "备货中", "已发货", "已收货", "已关闭"]
    sales_orders: list[dict] = []
    so_specs = [
        ("SO202607001", "DLR-01", "SKU-ZB-G001", 12000, 5.50, "已发货"),
        ("SO202607002", "DLR-03", "SKU-ZB-M001", 8000, 9.90, "备货中"),
        ("SO202607003", "KA-01", "SKU-ZB-G001", 30000, 5.20, "已下单"),
        ("SO202607004", "KA-02", "SKU-ZB-B001", 3000, 27.00, "已发货"),
        ("SO202607005", "DLR-08", "SKU-ZB-H001", 10000, 6.80, "已收货"),
        ("SO202607006", "EC-30", "SKU-ZB-G010", 6000, 7.20, "备货中"),
        ("SO202607007", "DLR-01", "SKU-ZB-R001", 15000, 2.80, "已发货"),
        ("SO202607008", "EXP-01", "SKU-ZB-G001", 20000, 0.78, "已下单"),  # USD
    ]
    for so_no, cust_code, pcode, qty, unit_price, status in so_specs:
        cust = customer_by_code[cust_code]
        sales_orders.append({
            "so_no": so_no, "customer_code": cust_code, "customer_name": cust["name"],
            "product_code": pcode, "qty": qty, "unit_price": unit_price,
            "currency": cust["currency"], "status": status,
            "delivery_date": f"{BASE_DATE + timedelta(days=D.randint(R, 3, 30))}",
        })

    follow_ups: list[dict] = []
    for i in range(12):
        cust = D.pick(R, customers)
        opp = D.pick(R, opportunities)
        follow_ups.append({
            "followup_id": f"ASFU{D.pad(20260000 + i * 19)}",
            "customer_code": cust["code"], "opportunity_id": opp["opportunity_id"],
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 14))}T{D.pad(D.randint(R, 9, 18), 2)}:00:00",
            "method": D.pick(R, ["电话", "拜访", "邮件", "微信", "线上对接"]),
            "owner": cust["owner"],
            "content": D.pick(R, [
                "华东经销商确认 中性笔 开学季备货，需锁定进口到货",
                "政企集采招标确认主推 中性笔 + 记号笔 组合方案",
                "电商大促 中性笔 新品备货，确认投放与库存",
                "KA 连锁要求提供防伪溯源与批次证明",
                "对账确认上月发货明细，已开具增值税专用发票",
                "海外出口询价 中性笔，确认 FOB 报价与船期",
            ]),
            "next_action": D.pick(R, ["确认备货", "更新报价", "提供防伪证明", "跟进回款", "锁定船期"]),
        })

    # 售后工单 / 客诉（CASE-，跨系统联动 PIM 产品反馈 FB + ERP 出库 so_no）
    complaint_specs = [
        # (cid, cno, customer_code, product_code, batch, defect, sev, status, off, ctype, claim_qty)
        ("CASE-0001", "CR-AS-2026-0001", "DLR-01", "SKU-ZB-G001", "BAT202607001",
         "首笔不出墨", "一般", "处理中", -6, "quality", 120),
        ("CASE-0002", "CR-AS-2026-0002", "KA-02", "SKU-ZB-B001", "BAT202607002",
         "笔夹松动脱落", "严重", "8D 进行中", -5, "quality", 35),
        ("CASE-0003", "CR-AS-2026-0003", "DLR-03", "SKU-ZB-M001", "BAT202607003",
         "墨水偏淡", "一般", "处理中", -4, "quality", 80),
        ("CASE-0004", "CR-AS-2026-0004", "DLR-08", "SKU-ZB-G010", "BAT202607005",
         "书写刮纸", "一般", "处理中", -3, "quality", 60),
        ("CASE-0005", "CR-AS-2026-0005", "DLR-01", "SKU-ZB-G001", "BAT202607001",
         "运输破损补发", "一般", "已闭环", -8, "logistics", 200),
        ("CASE-0006", "CR-AS-2026-0006", "KA-01", "SKU-ZB-G001", "BAT202607001",
         "整批笔尖偏磨出墨不均", "严重", "8D 进行中", -4, "quality", 500),
        ("CASE-0007", "CR-AS-2026-0007", "EC-30", "SKU-ZB-G010", "BAT202607005",
         "错发色号", "一般", "已闭环", -2, "service", 40),
    ]
    complaints: list[dict] = []
    for cid, cno, cust_code, pcode, batch, defect, sev, status, off, ctype, claim_qty in complaint_specs:
        cust = customer_by_code[cust_code]
        unit = {"SKU-ZB-G001": 5.50, "SKU-ZB-B001": 28.00, "SKU-ZB-M001": 9.90,
                "SKU-ZB-G010": 7.20, "SKU-ZB-H001": 6.80, "SKU-ZB-R001": 2.80}.get(pcode, 5.0)
        complaints.append({
            "complaint_id": cid, "complaint_no": cno,
            "customer_code": cust_code, "customer_name": cust["name"],
            "product_code": pcode, "batch_no": batch,
            "work_order_no": None,  # 文具无 MES 工单；批次号在 batch_no
            "defect": defect, "defect_type": defect, "type": ctype,
            "severity": sev, "claim_qty": claim_qty,
            "claim_amount": round(claim_qty * unit, 2), "status": status,
            "reported_at": f"{BASE_DATE + timedelta(days=off)}",
            "owner": D.pick(R, ["客服-夏", "售后-陈", "质量-周", "电商-林"]),
        })
    complaint_by_no = {c["complaint_id"]: c for c in complaints}

    # 应收（REC-，invoice_no 与 CST 销项发票 INV- 对齐；含 2 条逾期）
    receivable_specs = [
        (1, "DLR-01", "SO202607001", 66000.00, "INV202607005", -20, 5),    # 未到期（对齐 CST 销项发票 + 凭证 BV-AS-2026-0710）
        (2, "DLR-03", "SO202607002", 79200.00, "INV202607010", -18, -3),   # 逾期
        (3, "KA-01", "SO202607003", 156000.00, "INV202607011", -15, 25),
        (4, "KA-02", "SO202607004", 81000.00, "INV202607012", -12, -1),    # 逾期
        (5, "DLR-08", "SO202607005", 68000.00, "INV202607013", -10, 30),
        (6, "EC-30", "SO202607006", 43200.00, "INV202607014", -8, 35),
        (7, "DLR-01", "SO202607007", 42000.00, "INV202607015", -6, 40),
    ]
    receivables: list[dict] = []
    for suffix, cust_code, so_no, amt, inv_no, b_off, d_off in receivable_specs:
        cust = customer_by_code[cust_code]
        due = BASE_DATE + timedelta(days=d_off)
        overdue = (BASE_DATE - due).days > 0
        receivables.append({
            "receivable_id": f"ASAR{D.pad(20260000 + suffix * 13)}",
            "customer_code": cust_code, "customer_name": cust["name"],
            "so_no": so_no, "invoice_no": inv_no,
            "amount": amt, "currency": cust["currency"],
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已收款"]),
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    return CrmData(
        customers=customers, customer_by_code=customer_by_code, contacts=contacts,
        opportunities=opportunities, opportunity_by_no=opportunity_by_no,
        quotations=quotations, quotation_by_no=quotation_by_no,
        sales_orders=sales_orders, follow_ups=follow_ups,
        complaints=complaints, complaint_by_no=complaint_by_no,
        receivables=receivables,
    )


def _build_starexploration() -> CrmData:
    """星途勘探客户与投标口径：工程业主/投资方(CLI-) + 投标商机(OPP-) + 投标报价(QT-) +
    中标合同(CT-SE-，client_code 与 EPC project.client_code 对齐，product_code 承载项目号
    PRJ-) + 履约争议(DSP-，对应 complaints 字段，支撑合同审查/履约风险) + 工程回款(REC-，
    invoice_no 与 ERP 应付/凭证 INV-/BV-SE- 按 invoice_no 对齐)。"""
    R = D.rng(20260723)

    customers = [
        {"code": "CLI-001", "name": "湖南电工装备集团", "type": "工业业主", "industry": "电工装备制造",
         "region": "华中", "credit_grade": "A", "payment_terms_days": 60, "currency": "CNY",
         "owner": "陈投标", "address": "湖南省长沙市"},
        {"code": "CLI-002", "name": "江苏恒力新能源", "type": "工业业主", "industry": "锂离子电池",
         "region": "华东", "credit_grade": "A", "payment_terms_days": 90, "currency": "CNY",
         "owner": "林客户", "address": "江苏省常州市"},
        {"code": "CLI-003", "name": "合肥滨湖城投", "type": "市政业主", "industry": "市政水务",
         "region": "华东", "credit_grade": "A", "payment_terms_days": 60, "currency": "CNY",
         "owner": "周投标", "address": "安徽省合肥市"},
        {"code": "CLI-004", "name": "长沙经开投资", "type": "园区业主", "industry": "园区开发",
         "region": "华中", "credit_grade": "B", "payment_terms_days": 45, "currency": "CNY",
         "owner": "陈投标", "address": "湖南省长沙市"},
        {"code": "CLI-005", "name": "国机集团总部", "type": "集团内业主", "industry": "综合工程",
         "region": "全国", "credit_grade": "A", "payment_terms_days": 60, "currency": "CNY",
         "owner": "林客户", "address": "北京市"},
    ]
    customer_by_code = {c["code"]: c for c in customers}

    contacts: list[dict] = []
    for c in customers:
        n = D.randint(R, 1, 3)
        for i in range(n):
            contacts.append({
                "contact_id": f"SECT{D.pad(D.randint(R, 1000, 9999))}",
                "customer_code": c["code"],
                "name": D.pick(R, ["沈雯", "韩雪", "江涛", "夏琳", "范琦", "蔡伟", "陶然", "宋媛"]),
                "title": D.pick(R, ["项目总监", "工程部经理", "采购经理", "投资总监", "技经主管"]),
                "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
                "email": f"contact{i}@{c['code'].lower()}.example",
                "decision_role": D.pick(R, ["决策者", "影响者", "使用者", "把关者"]),
            })

    # 项目号（与 EPC PRJ- / DES SCH- 对齐）
    project_codes = ["PRJ-IND-001", "PRJ-BAT-001", "PRJ-CIV-001"]
    stages = ["跟踪", "投标", "评标", "中标", "签约", "落标"]
    sources = ["公开招标", "邀请招标", "集团内委", "老客户续标", "设计前置"]

    opportunities: list[dict] = []
    quotations: list[dict] = []
    for i, (cust, project) in enumerate([(customers[0], project_codes[0]),
                                         (customers[1], project_codes[1]),
                                         (customers[2], project_codes[2]),
                                         (customers[3], project_codes[0]),
                                         (customers[4], project_codes[1])]):
        stage = D.pick(R, stages)
        amount = D.randint(R, 5_000_000, 95_000_000)
        oid = f"SEOPP{D.pad(20260000 + i * 43 + 11)}"
        opportunities.append({
            "opportunity_id": oid, "customer_code": cust["code"], "customer_name": cust["name"],
            "product_code": project, "stage": stage, "amount": amount,
            "currency": cust["currency"], "owner": cust["owner"],
            "source": D.pick(R, sources),
            "expected_close": f"{BASE_DATE + timedelta(days=D.randint(R, -30, 90))}",
        })
        qid = f"SEQT{D.pad(20260000 + i * 29 + 7)}"
        quotations.append({
            "quotation_id": qid, "opportunity_id": oid, "customer_code": cust["code"],
            "product_code": project, "customer_part_no": f"{cust['code']}-{project[-3:]}",
            "currency": cust["currency"],
            "tiers": [{"min_qty": 1, "unit_price": amount}],
            "mold_fee": 0, "sample_fee": 0,
            "valid_until": f"{BASE_DATE + timedelta(days=30)}",
            "status": D.pick(R, ["草稿", "待审", "已发", "已接受", "已拒绝"]),
        })
    opportunity_by_no = {o["opportunity_id"]: o for o in opportunities}
    quotation_by_no = {q["quotation_id"]: q for q in quotations}

    # 中标合同（CT-SE-，client_code 与 EPC project.client_code 对齐，product_code 承载项目号）
    sales_orders: list[dict] = []
    contract_specs = [
        ("CT-SE-001", "CLI-001", "PRJ-IND-001", 18500_0000, "履约中", "陈投标",
         ["付款里程碑偏紧", "保密条款需强化"], "设计院 SEOF0207"),
        ("CT-SE-002", "CLI-002", "PRJ-BAT-001", 92000_0000, "履约中", "林客户",
         ["涉密工艺参数保密", "付款里程碑风险点 2 处"], "设计院 SEOF0218"),
        ("CT-SE-003", "CLI-003", "PRJ-CIV-001", 31500_0000, "前期", "周投标",
         ["变更签证条款待细化"], "设计院 SEOF0209"),
    ]
    for so_no, cust_code, pcode, amt, status, owner, risk_flags, signer in contract_specs:
        cust = customer_by_code[cust_code]
        sales_orders.append({
            "so_no": so_no, "customer_code": cust_code, "customer_name": cust["name"],
            "product_code": pcode, "qty": 1, "unit_price": amt,
            "currency": cust["currency"], "status": status,
            "delivery_date": f"{BASE_DATE + timedelta(days=D.randint(R, 180, 540))}",
            "contract_amount": amt, "signer": signer, "owner": owner,
            "risk_flags": risk_flags,
            "payment_milestones": "预付款30%+进度款40%+竣工20%+质保金10%",
            "confidential": so_no in ("CT-SE-002",),
            "client_code": so_no,  # 与 EPC project.client_code 对齐
        })

    follow_ups: list[dict] = []
    for i in range(10):
        cust = D.pick(R, customers)
        opp = D.pick(R, opportunities)
        follow_ups.append({
            "followup_id": f"SEFU{D.pad(20260000 + i * 19)}",
            "customer_code": cust["code"], "opportunity_id": opp["opportunity_id"],
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 14))}T{D.pad(D.randint(R, 9, 18), 2)}:00:00",
            "method": D.pick(R, ["电话", "拜访", "邮件", "微信", "线上对接"]),
            "owner": cust["owner"],
            "content": D.pick(R, [
                "电工装备厂房 EPC 投标，确认资质与业绩要求",
                "电池工厂业主确认工艺参数保密要求，需签订保密协议",
                "市政水厂可研评审，业主关注出水水质与工期",
                "园区业主邀请参加设计前置咨询，争取绑定 EPC",
                "集团内委项目，确认设计交底与图纸交付节点",
            ]),
            "next_action": D.pick(R, ["确认投标", "更新报价", "签订保密协议", "跟进回款", "准备交底"]),
        })

    # 履约争议 / 纠纷（DSP-，对应 complaints 字段，支撑 LEG-01 合同审查/履约风险）
    complaint_specs = [
        ("DSP-0001", "CR-SE-2026-0001", "CLI-001", "PRJ-IND-001", "BAT202607001",
         "进度款支付里程碑争议", "一般", "处理中", -6, "contract", 0),
        ("DSP-0002", "CR-SE-2026-0002", "CLI-002", "PRJ-BAT-001", "BAT202607002",
         "设计变更签证费用分歧", "严重", "8D 进行中", -5, "contract", 0),
        ("DSP-0003", "CR-SE-2026-0003", "CLI-003", "PRJ-CIV-001", "BAT202607003",
         "地质条件变化引发工期顺延争议", "一般", "处理中", -4, "contract", 0),
        ("DSP-0004", "CR-SE-2026-0004", "CLI-001", "PRJ-IND-001", "BAT202607001",
         "质保金返还节点争议", "一般", "已闭环", -8, "contract", 0),
    ]
    complaints: list[dict] = []
    for cid, cno, cust_code, pcode, batch, defect, sev, status, off, ctype, claim_qty in complaint_specs:
        cust = customer_by_code[cust_code]
        complaints.append({
            "complaint_id": cid, "complaint_no": cno,
            "customer_code": cust_code, "customer_name": cust["name"],
            "product_code": pcode, "batch_no": batch,
            "work_order_no": None,
            "defect": defect, "defect_type": defect, "type": ctype,
            "severity": sev, "claim_qty": claim_qty,
            "claim_amount": 0.0, "status": status,
            "reported_at": f"{BASE_DATE + timedelta(days=off)}",
            "owner": D.pick(R, ["法务-陈", "合同-周", "项目-林", "技经-夏"]),
        })
    complaint_by_no = {c["complaint_id"]: c for c in complaints}

    # 工程回款（REC-，invoice_no 与 ERP 应付/凭证 INV-/BV-SE- 按 invoice_no 对齐；含逾期）
    receivable_specs = [
        (1, "CLI-001", "CT-SE-001", 5550000.00, "INV202607001", -20, 5),    # 对齐 ERP BV-SE-2026-0701
        (2, "CLI-002", "CT-SE-002", 27600000.00, "INV202607002", -18, -3), # 逾期，对齐 BV-SE-2026-0702
        (3, "CLI-003", "CT-SE-003", 9450000.00, "INV202607003", -15, 25),   # 对齐 BV-SE-2026-0703
        (4, "CLI-001", "CT-SE-001", 3700000.00, "INV202607004", -12, -1),   # 逾期，对齐 BV-SE-2026-0704
        (5, "CLI-002", "CT-SE-002", 9200000.00, "INV202607005", -8, 35),    # 对齐 BV-SE-2026-0710 合同进度款
        (6, "CLI-004", "CT-SE-001", 8300000.00, "INV202607006", -6, 40),
    ]
    receivables: list[dict] = []
    for suffix, cust_code, so_no, amt, inv_no, b_off, d_off in receivable_specs:
        cust = customer_by_code[cust_code]
        due = BASE_DATE + timedelta(days=d_off)
        overdue = (BASE_DATE - due).days > 0
        receivables.append({
            "receivable_id": f"SEAR{D.pad(20260000 + suffix * 13)}",
            "customer_code": cust_code, "customer_name": cust["name"],
            "so_no": so_no, "invoice_no": inv_no,
            "amount": amt, "currency": cust["currency"],
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已收款"]),
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    return CrmData(
        customers=customers, customer_by_code=customer_by_code, contacts=contacts,
        opportunities=opportunities, opportunity_by_no=opportunity_by_no,
        quotations=quotations, quotation_by_no=quotation_by_no,
        sales_orders=sales_orders, follow_ups=follow_ups,
        complaints=complaints, complaint_by_no=complaint_by_no,
        receivables=receivables,
    )


def _build_starhma() -> CrmData:
    """星途热熔胶客户与销售口径：六大赛道企业客户（CLI-，汽车内饰/医疗/食品包装/
    物流快递袋/鞋材箱包/家居）+ 询盘商机（INQ-，带基材/温度/环保/剥离力等工况需求，
    支撑智能询盘助手）+ 报价（QT-，联动 FRM 配方 FORM- 与 ERP 成品胶 M-FG-）+
    合同（CT-HMA-，so_no 与 ERP 生产成本 work_order_no 对齐）+ 履约争议（complaints，
    DSP-HMA-）+ 回款（AR-，invoice_no 与 ERP 应付/凭证 INV-/BV-HMA- 对齐）。"""
    R = D.rng(20260725)

    customers = [
        {"code": "CLI-001", "name": "某汽车零部件制造有限公司", "type": "终端", "industry": "汽车内饰",
         "region": "华东", "credit_grade": "A", "payment_terms_days": 60, "currency": "CNY",
         "owner": "陈销售", "address": "江苏省苏州市"},
        {"code": "CLI-002", "name": "某医疗耗材科技有限公司", "type": "终端", "industry": "医疗用品",
         "region": "华中", "credit_grade": "A", "payment_terms_days": 45, "currency": "CNY",
         "owner": "林外贸", "address": "湖北省武汉市"},
        {"code": "CLI-003", "name": "某鞋材箱包有限公司", "type": "终端", "industry": "鞋材箱包",
         "region": "华南", "credit_grade": "B", "payment_terms_days": 30, "currency": "CNY",
         "owner": "陈销售", "address": "广东省东莞市"},
        {"code": "CLI-004", "name": "某食品包装材料厂", "type": "终端", "industry": "食品日化包装",
         "region": "华东", "credit_grade": "A", "payment_terms_days": 45, "currency": "CNY",
         "owner": "林外贸", "address": "浙江省杭州市"},
        {"code": "CLI-005", "name": "某物流快递包装制品公司", "type": "终端", "industry": "物流快递袋",
         "region": "华北", "credit_grade": "B", "payment_terms_days": 30, "currency": "CNY",
         "owner": "王内销", "address": "北京市大兴区"},
    ]
    customer_by_code = {c["code"]: c for c in customers}

    contacts: list[dict] = []
    for c in customers:
        for i in range(D.randint(R, 1, 2)):
            contacts.append({
                "contact_id": f"HMACT{D.pad(D.randint(R, 1000, 9999))}",
                "customer_code": c["code"],
                "name": D.pick(R, ["沈雯", "韩雪", "江涛", "夏琳", "范琦", "蔡伟", "陶然"]),
                "title": D.pick(R, ["采购经理", "技术主管", "工艺工程师", "研发经理"]),
                "phone": f"1{D.randint(R, 30, 89)}{D.randint(R, 10000000, 99999999)}",
                "email": f"contact{i}@{c['code'].lower()}.example",
                "decision_role": D.pick(R, ["决策者", "影响者", "使用者", "把关者"]),
            })

    # 询盘商机（INQ-，带工况需求字段，支撑智能询盘助手匹配 FRM 配方）
    opp_specs = [
        ("INQ-001", "CLI-001", "汽车内饰", "PET 植绒布/ABS", "180℃", 12, 28, ["REACH", "SGS"],
         "FORM-CUS-001", 5, 30000, "跟踪"),
        ("INQ-002", "CLI-002", "医疗用品", "无纺布/PE 膜", "130℃", 6, 14, ["FDA", "ISO-10993"],
         "FORM-CUS-002", 8, 15000, "报价中"),
        ("INQ-003", "CLI-003", "鞋材箱包", "EVA/PU 革", "120℃", 9, 20, ["REACH"],
         "FORM-CUS-003", 3, 20000, "送样"),
        ("INQ-004", "CLI-004", "食品日化包装", "PET/铝箔", "150℃", 10, 16, ["FDA", "REACH", "SGS"],
         "FORM-STD-003", 1, 25000, "跟踪"),
        ("INQ-005", "CLI-005", "物流快递袋", "BOPP/CPE 复合膜", "170℃", 5, 22, ["REACH"],
         "FORM-STD-002", 1, 40000, "报价中"),
    ]
    opportunities: list[dict] = []
    quotations: list[dict] = []
    for oid, cust_code, industry, substrate, app_temp, open_t, peel, env_std, formula, stage_idx, qty, stage in opp_specs:
        cust = customer_by_code[cust_code]
        amount = qty * 25 * 100  # 单价粗估
        opportunities.append({
            "opportunity_id": oid, "customer_code": cust_code, "customer_name": cust["name"],
            "product_code": formula, "stage": stage,
            "amount": amount, "currency": cust["currency"], "owner": cust["owner"],
            "source": D.pick(R, ["主动询盘", "老客户复购", "展会线索", "外贸询盘", "内销拓展"]),
            "expected_close": f"{BASE_DATE + timedelta(days=D.randint(R, 10, 60))}",
            # 询盘工况需求（智能询盘助手解析字段）
            "inquiry_industry": industry, "inquiry_substrate": substrate,
            "inquiry_application_temp": app_temp, "inquiry_open_time_sec": open_t,
            "inquiry_peel_strength_N": peel, "inquiry_env_std": env_std,
            "inquiry_qty_kg": qty,
            "matched_formula": formula,
        })
        quotations.append({
            "quotation_id": f"HMAQT{D.pad(20260000 + opp_specs.index((oid, cust_code, industry, substrate, app_temp, open_t, peel, env_std, formula, stage_idx, qty, stage)) * 29 + 7)}",
            "opportunity_id": oid, "customer_code": cust_code,
            "product_code": formula, "customer_part_no": f"{cust_code}-{formula[-3:]}",
            "currency": cust["currency"],
            "tiers": [{"min_qty": qty, "unit_price": 25.0}],
            "mold_fee": 0, "sample_fee": 500,
            "valid_until": f"{BASE_DATE + timedelta(days=30)}",
            "status": D.pick(R, ["草稿", "待审", "已发", "已接受"]),
        })
    opportunity_by_no = {o["opportunity_id"]: o for o in opportunities}
    quotation_by_no = {q["quotation_id"]: q for q in quotations}

    # 合同（CT-HMA-，so_no 与 ERP 生产成本 work_order_no 对齐）
    contract_specs = [
        ("CT-HMA-001", "CLI-001", "FORM-CUS-001", 750000.0, "履约中", "陈销售",
         ["付款里程碑偏紧", "高温耐温复测节点"], "技销-陈", "M-FG-001"),
        ("CT-HMA-002", "CLI-002", "FORM-CUS-002", 375000.0, "履约中", "林外贸",
         ["医用 ISO-10993 资质留存", "低温适应性 -10℃ 复测"], "技销-林", "M-FG-003"),
        ("CT-HMA-003", "CLI-005", "FORM-STD-002", 840000.0, "履约中", "王内销",
         ["旺季交付能力保障", "堵枪客诉复测节点"], "销售-王", "M-FG-002"),
    ]
    sales_orders: list[dict] = []
    for so_no, cust_code, pcode, amt, status, owner, risk_flags, signer, fg_code in contract_specs:
        cust = customer_by_code[cust_code]
        sales_orders.append({
            "so_no": so_no, "customer_code": cust_code, "customer_name": cust["name"],
            "product_code": pcode, "qty": 30000, "unit_price": round(amt / 30000, 2),
            "currency": cust["currency"], "status": status,
            "delivery_date": f"{BASE_DATE + timedelta(days=D.randint(R, 30, 180))}",
            "contract_amount": amt, "signer": signer, "owner": owner,
            "risk_flags": risk_flags, "fg_code": fg_code,
            "payment_milestones": "预付款30%+发货款60%+质保金10%",
        })

    follow_ups: list[dict] = []
    for i, opp in enumerate(opportunities):
        follow_ups.append({
            "followup_id": f"HMAFU{D.pad(20260000 + i * 19)}",
            "customer_code": opp["customer_code"], "opportunity_id": opp["opportunity_id"],
            "at": f"{BASE_DATE - timedelta(days=D.randint(R, 0, 10))}T{D.pad(D.randint(R, 9, 18), 2)}:00:00",
            "method": D.pick(R, ["电话", "拜访", "邮件", "微信", "线上对接"]),
            "owner": opp["owner"],
            "content": D.pick(R, [
                f"{opp['inquiry_industry']}客户确认基材 {opp['inquiry_substrate']} 与施胶温度，需匹配配方",
                "客户要求寄送样品并安排现场工艺调试",
                "确认环保认证资料 FDA/REACH/SGS 齐全",
                "外贸客户多语种技术方案与报价翻译",
                "客户产线堵枪问题跟进，技术销售现场支持",
            ]),
            "next_action": D.pick(R, ["匹配配方", "寄样", "签订合同", "跟进回款", "现场调试"]),
        })

    # 履约争议（complaints，DSP-HMA-，区别于 QAS 售后粘接故障）
    complaint_specs = [
        ("DSP-HMA-001", "CR-HMA-2026-001", "CLI-001", "CT-HMA-001", "BAT-2026-0703",
         "高温耐温复测节点延期争议", "一般", "处理中", -6, "contract"),
        ("DSP-HMA-002", "CR-HMA-2026-002", "CLI-002", "CT-HMA-002", "BAT-2026-0704",
         "低温 -10℃ 适应性复测不通过引发争议", "严重", "8D 进行中", -2, "contract"),
        ("DSP-HMA-003", "CR-HMA-2026-003", "CLI-005", "CT-HMA-003", "BAT-2026-0702",
         "旺季交付延期与堵枪客诉连带争议", "一般", "处理中", -1, "contract"),
    ]
    complaints: list[dict] = []
    for cid, cno, cust_code, so_no, batch, defect, sev, status, off, ctype in complaint_specs:
        cust = customer_by_code[cust_code]
        complaints.append({
            "complaint_id": cid, "complaint_no": cno,
            "customer_code": cust_code, "customer_name": cust["name"],
            "product_code": so_no, "batch_no": batch, "work_order_no": None,
            "defect": defect, "defect_type": defect, "type": ctype,
            "severity": sev, "claim_qty": 0, "claim_amount": 0.0, "status": status,
            "reported_at": f"{BASE_DATE + timedelta(days=off)}",
            "owner": D.pick(R, ["法务-陈", "技销-林", "销售-王"]),
        })
    complaint_by_no = {c["complaint_id"]: c for c in complaints}

    # 回款（AR-，invoice_no 与 ERP 应付/凭证 INV-/BV-HMA- 对齐；含逾期）
    receivable_specs = [
        (1, "CLI-001", "CT-HMA-001", 225000.00, "INV202607001", -20, 5),    # 对齐 ERP BV-HMA-2026-0701
        (2, "CLI-002", "CT-HMA-002", 112500.00, "INV202607002", -18, -3),   # 逾期，对齐 BV-HMA-2026-0702
        (3, "CLI-005", "CT-HMA-003", 252000.00, "INV202607003", -15, 12),   # 对齐 BV-HMA-2026-0703
        (4, "CLI-001", "CT-HMA-001", 225000.00, "INV202607004", -12, -1),   # 逾期，对齐 BV-HMA-2026-0704
        (5, "CLI-004", "CT-HMA-001", 75000.00, "INV202607005", -8, 25),
    ]
    receivables: list[dict] = []
    for suffix, cust_code, so_no, amt, inv_no, b_off, d_off in receivable_specs:
        cust = customer_by_code[cust_code]
        due = BASE_DATE + timedelta(days=d_off)
        overdue = (BASE_DATE - due).days > 0
        receivables.append({
            "receivable_id": f"HMAAR{D.pad(20260000 + suffix * 13)}",
            "customer_code": cust_code, "customer_name": cust["name"],
            "so_no": so_no, "invoice_no": inv_no,
            "amount": amt, "currency": cust["currency"],
            "billing_date": f"{BASE_DATE + timedelta(days=b_off)}",
            "due_date": f"{due}",
            "status": "逾期" if overdue else D.pick(R, ["未到期", "未到期", "已收款"]),
            "days_overdue": max(0, (BASE_DATE - due).days),
        })

    return CrmData(
        customers=customers, customer_by_code=customer_by_code, contacts=contacts,
        opportunities=opportunities, opportunity_by_no=opportunity_by_no,
        quotations=quotations, quotation_by_no=quotation_by_no,
        sales_orders=sales_orders, follow_ups=follow_ups,
        complaints=complaints, complaint_by_no=complaint_by_no,
        receivables=receivables,
    )


# ───────────────────────── 多租户注册表（懒构建） ─────────────────────────


TENANTS = LazyTenantRegistry[CrmData]({
    "minrui": _build_minrui,
    "starclothing": _build_starclothing,
    "agileac": _build_agileac,
    "agilesteel": _build_agilesteel,
    "agilestationery": _build_agilestationery,
    "starexploration": _build_starexploration,
    "starhma": _build_starhma,
})


def load(tenant: str) -> CrmData:
    """按 tenant 取数据集；首次调用时触发构建并缓存。"""
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 向后兼容：模块级别名（默认 minrui，供跨系统延迟导入与未改造调用方） ──
_minrui = TENANTS["minrui"]
CUSTOMERS = _minrui.customers
CUSTOMER_BY_CODE = _minrui.customer_by_code
CONTACTS = _minrui.contacts
OPPORTUNITIES = _minrui.opportunities
OPP_BY_ID = _minrui.opportunity_by_no
QUOTATIONS = _minrui.quotations
QUOT_BY_ID = _minrui.quotation_by_no
SALES_ORDERS = _minrui.sales_orders
FOLLOWUPS = _minrui.follow_ups
COMPLAINTS = _minrui.complaints
COMPLAINT_BY_ID = _minrui.complaint_by_no
RECEIVABLES = _minrui.receivables
