"""为「敏睿钢铁」组织创建本体文件（9 组织级域 + Cross + 部门/团队级）。

每个域 4 文件：README/object-types/link-types/action-types；PLM/SCM/ERP/MES/CRM/HRM/EQM/EMS/EHS
各含 identifiers.md（标识符约定 + 跨码空间映射规则）—— 防猜码 404 的 no-guessing 骨架。
沿用 agileac 的 render_identifiers_md + _files_for + _seed_scope 模式。

用法:
    docker cp demo/agilesteel/scripts/seed_agilesteel_ontology.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_agilesteel_ontology.py
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
from app.models.department import Department  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.team import Team  # noqa: E402
from app.schemas.ontology import OntologyFileCreate  # noqa: E402
from app.services.ontology_store_service import create_folder, upsert_file  # noqa: E402

logger = structlog.get_logger()

ORG_SLUG = "agilesteel"
ORG_NAME_FALLBACK = "敏睿钢铁"


# ───────────────────────── 标识符约定（no-guessing 骨架） ─────────────────────────

PLM_IDENTIFIER_CONVENTIONS = [
    {"entity": "SteelGrade", "field": "grade_code", "prefix": "P-ST-", "example": "P-ST-Q345B",
     "note": "钢种牌号（与 HR 岗位 P- 不同码空间，按第二段区分）"},
    {"entity": "DefectHistory", "field": "case_id", "prefix": "DF-AS-", "example": "DF-AS-2026001",
     "note": "钢种质量历史案例（与 MES 缺陷 DF 裸码不同码空间）"},
    {"entity": "CostLedger", "field": "ledger_id", "prefix": "CL-AS-", "example": "CL-AS-202606-Q345B",
     "note": "分钢种成本台账"},
]
PLM_CODE_SPACE_MAPPINGS = [
    {"from_field": "SteelGrade.grade_code", "from_prefix": "P-ST-", "to_field": "HRM.Position.code", "to_prefix": "P-",
     "rule": "P- 单独=HR 岗位（P-MELT/P-EQP）；P-ST-=PLM 钢种。调 PLM getSteelGrade 只收 P-ST-，调 HRM listPositions 只收 P-，勿互传",
     "example": "getSteelGrade(grade_code='P-ST-Q345B') ✓ vs listPositions(position='P-MELT') ✓",
     "why": "杜绝把岗位码 P-MELT 当钢种传 PLM 端点 404"},
    {"from_field": "DefectHistory.case_id", "from_prefix": "DF-AS-", "to_field": "MES.Defect.defect_id", "to_prefix": "DF",
     "rule": "MES 缺陷 DF（裸码 DF20260701）回流 PLM 钢种历史 DF-AS-，按 steel_grade/P-ST- 关联勿直传 DF",
     "example": "listDefectHistory(style_code='P-ST-Q345B') 取该钢种历史案例，MES defect_id='DF20260701' 另码空间",
     "why": "杜绝把 MES 缺陷号当 PLM 案例号 404"},
]

SCM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Supplier", "field": "code", "prefix": "S-STEEL-", "example": "S-STEEL-ORE-01",
     "note": "钢铁料供应商（铁矿石/焦炭/废钢/合金/耐材/物流）"},
    {"entity": "Quotation", "field": "quotation_no", "prefix": "ASQ", "example": "ASQ202607001",
     "note": "大宗原料报价单"},
    {"entity": "ScrapGrade", "field": "scrap_code", "prefix": "SCR-", "example": "SCR-HMS1",
     "note": "废钢分级（重废1/2 型/破碎料/车屑）"},
]
SCM_CODE_SPACE_MAPPINGS = [
    {"from_field": "ScrapGrade.scrap_code", "from_prefix": "SCR-", "to_field": "ERP.Material.material_code", "to_prefix": "M-SCR-",
     "rule": "SCM 废钢分级 SCR- 对齐 ERP 采购物料 M-SCR-（如 SCR-HMS1 ↔ M-SCR-HMS1），调 getScrapPrice 收 SCR-，调 ERP listMaterials 收 M-SCR-",
     "example": "getScrapPrice(scrap_code='SCR-HMS1') vs listMaterials(material_code='M-SCR-HMS1')",
     "why": "废钢判级与采购物料对齐，不同前缀勿直传"},
]

ERP_IDENTIFIER_CONVENTIONS = [
    {"entity": "Material", "field": "material_code", "prefix": "M-", "example": "M-ST-Q345B-Billet",
     "note": "钢铁料（钢坯 M-ST-*-Billet / 成品 M-ST-*-Bar / 铁矿石 M-ORE / 焦炭 M-COKE / 废钢 M-SCR / 合金 M-ALY）"},
    {"entity": "Voucher", "field": "voucher_no", "prefix": "BV-AS-", "example": "BV-AS-2026-0512",
     "note": "财务凭证（跨系统 SSO 演示）"},
    {"entity": "Payable", "field": "payable_id", "prefix": "ASAP", "example": "ASAP20260001", "note": "应付"},
    {"entity": "PurchaseOrder", "field": "po_no", "prefix": "ASPO", "example": "ASPO20260001", "note": "采购订单"},
    {"entity": "ProductionCost", "field": "cost_id", "prefix": "PC-AS-", "example": "PC-AS-2026062901",
     "note": "分钢种炉次生产成本（含 heat_no + steel_grade）"},
]
ERP_CODE_SPACE_MAPPINGS = [
    {"from_field": "ProductionCost.heat_no", "from_prefix": "HT", "to_field": "MES.Heat.heat_no", "to_prefix": "HT",
     "rule": "ERP 炉次成本 PC-AS- 按 heat_no 关联 MES 炉次 HT，对账按 heat_no 直查勿转换",
     "example": "listProductionCosts 取 cost_id='PC-AS-2026062901' heat_no='HT2026062901' → MES getHeat(heat_no='HT2026062901')",
     "why": "炉次成本对账跨 ERP/MES 按 heat_no 一致"},
    {"from_field": "Voucher.voucher_no", "from_prefix": "BV-AS-", "to_field": "PLM.Voucher.voucher_no", "to_prefix": "BV-AS-",
     "rule": "凭证跨系统一致 BV-AS-，对账/SSO 直交叉查",
     "example": "ERP listVouchers(voucher_no='BV-AS-2026-0512') = PLM 凭证同号",
     "why": "凭证跨系统一致，SSO 免登跨查"},
]

MES_IDENTIFIER_CONVENTIONS = [
    {"entity": "Heat", "field": "heat_no", "prefix": "HT", "example": "HT2026062901",
     "note": "炉次（钢铁主实体：一炉钢，回挂钢种 P-ST- + 配料废钢 M-SCR- + 转炉 EQ-CV-）"},
    {"entity": "WorkOrder", "field": "work_order_no", "prefix": "SWO", "example": "SWO202607001", "note": "钢铁工单（Steel WorkOrder）"},
    {"entity": "ProductionOrder", "field": "order_no", "prefix": "SPO", "example": "SPO20260701", "note": "钢铁生产订单（由 CRM ASSO 驱动按单排产）"},
    {"entity": "Defect", "field": "defect_id", "prefix": "DF", "example": "DF20260701", "note": "钢材表面缺陷（8 类，裸码；与 PLM DF-AS- 不同码空间）"},
    {"entity": "Equipment", "field": "code", "prefix": "EQ-", "example": "EQ-CV-2", "note": "设备（与 EQM 共享码空间，同码不同系统）"},
]
MES_CODE_SPACE_MAPPINGS = [
    {"from_field": "Heat.steel_grade", "from_prefix": "HT", "to_field": "PLM.SteelGrade.grade_code", "to_prefix": "P-ST-",
     "rule": "炉次 steel_grade 字段值即 PLM 钢种码 P-ST-，调 PLM getSteelGrade(grade_code=heat.steel_grade)",
     "example": "getHeat(heat_no='HT2026062901').steel_grade='P-ST-Q345B' → getSteelGrade('P-ST-Q345B')",
     "why": "炉次回挂钢种主数据，按 steel_grade 直查"},
    {"from_field": "Heat.charging_scrap", "from_prefix": "HT", "to_field": "SCM.ScrapGrade.scrap_code", "to_prefix": "SCR-",
     "rule": "炉次 charging_scrap 字段值即 ERP 采购物料码 M-SCR-（对应 SCM 废钢 SCR-），配料追溯按此关联",
     "example": "getHeat().charging_scrap='M-SCR-HMS1' → SCM getScrapPrice('SCR-HMS1')（去 M-SCR-→SCR-）",
     "why": "废钢配料追溯跨 SCM，注意 M-SCR- vs SCR- 前缀转换"},
    {"from_field": "Equipment.code", "from_prefix": "EQ-", "to_field": "EQM.Equipment.code", "to_prefix": "EQ-",
     "rule": "MES 设备 EQ- 与 EQM 共享码空间，同码直查勿转换（EQM 是 MES 设备的预测性维护外延）",
     "example": "MES getEquipment(code='EQ-CV-2') + EQM getEquipment(code='EQ-CV-2') 同码",
     "why": "设备码空间共享，闭环不冲突"},
    {"from_field": "Defect.defect_id", "from_prefix": "DF", "to_field": "PLM.DefectHistory.case_id", "to_prefix": "DF-AS-",
     "rule": "MES 缺陷 DF 裸码回流 PLM 钢种历史 DF-AS-，按 steel_grade/P-ST- 关联勿直传 DF",
     "example": "MES listDefects(defect_id='DF20260701') vs PLM listDefectHistory(style_code='P-ST-Q345B')",
     "why": "杜绝把 DF 当 DF-AS- 传 404"},
]

CRM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Customer", "field": "code", "prefix": "C-AS-", "example": "C-AS-PROJ-01", "note": "客户（工程项目/钢贸/直供/海外）"},
    {"entity": "SalesOrder", "field": "so_no", "prefix": "ASSO", "example": "ASSO202607001", "note": "销售订单（驱动 MES 按单排产 SPO）"},
    {"entity": "Complaint", "field": "complaint_no", "prefix": "CR-AS-", "example": "CR-AS-2026-0001", "note": "钢材质量异议"},
    {"entity": "Receivable", "field": "receivable_id", "prefix": "ASAR", "example": "ASAR20260001", "note": "应收（与 ERP 共享 ASINV 发票号）"},
]
CRM_CODE_SPACE_MAPPINGS = [
    {"from_field": "SalesOrder.so_no", "from_prefix": "ASSO", "to_field": "MES.ProductionOrder.sales_order_no", "to_prefix": "SPO",
     "rule": "CRM 销售订单 ASSO 驱动 MES 生产订单 SPO（按单排产），MES production_order.sales_order_no=ASSO",
     "example": "getSalesOrder(so_no='ASSO202607001') → MES listProductionOrders 按 sales_order_no 关联",
     "why": "销售订单驱动排产，跨 CRM/MES 关联"},
]

HRM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Employee", "field": "emp_no", "prefix": "ASSA/ASOF", "example": "ASSA001/ASOF201",
     "note": "员工（ASSA 车间岗 / ASOF 职能岗）"},
    {"entity": "Position", "field": "code", "prefix": "P-", "example": "P-MELT", "note": "岗位（P-MELT 炼钢工程师等；与 PLM 钢种 P-ST- 共享 P- 前缀）"},
    {"entity": "Recruitment", "field": "req_id", "prefix": "ASRC", "example": "ASRC2026001", "note": "招聘需求"},
    {"entity": "Resume", "field": "resume_id", "prefix": "ASRM", "example": "ASRM20260001", "note": "简历"},
]
HRM_CODE_SPACE_MAPPINGS = [
    {"from_field": "Position.code", "from_prefix": "P-", "to_field": "PLM.SteelGrade.grade_code", "to_prefix": "P-ST-",
     "rule": "P- 单独=HR 岗位（P-MELT/P-EQP/P-ENE）；P-ST-=PLM 钢种。listResumesByPosition(position='P-MELT') ✓，getSteelGrade('P-ST-Q345B') ✓，勿互传",
     "example": "P-MELT（炼钢工程师）vs P-ST-Q345B（钢种），按第二段区分",
     "why": "杜绝岗位码当钢种传 PLM 404"},
]

EQM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Equipment", "field": "code", "prefix": "EQ-", "example": "EQ-CV-2", "note": "关键设备（高炉 EQ-BF-/转炉 EQ-CV-/连铸 EQ-CCM-/轧机 EQ-RM-，与 MES 共享码空间）"},
    {"entity": "SparePart", "field": "code", "prefix": "SP-", "example": "SP-CV-TUYERE", "note": "备件（氧枪枪头/轧辊/冷却壁/结晶器/电极）"},
    {"entity": "FaultHistory", "field": "fault_id", "prefix": "EQF", "example": "EQF20260301", "note": "故障历史（MTBF/MTTR）"},
    {"entity": "MaintenancePlan", "field": "plan_no", "prefix": "MP", "example": "MP202607001", "note": "预测性维护建议"},
]
EQM_CODE_SPACE_MAPPINGS = [
    {"from_field": "Equipment.code", "from_prefix": "EQ-", "to_field": "MES.Equipment.code", "to_prefix": "EQ-",
     "rule": "EQM 设备 EQ- 与 MES 共享码空间，同码直查（EQM 是 MES 设备预测性维护外延）",
     "example": "EQM predictEquipmentFailure(code='EQ-CV-2') + MES getEquipment(code='EQ-CV-2') 同码",
     "why": "设备码空间共享，闭环不冲突，勿转换"},
]

EMS_IDENTIFIER_CONVENTIONS = [
    {"entity": "Meter", "field": "code", "prefix": "EM-", "example": "EM-GAS-CV1", "note": "能源介质计量点（煤气/蒸汽/电力/氧气/氮气/水）"},
    {"entity": "Emission", "field": "source_code", "prefix": "EMS-", "example": "EMS-SO2-SINTER", "note": "排放源（SO2/NOx/颗粒物/CO2）"},
    {"entity": "DispatchPlan", "field": "plan_no", "prefix": "EDP", "example": "EDP202607001", "note": "能源调度方案"},
    {"entity": "Alarm", "field": "alarm_no", "prefix": "EA", "example": "EA20260701A", "note": "能源/排放预警"},
]
EMS_CODE_SPACE_MAPPINGS: list = []

EHS_IDENTIFIER_CONVENTIONS = [
    {"entity": "Hazard", "field": "code", "prefix": "HD-", "example": "HD20260001", "note": "隐患台账（含整改闭环状态，equipment_code 关联 EQ-）"},
    {"entity": "Violation", "field": "code", "prefix": "VIO-", "example": "VIO20260701", "note": "违章记录（AI 识别+人工核实）"},
    {"entity": "Inspection", "field": "code", "prefix": "INS-", "example": "INS20260701", "note": "巡检记录"},
]
EHS_CODE_SPACE_MAPPINGS = [
    {"from_field": "Hazard.equipment_code", "from_prefix": "HD-", "to_field": "EQM.Equipment.code", "to_prefix": "EQ-",
     "rule": "隐患 equipment_code 关联 EQ- 设备码，隐患闭环到设备预测性维护",
     "example": "getHazard(code='HD20260002').equipment_code='EQ-BF-1' → EQM getEquipment('EQ-BF-1')",
     "why": "隐患挂设备，闭环到设备维护"},
]


# ───────────────────────── 对象/链接/动作类型（精简） ─────────────────────────

def _ot(name: str, pk: str, props: dict, desc: str = "", backing: str = "") -> dict:
    return {"objectType": name, "primaryKey": pk, "title": pk, "description": desc,
            "backingInterface": backing or f"mock.agilesteel.{name.lower()}",
            "properties": {k: {"type": v if isinstance(v, str) else "string", "description": k} for k, v in props.items()}}

def _lt(name: str, parent: str, child: str, join: str, cross: bool = False, desc: str = "") -> dict:
    return {"linkType": name, "parent": parent, "child": child, "cardinality": "1:N",
            "joinField": join, "crossSystem": cross, "description": desc}

PLM_OBJECT_TYPES = [
    _ot("SteelGrade", "grade_code", {"grade_code": "str", "name": "str", "category": "str", "standard": "str", "yield_strength": "str"}, "钢种主数据"),
    _ot("DefectHistory", "case_id", {"case_id": "str", "style_code": "str", "defect_type": "str", "root_cause": "str"}, "钢种质量历史案例"),
    _ot("CostLedger", "ledger_id", {"ledger_id": "str", "style_code": "str", "unit_cost": "num", "period": "str"}, "分钢种成本台账"),
]
PLM_LINK_TYPES = [_lt("grade_has_defect_history", "SteelGrade", "DefectHistory", "style_code/grade_code", False, "钢种关联质量历史")]
PLM_ACTION_TYPES: list = []

SCM_OBJECT_TYPES = [
    _ot("Supplier", "code", {"code": "str", "name": "str", "category": "str", "rating": "str"}, "钢铁料供应商"),
    _ot("Quotation", "quotation_no", {"quotation_no": "str", "supplier_code": "str", "material_code": "str", "unit_price": "num"}, "大宗原料报价"),
    _ot("ScrapGrade", "scrap_code", {"scrap_code": "str", "name": "str", "price_per_t": "num", "applicable_steel": "str"}, "废钢分级"),
]
SCM_LINK_TYPES = [_lt("quotation_by_supplier", "Supplier", "Quotation", "supplier_code", False, "供应商报价")]
SCM_ACTION_TYPES: list = []

ERP_OBJECT_TYPES = [
    _ot("Material", "material_code", {"material_code": "str", "name": "str", "category": "str", "unit_cost": "num"}, "钢铁料主数据"),
    _ot("Voucher", "voucher_no", {"voucher_no": "str", "period": "str", "status": "str", "debit_total": "num"}, "财务凭证"),
    _ot("ProductionCost", "cost_id", {"cost_id": "str", "heat_no": "str", "steel_grade": "str", "total_cost": "num"}, "分钢种炉次成本"),
    _ot("Payable", "payable_id", {"payable_id": "str", "supplier_code": "str", "amount": "num", "days_overdue": "int"}, "应付"),
]
ERP_LINK_TYPES = [_lt("cost_by_heat", "ProductionCost", "Material", "heat_no", True, "炉次成本按 heat_no 关联")]
ERP_ACTION_TYPES: list = []

MES_OBJECT_TYPES = [
    _ot("Heat", "heat_no", {"heat_no": "str", "steel_grade": "str", "converter_code": "str", "endpoint_carbon_actual": "num", "hit_carbon_temp": "bool"}, "炉次（钢铁主实体）"),
    _ot("WorkOrder", "work_order_no", {"work_order_no": "str", "order_no": "str", "product_code": "str", "plan_qty": "num", "status": "str"}, "钢铁工单"),
    _ot("ProductionOrder", "order_no", {"order_no": "str", "sales_order_no": "str", "product_code": "str", "plan_qty": "num"}, "生产订单"),
    _ot("Defect", "defect_id", {"defect_id": "str", "work_order_no": "str", "product_code": "str", "defect_name": "str", "severity": "str"}, "钢材表面缺陷"),
    _ot("Equipment", "code", {"code": "str", "name": "str", "type": "str", "status": "str"}, "设备（与 EQM 共享码空间）"),
]
MES_LINK_TYPES = [
    _lt("heat_to_workorder", "Heat", "WorkOrder", "steel_grade", False, "炉次关联工单"),
    _lt("po_to_workorder", "ProductionOrder", "WorkOrder", "order_no", False, "生产订单关联工单"),
    _lt("defect_to_workorder", "Defect", "WorkOrder", "work_order_no", False, "缺陷关联工单"),
]
MES_ACTION_TYPES: list = []

CRM_OBJECT_TYPES = [
    _ot("Customer", "code", {"code": "str", "name": "str", "type": "str", "credit_grade": "str"}, "客户"),
    _ot("SalesOrder", "so_no", {"so_no": "str", "customer_code": "str", "product_code": "str", "qty": "num", "status": "str"}, "销售订单"),
    _ot("Complaint", "complaint_id", {"complaint_id": "str", "complaint_no": "str", "work_order_no": "str", "defect": "str"}, "钢材质量异议"),
    _ot("Receivable", "receivable_id", {"receivable_id": "str", "customer_code": "str", "so_no": "str", "amount": "num", "days_overdue": "int"}, "应收"),
]
CRM_LINK_TYPES = [
    _lt("so_to_customer", "SalesOrder", "Customer", "customer_code", False, "订单关联客户"),
    _lt("complaint_to_wo", "Complaint", "MES.WorkOrder", "work_order_no", True, "异议关联 MES 工单"),
    _lt("receivable_to_so", "Receivable", "SalesOrder", "so_no", False, "应收关联订单"),
]
CRM_ACTION_TYPES: list = []

HRM_OBJECT_TYPES = [
    _ot("Employee", "emp_no", {"emp_no": "str", "name": "str", "department": "str", "position": "str"}, "员工"),
    _ot("Position", "code", {"code": "str", "name": "str", "grade": "str", "level": "int"}, "岗位"),
    _ot("Resume", "resume_id", {"resume_id": "str", "position_code": "str", "rating_score": "int", "tags": "str"}, "简历"),
    _ot("Recruitment", "req_id", {"req_id": "str", "position": "str", "headcount": "int", "status": "str"}, "招聘需求"),
]
HRM_LINK_TYPES = [
    _lt("resume_to_position", "Resume", "Position", "position_code/code", False, "简历关联岗位"),
    _lt("recruitment_to_position", "Recruitment", "Position", "position/code", False, "招聘需求关联岗位"),
]
HRM_ACTION_TYPES: list = []

EQM_OBJECT_TYPES = [
    _ot("Equipment", "code", {"code": "str", "name": "str", "type": "str", "criticality": "str", "status": "str"}, "关键设备（与 MES 共享码空间）"),
    _ot("SparePart", "code", {"code": "str", "name": "str", "fit_equipment": "str", "stock_qty": "int", "safety_stock": "int"}, "备件"),
    _ot("FaultHistory", "fault_id", {"fault_id": "str", "equipment_code": "str", "fault_desc": "str", "downtime_hours": "num"}, "故障历史"),
    _ot("MaintenancePlan", "plan_no", {"plan_no": "str", "equipment_code": "str", "confidence": "num", "status": "str"}, "预测性维护建议"),
]
EQM_LINK_TYPES = [
    _lt("fault_to_equipment", "FaultHistory", "Equipment", "equipment_code", False, "故障关联设备"),
    _lt("plan_to_equipment", "MaintenancePlan", "Equipment", "equipment_code", False, "维护建议关联设备"),
    _lt("eqm_eq_mes", "Equipment", "MES.Equipment", "code", True, "EQM 设备与 MES 设备同码空间"),
]
EQM_ACTION_TYPES: list = []

EMS_OBJECT_TYPES = [
    _ot("Meter", "code", {"code": "str", "name": "str", "media": "str", "process": "str"}, "能源计量点"),
    _ot("MediaBalance", "process", {"process": "str", "media": "str", "supply": "num", "demand": "num", "gap": "num"}, "介质供需平衡"),
    _ot("Emission", "source_code", {"source_code": "str", "pollutant": "str", "value": "num", "limit": "num", "status": "str"}, "排放监测"),
    _ot("DispatchPlan", "plan_no", {"plan_no": "str", "media": "str", "status": "str", "expected_save_kgce": "num"}, "调度方案"),
]
EMS_LINK_TYPES = [_lt("balance_to_meter", "MediaBalance", "Meter", "media", False, "平衡关联计量点")]
EMS_ACTION_TYPES: list = []

EHS_OBJECT_TYPES = [
    _ot("Hazard", "code", {"code": "str", "area": "str", "level": "str", "status": "str", "equipment_code": "str"}, "隐患台账"),
    _ot("Violation", "code", {"code": "str", "type": "str", "severity": "str", "status": "str"}, "违章记录"),
    _ot("SafetyRisk", "area", {"area": "str", "level": "str", "exposed_persons": "int"}, "风险点分级"),
]
EHS_LINK_TYPES = [_lt("hazard_to_equipment", "Hazard", "EQM.Equipment", "equipment_code", True, "隐患关联设备")]
EHS_ACTION_TYPES: list = []


# 跨系统闭环链接（8 条钢铁物理流）
CROSS_LINK_TYPES = [
    _lt("sales_order_drives_production", "CRM.SalesOrder", "MES.ProductionOrder", "so_no/sales_order_no", True, "销售订单 ASSO 驱动按单排产 SPO"),
    _lt("heat_to_cost", "MES.Heat", "ERP.ProductionCost", "heat_no", True, "炉次 HT 归集炉次成本 PC-AS-"),
    _lt("heat_to_grade", "MES.Heat", "PLM.SteelGrade", "steel_grade/grade_code", True, "炉次回挂钢种主数据 P-ST-"),
    _lt("scrap_to_heat", "SCM.ScrapGrade", "MES.Heat", "scrap_code/charging_scrap", True, "废钢配料 SCR-→炉次装料"),
    _lt("eq_shared", "MES.Equipment", "EQM.Equipment", "code", True, "设备码空间共享 EQ-（同码不同系统）"),
    _lt("defect_to_history", "MES.Defect", "PLM.DefectHistory", "defect_id/case_id", True, "缺陷 DF 回流钢种历史 DF-AS-"),
    _lt("meter_to_heat", "EMS.Meter", "MES.Heat", "process/heat_no", True, "工序能耗对标"),
    _lt("hazard_to_equipment", "EHS.Hazard", "EQM.Equipment", "equipment_code", True, "隐患挂设备闭环"),
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
                convs: list | None = None, mappings: list | None = None):
    meta = {"system": folder.lower(), "source": "mock-agilesteel"}
    files = [
        (f"{folder}/README.md", render_readme_md(label, folder, ots, lts, ats, summary), {**meta, "kind": "readme"}),
        (f"{folder}/object-types.md", render_object_types_md(f"{label} · 对象类型", f"由 mock {folder} 数据接口支撑。", ots), {**meta, "kind": "object-types"}),
        (f"{folder}/link-types.md", render_link_types_md(f"{label} · 链接类型", f"定义 {label} 内部及跨系统对象间关系。", lts), {**meta, "kind": "link-types"}),
        (f"{folder}/action-types.md", render_action_types_md(f"{label} · 动作类型", f"定义 {label} 上可执行的写操作。", ats), {**meta, "kind": "action-types"}),
    ]
    if convs:
        files.append((f"{folder}/identifiers.md",
                      render_identifiers_md(f"{label} · 标识符与码空间映射",
                                             f"{label} 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把炉次 HT 当钢种 P-ST-、把岗位 P-MELT 当钢种 P-ST-、把 MES 缺陷 DF 当 PLM 案例 DF-AS- 等 404。",
                                             convs, mappings or []),
                      {**meta, "kind": "identifiers"}))
    return files


# 组织级 10 个本体文件夹
ORG_SYSTEMS = [
    {"folder": "PLM", "label": "PLM 钢铁产品生命周期本体",
     "summary": "钢种主数据(P-ST-)/钢种质量历史(DF-AS-)/分钢种成本台账；缺陷回流钢种历史构成质量闭环。",
     "object_types": PLM_OBJECT_TYPES, "link_types": PLM_LINK_TYPES, "action_types": PLM_ACTION_TYPES,
     "conventions": PLM_IDENTIFIER_CONVENTIONS, "code_mappings": PLM_CODE_SPACE_MAPPINGS},
    {"folder": "SCM", "label": "SCM 钢铁供应链协同本体",
     "summary": "钢铁料供应商/大宗原料报价(ASQ)/废钢分级(SCR-)/到货/补单/交期/校验。",
     "object_types": SCM_OBJECT_TYPES, "link_types": SCM_LINK_TYPES, "action_types": SCM_ACTION_TYPES,
     "conventions": SCM_IDENTIFIER_CONVENTIONS, "code_mappings": SCM_CODE_SPACE_MAPPINGS},
    {"folder": "ERP", "label": "ERP 财务物料采购本体",
     "summary": "钢铁料主数据/采购单/库存/应付(ASAP)/凭证(BV-AS-)/分钢种炉次成本(PC-AS-)/成本中心。",
     "object_types": ERP_OBJECT_TYPES, "link_types": ERP_LINK_TYPES, "action_types": ERP_ACTION_TYPES,
     "conventions": ERP_IDENTIFIER_CONVENTIONS, "code_mappings": ERP_CODE_SPACE_MAPPINGS},
    {"folder": "MES", "label": "MES 钢铁制造执行本体",
     "summary": "炉次(HT 钢铁主实体)/工单(SWO)/生产订单(SPO)/表面缺陷(DF 8类)/设备(EQ-)/OEE；炉次回挂钢种+配料+设备。",
     "object_types": MES_OBJECT_TYPES, "link_types": MES_LINK_TYPES, "action_types": MES_ACTION_TYPES,
     "conventions": MES_IDENTIFIER_CONVENTIONS, "code_mappings": MES_CODE_SPACE_MAPPINGS},
    {"folder": "CRM", "label": "CRM 客户销售本体",
     "summary": "客户(C-AS-)/商机/报价/销售订单(ASSO)/质量异议(CR-AS-)/应收(ASAR)；订单驱动排产+异议关联工单。",
     "object_types": CRM_OBJECT_TYPES, "link_types": CRM_LINK_TYPES, "action_types": CRM_ACTION_TYPES,
     "conventions": CRM_IDENTIFIER_CONVENTIONS, "code_mappings": CRM_CODE_SPACE_MAPPINGS},
    {"folder": "HRM", "label": "HRM 人力资源本体",
     "summary": "员工(ASSA/ASOF)/岗位(P-)/简历(ASRM)/招聘(ASRC)/薪酬/绩效/会议。",
     "object_types": HRM_OBJECT_TYPES, "link_types": HRM_LINK_TYPES, "action_types": HRM_ACTION_TYPES,
     "conventions": HRM_IDENTIFIER_CONVENTIONS, "code_mappings": HRM_CODE_SPACE_MAPPINGS},
    {"folder": "EQM", "label": "EQM 设备管理本体",
     "summary": "关键设备(EQ- 高炉/转炉/连铸/轧机)/备件(SP-)/故障历史(EQF)/预测性维护建议(MP)；与 MES 共享设备码空间。",
     "object_types": EQM_OBJECT_TYPES, "link_types": EQM_LINK_TYPES, "action_types": EQM_ACTION_TYPES,
     "conventions": EQM_IDENTIFIER_CONVENTIONS, "code_mappings": EQM_CODE_SPACE_MAPPINGS},
    {"folder": "EMS", "label": "EMS 能源环保本体",
     "summary": "能源计量点(EM-)/介质平衡/排放(EMS-)/工序能耗/调度方案(EDP)/预警(EA)。",
     "object_types": EMS_OBJECT_TYPES, "link_types": EMS_LINK_TYPES, "action_types": EMS_ACTION_TYPES,
     "conventions": EMS_IDENTIFIER_CONVENTIONS, "code_mappings": EMS_CODE_SPACE_MAPPINGS},
    {"folder": "EHS", "label": "EHS 安全管理本体",
     "summary": "隐患台账(HD-)/违章(VIO-)/巡检(INS-)/风险点分级/劳保；隐患关联设备 EQ- 闭环。",
     "object_types": EHS_OBJECT_TYPES, "link_types": EHS_LINK_TYPES, "action_types": EHS_ACTION_TYPES,
     "conventions": EHS_IDENTIFIER_CONVENTIONS, "code_mappings": EHS_CODE_SPACE_MAPPINGS},
    {"folder": "Cross", "label": "跨系统闭环本体",
     "summary": "8 条跨系统链接：销售订单→生产订单→炉次→钢种+废钢→缺陷→设备→能耗→隐患→炉次成本（钢铁物理流贯通）。",
     "object_types": [], "link_types": CROSS_LINK_TYPES, "action_types": CROSS_ACTION_TYPES},
]

# 部门/团队级本体文件夹
DEPT_TEAM_SYSTEMS = [
    {"folder": "equipment", "label": "设备管理部本体（部门级）",
     "scope_type": "department", "dept_slug": "equipment", "team_slug": None,
     "summary": "预测性维护流程/振动诊断规则/备件管理；关联 EQM 设备+备件构成 EQP-01 闭环。",
     "object_types": [], "link_types": [], "action_types": []},
    {"folder": "energy", "label": "能源环保部本体（部门级）",
     "scope_type": "department", "dept_slug": "energy", "team_slug": None,
     "summary": "能源调度流程/排放管控/碳足迹核算；关联 EMS 计量点+排放构成 ENE-01 闭环。",
     "object_types": [], "link_types": [], "action_types": []},
    {"folder": "safety", "label": "安全环保部本体（部门级）",
     "scope_type": "department", "dept_slug": "safety", "team_slug": None,
     "summary": "违章识别/隐患闭环/应急处置；关联 EHS 隐患+违章构成 SAF-01 闭环。",
     "object_types": [], "link_types": [], "action_types": []},
    {"folder": "hr", "label": "人力资源部本体（部门级）",
     "scope_type": "department", "dept_slug": "hr", "team_slug": None,
     "summary": "招聘流程/培训体系/薪酬结构/员工制度；关联 HRM 简历/员工/薪酬构成 HR-01 闭环。",
     "object_types": [], "link_types": [], "action_types": []},
    {"folder": "hr-recruiting", "label": "招聘组本体（团队级）",
     "scope_type": "team", "dept_slug": "hr", "team_slug": "hr-recruiting",
     "summary": "岗位 JD/胜任力模型/5 维度评估规则/面试题库；关联 HRM 简历+岗位。",
     "object_types": [], "link_types": [], "action_types": []},
]


# ───────────────────────── 主流程 ─────────────────────────

async def _get_org(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None)))
    org = result.scalar_one_or_none()
    if org is not None:
        return org
    result = await db.execute(select(Organization).where(Organization.name == ORG_NAME_FALLBACK, Organization.deleted_at.is_(None)))
    return result.scalar_one_or_none()


async def _get_dept_by_slug(db: AsyncSession, org_id, slug: str) -> Department | None:
    return (await db.execute(select(Department).where(
        Department.organization_id == org_id, Department.slug == slug, Department.deleted_at.is_(None)
    ))).scalar_one_or_none()


async def _get_team_by_slug(db: AsyncSession, dept_id, slug: str) -> Team | None:
    return (await db.execute(select(Team).where(
        Team.department_id == dept_id, Team.slug == slug, Team.deleted_at.is_(None)
    ))).scalar_one_or_none()


async def _seed_scope(db, org_id, scope_type, scope_id, systems, scope_label) -> list:
    out = []
    for s in systems:
        await create_folder(db, org_id, scope_type, scope_id, s["folder"])
        files = _files_for(s["folder"], s["label"], s["object_types"], s["link_types"], s["action_types"], s["summary"],
                           convs=s.get("conventions"), mappings=s.get("code_mappings"))
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
            raise RuntimeError(f"组织 slug='{ORG_SLUG}' 不存在，请先运行 seed_agilesteel_org.py。")
        logger.info("seed_agilesteel_ontology_org", slug=org.slug, org_id=str(org.id))

        org_results = await _seed_scope(db, org.id, "organization", None, ORG_SYSTEMS, "organization")
        overall["scopes"].append({"scope": "organization", "systems": org_results})

        for s in DEPT_TEAM_SYSTEMS:
            if s["scope_type"] == "department":
                dept = await _get_dept_by_slug(db, org.id, s["dept_slug"])
                if dept is None:
                    raise RuntimeError(f"部门 slug='{s['dept_slug']}' 不存在。")
                scope_id, scope_label = str(dept.id), f"department:{s['dept_slug']}"
            else:
                dept = await _get_dept_by_slug(db, org.id, s["dept_slug"])
                if dept is None:
                    raise RuntimeError(f"部门 slug='{s['dept_slug']}' 不存在。")
                team = await _get_team_by_slug(db, dept.id, s["team_slug"])
                if team is None:
                    raise RuntimeError(f"团队 slug='{s['team_slug']}' 不存在。")
                scope_id, scope_label = str(team.id), f"team:{s['dept_slug']}/{s['team_slug']}"
            res = await _seed_scope(db, org.id, s["scope_type"], scope_id, [s], scope_label)
            overall["scopes"].append({"scope": scope_label, "systems": res})

        await db.commit()
    return overall


def _print_report(result: dict) -> None:
    print("\n" + "=" * 72)
    print("敏睿钢铁本体导入完成（覆盖式幂等，可安全重复执行）")
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
    print("位置：管理端「敏睿钢铁」组织 → 本体 → PLM/SCM/ERP/MES/CRM/HRM/EQM/EMS/EHS/Cross（组织级）")
    print("        + equipment/energy/safety/hr（部门级）/ hr-recruiting（团队级）")
    print("9 域含 identifiers.md（标识符约定 + 跨码空间映射），agent 推理时按用户 scope 注入。")
    print("=" * 72)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
