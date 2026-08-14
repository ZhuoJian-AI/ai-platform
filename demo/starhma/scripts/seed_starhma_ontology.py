"""为「星途热熔胶」组织创建本体文件（6 组织级域 + Cross）。

每个域 4 文件：README/object-types/link-types/action-types；FRM/PCM/QAS/ERP/MES/CRM
各含 identifiers.md（标识符约定 + 跨码空间映射规则）—— 防猜码 404 的 no-guessing 骨架。
外加 cross/README.md + cross/identifiers.md（承载 §4 8 条跨系统闭环）。
沿用 starexploration/agilestationery/agilesteel 的 render_identifiers_md + _files_for + _seed_scope 模式。

用法:
    docker cp demo/starhma/scripts/seed_starhma_ontology.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_starhma_ontology.py
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

ORG_SLUG = "starhma"
ORG_NAME_FALLBACK = "星途热熔胶"


# ───────────────────────── 标识符约定（no-guessing 骨架） ─────────────────────────

FRM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Formula", "field": "formula_no", "prefix": "FORM-", "example": "FORM-STD-001",
     "note": "配方（FORM-STD- 标准品 / FORM-CUS- 定制；标准品 product_code→ERP 成品胶 M-FG-，定制→MES 批次 BAT- 按 formula_no 关联）"},
    {"entity": "Ingredient", "field": "ingredient_code", "prefix": "ING-", "example": "ING-RES-001",
     "note": "原料组分（ING-RES- 树脂 / ING-TK- 增粘 / ING-WAX- 蜡 / ING-AO- 抗氧；→ERP 采购物料 M-RES-/M-TK-/M-WAX-/M-AO- prefix 转换）"},
    {"entity": "Experiment", "field": "exp_no", "prefix": "EXP-", "example": "EXP-RHE-001",
     "note": "实验（EXP-RHE- 流变 / EXP-TEN- 拉力 / EXP-ADH- 持粘）；性能预测输出 PERF-"},
    {"entity": "Sample", "field": "sample_no", "prefix": "SMP-", "example": "SMP-2026-002", "note": "实验样品（关联 formula_no/exp_no）"},
    {"entity": "TestScheme", "field": "scheme_no", "prefix": "TS-", "example": "TS-001", "note": "测试方案（关联 formula_no，含检测项与判定标准）"},
    {"entity": "FailureRecord", "field": "fr_no", "prefix": "FR-", "example": "FR-2025-021",
     "note": "配方失效记录（关联 formula_no/batch_no/related_exp_no）"},
]
FRM_CODE_SPACE_MAPPINGS = [
    {"from_field": "Ingredient.ingredient_code", "from_prefix": "ING-RES-", "to_field": "ERP.Material.material_code", "to_prefix": "M-RES-",
     "rule": "FRM 组分 ING-RES-/ING-TK-/ING-WAX-/ING-AO- 与 ERP 采购物料 M-RES-/M-TK-/M-WAX-/M-AO- 不同前缀但同实体，按 material_code 关联（prefix 转换：ING-RES-→M-RES-）：调 FRM listIngredients 收 ING-，调 ERP listMaterials 收 M-，勿互传",
     "example": "listIngredients(ingredient_code='ING-RES-001') ↔ ERP listMaterials(material_code='M-RES-001')",
     "why": "组分转采购物料需 prefix 转换，直传 ING- 必 404"},
    {"from_field": "Formula.formula_no", "from_prefix": "FORM-STD-", "to_field": "ERP.Material.material_code", "to_prefix": "M-FG-",
     "rule": "标准品配方 FORM-STD-.product_code 字段值即 ERP 成品胶 M-FG-，按 material_code 关联：调 FRM getFormula(formula_no='FORM-STD-001').product_code='M-FG-001' → ERP listMaterials(material_code='M-FG-001')，勿把 FORM- 当 M-FG- 传 ERP",
     "example": "getFormula('FORM-STD-001').product_code='M-FG-001' → ERP listMaterials(material_code='M-FG-001')",
     "why": "标准品配方→成品胶，跨 FRM/ERP 按 product_code 跳转"},
    {"from_field": "Formula.formula_no", "from_prefix": "FORM-CUS-", "to_field": "MES.Batch.batch_no", "to_prefix": "BAT-",
     "rule": "定制配方 FORM-CUS- 转 MES 生产批次 BAT-，按 formula_no 关联（BAT-2026-0703.formula_no='FORM-CUS-001'）：调 FRM getFormula 收 FORM-CUS-，调 MES listBatches(formula_no='FORM-CUS-001') 收 BAT-，勿把 FORM- 当 BAT- 传 MES",
     "example": "getFormula('FORM-CUS-001') ↔ MES listBatches(formula_no='FORM-CUS-001').batch_no='BAT-2026-0703'",
     "why": "定制配方转产→批次，跨 FRM/MES 按 formula_no 跳转"},
]
PCM_IDENTIFIER_CONVENTIONS = [
    {"entity": "ProcessParam", "field": "pp_no", "prefix": "PP-", "example": "PP-REACT-002",
     "note": "工艺参数（PP-STIR- 搅拌 / PP-REACT- 反应 / PP-COOL- 冷却；formula_no→FRM FORM-，product_code→ERP M-FG-）"},
    {"entity": "Equipment", "field": "eq_no", "prefix": "EQ-", "example": "EQ-MTR-02",
     "note": "设备（EQ-RX- 反应釜 / EQ-MTR- 电机 / EQ-GRN- 造粒机；line 字段关联 MES LINE-）"},
    {"entity": "ScheduleRule", "field": "rule_no", "prefix": "PSCH-", "example": "PSCH-001",
     "note": "排产建议（关联 line/product_code；故障预测输出 PM-）"},
]
PCM_CODE_SPACE_MAPPINGS = [
    {"from_field": "ProcessParam.formula_no", "from_prefix": "PP-", "to_field": "FRM.Formula.formula_no", "to_prefix": "FORM-",
     "rule": "工艺参数 PP-.formula_no 字段值即 FRM 配方码 FORM-，按 formula_no 关联：调 PCM listProcessParams 收 PP-，调 FRM getFormula(formula_no=pp.formula_no)，勿把 PP- 当 FORM- 传 FRM",
     "example": "listProcessParams(pp_no='PP-REACT-002').formula_no='FORM-CUS-002' → FRM getFormula('FORM-CUS-002')",
     "why": "工艺参数挂配方，跨 PCM/FRM 按 formula_no 跳转"},
    {"from_field": "ProcessParam.product_code", "from_prefix": "PP-", "to_field": "ERP.Material.material_code", "to_prefix": "M-FG-",
     "rule": "工艺参数 PP-.product_code 字段值即 ERP 成品胶 M-FG-，按 material_code 关联：调 PCM listProcessParams 收 PP-，调 ERP listMaterials(material_code=pp.product_code)，勿把 PP- 当 M-FG- 传 ERP",
     "example": "listProcessParams(pp_no='PP-REACT-002').product_code='M-FG-002' → ERP listMaterials(material_code='M-FG-002')",
     "why": "工艺参数挂成品胶，跨 PCM/ERP 按 product_code 跳转"},
    {"from_field": "Equipment.line", "from_prefix": "EQ-", "to_field": "MES.Line.line_no", "to_prefix": "LINE-",
     "rule": "PCM 设备 EQ-.line 字段值即 MES 产线码 LINE-，按 line_no 关联：调 PCM listEquipment 收 EQ-，调 MES listLines(line_no=eq.line)，勿把 EQ- 当 LINE- 传 MES",
     "example": "getEquipment(eq_no='EQ-MTR-02').line='LINE-AUTO-02' → MES listLines(line_no='LINE-AUTO-02')",
     "why": "设备挂产线，跨 PCM/MES 按 line 字段跳转"},
    {"from_field": "ScheduleRule.rule_no", "from_prefix": "PSCH-", "to_field": "MES.WorkOrder.wo_no", "to_prefix": "WO",
     "rule": "PCM 排产建议 PSCH- 与 MES 工单 WO 按 work_order_no 关联（PSCH- 落产工单 WO）：调 PCM optimizeProductionSchedule 收 PSCH-，调 MES listWorkOrders(wo_no=...) 收 WO，勿把 PSCH- 当 WO 传 MES",
     "example": "optimizeProductionSchedule(...).recommended[].work_order_no='WO202607001' → MES getWorkOrder('WO202607001')",
     "why": "排产→工单，跨 PCM/MES 按 work_order_no 跳转"},
]
QAS_IDENTIFIER_CONVENTIONS = [
    {"entity": "QualityReport", "field": "qr_no", "prefix": "QR-", "example": "QR-FG-2026-002",
     "note": "检测报告（QR-IN- 来料 / QR-FG- 成品；batch_no→MES BAT-，material_code→ERP M-，formula_no→FRM FORM-）"},
    {"entity": "CustomerComplaint", "field": "cc_no", "prefix": "CC-", "example": "CC-2026-001",
     "note": "售后粘接故障客诉（开胶/拉丝/堵枪/低温失效；customer_code→CRM CLI-，formula_no/batch_no→FRM/MES）"},
    {"entity": "FailureCase", "field": "case_no", "prefix": "FC-", "example": "FC-2025-008", "note": "故障案例（关联 related_cc_no/related_formula_no；根因输出 RCA-）"},
    {"entity": "NgRecord", "field": "ng_no", "prefix": "NG-", "example": "NG-2026-001", "note": "不良品记录（batch_no→MES BAT-）"},
]
QAS_CODE_SPACE_MAPPINGS = [
    {"from_field": "QualityReport.batch_no", "from_prefix": "QR-", "to_field": "MES.Batch.batch_no", "to_prefix": "BAT-",
     "rule": "检测报告 QR-.batch_no 字段值即 MES 批次码 BAT-，按 batch_no 关联：调 QAS listQualityReports 收 QR-，调 MES listBatches(batch_no=qr.batch_no)，勿把 QR- 当 BAT- 传 MES",
     "example": "getQualityReport(qr_no='QR-FG-2026-002').batch_no='BAT-2026-0702' → MES listBatches(batch_no='BAT-2026-0702')",
     "why": "成品检测挂批次，跨 QAS/MES 按 batch_no 跳转"},
    {"from_field": "QualityReport.material_code", "from_prefix": "QR-", "to_field": "ERP.Material.material_code", "to_prefix": "M-",
     "rule": "来料检测 QR-IN-.material_code 字段值即 ERP 物料码 M-（M-RES-/M-TK-/...），按 material_code 关联：调 QAS listQualityReports 收 QR-，调 ERP listMaterials(material_code=qr.material_code)，勿把 QR- 当 M- 传 ERP",
     "example": "getQualityReport(qr_no='QR-IN-2026-001').material_code='M-RES-001' → ERP listMaterials(material_code='M-RES-001')",
     "why": "来料检测挂物料，跨 QAS/ERP 按 material_code 跳转"},
    {"from_field": "QualityReport.formula_no", "from_prefix": "QR-", "to_field": "FRM.Formula.formula_no", "to_prefix": "FORM-",
     "rule": "检测报告 QR-.formula_no 字段值即 FRM 配方码 FORM-，按 formula_no 关联：调 QAS listQualityReports 收 QR-，调 FRM getFormula(formula_no=qr.formula_no)，勿把 QR- 当 FORM- 传 FRM",
     "example": "getQualityReport(qr_no='QR-FG-2026-002').formula_no='FORM-CUS-002' → FRM getFormula('FORM-CUS-002')",
     "why": "成品检测挂配方，跨 QAS/FRM 按 formula_no 跳转"},
    {"from_field": "CustomerComplaint.customer_code", "from_prefix": "CC-", "to_field": "CRM.Customer.customer_code", "to_prefix": "CLI-",
     "rule": "客诉 CC-.customer_code 字段值即 CRM 客户码 CLI-，按 customer_code 关联：调 QAS listCustomerComplaints 收 CC-，调 CRM listCustomers(customer_code=cc.customer_code)，勿把 CC- 当 CLI- 传 CRM",
     "example": "getCustomerComplaint(cc_no='CC-2026-001').customer_code='CLI-001' → CRM listCustomers(customer_code='CLI-001')",
     "why": "客诉挂客户，跨 QAS/CRM 按 customer_code 跳转"},
    {"from_field": "CustomerComplaint.formula_no", "from_prefix": "CC-", "to_field": "FRM.Formula.formula_no", "to_prefix": "FORM-",
     "rule": "客诉 CC-.formula_no 字段值即 FRM 配方码 FORM-，按 formula_no 关联：调 QAS listCustomerComplaints 收 CC-，调 FRM getFormula(formula_no=cc.formula_no)，勿把 CC- 当 FORM- 传 FRM",
     "example": "getCustomerComplaint(cc_no='CC-2026-001').formula_no='FORM-CUS-001' → FRM getFormula('FORM-CUS-001')",
     "why": "客诉挂配方，跨 QAS/FRM 按 formula_no 跳转"},
    {"from_field": "CustomerComplaint.batch_no", "from_prefix": "CC-", "to_field": "MES.Batch.batch_no", "to_prefix": "BAT-",
     "rule": "客诉 CC-.batch_no 字段值即 MES 批次码 BAT-，按 batch_no 关联：调 QAS listCustomerComplaints 收 CC-，调 MES listBatches(batch_no=cc.batch_no)，勿把 CC- 当 BAT- 传 MES",
     "example": "getCustomerComplaint(cc_no='CC-2026-001').batch_no='BAT-2026-0703' → MES listBatches(batch_no='BAT-2026-0703')",
     "why": "客诉挂批次，跨 QAS/MES 按 batch_no 跳转"},
    {"from_field": "NgRecord.batch_no", "from_prefix": "NG-", "to_field": "MES.Batch.batch_no", "to_prefix": "BAT-",
     "rule": "不良品 NG-.batch_no 字段值即 MES 批次码 BAT-，按 batch_no 关联：调 QAS listNgRecords 收 NG-，调 MES listBatches(batch_no=ng.batch_no)，勿把 NG- 当 BAT- 传 MES",
     "example": "listNgRecords(ng_no='NG-2026-001').batch_no='BAT-2026-0702' → MES listBatches(batch_no='BAT-2026-0702')",
     "why": "不良品挂批次，跨 QAS/MES 按 batch_no 跳转"},
]
ERP_IDENTIFIER_CONVENTIONS = [
    {"entity": "Supplier", "field": "supplier_code", "prefix": "S-HMA-", "example": "S-HMA-001", "note": "供应商"},
    {"entity": "Material", "field": "material_code", "prefix": "M-", "example": "M-RES-001",
     "note": "物料（M-RES- 树脂 / M-TK- 增粘 / M-WAX- 蜡 / M-AO- 抗氧 / M-FG- 成品胶；与 FRM 组分 ING- prefix 转换关联）"},
    {"entity": "Warehouse", "field": "wh_no", "prefix": "WH-HMA-", "example": "WH-HMA-001", "note": "仓库"},
    {"entity": "PurchaseOrder", "field": "po_no", "prefix": "POHMA", "example": "POHMA202607001", "note": "采购单"},
    {"entity": "Inventory", "field": "stock_id", "prefix": "STK-", "example": "STK-001",
     "note": "库存（按 material_code+wh_no 定位，非独立业务码；与发票 INV 无关）"},
    {"entity": "Payable", "field": "payable_id", "prefix": "HMAAP", "example": "HMAAP202607001", "note": "应付（invoice_no 关联 CRM 发票 INV）"},
    {"entity": "Voucher", "field": "voucher_no", "prefix": "BV-HMA-", "example": "BV-HMA-2026-0701",
     "note": "财务凭证（与 CRM 发票 INV 按 invoice_no/voucher_no 关联）"},
    {"entity": "CostCenter", "field": "cc_code", "prefix": "CC-HMA-", "example": "CC-HMA-001", "note": "成本中心"},
    {"entity": "ProductionCost", "field": "cost_id", "prefix": "PC-HMA-", "example": "PC-HMA-202607001",
     "note": "生产成本（heat_no 承载 MES 批次 BAT-；work_order_no 引用 CRM 合同 CT-HMA-）"},
]
ERP_CODE_SPACE_MAPPINGS = [
    {"from_field": "Material.material_code", "from_prefix": "M-RES-", "to_field": "FRM.Ingredient.ingredient_code", "to_prefix": "ING-RES-",
     "rule": "ERP 物料 M-RES-/M-TK-/M-WAX-/M-AO- 与 FRM 组分 ING-RES-/ING-TK-/ING-WAX-/ING-AO- 不同前缀但同实体，按 material_code 关联（prefix 转换：M-RES-→ING-RES-）：调 ERP listMaterials 收 M-，调 FRM listIngredients 收 ING-，勿互传",
     "example": "listMaterials(material_code='M-RES-001') ↔ FRM listIngredients(ingredient_code='ING-RES-001')",
     "why": "物料与组分 prefix 不同，直传必 404"},
    {"from_field": "Material.material_code", "from_prefix": "M-FG-", "to_field": "FRM.Formula.formula_no", "to_prefix": "FORM-STD-",
     "rule": "ERP 成品胶 M-FG- 与 FRM 标准品配方 FORM-STD- 按 product_code/formula_no 关联（M-FG-001.product_code 对应 FORM-STD-001）：调 ERP listMaterials 收 M-FG-，调 FRM getFormula，勿把 M-FG- 当 FORM- 传 FRM",
     "example": "listMaterials(material_code='M-FG-001') ↔ FRM getFormula('FORM-STD-001').product_code='M-FG-001'",
     "why": "成品胶与标准品配方跨 ERP/FRM 按 product_code 跳转"},
    {"from_field": "Voucher.voucher_no", "from_prefix": "BV-HMA-", "to_field": "CRM.Receivable.invoice_no", "to_prefix": "INV",
     "rule": "ERP 凭证 BV-HMA- 与 CRM 发票 INV 不同码空间，按 invoice_no/voucher_no 关联（INV202607001↔BV-HMA-2026-0701）：调 ERP listVouchers 收 BV-HMA-，调 CRM listReceivables 收 INV，勿互传",
     "example": "listVouchers(voucher_no='BV-HMA-2026-0701') vs listReceivables(invoice_no='INV202607001')",
     "why": "凭证与发票不同码空间，直传必 404"},
    {"from_field": "ProductionCost.work_order_no", "from_prefix": "PC-HMA-", "to_field": "CRM.SalesOrder.so_no", "to_prefix": "CT-HMA-",
     "rule": "生产成本 PC-HMA-.work_order_no 字段承载 CRM 合同号 CT-HMA-，按 so_no 关联：调 ERP listProductionCosts 收 PC-HMA-，调 CRM listSalesOrders(so_no=pc.work_order_no)，勿把 PC-HMA- 当 CT-HMA- 传 CRM",
     "example": "listProductionCosts(cost_id='PC-HMA-202607001').work_order_no='CT-HMA-001' → CRM listSalesOrders(so_no='CT-HMA-001')",
     "why": "生产成本挂合同，跨 ERP/CRM 按 work_order_no 跳转"},
    {"from_field": "ProductionCost.heat_no", "from_prefix": "PC-HMA-", "to_field": "MES.Batch.batch_no", "to_prefix": "BAT-",
     "rule": "生产成本 PC-HMA-.heat_no 字段承载 MES 批次号 BAT-，按 batch_no 关联：调 ERP listProductionCosts 收 PC-HMA-，调 MES listBatches(batch_no=pc.heat_no)，勿把 PC-HMA- 当 BAT- 传 MES",
     "example": "listProductionCosts(cost_id='PC-HMA-202607001').heat_no='BAT-2026-0703' → MES listBatches(batch_no='BAT-2026-0703')",
     "why": "生产成本挂批次，跨 ERP/MES 按 heat_no 跳转"},
]
MES_IDENTIFIER_CONVENTIONS = [
    {"entity": "Line", "field": "line_no", "prefix": "LINE-", "example": "LINE-AUTO-01",
     "note": "产线（LINE-AUTO-01/02 全自动 / LINE-03/04 半自动）"},
    {"entity": "Equipment", "field": "eq_no", "prefix": "EQ-", "example": "EQ-MTR-02",
     "note": "设备（与 PCM 共享 EQ- 码空间：EQ-RX- 反应釜 / EQ-MTR- 电机 / EQ-GRN- 造粒机）"},
    {"entity": "Product", "field": "product_code", "prefix": "M-FG-", "example": "M-FG-002",
     "note": "成品胶产品（与 ERP 物料 M-FG- 共享码空间）"},
    {"entity": "Routing", "field": "routing_no", "prefix": "ROUTE-", "example": "ROUTE-001", "note": "工艺路线（关联 product_code）"},
    {"entity": "WorkOrder", "field": "wo_no", "prefix": "WO", "example": "WO202607001", "note": "工单（关联 product_code/line_no）"},
    {"entity": "Batch", "field": "batch_no", "prefix": "BAT-", "example": "BAT-2026-0701",
     "note": "生产批次（formula_no→FRM FORM-CUS-；→QAS QR-FG-/NG-；→ERP PC-HMA-.heat_no）"},
    {"entity": "WorkReport", "field": "report_no", "prefix": "WR-", "example": "WR-2026-0701", "note": "报工（关联 batch_no/line_no）"},
    {"entity": "Defect", "field": "defect_no", "prefix": "DF-", "example": "DF-2026-001", "note": "不良（关联 batch_no）"},
]
MES_CODE_SPACE_MAPPINGS = [
    {"from_field": "Product.product_code", "from_prefix": "M-FG-", "to_field": "ERP.Material.material_code", "to_prefix": "M-FG-",
     "rule": "MES 成品胶产品 M-FG- 与 ERP 物料 M-FG- 同码空间共享，按 product_code/material_code 直接关联：调 MES listProducts 收 M-FG-，调 ERP listMaterials(material_code=...)，码相同可直接传",
     "example": "listProducts(product_code='M-FG-002') ↔ ERP listMaterials(material_code='M-FG-002')",
     "why": "成品胶跨 MES/ERP 共享 M-FG- 码空间"},
    {"from_field": "Batch.formula_no", "from_prefix": "BAT-", "to_field": "FRM.Formula.formula_no", "to_prefix": "FORM-CUS-",
     "rule": "MES 批次 BAT-.formula_no 字段值即 FRM 定制配方码 FORM-CUS-，按 formula_no 关联：调 MES listBatches 收 BAT-，调 FRM getFormula(formula_no=batch.formula_no)，勿把 BAT- 当 FORM- 传 FRM",
     "example": "listBatches(batch_no='BAT-2026-0703').formula_no='FORM-CUS-001' → FRM getFormula('FORM-CUS-001')",
     "why": "批次挂定制配方，跨 MES/FRM 按 formula_no 跳转"},
    {"from_field": "Batch.batch_no", "from_prefix": "BAT-", "to_field": "QAS.QualityReport.qr_no", "to_prefix": "QR-FG-",
     "rule": "MES 批次 BAT- 转 QAS 成品检测 QR-FG-，按 batch_no 关联：调 MES listBatches 收 BAT-，调 QAS listQualityReports(batch_no=...) 收 QR-FG-，勿把 BAT- 当 QR- 传 QAS",
     "example": "listBatches(batch_no='BAT-2026-0702') ↔ QAS listQualityReports(batch_no='BAT-2026-0702').qr_no='QR-FG-2026-002'",
     "why": "批次→成品检测，跨 MES/QAS 按 batch_no 跳转"},
    {"from_field": "Batch.batch_no", "from_prefix": "BAT-", "to_field": "QAS.NgRecord.ng_no", "to_prefix": "NG-",
     "rule": "MES 批次 BAT- 转 QAS 不良品 NG-，按 batch_no 关联：调 MES listBatches 收 BAT-，调 QAS listNgRecords(batch_no=...) 收 NG-，勿把 BAT- 当 NG- 传 QAS",
     "example": "listBatches(batch_no='BAT-2026-0702') ↔ QAS listNgRecords(batch_no='BAT-2026-0702').ng_no='NG-2026-001'",
     "why": "批次→不良品，跨 MES/QAS 按 batch_no 跳转"},
    {"from_field": "Batch.batch_no", "from_prefix": "BAT-", "to_field": "ERP.ProductionCost.heat_no", "to_prefix": "PC-HMA-",
     "rule": "MES 批次 BAT- 承载于 ERP 生产成本 PC-HMA-.heat_no 字段，按 batch_no/heat_no 关联：调 MES listBatches 收 BAT-，调 ERP listProductionCosts(heat_no=...) 收 PC-HMA-，勿把 BAT- 当 PC-HMA- 传 ERP",
     "example": "listBatches(batch_no='BAT-2026-0703') ↔ ERP listProductionCosts(heat_no='BAT-2026-0703').cost_id='PC-HMA-202607001'",
     "why": "批次→生产成本，跨 MES/ERP 按 heat_no 跳转"},
    {"from_field": "Equipment.eq_no", "from_prefix": "EQ-", "to_field": "PCM.Equipment.eq_no", "to_prefix": "EQ-",
     "rule": "MES 设备 EQ- 与 PCM 设备 EQ- 同码空间共享（同一台设备），按 eq_no 直接关联：调 MES listEquipment 收 EQ-，调 PCM getEquipment(eq_no=...)，码相同可直接传",
     "example": "MES getEquipment(eq_no='EQ-MTR-02') ↔ PCM getEquipment(eq_no='EQ-MTR-02')",
     "why": "设备跨 MES/PCM 共享 EQ- 码空间"},
]
CRM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Customer", "field": "customer_code", "prefix": "CLI-", "example": "CLI-001",
     "note": "客户（汽车内饰/医疗/食品日化包装/物流快递袋/鞋材箱包/粘扣带/家居七大下游）"},
    {"entity": "Contact", "field": "contact_id", "prefix": "CONT-", "example": "CONT-001", "note": "客户联系人"},
    {"entity": "Opportunity", "field": "opp_no", "prefix": "INQ-", "example": "INQ-002", "note": "询盘/商机（按基材/工况需求解析）"},
    {"entity": "Quotation", "field": "quote_no", "prefix": "HMAQT-", "example": "HMAQT-002", "note": "报价"},
    {"entity": "SalesOrder", "field": "so_no", "prefix": "CT-HMA-", "example": "CT-HMA-001",
     "note": "合同（与 ERP 生产成本 PC-HMA-.work_order_no 关联）"},
    {"entity": "FollowUp", "field": "follow_up_id", "prefix": "FU-", "example": "FU-2026-001", "note": "跟进记录"},
    {"entity": "Complaint", "field": "case_id", "prefix": "DSP-HMA-", "example": "DSP-HMA-001", "note": "争议/纠纷（区别于 QAS 售后客诉 CC-）"},
    {"entity": "Receivable", "field": "receivable_id", "prefix": "HMAAR-", "example": "HMAAR-2026-001",
     "note": "回款；invoice_no 前缀 INV（INV202607001，与 ERP 凭证 BV-HMA- 按 invoice_no 关联）"},
]
CRM_CODE_SPACE_MAPPINGS = [
    {"from_field": "SalesOrder.so_no", "from_prefix": "CT-HMA-", "to_field": "ERP.ProductionCost.work_order_no", "to_prefix": "PC-HMA-",
     "rule": "CRM 合同 CT-HMA- 承载于 ERP 生产成本 PC-HMA-.work_order_no 字段，按 so_no/work_order_no 关联：调 CRM listSalesOrders 收 CT-HMA-，调 ERP listProductionCosts(work_order_no=...) 收 PC-HMA-，勿把 CT-HMA- 当 PC-HMA- 传 ERP",
     "example": "listSalesOrders(so_no='CT-HMA-001') ↔ ERP listProductionCosts(work_order_no='CT-HMA-001').cost_id='PC-HMA-202607001'",
     "why": "合同→生产成本，跨 CRM/ERP 按 work_order_no 跳转"},
    {"from_field": "Receivable.invoice_no", "from_prefix": "INV", "to_field": "ERP.Voucher.voucher_no", "to_prefix": "BV-HMA-",
     "rule": "CRM 回款发票 INV 与 ERP 凭证 BV-HMA- 不同码空间，按 invoice_no/voucher_no 关联（INV202607001↔BV-HMA-2026-0701）：调 CRM listReceivables 收 INV，调 ERP listVouchers(voucher_no=...) 收 BV-HMA-，勿互传",
     "example": "listReceivables(invoice_no='INV202607001') vs listVouchers(voucher_no='BV-HMA-2026-0701')",
     "why": "发票与凭证不同码空间，直传必 404"},
]
CROSS_IDENTIFIER_CONVENTIONS = [
    {"entity": "闭环1 组分→采购物料", "field": "ingredient_code/material_code", "prefix": "ING-RES-/M-RES-", "example": "ING-RES-001↔M-RES-001",
     "note": "FRM 组分 ING- → ERP 采购物料 M-（prefix 转换 ING-RES-→M-RES-）"},
    {"entity": "闭环2 配方→成品胶", "field": "formula_no/product_code", "prefix": "FORM-STD-/M-FG-", "example": "FORM-STD-001↔M-FG-001",
     "note": "FRM 标准品配方 FORM-STD- → ERP 成品胶 M-FG-（按 product_code）"},
    {"entity": "闭环3 定制配方→生产批次", "field": "formula_no", "prefix": "FORM-CUS-/BAT-", "example": "FORM-CUS-001↔BAT-2026-0703",
     "note": "FRM 定制配方 FORM-CUS- → MES 生产批次 BAT-（按 formula_no）"},
    {"entity": "闭环4 设备→产线 + 排产→工单", "field": "line / work_order_no", "prefix": "EQ-/LINE- | PSCH-/WO",
     "example": "EQ-MTR-02↔LINE-AUTO-02 | PSCH-001↔WO202607001",
     "note": "PCM 设备 EQ- → MES 产线 LINE-（按 line）；PCM 排产 PSCH- → MES 工单 WO（按 work_order_no）"},
    {"entity": "闭环5 批次→质检/不良", "field": "batch_no", "prefix": "BAT-/QR-FG- | BAT-/NG-", "example": "BAT-2026-0702↔QR-FG-2026-002 / NG-2026-001",
     "note": "MES 批次 BAT- → QAS 成品检测 QR-FG- / 不良品 NG-（按 batch_no）"},
    {"entity": "闭环6 客诉→客户", "field": "customer_code", "prefix": "CC-/CLI-", "example": "CC-2026-001↔CLI-001",
     "note": "QAS 售后客诉 CC- → CRM 客户 CLI-（按 customer_code）"},
    {"entity": "闭环7 发票→凭证", "field": "invoice_no/voucher_no", "prefix": "INV/BV-HMA-", "example": "INV202607001↔BV-HMA-2026-0701",
     "note": "CRM 发票 INV → ERP 凭证 BV-HMA-（按 invoice_no，对账闭环）"},
    {"entity": "闭环8 合同/批次→生产成本", "field": "work_order_no / heat_no", "prefix": "CT-HMA-/BAT- → PC-HMA-",
     "example": "CT-HMA-001→PC-HMA-202607001.work_order_no；BAT-2026-0703→PC-HMA-202607001.heat_no",
     "note": "CRM 合同 CT-HMA- → ERP 生产成本 PC-HMA-.work_order_no；MES 批次 BAT- → ERP PC-HMA-.heat_no（成本归集）"},
]
CROSS_CODE_SPACE_MAPPINGS = [
    {"from_field": "FRM.Ingredient.ingredient_code", "from_prefix": "ING-RES-", "to_field": "ERP.Material.material_code", "to_prefix": "M-RES-",
     "rule": "组分→采购物料：ING-RES-/ING-TK-/ING-WAX-/ING-AO- prefix 转换为 M-RES-/M-TK-/M-WAX-/M-AO-，按 material_code 关联",
     "example": "ING-RES-001 ↔ M-RES-001", "why": "prefix 转换，直传 ING- 必 404"},
    {"from_field": "FRM.Formula.formula_no", "from_prefix": "FORM-STD-", "to_field": "ERP.Material.material_code", "to_prefix": "M-FG-",
     "rule": "标准品配方→成品胶：FORM-STD-.product_code 即 M-FG-，按 material_code 关联", "example": "FORM-STD-001↔M-FG-001", "why": "配方→成品胶跨 FRM/ERP"},
    {"from_field": "FRM.Formula.formula_no", "from_prefix": "FORM-CUS-", "to_field": "MES.Batch.batch_no", "to_prefix": "BAT-",
     "rule": "定制配方→生产批次：BAT-.formula_no 即 FORM-CUS-，按 formula_no 关联", "example": "FORM-CUS-001↔BAT-2026-0703", "why": "定制配方转产跨 FRM/MES"},
    {"from_field": "PCM.Equipment.line", "from_prefix": "EQ-", "to_field": "MES.Line.line_no", "to_prefix": "LINE-",
     "rule": "设备→产线：EQ-.line 即 LINE-，按 line_no 关联", "example": "EQ-MTR-02↔LINE-AUTO-02", "why": "设备挂产线跨 PCM/MES"},
    {"from_field": "PCM.ScheduleRule.work_order_no", "from_prefix": "PSCH-", "to_field": "MES.WorkOrder.wo_no", "to_prefix": "WO",
     "rule": "排产→工单：PSCH- 落产 WO，按 work_order_no 关联", "example": "PSCH-001↔WO202607001", "why": "排产跨 PCM/MES"},
    {"from_field": "MES.Batch.batch_no", "from_prefix": "BAT-", "to_field": "QAS.QualityReport.qr_no", "to_prefix": "QR-FG-",
     "rule": "批次→成品检测：BAT- 转 QR-FG-，按 batch_no 关联", "example": "BAT-2026-0702↔QR-FG-2026-002", "why": "批次质检跨 MES/QAS"},
    {"from_field": "MES.Batch.batch_no", "from_prefix": "BAT-", "to_field": "QAS.NgRecord.ng_no", "to_prefix": "NG-",
     "rule": "批次→不良品：BAT- 转 NG-，按 batch_no 关联", "example": "BAT-2026-0702↔NG-2026-001", "why": "批次不良跨 MES/QAS"},
    {"from_field": "QAS.CustomerComplaint.customer_code", "from_prefix": "CC-", "to_field": "CRM.Customer.customer_code", "to_prefix": "CLI-",
     "rule": "客诉→客户：CC-.customer_code 即 CLI-，按 customer_code 关联", "example": "CC-2026-001↔CLI-001", "why": "客诉挂客户跨 QAS/CRM"},
    {"from_field": "CRM.Receivable.invoice_no", "from_prefix": "INV", "to_field": "ERP.Voucher.voucher_no", "to_prefix": "BV-HMA-",
     "rule": "发票→凭证：INV 与 BV-HMA- 按 invoice_no/voucher_no 关联（对账闭环）", "example": "INV202607001↔BV-HMA-2026-0701", "why": "对账闭环跨 CRM/ERP"},
    {"from_field": "CRM.SalesOrder.so_no", "from_prefix": "CT-HMA-", "to_field": "ERP.ProductionCost.work_order_no", "to_prefix": "PC-HMA-",
     "rule": "合同→生产成本：CT-HMA- 承载于 PC-HMA-.work_order_no，按 so_no 关联", "example": "CT-HMA-001↔PC-HMA-202607001", "why": "成本归集跨 CRM/ERP"},
    {"from_field": "MES.Batch.batch_no", "from_prefix": "BAT-", "to_field": "ERP.ProductionCost.heat_no", "to_prefix": "PC-HMA-",
     "rule": "批次→生产成本：BAT- 承载于 PC-HMA-.heat_no，按 batch_no/heat_no 关联", "example": "BAT-2026-0703↔PC-HMA-202607001", "why": "成本归集跨 MES/ERP"},
]


# ───────────────────────── 对象/链接/动作类型（精简） ─────────────────────────

def _ot(name: str, pk: str, props: dict, desc: str = "", backing: str = "") -> dict:
    return {"objectType": name, "primaryKey": pk, "title": pk, "description": desc,
            "backingInterface": backing or f"mock.starhma.{name.lower()}",
            "properties": {k: {"type": v if isinstance(v, str) else "string", "description": k} for k, v in props.items()}}

def _lt(name: str, parent: str, child: str, join: str, cross: bool = False, desc: str = "") -> dict:
    return {"linkType": name, "parent": parent, "child": child, "cardinality": "1:N",
            "joinField": join, "crossSystem": cross, "description": desc}

def _at(name: str, desc: str = "") -> dict:
    return {"actionType": name, "description": desc}

FRM_OBJECT_TYPES = [
    _ot("Formula", "formula_no", {"formula_no": "str", "name": "str", "type": "str", "product_code": "str", "base_recipe": "str", "viscosity": "num", "open_time": "num", "peel_strength": "num", "cost_per_kg": "num", "status": "str"}, "配方"),
    _ot("Ingredient", "ingredient_code", {"ingredient_code": "str", "name": "str", "category": "str", "material_code": "str", "spec": "str", "unit_cost": "num"}, "原料组分"),
    _ot("Experiment", "exp_no", {"exp_no": "str", "formula_no": "str", "type": "str", "result": "str", "sample_desc": "str", "equipment_code": "str"}, "实验"),
    _ot("Sample", "sample_no", {"sample_no": "str", "formula_no": "str", "exp_no": "str", "batch_no": "str", "storage": "str", "status": "str"}, "实验样品"),
    _ot("TestScheme", "scheme_no", {"scheme_no": "str", "formula_no": "str", "items": "str", "criteria": "str", "standard": "str"}, "测试方案"),
    _ot("FailureRecord", "fr_no", {"fr_no": "str", "formula_no": "str", "batch_no": "str", "phenomenon": "str", "root_cause": "str", "related_exp_no": "str"}, "配方失效记录"),
]
FRM_LINK_TYPES = [
    _lt("ingredient_to_formula", "Ingredient", "Formula", "ingredient_code/formula_no", False, "组分关联配方"),
    _lt("experiment_to_formula", "Experiment", "Formula", "exp_no/formula_no", False, "实验关联配方"),
    _lt("sample_to_formula", "Sample", "Formula", "sample_no/formula_no", False, "样品关联配方"),
    _lt("sample_to_experiment", "Sample", "Experiment", "sample_no/exp_no", False, "样品关联实验"),
    _lt("testscheme_to_formula", "TestScheme", "Formula", "scheme_no/formula_no", False, "测试方案关联配方"),
    _lt("failurerecord_to_formula", "FailureRecord", "Formula", "fr_no/formula_no", False, "失效记录关联配方"),
    _lt("failurerecord_to_experiment", "FailureRecord", "Experiment", "fr_no/related_exp_no", False, "失效记录关联实验"),
    _lt("ingredient_to_material", "Ingredient", "ERP.Material", "ingredient_code/material_code", True, "组分关联 ERP 物料（prefix 转换 ING-RES-→M-RES-）"),
    _lt("formula_to_finishedgoods", "Formula", "ERP.Material", "formula_no/product_code", True, "标准品配方关联 ERP 成品胶 M-FG-"),
    _lt("formula_to_batch", "Formula", "MES.Batch", "formula_no/formula_no", True, "定制配方关联 MES 批次 BAT-"),
]
FRM_ACTION_TYPES = [
    _at("recommendFormula", "按基材/施胶温度/开放时间/剥离力/环保/成本约束推荐历史相似配方与初始配比（返回 FORM-/ING- 码）"),
    _at("predictPerformance", "对配方 FORM- 预估粘度/剥离力/开放时间等性能（输出 PERF- 预测值）"),
    _at("analyzeExperimentData", "分析流变 EXP-RHE-/拉力 EXP-TEN-/持粘 EXP-ADH- 实验数据，识别异常并关联失效记录 FR-"),
    _at("generateExperimentReport", "对配方 FORM-CUS- 生成标准化实验报告（汇总实验/样品/失效记录）"),
]

PCM_OBJECT_TYPES = [
    _ot("ProcessParam", "pp_no", {"pp_no": "str", "formula_no": "str", "product_code": "str", "stage": "str", "temp": "num", "speed": "num", "duration": "num"}, "工艺参数"),
    _ot("Equipment", "eq_no", {"eq_no": "str", "name": "str", "type": "str", "line": "str", "status": "str", "health_score": "num"}, "设备"),
    _ot("ScheduleRule", "rule_no", {"rule_no": "str", "line": "str", "product_code": "str", "work_order_no": "str", "changeover_cost": "num", "capacity_per_day": "num"}, "排产建议"),
]
PCM_LINK_TYPES = [
    _lt("processparam_to_equipment", "ProcessParam", "Equipment", "pp_no/eq_no", False, "工艺参数关联设备"),
    _lt("processparam_to_formula", "ProcessParam", "FRM.Formula", "pp_no/formula_no", True, "工艺参数关联 FRM 配方"),
    _lt("processparam_to_product", "ProcessParam", "ERP.Material", "pp_no/product_code", True, "工艺参数关联 ERP 成品胶 M-FG-"),
    _lt("equipment_to_line", "Equipment", "MES.Line", "eq_no/line", True, "设备关联 MES 产线 LINE-"),
    _lt("schedulerule_to_line", "ScheduleRule", "MES.Line", "rule_no/line", True, "排产建议关联 MES 产线"),
    _lt("schedulerule_to_workorder", "ScheduleRule", "MES.WorkOrder", "rule_no/work_order_no", True, "排产建议关联 MES 工单 WO"),
]
PCM_ACTION_TYPES = [
    _at("recommendProcessParams", "按配方 FORM-/产品 M-FG- 推荐工艺参数 PP-STIR-/PP-REACT-/PP-COOL-"),
    _at("predictEquipmentFault", "对设备 EQ- 基于振动/温升/健康分预测故障风险，给保养提醒（输出 PM-）"),
    _at("optimizeProductionSchedule", "综合 MES 工单 WO/产线 LINE- 负荷/换线成本给排产建议 PSCH- 与冲突订单"),
]

QAS_OBJECT_TYPES = [
    _ot("QualityReport", "qr_no", {"qr_no": "str", "type": "str", "batch_no": "str", "material_code": "str", "formula_no": "str", "result": "str", "inspector": "str"}, "检测报告"),
    _ot("CustomerComplaint", "cc_no", {"cc_no": "str", "customer_code": "str", "formula_no": "str", "batch_no": "str", "phenomenon": "str", "severity": "str"}, "售后粘接故障客诉"),
    _ot("FailureCase", "case_no", {"case_no": "str", "phenomenon": "str", "root_cause_code": "str", "related_cc_no": "str", "related_formula_no": "str"}, "故障案例"),
    _ot("NgRecord", "ng_no", {"ng_no": "str", "batch_no": "str", "defect_type": "str", "qty": "num", "disposition": "str"}, "不良品记录"),
]
QAS_LINK_TYPES = [
    _lt("failurecase_to_complaint", "FailureCase", "CustomerComplaint", "case_no/related_cc_no", False, "故障案例关联客诉"),
    _lt("qualityreport_to_batch", "QualityReport", "MES.Batch", "qr_no/batch_no", True, "检测报告关联 MES 批次 BAT-"),
    _lt("qualityreport_to_material", "QualityReport", "ERP.Material", "qr_no/material_code", True, "来料检测关联 ERP 物料 M-"),
    _lt("qualityreport_to_formula", "QualityReport", "FRM.Formula", "qr_no/formula_no", True, "检测报告关联 FRM 配方 FORM-"),
    _lt("complaint_to_customer", "CustomerComplaint", "CRM.Customer", "cc_no/customer_code", True, "客诉关联 CRM 客户 CLI-"),
    _lt("complaint_to_formula", "CustomerComplaint", "FRM.Formula", "cc_no/formula_no", True, "客诉关联 FRM 配方 FORM-"),
    _lt("complaint_to_batch", "CustomerComplaint", "MES.Batch", "cc_no/batch_no", True, "客诉关联 MES 批次 BAT-"),
    _lt("ngrecord_to_batch", "NgRecord", "MES.Batch", "ng_no/batch_no", True, "不良品关联 MES 批次 BAT-"),
]
QAS_ACTION_TYPES = [
    _at("diagnoseAfterSalesFault", "对客诉 CC- 按现象/基材/工况匹配故障案例 FC- 与历史客诉，给排查方案与配方调整建议"),
    _at("generateInspectionReport", "对批次 BAT-/来料 M- 生成检测报告 QR-IN-/QR-FG-"),
    _at("analyzeRootCause", "对不良 NG-/客诉 CC- 做根因分析，输出 RCA- 与改进措施"),
]

ERP_OBJECT_TYPES = [
    _ot("Supplier", "supplier_code", {"supplier_code": "str", "name": "str", "category": "str", "rating": "str"}, "供应商"),
    _ot("Material", "material_code", {"material_code": "str", "name": "str", "category": "str", "unit_cost": "num", "safety_stock": "num"}, "物料"),
    _ot("Warehouse", "wh_no", {"wh_no": "str", "name": "str", "location": "str", "type": "str"}, "仓库"),
    _ot("PurchaseOrder", "po_no", {"po_no": "str", "supplier_code": "str", "total_amount": "num", "status": "str"}, "采购单"),
    _ot("Inventory", "stock_id", {"stock_id": "str", "material_code": "str", "wh_no": "str", "qty": "num", "safety_stock": "num"}, "库存"),
    _ot("Payable", "payable_id", {"payable_id": "str", "supplier_code": "str", "invoice_no": "str", "amount": "num", "days_overdue": "int"}, "应付"),
    _ot("Voucher", "voucher_no", {"voucher_no": "str", "period": "str", "status": "str", "debit_total": "num"}, "财务凭证"),
    _ot("CostCenter", "cc_code", {"cc_code": "str", "name": "str", "type": "str"}, "成本中心"),
    _ot("ProductionCost", "cost_id", {"cost_id": "str", "heat_no": "str", "work_order_no": "str", "cost_center": "str", "total_cost": "num"}, "生产成本"),
]
ERP_LINK_TYPES = [
    _lt("po_to_supplier", "PurchaseOrder", "Supplier", "po_no/supplier_code", False, "采购单关联供应商"),
    _lt("po_to_material", "PurchaseOrder", "Material", "po_no/material_code", False, "采购单关联物料"),
    _lt("inventory_to_material", "Inventory", "Material", "stock_id/material_code", False, "库存关联物料"),
    _lt("inventory_to_warehouse", "Inventory", "Warehouse", "stock_id/wh_no", False, "库存关联仓库"),
    _lt("payable_to_po", "Payable", "PurchaseOrder", "payable_id/po_no", False, "应付关联采购单"),
    _lt("payable_to_supplier", "Payable", "Supplier", "payable_id/supplier_code", False, "应付关联供应商"),
    _lt("pc_to_costcenter", "ProductionCost", "CostCenter", "cost_id/cost_center", False, "生产成本关联成本中心"),
    _lt("material_to_ingredient", "Material", "FRM.Ingredient", "material_code/ingredient_code", True, "物料关联 FRM 组分（prefix 转换 M-RES-→ING-RES-）"),
    _lt("material_to_formula", "Material", "FRM.Formula", "material_code/product_code", True, "成品胶关联 FRM 标准品配方 FORM-STD-"),
    _lt("voucher_to_invoice", "Voucher", "CRM.Receivable", "voucher_no/invoice_no", True, "凭证关联 CRM 发票 INV"),
    _lt("pc_to_salesorder", "ProductionCost", "CRM.SalesOrder", "cost_id/work_order_no", True, "生产成本关联 CRM 合同 CT-HMA-"),
    _lt("pc_to_batch", "ProductionCost", "MES.Batch", "cost_id/heat_no", True, "生产成本关联 MES 批次 BAT-"),
]
ERP_ACTION_TYPES: list = []

MES_OBJECT_TYPES = [
    _ot("Line", "line_no", {"line_no": "str", "name": "str", "type": "str", "capacity_per_day": "num", "status": "str"}, "产线"),
    _ot("Equipment", "eq_no", {"eq_no": "str", "name": "str", "line_no": "str", "oee": "num", "status": "str"}, "设备（与 PCM 共享 EQ- 码）"),
    _ot("Product", "product_code", {"product_code": "str", "name": "str", "category": "str", "spec": "str"}, "成品胶产品"),
    _ot("Routing", "routing_no", {"routing_no": "str", "product_code": "str", "steps": "str", "std_cycle_time": "num"}, "工艺路线"),
    _ot("WorkOrder", "wo_no", {"wo_no": "str", "product_code": "str", "line_no": "str", "qty": "num", "plan_start": "str", "plan_end": "str", "status": "str"}, "工单"),
    _ot("Batch", "batch_no", {"batch_no": "str", "wo_no": "str", "formula_no": "str", "product_code": "str", "line_no": "str", "qty": "num", "status": "str"}, "生产批次"),
    _ot("WorkReport", "report_no", {"report_no": "str", "batch_no": "str", "line_no": "str", "output_qty": "num", "shift": "str", "operator": "str"}, "报工"),
    _ot("Defect", "defect_no", {"defect_no": "str", "batch_no": "str", "type": "str", "qty": "num", "root_cause": "str"}, "不良"),
]
MES_LINK_TYPES = [
    _lt("equipment_to_line", "Equipment", "Line", "eq_no/line_no", False, "设备关联产线"),
    _lt("routing_to_product", "Routing", "Product", "routing_no/product_code", False, "工艺路线关联产品"),
    _lt("wo_to_product", "WorkOrder", "Product", "wo_no/product_code", False, "工单关联产品"),
    _lt("wo_to_line", "WorkOrder", "Line", "wo_no/line_no", False, "工单关联产线"),
    _lt("batch_to_wo", "Batch", "WorkOrder", "batch_no/wo_no", False, "批次关联工单"),
    _lt("batch_to_product", "Batch", "Product", "batch_no/product_code", False, "批次关联产品"),
    _lt("workreport_to_batch", "WorkReport", "Batch", "report_no/batch_no", False, "报工关联批次"),
    _lt("defect_to_batch", "Defect", "Batch", "defect_no/batch_no", False, "不良关联批次"),
    _lt("product_to_material", "Product", "ERP.Material", "product_code/material_code", True, "产品关联 ERP 成品胶 M-FG-（共享码空间）"),
    _lt("batch_to_formula", "Batch", "FRM.Formula", "batch_no/formula_no", True, "批次关联 FRM 定制配方 FORM-CUS-"),
    _lt("batch_to_qualityreport", "Batch", "QAS.QualityReport", "batch_no/batch_no", True, "批次关联 QAS 成品检测 QR-FG-"),
    _lt("batch_to_ngrecord", "Batch", "QAS.NgRecord", "batch_no/batch_no", True, "批次关联 QAS 不良品 NG-"),
    _lt("batch_to_productioncost", "Batch", "ERP.ProductionCost", "batch_no/heat_no", True, "批次关联 ERP 生产成本 PC-HMA-"),
    _lt("mes_equipment_to_pcm", "Equipment", "PCM.Equipment", "eq_no/eq_no", True, "MES 设备关联 PCM 设备（共享 EQ- 码空间）"),
]
MES_ACTION_TYPES: list = []

CRM_OBJECT_TYPES = [
    _ot("Customer", "customer_code", {"customer_code": "str", "name": "str", "industry": "str", "credit_grade": "str"}, "客户"),
    _ot("Contact", "contact_id", {"contact_id": "str", "customer_code": "str", "name": "str", "position": "str", "phone": "str"}, "客户联系人"),
    _ot("Opportunity", "opp_no", {"opp_no": "str", "customer_code": "str", "product_code": "str", "requirement": "str", "stage": "str"}, "询盘/商机"),
    _ot("Quotation", "quote_no", {"quote_no": "str", "opp_no": "str", "customer_code": "str", "product_code": "str", "tiers": "str", "total_amount": "num"}, "报价"),
    _ot("SalesOrder", "so_no", {"so_no": "str", "customer_code": "str", "product_code": "str", "contract_amount": "num", "risk_flags": "str"}, "合同"),
    _ot("FollowUp", "follow_up_id", {"follow_up_id": "str", "customer_code": "str", "opp_no": "str", "content": "str", "next_action": "str"}, "跟进记录"),
    _ot("Complaint", "case_id", {"case_id": "str", "customer_code": "str", "product_code": "str", "defect": "str", "severity": "str"}, "争议/纠纷"),
    _ot("Receivable", "receivable_id", {"receivable_id": "str", "customer_code": "str", "so_no": "str", "invoice_no": "str", "days_overdue": "int"}, "回款"),
]
CRM_LINK_TYPES = [
    _lt("contact_to_customer", "Contact", "Customer", "contact_id/customer_code", False, "联系人关联客户"),
    _lt("opp_to_customer", "Opportunity", "Customer", "opp_no/customer_code", False, "询盘关联客户"),
    _lt("quote_to_opp", "Quotation", "Opportunity", "quote_no/opp_no", False, "报价关联询盘"),
    _lt("quote_to_customer", "Quotation", "Customer", "quote_no/customer_code", False, "报价关联客户"),
    _lt("so_to_customer", "SalesOrder", "Customer", "so_no/customer_code", False, "合同关联客户"),
    _lt("followup_to_customer", "FollowUp", "Customer", "follow_up_id/customer_code", False, "跟进关联客户"),
    _lt("followup_to_opp", "FollowUp", "Opportunity", "follow_up_id/opp_no", False, "跟进关联询盘"),
    _lt("complaint_to_customer", "Complaint", "Customer", "case_id/customer_code", False, "争议关联客户"),
    _lt("receivable_to_so", "Receivable", "SalesOrder", "receivable_id/so_no", False, "回款关联合同"),
    _lt("so_to_productioncost", "SalesOrder", "ERP.ProductionCost", "so_no/work_order_no", True, "合同关联 ERP 生产成本 PC-HMA-"),
    _lt("invoice_to_voucher", "Receivable", "ERP.Voucher", "invoice_no/voucher_no", True, "回款发票关联 ERP 凭证 BV-HMA-"),
]
CRM_ACTION_TYPES: list = []


# 跨系统闭环链接（8 条热熔胶跨系统闭环，承载 spec §4）
CROSS_LINK_TYPES = [
    _lt("ingredient_to_material_closure", "FRM.Ingredient", "ERP.Material", "ingredient_code/material_code", True,
        "组分 ING-(FRM)→采购物料 M-(ERP，prefix 转换 ING-RES-→M-RES-)"),
    _lt("formula_to_finishedgoods_closure", "FRM.Formula", "ERP.Material", "formula_no/product_code", True,
        "标准品配方 FORM-STD-(FRM)→成品胶 M-FG-(ERP)"),
    _lt("formula_to_batch_closure", "FRM.Formula", "MES.Batch", "formula_no/formula_no", True,
        "定制配方 FORM-CUS-(FRM)→生产批次 BAT-(MES，按 formula_no)"),
    _lt("equipment_to_line_closure", "PCM.Equipment", "MES.Line", "eq_no/line", True,
        "设备 EQ-(PCM)→产线 LINE-(MES，按 line)"),
    _lt("schedule_to_workorder_closure", "PCM.ScheduleRule", "MES.WorkOrder", "rule_no/work_order_no", True,
        "排产建议 PSCH-(PCM)→工单 WO(MES，按 work_order_no)"),
    _lt("batch_to_quality_closure", "MES.Batch", "QAS.QualityReport", "batch_no/batch_no", True,
        "批次 BAT-(MES)→成品检测 QR-FG-(QAS) / 不良品 NG-(QAS)，按 batch_no"),
    _lt("batch_to_ng_closure", "MES.Batch", "QAS.NgRecord", "batch_no/batch_no", True,
        "批次 BAT-(MES)→不良品 NG-(QAS)，按 batch_no"),
    _lt("complaint_to_customer_closure", "QAS.CustomerComplaint", "CRM.Customer", "cc_no/customer_code", True,
        "售后客诉 CC-(QAS)→客户 CLI-(CRM，按 customer_code)"),
    _lt("invoice_to_voucher_closure", "CRM.Receivable", "ERP.Voucher", "invoice_no/voucher_no", True,
        "回款发票 INV(CRM)→凭证 BV-HMA-(ERP，按 invoice_no，对账闭环)"),
    _lt("contract_to_productioncost_closure", "CRM.SalesOrder", "ERP.ProductionCost", "so_no/work_order_no", True,
        "合同 CT-HMA-(CRM)→生产成本 PC-HMA-(ERP，按 work_order_no)"),
    _lt("batch_to_productioncost_closure", "MES.Batch", "ERP.ProductionCost", "batch_no/heat_no", True,
        "批次 BAT-(MES)→生产成本 PC-HMA-(ERP，按 heat_no，成本归集)"),
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
    lines = [f"# {title}\n", f"> {intro}\n"]
    if convs:
        lines += ["## 标识符约定\n",
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
    meta = {"system": folder.lower(), "source": "mock-starhma"}
    files = [
        (f"{folder}/README.md", render_readme_md(label, folder, ots, lts, ats, summary), {**meta, "kind": "readme"}),
        (f"{folder}/object-types.md", render_object_types_md(f"{label} · 对象类型", f"由 mock {folder} 数据接口支撑。", ots), {**meta, "kind": "object-types"}),
        (f"{folder}/link-types.md", render_link_types_md(f"{label} · 链接类型", f"定义 {label} 内部及跨系统对象间关系。", lts), {**meta, "kind": "link-types"}),
        (f"{folder}/action-types.md", render_action_types_md(f"{label} · 动作类型", f"定义 {label} 上可执行的写操作。", ats), {**meta, "kind": "action-types"}),
    ]
    if convs:
        default_intro = (f"{label} 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——"
                         f"杜绝把组分 ING- 当物料 M- 传 ERP（prefix 转换 ING-RES-→M-RES-）、"
                         f"把标准品配方 FORM-STD- 当成品胶 M-FG- 传 ERP、"
                         f"把定制配方 FORM-CUS- 当批次 BAT- 传 MES、"
                         f"把设备 EQ- 当产线 LINE- 传 MES、"
                         f"把客诉 CC- 当客户 CLI- 传 CRM、"
                         f"把发票 INV 当凭证 BV-HMA- 传 ERP 等 404。")
        files.append((f"{folder}/identifiers.md",
                      render_identifiers_md(f"{label} · 标识符与码空间映射",
                                             identifiers_intro or default_intro,
                                             convs, mappings or []),
                      {**meta, "kind": "identifiers"}))
    return files


# 组织级 7 个本体文件夹（6 域 + Cross）
ORG_SYSTEMS = [
    {"folder": "FRM", "label": "FRM 配方研发本体",
     "summary": "配方(FORM-STD-/FORM-CUS-)/原料组分(ING-)/实验(EXP-RHE-/EXP-TEN-/EXP-ADH-)/样品(SMP-)/测试方案(TS-)/失效记录(FR-)；组分→ERP 物料(prefix 转换)、标准品配方→成品胶、定制配方→MES 批次跨系统关联。",
     "object_types": FRM_OBJECT_TYPES, "link_types": FRM_LINK_TYPES, "action_types": FRM_ACTION_TYPES,
     "conventions": FRM_IDENTIFIER_CONVENTIONS, "code_mappings": FRM_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "FRM 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把组分 ING-RES- 当物料 M-RES- 传 ERP（prefix 转换 ING-RES-→M-RES-）、把标准品配方 FORM-STD- 当成品胶 M-FG- 传 ERP、把定制配方 FORM-CUS- 当批次 BAT- 传 MES 等 404。"},
    {"folder": "PCM", "label": "PCM 工艺与设备本体",
     "summary": "工艺参数(PP-STIR-/PP-REACT-/PP-COOL-)/设备(EQ-RX-/EQ-MTR-/EQ-GRN-)/排产建议(PSCH-)；工艺参数挂配方 FORM-/成品胶 M-FG-，设备挂产线 LINE-，排产落产工单 WO 跨系统关联。",
     "object_types": PCM_OBJECT_TYPES, "link_types": PCM_LINK_TYPES, "action_types": PCM_ACTION_TYPES,
     "conventions": PCM_IDENTIFIER_CONVENTIONS, "code_mappings": PCM_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "PCM 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把工艺参数 PP- 当配方 FORM- 传 FRM、把 PP- 当成品胶 M-FG- 传 ERP、把设备 EQ- 当产线 LINE- 传 MES、把排产 PSCH- 当工单 WO 传 MES 等 404。"},
    {"folder": "QAS", "label": "QAS 质量与技术服务本体",
     "summary": "检测报告(QR-IN-/QR-FG-)/售后客诉(CC-，开胶/拉丝/堵枪/低温失效)/故障案例(FC-)/不良品(NG-)；检测挂批次 BAT-/物料 M-/配方 FORM-，客诉挂客户 CLI-/配方/批次跨系统关联。",
     "object_types": QAS_OBJECT_TYPES, "link_types": QAS_LINK_TYPES, "action_types": QAS_ACTION_TYPES,
     "conventions": QAS_IDENTIFIER_CONVENTIONS, "code_mappings": QAS_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "QAS 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把检测报告 QR- 当批次 BAT- 传 MES、把 QR- 当物料 M- 传 ERP、把客诉 CC- 当客户 CLI- 传 CRM、把 CC- 当配方 FORM- 传 FRM、把不良 NG- 当批次 BAT- 传 MES 等 404。"},
    {"folder": "ERP", "label": "ERP 资源计划本体",
     "summary": "供应商(S-HMA-)/物料(M-RES-/M-TK-/M-WAX-/M-AO-/M-FG-)/仓(WH-HMA-)/采购单(POHMA)/库存/应付(HMAAP)/凭证(BV-HMA-)/成本中心(CC-HMA-)/生产成本(PC-HMA-)；凭证与回款发票 INV 跨系统对账。",
     "object_types": ERP_OBJECT_TYPES, "link_types": ERP_LINK_TYPES, "action_types": ERP_ACTION_TYPES,
     "conventions": ERP_IDENTIFIER_CONVENTIONS, "code_mappings": ERP_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "ERP 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把物料 M-RES- 当组分 ING-RES- 传 FRM（prefix 转换 M-RES-→ING-RES-）、把成品胶 M-FG- 当标准品配方 FORM-STD- 传 FRM、把凭证 BV-HMA- 当发票 INV 传 CRM、把生产成本 PC-HMA- 当合同 CT-HMA- 传 CRM、把 PC-HMA- 当批次 BAT- 传 MES 等 404。"},
    {"folder": "MES", "label": "MES 制造执行本体",
     "summary": "产线(LINE-AUTO-01/02、LINE-03/04)/设备(EQ-，与 PCM 共享)/产品(M-FG-，与 ERP 共享)/工艺路线(ROUTE-)/工单(WO)/批次(BAT-)/报工(WR-)/不良(DF-)；批次→定制配方/成品检测/不良品/生产成本跨系统关联。",
     "object_types": MES_OBJECT_TYPES, "link_types": MES_LINK_TYPES, "action_types": MES_ACTION_TYPES,
     "conventions": MES_IDENTIFIER_CONVENTIONS, "code_mappings": MES_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "MES 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把批次 BAT- 当定制配方 FORM-CUS- 传 FRM、把 BAT- 当成品检测 QR-FG- 或不良 NG- 传 QAS、把 BAT- 当生产成本 PC-HMA- 传 ERP、把产品 M-FG- 误传（与 ERP 共享可直接传）、把设备 EQ- 当 PCM 设备误传（共享可直接传）等 404。"},
    {"folder": "CRM", "label": "CRM 客户管理本体",
     "summary": "客户(CLI-)/联系人(CONT-)/询盘(INQ-)/报价(HMAQT-)/合同(CT-HMA-)/跟进(FU-)/争议(DSP-HMA-)/回款(HMAAR-，发票 INV)；合同→生产成本、发票→凭证跨系统关联。",
     "object_types": CRM_OBJECT_TYPES, "link_types": CRM_LINK_TYPES, "action_types": CRM_ACTION_TYPES,
     "conventions": CRM_IDENTIFIER_CONVENTIONS, "code_mappings": CRM_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "CRM 各实体主键命名约定与跨码空间映射。调 path 参数端点前必读——杜绝把合同 CT-HMA- 当生产成本 PC-HMA- 传 ERP、把回款发票 INV 当凭证 BV-HMA- 传 ERP、把争议 DSP-HMA- 当售后客诉 CC- 传 QAS（不同实体）等 404。"},
    {"folder": "Cross", "label": "跨系统闭环本体",
     "summary": "8 条跨系统闭环：组分→采购物料(prefix 转换)；标准品配方→成品胶；定制配方→批次；设备→产线 + 排产→工单；批次→质检/不良；客诉→客户；发票→凭证(对账)；合同/批次→生产成本(成本归集)。",
     "object_types": [], "link_types": CROSS_LINK_TYPES, "action_types": CROSS_ACTION_TYPES,
     "conventions": CROSS_IDENTIFIER_CONVENTIONS, "code_mappings": CROSS_CODE_SPACE_MAPPINGS,
     "identifiers_intro": "星途热熔胶跨系统闭环标识符总览。8 条闭环承载 spec §4：FRM↔ERP/MES、PCM↔MES、MES↔QAS/ERP、QAS↔CRM、CRM↔ERP。调跨系统端点前必读——按字段（非码本身）跳转，prefix 不同的需转换（ING-RES-→M-RES-），共享码空间可直接传（M-FG-/EQ-）。"},
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
            raise RuntimeError(f"组织 slug='{ORG_SLUG}' 不存在，请先运行 seed_starhma_org.py。")
        logger.info("seed_starhma_ontology_org", slug=org.slug, org_id=str(org.id))

        org_results = await _seed_scope(db, org.id, "organization", None, ORG_SYSTEMS, "organization")
        overall["scopes"].append({"scope": "organization", "systems": org_results})

        await db.commit()
    return overall


def _print_report(result: dict) -> None:
    print("\n" + "=" * 72)
    print("星途热熔胶本体导入完成（覆盖式幂等，可安全重复执行）")
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
    print("位置：管理端「星途热熔胶」组织 → 本体 → FRM/PCM/QAS/ERP/MES/CRM/Cross（组织级）")
    print("6 域 + Cross 各含 identifiers.md（标识符约定 + 跨码空间映射），agent 推理时按用户 scope 注入。")
    print("=" * 72)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
