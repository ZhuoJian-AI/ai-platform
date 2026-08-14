"""CST 多租户确定性种子数据——agilestationery（敏睿文具，报关与单证）。

CST 是叶系统，无循环依赖，沿用懒构建。``agilestationery`` 一份 ``CstData``，覆盖
进出口报关单（CD-，关联 ERP 采购单 PO-）+ HS 商品归类（HS-）+ 发票（INV-，关联
ERP 凭证 BV-）+ 汇率（FX-）+ 合规校验记录。

标识符：报关单 ``CD-``、HS 归类 ``HS-``、发票 ``INV-``、汇率 ``FX-``。
报关单 ``CD-`` 引用 ERP 采购单 ``PO-``（按 po_no 关联，勿直传）；发票 ``INV-`` 与
ERP 凭证 ``BV-`` 按 invoice_no 关联（不同码空间，identifiers.md 显式消歧）。
"""

from __future__ import annotations

from dataclasses import dataclass

from mock.core import data as D
from mock.core.tenant import LazyTenantRegistry

BASE_DATE = "2026-07-14"


@dataclass
class CstData:
    declarations: list[dict]               # 进出口报关单
    declaration_by_no: dict[str, dict]
    hs_codes: list[dict]                   # HS 商品归类
    hs_by_code: dict[str, dict]
    invoices: list[dict]                   # 发票（识别/验真）
    invoice_by_no: dict[str, dict]
    exchange_rates: list[dict]             # 汇率
    compliance_checks: list[dict]          # 合规校验记录


# ───────────────────────── agilestationery（敏睿文具） ─────────────────────────


