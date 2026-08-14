"""为「星途勘探」组织创建本体文件（6 组织级域 + Cross）。

每个域 4 文件：README/object-types/link-types/action-types；DES/EPC/SEC/ERP/HRM/CRM
各含 identifiers.md（标识符约定 + 跨码空间映射规则）—— 防猜码 404 的 no-guessing 骨架。
沿用 agilesteel/agilestationery 的 render_identifiers_md + _files_for + _seed_scope 模式。

用法:
    docker cp demo/starexploration/scripts/seed_starexploration_ontology.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_starexploration_ontology.py
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

ORG_SLUG = "starexploration"
ORG_NAME_FALLBACK = "星途勘探"


# ───────────────────────── 标识符约定（no-guessing 骨架） ─────────────────────────

DES_IDENTIFIER_CONVENTIONS = [
    {"entity": "Scheme", "field": "scheme_no", "prefix": "SCH-", "example": "SCH-IND-001",
     "note": "设计方案（SCH-IND- 工业厂房 / SCH-BAT- 电池工厂 / SCH-CIV- 市政；与 EPC 项目 PRJ- 按 scheme_no 关联）"},
    {"entity": "Drawing", "field": "drawing_no", "prefix": "DWG-", "example": "DWG-ARC-001",
     "note": "图纸（DWG-ARC- 建筑 / DWG-STR- 结构 / DWG-MEP- 机电；交付物与 EPC PDOC-、脱密对象 SEC SECDOC- 按 drawing_no 关联）"},
    {"entity": "Spec", "field": "spec_code", "prefix": "SPEC-", "example": "SPEC-GB-50011",
     "note": "规范条款（国标编号，含强条 is_mandatory）"},
    {"entity": "QuantityItem", "field": "qi_no", "prefix": "QTI-", "example": "QTI-CON-001",
     "note": "算量项（QTI-CON- 混凝土 / QTI-STE- 钢筋；material_code 映射 ERP 物料 M-CON-/M-STE- 需 prefix 转换）"},
    {"entity": "Clash", "field": "clash_no", "prefix": "CLS-", "example": "CLS-2026-001", "note": "跨专业碰撞"},
]
DES_CODE_SPACE_MAPPINGS = [
    {"from_field": "QuantityItem.material_code", "from_prefix": "QTI-CON-", "to_field": "ERP.Material.material_code", "to_prefix": "M-CON-",
     "rule": "DES 算量项 QTI-CON-/QTI-STE- 的 material_code 字段值即 ERP 物料码 M-CON-/M-STE-（prefix 转换：QTI-CON-→M-CON-，QTI-STE-→M-STE-），按 material_code 关联：调 DES computeQuantityTakeoff 收 QTI-，调 ERP listMaterials 收 M-，勿把 QTI- 当 M- 传 ERP",
     "example": "computeQuantityTakeoff(scheme_no='SCH-IND-001').by_material[].material_code='M-CON-001' → ERP listMaterials(material_code='M-CON-001')",
     "why": "算量项转采购物料需 prefix 转换，直传 QTI- 必 404"},
    {"from_field": "Scheme.scheme_no", "from_prefix": "SCH-", "to_field": "EPC.Project.project_code", "to_prefix": "PRJ-",
     "rule": "设计方案 SCH- 与 EPC 项目 PRJ- 不同前缀但同实体（方案转项目），按 scheme_no 关联：调 EPC getProject(project_code='PRJ-BAT-001').scheme_no='SCH-BAT-001'，勿把 SCH- 当 PRJ- 传 EPC",
     "example": "getScheme(scheme_no='SCH-BAT-001') ↔ EPC getProject(project_code='PRJ-BAT-001')（SCH-BAT-001 ↔ PRJ-BAT-001）",
     "why": "方案转项目，前缀不同需对齐勿互传"},
    {"from_field": "Drawing.drawing_no", "from_prefix": "DWG-", "to_field": "EPC.ProjectDocument.linked_code", "to_prefix": "PDOC-",
     "rule": "图纸 DWG- 经 EPC 项目文档 PDOC-.linked_code 关联（图纸交付物）：调 EPC listProjectDocuments 收 PDOC-，其 linked_code 字段值即 DWG-，勿把 PDOC- 当 DWG- 传 DES",
     "example": "listProjectDocuments(project_code='PRJ-IND-001').linked_code='DWG-ARC-001' → DES getDrawing('DWG-ARC-001')",
     "why": "图纸交付物跨 DES/EPC，按 linked_code 跳转"},
    {"from_field": "Drawing.drawing_no", "from_prefix": "DWG-", "to_field": "SEC.ConfidentialDoc.source_doc", "to_prefix": "SECDOC-",
     "rule": "图纸 DWG- 经 SEC 涉密文档 SECDOC-.source_doc 关联（脱密对象）：调 SEC scanConfidentiality(source_doc='DWG-STR-001', source_system='DES')，勿把 SECDOC- 当 DWG- 传 DES",
     "example": "scanConfidentiality(source_doc='DWG-STR-001', source_system='DES') → SECDOC-001",
     "why": "图纸涉密检测/脱密跨 DES/SEC，按 source_doc 跳转"},
]
EPC_IDENTIFIER_CONVENTIONS = [
    {"entity": "Project", "field": "project_code", "prefix": "PRJ-", "example": "PRJ-IND-001",
     "note": "工程项目（PRJ-IND-/PRJ-BAT-/PRJ-CIV-；与 DES 方案 SCH- 按 scheme_no、与 CRM 合同 CT-SE- 按 client_code 关联）"},
    {"entity": "ScheduleActivity", "field": "activity_no", "prefix": "SCD-", "example": "SCD-001", "note": "进度工序（关键路径节点，含延误天）"},
    {"entity": "SiteHazard", "field": "hazard_no", "prefix": "HAZ-", "example": "HAZ-2026-001",
     "note": "现场隐患（感知类，含 sample_desc 画面描述；不生成图片/视频）"},
    {"entity": "ProjectDocument", "field": "doc_no", "prefix": "PDOC-", "example": "PDOC-IND-002",
     "note": "项目文档（合同/图纸/签证/验收；图纸类 linked_code 关联 DES DWG-，涉密类关联 SEC SECDOC-）"},
]
EPC_CODE_SPACE_MAPPINGS = [
    {"from_field": "Project.scheme_no", "from_prefix": "PRJ-", "to_field": "DES.Scheme.scheme_no", "to_prefix": "SCH-",
     "rule": "EPC 项目 PRJ-.scheme_no 字段值即 DES 方案码 SCH-，按 scheme_no 关联：调 DES getScheme(scheme_no=project.scheme_no)，勿把 PRJ- 当 SCH- 传 DES",
     "example": "getProject(project_code='PRJ-BAT-001').scheme_no='SCH-BAT-001' → DES getScheme('SCH-BAT-001')",
     "why": "项目挂设计方案，跨 EPC/DES 按 scheme_no 跳转"},
    {"from_field": "Project.cost_center_code", "from_prefix": "PRJ-", "to_field": "ERP.CostCenter.cc_code", "to_prefix": "CC-",
     "rule": "EPC 项目 cost_center_code 字段值即 ERP 成本中心码 CC-（如 PRJ-IND-001→CC-IND-001），按 cc_code 关联：调 ERP listCostCenters 收 CC-，勿把 PRJ- 当 CC- 传 ERP",
     "example": "getProject('PRJ-IND-001').cost_center_code='CC-IND-001' → ERP listCostCenters(cc_code='CC-IND-001')",
     "why": "项目挂成本中心，跨 EPC/ERP 按 cc_code 跳转"},
    {"from_field": "Project.client_code", "from_prefix": "PRJ-", "to_field": "CRM.SalesOrder.so_no", "to_prefix": "CT-SE-",
     "rule": "EPC 项目 client_code 字段值即 CRM 合同号 CT-SE-，按 contract_no/client_code 关联：调 CRM listSalesOrders 收 CT-SE-，勿把 PRJ- 当 CT-SE- 传 CRM",
     "example": "getProject('PRJ-IND-001').client_code='CT-SE-001' → CRM listSalesOrders(so_no='CT-SE-001')",
     "why": "项目挂合同，跨 EPC/CRM 按 client_code 跳转"},
    {"from_field": "ProjectDocument.linked_code", "from_prefix": "PDOC-", "to_field": "DES.Drawing.drawing_no", "to_prefix": "DWG-",
     "rule": "图纸类项目文档 PDOC-.linked_code 字段值即 DES 图纸码 DWG-，按 drawing_no 关联：调 DES getDrawing(drawing_no=doc.linked_code)，勿把 PDOC- 当 DWG- 传 DES",
     "example": "listProjectDocuments(project_code='PRJ-IND-001') 中 type='图纸' 的 linked_code='DWG-ARC-001' → DES getDrawing('DWG-ARC-001')",
     "why": "图纸交付物跨 EPC/DES，按 linked_code 跳转"},
]
SEC_IDENTIFIER_CONVENTIONS = [
    {"entity": "ConfidentialDoc", "field": "doc_no", "prefix": "SECDOC-", "example": "SECDOC-001",
     "note": "涉密文档（source_doc 关联 DES DWG- 或 EPC PDOC-；密级 机密/秘密/内部）"},
    {"entity": "ConfidentialMark", "field": "mark_no", "prefix": "SECMARK-", "example": "SECMARK-001", "note": "涉密标记（具体条文/图样定位）"},
    {"entity": "DesensitizationRecord", "field": "record_no", "prefix": "DESEN-", "example": "DESEN-2026-001", "note": "脱敏记录（source_doc 关联 DES DWG- 或 EPC PDOC-）"},
    {"entity": "BehaviorLog", "field": "log_no", "prefix": "BHV-", "example": "BHV-2026-001", "note": "行为日志（高频下载/非工作时间/尝试外发）"},
]
SEC_CODE_SPACE_MAPPINGS = [
    {"from_field": "ConfidentialDoc.source_doc", "from_prefix": "SECDOC-", "to_field": "DES.Drawing.drawing_no", "to_prefix": "DWG-",
     "rule": "涉密文档 SECDOC-.source_doc（source_system=DES）字段值即 DES 图纸码 DWG-，按 drawing_no 关联：调 SEC scanConfidentiality(source_doc='DWG-STR-001', source_system='DES')，勿把 SECDOC- 当 DWG- 传 DES",
     "example": "getConfidentialDoc(doc_no='SECDOC-001').source_doc='DWG-STR-001' → DES getDrawing('DWG-STR-001')",
     "why": "涉密检测/脱密按来源文档号跳转，SECDOC- ≠ DWG-"},
    {"from_field": "ConfidentialDoc.source_doc", "from_prefix": "SECDOC-", "to_field": "EPC.ProjectDocument.doc_no", "to_prefix": "PDOC-",
     "rule": "涉密文档 SECDOC-.source_doc（source_system=EPC）字段值即 EPC 项目文档码 PDOC-，按 doc_no 关联：调 SEC scanConfidentiality(source_doc='PDOC-BAT-001', source_system='EPC')，勿把 SECDOC- 当 PDOC- 传 EPC",
     "example": "getConfidentialDoc(doc_no='SECDOC-003').source_doc='PDOC-BAT-001' → EPC listProjectDocuments 找 PDOC-BAT-001",
     "why": "项目文档涉密按来源文档号跳转，SECDOC- ≠ PDOC-"},
]
ERP_IDENTIFIER_CONVENTIONS = [
    {"entity": "Material", "field": "material_code", "prefix": "M-", "example": "M-CON-001",
     "note": "工程物料（M-CON- 混凝土 / M-STE- 钢筋 / M-ARC- 建筑做法；与 DES 算量项 QTI-CON-/QTI-STE- prefix 转换关联）"},
    {"entity": "PurchaseOrder", "field": "po_no", "prefix": "POSE", "example": "POSE202607001", "note": "工程采购单"},
    {"entity": "Payable", "field": "payable_id", "prefix": "SEAP", "example": "SEAP202607001", "note": "应付（工程款，invoice_no 关联 CRM 发票 INV-）"},
    {"entity": "Voucher", "field": "voucher_no", "prefix": "BV-SE-", "example": "BV-SE-2026-0701",
     "note": "财务凭证（与 CRM 发票 INV- 按 invoice_no/voucher_no 关联）"},
    {"entity": "CostCenter", "field": "cc_code", "prefix": "CC-", "example": "CC-IND-001",
     "note": "成本中心（项目 CC-IND-/CC-BAT-/CC-CIV- 与 EPC project.cost_center_code 对齐；部门 CC-SE- 与 HRM 员工对齐）"},
    {"entity": "ProductionCost", "field": "cost_id", "prefix": "PC-SE-", "example": "PC-SE-202607001",
     "note": "项目成本（heat_no 承载项目号 PRJ-；work_order_no 引用 CRM 合同号 CT-SE-）"},
]
ERP_CODE_SPACE_MAPPINGS = [
    {"from_field": "Material.material_code", "from_prefix": "M-CON-", "to_field": "DES.QuantityItem.qi_no", "to_prefix": "QTI-CON-",
     "rule": "ERP 物料 M-CON-/M-STE- 与 DES 算量项 QTI-CON-/QTI-STE- 不同前缀但同实体，按 material_code 关联（prefix 转换 M-CON-→QTI-CON-）：调 ERP listMaterials 收 M-，调 DES listQuantityItems 收 QTI-，勿互传",
     "example": "listMaterials(material_code='M-CON-001') ↔ DES listQuantityItems（material_code='M-CON-001'）",
     "why": "物料与算量项 prefix 不同，直传必 404"},
    {"from_field": "Voucher.voucher_no", "from_prefix": "BV-SE-", "to_field": "CRM.Receivable.invoice_no", "to_prefix": "INV-",
     "rule": "ERP 凭证 BV-SE- 与 CRM 发票 INV- 不同码空间，按 invoice_no/voucher_no 关联：调 ERP listVouchers 收 BV-SE-，调 CRM listReceivables 收 INV-（INV202607001↔BV-SE-2026-0701），勿互传",
     "example": "listVouchers(voucher_no='BV-SE-2026-0701') vs listReceivables(invoice_no='INV202607001')",
     "why": "凭证与发票不同码空间，直传必 404"},
    {"from_field": "CostCenter.cc_code", "from_prefix": "CC-IND-", "to_field": "EPC.Project.cost_center_code", "to_prefix": "PRJ-",
     "rule": "ERP 成本中心 CC-IND-001 与 EPC 项目 PRJ-IND-001 按 cost_center_code 关联（PRJ-IND-001.cost_center_code='CC-IND-001'）：调 ERP listCostCenters 收 CC-，勿把 CC- 当 PRJ- 传 EPC",
     "example": "listCostCenters(cc_code='CC-IND-001') ↔ getProject('PRJ-IND-001').cost_center_code",
     "why": "项目挂成本中心，跨 ERP/EPC 按 cc_code 跳转"},
    {"from_field": "ProductionCost.heat_no", "from_prefix": "PC-SE-", "to_field": "EPC.Project.project_code", "to_prefix": "PRJ-",
     "rule": "项目成本 PC-SE-.heat_no 字段承载项目号 PRJ-，按 project_code 关联：调 ERP listProductionCosts 收 PC-SE-，其 heat_no 即 PRJ-，勿把 PC-SE- 当 PRJ- 传 EPC",
     "example": "listProductionCosts(cost_id='PC-SE-202607001').heat_no='PRJ-IND-001' → EPC getProject('PRJ-IND-001')",
     "why": "项目成本挂项目号，按 heat_no 字段跳转"},
]
HRM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Employee-Client", "field": "emp_no", "prefix": "SESA", "example": "SESA0100", "note": "客户经理岗员工（name 取自 CRM 负责人）"},
    {"entity": "Employee-Function", "field": "emp_no", "prefix": "SEOF", "example": "SEOF0200", "note": "设计/职能岗员工"},
    {"entity": "Department", "field": "dept_code", "prefix": "PD-", "example": "PD-DES", "note": "部门（PD-DES 设计研究院 / PD-COST 造价技经 / PD-EPC 等）"},
    {"entity": "Position", "field": "code", "prefix": "P-", "example": "P-DES", "note": "岗位（P-DES 设计师 / P-COST 造价工程师 / P-EPC 项目经理；与 ERP 物料 M- 不同码空间，按 prefix 区分勿互传）"},
    {"entity": "Recruitment", "field": "req_id", "prefix": "ASRC", "example": "ASRC20260000", "note": "招聘需求（position 关联岗位 P-）"},
    {"entity": "Resume", "field": "resume_id", "prefix": "SERM", "example": "SERM20260001", "note": "简历（position_code 关联岗位 P-）"},
    {"entity": "Meeting", "field": "meeting_id", "prefix": "SEMT", "example": "SEMT20260001", "note": "会议纪要（公文会议闭环核心数据）"},
]
HRM_CODE_SPACE_MAPPINGS = [
    {"from_field": "Recruitment.position", "from_prefix": "ASRC", "to_field": "Position.code", "to_prefix": "P-",
     "rule": "招聘需求 ASRC.position 字段值即岗位码 P-，按 position_code 关联：调 HRM listPositions 收 P-，勿把 ASRC 当 P- 传",
     "example": "listRecruitments(req_id='ASRC20260000').position='P-DES' → listPositions(code='P-DES')",
     "why": "招聘需求挂岗位，按 position 字段跳转"},
    {"from_field": "Position.code", "from_prefix": "P-", "to_field": "ERP.Material.material_code", "to_prefix": "M-",
     "rule": "岗位码 P- 与 ERP 物料 M- 不同码空间（P-DES 设计岗 vs M-CON- 混凝土），按 prefix 区分：调 HRM listPositions 收 P-，调 ERP listMaterials 收 M-，勿把 P- 当 M- 传 ERP 或反向",
     "example": "listPositions(code='P-DES')（HRM 岗位）vs listMaterials(material_code='M-CON-001')（ERP 物料）",
     "why": "P- 与 M- 同为短前缀易混，按 prefix 区分勿互传（同 agilesteel P- 教训）"},
]
CRM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Customer", "field": "customer_code", "prefix": "CLI-", "example": "CLI-001", "note": "工程业主/投资方"},
    {"entity": "Opportunity", "field": "opp_no", "prefix": "SEOPP", "example": "SEOPP20260011", "note": "投标商机（product_code 承载项目号 PRJ-）"},
    {"entity": "Quotation", "field": "quote_no", "prefix": "SEQT", "example": "SEQT20260007", "note": "投标报价"},
    {"entity": "SalesOrder-Contract", "field": "so_no", "prefix": "CT-SE-", "example": "CT-SE-001",
     "note": "中标合同（client_code 与 EPC project.client_code 对齐；product_code 承载项目号 PRJ-）"},
    {"entity": "Complaint-Dispute", "field": "case_id", "prefix": "DSP-", "example": "DSP-0001",
     "note": "履约争议/纠纷（product_code 承载项目号 PRJ-）"},
    {"entity": "Receivable", "field": "receivable_id", "prefix": "SEAR", "example": "SEAR20260013", "note": "工程回款"},
    {"entity": "ReceivableInvoice", "field": "invoice_no", "prefix": "INV", "example": "INV202607001", "note": "回款发票号（与 ERP 凭证 BV-SE- 按 invoice_no 关联）"},
]
CRM_CODE_SPACE_MAPPINGS = [
    {"from_field": "SalesOrder-Contract.so_no", "from_prefix": "CT-SE-", "to_field": "EPC.Project.client_code", "to_prefix": "PRJ-",
     "rule": "合同 CT-SE- 与 EPC 项目 PRJ- 按 client_code 关联（PRJ-IND-001.client_code='CT-SE-001'）：调 CRM listSalesOrders 收 CT-SE-，勿把 CT-SE- 当 PRJ- 传 EPC",
     "example": "listSalesOrders(so_no='CT-SE-001') ↔ getProject('PRJ-IND-001').client_code='CT-SE-001'",
     "why": "合同关联项目，跨 CRM/EPC 按 client_code 跳转"},
    {"from_field": "ReceivableInvoice.invoice_no", "from_prefix": "INV", "to_field": "ERP.Voucher.voucher_no", "to_prefix": "BV-SE-",
     "rule": "CRM 回款发票 INV- 与 ERP 凭证 BV-SE- 不同码空间，按 invoice_no/voucher_no 关联（INV202607001↔BV-SE-2026-0701）：调 CRM listReceivables 收 INV-，调 ERP listVouchers 收 BV-SE-，勿互传",
     "example": "listReceivables(invoice_no='INV202607001') vs listVouchers(voucher_no='BV-SE-2026-0701')",
     "why": "发票与凭证不同码空间，直传必 404"},
    {"from_field": "Complaint-Dispute.product_code", "from_prefix": "DSP-", "to_field": "EPC.Project.project_code", "to_prefix": "PRJ-",
     "rule": "履约争议 DSP-.product_code 字段值即 EPC 项目号 PRJ-，按 project_code 关联：调 EPC getProject(project_code=dispute.product_code)，勿把 DSP- 当 PRJ- 传 EPC",
     "example": "getComplaint(case_id='DSP-0001').product_code='PRJ-IND-001' → EPC getProject('PRJ-IND-001')",
     "why": "争议挂项目，按 product_code 字段跳转"},
]


# ───────────────────────── 对象/链接/动作类型（精简） ─────────────────────────

def _ot(name: str, pk: str, props: dict, desc: str = "", backing: str = "") -> dict:
    return {"objectType": name, "primaryKey": pk, "title": pk, "description": desc,
            "backingInterface": backing or f"mock.starexploration.{name.lower()}",
            "properties": {k: {"type": v if isinstance(v, str) else "string", "description": k} for k, v in props.items()}}

def _lt(name: str, parent: str, child: str, join: str, cross: bool = False, desc: str = "") -> dict:
    return {"linkType": name, "parent": parent, "child": child, "cardinality": "1:N",
            "joinField": join, "crossSystem": cross, "description": desc}

DES_OBJECT_TYPES = [
    _ot("Scheme", "scheme_no", {"scheme_no": "str", "name": "str", "domain": "str", "stage": "str", "invest_wan": "num"}, "设计方案"),
    _ot("Drawing", "drawing_no", {"drawing_no": "str", "scheme_no": "str", "discipline": "str", "compliance_flags": "str"}, "图纸"),
    _ot("Spec", "spec_code", {"spec_code": "str", "clause": "str", "is_mandatory": "bool", "requirement": "str"}, "规范条款"),
    _ot("QuantityItem", "qi_no", {"qi_no": "str", "scheme_no": "str", "material_code": "str", "qty": "num", "unit_cost": "num"}, "算量项"),
    _ot("Clash", "clash_no", {"clash_no": "str", "scheme_no": "str", "discipline_a": "str", "discipline_b": "str", "severity": "str"}, "跨专业碰撞"),
]
DES_LINK_TYPES = [
    _lt("drawing_to_scheme", "Drawing", "Scheme", "drawing_no/scheme_no", False, "图纸关联方案"),
    _lt("qi_to_scheme", "QuantityItem", "Scheme", "qi_no/scheme_no", False, "算量项关联方案"),
    _lt("qi_to_material", "QuantityItem", "ERP.Material", "material_code", True, "算量项关联 ERP 物料（prefix 转换）"),
    _lt("clash_to_scheme", "Clash", "Scheme", "clash_no/scheme_no", False, "碰撞关联方案"),
    _lt("scheme_to_project", "Scheme", "EPC.Project", "scheme_no", True, "方案关联 EPC 项目"),
    _lt("drawing_to_secdoc", "Drawing", "SEC.ConfidentialDoc", "drawing_no/source_doc", True, "图纸关联 SEC 涉密文档"),
]
DES_ACTION_TYPES: list = []

EPC_OBJECT_TYPES = [
    _ot("Project", "project_code", {"project_code": "str", "name": "str", "scheme_no": "str", "client_code": "str", "progress_pct": "num", "cost_center_code": "str"}, "工程项目"),
    _ot("ScheduleActivity", "activity_no", {"activity_no": "str", "project_code": "str", "name": "str", "delay_days": "int", "on_critical_path": "bool"}, "进度工序"),
    _ot("SiteHazard", "hazard_no", {"hazard_no": "str", "project_code": "str", "category": "str", "severity": "str", "sample_desc": "str"}, "现场隐患（感知类）"),
    _ot("ProjectDocument", "doc_no", {"doc_no": "str", "project_code": "str", "type": "str", "linked_code": "str", "confidential": "bool"}, "项目文档"),
]
EPC_LINK_TYPES = [
    _lt("activity_to_project", "ScheduleActivity", "Project", "activity_no/project_code", False, "工序关联项目"),
    _lt("hazard_to_project", "SiteHazard", "Project", "hazard_no/project_code", False, "隐患关联项目"),
    _lt("doc_to_project", "ProjectDocument", "Project", "doc_no/project_code", False, "文档关联项目"),
    _lt("project_to_scheme", "Project", "DES.Scheme", "scheme_no", True, "项目关联 DES 方案"),
    _lt("project_to_contract", "Project", "CRM.SalesOrder", "client_code/so_no", True, "项目关联 CRM 合同"),
    _lt("project_to_costcenter", "Project", "ERP.CostCenter", "cost_center_code/cc_code", True, "项目关联 ERP 成本中心"),
    _lt("doc_to_drawing", "ProjectDocument", "DES.Drawing", "linked_code/drawing_no", True, "图纸文档关联 DES 图纸"),
]
EPC_ACTION_TYPES: list = []

SEC_OBJECT_TYPES = [
    _ot("ConfidentialDoc", "doc_no", {"doc_no": "str", "source_doc": "str", "source_system": "str", "classification": "str", "sensitive_terms": "str"}, "涉密文档"),
    _ot("ConfidentialMark", "mark_no", {"mark_no": "str", "doc_no": "str", "classification": "str", "term": "str"}, "涉密标记"),
    _ot("DesensitizationRecord", "record_no", {"record_no": "str", "source_doc": "str", "source_system": "str", "classification_before": "str", "classification_after": "str"}, "脱敏记录"),
    _ot("BehaviorLog", "log_no", {"log_no": "str", "user": "str", "behavior": "str", "risk_level": "str", "off_hours": "bool"}, "行为日志"),
]
SEC_LINK_TYPES = [
    _lt("mark_to_doc", "ConfidentialMark", "ConfidentialDoc", "mark_no/doc_no", False, "标记关联涉密文档"),
    _lt("desen_to_source", "DesensitizationRecord", "ConfidentialDoc", "record_no/source_doc", False, "脱敏记录关联涉密文档"),
    _lt("secdoc_to_drawing", "ConfidentialDoc", "DES.Drawing", "source_doc/drawing_no", True, "涉密文档关联 DES 图纸"),
    _lt("secdoc_to_pdoc", "ConfidentialDoc", "EPC.ProjectDocument", "source_doc/doc_no", True, "涉密文档关联 EPC 项目文档"),
]
SEC_ACTION_TYPES: list = []

ERP_OBJECT_TYPES = [
    _ot("Material", "material_code", {"material_code": "str", "name": "str", "category": "str", "unit_cost": "num"}, "工程物料"),
    _ot("PurchaseOrder", "po_no", {"po_no": "str", "supplier_code": "str", "total_amount": "num", "status": "str"}, "工程采购单"),
    _ot("Inventory", "stock_id", {"stock_id": "str", "material_code": "str", "qty": "num", "warehouse": "str"}, "库存"),
    _ot("Payable", "payable_id", {"payable_id": "str", "supplier_code": "str", "invoice_no": "str", "amount": "num", "days_overdue": "int"}, "应付"),
    _ot("Voucher", "voucher_no", {"voucher_no": "str", "period": "str", "status": "str", "debit_total": "num"}, "财务凭证"),
    _ot("CostCenter", "cc_code", {"cc_code": "str", "name": "str", "type": "str"}, "成本中心"),
    _ot("ProductionCost", "cost_id", {"cost_id": "str", "heat_no": "str", "work_order_no": "str", "cost_center": "str", "total_cost": "num"}, "项目成本"),
]
ERP_LINK_TYPES = [
    _lt("po_to_material", "PurchaseOrder", "Material", "po_no/material_code", False, "采购单关联物料"),
    _lt("payable_to_po", "Payable", "PurchaseOrder", "payable_id/po_no", False, "应付关联采购单"),
    _lt("pc_to_costcenter", "ProductionCost", "CostCenter", "cost_id/cost_center", False, "项目成本关联成本中心"),
    _lt("material_to_qi", "Material", "DES.QuantityItem", "material_code", True, "物料关联 DES 算量项（prefix 转换）"),
    _lt("voucher_to_invoice", "Voucher", "CRM.Receivable", "voucher_no/invoice_no", True, "凭证关联 CRM 发票"),
    _lt("costcenter_to_project", "CostCenter", "EPC.Project", "cc_code/cost_center_code", True, "成本中心关联 EPC 项目"),
]
ERP_ACTION_TYPES: list = []

HRM_OBJECT_TYPES = [
    _ot("Department", "dept_code", {"dept_code": "str", "name": "str", "cost_center": "str"}, "部门"),
    _ot("Position", "code", {"code": "str", "name": "str", "grade": "str"}, "岗位"),
    _ot("Employee", "emp_no", {"emp_no": "str", "name": "str", "dept_code": "str", "position": "str", "cost_center": "str"}, "员工"),
    _ot("Attendance", "record_id", {"record_id": "str", "emp_no": "str", "date": "str", "status": "str"}, "考勤"),
    _ot("Leave", "leave_id", {"leave_id": "str", "emp_no": "str", "type": "str", "days": "num"}, "请假"),
    _ot("Payroll", "payroll_id", {"payroll_id": "str", "emp_no": "str", "period": "str", "net_pay": "num"}, "薪酬"),
    _ot("Performance", "perf_id", {"perf_id": "str", "emp_no": "str", "period": "str", "score": "num"}, "绩效"),
    _ot("Recruitment", "req_id", {"req_id": "str", "position": "str", "headcount": "int", "status": "str"}, "招聘需求"),
    _ot("Resume", "resume_id", {"resume_id": "str", "position_code": "str", "rating_score": "int", "tags": "str"}, "简历"),
    _ot("Meeting", "meeting_id", {"meeting_id": "str", "title": "str", "department": "str", "summary": "str"}, "会议纪要"),
]
HRM_LINK_TYPES = [
    _lt("employee_to_position", "Employee", "Position", "emp_no/position", False, "员工关联岗位"),
    _lt("employee_to_dept", "Employee", "Department", "emp_no/dept_code", False, "员工关联部门"),
    _lt("resume_to_position", "Resume", "Position", "resume_id/position_code", False, "简历关联岗位"),
    _lt("recruitment_to_position", "Recruitment", "Position", "req_id/position", False, "招聘需求关联岗位"),
    _lt("meeting_to_dept", "Meeting", "Department", "meeting_id/department", False, "会议关联部门"),
]
HRM_ACTION_TYPES: list = []

CRM_OBJECT_TYPES = [
    _ot("Customer", "customer_code", {"customer_code": "str", "name": "str", "type": "str", "credit_grade": "str"}, "工程业主/投资方"),
    _ot("Opportunity", "opp_no", {"opp_no": "str", "customer_code": "str", "product_code": "str", "amount": "num", "stage": "str"}, "投标商机"),
    _ot("Quotation", "quote_no", {"quote_no": "str", "customer_code": "str", "product_code": "str", "tiers": "str"}, "投标报价"),
    _ot("SalesOrder", "so_no", {"so_no": "str", "customer_code": "str", "product_code": "str", "contract_amount": "num", "risk_flags": "str"}, "中标合同"),
    _ot("Complaint", "case_id", {"case_id": "str", "customer_code": "str", "product_code": "str", "defect": "str", "severity": "str"}, "履约争议/纠纷"),
    _ot("Receivable", "receivable_id", {"receivable_id": "str", "customer_code": "str", "so_no": "str", "invoice_no": "str", "days_overdue": "int"}, "工程回款"),
]
CRM_LINK_TYPES = [
    _lt("so_to_customer", "SalesOrder", "Customer", "so_no/customer_code", False, "合同关联客户"),
    _lt("opp_to_customer", "Opportunity", "Customer", "opp_no/customer_code", False, "商机关联客户"),
    _lt("receivable_to_so", "Receivable", "SalesOrder", "receivable_id/so_no", False, "回款关联合同"),
    _lt("so_to_project", "SalesOrder", "EPC.Project", "so_no/client_code", True, "合同关联 EPC 项目"),
    _lt("invoice_to_voucher", "Receivable", "ERP.Voucher", "invoice_no/voucher_no", True, "回款发票关联 ERP 凭证"),
    _lt("dispute_to_project", "Complaint", "EPC.Project", "case_id/product_code", True, "履约争议关联 EPC 项目"),
]
CRM_ACTION_TYPES: list = []


# 跨系统闭环链接（8 条勘探设计闭环）
CROSS_LINK_TYPES = [
    _lt("scheme_to_project_closure", "DES.Scheme", "EPC.Project", "scheme_no", True,
        "设计方案 SCH-(DES)→工程项目 PRJ-(EPC)：方案转项目，按 scheme_no 关联"),
    _lt("quantity_to_procurement_closure", "DES.QuantityItem", "ERP.PurchaseOrder", "material_code", True,
        "算量项 QTI-(DES)→物料 M-(ERP，prefix 转换)→采购单 POSE-(ERP)→项目成本 PC-SE-"),
    _lt("drawing_delivery_closure", "DES.Drawing", "EPC.ProjectDocument", "drawing_no/linked_code", True,
        "图纸 DWG-(DES)→项目文档 PDOC-(EPC)：图纸交付物"),
    _lt("drawing_desensitization_closure", "DES.Drawing", "SEC.ConfidentialDoc", "drawing_no/source_doc", True,
        "图纸 DWG-(DES)→涉密文档 SECDOC-(SEC)→脱敏记录 DESEN-(SEC)：涉密检测→脱密闭环"),
    _lt("contract_project_closure", "CRM.SalesOrder", "EPC.Project", "so_no/client_code", True,
        "合同 CT-SE-(CRM)→工程项目 PRJ-(EPC)：按 client_code 关联"),
    _lt("invoice_voucher_closure", "CRM.Receivable", "ERP.Voucher", "invoice_no/voucher_no", True,
        "回款发票 INV-(CRM)→凭证 BV-SE-(ERP)：按 invoice_no 关联（对账闭环）"),
    _lt("procurement_cost_closure", "ERP.PurchaseOrder", "EPC.Project", "po_no/project_code", True,
        "采购 POSE-(ERP)→项目成本 PC-SE-(ERP)→项目 PRJ-(EPC)：成本归集"),
    _lt("recruitment_costcenter_closure", "HRM.Recruitment", "ERP.CostCenter", "position/cc_code", True,
        "招聘需求 ASRC-(HRM)→岗位 P-(HRM)→员工→成本中心 CC-(ERP)"),
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
    meta = {"system": folder.lower(), "source": "mock-starexploration"}
    files = [
        (f"{folder}/README.md", render_readme_md(label, folder, ots, lts, ats, summary), {**meta, "kind": "readme"}),
        (f"{folder}/object-types.md", render_object_types_md(f"{label} · 对象类型", f"由 mock {folder} 数据接口支撑。", ots), {**meta, "kind": "object-types"}),
        (f"{folder}/link-types.md", render_link_types_md(f"{label} · 链接类型", f"定义 {label} 内部及跨系统对象间关系。", lts), {**meta, "kind": "link-types"}),
        (f"{folder}/action-types.md", render_action_types_md(f"{label} · 动作类型", f"定义 {label} 上可执行的写操作。", ats), {**meta, "kind": "action-types"}),
    ]
    if convs:
        default_intro = (f"{label} 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——"
                         f"杜绝把算量项 QTI- 当物料 M- 传 ERP、把方案 SCH- 当项目 PRJ- 传 EPC、"
                         f"把发票 INV- 当凭证 BV-SE- 传 ERP、把岗位 P- 当物料 M- 传 ERP、"
                         f"把涉密文档 SECDOC- 当图纸 DWG- 传 DES 等 404。")
        files.append((f"{folder}/identifiers.md",
                      render_identifiers_md(f"{label} · 标识符与码空间映射",
                                             identifiers_intro or default_intro,
                                             convs, mappings or []),
                      {**meta, "kind": "identifiers"}))
    return files


# 组织级 7 个本体文件夹（6 域 + Cross）
ORG_SYSTEMS = [
    {"folder": "DES", "label": "DES 设计管理本体",
     "summary": "设计方案(SCH-)/图纸(DWG-)/规范条款(SPEC-)/算量项(QTI-)/跨专业碰撞(CLS-)；方案→项目、算量→物料、图纸→交付物/脱密对象跨系统关联。",
     "object_types": DES_OBJECT_TYPES, "link_types": DES_LINK_TYPES, "action_types": DES_ACTION_TYPES,
     "conventions": DES_IDENTIFIER_CONVENTIONS, "code_mappings": DES_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "DES 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把算量项 QTI- 当物料 M- 传 ERP（prefix 转换 QTI-CON-→M-CON-）、把方案 SCH- 当项目 PRJ- 传 EPC、把图纸 DWG- 当涉密文档 SECDOC- 传 SEC 等 404。"},
    {"folder": "EPC", "label": "EPC 工程总承包本体",
     "summary": "工程项目(PRJ-)/进度工序(SCD-)/现场隐患(HAZ-，感知类)/项目文档(PDOC-)；项目挂方案 SCH-/合同 CT-SE-/成本中心 CC-，图纸文档挂 DES DWG-。",
     "object_types": EPC_OBJECT_TYPES, "link_types": EPC_LINK_TYPES, "action_types": EPC_ACTION_TYPES,
     "conventions": EPC_IDENTIFIER_CONVENTIONS, "code_mappings": EPC_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "EPC 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把项目 PRJ- 当方案 SCH- 传 DES、把成本中心 CC- 当项目 PRJ- 传 EPC、把项目文档 PDOC- 当图纸 DWG- 传 DES、把合同 CT-SE- 当项目 PRJ- 传 EPC 等 404。"},
    {"folder": "SEC", "label": "SEC 保密与合规本体",
     "summary": "涉密文档(SECDOC-)/涉密标记(SECMARK-)/脱敏记录(DESEN-)/行为日志(BHV-)；涉密文档按来源 DES DWG-/EPC PDOC- 关联，脱密闭环。",
     "object_types": SEC_OBJECT_TYPES, "link_types": SEC_LINK_TYPES, "action_types": SEC_ACTION_TYPES,
     "conventions": SEC_IDENTIFIER_CONVENTIONS, "code_mappings": SEC_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "SEC 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把涉密文档 SECDOC- 当图纸 DWG- 传 DES、把 SECDOC- 当项目文档 PDOC- 传 EPC 等 404；涉密检测/脱密按来源文档号跳转。"},
    {"folder": "ERP", "label": "ERP 资源计划本体",
     "summary": "工程物料(M-CON-/M-STE-/M-ARC-)/采购单(POSE-)/应付(SEAP)/凭证(BV-SE-)/成本中心(CC-IND-/CC-SE-)/项目成本(PC-SE-)；凭证与回款发票 INV- 跨系统对账。",
     "object_types": ERP_OBJECT_TYPES, "link_types": ERP_LINK_TYPES, "action_types": ERP_ACTION_TYPES,
     "conventions": ERP_IDENTIFIER_CONVENTIONS, "code_mappings": ERP_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "ERP 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把物料 M- 当算量项 QTI- 传 DES（prefix 转换 M-CON-→QTI-CON-）、把凭证 BV-SE- 当发票 INV- 传 CRM、把成本中心 CC- 当项目 PRJ- 传 EPC、把项目成本 PC-SE- 当项目 PRJ- 传 EPC 等 404。"},
    {"folder": "HRM", "label": "HRM 人力资源本体",
     "summary": "部门(PD-DES/PD-COST/...)/岗位(P-DES/P-COST/...)/员工(SESA/SEOF)/考勤/请假/薪酬/绩效/招聘需求(ASRC)/简历(SERM)/会议纪要(SEMT)；岗位 P- 与 ERP 物料 M- 不同码空间。",
     "object_types": HRM_OBJECT_TYPES, "link_types": HRM_LINK_TYPES, "action_types": HRM_ACTION_TYPES,
     "conventions": HRM_IDENTIFIER_CONVENTIONS, "code_mappings": HRM_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "HRM 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把岗位 P- 当物料 M- 传 ERP（同 agilesteel P- 教训，按 prefix 区分勿互传）、把招聘需求 ASRC 当岗位 P- 传、把员工 emp_no 当成本中心 CC- 传 ERP 等 404。"},
    {"folder": "CRM", "label": "CRM 客户与投标本体",
     "summary": "工程业主(CLI-)/投标商机(SEOPP)/投标报价(SEQT)/中标合同(CT-SE-)/履约争议(DSP-)/工程回款(SEAR)/回款发票(INV-)；合同关联项目、发票关联凭证。",
     "object_types": CRM_OBJECT_TYPES, "link_types": CRM_LINK_TYPES, "action_types": CRM_ACTION_TYPES,
     "conventions": CRM_IDENTIFIER_CONVENTIONS, "code_mappings": CRM_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "CRM 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把合同 CT-SE- 当项目 PRJ- 传 EPC、把回款发票 INV- 当凭证 BV-SE- 传 ERP、把履约争议 DSP- 当项目 PRJ- 传 EPC 等 404。"},
    {"folder": "Cross", "label": "跨系统闭环本体",
     "summary": "8 条跨系统闭环：方案→项目；算量→物料→采购→项目成本；图纸→项目文档；图纸→涉密检测→脱密；合同→项目；发票→凭证（对账）；采购→项目成本→项目；招聘→岗位→员工→成本中心。",
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
            raise RuntimeError(f"组织 slug='{ORG_SLUG}' 不存在，请先运行 seed_starexploration_org.py。")
        logger.info("seed_starexploration_ontology_org", slug=org.slug, org_id=str(org.id))

        org_results = await _seed_scope(db, org.id, "organization", None, ORG_SYSTEMS, "organization")
        overall["scopes"].append({"scope": "organization", "systems": org_results})

        await db.commit()
    return overall


def _print_report(result: dict) -> None:
    print("\n" + "=" * 72)
    print("星途勘探本体导入完成（覆盖式幂等，可安全重复执行）")
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
    print("位置：管理端「星途勘探」组织 → 本体 → DES/EPC/SEC/ERP/HRM/CRM/Cross（组织级）")
    print("6 域含 identifiers.md（标识符约定 + 跨码空间映射），agent 推理时按用户 scope 注入。")
    print("=" * 72)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
