"""为「星途服装」组织导入服装本体（PLM + SCM + 跨系统闭环链接）。

Palantir Foundry 风格：对象类型 / 链接类型 / 动作类型。覆盖 7 个 demo 场景所需的
服装域实体与跨系统关系：
  - PLM：Style/Fabric/Bom/SamplingOrder/BulkOrder/QcReport/DefectCase/CostLedger/FeasibilityLog
  - SCM：Supplier/Quotation/CapacityCalendar/FabricArrivalPlan/ReplenishmentSuggestion/LeadtimeSnapshot/MaterialValidation
  - 跨系统闭环：BulkOrder→WorkOrder(MES)→QcReport→DefectCase→Style（新品风险回流）
                SamplingOrder→BulkOrder→SalesOrder(CRM)→Receivable
                Style→Fabric→Supplier→Quotation→CostLedger

幂等：upsert 覆盖内容。落位组织级作用域 PLM/、SCM/、Cross/ 三个文件夹。

用法:
    # 容器内（docker cp 后）：
    docker cp demo/starclothing/scripts/seed_starclothing_ontology.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_starclothing_ontology.py
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# 兼容两种位置：容器内 /app/scripts/ → backend=/app；本地 demo/starclothing/scripts/ → backend=repo/llm_router/backend
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

ORG_SLUG = os.getenv("MOCK_SEED_ORG_SLUG", "starclothing")
ORG_NAME_FALLBACK = "星途服装"
SCOPE_TYPE = "organization"
SCOPE_ID = None


# ───────────────────────── PLM 对象类型 ─────────────────────────

PLM_OBJECT_TYPES = [
    {
        "objectType": "Style", "primaryKey": "style_code",
        "title": "{style_code} · {name}（{status}）",
        "description": "款式：服装 SKU，含季节/面料/工艺/成本。",
        "backingInterface": "GET /api/v1/styles, GET /api/v1/styles/{style_code}",
        "properties": {
            "style_code": {"type": "string", "description": "款式编码（主键），形如 `P-FW2026-001`（P- + 季节 FW/SS/AP + 年份 + 序号）；与 MES product_code 对齐"},
            "name": {"type": "string"},
            "category": {"type": "string", "description": "季节分类 FW/SS/AP"},
            "fabric_main": {"type": "string", "description": "主面料**物料码**，`M-` 前缀（如 `M-WOOL-DBL-360`）；与面料主数据 `Fabric.fabric_code`（`F-` 前缀）**不同码空间**——查面料详情须按后缀映射到 F- 码（见 identifiers.md）"},
            "material_composition": {"type": "string"},
            "qty_per_batch": {"type": "number"},
            "unit_cost": {"type": "number"},
            "status": {"type": "string", "description": "开发中/打样中/已量产/已停产"},
            "designer": {"type": "string"},
            "developer": {"type": "string"},
            "sample_due_date": {"type": "string"},
            "bulk_due_date": {"type": "string"},
        },
    },
    {
        "objectType": "Fabric", "primaryKey": "fabric_code",
        "title": "{fabric_code} · {name}",
        "description": "数字面料库：含克重/幅宽/成分/供应商/产能/交期/起订量。",
        "backingInterface": "GET /api/v1/fabrics, GET /api/v1/fabrics/{fabric_code}",
        "properties": {
            "fabric_code": {"type": "string", "description": "面料主数据编码（主键），`F-` 前缀，形如 `F-WOOL-DBL-360`、`F-SHELL-3L-150`（注意：BOM 物料码用 `M-` 前缀，如 `M-WOOL-DBL-360`，按后缀映射到本码）"},
            "name": {"type": "string"},
            "composition": {"type": "string", "description": "成分，如 30%羊绒 70%羊毛"},
            "weight_gsm": {"type": "number", "description": "克重 g/㎡"},
            "width_mm": {"type": "number", "description": "门幅 mm"},
            "category": {"type": "string"},
            "supplier_code": {"type": "string", "description": "关联 SCM.Supplier"},
            "moq": {"type": "number", "description": "最小起订量"},
            "leadtime_days": {"type": "number"},
            "capacity_per_day": {"type": "number"},
            "unit_cost": {"type": "number"},
            "loss_rate": {"type": "number", "description": "损耗率 %"},
            "available_stock": {"type": "number"},
        },
    },
    {
        "objectType": "Bom", "primaryKey": "style_code#material_code",
        "title": "{style_code} · {material_code}（用量 {qty}）",
        "description": "款式 BOM：每款的物料清单与用量/损耗。",
        "backingInterface": "GET /api/v1/boms?style_code=",
        "properties": {
            "style_code": {"type": "string", "description": "关联 Style，形如 `P-FW2026-001`"},
            "material_code": {"type": "string", "description": "物料编码，`M-` 前缀（如 `M-WOOL-DBL-360`、`M-BTN-RESIN`、`M-PKG-CTN`）；面料物料对应 `Fabric.fabric_code`（`F-` 前缀，按后缀映射，见 identifiers.md）"},
            "qty": {"type": "number", "description": "单件用量"},
            "uom": {"type": "string"},
            "loss_rate": {"type": "number", "description": "损耗 %"},
        },
    },
    {
        "objectType": "SamplingOrder", "primaryKey": "sampling_no",
        "title": "{sampling_no} · {style_code}（{stage}/{status}）",
        "description": "打样单：初样/二样/确认样进度与超期标记。",
        "backingInterface": "GET /api/v1/sampling-orders, GET /api/v1/sampling-orders/{sampling_no}",
        "properties": {
            "sampling_no": {"type": "string", "description": "打样单号，形如 `SMP20260009`"},
            "style_code": {"type": "string", "description": "关联 Style，形如 `P-FW2026-001`"},
            "factory": {"type": "string"},
            "stage": {"type": "string", "description": "初样/二样/确认样"},
            "status": {"type": "string", "description": "待排/打样中/已确认/已退回"},
            "plan_date": {"type": "string"},
            "actual_date": {"type": "string"},
            "days_late": {"type": "number"},
        },
    },
    {
        "objectType": "BulkOrder", "primaryKey": "bulk_no",
        "title": "{bulk_no} · {style_code}（{status}）",
        "description": "大货单：量产订单，含产能/交期/质检状态/超期。",
        "backingInterface": "GET /api/v1/bulk-orders, GET /api/v1/bulk-orders/{bulk_no}",
        "properties": {
            "bulk_no": {"type": "string", "description": "大货单号，形如 `BLK20260007`"},
            "style_code": {"type": "string", "description": "关联 Style，形如 `P-FW2026-001`"},
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
        "objectType": "QcReport", "primaryKey": "qc_no",
        "title": "{qc_no} · {bulk_no}（pass={pass}）",
        "description": "质检报告：AQL 抽样/不良数/通过结论。",
        "backingInterface": "GET /api/v1/qc-reports",
        "properties": {
            "qc_no": {"type": "string", "description": "质检报告号，形如 `QC20260001`"},
            "bulk_no": {"type": "string", "description": "关联 BulkOrder，形如 `BLK20260007`"},
            "style_code": {"type": "string", "description": "关联 Style，形如 `P-FW2026-001`"},
            "inspector": {"type": "string"},
            "check_date": {"type": "string"},
            "aql_level": {"type": "string"},
            "sample_size": {"type": "number"},
            "defect_count": {"type": "number"},
            "pass": {"type": "boolean"},
            "defect_summary": {"type": "string"},
        },
    },
    {
        "objectType": "DefectCase", "primaryKey": "case_id",
        "title": "{case_id} · {style_code}（{defect_type}）",
        "description": "缺陷历史：款类/缺陷类型/根因/纠正/规避要点。新品开发时按 style_code 检索历史缺陷做风险规避，新款无历史时按 category 查同类案例 fallback。",
        "backingInterface": "GET /api/v1/defect-history",
        "properties": {
            "case_id": {"type": "string", "description": "缺陷案例号，形如 `DF20260009`"},
            "style_code": {"type": "string", "description": "关联 Style，形如 `P-FW2026-001`；新款可能无历史 case"},
            "category": {"type": "string", "description": "款类，如 压胶冲锋衣/双面呢大衣；新款无 style_code 历史时按 category fallback 查同类缺陷"},
            "defect_type": {"type": "string", "description": "漏水/压胶脱落/起球/掉色/尺寸偏差…"},
            "severity": {"type": "string"},
            "root_cause": {"type": "string"},
            "corrective_action": {"type": "string"},
            "avoidance_hint": {"type": "string", "description": "规避要点，新品开发时注入"},
            "date_reported": {"type": "string"},
            "work_order_no": {"type": "string", "description": "工单号，`XWO` 前缀（如 `XWO20260788`），关联 MES.WorkOrder"},
        },
    },
    {
        "objectType": "CostLedger", "primaryKey": "ledger_no",
        "title": "{ledger_no} · {style_code}（{period}）",
        "description": "成本台账：按款/面料/期间归集料工费，比价/核算后更新。",
        "backingInterface": "GET /api/v1/cost-ledger",
        "properties": {
            "ledger_no": {"type": "string", "description": "台账号，形如 `XCL20260001`"},
            "style_code": {"type": "string", "description": "关联 Style，形如 `P-FW2026-001`"},
            "material_code": {"type": "string", "description": "物料码，`M-` 前缀"},
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
        "title": "{log_no} · {fabric_code} → {supplier_code}",
        "description": "面料可行性测算留痕：决策时成本/交期/产能快照，供回溯复核。注意只覆盖成本/交期/产能三维度，不含缺陷预防措施留痕。",
        "backingInterface": "GET /api/v1/feasibility-logs",
        "properties": {
            "log_no": {"type": "string", "description": "留痕号，形如 `FL20260001`"},
            "style_code": {"type": "string", "description": "关联 Style，形如 `P-FW2026-001`"},
            "fabric_code": {"type": "string", "description": "面料主数据码，`F-` 前缀，如 `F-WOOL-DBL-360`"},
            "supplier_code": {"type": "string", "description": "供应商码，`XS-FAB-` 前缀，如 `XS-FAB-003`"},
            "qty_requested": {"type": "number"},
            "cost_estimated": {"type": "number"},
            "leadtime_estimated": {"type": "number"},
            "capacity_available": {"type": "number"},
            "snapshot_at": {"type": "string"},
            "decision": {"type": "string"},
        },
    },
]

PLM_LINK_TYPES = [
    {"linkType": "StyleToFabric", "parent": "Style", "child": "Fabric",
     "cardinality": "MANY_ONE", "joinField": "fabric_main / fabric_code",
     "description": "款式使用主面料。**`Style.fabric_main` 是 `M-` 前缀物料码，`Fabric.fabric_code` 是 `F-` 前缀主数据码，不同码空间——须按后缀（如 `WOOL-DBL-360`）映射：`M-WOOL-DBL-360` → `F-WOOL-DBL-360`。查面料详情用 `getFabric(fabric_code='F-WOOL-DBL-360')`，不可直接传 `M-` 码（会 404）。详见 identifiers.md。**"},
    {"linkType": "StyleToBom", "parent": "Style", "child": "Bom",
     "cardinality": "ONE_MANY", "joinField": "style_code",
     "description": "款式含多行 BOM（面料/辅料/包装）。"},
    {"linkType": "StyleToSampling", "parent": "Style", "child": "SamplingOrder",
     "cardinality": "ONE_MANY", "joinField": "style_code",
     "description": "款式的打样流程（初样→二样→确认样）。"},
    {"linkType": "StyleToBulk", "parent": "Style", "child": "BulkOrder",
     "cardinality": "ONE_MANY", "joinField": "style_code",
     "description": "款式的大货订单。"},
    {"linkType": "SamplingToBulk", "parent": "SamplingOrder", "child": "BulkOrder",
     "cardinality": "ONE_ONE", "joinField": "style_code（同款）",
     "description": "打样确认后转入大货（同款）。"},
    {"linkType": "BulkToQc", "parent": "BulkOrder", "child": "QcReport",
     "cardinality": "ONE_MANY", "joinField": "bulk_no",
     "description": "大货单的质检报告。"},
    {"linkType": "QcToDefect", "parent": "QcReport", "child": "DefectCase",
     "cardinality": "ONE_MANY", "joinField": "bulk_no / style_code",
     "description": "质检发现的不良回流为缺陷案例。"},
    {"linkType": "StyleToDefect", "parent": "Style", "child": "DefectCase",
     "cardinality": "ONE_MANY", "joinField": "style_code",
     "description": "款式历史缺陷（新品开发时检索规避）。"},
    {"linkType": "StyleToCostLedger", "parent": "Style", "child": "CostLedger",
     "cardinality": "ONE_MANY", "joinField": "style_code",
     "description": "款式成本台账。"},
    {"linkType": "StyleToFeasibility", "parent": "Style", "child": "FeasibilityLog",
     "cardinality": "ONE_MANY", "joinField": "style_code",
     "description": "款式面料可行性测算留痕。"},
]

PLM_ACTION_TYPES = [
    {"actionType": "addDefectRecord", "operation": "CREATE", "target": "DefectCase",
     "description": "大货后缺陷回流：写入缺陷历史，供下次新品检索。",
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
     "effects": {"status": "已回流，等待下次新品检索"}},
    {"actionType": "postVoucher", "operation": "CREATE", "target": "Voucher",
     "description": "新建财务凭证（写入演示）。",
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


# ───────────────────────── PLM 标识符约定与码空间映射 ─────────────────────────
# 防猜码 404 的「no guessing」骨架：把每个实体的主键前缀 + 示例值写死，并把
# BOM 物料码(M-) 与面料主数据码(F-)、款号与工单号(XWO) 等「不同码空间」的映射
# 规则显式列出。agent 调 path 参数端点前读此表，杜绝把 M- 当 F-、把 WO 当 XWO。

PLM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Style",         "field": "style_code",    "prefix": "P-",   "example": "P-FW2026-001",   "note": "P- + 季节(FW/SS/AP) + 年份 + 序号"},
    {"entity": "Fabric",        "field": "fabric_code",   "prefix": "F-",   "example": "F-WOOL-DBL-360", "note": "面料主数据码；与 BOM 物料码 M- 不同码空间"},
    {"entity": "Bom",           "field": "material_code", "prefix": "M-",   "example": "M-WOOL-DBL-360", "note": "BOM 物料码（面料/辅料/包装）；面料物料按后缀映射到 F- 码"},
    {"entity": "SamplingOrder", "field": "sampling_no",   "prefix": "SMP",  "example": "SMP20260009",   "note": "SMP + 年月 + 序号"},
    {"entity": "BulkOrder",     "field": "bulk_no",       "prefix": "BLK",  "example": "BLK20260007",   "note": "BLK + 年月 + 序号"},
    {"entity": "QcReport",      "field": "qc_no",         "prefix": "QC",   "example": "QC20260001",    "note": "QC + 年月 + 序号"},
    {"entity": "DefectCase",    "field": "case_id",       "prefix": "DF",   "example": "DF20260009",    "note": "DF + 年月 + 序号；可按 style_code 或 category 查"},
    {"entity": "CostLedger",    "field": "ledger_no",    "prefix": "XCL",  "example": "XCL20260001",   "note": "XCL + 年月 + 序号"},
    {"entity": "FeasibilityLog","field": "log_no",        "prefix": "FL",   "example": "FL20260001",    "note": "FL + 年月 + 序号；含成本/交期/产能快照，不含缺陷预防留痕"},
]

PLM_CODE_SPACE_MAPPINGS = [
    {
        "from_field": "Style.fabric_main / Bom.material_code", "from_prefix": "M-",
        "to_field": "Fabric.fabric_code", "to_prefix": "F-",
        "rule": "按后缀（品类缩写+规格，如 WOOL-DBL-360）等价映射，M- 码不可直接当 F- 码用",
        "example": "Style(P-FW2026-001).fabric_main='M-WOOL-DBL-360' → 查面料详情用 getFabric(fabric_code='F-WOOL-DBL-360')",
        "why": "BOM 物料码与面料主数据码是不同码空间，直接传 M- 码命中 404（fabric M-WOOL-DBL-360 not found）",
    },
    {
        "from_field": "Style.style_code", "from_prefix": "P-",
        "to_field": "MES.WorkOrder.won", "to_prefix": "XWO",
        "rule": "款号不等于工单号；按 listWorkOrders(style_code=...) 取该款全部工单号，再 getWorkOrder(won=...)",
        "example": "Style(P-FW2026-001) → listWorkOrders(style_code='P-FW2026-001') → won='XWO20260788' → getWorkOrder(won='XWO20260788')",
        "why": "工单号 XWO 前缀，不可用 WO2026xxxx 猜测（work order WO20260607 not found）",
    },
    {
        "from_field": "DefectCase.style_code", "from_prefix": "P-",
        "to_field": "DefectCase（按 category fallback）", "to_prefix": "—",
        "rule": "新款无 style_code 历史缺陷时，按 category（压胶冲锋衣/双面呢大衣…）查同类历史缺陷",
        "example": "P-FW2026-002 无历史 case → listDefectHistory(category='压胶冲锋衣') → DF20260012 漏水 / DF20260018 压胶脱落",
        "why": "新款缺陷检索需按品类 fallback，否则漏掉同类历史案例根因/纠正/规避要点",
    },
    {
        "from_field": "BulkOrder.bulk_no / SamplingOrder.sampling_no", "from_prefix": "BLK / SMP",
        "to_field": "同实体详情端点 path 参数", "to_prefix": "—",
        "rule": "详情端点用 path 参数：getBulkOrder(bulk_no=...) / getSamplingProgress(sampling_no=...)；列表端点用 query 参数",
        "example": "getBulkOrder(bulk_no='BLK20260007') / getSamplingProgress(sampling_no='SMP20260009')",
        "why": "path 端点占位符已由 executor 替换，传真实编码即命中真实数据（v7 修复后）",
    },
]


# ───────────────────────── SCM 对象类型 ─────────────────────────

SCM_OBJECT_TYPES = [
    {
        "objectType": "Supplier", "primaryKey": "code",
        "title": "{code} · {name}（{category}）",
        "description": "供应商：含产能/起订量/账期/评级。",
        "backingInterface": "GET /api/v1/suppliers, GET /api/v1/suppliers/{code}",
        "properties": {
            "code": {"type": "string"},
            "name": {"type": "string"},
            "category": {"type": "string", "description": "面料/辅料/外协加工/辅料包装"},
            "contact": {"type": "string"},
            "payment_terms_days": {"type": "number"},
            "rating": {"type": "string"},
            "capacity_per_day": {"type": "number"},
            "moq": {"type": "number"},
            "specialty": {"type": "string"},
        },
    },
    {
        "objectType": "Quotation", "primaryKey": "quotation_no",
        "title": "{quotation_no} · {supplier_name} → {material_name}",
        "description": "报价单：单价/起订/交期/账期/有效期，多家对比同规格。",
        "backingInterface": "GET /api/v1/quotations, GET /api/v1/quotations/{quotation_no}, GET /api/v1/quotations/compare",
        "properties": {
            "quotation_no": {"type": "string"},
            "supplier_code": {"type": "string", "description": "关联 Supplier"},
            "supplier_name": {"type": "string"},
            "material_code": {"type": "string", "description": "关联 ERP.Material / PLM.Fabric"},
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
        "description": "面料在途到货计划：含延误天数。",
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
        "description": "补单节奏建议：按交期反推+产能占用给首单/补1/补2 节点。",
        "backingInterface": "GET /api/v1/replenishment-suggestions, GET /api/v1/suggest-replenishment",
        "properties": {
            "suggestion_id": {"type": "string"},
            "style_code": {"type": "string"},
            "bulk_no": {"type": "string"},
            "total_qty": {"type": "number"},
            "first_batch_qty": {"type": "number"}, "first_batch_date": {"type": "string"},
            "replenish_1_qty": {"type": "number"}, "replenish_1_date": {"type": "string"},
            "replenish_2_qty": {"type": "number"}, "replenish_2_date": {"type": "string"},
            "fabric_arrival_date": {"type": "string"},
            "risks": {"type": "array", "description": "风险列表"},
        },
    },
    {
        "objectType": "LeadtimeSnapshot", "primaryKey": "snapshot_id",
        "title": "{snapshot_id} · {material_code} → {supplier_code}",
        "description": "交期快照：用于实时交期异动检测（同供应商同面料不同快照对比 Δ）。",
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
        "description": "物料校验记录：双向（工厂端/我方端发起），含应投/实投/差异。",
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
     "description": "供应商的多份报价（不同面料/规格）。"},
    {"linkType": "SupplierToCapacity", "parent": "Supplier", "child": "CapacityCalendar",
     "cardinality": "ONE_MANY", "joinField": "supplier_code",
     "description": "供应商未来 N 天产能占用。"},
    {"linkType": "SupplierToArrival", "parent": "Supplier", "child": "FabricArrivalPlan",
     "cardinality": "ONE_MANY", "joinField": "supplier_code",
     "description": "供应商的面料在途到货。"},
    {"linkType": "SupplierToLeadtimeSnapshot", "parent": "Supplier", "child": "LeadtimeSnapshot",
     "cardinality": "ONE_MANY", "joinField": "supplier_code",
     "description": "供应商交期快照序列（异动检测）。"},
    {"linkType": "QuotationToMaterial", "parent": "Quotation", "child": "ERP.Material",
     "cardinality": "MANY_ONE", "joinField": "material_code", "crossSystem": True,
     "description": "【跨系统】报价对应 ERP 物料（面料/辅料）。"},
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


# ───────────────────────── SCM 标识符约定与码空间映射 ─────────────────────────
# 防猜码 404 的「no guessing」骨架（SCM 域）。关键跨系统坑：SCM.MaterialValidation
# 的 work_order_no 存的是 WO 前缀，而 MES.WorkOrder.won 是 XWO 前缀——两者不直接匹配，
# 不可把 SCM 的 WO 码直接传给 MES getWorkOrder，须经 listWorkOrders 查真实 XWO won。

SCM_IDENTIFIER_CONVENTIONS = [
    {"entity": "Supplier",            "field": "code",            "prefix": "XS-",   "example": "XS-FAB-001",   "note": "XS- + 品类(FAB 面料/ACC 辅料/PKG 包装/PRT 印花外协) + 序号；getSupplier(code) 直传"},
    {"entity": "Quotation",           "field": "quotation_no",   "prefix": "Q",     "example": "Q202607001",   "note": "Q + 年月 + 序号；compareQuotations 用 material_code 入参"},
    {"entity": "CapacityCalendar",    "field": "entry_id",       "prefix": "CC",    "example": "CC001",        "note": "CC + 序号；listCapacityCalendar 按 supplier_code 查"},
    {"entity": "FabricArrivalPlan",   "field": "plan_id",        "prefix": "FAP-",  "example": "FAP-001",      "note": "FAP- + 序号；listFabricArrivalPlans 按 material_code 查"},
    {"entity": "ReplenishmentSuggestion","field":"suggestion_id","prefix": "SUG-",  "example": "SUG-001",      "note": "SUG- + 序号；listReplenishmentSuggestions 按 style_code 查"},
    {"entity": "LeadtimeSnapshot",    "field": "snapshot_id",    "prefix": "LS-",   "example": "LS-001",       "note": "LS- + 序号；getLeadtimeDiff(since) 按 material_code+supplier_code 查异动"},
    {"entity": "MaterialValidation",  "field": "validation_id",  "prefix": "MV-",   "example": "MV-001",      "note": "MV- + 序号；listMaterialValidations 拿待校验物料"},
]

SCM_CODE_SPACE_MAPPINGS = [
    {
        "from_field": "MaterialValidation.work_order_no / 各实体 work_order_no", "from_prefix": "WO",
        "to_field": "MES.WorkOrder.won", "to_prefix": "XWO",
        "rule": "SCM 里存的工单号是 WO 前缀（如 WO20260607），MES 工单号是 XWO 前缀（如 XWO20260607），不直接匹配。不可把 SCM 的 WO 码直接传给 MES getWorkOrder",
        "example": "SCM listMaterialValidations 返回 work_order_no='WO20260607' → MES getWorkOrder(won='WO20260607') 会 404；正确做法：listWorkOrders(style_code=...) 或 listWorkOrders(work_order_no='WO20260607') 拿 MES 真实 won（XWO 前缀）",
        "why": "SCM 与 MES 工单号前缀不一致（数据现状），直传 WO 码命中 404（work order WO20260607 not found）",
    },
    {
        "from_field": "Quotation.material_code / 各实体 material_code", "from_prefix": "M-",
        "to_field": "PLM.Fabric.fabric_code", "to_prefix": "F-",
        "rule": "SCM 物料码与 PLM BOM 物料码同空间（M- 前缀），与 PLM 面料主数据码 F- 不同码空间——查面料主数据按后缀映射",
        "example": "compareQuotations(material_code='M-WOOL-DBL-360')；若需面料详情用 PLM getFabric(fabric_code='F-WOOL-DBL-360')，不可直传 M- 码",
        "why": "M- 物料码与 F- 面料主数据码不同码空间，直传 M- 码命中 404（详见 PLM/identifiers.md）",
    },
    {
        "from_field": "Supplier.code", "from_prefix": "XS-",
        "to_field": "getSupplier(code) / listCapacityCalendar(supplier_code)", "to_prefix": "XS-",
        "rule": "供应商码直传：getSupplier(code='XS-FAB-001') / listCapacityCalendar(supplier_code='XS-FAB-001')，SCM 内部自洽",
        "example": "getSupplier(code='XS-FAB-001') → 0 失败；listCapacityCalendar(supplier_code='XS-FAB-001')",
        "why": "SCM 供应商码无跨系统映射坑，直接用",
    },
]


# ───────────────────────── 跨系统闭环链接 ─────────────────────────

CROSS_LINK_TYPES = [
    {"linkType": "StyleToMesProduct", "parent": "PLM.Style", "child": "MES.Product",
     "cardinality": "ONE_ONE", "joinField": "style_code / product_code", "crossSystem": True,
     "description": "【跨系统】款式与 MES 工艺路线产品对齐（同码 P-FW2026-xxx）。"},
    {"linkType": "BulkToMesWorkOrder", "parent": "PLM.BulkOrder", "child": "MES.WorkOrder",
     "cardinality": "ONE_MANY", "joinField": "bulk_no / order_no", "crossSystem": True,
     "description": "【跨系统】大货单下挂 MES 工单（按产线分单）。"},
    {"linkType": "BulkToCrmSalesOrder", "parent": "PLM.BulkOrder", "child": "CRM.SalesOrder",
     "cardinality": "MANY_ONE", "joinField": "customer_code / so_no", "crossSystem": True,
     "description": "【跨系统】大货单关联 CRM 销售订单（按客户/款）。"},
    {"linkType": "DefectToMesWorkOrder", "parent": "PLM.DefectCase", "child": "MES.WorkOrder",
     "cardinality": "MANY_ONE", "joinField": "work_order_no", "crossSystem": True,
     "description": "【跨系统】缺陷案例关联 MES 工单（定位发生工序）。"},
    {"linkType": "DefectToStyleClosedLoop", "parent": "PLM.DefectCase", "child": "PLM.Style",
     "cardinality": "MANY_ONE", "joinField": "style_code / category",
     "description": "【闭环】大货缺陷 → RAG 检索 → 新品开发预警（生命周期数据闭环）。"},
    {"linkType": "ComplaintToDefect", "parent": "CRM.Complaint", "child": "PLM.DefectCase",
     "cardinality": "ONE_MANY", "joinField": "work_order_no / style_code", "crossSystem": True,
     "description": "【跨系统】CRM 客诉 8D 关联 PLM 缺陷案例（同工单/款）。"},
    {"linkType": "BulkToErpProductionCost", "parent": "PLM.BulkOrder", "child": "ERP.ProductionCost",
     "cardinality": "ONE_MANY", "joinField": "work_order_no", "crossSystem": True,
     "description": "【跨系统】大货单按工单归集 ERP 生产成本。"},
    {"linkType": "BulkToErpPayable", "parent": "PLM.BulkOrder", "child": "ERP.Payable",
     "cardinality": "ONE_MANY", "joinField": "supplier_code / invoice_no", "crossSystem": True,
     "description": "【跨系统】大货单的面料采购应付（ERP 侧）。"},
    {"linkType": "BulkToCrmReceivable", "parent": "PLM.BulkOrder", "child": "CRM.Receivable",
     "cardinality": "ONE_MANY", "joinField": "customer_code / so_no", "crossSystem": True,
     "description": "【跨系统】大货单的成衣销售应收（CRM 侧）。"},
    {"linkType": "StyleToErpMaterial", "parent": "PLM.Bom", "child": "ERP.Material",
     "cardinality": "MANY_ONE", "joinField": "material_code", "crossSystem": True,
     "description": "【跨系统】BOM 行引用 ERP 物料（面料/辅料/包装）。"},
    {"linkType": "ArrivalToErpPurchaseOrder", "parent": "SCM.FabricArrivalPlan", "child": "ERP.PurchaseOrder",
     "cardinality": "MANY_ONE", "joinField": "po_ref / po_no", "crossSystem": True,
     "description": "【跨系统】面料到货计划关联 ERP 采购单。"},
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
        f"**动作类型 {len(ats)}**：" + "、".join(a["actionType"] for a in ats), "",
        "> Palantir Foundry Ontology 规范；agent 运行时按任务配置注入对应文件 content。",
    ])


def _files_for(folder: str, label: str, ots: list, lts: list, ats: list, summary: str,
                convs: list | None = None, mappings: list | None = None):
    meta = {"system": folder.lower(), "source": "mock-starclothing"}
    files = [
        (f"{folder}/README.md", render_readme_md(label, folder, ots, lts, ats, summary), {**meta, "kind": "readme"}),
        (f"{folder}/object-types.md", render_object_types_md(f"{label} · 对象类型", f"由 mock {folder} 数据接口（连接器 `starclothing-{folder.lower()}`）支撑。", ots), {**meta, "kind": "object-types"}),
        (f"{folder}/link-types.md", render_link_types_md(f"{label} · 链接类型", f"定义 {label} 内部及跨系统对象间的关系。", lts), {**meta, "kind": "link-types"}),
        (f"{folder}/action-types.md", render_action_types_md(f"{label} · 动作类型", f"定义 {label} 上可执行的写操作。", ats), {**meta, "kind": "action-types"}),
    ]
    if convs:
        files.append((f"{folder}/identifiers.md",
                      render_identifiers_md(f"{label} · 标识符与码空间映射",
                                            f"{label} 各实体主键的命名约定与跨码空间映射规则。调用 path 参数端点前必读——杜绝把物料码当面料主数据码、把 WO 当 XWO 等 404。",
                                            convs, mappings or []),
                      {**meta, "kind": "identifiers"}))
    return files


SYSTEMS = [
    {
        "folder": "PLM", "label": "PLM 服装产品生命周期本体",
        "summary": "产品侧本体：款式/面料/BOM/打样/大货/质检/缺陷历史/成本台账/可行性留痕；缺陷→款式构成新品风险闭环。",
        "object_types": PLM_OBJECT_TYPES, "link_types": PLM_LINK_TYPES, "action_types": PLM_ACTION_TYPES,
        "conventions": PLM_IDENTIFIER_CONVENTIONS, "code_mappings": PLM_CODE_SPACE_MAPPINGS,
    },
    {
        "folder": "SCM", "label": "SCM 服装供应链协同本体",
        "summary": "供应链侧本体：供应商/报价/产能日历/面料到货/补单建议/交期快照/物料校验；跨系统关联 ERP 物料、MES 工单、PLM 成本台账。",
        "object_types": SCM_OBJECT_TYPES, "link_types": SCM_LINK_TYPES, "action_types": SCM_ACTION_TYPES,
        "conventions": SCM_IDENTIFIER_CONVENTIONS, "code_mappings": SCM_CODE_SPACE_MAPPINGS,
    },
    {
        "folder": "Cross", "label": "跨系统闭环本体",
        "summary": "跨系统链接：款式↔MES产品、大货→工单→质检→缺陷→款式（闭环）、大货↔销售订单↔应收↔应付、报价→成本台账、面料到货↔采购单。",
        "object_types": [], "link_types": CROSS_LINK_TYPES, "action_types": [],
        "conventions": None, "code_mappings": None,
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


async def seed() -> dict:
    overall = {"systems": []}
    async with async_session_factory() as db:
        org = await _get_org(db, ORG_SLUG)
        if org is None:
            raise RuntimeError(
                f"组织 slug='{ORG_SLUG}'（或名称='{ORG_NAME_FALLBACK}'）不存在，"
                "请先运行 python scripts/seed_starclothing_apparel.py。"
            )
        logger.info("seed_starclothing_ontology_org", slug=org.slug, org_id=str(org.id))

        for s in SYSTEMS:
            await create_folder(db, org.id, SCOPE_TYPE, SCOPE_ID, s["folder"])
            files = _files_for(s["folder"], s["label"], s["object_types"], s["link_types"], s["action_types"], s["summary"],
                               s.get("conventions"), s.get("code_mappings"))
            for path, content, meta in files:
                await upsert_file(db, org.id, SCOPE_TYPE, SCOPE_ID,
                                  OntologyFileCreate(path=path, content=content, metadata=meta,
                                                     scope_type=SCOPE_TYPE, scope_id=SCOPE_ID))
                logger.info("ontology_file_upserted", path=path)
            overall["systems"].append({
                "folder": s["folder"], "label": s["label"],
                "object_types": len(s["object_types"]),
                "link_types": len(s["link_types"]),
                "action_types": len(s["action_types"]),
                "cross_system_links": sum(1 for lt in s["link_types"] if lt.get("crossSystem")),
            })

        await db.commit()
    return overall


def _print_report(result: dict) -> None:
    print("\n" + "=" * 64)
    print("星途服装本体导入完成（覆盖式幂等，可安全重复执行）")
    print("-" * 64)
    print(f"{'文件夹':<10}{'对象类型':>10}{'链接类型':>10}{'跨系统':>8}{'动作类型':>10}")
    for s in result["systems"]:
        print(f"{s['folder']:<10}{s['object_types']:>10}{s['link_types']:>10}"
              f"{s['cross_system_links']:>8}{s['action_types']:>10}")
    print("-" * 64)
    print("位置：管理端「星途服装」组织 → 本体（Ontology）→ PLM/、SCM/、Cross/ 文件夹。")
    print("终端任务勾选对应本体文件后，agent 推理时注入其 Markdown。")
    print("=" * 64)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