def _build_agilestationery() -> CstData:
    """敏睿文具报关与单证口径：进口报关单 + HS 归类 + 发票验真 + 汇率 + 合规校验。"""
    R = D.rng(20260715)

    hs_codes = [
        {"hs_code": "HS-960810", "name": "圆珠笔", "category": "书写工具",
         "unit": "支", "import_rate_pct": 14.0, "vat_pct": 13.0,
         "regulation": "需提供原产地证，日本原产可享优惠税率"},
        {"hs_code": "HS-960820", "name": "其他笔（中性笔/记号笔等）", "category": "书写工具",
         "unit": "支", "import_rate_pct": 14.0, "vat_pct": 13.0,
         "regulation": "按墨水类型与笔头结构归类，记号笔归 9608.20"},
        {"hs_code": "HS-960840", "name": "自来水钢笔等", "category": "书写工具",
         "unit": "支", "import_rate_pct": 14.0, "vat_pct": 13.0,
         "regulation": "特种笔类，需申报笔头材质"},
        {"hs_code": "HS-960860", "name": "笔芯", "category": "书写工具配件",
         "unit": "支", "import_rate_pct": 10.0, "vat_pct": 13.0,
         "regulation": "替换芯单独归类，需与整笔区分申报"},
        {"hs_code": "HS-960899", "name": "笔零件（笔夹/笔帽等）", "category": "书写工具配件",
         "unit": "千克", "import_rate_pct": 10.0, "vat_pct": 13.0,
         "regulation": "按重量申报的零件类"},
        {"hs_code": "HS-392610", "name": "塑料办公用品/包装", "category": "塑制品",
         "unit": "千克", "import_rate_pct": 8.0, "vat_pct": 13.0,
         "regulation": "文具塑料包装盒归此"},
    ]
    hs_by_code = {h["hs_code"]: h for h in hs_codes}

    # 进出口报关单（CD-，关联 ERP 采购单 PO-）
    declarations = [
        {"declaration_no": "CD202607001", "type": "进口", "po_no": "PO202607001",
         "supplier": "敏睿文具·日本进口品牌厂商", "origin_country": "日本",
         "port": "上海浦东国际机场", "hs_code": "HS-960820", "product_desc": "敏睿中性笔 中性笔",
         "qty": 120000, "uom": "支", "amount_jpy": 3360000, "amount_cny": 161280.0,
         "exchange_rate": 0.048, "freight_cny": 4200.0, "insurance_cny": 380.0,
         "status": "已申报", "declared_at": "2026-07-05T10:00:00",
         "expected_clear": "2026-07-09", "customs_broker": "上海外代报关行"},
        {"declaration_no": "CD202607002", "type": "进口", "po_no": "PO202607002",
         "supplier": "敏睿文具·日本进口品牌厂商", "origin_country": "日本",
         "port": "上海浦东国际机场", "hs_code": "HS-960810", "product_desc": "敏睿金属圆珠笔",
         "qty": 20000, "uom": "支", "amount_jpy": 250000, "amount_cny": 12000.0,
         "exchange_rate": 0.048, "freight_cny": 1500.0, "insurance_cny": 120.0,
         "status": "查验中", "declared_at": "2026-07-08T09:30:00",
         "expected_clear": "2026-07-13", "customs_broker": "上海外代报关行"},
        {"declaration_no": "CD202607003", "type": "进口", "po_no": "PO202607003",
         "supplier": "敏睿文具·日本进口品牌厂商", "origin_country": "日本",
         "port": "深圳盐田港", "hs_code": "HS-960820", "product_desc": "敏睿油性记号笔",
         "qty": 80000, "uom": "支", "amount_jpy": 336000, "amount_cny": 16128.0,
         "exchange_rate": 0.048, "freight_cny": 2800.0, "insurance_cny": 220.0,
         "status": "已放行", "declared_at": "2026-07-02T14:00:00",
         "expected_clear": "2026-07-06", "customs_broker": "深圳关贸报关行"},
        {"declaration_no": "CD202607004", "type": "进口", "po_no": "PO202607004",
         "supplier": "敏睿文具·日本进口品牌厂商", "origin_country": "日本",
         "port": "上海浦东国际机场", "hs_code": "HS-960860", "product_desc": "敏睿中性笔 替换芯",
         "qty": 100000, "uom": "支", "amount_jpy": 120000, "amount_cny": 5760.0,
         "exchange_rate": 0.048, "freight_cny": 980.0, "insurance_cny": 60.0,
         "status": "已申报", "declared_at": "2026-07-10T11:00:00",
         "expected_clear": "2026-07-14", "customs_broker": "上海外代报关行"},
        {"declaration_no": "CD202607005", "type": "进口", "po_no": "PO202607005",
         "supplier": "敏睿文具·日本进口品牌厂商", "origin_country": "日本",
         "port": "上海浦东国际机场", "hs_code": "HS-960820", "product_desc": "敏睿中性笔 Clip 中性笔 0.4",
         "qty": 60000, "uom": "支", "amount_jpy": 210000, "amount_cny": 10080.0,
         "exchange_rate": 0.048, "freight_cny": 1900.0, "insurance_cny": 150.0,
         "status": "异常-归类存疑", "declared_at": "2026-07-11T15:00:00",
         "expected_clear": "2026-07-18", "customs_broker": "上海外代报关行"},
        {"declaration_no": "CD202606020", "type": "进口", "po_no": "PO202606020",
         "supplier": "敏睿文具·日本进口品牌厂商", "origin_country": "日本",
         "port": "深圳盐田港", "hs_code": "HS-392610", "product_desc": "文具塑料包装盒",
         "qty": 5000, "uom": "千克", "amount_jpy": 250000, "amount_cny": 12000.0,
         "exchange_rate": 0.048, "freight_cny": 2600.0, "insurance_cny": 180.0,
         "status": "已放行", "declared_at": "2026-06-25T09:00:00",
         "expected_clear": "2026-06-29", "customs_broker": "深圳关贸报关行"},
    ]
    declaration_by_no = {d["declaration_no"]: d for d in declarations}

    # 发票（INV-，关联 ERP 凭证 BV-）
    invoices = [
        {"invoice_no": "INV202607001", "type": "增值税专用发票", "direction": "进项",
         "supplier": "敏睿文具·日本进口品牌厂商", "buyer": "敏睿文具贸易（中国）有限公司",
         "amount": 161280.00, "tax": 20966.40, "total_with_tax": 182246.40,
         "voucher_no": "BV-AS-2026-0701", "tax_rate_pct": 13.0,
         "issued_at": "2026-07-05", "verified": True, "status": "已验真入账",
         "matched_declaration": "CD202607001"},
        {"invoice_no": "INV202607002", "type": "增值税专用发票", "direction": "进项",
         "supplier": "上海外代报关行", "buyer": "敏睿文具贸易（中国）有限公司",
         "amount": 4200.00, "tax": 252.00, "total_with_tax": 4452.00,
         "voucher_no": "BV-AS-2026-0702", "tax_rate_pct": 6.0,
         "issued_at": "2026-07-06", "verified": True, "status": "已验真入账",
         "matched_declaration": "CD202607001"},
        {"invoice_no": "INV202607003", "type": "增值税专用发票", "direction": "进项",
         "supplier": "敏睿文具·日本进口品牌厂商", "buyer": "敏睿文具贸易（中国）有限公司",
         "amount": 16128.00, "tax": 2096.64, "total_with_tax": 18224.64,
         "voucher_no": "BV-AS-2026-0703", "tax_rate_pct": 13.0,
         "issued_at": "2026-07-03", "verified": True, "status": "已验真入账",
         "matched_declaration": "CD202607003"},
        {"invoice_no": "INV202607004", "type": "增值税普通发票", "direction": "进项",
         "supplier": "深圳关贸报关行", "buyer": "敏睿文具贸易（中国）有限公司",
         "amount": 2800.00, "tax": 168.00, "total_with_tax": 2968.00,
         "voucher_no": None, "tax_rate_pct": 6.0,
         "issued_at": "2026-07-04", "verified": False, "status": "待验真",
         "matched_declaration": "CD202607003"},
        {"invoice_no": "INV202607005", "type": "增值税专用发票", "direction": "销项",
         "supplier": "敏睿文具贸易（中国）有限公司", "buyer": "华东文具经销商 DLR-01",
         "amount": 66000.00, "tax": 8580.00, "total_with_tax": 74580.00,
         "voucher_no": "BV-AS-2026-0710", "tax_rate_pct": 13.0,
         "issued_at": "2026-07-09", "verified": True, "status": "已验真入账",
         "matched_declaration": None},
        {"invoice_no": "INV202607006", "type": "增值税专用发票", "direction": "进项",
         "supplier": "深圳盐田港物流", "buyer": "敏睿文具贸易（中国）有限公司",
         "amount": 2600.00, "tax": 234.00, "total_with_tax": 2834.00,
         "voucher_no": "BV-AS-2026-0704", "tax_rate_pct": 9.0,
         "issued_at": "2026-06-26", "verified": True, "status": "已验真入账",
         "matched_declaration": "CD202606020"},
        {"invoice_no": "INV202607007", "type": "增值税专用发票", "direction": "进项",
         "supplier": "敏睿文具·日本进口品牌厂商", "buyer": "敏睿文具贸易（中国）有限公司",
         "amount": 12000.00, "tax": 1560.00, "total_with_tax": 13560.00,
         "voucher_no": None, "tax_rate_pct": 13.0,
         "issued_at": "2026-07-08", "verified": False, "status": "存疑-发票代码异常",
         "matched_declaration": "CD202607002"},
    ]
    invoice_by_no = {i["invoice_no"]: i for i in invoices}

    # 汇率（FX-，含波动预警因子）
    exchange_rates = [
        {"pair": "JPY/CNY", "rate": 0.0480, "trend_30d": "下行", "change_pct_30d": -1.8,
         "forecast": "日元走弱，建议锁定对日采购付款窗口", "as_of": "2026-07-14"},
        {"pair": "USD/CNY", "rate": 7.18, "trend_30d": "震荡", "change_pct_30d": 0.3,
         "forecast": "美元窄幅震荡，按需结汇", "as_of": "2026-07-14"},
        {"pair": "EUR/CNY", "rate": 7.82, "trend_30d": "上行", "change_pct_30d": 1.2,
         "forecast": "欧元走强，欧洲采购成本上升", "as_of": "2026-07-14"},
    ]

    # 合规校验记录
    compliance_checks = [
        {"check_no": "CST-CK-001", "declaration_no": "CD202607001", "check_type": "归类准确性",
         "result": "通过", "detail": "中性笔归 HS-960820 正确", "checked_at": "2026-07-05T11:00:00"},
        {"check_no": "CST-CK-002", "declaration_no": "CD202607002", "check_type": "单证完整性",
         "result": "异常", "detail": "缺原产地证，需补传", "checked_at": "2026-07-08T10:00:00"},
        {"check_no": "CST-CK-003", "declaration_no": "CD202607005", "check_type": "归类准确性",
         "result": "存疑", "detail": "中性笔 0.4 归 960820 与 960840 存疑，建议预归类确认",
         "checked_at": "2026-07-11T16:00:00"},
        {"check_no": "CST-CK-004", "declaration_no": "CD202607001", "check_type": "价格申报",
         "result": "通过", "detail": "成交价格在合理区间", "checked_at": "2026-07-05T11:30:00"},
        {"check_no": "CST-CK-005", "invoice_no": "INV202607007", "check_type": "发票合规",
         "result": "异常", "detail": "发票代码异常，疑似虚开，需停付重核", "checked_at": "2026-07-08T14:00:00"},
    ]

    return CstData(
        declarations=declarations, declaration_by_no=declaration_by_no,
        hs_codes=hs_codes, hs_by_code=hs_by_code,
        invoices=invoices, invoice_by_no=invoice_by_no,
        exchange_rates=exchange_rates, compliance_checks=compliance_checks,
    )


