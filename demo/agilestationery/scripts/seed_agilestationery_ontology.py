"""为「敏睿文具」组织创建本体文件（7 组织级域 + Cross）。

每个域 4 文件：README/object-types/link-types/action-types；ERP/CRM/SCM/HRM/PIM/CST/CHN
各含 identifiers.md（标识符约定 + 跨码空间映射规则）—— 防猜码 404 的 no-guessing 骨架。
沿用 agilesteel 的 render_identifiers_md + _files_for + _seed_scope 模式。

用法:
    docker cp demo/agilestationery/scripts/seed_agilestationery_ontology.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_agilestationery_ontology.py
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parent.parent
if not (_BACKEND_DIR / "app" / "database.py").exists():
    _BACKEND_DIR = _HERE.parents[3] / "llm_router" / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

import structlog  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.schemas.ontology import OntologyFileCreate  # noqa: E402
from app.services.ontology_store_service import create_folder, upsert_file  # noqa: E402

logger = structlog.get_logger()

ORG_SLUG = "agilestationery"
ORG_NAME_FALLBACK = "敏睿文具"


# ───────────────────────── 标识符约定（no-guessing 骨架） ─────────────────────────

ERP_IDENTIFIER_CONVENTIONS = [
    {"entity": "Material", "field": "material_code", "prefix": "M-ZB-", "example": "M-ZB-G001",
     "note": "文具物料（笔/本/文件夹等成品与原料；与 PIM 产品 SKU-ZB- 不同前缀，按 product_code/material_code 关联）"},
    {"entity": "PurchaseOrder", "field": "po_no", "prefix": "PO-", "example": "PO202607001", "note": "采购订单"},
    {"entity": "Payable", "field": "payable_id", "prefix": "ASAP", "example": "ASAP20260001", "note": "应付"},
    {"entity": "Voucher", "field": "voucher_no", "prefix": "BV-AS-", "example": "BV-AS-2026-0701",
     "note": "财务凭证（与 CST 发票 INV- 不同码空间，按 invoice_no/voucher_no 关联）"},
    {"entity": "CostCenter", "field": "cc_code", "prefix": "CC-ZB-", "example": "CC-ZB-EC-01",
     "note": "成本中心（与 HRM 员工 emp_no 对齐）"},
    {"entity": "ImportBatchCost", "field": "batch_id", "prefix": "BAT", "example": "BAT202607001", "note": "进口批次成本"},
]
ERP_CODE_SPACE_MAPPINGS = [
    {"from_field": "Material.material_code", "from_prefix": "M-ZB-", "to_field": "PIM.Product.product_code", "to_prefix": "SKU-ZB-",
     "rule": "ERP 物料 M-ZB- 与 PIM 产品 SKU-ZB- 不同前缀但同实体，按 product_code/material_code 关联：调 ERP listMaterials 收 M-ZB-，调 PIM getProduct 收 SKU-ZB-，勿直传",
     "example": "listMaterials(material_code='M-ZB-G001') vs getProduct(product_code='SKU-ZB-G001')（M-ZB-G001 ↔ SKU-ZB-G001）",
     "why": "杜绝把 M-ZB- 当 SKU-ZB- 传 PIM 端点 404"},
    {"from_field": "PurchaseOrder.po_no", "from_prefix": "PO-", "to_field": "CST.Declaration.po_no", "to_prefix": "CD-",
     "rule": "CST 报关单 CD-.po_no 字段引用 ERP 采购单 PO-，按 po_no 关联：调 ERP getPurchaseOrder(po_no=...) 直查，勿把 CD- 当 PO- 传 ERP",
     "example": "getDeclaration(declaration_no='CD202607001').po_no='PO202607001' → getPurchaseOrder(po_no='PO202607001')",
     "why": "报关单引用采购单，勿反向直传 CD 给 ERP"},
    {"from_field": "Voucher.voucher_no", "from_prefix": "BV-AS-", "to_field": "CST.Invoice.invoice_no", "to_prefix": "INV-",
     "rule": "ERP 凭证 BV-AS- 与 CST 发票 INV- 不同码空间，按 invoice_no/voucher_no 关联：调 ERP listVouchers 收 BV-AS-，调 CST getInvoice 收 INV-，勿互传",
     "example": "listVouchers(voucher_no='BV-AS-2026-0701') vs getInvoice(invoice_no='INV202607001')",
     "why": "凭证与发票不同码空间，直传必 404"},
]

CRM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Customer-Distributor", "field": "customer_code", "prefix": "DLR-", "example": "DLR-001",
     "note": "经销商客户（与 ERP 客户同码空间直查）"},
    {"entity": "Customer-KA", "field": "customer_code", "prefix": "KA-", "example": "KA-01", "note": "KA 大客户"},
    {"entity": "Customer-Ecommerce", "field": "customer_code", "prefix": "EC-", "example": "EC-09", "note": "电商客户"},
    {"entity": "Customer-Overseas", "field": "customer_code", "prefix": "EXP-", "example": "EXP-JP-01", "note": "海外客户"},
    {"entity": "Opportunity", "field": "opp_no", "prefix": "ASOPP", "example": "ASOPP202607001", "note": "商机"},
    {"entity": "Quotation", "field": "quote_no", "prefix": "ASQT", "example": "ASQT202607001", "note": "销售报价"},
    {"entity": "SalesOrder", "field": "so_no", "prefix": "SO-", "example": "SO202607001",
     "note": "销售订单（与 ERP 出库同 so_no 直查）"},
    {"entity": "ComplaintTicket", "field": "case_id", "prefix": "CASE-", "example": "CASE-0001",
     "note": "客诉工单（product_code 关联 PIM 产品 SKU-ZB- / 反馈 FB-）"},
    {"entity": "Receivable", "field": "receivable_id", "prefix": "ASAR/REC", "example": "REC20260001", "note": "应收"},
    {"entity": "ReceivableInvoice", "field": "invoice_no", "prefix": "INV", "example": "INV202607001", "note": "应收发票号"},
]
CRM_CODE_SPACE_MAPPINGS = [
    {"from_field": "Customer-Distributor.customer_code", "from_prefix": "DLR-", "to_field": "ERP.Customer.customer_code", "to_prefix": "DLR-",
     "rule": "CRM 经销商 DLR- 与 ERP 客户同码空间，按 customer_code 直查勿转换",
     "example": "getCustomer(code='DLR-001')（CRM）= ERP 客户同号",
     "why": "经销商跨 CRM/ERP 同码，免转换直查"},
    {"from_field": "SalesOrder.so_no", "from_prefix": "SO-", "to_field": "ERP.Outbound.so_no", "to_prefix": "SO-",
     "rule": "CRM 销售订单 SO- 与 ERP 出库同 so_no 直查（按单发货对账）",
     "example": "getSalesOrder(so_no='SO202607001') → ERP listOutbounds(so_no='SO202607001')",
     "why": "销售订单驱动出库，跨 CRM/ERP 按 so_no 一致"},
    {"from_field": "ComplaintTicket.product_code", "from_prefix": "CASE-", "to_field": "PIM.Product.product_code", "to_prefix": "SKU-ZB-",
     "rule": "客诉工单 CASE-.product_code 字段值即 PIM 产品码 SKU-ZB-（或反馈 FB-），按 product_code 关联：调 PIM getProduct(product_code=case.product_code)，勿把 CASE- 当 SKU 传",
     "example": "getComplaint(case_id='CASE-0001').product_code='SKU-ZB-G001' → getProduct('SKU-ZB-G001')",
     "why": "客诉关联产品主数据，CASE- ≠ SKU-ZB-"},
]

SCM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Supplier", "field": "code", "prefix": "SUP-", "example": "SUP-001",
     "note": "供应商（与 ERP 供应商 S-ZB- 同码空间直查）"},
    {"entity": "Quotation", "field": "quote_no", "prefix": "ASQ", "example": "ASQ202607001", "note": "供应商报价"},
    {"entity": "InTransit", "field": "plan_no", "prefix": "ASAP", "example": "ASAP202607001", "note": "在途到货计划"},
    {"entity": "Replenishment", "field": "suggestion_no", "prefix": "ASRS", "example": "ASRS202607001", "note": "补货建议"},
    {"entity": "LeadTimeSnapshot", "field": "snapshot_id", "prefix": "ASLS", "example": "ASLS202607001", "note": "交期快照"},
    {"entity": "ArrivalAcceptance", "field": "acceptance_no", "prefix": "ASMV", "example": "ASMV202607001", "note": "到货验收"},
]
SCM_CODE_SPACE_MAPPINGS = [
    {"from_field": "Supplier.code", "from_prefix": "SUP-", "to_field": "ERP.Supplier.code", "to_prefix": "S-ZB-",
     "rule": "SCM 供应商 SUP- 与 ERP 供应商 S-ZB- 同码空间（同一供应商两条前缀对齐），按 code 直查：调 SCM listSuppliers 收 SUP-，调 ERP listSuppliers 收 S-ZB-，同实体不同前缀需转换",
     "example": "SCM getSupplier(code='SUP-001') ↔ ERP getSupplier(code='S-ZB-001')（同供应商）",
     "why": "供应商跨 SCM/ERP 同实体，前缀不同需对齐勿混用"},
    {"from_field": "InTransit.material_code", "from_prefix": "ASAP", "to_field": "ERP.Material.material_code", "to_prefix": "M-ZB-",
     "rule": "在途到货 material_code 字段值即 ERP 物料码 M-ZB-，按 material_code 直查勿转换",
     "example": "getInTransit(plan_no='ASAP202607001').material_code='M-ZB-G001' → ERP getMaterial('M-ZB-G001')",
     "why": "在途到货挂物料主数据，同码直查"},
]

HRM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Employee-Sales", "field": "emp_no", "prefix": "ASSA", "example": "ASSA001", "note": "销售岗员工"},
    {"entity": "Employee-Function", "field": "emp_no", "prefix": "ASOF", "example": "ASOF201", "note": "职能岗员工"},
    {"entity": "Department", "field": "dept_code", "prefix": "PD-", "example": "PD-EC", "note": "部门"},
    {"entity": "Position", "field": "code", "prefix": "P-", "example": "P-EC", "note": "岗位（P-EC 渠道经理等；与 PIM 产品 SKU-ZB- 不同体系，PIM 不用 P- 故无歧义，但须显式说明）"},
    {"entity": "Recruitment", "field": "req_id", "prefix": "ASRC", "example": "ASRC2026001", "note": "招聘需求（position 关联岗位 P-）"},
    {"entity": "Resume", "field": "resume_id", "prefix": "ASRM", "example": "ASRM20260001", "note": "简历"},
    {"entity": "Meeting", "field": "meeting_id", "prefix": "ASMT", "example": "ASMT202607001", "note": "会议"},
]
HRM_CODE_SPACE_MAPPINGS = [
    {"from_field": "Recruitment.position", "from_prefix": "ASRC", "to_field": "Position.code", "to_prefix": "P-",
     "rule": "招聘需求 ASRC.position 字段值即岗位码 P-，按 position_code 关联：调 HRM getPosition(code=req.position)，勿把 ASRC 当 P- 传",
     "example": "getRecruitment(req_id='ASRC2026001').position='P-EC' → getPosition('P-EC')",
     "why": "招聘需求挂岗位，ASRC ≠ P-"},
    {"from_field": "Position.code", "from_prefix": "P-", "to_field": "PIM.Product.product_code", "to_prefix": "SKU-ZB-",
     "rule": "岗位 P-（HRM，P-EC=渠道经理）与 PIM 产品码 SKU-ZB- 不同体系：PIM 用 SKU-ZB- 不用 P-，故无歧义。勿把岗位 P- 当产品码传 PIM。教训同钢铁 P-ST-：第二段区分，P- 仅属 HRM",
     "example": "getPosition(code='P-EC')（HRM 岗位）vs getProduct(product_code='SKU-ZB-G001')（PIM 产品）",
     "why": "杜绝把岗位码 P- 当产品码传 PIM 404；与钢铁 P-ST- 同类教训"},
    {"from_field": "Employee.emp_no", "from_prefix": "ASSA/ASOF", "to_field": "ERP.CostCenter.cc_code", "to_prefix": "CC-ZB-",
     "rule": "员工 emp_no 对齐 ERP 成本中心 CC-ZB-（员工归属成本中心），按 emp_no/cc_code 关联：调 HRM getEmployee(emp_no=...)，调 ERP getCostCenter(cc_code=...)，不同码空间勿直传",
     "example": "getEmployee(emp_no='ASOF201').cc_code='CC-ZB-EC-01' → getCostCenter('CC-ZB-EC-01')",
     "why": "员工挂成本中心，emp_no ≠ CC-ZB-"},
]

PIM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Product", "field": "product_code", "prefix": "SKU-ZB-", "example": "SKU-ZB-G001",
     "note": "产品（与 ERP 物料 M-ZB- 不同前缀，按 product_code/material_code 关联）"},
    {"entity": "SKU", "field": "sku_code", "prefix": "SKU-ZB-", "example": "SKU-ZB-G001-R", "note": "SKU（产品规格细分）"},
    {"entity": "Category", "field": "cat_code", "prefix": "CAT-", "example": "CAT-GEL", "note": "品类（CAT-GEL 中性笔等）"},
    {"entity": "AntiCounterfeitProfile", "field": "product_code", "prefix": "（按 product_code）", "example": "SKU-ZB-G001",
     "note": "防伪档案（按 product_code 关联产品）"},
    {"entity": "CounterfeitSample", "field": "sample_code", "prefix": "CTF-", "example": "CTF20260701",
     "note": "假货样本（evidence_code 关联 CHN 取证 EV-，勿直传 CTF 给 CHN）"},
    {"entity": "Feedback", "field": "feedback_id", "prefix": "FB-", "example": "FB20260701",
     "note": "全渠道反馈（product_code 关联产品 SKU-ZB-）"},
]
PIM_CODE_SPACE_MAPPINGS = [
    {"from_field": "Product.product_code", "from_prefix": "SKU-ZB-", "to_field": "ERP.Material.material_code", "to_prefix": "M-ZB-",
     "rule": "PIM 产品 SKU-ZB- 与 ERP 物料 M-ZB- 不同前缀但同实体，按 product_code/material_code 关联：调 PIM getProduct 收 SKU-ZB-，调 ERP getMaterial 收 M-ZB-，勿直传",
     "example": "getProduct(product_code='SKU-ZB-G001') vs getMaterial(material_code='M-ZB-G001')（SKU-ZB-G001 ↔ M-ZB-G001）",
     "why": "产品与物料跨 PIM/ERP，前缀不同需转换勿混用"},
    {"from_field": "CounterfeitSample.evidence_code", "from_prefix": "CTF-", "to_field": "CHN.Evidence.evidence_code", "to_prefix": "EV-",
     "rule": "假货样本 CTF-.evidence_code 字段值即 CHN 取证码 EV-（如 CTF20260701.evidence_code=EV20260701），按 evidence_code 关联，再由 CHN EV- → 违规商家 MR-。勿直传 CTF 给 CHN 端点",
     "example": "getCounterfeitSample(sample_code='CTF20260701').evidence_code='EV20260701' → CHN getEvidence('EV20260701').merchant_code='MR-DL-01'",
     "why": "假货样本→取证→违规商家三级链路，CTF ≠ EV-，按 evidence_code 跳转"},
    {"from_field": "Feedback.product_code", "from_prefix": "FB-", "to_field": "Product.product_code", "to_prefix": "SKU-ZB-",
     "rule": "反馈 FB-.product_code 字段值即 PIM 产品码 SKU-ZB-，按 product_code 关联：调 PIM getProduct(product_code=fb.product_code)，勿把 FB- 当 SKU 传",
     "example": "getFeedback(feedback_id='FB20260701').product_code='SKU-ZB-G001' → getProduct('SKU-ZB-G001')",
     "why": "反馈挂产品主数据，FB- ≠ SKU-ZB-"},
]

CST_IDENTIFIER_CONVENTIONS = [
    {"entity": "Declaration", "field": "declaration_no", "prefix": "CD-", "example": "CD202607001",
     "note": "报关单（po_no 引用 ERP 采购单 PO-，按 po_no 关联勿直传 CD 给 ERP）"},
    {"entity": "HSClassification", "field": "hs_code", "prefix": "HS-", "example": "HS-960820", "note": "HS 归类（如 960820 圆珠笔）"},
    {"entity": "Invoice", "field": "invoice_no", "prefix": "INV-", "example": "INV202607001",
     "note": "发票（voucher_no 关联 ERP 凭证 BV-AS-，matched_declaration 关联报关单 CD-）"},
    {"entity": "ExchangeRate", "field": "pair", "prefix": "FX-", "example": "FX-JPY/CNY", "note": "汇率（按 pair 如 JPY/CNY）"},
    {"entity": "ComplianceCheck", "field": "check_id", "prefix": "CST-CK", "example": "CST-CK202607001", "note": "合规校验"},
]
CST_CODE_SPACE_MAPPINGS = [
    {"from_field": "Declaration.po_no", "from_prefix": "CD-", "to_field": "ERP.PurchaseOrder.po_no", "to_prefix": "PO-",
     "rule": "报关单 CD-.po_no 字段引用 ERP 采购单 PO-，按 po_no 关联：调 ERP getPurchaseOrder(po_no=decl.po_no)，勿把 CD- 当 PO- 传 ERP",
     "example": "getDeclaration(declaration_no='CD202607001').po_no='PO202607001' → getPurchaseOrder('PO202607001')",
     "why": "报关单引用采购单，反向直传 CD 给 ERP 必 404"},
    {"from_field": "Invoice.voucher_no", "from_prefix": "INV-", "to_field": "ERP.Voucher.voucher_no", "to_prefix": "BV-AS-",
     "rule": "发票 INV-.voucher_no 字段值即 ERP 凭证码 BV-AS-，按 invoice_no/voucher_no 关联：调 CST getInvoice 收 INV-，调 ERP listVouchers 收 BV-AS-，勿互传",
     "example": "getInvoice(invoice_no='INV202607001').voucher_no='BV-AS-2026-0701' → listVouchers('BV-AS-2026-0701')",
     "why": "发票与凭证不同码空间，直传必 404"},
    {"from_field": "Invoice.matched_declaration", "from_prefix": "INV-", "to_field": "Declaration.declaration_no", "to_prefix": "CD-",
     "rule": "发票 INV-.matched_declaration 字段值即报关单码 CD-，按 declaration_no 关联：调 CST getDeclaration(declaration_no=inv.matched_declaration)",
     "example": "getInvoice(invoice_no='INV202607001').matched_declaration='CD202607001' → getDeclaration('CD202607001')",
     "why": "发票挂报关单，CST 内部关联勿跨码直传"},
]

CHN_IDENTIFIER_CONVENTIONS = [
    {"entity": "Merchant-Distributor", "field": "merchant_code", "prefix": "MR-", "example": "MR-DL-01",
     "note": "渠道商家-经销商（MR-DL- 经销商 / MR-EC- 电商；与 CRM 客户按 merchant_code/customer_code 关联）"},
    {"entity": "Merchant-Ecommerce", "field": "merchant_code", "prefix": "MR-", "example": "MR-EC-09", "note": "渠道商家-电商"},
    {"entity": "PriceViolation", "field": "violation_id", "prefix": "PV-", "example": "PV20260701", "note": "低价违规"},
    {"entity": "UnauthorizedShop", "field": "shop_id", "prefix": "UNS-", "example": "UNS-20260701", "note": "非授权店铺"},
    {"entity": "Evidence", "field": "evidence_code", "prefix": "EV-", "example": "EV20260701",
     "note": "取证（pim_sample_code 关联 PIM 假货样本 CTF-，merchant_code 关联渠道商家 MR-）"},
    {"entity": "Competitor", "field": "competitor_code", "prefix": "CMP-", "example": "CMP-01", "note": "竞品"},
    {"entity": "ChannelPerformance", "field": "channel", "prefix": "（按 channel）", "example": "channel=EC-09",
     "note": "渠道效能（按 channel 维度统计）"},
]
CHN_CODE_SPACE_MAPPINGS = [
    {"from_field": "Evidence.pim_sample_code", "from_prefix": "EV-", "to_field": "PIM.CounterfeitSample.sample_code", "to_prefix": "CTF-",
     "rule": "取证 EV-.pim_sample_code 字段值即 PIM 假货样本码 CTF-（如 EV20260701.pim_sample_code=CTF20260701），按 evidence_code/sample_code 关联：调 CHN getEvidence 收 EV-，调 PIM getCounterfeitSample 收 CTF-，勿互传",
     "example": "getEvidence(evidence_code='EV20260701').pim_sample_code='CTF20260701' → getCounterfeitSample('CTF20260701')",
     "why": "取证挂假货样本，EV- ≠ CTF-，跨码按字段跳转"},
    {"from_field": "Evidence.merchant_code", "from_prefix": "EV-", "to_field": "Merchant.merchant_code", "to_prefix": "MR-",
     "rule": "取证 EV-.merchant_code 字段值即渠道商家码 MR-，按 merchant_code 直查（同码空间）",
     "example": "getEvidence(evidence_code='EV20260701').merchant_code='MR-DL-01' → getMerchant('MR-DL-01')",
     "why": "取证挂违规商家，同码直查"},
    {"from_field": "Merchant.merchant_code", "from_prefix": "MR-", "to_field": "CRM.Customer.customer_code", "to_prefix": "DLR-/EC-",
     "rule": "授权渠道商家 MR- 对应 CRM 客户码（MR-DL-01↔DLR-01 / MR-EC-09↔EC-09），按 merchant_code/customer_code 关联：调 CHN getMerchant 收 MR-，调 CRM getCustomer 收 DLR-/EC-，前缀不同需对齐",
     "example": "getMerchant('MR-DL-01').customer_code='DLR-01' → getCustomer('DLR-01')",
     "why": "渠道商家与 CRM 客户同实体不同前缀，对齐勿混用"},
]


# ───────────────────────── 对象/链接/动作类型（精简） ─────────────────────────

def _ot(name: str, pk: str, props: dict, desc: str = "", backing: str = "") -> dict:
    return {"objectType": name, "primaryKey": pk, "title": pk, "description": desc,
            "backingInterface": backing or f"mock.agilestationery.{name.lower()}",
            "properties": {k: {"type": v if isinstance(v, str) else "string", "description": k} for k, v in props.items()}}

def _lt(name: str, parent: str, child: str, join: str, cross: bool = False, desc: str = "") -> dict:
    return {"linkType": name, "parent": parent, "child": child, "cardinality": "1:N",
            "joinField": join, "crossSystem": cross, "description": desc}

ERP_OBJECT_TYPES = [
    _ot("Material", "material_code", {"material_code": "str", "name": "str", "category": "str", "unit_cost": "num"}, "文具物料主数据"),
    _ot("PurchaseOrder", "po_no", {"po_no": "str", "supplier_code": "str", "amount": "num", "status": "str"}, "采购订单"),
    _ot("Inventory", "stock_id", {"stock_id": "str", "material_code": "str", "qty": "num", "warehouse": "str"}, "库存"),
    _ot("Payable", "payable_id", {"payable_id": "str", "supplier_code": "str", "amount": "num", "days_overdue": "int"}, "应付"),
    _ot("Voucher", "voucher_no", {"voucher_no": "str", "period": "str", "status": "str", "debit_total": "num"}, "财务凭证"),
    _ot("CostCenter", "cc_code", {"cc_code": "str", "name": "str", "manager_emp_no": "str"}, "成本中心"),
    _ot("ImportBatchCost", "batch_id", {"batch_id": "str", "declaration_no": "str", "total_cost": "num", "landed_cost": "num"}, "进口批次成本"),
]
ERP_LINK_TYPES = [
    _lt("po_to_material", "PurchaseOrder", "Material", "po_no/material_code", False, "采购单关联物料"),
    _lt("payable_to_supplier", "Payable", "PurchaseOrder", "po_no", False, "应付关联采购单"),
    _lt("batchcost_to_declaration", "ImportBatchCost", "CST.Declaration", "declaration_no", True, "进口批次成本挂报关单"),
    _lt("cc_to_employee", "CostCenter", "HRM.Employee", "cc_code/emp_no", True, "成本中心挂员工"),
]
ERP_ACTION_TYPES: list = []

CRM_OBJECT_TYPES = [
    _ot("Customer", "customer_code", {"customer_code": "str", "name": "str", "type": "str", "credit_grade": "str"}, "客户（经销商/KA/电商/海外）"),
    _ot("Opportunity", "opp_no", {"opp_no": "str", "customer_code": "str", "product_code": "str", "amount": "num", "stage": "str"}, "商机"),
    _ot("Quotation", "quote_no", {"quote_no": "str", "customer_code": "str", "product_code": "str", "unit_price": "num"}, "销售报价"),
    _ot("SalesOrder", "so_no", {"so_no": "str", "customer_code": "str", "product_code": "str", "qty": "num", "status": "str"}, "销售订单"),
    _ot("ComplaintTicket", "case_id", {"case_id": "str", "customer_code": "str", "product_code": "str", "severity": "str", "status": "str"}, "客诉工单"),
    _ot("Receivable", "receivable_id", {"receivable_id": "str", "customer_code": "str", "so_no": "str", "amount": "num", "days_overdue": "int"}, "应收"),
    _ot("Visit", "visit_id", {"visit_id": "str", "customer_code": "str", "feedback": "str", "next_action": "str"}, "回访"),
]
CRM_LINK_TYPES = [
    _lt("so_to_customer", "SalesOrder", "Customer", "customer_code", False, "订单关联客户"),
    _lt("opp_to_customer", "Opportunity", "Customer", "customer_code", False, "商机关联客户"),
    _lt("complaint_to_product", "ComplaintTicket", "PIM.Product", "product_code", True, "客诉关联 PIM 产品"),
    _lt("receivable_to_so", "Receivable", "SalesOrder", "so_no", False, "应收关联订单"),
    _lt("visit_to_customer", "Visit", "Customer", "customer_code", False, "回访关联客户"),
]
CRM_ACTION_TYPES: list = []

SCM_OBJECT_TYPES = [
    _ot("Supplier", "code", {"code": "str", "name": "str", "category": "str", "rating": "str"}, "供应商"),
    _ot("Quotation", "quote_no", {"quote_no": "str", "supplier_code": "str", "material_code": "str", "unit_price": "num"}, "供应商报价"),
    _ot("PriceCompare", "compare_no", {"compare_no": "str", "material_code": "str", "supplier_code": "str", "unit_price": "num", "rank": "int"}, "比价"),
    _ot("InTransit", "plan_no", {"plan_no": "str", "supplier_code": "str", "material_code": "str", "eta": "str", "status": "str"}, "在途到货"),
    _ot("Replenishment", "suggestion_no", {"suggestion_no": "str", "material_code": "str", "suggested_qty": "num", "reason": "str"}, "补货建议"),
    _ot("LeadTimeSnapshot", "snapshot_id", {"snapshot_id": "str", "supplier_code": "str", "material_code": "str", "lead_time_days": "int"}, "交期快照"),
    _ot("ArrivalAcceptance", "acceptance_no", {"acceptance_no": "str", "plan_no": "str", "material_code": "str", "accepted_qty": "num", "defect_qty": "num"}, "到货验收"),
]
SCM_LINK_TYPES = [
    _lt("quotation_by_supplier", "Supplier", "Quotation", "supplier_code", False, "供应商报价"),
    _lt("compare_to_quotation", "PriceCompare", "Quotation", "quote_no", False, "比价关联报价"),
    _lt("intransit_to_material", "InTransit", "ERP.Material", "material_code", True, "在途到货挂 ERP 物料"),
    _lt("acceptance_to_intransit", "ArrivalAcceptance", "InTransit", "plan_no", False, "验收关联在途到货"),
]
SCM_ACTION_TYPES: list = []

HRM_OBJECT_TYPES = [
    _ot("Department", "dept_code", {"dept_code": "str", "name": "str", "parent_dept": "str"}, "部门"),
    _ot("Position", "code", {"code": "str", "name": "str", "dept_code": "str", "grade": "str"}, "岗位"),
    _ot("Employee", "emp_no", {"emp_no": "str", "name": "str", "dept_code": "str", "position": "str", "cc_code": "str"}, "员工"),
    _ot("Attendance", "record_id", {"record_id": "str", "emp_no": "str", "date": "str", "status": "str"}, "考勤"),
    _ot("Leave", "leave_id", {"leave_id": "str", "emp_no": "str", "type": "str", "days": "num"}, "请假"),
    _ot("Payroll", "payroll_id", {"payroll_id": "str", "emp_no": "str", "period": "str", "net": "num"}, "薪酬"),
    _ot("Performance", "perf_id", {"perf_id": "str", "emp_no": "str", "period": "str", "score": "num"}, "绩效"),
    _ot("Recruitment", "req_id", {"req_id": "str", "position": "str", "headcount": "int", "status": "str"}, "招聘需求"),
    _ot("Resume", "resume_id", {"resume_id": "str", "position_code": "str", "rating_score": "int", "tags": "str"}, "简历"),
    _ot("Meeting", "meeting_id", {"meeting_id": "str", "organizer_emp_no": "str", "topic": "str", "attendees": "str"}, "会议"),
]
HRM_LINK_TYPES = [
    _lt("employee_to_position", "Employee", "Position", "position/code", False, "员工关联岗位"),
    _lt("employee_to_dept", "Employee", "Department", "dept_code", False, "员工关联部门"),
    _lt("resume_to_position", "Resume", "Position", "position_code/code", False, "简历关联岗位"),
    _lt("recruitment_to_position", "Recruitment", "Position", "position/code", False, "招聘需求关联岗位"),
    _lt("attendance_to_employee", "Attendance", "Employee", "emp_no", False, "考勤关联员工"),
]
HRM_ACTION_TYPES: list = []

PIM_OBJECT_TYPES = [
    _ot("Product", "product_code", {"product_code": "str", "name": "str", "cat_code": "str", "brand": "str"}, "产品"),
    _ot("SKU", "sku_code", {"sku_code": "str", "product_code": "str", "spec": "str", "barcode": "str"}, "SKU"),
    _ot("Category", "cat_code", {"cat_code": "str", "name": "str", "parent_cat": "str"}, "品类"),
    _ot("AntiCounterfeitProfile", "product_code", {"product_code": "str", "auth_method": "str", "batch_prefix": "str"}, "防伪档案"),
    _ot("CounterfeitSample", "sample_code", {"sample_code": "str", "product_code": "str", "evidence_code": "str", "channel": "str"}, "假货样本"),
    _ot("Feedback", "feedback_id", {"feedback_id": "str", "product_code": "str", "channel": "str", "sentiment": "str", "content": "str"}, "全渠道反馈"),
]
PIM_LINK_TYPES = [
    _lt("sku_to_product", "SKU", "Product", "product_code", False, "SKU 关联产品"),
    _lt("product_to_category", "Product", "Category", "cat_code", False, "产品关联品类"),
    _lt("profile_to_product", "AntiCounterfeitProfile", "Product", "product_code", False, "防伪档案关联产品"),
    _lt("sample_to_evidence", "CounterfeitSample", "CHN.Evidence", "evidence_code", True, "假货样本关联 CHN 取证"),
    _lt("feedback_to_product", "Feedback", "Product", "product_code", False, "反馈关联产品"),
]
PIM_ACTION_TYPES: list = []

CST_OBJECT_TYPES = [
    _ot("Declaration", "declaration_no", {"declaration_no": "str", "po_no": "str", "hs_code": "str", "country": "str", "status": "str"}, "报关单"),
    _ot("HSClassification", "hs_code", {"hs_code": "str", "name": "str", "tax_rate": "num", "unit": "str"}, "HS 归类"),
    _ot("Invoice", "invoice_no", {"invoice_no": "str", "declaration_no": "str", "voucher_no": "str", "amount": "num", "currency": "str"}, "发票"),
    _ot("ExchangeRate", "pair", {"pair": "str", "rate": "num", "date": "str"}, "汇率"),
    _ot("ComplianceCheck", "check_id", {"check_id": "str", "declaration_no": "str", "rule": "str", "result": "str"}, "合规校验"),
]
CST_LINK_TYPES = [
    _lt("declaration_to_po", "Declaration", "ERP.PurchaseOrder", "po_no", True, "报关单引用 ERP 采购单"),
    _lt("invoice_to_voucher", "Invoice", "ERP.Voucher", "voucher_no", True, "发票关联 ERP 凭证"),
    _lt("invoice_to_declaration", "Invoice", "Declaration", "declaration_no", False, "发票关联报关单"),
    _lt("check_to_declaration", "ComplianceCheck", "Declaration", "declaration_no", False, "合规校验关联报关单"),
    _lt("declaration_to_hs", "Declaration", "HSClassification", "hs_code", False, "报关单关联 HS 归类"),
]
CST_ACTION_TYPES: list = []

CHN_OBJECT_TYPES = [
    _ot("Merchant", "merchant_code", {"merchant_code": "str", "name": "str", "type": "str", "channel": "str", "authorized": "bool"}, "渠道商家"),
    _ot("PriceViolation", "violation_id", {"violation_id": "str", "merchant_code": "str", "product_code": "str", "low_price": "num", "status": "str"}, "低价违规"),
    _ot("UnauthorizedShop", "shop_id", {"shop_id": "str", "merchant_code": "str", "platform": "str", "status": "str"}, "非授权店铺"),
    _ot("Evidence", "evidence_code", {"evidence_code": "str", "merchant_code": "str", "pim_sample_code": "str", "evidence_type": "str"}, "取证"),
    _ot("ChannelPerformance", "channel", {"channel": "str", "gmv": "num", "share": "num", "trend": "str"}, "渠道效能"),
    _ot("Competitor", "competitor_code", {"competitor_code": "str", "name": "str", "product_code": "str", "price": "num"}, "竞品"),
]
CHN_LINK_TYPES = [
    _lt("violation_to_merchant", "PriceViolation", "Merchant", "merchant_code", False, "违规关联商家"),
    _lt("unauthorized_to_merchant", "UnauthorizedShop", "Merchant", "merchant_code", False, "非授权店铺关联商家"),
    _lt("evidence_to_merchant", "Evidence", "Merchant", "merchant_code", False, "取证关联商家"),
    _lt("evidence_to_pim_sample", "Evidence", "PIM.CounterfeitSample", "pim_sample_code/sample_code", True, "取证关联 PIM 假货样本"),
    _lt("merchant_to_crm_customer", "Merchant", "CRM.Customer", "merchant_code/customer_code", True, "渠道商家关联 CRM 客户"),
]
CHN_ACTION_TYPES: list = []


# 跨系统闭环链接（8 条文具贸易闭环）
CROSS_LINK_TYPES = [
    _lt("sales_order_drives_procurement", "CRM.SalesOrder", "ERP.PurchaseOrder", "so_no/po_no", True,
        "销售订单 SO-(CRM)→采购单 PO-(ERP)→报关单 CD-(CST)→发票 INV-(CST)→凭证 BV-(ERP)→应收 REC-(CRM)"),
    _lt("product_to_material_flow", "PIM.Product", "ERP.Material", "product_code/material_code", True,
        "产品 SKU-ZB-(PIM)→物料 M-ZB-(ERP)→库存→补货建议"),
    _lt("counterfeit_enforcement", "PIM.CounterfeitSample", "CHN.Evidence", "evidence_code/pim_sample_code", True,
        "假货样本 CTF-(PIM)→取证 EV-(CHN)→违规商家 MR-(CHN)"),
    _lt("distributor_to_receivable", "CRM.Customer", "ERP.Voucher", "customer_code/voucher_no", True,
        "经销商 DLR-(CRM)→应收 REC-(CRM)→凭证 BV-(ERP)"),
    _lt("complaint_to_feedback_flow", "CRM.ComplaintTicket", "PIM.Feedback", "product_code", True,
        "客诉 CASE-(CRM)→产品反馈 FB-(PIM)→产品 SKU-ZB-"),
    _lt("recruitment_to_costcenter", "HRM.Recruitment", "ERP.CostCenter", "position/cc_code", True,
        "招聘需求 ASRC-(HRM)→岗位 P-(HRM)→员工→成本中心 CC-ZB-(ERP)"),
    _lt("competitor_to_opportunity", "CHN.Competitor", "CRM.Opportunity", "competitor_code/product_code", True,
        "竞品 CMP-(CHN)→商机/营销物料(MKT)"),
    _lt("feedback_to_product_improvement", "PIM.Feedback", "PIM.Product", "product_code", False,
        "反馈 FB-(PIM)→产品改进(日本总部)"),
]
CROSS_ACTION_TYPES: list = []


# ───────────────────────── Markdown 渲染 ─────────────────────────

def render_object_types_md(title: str, intro: str, ots: list) -> str:
    lines = [f"# {title}\n", f"> {intro}\n", "```ontology", json.dumps(ots, ensure_ascii=False, indent=2), "```\n"]
    for ot in ots:
        lines += [f"## {ot['objectType']}", ot.get("description", ""), "",
                  f"- 主键：`{ot['primaryKey']}` ｜ 标题：`{ot.get('title','')}`"]
        if ot.get("backingInterface"):
            lines.append(f"- 数据接口：`{ot['backingInterface']}`")
        lines += ["\n| 属性 | 类型 | 说明 |", "|---|---|---|"]
        for p, d in ot["properties"].items():
            lines.append(f"| `{p}` | {d['type']} | {d.get('description','')} |")
        lines.append("")
    return "\n".join(lines)


def render_link_types_md(title: str, intro: str, lts: list) -> str:
    lines = [f"# {title}\n", f"> {intro}\n", "```ontology", json.dumps(lts, ensure_ascii=False, indent=2), "```\n",
             "| 链接类型 | 父→子 | 基数 | join | 跨系统 | 说明 |", "|---|---|---|---|---|---|"]
    for lt in lts:
        cross = "✓" if lt.get("crossSystem") else ""
        lines.append(f"| {lt['linkType']} | {lt['parent']}→{lt['child']} | {lt['cardinality']} | `{lt['joinField']}` | {cross} | {lt.get('description','')} |")
    return "\n".join(lines)


def render_action_types_md(title: str, intro: str, ats: list) -> str:
    lines = [f"# {title}\n", f"> {intro}\n", "```ontology", json.dumps(ats, ensure_ascii=False, indent=2), "```\n"]
    for at in ats:
        lines += [f"## {at['actionType']}", at.get("description", ""), ""]
    return "\n".join(lines)


def render_identifiers_md(title: str, intro: str, convs: list, mappings: list) -> str:
    lines = [f"# {title}\n", f"> {intro}\n", "## 标识符约定\n",
             "| 实体 | 主键字段 | 前缀 | 示例值 | 说明 |", "|---|---|---|---|---|"]
    for c in convs:
        lines.append(f"| {c['entity']} | `{c['field']}` | `{c['prefix']}` | `{c['example']}` | {c['note']} |")
    lines += ["\n## 跨码空间映射规则（调 path 参数端点前必读，杜绝 404）\n"]
    for m in mappings:
        lines += [
            f"### `{m['from_field']}`（`{m['from_prefix']}`）→ `{m['to_field']}`（`{m['to_prefix']}`）",
            f"- 规则：{m['rule']}", f"- 示例：{m['example']}", f"- 原因：{m['why']}\n",
        ]
    return "\n".join(lines)


def render_readme_md(label: str, folder: str, ots: list, lts: list, ats: list, summary: str) -> str:
    cross = [lt for lt in lts if lt.get("crossSystem")]
    return "\n".join([
        f"# {label}\n", f"> {summary}\n",
        f"**对象类型 {len(ots)}**：" + "、".join(o["objectType"] for o in ots) + "  ",
        f"**链接类型 {len(lts)}**（跨系统 {len(cross)}）：" + "、".join(l["linkType"] for l in lts) + "  ",
        f"**动作类型 {len(ats)}**：" + ("、".join(a["actionType"] for a in ats) if ats else "无"), "",
        "> Palantir Foundry Ontology 规范；agent 运行时按任务配置注入对应文件 content。",
    ])


def _files_for(folder: str, label: str, ots: list, lts: list, ats: list, summary: str,
                convs: list | None = None, mappings: list | None = None,
                identifiers_intro: str = "") -> list:
    meta = {"system": folder.lower(), "source": "mock-agilestationery"}
    files = [
        (f"{folder}/README.md", render_readme_md(label, folder, ots, lts, ats, summary), {**meta, "kind": "readme"}),
        (f"{folder}/object-types.md", render_object_types_md(f"{label} · 对象类型", f"由 mock {folder} 数据接口支撑。", ots), {**meta, "kind": "object-types"}),
        (f"{folder}/link-types.md", render_link_types_md(f"{label} · 链接类型", f"定义 {label} 内部及跨系统对象间关系。", lts), {**meta, "kind": "link-types"}),
        (f"{folder}/action-types.md", render_action_types_md(f"{label} · 动作类型", f"定义 {label} 上可执行的写操作。", ats), {**meta, "kind": "action-types"}),
    ]
    if convs:
        default_intro = (f"{label} 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——"
                         f"杜绝把物料 M-ZB- 当产品 SKU-ZB-、把报关单 CD- 当采购单 PO-、把发票 INV- 当凭证 BV-AS-、"
                         f"把岗位 P- 当产品码 SKU-ZB-、把假货样本 CTF- 当取证 EV- 等 404。")
        files.append((f"{folder}/identifiers.md",
                      render_identifiers_md(f"{label} · 标识符与码空间映射",
                                             identifiers_intro or default_intro,
                                             convs, mappings or []),
                      {**meta, "kind": "identifiers"}))
    return files


# 组织级 8 个本体文件夹（7 域 + Cross）
ORG_SYSTEMS = [
    {"folder": "ERP", "label": "ERP 资源计划本体",
     "summary": "物料(M-ZB-)/采购单(PO-)/库存/应付(ASAP)/凭证(BV-AS-)/成本中心(CC-ZB-)/进口批次成本(BAT)；凭证与报关单/发票跨系统对账。",
     "object_types": ERP_OBJECT_TYPES, "link_types": ERP_LINK_TYPES, "action_types": ERP_ACTION_TYPES,
     "conventions": ERP_IDENTIFIER_CONVENTIONS, "code_mappings": ERP_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "ERP 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把物料 M-ZB- 当产品 SKU-ZB- 传 PIM、把报关单 CD- 当采购单 PO- 传 ERP、把发票 INV- 当凭证 BV-AS- 传 ERP 等 404。"},
    {"folder": "CRM", "label": "CRM 销售与经销商本体",
     "summary": "客户(DLR-/KA-/EC-/EXP-)/商机(ASOPP)/报价(ASQT)/销售订单(SO-)/客诉工单(CASE-)/应收(ASAR/REC)/回访；订单驱动出库+客诉关联产品。",
     "object_types": CRM_OBJECT_TYPES, "link_types": CRM_LINK_TYPES, "action_types": CRM_ACTION_TYPES,
     "conventions": CRM_IDENTIFIER_CONVENTIONS, "code_mappings": CRM_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "CRM 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把客诉工单 CASE- 当产品 SKU-ZB- 传 PIM、把销售订单 SO- 当出库码乱传等 404；经销商 DLR- 跨 CRM/ERP 同码可直查。"},
    {"folder": "SCM", "label": "SCM 供应链协同本体",
     "summary": "供应商(SUP-)/报价(ASQ)/比价/在途到货(ASAP)/补货建议(ASRS)/交期快照(ASLS)/到货验收(ASMV)；供应商与 ERP 供应商 S-ZB- 同码对齐。",
     "object_types": SCM_OBJECT_TYPES, "link_types": SCM_LINK_TYPES, "action_types": SCM_ACTION_TYPES,
     "conventions": SCM_IDENTIFIER_CONVENTIONS, "code_mappings": SCM_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "SCM 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把供应商 SUP- 与 ERP 供应商 S-ZB- 混用、把在途到货计划号 ASAP 当物料 M-ZB- 传 ERP 等 404。"},
    {"folder": "HRM", "label": "HRM 人力资源本体",
     "summary": "部门(PD-)/岗位(P-)/员工(ASSA/ASOF)/考勤/请假/薪酬/绩效/招聘需求(ASRC)/简历(ASRM)/会议(ASMT)；岗位 P- 与 PIM 产品 SKU-ZB- 不同体系。",
     "object_types": HRM_OBJECT_TYPES, "link_types": HRM_LINK_TYPES, "action_types": HRM_ACTION_TYPES,
     "conventions": HRM_IDENTIFIER_CONVENTIONS, "code_mappings": HRM_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "HRM 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把岗位 P- 当产品码 SKU-ZB- 传 PIM（与钢铁 P-ST- 同类教训）、把招聘需求 ASRC 当岗位 P- 传、把员工 emp_no 当成本中心 CC-ZB- 传 ERP 等 404。"},
    {"folder": "PIM", "label": "PIM 产品与防伪本体",
     "summary": "产品(SKU-ZB-)/SKU/品类(CAT-)/防伪档案/假货样本(CTF-)/全渠道反馈(FB-)；假货样本→取证→违规商家三级链路。",
     "object_types": PIM_OBJECT_TYPES, "link_types": PIM_LINK_TYPES, "action_types": PIM_ACTION_TYPES,
     "conventions": PIM_IDENTIFIER_CONVENTIONS, "code_mappings": PIM_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "PIM 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把产品 SKU-ZB- 当物料 M-ZB- 传 ERP、把假货样本 CTF- 当取证 EV- 传 CHN、把反馈 FB- 当产品 SKU-ZB- 传等 404。"},
    {"folder": "CST", "label": "CST 报关与单证本体",
     "summary": "报关单(CD-)/HS归类(HS-)/发票(INV-)/汇率(FX-)/合规校验(CST-CK)；报关单引用采购单 PO-、发票关联凭证 BV-AS-。",
     "object_types": CST_OBJECT_TYPES, "link_types": CST_LINK_TYPES, "action_types": CST_ACTION_TYPES,
     "conventions": CST_IDENTIFIER_CONVENTIONS, "code_mappings": CST_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "CST 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把报关单 CD- 当采购单 PO- 传 ERP、把发票 INV- 当凭证 BV-AS- 传 ERP、把发票 INV- 当报关单 CD- 乱传等 404。"},
    {"folder": "CHN", "label": "CHN 渠道与电商秩序本体",
     "summary": "渠道商家(MR-)/低价违规(PV-)/非授权店铺(UNS-)/取证(EV-)/渠道效能/竞品(CMP-)；取证挂假货样本+违规商家。",
     "object_types": CHN_OBJECT_TYPES, "link_types": CHN_LINK_TYPES, "action_types": CHN_ACTION_TYPES,
     "conventions": CHN_IDENTIFIER_CONVENTIONS, "code_mappings": CHN_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "CHN 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把取证 EV- 当假货样本 CTF- 传 PIM、把渠道商家 MR- 当客户码 DLR-/EC- 乱传 CRM（前缀不同需对齐）等 404。"},
    {"folder": "Cross", "label": "跨系统闭环本体",
     "summary": "8 条跨系统闭环：销售订单→采购单→报关单→发票→凭证→应收；产品→物料→库存→补货；假货样本→取证→违规商家；经销商→应收→凭证；客诉→反馈→产品；招聘→岗位→员工→成本中心；竞品→商机；反馈→产品改进。",
     "object_types": [], "link_types": CROSS_LINK_TYPES, "action_types": CROSS_ACTION_TYPES},
]


# ───────────────────────── 主流程 ─────────────────────────

async def _get_org(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None)))
    org = result.scalar_one_or_none()
    if org is not None:
        return org
    result = await db.execute(select(Organization).where(Organization.name == ORG_NAME_FALLBACK, Organization.deleted_at.is_(None)))
    return result.scalar_one_or_none()


async def _seed_scope(db, org_id, scope_type, scope_id, systems, scope_label) -> list:
    out = []
    for s in systems:
        await create_folder(db, org_id, scope_type, scope_id, s["folder"])
        files = _files_for(s["folder"], s["label"], s["object_types"], s["link_types"], s["action_types"], s["summary"],
                           convs=s.get("conventions"), mappings=s.get("code_mappings"),
                           identifiers_intro=s.get("identifiers_intro", ""))
        for path, content, meta in files:
            await upsert_file(db, org_id, scope_type, scope_id,
                              OntologyFileCreate(path=path, content=content, metadata=meta,
                                                 scope_type=scope_type, scope_id=scope_id))
            logger.info("ontology_file_upserted", path=path, scope=scope_label)
        out.append({
            "folder": s["folder"], "label": s["label"],
            "object_types": len(s["object_types"]), "link_types": len(s["link_types"]),
            "action_types": len(s["action_types"]),
            "cross_system_links": sum(1 for lt in s["link_types"] if lt.get("crossSystem")),
            "identifiers": "✓" if s.get("conventions") else "", "files": len(files), "scope": scope_label,
        })
    return out


async def seed() -> dict:
    overall = {"scopes": []}
    async with async_session_factory() as db:
        org = await _get_org(db, ORG_SLUG)
        if org is None:
            raise RuntimeError(f"组织 slug='{ORG_SLUG}' 不存在，请先运行 seed_agilestationery_org.py。")
        logger.info("seed_agilestationery_ontology_org", slug=org.slug, org_id=str(org.id))

        org_results = await _seed_scope(db, org.id, "organization", None, ORG_SYSTEMS, "organization")
        overall["scopes"].append({"scope": "organization", "systems": org_results})

        await db.commit()
    return overall


def _print_report(result: dict) -> None:
    print("\n" + "=" * 72)
    print("敏睿文具本体导入完成（覆盖式幂等，可安全重复执行）")
    print("-" * 72)
    total_files = total_ot = total_lt = total_at = total_cross = 0
    for sc in result["scopes"]:
        print(f"\n[{sc['scope']}]")
        print(f"  {'文件夹':<22}{'对象类型':>8}{'链接类型':>8}{'跨系统':>6}{'动作类型':>8}{'标识符':>6}{'文件数':>6}")
        for s in sc["systems"]:
            print(f"  {s['folder']:<22}{s['object_types']:>8}{s['link_types']:>8}"
                  f"{s['cross_system_links']:>6}{s['action_types']:>8}{s['identifiers']:>6}{s['files']:>6}")
            total_ot += s["object_types"]; total_lt += s["link_types"]; total_at += s["action_types"]
            total_cross += s["cross_system_links"]; total_files += s["files"]
    print("-" * 72)
    print(f"合计：{total_files} 个本体文件｜{total_ot} 对象类型｜{total_lt} 链接类型（跨系统 {total_cross}）｜{total_at} 动作类型")
    print("位置：管理端「敏睿文具」组织 → 本体 → ERP/CRM/SCM/HRM/PIM/CST/CHN/Cross（组织级）")
    print("7 域含 identifiers.md（标识符约定 + 跨码空间映射），agent 推理时按用户 scope 注入。")
    print("=" * 72)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
