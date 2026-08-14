"""为「敏睿空调」组织导入 HVAC 本体（28 组织级 + 16 部门/团队级 = 44 个本体文件）。

Palantir Foundry 风格：对象类型 / 链接类型 / 动作类型。覆盖 11 个 demo 场景所需的
空调域实体与跨系统关系：

  - PLM（产品生命周期）：Style(AC 产品)/Bom/DefectHistory/CostLedger/FeasibilityLog/
    SellingPoints/Voucher
  - SCM（供应链）：Supplier/Quotation/CapacityCalendar/FabricArrivalPlan/
    ReplenishmentSuggestion/LeadtimeSnapshot/MaterialValidation
  - ERP（财务/物料/采购）：Material/PurchaseOrder/Inventory/Voucher/Payable/Receivable/
    ProductionCost/CostCenter
  - MES（制造执行）：ProductionOrder/WorkOrder/Defect/Equipment/OEE
  - CRM（客户/销售）：Customer/Opportunity/Quotation/SalesOrder/Complaint/Receivable
  - HRM（人力资源）：Employee/Department/Position/Resume/Meeting/Recruitment
  - Cross（跨系统闭环）：Style↔MES.Product、Complaint→MES.Defect→PLM.DefectHistory→Style、
    WorkOrder→ERP.ProductionCost、SalesOrder→Receivable、PurchaseOrder→ArrivalPlan 等

部门/团队级 4 个：rnd-translation(team)/after-sales(dept)/marketing(dept)/hr(dept)。

幂等：upsert 覆盖内容。落位 (organization_id, scope_type, scope_id) 三元组作用域。

用法:
    docker cp demo/agileac/scripts/seed_agileac_ontology.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_agileac_ontology.py
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json
import os
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

ORG_SLUG = os.getenv("MOCK_SEED_ORG_SLUG", "agileac")
ORG_NAME_FALLBACK = "敏睿空调"


# ───────────────────────── PLM 对象类型 ─────────────────────────

PLM_OBJECT_TYPES = [
    {
        "objectType": "Style", "primaryKey": "style_code",
        "title": "{style_code} · {name}（{category}）",
        "description": "空调产品：家用壁挂/柜机/移动机 + 商用 VRV/风管机/冷水机型号，含产品类型/BOM/工艺/成本/卖点。",
        "backingInterface": "GET /api/v1/styles, GET /api/v1/styles/{style_code}",
        "properties": {
            "style_code": {"type": "string", "description": "产品编码（主键，与 MES product_code 对齐），如 P-RC-WALL-15"},
            "name": {"type": "string"},
            "category": {"type": "string", "description": "家用壁挂/家用柜机/家用移动/商用VRV/商用水管/商用水冷"},
            "cooling_capacity_kw": {"type": "number", "description": "制冷量 kW"},
            "power_supply": {"type": "string", "description": "电源 1Φ/3Φ"},
            "refrigerant": {"type": "string", "description": "制冷剂 R410A/R32"},
            "energy_class": {"type": "string", "description": "能效等级 1/2/3"},
            "unit_cost": {"type": "number"},
            "status": {"type": "string", "description": "开发中/已量产/已停产"},
            "designer": {"type": "string"},
            "launch_date": {"type": "string"},
        },
    },
    {
        "objectType": "Bom", "primaryKey": "style_code#material_code",
        "title": "{style_code} · {material_code}（用量 {qty}）",
        "description": "产品 BOM：压缩机/冷凝器/蒸发器/电子膨胀阀/制冷剂等核心配件清单。",
        "backingInterface": "GET /api/v1/boms?style_code=",
        "properties": {
            "style_code": {"type": "string", "description": "关联 Style"},
            "material_code": {"type": "string", "description": "关联 ERP.Material（压缩机/换热器/阀件/制冷剂/包装）"},
            "qty": {"type": "number", "description": "单台用量"},
            "uom": {"type": "string"},
            "loss_rate": {"type": "number", "description": "损耗 %"},
        },
    },
    {
        "objectType": "DefectHistory", "primaryKey": "case_id",
        "title": "{case_id} · {style_code}（{defect_type}）",
        "description": "故障案例历史：8 类空调故障（不制冷/噪音/漏水/通讯故障/制热不足/异味/外观不良/电气故障）的根因 + 纠正 + 规避要点，供 SVC-01 与 QAL-01 RAG 检索回流到新品开发。",
        "backingInterface": "GET /api/v1/defect-history",
        "properties": {
            "case_id": {"type": "string"},
            "style_code": {"type": "string", "description": "关联 Style"},
            "category": {"type": "string", "description": "产品类别，如 家用壁挂/商用VRV"},
            "defect_type": {"type": "string", "description": "不制冷/噪音/漏水/通讯故障/制热不足/异味/外观不良/电气故障"},
            "severity": {"type": "string"},
            "root_cause": {"type": "string"},
            "corrective_action": {"type": "string"},
            "avoidance_hint": {"type": "string", "description": "规避要点，新品开发时注入"},
            "date_reported": {"type": "string"},
            "work_order_no": {"type": "string", "description": "关联 MES.WorkOrder"},
        },
    },
    {
        "objectType": "CostLedger", "primaryKey": "ledger_no",
        "title": "{ledger_no} · {style_code}（{period}）",
        "description": "成本台账：按产品/物料/期间归集料工费，供 FIN-01 对账与 SCM-01 比价后更新。",
        "backingInterface": "GET /api/v1/cost-ledger",
        "properties": {
            "ledger_no": {"type": "string"},
            "style_code": {"type": "string"},
            "material_code": {"type": "string"},
            "period": {"type": "string"},
            "cost_material": {"type": "number"},
            "cost_labor": {"type": "number"},
            "cost_overhead": {"type": "number"},
            "cost_total": {"type": "number"},
            "updated_at": {"type": "string"},
        },
    },
    {
        "objectType": "FeasibilityLog", "primaryKey": "log_no",
        "title": "{log_no} · {material_code} → {supplier_code}",
        "description": "物料可行性测算留痕：决策时成本/交期/产能快照，供 PRD-01 与 SCM-01 回溯。",
        "backingInterface": "GET /api/v1/feasibility-logs",
        "properties": {
            "log_no": {"type": "string"},
            "style_code": {"type": "string"},
            "material_code": {"type": "string"},
            "supplier_code": {"type": "string"},
            "qty_requested": {"type": "number"},
            "cost_estimated": {"type": "number"},
            "leadtime_estimated": {"type": "number"},
            "capacity_available": {"type": "number"},
            "snapshot_at": {"type": "string"},
            "decision": {"type": "string"},
        },
    },
    {
        "objectType": "SellingPoints", "primaryKey": "style_code",
        "title": "{style_code} 卖点清单",
        "description": "产品卖点（能效/静音/智能除菌/精准送风/外观）——产品部交付给市场部使用。",
        "backingInterface": "GET /api/v1/styles/{style_code}（产品参数 + 卖点段）",
        "properties": {
            "style_code": {"type": "string"},
            "selling_points": {"type": "array", "description": "卖点列表"},
            "scenarios": {"type": "array", "description": "适用场景"},
            "competitor_diffs": {"type": "string", "description": "差异化"},
        },
    },
    {
        "objectType": "Voucher", "primaryKey": "voucher_no",
        "title": "{voucher_no} · {period}（{status}）",
        "description": "财务凭证（PLM 侧）：跨系统 SSO 演示凭证 BV-AG-2026-0512 在 PLM 与 ERP 双侧呈现。",
        "backingInterface": "GET /api/v1/vouchers, POST /api/v1/vouchers",
        "properties": {
            "voucher_no": {"type": "string"},
            "period": {"type": "string"},
            "summary": {"type": "string"},
            "debit_total": {"type": "number"},
            "credit_total": {"type": "number"},
            "status": {"type": "string", "description": "草稿/财务复核中/已过账"},
            "source_system": {"type": "string", "description": "PLM/ERP（跨系统对账字段）"},
        },
    },
]

PLM_LINK_TYPES = [
    {"linkType": "StyleToBom", "parent": "Style", "child": "Bom",
     "cardinality": "ONE_MANY", "joinField": "style_code",
     "description": "产品的 BOM 行（压缩机/换热器/阀件/制冷剂/包装）。"},
    {"linkType": "StyleToDefect", "parent": "Style", "child": "DefectHistory",
     "cardinality": "ONE_MANY", "joinField": "style_code",
     "description": "产品历史故障（新品开发与售后诊断时检索规避）。"},
    {"linkType": "StyleToCostLedger", "parent": "Style", "child": "CostLedger",
     "cardinality": "ONE_MANY", "joinField": "style_code",
     "description": "产品成本台账。"},
    {"linkType": "StyleToFeasibility", "parent": "Style", "child": "FeasibilityLog",
     "cardinality": "ONE_MANY", "joinField": "style_code",
     "description": "产品物料可行性测算留痕。"},
    {"linkType": "StyleToSellingPoints", "parent": "Style", "child": "SellingPoints",
     "cardinality": "ONE_ONE", "joinField": "style_code",
     "description": "产品的卖点清单。"},
]

PLM_ACTION_TYPES = [
    {"actionType": "addDefectRecord", "operation": "CREATE", "target": "DefectHistory",
     "description": "售后/质检后故障回流：写入缺陷历史，供下次新品/质量检索。",
     "backingInterface": "POST /api/v1/defect-history",
     "parameters": {
         "style_code": {"type": "string"},
         "category": {"type": "string"},
         "defect_type": {"type": "string"},
         "severity": {"type": "string"},
         "root_cause": {"type": "string"},
         "corrective_action": {"type": "string"},
         "avoidance_hint": {"type": "string"},
     },
     "effects": {"status": "已回流，等待下次新品/质量检索"}},
    {"actionType": "postVoucher", "operation": "CREATE", "target": "Voucher",
     "description": "新建财务凭证（写入演示，跨系统 SSO 演示场景）。",
     "backingInterface": "POST /api/v1/vouchers",
     "parameters": {"period": {"type": "string"}, "summary": {"type": "string"},
                    "debit_total": {"type": "number"}, "credit_total": {"type": "number"}},
     "effects": {"status": "草稿"}},
    {"actionType": "updateCostLedger", "operation": "MODIFY", "target": "CostLedger",
     "description": "比价后更新成本台账。",
     "backingInterface": "POST /api/v1/cost-ledger",
     "parameters": {"style_code": {"type": "string"}, "material_code": {"type": "string"},
                    "period": {"type": "string"}, "cost_material": {"type": "number"}},
     "effects": {"status": "已更新"}},
]


# ───────────────────────── SCM 对象类型 ─────────────────────────

SCM_OBJECT_TYPES = [
    {
        "objectType": "Supplier", "primaryKey": "code",
        "title": "{code} · {name}（{category}）",
        "description": "供应商：压缩机/换热器/阀件/制冷剂/包装/物流等，含产能/起订量/账期/评级/资质。",
        "backingInterface": "GET /api/v1/suppliers, GET /api/v1/suppliers/{code}",
        "properties": {
            "code": {"type": "string"},
            "name": {"type": "string"},
            "category": {"type": "string", "description": "压缩机/换热器/阀件/制冷剂/包装/物流"},
            "contact": {"type": "string"},
            "payment_terms_days": {"type": "number"},
            "rating": {"type": "string"},
            "capacity_per_day": {"type": "number"},
            "moq": {"type": "number"},
            "specialty": {"type": "string"},
            "qualifications": {"type": "array", "description": "资质证书列表（ISO/IATF/CCC 等）"},
        },
    },
    {
        "objectType": "Quotation", "primaryKey": "quotation_no",
        "title": "{quotation_no} · {supplier_name} → {material_name}",
        "description": "报价单：压缩机/换热器等核心配件的单价/起订/交期/账期/有效期，多家对比同规格。",
        "backingInterface": "GET /api/v1/quotations, GET /api/v1/quotations/{quotation_no}, GET /api/v1/quotations/compare",
        "properties": {
            "quotation_no": {"type": "string"},
            "supplier_code": {"type": "string", "description": "关联 Supplier"},
            "supplier_name": {"type": "string"},
            "material_code": {"type": "string", "description": "关联 ERP.Material"},
            "material_name": {"type": "string"},
            "spec": {"type": "string"},
            "unit_price": {"type": "number"},
            "moq": {"type": "number"},
            "leadtime_days": {"type": "number"},
            "payment_terms_days": {"type": "number"},
            "valid_until": {"type": "string"},
            "status": {"type": "string"},
        },
    },
    {
        "objectType": "CapacityCalendar", "primaryKey": "entry_id",
        "title": "{supplier_code} · {date}（占用 {utilization_pct}%）",
        "description": "产能日历：按供应商+日期的总产能/已用/可用/占用率。",
        "backingInterface": "GET /api/v1/capacity-calendar, GET /api/v1/suppliers/{code}/capacity",
        "properties": {
            "entry_id": {"type": "string"},
            "supplier_code": {"type": "string"},
            "date": {"type": "string"},
            "total_capacity": {"type": "number"},
            "used": {"type": "number"},
            "available": {"type": "number"},
            "utilization_pct": {"type": "number"},
        },
    },
    {
        "objectType": "FabricArrivalPlan", "primaryKey": "plan_id",
        "title": "{plan_id} · {material_code}（{status}）",
        "description": "配件在途到货计划：压缩机/换热器/制冷剂等到货状态与延误天数。",
        "backingInterface": "GET /api/v1/fabric-arrival-plans",
        "properties": {
            "plan_id": {"type": "string"},
            "supplier_code": {"type": "string"},
            "material_code": {"type": "string"},
            "po_ref": {"type": "string", "description": "关联 ERP.PurchaseOrder"},
            "qty": {"type": "number"},
            "uom": {"type": "string"},
            "ship_date": {"type": "string"},
            "eta": {"type": "string"},
            "status": {"type": "string", "description": "在途/已到货/延误"},
            "delay_days": {"type": "number"},
        },
    },
    {
        "objectType": "ReplenishmentSuggestion", "primaryKey": "suggestion_id",
        "title": "{suggestion_id} · {style_code}（首单+补1+补2）",
        "description": "补单节奏建议：按交期反推+产能占用给首单/补1/补2 节点（家用旺季备货 + 商用项目排产）。",
        "backingInterface": "GET /api/v1/replenishment-suggestions, GET /api/v1/suggest-replenishment",
        "properties": {
            "suggestion_id": {"type": "string"},
            "style_code": {"type": "string"},
            "bulk_no": {"type": "string"},
            "total_qty": {"type": "number"},
            "first_batch_qty": {"type": "number"}, "first_batch_date": {"type": "string"},
            "replenish_1_qty": {"type": "number"}, "replenish_1_date": {"type": "string"},
            "replenish_2_qty": {"type": "number"}, "replenish_2_date": {"type": "string"},
            "fabric_arrival_date": {"type": "string", "description": "关键配件到货日"},
            "risks": {"type": "array", "description": "风险列表"},
        },
    },
    {
        "objectType": "LeadtimeSnapshot", "primaryKey": "snapshot_id",
        "title": "{snapshot_id} · {material_code} → {supplier_code}",
        "description": "交期快照：用于实时交期异动检测（同供应商同物料不同快照对比 Δ）。",
        "backingInterface": "GET /api/v1/leadtime-snapshots, GET /api/v1/leadtime-diff",
        "properties": {
            "snapshot_id": {"type": "string"},
            "material_code": {"type": "string"},
            "supplier_code": {"type": "string"},
            "leadtime_days": {"type": "number"},
            "captured_at": {"type": "string"},
            "snapshot_at": {"type": "string"},
            "source": {"type": "string", "description": "初测/复测"},
        },
    },
    {
        "objectType": "MaterialValidation", "primaryKey": "validation_id",
        "title": "{validation_id} · {work_order_no}（{status}）",
        "description": "物料校验记录：双向（工厂端/我方端发起），含应投/实投/差异，触发缺料/超领预警。",
        "backingInterface": "GET /api/v1/material-validations, POST /api/v1/material-validations",
        "properties": {
            "validation_id": {"type": "string"},
            "initiated_by": {"type": "string", "description": "factory/internal"},
            "work_order_no": {"type": "string", "description": "关联 MES.WorkOrder"},
            "style_code": {"type": "string"},
            "bom_material_code": {"type": "string"},
            "required_qty": {"type": "number", "description": "应投"},
            "actual_qty": {"type": "number", "description": "实投"},
            "variance_qty": {"type": "number"},
            "variance_pct": {"type": "number"},
            "status": {"type": "string", "description": "正常/缺料/超领"},
            "operator": {"type": "string"},
            "check_date": {"type": "string"},
        },
    },
]

SCM_LINK_TYPES = [
    {"linkType": "SupplierToQuotation", "parent": "Supplier", "child": "Quotation",
     "cardinality": "ONE_MANY", "joinField": "supplier_code",
     "description": "供应商的多份报价（不同配件/规格）。"},
    {"linkType": "SupplierToCapacity", "parent": "Supplier", "child": "CapacityCalendar",
     "cardinality": "ONE_MANY", "joinField": "supplier_code",
     "description": "供应商未来 N 天产能占用。"},
    {"linkType": "SupplierToArrival", "parent": "Supplier", "child": "FabricArrivalPlan",
     "cardinality": "ONE_MANY", "joinField": "supplier_code",
     "description": "供应商的配件在途到货。"},
    {"linkType": "SupplierToLeadtimeSnapshot", "parent": "Supplier", "child": "LeadtimeSnapshot",
     "cardinality": "ONE_MANY", "joinField": "supplier_code",
     "description": "供应商交期快照序列（异动检测）。"},
    {"linkType": "QuotationToMaterial", "parent": "Quotation", "child": "ERP.Material",
     "cardinality": "MANY_ONE", "joinField": "material_code", "crossSystem": True,
     "description": "【跨系统】报价对应 ERP 物料（压缩机/换热器/阀件/制冷剂）。"},
    {"linkType": "QuotationToCostLedger", "parent": "Quotation", "child": "PLM.CostLedger",
     "cardinality": "MANY_ONE", "joinField": "material_code / style_code", "crossSystem": True,
     "description": "【跨系统】比价后更新 PLM 成本台账。"},
    {"linkType": "MaterialValidationToWorkOrder", "parent": "MaterialValidation", "child": "MES.WorkOrder",
     "cardinality": "MANY_ONE", "joinField": "work_order_no", "crossSystem": True,
     "description": "【跨系统】物料校验关联 MES 工单。"},
]

SCM_ACTION_TYPES = [
    {"actionType": "createMaterialValidation", "operation": "CREATE", "target": "MaterialValidation",
     "description": "发起物料校验（工厂端/我方端均可，按 APIKey 作用域分流）。",
     "backingInterface": "POST /api/v1/material-validations",
     "parameters": {
         "initiated_by": {"type": "string", "description": "factory/internal"},
         "work_order_no": {"type": "string"},
         "style_code": {"type": "string"},
         "bom_material_code": {"type": "string"},
         "required_qty": {"type": "number"},
         "actual_qty": {"type": "number"},
     },
     "effects": {"status": "已记录，差异超阈值触发缺料/超领预警"}},
]


# ───────────────────────── SCM 标识符约定（SCM-01 四层化补齐） ─────────────────────────

SCM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Supplier", "field": "code", "prefix": "S-",
     "example": "S-COMP-001",
     "note": "供应商主键；第二段按品类：S-COMP- 压缩机 / S-HEX- 换热器 / S-VALVE- 阀件 / S-REF- 制冷剂 / S-PKG- 包装 / S-PSB- 钣金 / S-LOG- 物流"},
    {"entity": "Quotation", "field": "quotation_no", "prefix": "AGQ",
     "example": "AGQ202607001",
     "note": "报价单主键；含供应商+物料+单价/起订/交期/账期，多家对比同规格走 compareQuotations"},
    {"entity": "CapacityCalendar", "field": "entry_id", "prefix": "AGCC",
     "example": "AGCC202607001",
     "note": "产能日历条目；按供应商+日期的总产能/已用/可用/占用率"},
    {"entity": "FabricArrivalPlan", "field": "plan_id", "prefix": "AGFAP",
     "example": "AGFAP-002",
     "note": "配件在途到货计划主键；延误样本 AGFAP-002（S-COMP-002 压缩机延误 7 天，影响工单 AWO20260105）"},
    {"entity": "ReplenishmentSuggestion", "field": "suggestion_id", "prefix": "AGRS",
     "example": "AGRS202607001",
     "note": "补单节奏建议；按交期反推首单/补1/补2 节点"},
    {"entity": "LeadtimeSnapshot", "field": "snapshot_id", "prefix": "AGLT",
     "example": "AGLT202606001",
     "note": "交期快照；同供应商同物料不同快照对比 Δ 走 getLeadtimeDiff"},
    {"entity": "MaterialValidation", "field": "validation_id", "prefix": "AGMV",
     "example": "AGMV202607001",
     "note": "物料校验记录；双向（工厂端/我方端），触发缺料/超领预警"},
]

SCM_CODE_SPACE_MAPPINGS = [
    {
        "from_field": "Quotation.material_code", "from_prefix": "M-",
        "to_field": "ERP.Material.material_code", "to_prefix": "M-",
        "rule": "同码空间，报价物料号直传 ERP 物料查询",
        "example": "AGQ202607001.material_code=M-COMP-GT-24K → ERP getMaterial(M-COMP-GT-24K)",
        "why": "压缩机/换热器/阀件/制冷剂物料号在 SCM 报价与 ERP 物料间一致，可直接关联",
    },
    {
        "from_field": "Quotation.supplier_code / FabricArrivalPlan.supplier_code", "from_prefix": "S-",
        "to_field": "ERP.PurchaseOrder.supplier_code", "to_prefix": "S-",
        "rule": "同码空间，供应商号跨 SCM 报价/到货与 ERP 采购单一致",
        "example": "S-COMP-001 → ERP listPurchaseOrders(supplier_code=S-COMP-001)",
        "why": "供应商主键在 SCM 与 ERP 间统一，对账与到货监管按 supplier_code 关联",
    },
    {
        "from_field": "FabricArrivalPlan.po_ref / MaterialValidation.work_order_no", "from_prefix": "AGPO / AWO",
        "to_field": "ERP.PurchaseOrder.po_no / MES.WorkOrder.won", "to_prefix": "AGPO / AWO",
        "rule": "到货计划的 po_ref 对应 ERP 采购单号；物料校验的 work_order_no 对应 MES 工单号",
        "example": "AGFAP-002.po_ref → ERP 采购单；AGMV.work_order_no=AWO20260105 → MES getWorkOrder(AWO20260105)",
        "why": "到货计划与采购单、物料校验与工单跨系统关联，勿把 plan_id 当 po_no 直传",
    },
    {
        "from_field": "Quotation.material_code / FabricArrivalPlan.material_code", "from_prefix": "M-",
        "to_field": "PLM.Bom.material_code", "to_prefix": "M-",
        "rule": "报价/到货物料对应 PLM BOM 行（压缩机/换热器/阀件/制冷剂）",
        "example": "M-COMP-GT-24K → PLM listBoms(material_code=M-COMP-GT-24K) 看哪款产品用此物料",
        "why": "比价后可追溯物料用于哪款产品 BOM，联动 PLM 成本台账更新",
    },
]


# ───────────────────────── ERP 对象类型 ─────────────────────────

ERP_OBJECT_TYPES = [
    {
        "objectType": "Material", "primaryKey": "material_code",
        "title": "{material_code} · {name}（{category}）",
        "description": "物料：压缩机/冷凝器/蒸发器/电子膨胀阀/制冷剂/钣金/包装等，关联 PLM.Bom 与 SCM.Quotation。",
        "backingInterface": "GET /api/v1/materials, GET /api/v1/materials/{material_code}",
        "properties": {
            "material_code": {"type": "string"},
            "name": {"type": "string"},
            "category": {"type": "string", "description": "压缩机/换热器/阀件/制冷剂/钣金/包装"},
            "spec": {"type": "string"},
            "uom": {"type": "string"},
            "standard_cost": {"type": "number"},
            "abc_class": {"type": "string", "description": "A/B/C"},
            "supplier_code": {"type": "string"},
        },
    },
    {
        "objectType": "PurchaseOrder", "primaryKey": "po_no",
        "title": "{po_no} · {supplier_code}（{status}）",
        "description": "采购订单：核心配件采购单，关联 SCM.FabricArrivalPlan 到货。",
        "backingInterface": "GET /api/v1/purchase-orders, GET /api/v1/purchase-orders/{po_no}, POST /api/v1/purchase-orders/{po_no}/receive",
        "properties": {
            "po_no": {"type": "string"},
            "supplier_code": {"type": "string"},
            "order_date": {"type": "string"},
            "status": {"type": "string", "description": "已下单/已发货/已到货/已对账"},
            "total_amount": {"type": "number"},
            "lines": {"type": "array", "description": "订单行（material_code/qty/unit_price）"},
        },
    },
    {
        "objectType": "Inventory", "primaryKey": "material_code#warehouse_code",
        "title": "{material_code} @ {warehouse_code}（{qty}）",
        "description": "库存：按物料+仓库的现货/在途/安全库存。",
        "backingInterface": "GET /api/v1/inventory",
        "properties": {
            "material_code": {"type": "string"},
            "warehouse_code": {"type": "string"},
            "qty_on_hand": {"type": "number"},
            "qty_in_transit": {"type": "number"},
            "safety_stock": {"type": "number"},
            "uom": {"type": "string"},
            "abc_class": {"type": "string"},
        },
    },
    {
        "objectType": "Payable", "primaryKey": "invoice_no",
        "title": "{invoice_no} · {supplier_code}（{status}）",
        "description": "应付：供应商对账，含账期/逾期/状态。",
        "backingInterface": "GET /api/v1/payables",
        "properties": {
            "invoice_no": {"type": "string"},
            "supplier_code": {"type": "string"},
            "po_ref": {"type": "string"},
            "amount": {"type": "number"},
            "due_date": {"type": "string"},
            "status": {"type": "string", "description": "已对账/已核准/已付款/逾期"},
            "overdue_days": {"type": "number"},
        },
    },
    {
        "objectType": "Receivable", "primaryKey": "invoice_no",
        "title": "{invoice_no} · {customer_code}（{status}）",
        "description": "应收：客户对账，含账期/逾期/状态，与 CRM.Receivable 互通。",
        "backingInterface": "GET /api/v1/receivables",
        "properties": {
            "invoice_no": {"type": "string"},
            "customer_code": {"type": "string"},
            "so_ref": {"type": "string"},
            "amount": {"type": "number"},
            "due_date": {"type": "string"},
            "status": {"type": "string", "description": "已对账/已收款/逾期"},
            "overdue_days": {"type": "number"},
        },
    },
    {
        "objectType": "Voucher", "primaryKey": "voucher_no",
        "title": "{voucher_no} · {period}（{status}）",
        "description": "财务凭证（ERP 侧）：跨系统 SSO 演示凭证 BV-AG-2026-0512 在 ERP 与 PLM 双侧呈现。",
        "backingInterface": "GET /api/v1/vouchers, POST /api/v1/vouchers",
        "properties": {
            "voucher_no": {"type": "string"},
            "period": {"type": "string"},
            "summary": {"type": "string"},
            "debit_total": {"type": "number"},
            "credit_total": {"type": "number"},
            "status": {"type": "string", "description": "草稿/财务复核中/已过账"},
            "source_system": {"type": "string", "description": "PLM/ERP（跨系统对账字段）"},
        },
    },
    {
        "objectType": "ProductionCost", "primaryKey": "cost_id",
        "title": "{cost_id} · {work_order_no}（{period}）",
        "description": "生产成本：按工单归集料/工/制费，供 FIN-01 与 PLM.CostLedger 对账。",
        "backingInterface": "GET /api/v1/production-costs",
        "properties": {
            "cost_id": {"type": "string"},
            "work_order_no": {"type": "string", "description": "关联 MES.WorkOrder"},
            "style_code": {"type": "string"},
            "period": {"type": "string"},
            "cost_material": {"type": "number"},
            "cost_labor": {"type": "number"},
            "cost_overhead": {"type": "number"},
            "cost_total": {"type": "number"},
            "cost_center": {"type": "string"},
        },
    },
    {
        "objectType": "CostCenter", "primaryKey": "code",
        "title": "{code} · {name}",
        "description": "成本中心：车间/部门/项目维度的成本归集单元。",
        "backingInterface": "GET /api/v1/cost-centers",
        "properties": {
            "code": {"type": "string"},
            "name": {"type": "string"},
            "type": {"type": "string", "description": "车间/部门/项目"},
            "manager_emp_no": {"type": "string", "description": "关联 HRM.Employee"},
        },
    },
]

ERP_LINK_TYPES = [
    {"linkType": "MaterialToInventory", "parent": "Material", "child": "Inventory",
     "cardinality": "ONE_MANY", "joinField": "material_code",
     "description": "物料的多仓库存。"},
    {"linkType": "SupplierToPurchaseOrder", "parent": "Supplier", "child": "PurchaseOrder",
     "cardinality": "ONE_MANY", "joinField": "supplier_code",
     "description": "供应商的采购订单。"},
    {"linkType": "PurchaseOrderToPayable", "parent": "PurchaseOrder", "child": "Payable",
     "cardinality": "ONE_MANY", "joinField": "po_ref / invoice_no",
     "description": "采购订单的应付对账。"},
    {"linkType": "SalesOrderToReceivable", "parent": "SalesOrder", "child": "Receivable",
     "cardinality": "ONE_MANY", "joinField": "so_ref / invoice_no", "crossSystem": True,
     "description": "【跨系统】CRM 销售订单对应 ERP 应收。"},
    {"linkType": "WorkOrderToProductionCost", "parent": "MES.WorkOrder", "child": "ProductionCost",
     "cardinality": "ONE_MANY", "joinField": "work_order_no", "crossSystem": True,
     "description": "【跨系统】MES 工单按单归集 ERP 生产成本。"},
    {"linkType": "CostCenterToProductionCost", "parent": "CostCenter", "child": "ProductionCost",
     "cardinality": "ONE_MANY", "joinField": "code / cost_center",
     "description": "成本中心归集的生产成本。"},
]

ERP_ACTION_TYPES = [
    {"actionType": "receivePurchaseOrder", "operation": "MODIFY", "target": "PurchaseOrder",
     "description": "采购单到货收料（写入演示，更新库存与状态）。",
     "backingInterface": "POST /api/v1/purchase-orders/{po_no}/receive",
     "parameters": {"po_no": {"type": "string"}, "received_qty": {"type": "number"},
                    "warehouse_code": {"type": "string"}},
     "effects": {"status": "已到货", "inventory": "已更新"}},
    {"actionType": "postVoucher", "operation": "CREATE", "target": "Voucher",
     "description": "新建财务凭证（写入演示，跨系统 SSO 演示场景）。",
     "backingInterface": "POST /api/v1/vouchers",
     "parameters": {"period": {"type": "string"}, "summary": {"type": "string"},
                    "debit_total": {"type": "number"}, "credit_total": {"type": "number"}},
     "effects": {"status": "草稿"}},
]


# ───────────────────────── MES 对象类型 ─────────────────────────

MES_OBJECT_TYPES = [
    {
        "objectType": "ProductionOrder", "primaryKey": "order_no",
        "title": "{order_no} · {product_code}（{status}）",
        "description": "生产订单：家用/商用空调量产订单，含计划/实际/产能/超期。",
        "backingInterface": "GET /api/v1/production-orders, GET /api/v1/production-orders/{order_no}",
        "properties": {
            "order_no": {"type": "string"},
            "product_code": {"type": "string", "description": "关联 PLM.Style"},
            "customer_code": {"type": "string", "description": "关联 CRM.Customer"},
            "factory": {"type": "string"},
            "qty": {"type": "number"},
            "plan_start": {"type": "string"},
            "plan_end": {"type": "string"},
            "actual_end": {"type": "string"},
            "capacity_per_day": {"type": "number"},
            "delivery_date": {"type": "string"},
            "qc_status": {"type": "string"},
            "days_late": {"type": "number"},
        },
    },
    {
        "objectType": "WorkOrder", "primaryKey": "won",
        "title": "{won} · {product_code}（{status}）",
        "description": "工单：按产线分单，关联客诉/缺陷/工单成本，是售后故障诊断的核心载体。",
        "backingInterface": "GET /api/v1/work-orders, GET /api/v1/work-orders/{won}, POST /api/v1/work-orders/{won}/report",
        "properties": {
            "won": {"type": "string"},
            "order_no": {"type": "string", "description": "关联 ProductionOrder"},
            "product_code": {"type": "string", "description": "关联 PLM.Style"},
            "factory": {"type": "string"},
            "line": {"type": "string"},
            "qty": {"type": "number"},
            "plan_start": {"type": "string"}, "plan_end": {"type": "string"},
            "actual_end": {"type": "string"},
            "status": {"type": "string", "description": "待排/在制/完工/异常"},
            "operator_emp_no": {"type": "string", "description": "关联 HRM.Employee"},
            "days_late": {"type": "number"},
        },
    },
    {
        "objectType": "Defect", "primaryKey": "defect_id",
        "title": "{defect_id} · {product_code}（{defect_type}）",
        "description": "缺陷/故障：8 类空调故障（不制冷/噪音/漏水/通讯故障/制热不足/异味/外观不良/电气故障），含 5W2H 根因 + 相似历史 + 纠正措施。",
        "backingInterface": "GET /api/v1/defects, GET /api/v1/defects/{defect_id}/root-cause",
        "properties": {
            "defect_id": {"type": "string"},
            "won": {"type": "string", "description": "关联 WorkOrder"},
            "product_code": {"type": "string", "description": "关联 PLM.Style"},
            "defect_type": {"type": "string", "description": "不制冷/噪音/漏水/通讯故障/制热不足/异味/外观不良/电气故障"},
            "severity": {"type": "string"},
            "root_cause": {"type": "string", "description": "5W2H 根因（getDefectRootCause 提供）"},
            "corrective_action": {"type": "string"},
            "similar_history": {"type": "array", "description": "相似历史缺陷案例（PLM.DefectHistory 关联）"},
            "stage": {"type": "string", "description": "来料/制程/出货/售后"},
            "reported_at": {"type": "string"},
            "resolved_at": {"type": "string"},
        },
    },
    {
        "objectType": "Equipment", "primaryKey": "code",
        "title": "{code} · {name}（{status}）",
        "description": "设备：装配线/测试台/冷媒充注机/检漏设备等，含状态/产能/上次故障。",
        "backingInterface": "GET /api/v1/equipment/status, GET /api/v1/equipment/{code}",
        "properties": {
            "code": {"type": "string"},
            "name": {"type": "string"},
            "factory": {"type": "string"},
            "line": {"type": "string"},
            "status": {"type": "string", "description": "运行/停机/保养"},
            "capacity_per_day": {"type": "number"},
            "last_failure_at": {"type": "string"},
        },
    },
    {
        "objectType": "Oee", "primaryKey": "line#date",
        "title": "{line} · {date}（OEE {oee_pct}%）",
        "description": "OEE 综合效率：可用率 × 性能 × 质量。",
        "backingInterface": "GET /api/v1/oee",
        "properties": {
            "line": {"type": "string"},
            "date": {"type": "string"},
            "availability_pct": {"type": "number"},
            "performance_pct": {"type": "number"},
            "quality_pct": {"type": "number"},
            "oee_pct": {"type": "number"},
            "downtime_minutes": {"type": "number"},
            "defect_count": {"type": "number"},
        },
    },
    {
        "objectType": "Wip", "primaryKey": "won#stage",
        "title": "{won} · {stage}（{qty}）",
        "description": "在制品：按工单+工序的在制数量与停留时长。",
        "backingInterface": "GET /api/v1/wip",
        "properties": {
            "won": {"type": "string"},
            "stage": {"type": "string", "description": "钣金/装配/充填/检漏/测试/包装"},
            "qty": {"type": "number"},
            "in_at": {"type": "string"},
            "dwell_hours": {"type": "number"},
        },
    },
]

MES_LINK_TYPES = [
    {"linkType": "ProductionOrderToWorkOrder", "parent": "ProductionOrder", "child": "WorkOrder",
     "cardinality": "ONE_MANY", "joinField": "order_no",
     "description": "生产订单按产线分单为多个工单。"},
    {"linkType": "WorkOrderToDefect", "parent": "WorkOrder", "child": "Defect",
     "cardinality": "ONE_MANY", "joinField": "won",
     "description": "工单产生的缺陷/故障记录。"},
    {"linkType": "LineToEquipment", "parent": "Equipment", "child": "Oee",
     "cardinality": "ONE_MANY", "joinField": "line",
     "description": "产线设备的 OEE 指标。"},
    {"linkType": "WorkOrderToWip", "parent": "WorkOrder", "child": "Wip",
     "cardinality": "ONE_MANY", "joinField": "won",
     "description": "工单的在制品流转。"},
    {"linkType": "DefectToDefectHistory", "parent": "Defect", "child": "PLM.DefectHistory",
     "cardinality": "MANY_ONE", "joinField": "won / work_order_no", "crossSystem": True,
     "description": "【跨系统】MES 缺陷回流 PLM 缺陷历史，构成闭环。"},
]

MES_ACTION_TYPES = [
    {"actionType": "getDefectRootCause", "operation": "READ", "target": "Defect",
     "description": "获取缺陷 5W2H 根因 + 相似历史缺陷案例，供 SVC-01 与 QAL-01 推理。",
     "backingInterface": "GET /api/v1/defects/{defect_id}/root-cause",
     "parameters": {"defect_id": {"type": "string"}},
     "effects": {"status": "返回根因 + 相似历史 + 纠正建议"}},
    {"actionType": "reportWorkOrder", "operation": "MODIFY", "target": "WorkOrder",
     "description": "工单报工（写入演示，更新在制/完工数量）。",
     "backingInterface": "POST /api/v1/work-orders/{won}/report",
     "parameters": {"won": {"type": "string"}, "qty_good": {"type": "number"},
                    "qty_defect": {"type": "number"}, "operator_emp_no": {"type": "string"}},
     "effects": {"status": "已报工", "wip": "已扣减"}},
]


# ───────────────────────── CRM 对象类型 ─────────────────────────

CRM_OBJECT_TYPES = [
    {
        "objectType": "Customer", "primaryKey": "code",
        "title": "{code} · {name}（{tier}）",
        "description": "客户：家用经销/电商/工程项目/商用大客户，含信用/账期/联系人。",
        "backingInterface": "GET /api/v1/customers, GET /api/v1/customers/{code}",
        "properties": {
            "code": {"type": "string"},
            "name": {"type": "string"},
            "tier": {"type": "string", "description": "战略/核心/一般"},
            "channel": {"type": "string", "description": "经销/电商/工程项目/商用"},
            "credit_limit": {"type": "number"},
            "payment_terms_days": {"type": "number"},
            "contacts": {"type": "array"},
        },
    },
    {
        "objectType": "Opportunity", "primaryKey": "opportunity_id",
        "title": "{opportunity_id} · {customer_name}（{stage}）",
        "description": "商机：工程项目/经销补货/电商大促等线索与阶段。",
        "backingInterface": "GET /api/v1/opportunities, GET /api/v1/opportunities/{opportunity_id}",
        "properties": {
            "opportunity_id": {"type": "string"},
            "customer_code": {"type": "string"},
            "stage": {"type": "string", "description": "线索/报价/谈判/已成交/已失"},
            "amount": {"type": "number"},
            "expected_close_date": {"type": "string"},
            "owner_emp_no": {"type": "string", "description": "关联 HRM.Employee"},
        },
    },
    {
        "objectType": "Quotation", "primaryKey": "quotation_id",
        "title": "{quotation_id} · {customer_name}（{status}）",
        "description": "销售报价：含阶梯价/模具费，关联商机/客户。",
        "backingInterface": "GET /api/v1/quotations, GET /api/v1/quotations/{quotation_id}, POST /api/v1/quotations/{quotation_id}/submit",
        "properties": {
            "quotation_id": {"type": "string"},
            "customer_code": {"type": "string"},
            "opportunity_id": {"type": "string"},
            "amount": {"type": "number"},
            "valid_until": {"type": "string"},
            "status": {"type": "string", "description": "草稿/已送审/已批/已驳回"},
        },
    },
    {
        "objectType": "SalesOrder", "primaryKey": "so_no",
        "title": "{so_no} · {customer_code}（{status}）",
        "description": "销售订单：成交后的订单，关联生产单/应收/客诉。",
        "backingInterface": "GET /api/v1/sales-orders",
        "properties": {
            "so_no": {"type": "string"},
            "customer_code": {"type": "string"},
            "order_date": {"type": "string"},
            "amount": {"type": "number"},
            "status": {"type": "string", "description": "已下单/生产中/已发货/已对账/已收款"},
            "linked_production_order": {"type": "string", "description": "关联 MES.ProductionOrder"},
        },
    },
    {
        "objectType": "Complaint", "primaryKey": "complaint_id",
        "title": "{complaint_id} · {customer_code}（{type}/{severity}）",
        "description": "客诉/8D：故障报修与退货/换货客诉，关联 MES 缺陷与 PLM 故障历史。SVC-01 入口。",
        "backingInterface": "GET /api/v1/complaints, GET /api/v1/complaints/{complaint_id}",
        "properties": {
            "complaint_id": {"type": "string"},
            "customer_code": {"type": "string"},
            "type": {"type": "string", "description": "fault/return/quality/service"},
            "severity": {"type": "string"},
            "product_code": {"type": "string", "description": "关联 PLM.Style"},
            "linked_work_order_no": {"type": "string", "description": "关联 MES.WorkOrder"},
            "linked_defect_id": {"type": "string", "description": "关联 MES.Defect"},
            "stage_8d": {"type": "string", "description": "D1-D8 阶段"},
            "status": {"type": "string", "description": "受理/排查中/已闭环/已驳回"},
            "summary": {"type": "string"},
        },
    },
    {
        "objectType": "Receivable", "primaryKey": "invoice_no",
        "title": "{invoice_no} · {customer_code}（{status}）",
        "description": "应收：客户对账，含账期/逾期/状态，与 ERP.Receivable 互通。",
        "backingInterface": "GET /api/v1/receivables",
        "properties": {
            "invoice_no": {"type": "string"},
            "customer_code": {"type": "string"},
            "so_ref": {"type": "string"},
            "amount": {"type": "number"},
            "due_date": {"type": "string"},
            "status": {"type": "string"},
            "overdue_days": {"type": "number"},
        },
    },
    {
        "objectType": "FollowUp", "primaryKey": "followup_id",
        "title": "{followup_id} · {customer_code}",
        "description": "客户跟进：销售拜访/电话/邮件记录。",
        "backingInterface": "GET /api/v1/follow-ups",
        "properties": {
            "followup_id": {"type": "string"},
            "customer_code": {"type": "string"},
            "channel": {"type": "string"},
            "content": {"type": "string"},
            "followup_at": {"type": "string"},
            "owner_emp_no": {"type": "string"},
        },
    },
]

CRM_LINK_TYPES = [
    {"linkType": "CustomerToOpportunity", "parent": "Customer", "child": "Opportunity",
     "cardinality": "ONE_MANY", "joinField": "customer_code",
     "description": "客户的商机。"},
    {"linkType": "OpportunityToQuotation", "parent": "Opportunity", "child": "Quotation",
     "cardinality": "ONE_MANY", "joinField": "opportunity_id",
     "description": "商机的报价。"},
    {"linkType": "CustomerToSalesOrder", "parent": "Customer", "child": "SalesOrder",
     "cardinality": "ONE_MANY", "joinField": "customer_code",
     "description": "客户的销售订单。"},
    {"linkType": "SalesOrderToReceivable", "parent": "SalesOrder", "child": "Receivable",
     "cardinality": "ONE_MANY", "joinField": "so_no / invoice_no",
     "description": "销售订单的应收对账。"},
    {"linkType": "CustomerToComplaint", "parent": "Customer", "child": "Complaint",
     "cardinality": "ONE_MANY", "joinField": "customer_code",
     "description": "客户的客诉/8D。"},
    {"linkType": "ComplaintToWorkOrder", "parent": "Complaint", "child": "MES.WorkOrder",
     "cardinality": "MANY_ONE", "joinField": "linked_work_order_no / won", "crossSystem": True,
     "description": "【跨系统】客诉关联 MES 工单（定位发生工序）。"},
    {"linkType": "ComplaintToDefect", "parent": "Complaint", "child": "MES.Defect",
     "cardinality": "ONE_MANY", "joinField": "linked_defect_id / defect_id", "crossSystem": True,
     "description": "【跨系统】客诉关联 MES 缺陷（根因分析入口）。"},
    {"linkType": "CustomerToFollowUp", "parent": "Customer", "child": "FollowUp",
     "cardinality": "ONE_MANY", "joinField": "customer_code",
     "description": "客户跟进记录。"},
]

CRM_ACTION_TYPES = [
    {"actionType": "submitQuotation", "operation": "MODIFY", "target": "Quotation",
     "description": "销售报价送审（写入演示）。",
     "backingInterface": "POST /api/v1/quotations/{quotation_id}/submit",
     "parameters": {"quotation_id": {"type": "string"}},
     "effects": {"status": "已送审"}},
]


# ───────────────────────── HRM 对象类型 ─────────────────────────

HRM_OBJECT_TYPES = [
    {
        "objectType": "Department", "primaryKey": "code",
        "title": "{code} · {name}",
        "description": "部门：研发/产品/生产/质量/供应链/销售/售后/市场/财务/HR/IT 11 个。",
        "backingInterface": "GET /api/v1/departments, GET /api/v1/departments/{code}",
        "properties": {
            "code": {"type": "string"},
            "name": {"type": "string"},
            "manager_emp_no": {"type": "string", "description": "关联 Employee"},
            "headcount": {"type": "number"},
        },
    },
    {
        "objectType": "Position", "primaryKey": "code",
        "title": "{code} · {name}",
        "description": "岗位：研发/产品/生产/质量/供应链/销售/售后/市场/财务/HR/IT 各岗位编码 P-XXX。",
        "backingInterface": "GET /api/v1/positions",
        "properties": {
            "code": {"type": "string"},
            "name": {"type": "string"},
            "department_code": {"type": "string"},
            "level": {"type": "string"},
        },
    },
    {
        "objectType": "Employee", "primaryKey": "emp_no",
        "title": "{emp_no} · {name}（{department}/{position}）",
        "description": "员工：在职/试用/离职，关联部门/岗位/考勤/绩效/薪酬。",
        "backingInterface": "GET /api/v1/employees, GET /api/v1/employees/{emp_no}",
        "properties": {
            "emp_no": {"type": "string"},
            "name": {"type": "string"},
            "department": {"type": "string"},
            "position": {"type": "string"},
            "status": {"type": "string", "description": "在职/试用/离职"},
            "hire_date": {"type": "string"},
            "manager_emp_no": {"type": "string"},
        },
    },
    {
        "objectType": "Attendance", "primaryKey": "attendance_id",
        "title": "{emp_no} · {date}（{status}）",
        "description": "考勤：正常/迟到/早退/缺勤/加班。",
        "backingInterface": "GET /api/v1/attendance",
        "properties": {
            "attendance_id": {"type": "string"},
            "emp_no": {"type": "string"},
            "date": {"type": "string"},
            "check_in": {"type": "string"},
            "check_out": {"type": "string"},
            "status": {"type": "string"},
            "overtime_hours": {"type": "number"},
        },
    },
    {
        "objectType": "Leave", "primaryKey": "leave_id",
        "title": "{leave_id} · {emp_no}（{type}/{status}）",
        "description": "请假：年假/事假/病假/调休等，含审批状态。",
        "backingInterface": "GET /api/v1/leaves, POST /api/v1/leaves",
        "properties": {
            "leave_id": {"type": "string"},
            "emp_no": {"type": "string"},
            "type": {"type": "string"},
            "start": {"type": "string"},
            "end": {"type": "string"},
            "days": {"type": "number"},
            "reason": {"type": "string"},
            "status": {"type": "string", "description": "待批/已批/已驳/已销"},
        },
    },
    {
        "objectType": "Payroll", "primaryKey": "payroll_id",
        "title": "{payroll_id} · {emp_no}（{period}）",
        "description": "薪酬：按员工+期间的应发/扣减/实发，关联 ERP.Voucher 凭证。",
        "backingInterface": "GET /api/v1/payrolls, POST /api/v1/payrolls/run",
        "properties": {
            "payroll_id": {"type": "string"},
            "emp_no": {"type": "string"},
            "period": {"type": "string"},
            "gross_pay": {"type": "number"},
            "deductions": {"type": "number"},
            "net_pay": {"type": "number"},
            "cost_center": {"type": "string"},
            "status": {"type": "string", "description": "已核算/已发放/待审批"},
        },
    },
    {
        "objectType": "Performance", "primaryKey": "perf_id",
        "title": "{perf_id} · {emp_no}（{period}/{grade}）",
        "description": "绩效：按员工+期间的考核等级 A/B/C/D。",
        "backingInterface": "GET /api/v1/performances",
        "properties": {
            "perf_id": {"type": "string"},
            "emp_no": {"type": "string"},
            "period": {"type": "string"},
            "grade": {"type": "string", "description": "A/B/C/D"},
            "score": {"type": "number"},
            "reviewer_emp_no": {"type": "string"},
        },
    },
    {
        "objectType": "Recruitment", "primaryKey": "req_id",
        "title": "{req_id} · {position_code}（{status}）",
        "description": "招聘需求：按岗位+部门的招聘中/已关闭需求。",
        "backingInterface": "GET /api/v1/recruitments",
        "properties": {
            "req_id": {"type": "string"},
            "position_code": {"type": "string"},
            "department": {"type": "string"},
            "headcount": {"type": "number"},
            "status": {"type": "string", "description": "招聘中/已关闭"},
            "owner_emp_no": {"type": "string"},
        },
    },
    {
        "objectType": "Resume", "primaryKey": "resume_id",
        "title": "{resume_id} · {name}（{position_code}）",
        "description": "简历库：按岗位过滤的候选人简历，含评分/标签/状态。",
        "backingInterface": "GET /api/v1/resumes, POST /api/v1/resumes/shortlist",
        "properties": {
            "resume_id": {"type": "string"},
            "name": {"type": "string"},
            "position_code": {"type": "string", "description": "目标岗位 P-XXX"},
            "education": {"type": "string"},
            "years_of_experience": {"type": "number"},
            "rating_score": {"type": "number"},
            "tags": {"type": "array"},
            "source": {"type": "string"},
            "status": {"type": "string", "description": "待筛选/已初面/已复面/已录用/已淘汰"},
        },
    },
    {
        "objectType": "Meeting", "primaryKey": "meeting_id",
        "title": "{meeting_id} · {title}（{status}）",
        "description": "会议纪要：含参会人/会议时间/决议，HR-01 招聘复评场景出口。",
        "backingInterface": "GET /api/v1/meetings, POST /api/v1/meetings",
        "properties": {
            "meeting_id": {"type": "string"},
            "title": {"type": "string"},
            "department": {"type": "string"},
            "meeting_at": {"type": "string"},
            "status": {"type": "string", "description": "进行中/已完成"},
            "owner_emp_no": {"type": "string"},
            "summary": {"type": "string"},
            "created_at": {"type": "string"},
        },
    },
]

HRM_LINK_TYPES = [
    {"linkType": "DepartmentToEmployee", "parent": "Department", "child": "Employee",
     "cardinality": "ONE_MANY", "joinField": "code / department",
     "description": "部门的员工。"},
    {"linkType": "PositionToEmployee", "parent": "Position", "child": "Employee",
     "cardinality": "ONE_MANY", "joinField": "code / position",
     "description": "岗位的在职员工。"},
    {"linkType": "EmployeeToAttendance", "parent": "Employee", "child": "Attendance",
     "cardinality": "ONE_MANY", "joinField": "emp_no",
     "description": "员工的考勤记录。"},
    {"linkType": "EmployeeToLeave", "parent": "Employee", "child": "Leave",
     "cardinality": "ONE_MANY", "joinField": "emp_no",
     "description": "员工的请假记录。"},
    {"linkType": "EmployeeToPayroll", "parent": "Employee", "child": "Payroll",
     "cardinality": "ONE_MANY", "joinField": "emp_no",
     "description": "员工的薪酬记录。"},
    {"linkType": "EmployeeToPerformance", "parent": "Employee", "child": "Performance",
     "cardinality": "ONE_MANY", "joinField": "emp_no",
     "description": "员工的绩效记录。"},
    {"linkType": "DepartmentToRecruitment", "parent": "Department", "child": "Recruitment",
     "cardinality": "ONE_MANY", "joinField": "code / department",
     "description": "部门的招聘需求。"},
    {"linkType": "PositionToResume", "parent": "Position", "child": "Resume",
     "cardinality": "ONE_MANY", "joinField": "code / position_code",
     "description": "岗位的候选人简历。"},
    {"linkType": "RecruitmentToResume", "parent": "Recruitment", "child": "Resume",
     "cardinality": "ONE_MANY", "joinField": "position_code",
     "description": "招聘需求对应的简历。"},
    {"linkType": "EmployeeToMeeting", "parent": "Employee", "child": "Meeting",
     "cardinality": "ONE_MANY", "joinField": "emp_no / owner_emp_no",
     "description": "员工主持的会议纪要。"},
    {"linkType": "PayrollToVoucher", "parent": "Payroll", "child": "ERP.Voucher",
     "cardinality": "MANY_ONE", "joinField": "period / period", "crossSystem": True,
     "description": "【跨系统】HRM 薪酬期间关联 ERP 凭证（薪酬子任务对账入口）。"},
    {"linkType": "EmployeeToCostCenter", "parent": "Employee", "child": "ERP.CostCenter",
     "cardinality": "MANY_ONE", "joinField": "emp_no / manager_emp_no", "crossSystem": True,
     "description": "【跨系统】员工作为成本中心负责人。"},
]

HRM_ACTION_TYPES = [
    {"actionType": "applyLeave", "operation": "CREATE", "target": "Leave",
     "description": "请假申请（写入演示）。",
     "backingInterface": "POST /api/v1/leaves",
     "parameters": {"emp_no": {"type": "string"}, "type": {"type": "string"},
                    "start": {"type": "string"}, "end": {"type": "string"},
                    "days": {"type": "number"}, "reason": {"type": "string"}},
     "effects": {"status": "待批"}},
    {"actionType": "runPayroll", "operation": "CREATE", "target": "Payroll",
     "description": "生成薪酬（写入演示，按期间/成本中心核算）。",
     "backingInterface": "POST /api/v1/payrolls/run",
     "parameters": {"period": {"type": "string"}, "cost_center": {"type": "string"}},
     "effects": {"status": "已核算"}},
    {"actionType": "shortlistResumes", "operation": "CREATE", "target": "Resume",
     "description": "生成岗位候选人短名单（评分排序）。",
     "backingInterface": "POST /api/v1/resumes/shortlist",
     "parameters": {"position": {"type": "string"}, "topn": {"type": "number"}},
     "effects": {"status": "已生成短名单"}},
    {"actionType": "postMeetingMinutes", "operation": "CREATE", "target": "Meeting",
     "description": "提交会议纪要（写入演示）。",
     "backingInterface": "POST /api/v1/meetings",
     "parameters": {"title": {"type": "string"}, "department": {"type": "string"},
                    "meeting_at": {"type": "string"}, "owner_emp_no": {"type": "string"},
                    "summary": {"type": "string"}},
     "effects": {"status": "已完成"}},
]


# ───────────────────────── Cross 跨系统闭环 ─────────────────────────

CROSS_LINK_TYPES = [
    {"linkType": "StyleToMesProduct", "parent": "PLM.Style", "child": "MES.ProductionOrder",
     "cardinality": "ONE_MANY", "joinField": "style_code / product_code", "crossSystem": True,
     "description": "【跨系统】空调产品与 MES 生产订单对齐（同码 P-RC-WALL-15 等）。"},
    {"linkType": "ProductionOrderToWorkOrder", "parent": "MES.ProductionOrder", "child": "MES.WorkOrder",
     "cardinality": "ONE_MANY", "joinField": "order_no",
     "description": "生产订单按产线分单为多个工单（MES 内部）。"},
    {"linkType": "ComplaintToMesWorkOrder", "parent": "CRM.Complaint", "child": "MES.WorkOrder",
     "cardinality": "MANY_ONE", "joinField": "linked_work_order_no / won", "crossSystem": True,
     "description": "【跨系统】CRM 客诉 8D 关联 MES 工单（定位发生工序）。"},
    {"linkType": "ComplaintToMesDefect", "parent": "CRM.Complaint", "child": "MES.Defect",
     "cardinality": "ONE_MANY", "joinField": "linked_defect_id / defect_id", "crossSystem": True,
     "description": "【跨系统】CRM 客诉关联 MES 缺陷（根因分析入口）。"},
    {"linkType": "MesDefectToPlmDefectHistory", "parent": "MES.Defect", "child": "PLM.DefectHistory",
     "cardinality": "MANY_ONE", "joinField": "won / work_order_no", "crossSystem": True,
     "description": "【跨系统】【闭环】MES 缺陷回流 PLM 故障历史，下次新品开发时检索规避。"},
    {"linkType": "DefectToStyleClosedLoop", "parent": "PLM.DefectHistory", "child": "PLM.Style",
     "cardinality": "MANY_ONE", "joinField": "style_code",
     "description": "【闭环】故障历史 → RAG 检索 → 新品开发预警（生命周期数据闭环）。"},
    {"linkType": "SalesOrderToMesProductionOrder", "parent": "CRM.SalesOrder", "child": "MES.ProductionOrder",
     "cardinality": "ONE_ONE", "joinField": "linked_production_order / order_no", "crossSystem": True,
     "description": "【跨系统】销售订单关联 MES 生产订单（按订单排产）。"},
    {"linkType": "SalesOrderToErpReceivable", "parent": "CRM.SalesOrder", "child": "ERP.Receivable",
     "cardinality": "ONE_MANY", "joinField": "so_no / invoice_no", "crossSystem": True,
     "description": "【跨系统】销售订单的应收对账（ERP 侧）。"},
    {"linkType": "PurchaseOrderToScmArrival", "parent": "ERP.PurchaseOrder", "child": "SCM.FabricArrivalPlan",
     "cardinality": "ONE_MANY", "joinField": "po_no / po_ref", "crossSystem": True,
     "description": "【跨系统】采购单关联 SCM 到货计划。"},
    {"linkType": "QuotationToErpMaterial", "parent": "SCM.Quotation", "child": "ERP.Material",
     "cardinality": "MANY_ONE", "joinField": "material_code", "crossSystem": True,
     "description": "【跨系统】SCM 报价对应 ERP 物料。"},
    {"linkType": "BomToErpMaterial", "parent": "PLM.Bom", "child": "ERP.Material",
     "cardinality": "MANY_ONE", "joinField": "material_code", "crossSystem": True,
     "description": "【跨系统】PLM BOM 行引用 ERP 物料（压缩机/换热器/阀件/制冷剂）。"},
    {"linkType": "WorkOrderToErpProductionCost", "parent": "MES.WorkOrder", "child": "ERP.ProductionCost",
     "cardinality": "ONE_MANY", "joinField": "won / work_order_no", "crossSystem": True,
     "description": "【跨系统】MES 工单按单归集 ERP 生产成本（FIN-01 对账入口）。"},
    {"linkType": "CostLedgerToErpProductionCost", "parent": "PLM.CostLedger", "child": "ERP.ProductionCost",
     "cardinality": "ONE_MANY", "joinField": "style_code / work_order_no", "crossSystem": True,
     "description": "【跨系统】PLM 成本台账与 ERP 生产成本对账（四方对账之一）。"},
    {"linkType": "ComplaintToHrmEmployee", "parent": "CRM.Complaint", "child": "HRM.Employee",
     "cardinality": "MANY_ONE", "joinField": "owner_emp_no / emp_no", "crossSystem": True,
     "description": "【跨系统】客诉处理人关联 HRM 员工（催办对象定位）。"},
    {"linkType": "VoucherCrossSystem", "parent": "PLM.Voucher", "child": "ERP.Voucher",
     "cardinality": "ONE_ONE", "joinField": "voucher_no", "crossSystem": True,
     "description": "【跨系统】同一张凭证在 PLM/ERP 双侧呈现（BV-AG-2026-0512 跨系统 SSO 演示）。"},
    {"linkType": "EmployeeToErpCostCenter", "parent": "HRM.Employee", "child": "ERP.CostCenter",
     "cardinality": "MANY_ONE", "joinField": "emp_no / manager_emp_no", "crossSystem": True,
     "description": "【跨系统】员工作为 ERP 成本中心负责人。"},
    {"linkType": "ResumeToHrmRecruitment", "parent": "HRM.Resume", "child": "HRM.Recruitment",
     "cardinality": "MANY_ONE", "joinField": "position_code",
     "description": "简历关联招聘需求（HRM 内部闭环）。"},
]

CROSS_ACTION_TYPES: list = []


# ───────────────────────── 部门/团队级本体 ─────────────────────────
# 4 个部门/团队级 ontology：rnd-translation(team)/after-sales(dept)/marketing(dept)/hr(dept)

# 1. 研发翻译组（team 级）：翻译流程/术语条目/核对规则
RND_TRANSLATION_OBJECT_TYPES = [
    {
        "objectType": "TranslationTask", "primaryKey": "task_id",
        "title": "{task_id} · {source_lang} → {target_lang}",
        "description": "翻译任务：外文技术资料段 → 中文化译文，关联术语条目与核对规则。",
        "backingInterface": "PLM GET /api/v1/styles + 翻译任务元数据",
        "properties": {
            "task_id": {"type": "string"},
            "source_lang": {"type": "string", "description": "en/ja/de"},
            "target_lang": {"type": "string", "description": "zh-CN"},
            "style_code": {"type": "string", "description": "关联 PLM.Style（型号核对）"},
            "source_text": {"type": "string"},
            "target_text": {"type": "string"},
            "status": {"type": "string", "description": "待译/已译/已核对/已发布"},
            "translator_emp_no": {"type": "string"},
        },
    },
    {
        "objectType": "TermEntry", "primaryKey": "term_id",
        "title": "{term_id} · {source_term} → {target_term}",
        "description": "术语条目：空调行业术语词典（压缩机/换热器/电子膨胀阀/制冷剂等的中外对照）。",
        "backingInterface": "RAG collection rnd-translation 中的术语 chunk",
        "properties": {
            "term_id": {"type": "string"},
            "source_term": {"type": "string"},
            "target_term": {"type": "string"},
            "domain": {"type": "string", "description": "压缩机/换热器/阀件/制冷剂/电控"},
            "approved_at": {"type": "string"},
            "reviewer_emp_no": {"type": "string"},
        },
    },
    {
        "objectType": "CheckRule", "primaryKey": "rule_id",
        "title": "{rule_id} · {category}",
        "description": "核对规则：型号一致性/参数单位/术语标准化/数字格式 等核对项。",
        "backingInterface": "RAG collection rnd-translation 中的规则 chunk",
        "properties": {
            "rule_id": {"type": "string"},
            "category": {"type": "string", "description": "型号/参数/术语/格式"},
            "description": {"type": "string"},
            "severity": {"type": "string", "description": "error/warn/info"},
        },
    },
]

RND_TRANSLATION_LINK_TYPES = [
    {"linkType": "TaskToTerm", "parent": "TranslationTask", "child": "TermEntry",
     "cardinality": "MANY_MANY", "joinField": "task_id / term_id（任务-术语关联表）",
     "description": "翻译任务引用的术语条目。"},
    {"linkType": "TaskToRule", "parent": "TranslationTask", "child": "CheckRule",
     "cardinality": "MANY_MANY", "joinField": "task_id / rule_id（任务-规则关联表）",
     "description": "翻译任务应用的核对规则。"},
    {"linkType": "TaskToStyle", "parent": "TranslationTask", "child": "PLM.Style",
     "cardinality": "MANY_ONE", "joinField": "style_code", "crossSystem": True,
     "description": "【跨系统】翻译任务关联 PLM 产品（型号核对）。"},
]

RND_TRANSLATION_ACTION_TYPES: list = []


# 2. 售后服务部（dept 级）：故障诊断流程/8D 阶段/排查步骤/配件更换
AFTER_SALES_OBJECT_TYPES = [
    {
        "objectType": "DiagnosisFlow", "primaryKey": "flow_id",
        "title": "{flow_id} · {defect_type}",
        "description": "故障诊断流程：按 8 类空调故障类型的标准排查路径。",
        "backingInterface": "RAG collection after-sales 中的诊断流程 chunk",
        "properties": {
            "flow_id": {"type": "string"},
            "defect_type": {"type": "string", "description": "不制冷/噪音/漏水/通讯故障/制热不足/异味/外观不良/电气故障"},
            "steps": {"type": "array", "description": "排查步骤列表"},
            "expected_duration_min": {"type": "number"},
        },
    },
    {
        "objectType": "EightDStage", "primaryKey": "stage_code",
        "title": "{stage_code} · {name}",
        "description": "8D 阶段：D1-D8 阶段定义（团队/问题/临时措施/根因/永久措施/验证/防止再发/表彰）。",
        "backingInterface": "RAG collection after-sales 中的 8D chunk",
        "properties": {
            "stage_code": {"type": "string", "description": "D1-D8"},
            "name": {"type": "string"},
            "deliverable": {"type": "string", "description": "阶段交付物"},
            "owner_role": {"type": "string", "description": "工程师/研发/质量/采购"},
        },
    },
    {
        "objectType": "RepairStep", "primaryKey": "step_id",
        "title": "{step_id} · {step_no}（{defect_type}）",
        "description": "排查步骤：单步操作指引 + 所需工具 + 配件清单 + 风险提示。",
        "backingInterface": "RAG collection after-sales 中的排查步骤 chunk",
        "properties": {
            "step_id": {"type": "string"},
            "step_no": {"type": "number"},
            "defect_type": {"type": "string"},
            "action": {"type": "string"},
            "tools": {"type": "array"},
            "parts": {"type": "array", "description": "配件列表（关联 ERP.Material）"},
            "risk_hint": {"type": "string"},
        },
    },
    {
        "objectType": "PartReplacement", "primaryKey": "replacement_id",
        "title": "{replacement_id} · {material_code}",
        "description": "配件更换记录：压缩机/换热器/电子膨胀阀等配件的更换原因 + 责任方 + 成本归属。",
        "backingInterface": "MES 工单 + 配件更换记录",
        "properties": {
            "replacement_id": {"type": "string"},
            "work_order_no": {"type": "string", "description": "关联 MES.WorkOrder"},
            "material_code": {"type": "string", "description": "关联 ERP.Material"},
            "qty": {"type": "number"},
            "reason": {"type": "string", "description": "质量问题/磨损/运输损坏/用户误操作"},
            "responsible_party": {"type": "string", "description": "供应商/工厂/物流/客户"},
            "cost_bearer": {"type": "string", "description": "成本归属方（供应商扣款/工厂承担/公司承担）"},
        },
    },
]

AFTER_SALES_LINK_TYPES = [
    {"linkType": "DiagnosisFlowToRepairStep", "parent": "DiagnosisFlow", "child": "RepairStep",
     "cardinality": "ONE_MANY", "joinField": "flow_id / defect_type",
     "description": "诊断流程的排查步骤序列。"},
    {"linkType": "DiagnosisFlowToEightD", "parent": "DiagnosisFlow", "child": "EightDStage",
     "cardinality": "ONE_MANY", "joinField": "defect_type",
     "description": "诊断流程对应的 8D 阶段。"},
    {"linkType": "RepairStepToPart", "parent": "RepairStep", "child": "ERP.Material",
     "cardinality": "MANY_MANY", "joinField": "parts / material_code", "crossSystem": True,
     "description": "【跨系统】排查步骤所需的配件关联 ERP 物料。"},
    {"linkType": "PartReplacementToWorkOrder", "parent": "PartReplacement", "child": "MES.WorkOrder",
     "cardinality": "MANY_ONE", "joinField": "work_order_no", "crossSystem": True,
     "description": "【跨系统】配件更换关联 MES 工单。"},
]

AFTER_SALES_ACTION_TYPES: list = []


# 3. 市场部（dept 级）：营销内容类型/竞品对比维度/课件结构
MARKETING_OBJECT_TYPES = [
    {
        "objectType": "ContentType", "primaryKey": "type_code",
        "title": "{type_code} · {name}",
        "description": "营销内容类型：海报文案/视频脚本/课件大纲/考题/竞品对比表。",
        "backingInterface": "RAG collection marketing（chunk_type=卖点/竞品/课件模板）",
        "properties": {
            "type_code": {"type": "string", "description": "poster/video/courseware/quiz/competitor"},
            "name": {"type": "string"},
            "target_audience": {"type": "string", "description": "消费者/经销商/内部培训"},
            "channel": {"type": "string", "description": "电商详情页/线下海报/短视频/培训课件"},
            "template_fields": {"type": "array"},
        },
    },
    {
        "objectType": "CompetitorDimension", "primaryKey": "dim_code",
        "title": "{dim_code} · {name}",
        "description": "竞品对比维度：能效/静音/智能控制/价格/服务等对比指标。",
        "backingInterface": "RAG collection marketing（竞品 chunk）",
        "properties": {
            "dim_code": {"type": "string"},
            "name": {"type": "string", "description": "能效/静音/智能控制/价格/服务"},
            "unit": {"type": "string"},
            "higher_is_better": {"type": "boolean"},
            "data_source": {"type": "string", "description": "公开规格/第三方评测/内部测试"},
        },
    },
    {
        "objectType": "CoursewareStructure", "primaryKey": "course_code",
        "title": "{course_code} · {name}",
        "description": "课件结构：培训课件大纲 + PPT 框架 + 考题模板。",
        "backingInterface": "RAG collection marketing（课件模板 chunk）",
        "properties": {
            "course_code": {"type": "string"},
            "name": {"type": "string"},
            "module_count": {"type": "number"},
            "modules": {"type": "array", "description": "模块列表（标题/要点/案例/考题）"},
            "target_role": {"type": "string", "description": "经销商/内部员工/售后服务商"},
            "duration_hours": {"type": "number"},
        },
    },
]

MARKETING_LINK_TYPES = [
    {"linkType": "ContentTypeToStyle", "parent": "ContentType", "child": "PLM.Style",
     "cardinality": "MANY_ONE", "joinField": "style_code", "crossSystem": True,
     "description": "【跨系统】营销内容关联 PLM 产品（卖点入口）。"},
    {"linkType": "ContentTypeToCustomer", "parent": "ContentType", "child": "CRM.Customer",
     "cardinality": "MANY_ONE", "joinField": "customer_code", "crossSystem": True,
     "description": "【跨系统】营销内容关联 CRM 客户（客户画像入口）。"},
]

MARKETING_ACTION_TYPES: list = []


# 4. 人力资源部（dept 级）：招聘流程/培训体系/薪酬结构
HR_OBJECT_TYPES = [
    {
        "objectType": "RecruitmentFlow", "primaryKey": "flow_id",
        "title": "{flow_id} · {position_code}",
        "description": "招聘流程：岗位发布→简历筛选→初面→复面→录用→到岗 各阶段定义。",
        "backingInterface": "RAG collection hr（招聘流程 chunk）",
        "properties": {
            "flow_id": {"type": "string"},
            "position_code": {"type": "string", "description": "关联 HRM.Position"},
            "stages": {"type": "array", "description": "阶段列表（筛选/初面/复面/录用/到岗）"},
            "sla_days_per_stage": {"type": "number"},
            "owner_emp_no": {"type": "string"},
        },
    },
    {
        "objectType": "TrainingProgram", "primaryKey": "program_code",
        "title": "{program_code} · {name}",
        "description": "培训体系：新人入职/制度文档/技能提升/管理能力培养等课程体系。",
        "backingInterface": "RAG collection hr（员工制度知识库 chunk）",
        "properties": {
            "program_code": {"type": "string"},
            "name": {"type": "string"},
            "category": {"type": "string", "description": "入职/制度/技能/管理"},
            "modules": {"type": "array"},
            "duration_hours": {"type": "number"},
            "target_audience": {"type": "string"},
        },
    },
    {
        "objectType": "SalaryStructure", "primaryKey": "structure_code",
        "title": "{structure_code} · {name}",
        "description": "薪酬结构：基本工资/岗位津贴/绩效奖金/加班费/扣项 等薪资项定义。",
        "backingInterface": "RAG collection hr（薪酬结构 chunk）",
        "properties": {
            "structure_code": {"type": "string"},
            "name": {"type": "string"},
            "components": {"type": "array", "description": "薪资项（基本/津贴/奖金/加班/扣项）"},
            "applicable_positions": {"type": "array"},
            "effective_from": {"type": "string"},
        },
    },
    {
        "objectType": "PolicyDocument", "primaryKey": "doc_id",
        "title": "{doc_id} · {title}",
        "description": "员工制度文档：报销/请假/差旅/晋升等制度问答源。",
        "backingInterface": "RAG collection hr（员工制度 chunk）",
        "properties": {
            "doc_id": {"type": "string"},
            "title": {"type": "string"},
            "category": {"type": "string", "description": "报销/请假/差旅/晋升/福利"},
            "effective_from": {"type": "string"},
            "owner_dept_code": {"type": "string"},
        },
    },
]

HR_LINK_TYPES = [
    {"linkType": "RecruitmentFlowToResume", "parent": "RecruitmentFlow", "child": "HRM.Resume",
     "cardinality": "ONE_MANY", "joinField": "position_code", "crossSystem": True,
     "description": "【跨系统】招聘流程关联 HRM 简历库。"},
    {"linkType": "TrainingProgramToEmployee", "parent": "TrainingProgram", "child": "HRM.Employee",
     "cardinality": "MANY_MANY", "joinField": "program_code / emp_no", "crossSystem": True,
     "description": "【跨系统】培训体系关联 HRM 员工（受训记录）。"},
    {"linkType": "SalaryStructureToPayroll", "parent": "SalaryStructure", "child": "HRM.Payroll",
     "cardinality": "ONE_MANY", "joinField": "structure_code / payroll_id", "crossSystem": True,
     "description": "【跨系统】薪酬结构关联 HRM 薪酬记录。"},
]

HR_ACTION_TYPES: list = []


# ───────────────────────── 标识符约定与码空间映射 ─────────────────────────
# 防猜码 404 的「no guessing」骨架：把每个实体的主键前缀 + 真实示例值写死，并把
# MES Defect(DF) vs PLM DefectHistory(DF-AG-)、HRM Position(P-ACCT) vs PLM Style(P-RC-)
# 等「共用前缀/跨码空间」的映射规则显式列出。agent 调 path 参数端点前读此表，杜绝
# 把 MES 缺陷号 DF20260101 当 PLM 故障案例号 DF-AG-2026-001、把岗位码 P-ACCT 当产品码。
# 真实示例取自 mock agileac 租户数据（mock/mock/systems/*/data.py _build_agileac）。

PLM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Style",          "field": "style_code",    "prefix": "P-RC- / P-CC-",
     "example": "P-RC-WALL-15 / P-CC-VRV-360",
     "note": "P- + RC(家用壁挂/柜机/移动) 或 CC(商用多联机/风管/模块) + 型号 + 序号；getStyle(style_code=...) 直传"},
    {"entity": "Bom",            "field": "material_code", "prefix": "M-",
     "example": "M-COMP-GT-24K",
     "note": "BOM 物料码（压缩机/冷凝器/蒸发器/电子膨胀阀/制冷剂/控制板/电容/包装）；与 ERP Material.material_code 同码空间（已对齐）"},
    {"entity": "DefectHistory",  "field": "case_id",       "prefix": "DF-AG-",
     "example": "DF-AG-2026-001",
     "note": "DF-AG- + 年份 + 序号；PLM 故障案例历史；与 MES Defect.defect_id(DF20260101) 不同码空间"},
    {"entity": "CostLedger",     "field": "ledger_no",     "prefix": "AGCL",
     "example": "AGCL20260001", "note": "AGCL + 年月 + 序号；成本台账"},
    {"entity": "FeasibilityLog", "field": "log_no",        "prefix": "AGFL",
     "example": "AGFL20260001", "note": "AGFL + 年月 + 序号；含成本/交期/产能快照，不含缺陷预防留痕"},
    {"entity": "SellingPoints",  "field": "style_code",    "prefix": "P-RC- / P-CC-",
     "example": "P-RC-WALL-15", "note": "卖点按产品款号挂载；主键同 Style.style_code"},
]

PLM_CODE_SPACE_MAPPINGS = [
    {
        "from_field": "Bom.material_code", "from_prefix": "M-",
        "to_field": "ERP.Material.material_code", "to_prefix": "M-",
        "rule": "同码空间（mock 已对齐）：BOM 物料码可直接当 ERP 物料码查 listMaterials/getMaterial",
        "example": "Bom(P-RC-WALL-15).material_code='M-COMP-GT-24K' → ERP getMaterial(material_code='M-COMP-GT-24K')",
        "why": "PLM BOM 与 ERP 物料主数据共享 M- 码空间，无需转换；反面：勿把 M- 当作独立面料码（agileac 无 F- 面料码空间）",
    },
    {
        "from_field": "Style.style_code", "from_prefix": "P-RC- / P-CC-",
        "to_field": "CRM/MES.product_code", "to_prefix": "P-RC- / P-CC-",
        "rule": "同码空间：客诉/工单的 product_code 就是 PLM style_code，可直接查 getStyle",
        "example": "CRM Complaint(product_code='P-RC-WALL-15') → PLM getStyle(style_code='P-RC-WALL-15')",
        "why": "产品款号跨 PLM/CRM/MES 一致，直接传即命中真实产品数据",
    },
    {
        "from_field": "MES Defect.defect_id", "from_prefix": "DF",
        "to_field": "PLM DefectHistory.case_id", "to_prefix": "DF-AG-",
        "rule": "不同码空间：MES 缺陷号(DF20260101) ≠ PLM 故障案例号(DF-AG-2026-001)；跨系统查历史按 product_code 或 defect_type 关联，勿把 MES defect_id 传给 PLM getDefectHistory(case_id=...)",
        "example": "MES Defect(defect_id='DF20260101', product_code='P-RC-WALL-15') → PLM listDefectHistory(style_code='P-RC-WALL-15') 取 DF-AG-2026-001 等历史案例",
        "why": "DF 与 DF-AG- 是两套独立编号，直接传 DF20260101 给 PLM 命中 404",
    },
    {
        "from_field": "HRM Position.code", "from_prefix": "P-",
        "to_field": "PLM Style.style_code", "to_prefix": "P-RC- / P-CC-",
        "rule": "共用 P- 前缀但不同码空间，按第二段消歧：P-ACCT/P-HR/P-IT = 岗位码；P-RC-/P-CC- = 产品款号",
        "example": "HRM Position(P-ACCT) 勿传 PLM getStyle(style_code='P-ACCT')（命中 404）；产品款号恒为 P-RC-/P-CC- 开头",
        "why": "P- 前缀在 HRM 岗位与 PLM 产品间复用，LLM 易把岗位码当产品码",
    },
]

CRM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Customer",     "field": "code",            "prefix": "C-AG-",
     "example": "C-AG-RETAIL-01 / C-AG-PROJ-01",
     "note": "C-AG- + 渠道(RETAIL 零售/ECOM 电商/DEALER 经销/PROJ 工程) + 序号；getCustomer(code=...) 直传"},
    {"entity": "Opportunity",  "field": "opportunity_id", "prefix": "AGOPP",
     "example": "AGOPP20260011", "note": "AGOPP + 年月 + 序号；商机"},
    {"entity": "Quotation",    "field": "quotation_id",    "prefix": "AGQT",
     "example": "AGQT20260007", "note": "AGQT + 年月 + 序号；报价"},
    {"entity": "SalesOrder",   "field": "so_no",           "prefix": "AGSO",
     "example": "AGSO20260002", "note": "AGSO + 年月 + 序号；销售订单；与 MES WorkOrder.sales_order_no 同码空间"},
    {"entity": "Complaint",   "field": "complaint_id",     "prefix": "AGCP",
     "example": "AGCP-0001", "note": "AGCP + 序号；客诉工单（8D 闭环入口）"},
    {"entity": "FollowUp",     "field": "followup_id",      "prefix": "AGFU",
     "example": "AGFU20260019", "note": "AGFU + 年月 + 序号；客户跟进"},
    {"entity": "Receivable",   "field": "invoice_no",      "prefix": "AGINV",
     "example": "AGINV2025xxxx", "note": "AGINV + 年月 + 序号；应收/发票号；与 ERP Payable/Receivable 同码空间"},
]

CRM_CODE_SPACE_MAPPINGS = [
    {
        "from_field": "Complaint.work_order_no", "from_prefix": "AWO",
        "to_field": "MES.WorkOrder.won", "to_prefix": "AWO",
        "rule": "同码空间：客诉挂的工单号就是 MES 工单号，直接 getWorkOrder(won=...)",
        "example": "Complaint(AGCP-0001).work_order_no='AWO20260101' → MES getWorkOrder(won='AWO20260101')",
        "why": "客诉-工单跨 CRM/MES 共享 AWO 码空间，直接传即命中真实工单",
    },
    {
        "from_field": "SalesOrder.so_no", "from_prefix": "AGSO",
        "to_field": "MES.WorkOrder.sales_order_no", "to_prefix": "AGSO",
        "rule": "同码空间：MES 工单的 sales_order_no 引用 CRM 销售订单号，直接交叉查",
        "example": "MES WorkOrder(sales_order_no='AGSO20260002') → CRM getSalesOrder(so_no='AGSO20260002')",
        "why": "销售订单跨 CRM/MES 一致，无需转换",
    },
    {
        "from_field": "Complaint.product_code / SalesOrder.product_code", "from_prefix": "P-RC- / P-CC-",
        "to_field": "PLM.Style.style_code", "to_prefix": "P-RC- / P-CC-",
        "rule": "同码空间：客诉/订单的产品码就是 PLM 产品款号，直接 getStyle",
        "example": "Complaint(AGCP-0001).product_code='P-RC-WALL-15' → PLM getStyle(style_code='P-RC-WALL-15')",
        "why": "产品款号跨 CRM/PLM 一致",
    },
    {
        "from_field": "Receivable.invoice_no", "from_prefix": "AGINV",
        "to_field": "ERP.Payable/Receivable.invoice_no", "to_prefix": "AGINV",
        "rule": "同码空间：CRM 应收与 ERP 应收/应付共享 AGINV 发票号",
        "example": "CRM Receivable(invoice_no='AGINV2025xxxx') → ERP getPayable/getReceivable(invoice_no='AGINV2025xxxx')",
        "why": "发票号跨 CRM/ERP 一致，对账场景直接交叉查",
    },
]

MES_IDENTIFIER_CONVENTIONS = [
    {"entity": "ProductionOrder", "field": "order_no", "prefix": "PO",
     "example": "PO20260101", "note": "PO + 年月 + 序号；生产订单；与 CRM SalesOrder.so_no(AGSO) 不同码空间"},
    {"entity": "WorkOrder",       "field": "won",      "prefix": "AWO",
     "example": "AWO20260101", "note": "AWO + 年月 + 序号；工单号；与 CRM Complaint.work_order_no 同码空间"},
    {"entity": "Defect",          "field": "defect_id", "prefix": "DF",
     "example": "DF20260101", "note": "DF + 年月 + 序号；MES 制造缺陷；与 PLM DefectHistory.case_id(DF-AG-) 不同码空间"},
    {"entity": "Equipment",       "field": "code",      "prefix": "EQ-",
     "example": "EQ-RC-01 / EQ-CC-01", "note": "EQ- + 线别(RC 家用/CC 商用/TST 测试/PIP 管路) + 序号；设备"},
]

MES_CODE_SPACE_MAPPINGS = [
    {
        "from_field": "Defect.defect_id", "from_prefix": "DF",
        "to_field": "PLM.DefectHistory.case_id", "to_prefix": "DF-AG-",
        "rule": "不同码空间：MES 缺陷号(DF20260101) ≠ PLM 故障案例号(DF-AG-2026-001)；查 PLM 历史案例按 product_code 或 defect_type 关联，勿直接传 DF 号",
        "example": "MES Defect(defect_id='DF20260101') → 按 product_code='P-RC-WALL-15' 查 PLM listDefectHistory → 取 DF-AG-2026-001",
        "why": "DF 与 DF-AG- 独立编号，直接传命中 404（defect case DF20260101 not found in PLM）",
    },
    {
        "from_field": "WorkOrder.won", "from_prefix": "AWO",
        "to_field": "CRM.Complaint.work_order_no", "to_prefix": "AWO",
        "rule": "同码空间：工单号跨 MES/CRM 共享，客诉挂的 work_order_no 可直接当 won 查工单详情",
        "example": "MES getWorkOrder(won='AWO20260101') ← CRM Complaint(AGCP-0001).work_order_no='AWO20260101'",
        "why": "客诉-工单关联跨系统一致",
    },
    {
        "from_field": "ProductionOrder.order_no", "from_prefix": "PO",
        "to_field": "CRM.SalesOrder.so_no", "to_prefix": "AGSO",
        "rule": "不同码空间：生产订单(PO20260101) ≠ 销售订单(AGSO20260002)；生产订单由销售订单转化，查关联用 WorkOrder.sales_order_no",
        "example": "生产订单 PO20260101 → 其下工单 WorkOrder.sales_order_no='AGSO20260002' → CRM getSalesOrder(so_no='AGSO20260002')",
        "why": "PO 与 AGSO 是两套编号，勿把生产订单号当销售订单号查 CRM",
    },
]

HRM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Department",  "field": "code",   "prefix": "PD-",
     "example": "PD-ADM / PD-FIN / PD-HR / PD-IT / PD-RND / PD-SA / PD-PROD",
     "note": "PD- + 职能缩写；部门码"},
    {"entity": "Position",    "field": "code",   "prefix": "P-",
     "example": "P-ACCT / P-HR / P-IT / P-MGR / P-OP / P-SVC",
     "note": "P- + 岗位缩写；与 PLM Style(P-RC-/P-CC-) 共用 P- 前缀，按第二段消歧"},
    {"entity": "Employee",    "field": "emp_no", "prefix": "AGSA / AGOF",
     "example": "AGSA100 / AGOF200",
     "note": "AGSA=销售员工、AGOF=职能员工；车间员工 emp_no 对齐 MES 作业员（name-based）"},
    {"entity": "Recruitment", "field": "req_id", "prefix": "AGRC",
     "example": "AGRC20260000", "note": "AGRC + 年月 + 序号；招聘需求"},
    {"entity": "Resume",       "field": "resume_id", "prefix": "AGRM",
     "example": "AGRM20260001", "note": "AGRM + 年月 + 序号；简历"},
    {"entity": "Meeting",      "field": "meeting_id", "prefix": "AGMT",
     "example": "AGMT20260001", "note": "AGMT + 年月 + 序号；会议纪要"},
    {"entity": "Payroll",      "field": "payroll_id", "prefix": "AGPR",
     "example": "AGPR2026xxxx", "note": "AGPR + 年月 + 序号；薪酬记录"},
]

HRM_CODE_SPACE_MAPPINGS = [
    {
        "from_field": "Position.code", "from_prefix": "P-",
        "to_field": "PLM.Style.style_code", "to_prefix": "P-RC- / P-CC-",
        "rule": "共用 P- 前缀但不同码空间，按第二段消歧：P-ACCT/P-HR/P-IT = 岗位；P-RC-/P-CC- = 产品款号",
        "example": "HRM getEmployee(position='P-ACCT') 勿与 PLM getStyle(style_code='P-ACCT') 混用",
        "why": "P- 前缀在 HRM 岗位与 PLM 产品间复用，LLM 易混淆；产品款号恒带 RC/CC 第二段",
    },
    {
        "from_field": "Employee.emp_no", "from_prefix": "AGSA / AGOF",
        "to_field": "MES WorkOrder.op_name", "to_prefix": "（name-based）",
        "rule": "车间员工 emp_no 对齐 MES 工单作业员名（非编码前缀），按 name 关联",
        "example": "HRM Employee(name='张伟') ↔ MES WorkOrder.op_name='张伟'",
        "why": "AG- 前缀的员工号是 HRM 内部编号，MES 作业员字段存的是姓名，需按 name 而非 emp_no 关联",
    },
]

ERP_IDENTIFIER_CONVENTIONS = [
    {"entity": "Material",       "field": "material_code", "prefix": "M-",
     "example": "M-COMP-GT-24K / M-COND-FIN-30 / M-EEV-15",
     "note": "ERP 物料主数据；与 PLM Bom.material_code 同码空间（已对齐）"},
    {"entity": "PurchaseOrder",  "field": "po_no",          "prefix": "AGPO",
     "example": "AGPO20260003", "note": "AGPO + 年月 + 序号；采购订单"},
    {"entity": "Inventory",      "field": "material_code#warehouse_code", "prefix": "M-#WH-AG-",
     "example": "M-COMP-GT-24K#WH-AG-COMP", "note": "物料#仓库复合主键；仓库码 WH-AG- + 品类"},
    {"entity": "Payable",        "field": "invoice_no",     "prefix": "AGINV",
     "example": "AGINV2025xxxx", "note": "AGINV + 年月 + 序号；应付发票号；与 CRM Receivable 同码空间"},
    {"entity": "Receivable",     "field": "invoice_no",     "prefix": "AGINV",
     "example": "AGINV2025xxxx", "note": "AGINV + 年月 + 序号；应收发票号"},
    {"entity": "Voucher",        "field": "voucher_no",     "prefix": "BV-AG-",
     "example": "BV-AG-2026-0514", "note": "BV-AG- + 年份 + 序号；会计凭证（AG- 租户标识）"},
    {"entity": "ProductionCost", "field": "cost_id",        "prefix": "AGPC",
     "example": "AGPC20260004", "note": "AGPC + 年月 + 序号；生产成本记录"},
    {"entity": "CostCenter",     "field": "code",           "prefix": "CC-AG-",
     "example": "CC-AG-RC / CC-AG-FIN", "note": "CC-AG- + 部门缩写；成本中心"},
]

ERP_CODE_SPACE_MAPPINGS = [
    {
        "from_field": "Material.material_code", "from_prefix": "M-",
        "to_field": "PLM.Bom.material_code", "to_prefix": "M-",
        "rule": "同码空间（mock 已对齐）：ERP 物料码 = PLM BOM 物料码，可直接交叉查",
        "example": "ERP getMaterial(material_code='M-COMP-GT-24K') = PLM Bom 行 material_code='M-COMP-GT-24K'",
        "why": "PLM BOM 与 ERP 物料主数据共享 M- 码空间，无需转换",
    },
    {
        "from_field": "Voucher.voucher_no", "from_prefix": "BV-AG-",
        "to_field": "PLM.Voucher.voucher_no", "to_prefix": "BV-AG-",
        "rule": "同码空间：会计凭证跨 ERP/PLM 共享 BV-AG- 前缀（PLM 侧呈现同一凭证做 SSO 演示）",
        "example": "ERP getVoucher(voucher_no='BV-AG-2026-0514') = PLM Voucher 同号",
        "why": "凭证跨系统一致，对账/SSO 场景直接交叉查",
    },
    {
        "from_field": "Payable/Receivable.invoice_no", "from_prefix": "AGINV",
        "to_field": "CRM.Receivable.invoice_no", "to_prefix": "AGINV",
        "rule": "同码空间：发票号跨 ERP/CRM 共享 AGINV 前缀",
        "example": "ERP getPayable(invoice_no='AGINV2025xxxx') ↔ CRM Receivable(invoice_no='AGINV2025xxxx')",
        "why": "应收/应付对账场景跨 CRM/ERP 一致",
    },
]


# ───────────────────────── Markdown 渲染 ─────────────────────────

def render_object_types_md(title: str, intro: str, ots: list) -> str:
    lines = [f"# {title}\n", f"> {intro}\n", "```ontology",
             json.dumps(ots, ensure_ascii=False, indent=2), "```\n"]
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
    lines = [f"# {title}\n", f"> {intro}\n", "```ontology",
             json.dumps(lts, ensure_ascii=False, indent=2), "```\n",
             "| 链接类型 | 父→子 | 基数 | join | 跨系统 | 说明 |",
             "|---|---|---|---|---|---|"]
    for lt in lts:
        cross = "✓" if lt.get("crossSystem") else ""
        lines.append(f"| {lt['linkType']} | {lt['parent']}→{lt['child']} | {lt['cardinality']} | `{lt['joinField']}` | {cross} | {lt.get('description','')} |")
    return "\n".join(lines)


def render_action_types_md(title: str, intro: str, ats: list) -> str:
    lines = [f"# {title}\n", f"> {intro}\n", "```ontology",
             json.dumps(ats, ensure_ascii=False, indent=2), "```\n"]
    for at in ats:
        lines += [f"## {at['actionType']}", at.get("description",""), "",
                  f"- 操作：`{at['operation']}` ｜ 目标：`{at['target']}`"]
        if at.get("backingInterface"):
            lines.append(f"- 接口：`{at['backingInterface']}`")
        lines.append("")
    return "\n".join(lines)


def render_identifiers_md(title: str, intro: str, convs: list, mappings: list) -> str:
    """标识符约定 + 跨码空间映射规则。防猜码 404 的 no-guessing 骨架。"""
    lines = [f"# {title}\n", f"> {intro}\n", "## 标识符约定\n",
             "| 实体 | 主键字段 | 前缀 | 示例值 | 说明 |",
             "|---|---|---|---|---|"]
    for c in convs:
        lines.append(f"| {c['entity']} | `{c['field']}` | `{c['prefix']}` | `{c['example']}` | {c['note']} |")
    lines += ["\n## 跨码空间映射规则（调 path 参数端点前必读，杜绝 404）\n"]
    for m in mappings:
        lines += [
            f"### `{m['from_field']}`（`{m['from_prefix']}`）→ `{m['to_field']}`（`{m['to_prefix']}`）",
            f"- 规则：{m['rule']}",
            f"- 示例：{m['example']}",
            f"- 原因：{m['why']}\n",
        ]
    return "\n".join(lines)


def render_readme_md(label: str, folder: str, ots: list, lts: list, ats: list, summary: str) -> str:
    cross = [lt for lt in lts if lt.get("crossSystem")]
    return "\n".join([
        f"# {label}\n",
        f"> {summary}\n",
        f"**对象类型 {len(ots)}**：" + "、".join(o["objectType"] for o in ots) + "  ",
        f"**链接类型 {len(lts)}**（跨系统 {len(cross)}）：" + "、".join(l["linkType"] for l in lts) + "  ",
        f"**动作类型 {len(ats)}**：" + ("、".join(a["actionType"] for a in ats) if ats else "无"), "",
        "> Palantir Foundry Ontology 规范；agent 运行时按任务配置注入对应文件 content。",
    ])


def _files_for(folder: str, label: str, ots: list, lts: list, ats: list, summary: str,
                convs: list | None = None, mappings: list | None = None):
    meta = {"system": folder.lower(), "source": "mock-agileac"}
    files = [
        (f"{folder}/README.md", render_readme_md(label, folder, ots, lts, ats, summary), {**meta, "kind": "readme"}),
        (f"{folder}/object-types.md", render_object_types_md(f"{label} · 对象类型", f"由 mock {folder} 数据接口（连接器 `agileac-{folder.lower()}`）支撑。", ots), {**meta, "kind": "object-types"}),
        (f"{folder}/link-types.md", render_link_types_md(f"{label} · 链接类型", f"定义 {label} 内部及跨系统对象间的关系。", lts), {**meta, "kind": "link-types"}),
        (f"{folder}/action-types.md", render_action_types_md(f"{label} · 动作类型", f"定义 {label} 上可执行的写操作。", ats), {**meta, "kind": "action-types"}),
    ]
    if convs:
        files.append((f"{folder}/identifiers.md",
                      render_identifiers_md(f"{label} · 标识符与码空间映射",
                                            f"{label} 各实体主键的命名约定与跨码空间映射规则。调用 path 参数端点前必读——杜绝把 MES 缺陷号当 PLM 故障案例号、把岗位码 P-ACCT 当产品款号 P-RC- 等 404。",
                                            convs, mappings or []),
                      {**meta, "kind": "identifiers"}))
    return files


# 组织级 7 个本体文件夹
ORG_SYSTEMS = [
    {
        "folder": "PLM", "label": "PLM 空调产品生命周期本体",
        "summary": "产品侧本体：空调产品/BOM/故障案例历史/成本台账/可行性留痕/卖点/凭证；故障→产品构成新品风险闭环。",
        "object_types": PLM_OBJECT_TYPES, "link_types": PLM_LINK_TYPES, "action_types": PLM_ACTION_TYPES,
        "conventions": PLM_IDENTIFIER_CONVENTIONS, "code_mappings": PLM_CODE_SPACE_MAPPINGS,
    },
    {
        "folder": "SCM", "label": "SCM 空调供应链协同本体",
        "summary": "供应链侧本体：供应商/报价/产能日历/配件到货/补单建议/交期快照/物料校验；跨系统关联 ERP 物料、MES 工单、PLM 成本台账。",
        "object_types": SCM_OBJECT_TYPES, "link_types": SCM_LINK_TYPES, "action_types": SCM_ACTION_TYPES,
        "conventions": SCM_IDENTIFIER_CONVENTIONS, "code_mappings": SCM_CODE_SPACE_MAPPINGS,
    },
    {
        "folder": "ERP", "label": "ERP 财务物料采购本体",
        "summary": "ERP 侧本体：物料/采购单/库存/应付/应收/凭证/生产成本/成本中心；凭证与 PLM 双侧呈现构成跨系统 SSO 演示。",
        "object_types": ERP_OBJECT_TYPES, "link_types": ERP_LINK_TYPES, "action_types": ERP_ACTION_TYPES,
        "conventions": ERP_IDENTIFIER_CONVENTIONS, "code_mappings": ERP_CODE_SPACE_MAPPINGS,
    },
    {
        "folder": "MES", "label": "MES 空调制造执行本体",
        "summary": "MES 侧本体：生产订单/工单/缺陷(8类空调故障)/设备/OEE/在制品；getDefectRootCause 提供 5W2H 根因 + 相似历史。",
        "object_types": MES_OBJECT_TYPES, "link_types": MES_LINK_TYPES, "action_types": MES_ACTION_TYPES,
        "conventions": MES_IDENTIFIER_CONVENTIONS, "code_mappings": MES_CODE_SPACE_MAPPINGS,
    },
    {
        "folder": "CRM", "label": "CRM 客户销售本体",
        "summary": "CRM 侧本体：客户/商机/报价/销售订单/客诉8D/应收/跟进；客诉关联 MES 工单+缺陷构成售后诊断闭环入口。",
        "object_types": CRM_OBJECT_TYPES, "link_types": CRM_LINK_TYPES, "action_types": CRM_ACTION_TYPES,
        "conventions": CRM_IDENTIFIER_CONVENTIONS, "code_mappings": CRM_CODE_SPACE_MAPPINGS,
    },
    {
        "folder": "HRM", "label": "HRM 人力资源本体",
        "summary": "HRM 侧本体：部门/岗位/员工/考勤/请假/薪酬/绩效/招聘/简历/会议；简历-招聘-会议构成 HR-01 招聘闭环。",
        "object_types": HRM_OBJECT_TYPES, "link_types": HRM_LINK_TYPES, "action_types": HRM_ACTION_TYPES,
        "conventions": HRM_IDENTIFIER_CONVENTIONS, "code_mappings": HRM_CODE_SPACE_MAPPINGS,
    },
    {
        "folder": "Cross", "label": "跨系统闭环本体",
        "summary": "跨系统链接：产品↔生产单↔工单↔缺陷↔故障历史↔产品（闭环）、客诉↔工单/缺陷、销售订单↔生产单↔应收↔凭证、采购单↔到货、报价↔物料、工单↔生产成本、凭证跨系统。",
        "object_types": [], "link_types": CROSS_LINK_TYPES, "action_types": CROSS_ACTION_TYPES,
    },
]

# 部门/团队级 4 个本体文件夹
DEPT_TEAM_SYSTEMS = [
    {
        "folder": "rnd-translation", "label": "研发翻译组本体（团队级）",
        "scope_type": "team", "dept_slug": "rnd", "team_slug": "rnd-translation",
        "summary": "翻译流程/术语条目/核对规则；关联 PLM.Style 做型号核对。",
        "object_types": RND_TRANSLATION_OBJECT_TYPES, "link_types": RND_TRANSLATION_LINK_TYPES, "action_types": RND_TRANSLATION_ACTION_TYPES,
    },
    {
        "folder": "after-sales", "label": "售后服务部本体（部门级）",
        "scope_type": "department", "dept_slug": "after-sales", "team_slug": None,
        "summary": "故障诊断流程/8D阶段/排查步骤/配件更换；关联 MES 工单 + ERP 物料构成 SVC-01 闭环。",
        "object_types": AFTER_SALES_OBJECT_TYPES, "link_types": AFTER_SALES_LINK_TYPES, "action_types": AFTER_SALES_ACTION_TYPES,
    },
    {
        "folder": "marketing", "label": "市场部本体（部门级）",
        "scope_type": "department", "dept_slug": "marketing", "team_slug": None,
        "summary": "营销内容类型/竞品对比维度/课件结构；关联 PLM.Style 卖点 + CRM.Customer 客户画像。",
        "object_types": MARKETING_OBJECT_TYPES, "link_types": MARKETING_LINK_TYPES, "action_types": MARKETING_ACTION_TYPES,
    },
    {
        "folder": "hr", "label": "人力资源部本体（部门级）",
        "scope_type": "department", "dept_slug": "hr", "team_slug": None,
        "summary": "招聘流程/培训体系/薪酬结构/员工制度；关联 HRM 简历/员工/薪酬/招聘。",
        "object_types": HR_OBJECT_TYPES, "link_types": HR_LINK_TYPES, "action_types": HR_ACTION_TYPES,
    },
]


async def _get_org(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(
        select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None))
    )
    org = result.scalar_one_or_none()
    if org is not None:
        return org
    result = await db.execute(
        select(Organization).where(Organization.name == ORG_NAME_FALLBACK, Organization.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def _get_dept_by_slug(db: AsyncSession, org_id, slug: str) -> Department | None:
    result = await db.execute(
        select(Department).where(
            Department.organization_id == org_id,
            Department.slug == slug,
            Department.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _get_team_by_slug(db: AsyncSession, dept_id, slug: str) -> Team | None:
    result = await db.execute(
        select(Team).where(
            Team.department_id == dept_id,
            Team.slug == slug,
            Team.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _seed_scope(
    db: AsyncSession, org_id, scope_type: str, scope_id: str | None,
    systems: list, scope_label: str,
) -> list:
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
            "object_types": len(s["object_types"]),
            "link_types": len(s["link_types"]),
            "action_types": len(s["action_types"]),
            "cross_system_links": sum(1 for lt in s["link_types"] if lt.get("crossSystem")),
            "identifiers": "✓" if s.get("conventions") else "",
            "files": len(files),
            "scope": scope_label,
        })
    return out


async def seed() -> dict:
    overall = {"scopes": []}
    async with async_session_factory() as db:
        org = await _get_org(db, ORG_SLUG)
        if org is None:
            raise RuntimeError(
                f"组织 slug='{ORG_SLUG}'（或名称='{ORG_NAME_FALLBACK}'）不存在，"
                "请先运行 python scripts/seed_agileac_org.py。"
            )
        logger.info("seed_agileac_ontology_org", slug=org.slug, org_id=str(org.id))

        # ── 组织级 7 个本体文件夹（28 文件） ──
        org_results = await _seed_scope(db, org.id, "organization", None, ORG_SYSTEMS, "organization")
        overall["scopes"].append({"scope": "organization", "systems": org_results})

        # ── 部门/团队级 4 个本体文件夹（16 文件） ──
        for s in DEPT_TEAM_SYSTEMS:
            if s["scope_type"] == "department":
                dept = await _get_dept_by_slug(db, org.id, s["dept_slug"])
                if dept is None:
                    raise RuntimeError(f"部门 slug='{s['dept_slug']}' 不存在，请先运行 seed_agileac_org.py。")
                scope_id = str(dept.id)
                scope_label = f"department:{s['dept_slug']}"
            else:  # team
                dept = await _get_dept_by_slug(db, org.id, s["dept_slug"])
                if dept is None:
                    raise RuntimeError(f"部门 slug='{s['dept_slug']}' 不存在，请先运行 seed_agileac_org.py。")
                team = await _get_team_by_slug(db, dept.id, s["team_slug"])
                if team is None:
                    raise RuntimeError(f"团队 slug='{s['team_slug']}'（部门 {s['dept_slug']}）不存在，请先运行 seed_agileac_org.py。")
                scope_id = str(team.id)
                scope_label = f"team:{s['dept_slug']}/{s['team_slug']}"

            res = await _seed_scope(db, org.id, s["scope_type"], scope_id, [s], scope_label)
            overall["scopes"].append({"scope": scope_label, "systems": res})

        await db.commit()
    return overall


def _print_report(result: dict) -> None:
    print("\n" + "=" * 72)
    print("敏睿空调本体导入完成（覆盖式幂等，可安全重复执行）")
    print("-" * 72)
    total_files = 0
    total_ot = total_lt = total_at = total_cross = 0
    for sc in result["scopes"]:
        print(f"\n[{sc['scope']}]")
        print(f"  {'文件夹':<22}{'对象类型':>8}{'链接类型':>8}{'跨系统':>6}{'动作类型':>8}{'标识符':>6}{'文件数':>6}")
        for s in sc["systems"]:
            print(f"  {s['folder']:<22}{s['object_types']:>8}{s['link_types']:>8}"
                  f"{s['cross_system_links']:>6}{s['action_types']:>8}{s['identifiers']:>6}{s['files']:>6}")
            total_ot += s["object_types"]
            total_lt += s["link_types"]
            total_at += s["action_types"]
            total_cross += s["cross_system_links"]
            total_files += s["files"]
    print("-" * 72)
    print(f"合计：{total_files} 个本体文件｜{total_ot} 对象类型｜{total_lt} 链接类型（跨系统 {total_cross}）｜{total_at} 动作类型")
    print("位置：管理端「敏睿空调」组织 → 本体（Ontology）→ PLM/SCM/ERP/MES/CRM/HRM/Cross/（组织级）")
    print("        + rnd-translation（团队级）/ after-sales / marketing / hr（部门级）")
    print("PLM/CRM/MES/HRM/ERP 各域含 identifiers.md（标识符约定 + 跨码空间映射），agent 推理时按用户 scope 注入。")
    print("=" * 72)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