TENANTS = LazyTenantRegistry[CstData]({
    "agilestationery": _build_agilestationery,
})


def load(tenant: str) -> CstData:
    return TENANTS.load(tenant)


def all_tenant_ids() -> list[str]:
    return TENANTS.known_tenants()


# ── 派生量 ───────────────────────────────────────────────────

# 产品描述关键词 → HS 归类推荐（用于 recommendHsCode）
_HS_RULES = [
    {"keywords": ["圆珠笔", "金属圆珠笔", "细字圆珠笔"], "hs_code": "HS-960810", "reason": "圆珠笔归 9608.10.00"},
    {"keywords": ["中性笔", "中性笔", "中性笔", "凝胶"], "hs_code": "HS-960820",
     "reason": "中性笔属其他笔类，归 9608.20"},
    {"keywords": ["记号笔", "记号笔", "白板笔", "荧光笔"], "hs_code": "HS-960820",
     "reason": "记号笔/荧光笔归 9608.20（记号笔细分）"},
    {"keywords": ["笔芯", "替换芯", "替芯"], "hs_code": "HS-960860",
     "reason": "笔芯单独归类 9608.60，需与整笔区分申报"},
    {"keywords": ["笔夹", "笔帽", "笔杆", "零件"], "hs_code": "HS-960899",
     "reason": "笔零件按重量归 9608.99"},
    {"keywords": ["包装", "塑料盒", "包装盒"], "hs_code": "HS-392610",
     "reason": "塑料包装归 3926.10"},
]


def recommend_hs_code(tenant: str, product_desc: str) -> dict:
    """由产品描述 → HS 归类推荐（hs_code/税率/理由）。"""
    d = load(tenant)
    for rule in _HS_RULES:
        if any(k in product_desc for k in rule["keywords"]):
            hs = d.hs_by_code[rule["hs_code"]]
            return {"input": product_desc, "hs_code": hs["hs_code"], "name": hs["name"],
                    "import_rate_pct": hs["import_rate_pct"], "vat_pct": hs["vat_pct"],
                    "regulation": hs["regulation"], "reason": rule["reason"]}
    return {"input": product_desc, "hs_code": None, "name": None,
            "import_rate_pct": None, "vat_pct": None, "regulation": None,
            "reason": "无法自动归类，转人工确认（建议提供笔头结构/墨水类型）"}


def verify_invoice(tenant: str, invoice_no: str) -> dict:
    """发票验真（查验真伪/是否入账/关联凭证）。"""
    d = load(tenant)
    inv = d.invoice_by_no.get(invoice_no)
    if inv is None:
        return {"invoice_no": invoice_no, "exists": False, "verified": False,
                "status": "未找到", "detail": "发票号不在系统，疑似虚开或录错"}
    return {"invoice_no": invoice_no, "exists": True, "verified": inv["verified"],
            "status": inv["status"], "type": inv["type"], "direction": inv["direction"],
            "total_with_tax": inv["total_with_tax"], "tax_rate_pct": inv["tax_rate_pct"],
            "voucher_no": inv["voucher_no"], "matched_declaration": inv["matched_declaration"],
            "detail": ("已验真并入账" if inv["verified"] else "待验真/存疑，需人工复核")}


def check_compliance(tenant: str, declaration_no: str) -> dict:
    """报关单合规校验（归类/单证/价格/发票一致性，返回异常项与风险）。"""
    d = load(tenant)
    dec = d.declaration_by_no.get(declaration_no)
    if dec is None:
        return {"declaration_no": declaration_no, "exists": False, "issues": [],
                "risk_level": "未知", "detail": "报关单不存在"}
    issues = []
    for c in d.compliance_checks:
        if c.get("declaration_no") == declaration_no and c["result"] in ("异常", "存疑"):
            issues.append({"check_type": c["check_type"], "result": c["result"], "detail": c["detail"]})
    # 查验中/归类存疑状态自身即风险
    if dec["status"] in ("查验中", "异常-归类存疑"):
        issues.append({"check_type": "状态", "result": "存疑",
                        "detail": f"报关单状态为 {dec['status']}"})
    risk = "高" if len(issues) >= 2 else ("中" if len(issues) == 1 else "低")
    return {"declaration_no": declaration_no, "exists": True,
            "hs_code": dec["hs_code"], "product_desc": dec["product_desc"],
            "status": dec["status"], "issues": issues, "risk_level": risk,
            "detail": ("合规通过" if not issues else "存在合规风险，需处理上述异常项")}


def score_declaration_risk(tenant: str) -> list[dict]:
    """在途报关单风险打分（状态/归类存疑/单证异常/汇率敞口）。"""
    d = load(tenant)
    rows = []
    status_weight = {"异常-归类存疑": 1.0, "查验中": 0.6, "已申报": 0.3, "已放行": 0.1}
    for dec in d.declarations:
        if dec["status"] == "已放行":
            continue
        issue_cnt = sum(1 for c in d.compliance_checks
                        if c.get("declaration_no") == dec["declaration_no"]
                        and c["result"] in ("异常", "存疑"))
        score = round(status_weight.get(dec["status"], 0.2) * 60 + issue_cnt * 30, 2)
        rows.append({
            "declaration_no": dec["declaration_no"], "po_no": dec["po_no"],
            "product_desc": dec["product_desc"], "status": dec["status"],
            "issue_count": issue_cnt, "risk_score": score,
            "risk_level": "高" if score >= 70 else ("中" if score >= 40 else "低"),
        })
    rows.sort(key=lambda r: r["risk_score"], reverse=True)
    return rows
