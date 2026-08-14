"""依据 mock MES / CRM 数据接口，生成 Palantir Foundry 风格本体并导入「敏睿制造」组织。

本体遵循 Palantir Ontology 基本规范：
  - 对象类型（Object Type）：主键 + 标题 + 属性集 + 绑定数据接口（backing interface）；
  - 链接类型（Link Type）：父/子对象类型 + 基数 + join 字段；
  - 动作类型（Action Type）：CREATE/MODIFY/DELETE/EXECUTE + 目标对象 + 入参。
属性与 mock 接口字段一一对应；CRM 客诉 work_order_no 与 product_code 形成**跨系统**链接到 MES。

落位：组织级作用域下 ``MES/``、``CRM/`` 文件夹，各含 README + object-types / link-types / action-types
三个 Markdown 文件（文件内含 ```ontology JSON 块供机器读取 + 摘要表供人阅读）。
agent 运行时按任务配置的 ``ontology_ids`` 注入对应 OntologyFile.content。

幂等：``upsert_file`` 覆盖内容、``create_folder`` 已存在则原样返回，可安全重复执行。

用法:
    cd llm_router/backend
    python scripts/seed_mock_ontology.py
"""

# ruff: noqa: E501  -- 本体数据表行偏长（中文描述 + 接口路径），属数据性质
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.schemas.ontology import OntologyFileCreate  # noqa: E402
from app.services.ontology_store_service import create_folder, upsert_file  # noqa: E402

logger = structlog.get_logger()

ORG_SLUG = os.getenv("MOCK_SEED_ORG_SLUG", "minrui")
ORG_NAME_FALLBACK = "敏睿制造"

SCOPE_TYPE = "organization"
SCOPE_ID = None

# ───────────────────────── 本体定义 ─────────────────────────
# 属性 type 用 Palantir/JSON Schema 通用类型：string / number / integer / boolean / array / object。

MES_OBJECT_TYPES = [
    {
        "objectType": "ProductionOrder", "primaryKey": "order_no",
        "title": "{order_no} · {product_name}（{status}）", "description": "生产订单：下达给车间的批量生产任务。",
        "backingInterface": "GET /api/v1/production-orders, GET /api/v1/production-orders/{order_no}",
        "properties": {
            "order_no": {"type": "string", "description": "订单号（主键）"},
            "product_code": {"type": "string", "description": "产品编码，关联 Product"},
            "product_name": {"type": "string", "description": "产品名称"},
            "plan_qty": {"type": "number", "description": "计划数量"},
            "done_qty": {"type": "number", "description": "完工数量"},
            "uom": {"type": "string", "description": "计量单位"},
            "status": {"type": "string", "description": "已下达/在制/完工/关闭"},
            "line": {"type": "string", "description": "产线代号，关联 ProductionLine"},
            "planned_start": {"type": "string", "description": "计划开始日期"},
            "due_date": {"type": "string", "description": "交付日期"},
        },
    },
    {
        "objectType": "WorkOrder", "primaryKey": "work_order_no",
        "title": "{work_order_no} · {product_name}（{status}）", "description": "工单：车间按工序执行的生产单。",
        "backingInterface": "GET /api/v1/work-orders, GET /api/v1/work-orders/{won}",
        "properties": {
            "work_order_no": {"type": "string", "description": "工单号（主键）"},
            "order_no": {"type": "string", "description": "所属生产订单号，关联 ProductionOrder"},
            "product_code": {"type": "string", "description": "产品编码，关联 Product"},
            "product_name": {"type": "string", "description": "产品名称"},
            "line": {"type": "string", "description": "产线代号，关联 ProductionLine"},
            "plan_qty": {"type": "number", "description": "计划数量"},
            "done_qty": {"type": "number", "description": "已报工数量"},
            "defect_qty": {"type": "number", "description": "不良数量"},
            "uom": {"type": "string", "description": "计量单位"},
            "status": {"type": "string", "description": "待开工/在制/暂停/完工"},
            "shift": {"type": "string", "description": "早班/中班/晚班"},
            "planned_start": {"type": "string", "description": "计划开始时间"},
            "operator": {"type": "string", "description": "作业员编号"},
        },
    },
    {
        "objectType": "Operation", "primaryKey": "work_order_no#seq",
        "title": "{work_order_no} · 工序{seq} {name}", "description": "工序：工单内的工艺步骤及其报工进度。",
        "backingInterface": "GET /api/v1/work-orders/{won}（嵌套 operations）",
        "properties": {
            "work_order_no": {"type": "string", "description": "所属工单号，关联 WorkOrder"},
            "seq": {"type": "integer", "description": "工序序号"},
            "name": {"type": "string", "description": "工序名称"},
            "line": {"type": "string", "description": "执行产线"},
            "std_minutes": {"type": "number", "description": "标准工时（分钟）"},
            "reported_qty": {"type": "number", "description": "已报工数量"},
            "status": {"type": "string", "description": "工序状态"},
        },
    },
    {
        "objectType": "Equipment", "primaryKey": "code",
        "title": "{code} · {name}（{status}）", "description": "设备：产线上的加工/装配单元及实时参数。",
        "backingInterface": "GET /api/v1/equipment/status, GET /api/v1/equipment/{code}",
        "properties": {
            "code": {"type": "string", "description": "设备编号（主键）"},
            "name": {"type": "string", "description": "设备名称"},
            "line": {"type": "string", "description": "所属产线，关联 ProductionLine"},
            "type": {"type": "string", "description": "设备类型"},
            "status": {"type": "string", "description": "running/idle/fault/maintenance"},
            "temperature_c": {"type": "number", "description": "温度（℃）"},
            "vibration_mm_s": {"type": "number", "description": "振动（mm/s）"},
            "power_kw": {"type": "number", "description": "功率（kW）"},
            "utilization": {"type": "number", "description": "利用率"},
            "fault": {"type": "object", "description": "故障信息（无故障为空）"},
        },
    },
    {
        "objectType": "ProductionLine", "primaryKey": "code",
        "title": "{code} · {name}", "description": "产线：车间的生产单元（主数据）。",
        "backingInterface": "派生自设备/工单的 line 字段",
        "properties": {
            "code": {"type": "string", "description": "产线代号（主键）"},
            "name": {"type": "string", "description": "产线名称"},
            "workshop": {"type": "string", "description": "所属车间"},
            "product_type": {"type": "string", "description": "生产类型"},
        },
    },
    {
        "objectType": "Product", "primaryKey": "product_code",
        "title": "{product_code} · {name}", "description": "产品：可制造物料的编码与单位（主数据，跨系统共享）。",
        "backingInterface": "GET /api/v1/routings/{product_code}",
        "properties": {
            "product_code": {"type": "string", "description": "产品编码（主键，跨系统）"},
            "name": {"type": "string", "description": "产品名称"},
            "uom": {"type": "string", "description": "计量单位"},
        },
    },
    {
        "objectType": "RoutingStep", "primaryKey": "product_code#seq",
        "title": "{product_code} · 工序{seq} {name}", "description": "工艺路线步骤：产品的标准工序序列与工时。",
        "backingInterface": "GET /api/v1/routings/{product_code}（嵌套 routing）",
        "properties": {
            "product_code": {"type": "string", "description": "所属产品，关联 Product"},
            "seq": {"type": "integer", "description": "工序序号"},
            "name": {"type": "string", "description": "工序名称"},
            "line": {"type": "string", "description": "执行产线"},
            "std_minutes": {"type": "number", "description": "标准工时（分钟）"},
        },
    },
    {
        "objectType": "Defect", "primaryKey": "defect_id",
        "title": "{defect_id} · {defect_name}（{severity}）", "description": "不良记录：制程/出货发现的质量缺陷。",
        "backingInterface": "GET /api/v1/defects",
        "properties": {
            "defect_id": {"type": "string", "description": "不良记录号（主键）"},
            "work_order_no": {"type": "string", "description": "关联工单号，关联 WorkOrder"},
            "product_code": {"type": "string", "description": "产品编码"},
            "line": {"type": "string", "description": "发现产线"},
            "defect_code": {"type": "string", "description": "缺陷码"},
            "defect_name": {"type": "string", "description": "缺陷名称"},
            "qty": {"type": "integer", "description": "不良数量"},
            "severity": {"type": "string", "description": "轻微/一般/严重"},
            "found_at": {"type": "string", "description": "发现时间"},
            "station": {"type": "string", "description": "发现工位 IPQC/OQC/自检"},
        },
    },
    {
        "objectType": "ShiftOutput", "primaryKey": "date#line#shift",
        "title": "{date} · {line} · {shift}", "description": "班次产量：产线每班次的计划/实际/不良产量。",
        "backingInterface": "GET /api/v1/shifts/outputs",
        "properties": {
            "date": {"type": "string", "description": "日期"},
            "line": {"type": "string", "description": "产线代号，关联 ProductionLine"},
            "shift": {"type": "string", "description": "班次"},
            "plan_qty": {"type": "integer", "description": "计划产量"},
            "actual_qty": {"type": "integer", "description": "实际产量"},
            "defect_qty": {"type": "integer", "description": "不良产量"},
        },
    },
    {
        "objectType": "OEE", "primaryKey": "line#date",
        "title": "{line} · {date} · OEE {oee}", "description": "OEE：产线日综合设备效率（可用率×性能×质量）。",
        "backingInterface": "GET /api/v1/oee",
        "properties": {
            "line": {"type": "string", "description": "产线代号，关联 ProductionLine"},
            "date": {"type": "string", "description": "日期"},
            "availability": {"type": "number", "description": "可用率"},
            "performance": {"type": "number", "description": "性能率"},
            "quality": {"type": "number", "description": "质量率"},
            "oee": {"type": "number", "description": "综合 OEE"},
        },
    },
    {
        "objectType": "WorkInProcess", "primaryKey": "work_order_no",
        "title": "{work_order_no} · {current_station}", "description": "在制品：在制工单当前停留工序与数量。",
        "backingInterface": "GET /api/v1/wip",
        "properties": {
            "work_order_no": {"type": "string", "description": "工单号，关联 WorkOrder"},
            "product_code": {"type": "string", "description": "产品编码"},
            "line": {"type": "string", "description": "产线"},
            "current_seq": {"type": "integer", "description": "当前工序序号"},
            "current_station": {"type": "string", "description": "当前工序名称"},
            "in_process_qty": {"type": "integer", "description": "在制数量"},
            "hold": {"type": "boolean", "description": "是否暂停"},
        },
    },
]

MES_LINK_TYPES = [
    {"linkType": "ProductionOrderToWorkOrders", "parent": "ProductionOrder", "child": "WorkOrder",
     "cardinality": "ONE_MANY", "joinField": "order_no", "description": "一张生产订单含多个工单。"},
    {"linkType": "WorkOrderToOperations", "parent": "WorkOrder", "child": "Operation",
     "cardinality": "ONE_MANY", "joinField": "work_order_no", "description": "一个工单含多道工序。"},
    {"linkType": "WorkOrderToDefects", "parent": "WorkOrder", "child": "Defect",
     "cardinality": "ONE_MANY", "joinField": "work_order_no", "description": "一个工单可有多条不良记录。"},
    {"linkType": "ProductToRoutingSteps", "parent": "Product", "child": "RoutingStep",
     "cardinality": "ONE_MANY", "joinField": "product_code", "description": "一个产品有多道工艺步骤。"},
    {"linkType": "LineToEquipment", "parent": "ProductionLine", "child": "Equipment",
     "cardinality": "ONE_MANY", "joinField": "line", "description": "一条产线含多台设备。"},
    {"linkType": "LineToWorkOrders", "parent": "ProductionLine", "child": "WorkOrder",
     "cardinality": "ONE_MANY", "joinField": "line", "description": "一条产线承接多个工单。"},
    {"linkType": "ProductToWorkOrders", "parent": "Product", "child": "WorkOrder",
     "cardinality": "ONE_MANY", "joinField": "product_code", "description": "一个产品在多张工单上生产。"},
    {"linkType": "WorkOrderToWip", "parent": "WorkOrder", "child": "WorkInProcess",
     "cardinality": "ONE_ONE", "joinField": "work_order_no", "description": "在制工单对应一条在制品记录。"},
    {"linkType": "LineToOee", "parent": "ProductionLine", "child": "OEE",
     "cardinality": "ONE_MANY", "joinField": "line", "description": "一条产线每日一条 OEE（按 date 区分）。"},
]

MES_ACTION_TYPES = [
    {"actionType": "reportWorkOrder", "operation": "MODIFY", "target": "WorkOrder",
     "description": "工单报工：累加 done_qty。",
     "backingInterface": "POST /api/v1/work-orders/{won}/report",
     "parameters": {
         "work_order_no": {"type": "string", "description": "工单号"},
         "operation_seq": {"type": "integer", "description": "报工工序序号"},
         "qty": {"type": "integer", "description": "本次报工数量"},
         "operator": {"type": "string", "description": "作业员"},
     },
     "effects": {"done_qty": "+=qty"},
    },
]

CRM_OBJECT_TYPES = [
    {
        "objectType": "Customer", "primaryKey": "code",
        "title": "{code} · {name}（{type}）", "description": "客户：OEM/ODM/经销商/终端/外贸，含信用与账期。",
        "backingInterface": "GET /api/v1/customers, GET /api/v1/customers/{code}",
        "properties": {
            "code": {"type": "string", "description": "客户编码（主键）"},
            "name": {"type": "string", "description": "客户名称"},
            "type": {"type": "string", "description": "OEM/ODM/经销商/终端/外贸"},
            "industry": {"type": "string", "description": "行业"},
            "region": {"type": "string", "description": "区域"},
            "credit_grade": {"type": "string", "description": "信用等级 A/B/C"},
            "payment_terms_days": {"type": "integer", "description": "账期（天）"},
            "currency": {"type": "string", "description": "结算币种"},
            "owner": {"type": "string", "description": "负责销售"},
            "address": {"type": "string", "description": "地址"},
        },
    },
    {
        "objectType": "Contact", "primaryKey": "contact_id",
        "title": "{name} · {title}", "description": "联系人：客户下的对接人与决策角色。",
        "backingInterface": "GET /api/v1/contacts",
        "properties": {
            "contact_id": {"type": "string", "description": "联系人 ID（主键）"},
            "customer_code": {"type": "string", "description": "所属客户，关联 Customer"},
            "name": {"type": "string", "description": "姓名"},
            "title": {"type": "string", "description": "职务"},
            "phone": {"type": "string", "description": "电话"},
            "email": {"type": "string", "description": "邮箱"},
            "decision_role": {"type": "string", "description": "决策者/影响者/使用者/把关者"},
        },
    },
    {
        "objectType": "Opportunity", "primaryKey": "opportunity_id",
        "title": "{opportunity_id} · {customer_name}（{stage}）", "description": "商机：销售漏斗中的机会，关联产品与阶段。",
        "backingInterface": "GET /api/v1/opportunities, GET /api/v1/opportunities/{opportunity_id}",
        "properties": {
            "opportunity_id": {"type": "string", "description": "商机 ID（主键）"},
            "customer_code": {"type": "string", "description": "客户编码，关联 Customer"},
            "customer_name": {"type": "string", "description": "客户名称"},
            "product_code": {"type": "string", "description": "产品编码，跨系统关联 MES.Product"},
            "stage": {"type": "string", "description": "线索/打样/报价/送样/NPI/成交/流失"},
            "amount": {"type": "number", "description": "金额"},
            "currency": {"type": "string", "description": "币种"},
            "owner": {"type": "string", "description": "负责销售"},
            "source": {"type": "string", "description": "商机来源"},
            "expected_close": {"type": "string", "description": "预期成交日期"},
        },
    },
    {
        "objectType": "Quotation", "primaryKey": "quotation_id",
        "title": "{quotation_id} · {product_code}（{status}）", "description": "报价：阶梯价 + 模具费/打样费。",
        "backingInterface": "GET /api/v1/quotations, GET /api/v1/quotations/{quotation_id}",
        "properties": {
            "quotation_id": {"type": "string", "description": "报价 ID（主键）"},
            "opportunity_id": {"type": "string", "description": "所属商机，关联 Opportunity"},
            "customer_code": {"type": "string", "description": "客户编码，关联 Customer"},
            "product_code": {"type": "string", "description": "产品编码，跨系统关联 MES.Product"},
            "customer_part_no": {"type": "string", "description": "客户料号"},
            "currency": {"type": "string", "description": "币种"},
            "tiers": {"type": "array", "description": "阶梯价 [{min_qty, unit_price}]"},
            "mold_fee": {"type": "number", "description": "模具费"},
            "sample_fee": {"type": "number", "description": "打样费"},
            "valid_until": {"type": "string", "description": "报价有效期"},
            "status": {"type": "string", "description": "草稿/待审/已发/已接受/已拒绝"},
        },
    },
    {
        "objectType": "SalesOrder", "primaryKey": "so_no",
        "title": "{so_no} · {customer_code}（{status}）", "description": "销售订单：确认成交后可触达 MES 排产。",
        "backingInterface": "GET /api/v1/sales-orders",
        "properties": {
            "so_no": {"type": "string", "description": "销售订单号（主键）"},
            "customer_code": {"type": "string", "description": "客户编码，关联 Customer"},
            "product_code": {"type": "string", "description": "产品编码，跨系统关联 MES.Product"},
            "qty": {"type": "integer", "description": "数量"},
            "unit_price": {"type": "number", "description": "单价"},
            "currency": {"type": "string", "description": "币种"},
            "status": {"type": "string", "description": "已确认/排产中/部分发货/已发货/已结案"},
            "delivery_date": {"type": "string", "description": "交付日期"},
        },
    },
    {
        "objectType": "FollowUp", "primaryKey": "followup_id",
        "title": "{followup_id} · {method} · {at}", "description": "跟进记录：客户/商机的沟通日志。",
        "backingInterface": "GET /api/v1/follow-ups",
        "properties": {
            "followup_id": {"type": "string", "description": "跟进 ID（主键）"},
            "customer_code": {"type": "string", "description": "客户编码，关联 Customer"},
            "opportunity_id": {"type": "string", "description": "商机 ID，关联 Opportunity"},
            "at": {"type": "string", "description": "跟进时间"},
            "method": {"type": "string", "description": "电话/拜访/邮件/微信"},
            "owner": {"type": "string", "description": "跟进人"},
            "content": {"type": "string", "description": "跟进内容"},
            "next_action": {"type": "string", "description": "下一步动作"},
        },
    },
    {
        "objectType": "Complaint", "primaryKey": "complaint_id",
        "title": "{complaint_id} · {customer_name}（{severity}）", "description": "客诉/8D：售后质量投诉，关联 MES 工单做追溯。",
        "backingInterface": "GET /api/v1/complaints, GET /api/v1/complaints/{complaint_id}",
        "properties": {
            "complaint_id": {"type": "string", "description": "客诉 ID（主键）"},
            "customer_code": {"type": "string", "description": "客户编码，关联 Customer"},
            "customer_name": {"type": "string", "description": "客户名称"},
            "product_code": {"type": "string", "description": "产品编码，跨系统关联 MES.Product"},
            "batch_no": {"type": "string", "description": "批次号"},
            "work_order_no": {"type": "string", "description": "关联工单号，跨系统关联 MES.WorkOrder"},
            "defect": {"type": "string", "description": "缺陷描述"},
            "severity": {"type": "string", "description": "一般/严重/致命"},
            "status": {"type": "string", "description": "已受理/分析中/8D 进行中/已闭环"},
            "reported_at": {"type": "string", "description": "投诉时间"},
            "owner": {"type": "string", "description": "处理人"},
        },
    },
    {
        "objectType": "Receivable", "primaryKey": "receivable_id",
        "title": "{receivable_id} · {customer_name}（{status}）", "description": "应收对账：发票/账期/逾期。",
        "backingInterface": "GET /api/v1/receivables",
        "properties": {
            "receivable_id": {"type": "string", "description": "应收 ID（主键）"},
            "customer_code": {"type": "string", "description": "客户编码，关联 Customer"},
            "customer_name": {"type": "string", "description": "客户名称"},
            "invoice_no": {"type": "string", "description": "发票号"},
            "amount": {"type": "number", "description": "金额"},
            "currency": {"type": "string", "description": "币种"},
            "billing_date": {"type": "string", "description": "开票日期"},
            "due_date": {"type": "string", "description": "到期日期"},
            "status": {"type": "string", "description": "未到期/逾期/已收款"},
            "days_overdue": {"type": "integer", "description": "逾期天数"},
        },
    },
]

CRM_LINK_TYPES = [
    {"linkType": "CustomerToContacts", "parent": "Customer", "child": "Contact",
     "cardinality": "ONE_MANY", "joinField": "customer_code", "description": "一个客户有多个联系人。"},
    {"linkType": "CustomerToOpportunities", "parent": "Customer", "child": "Opportunity",
     "cardinality": "ONE_MANY", "joinField": "customer_code", "description": "一个客户有多个商机。"},
    {"linkType": "OpportunityToQuotations", "parent": "Opportunity", "child": "Quotation",
     "cardinality": "ONE_MANY", "joinField": "opportunity_id", "description": "一个商机可有多份报价。"},
    {"linkType": "OpportunityToFollowUps", "parent": "Opportunity", "child": "FollowUp",
     "cardinality": "ONE_MANY", "joinField": "opportunity_id", "description": "一个商机有多条跟进。"},
    {"linkType": "CustomerToFollowUps", "parent": "Customer", "child": "FollowUp",
     "cardinality": "ONE_MANY", "joinField": "customer_code", "description": "一个客户有多条跟进。"},
    {"linkType": "CustomerToSalesOrders", "parent": "Customer", "child": "SalesOrder",
     "cardinality": "ONE_MANY", "joinField": "customer_code", "description": "一个客户有多个销售订单。"},
    {"linkType": "CustomerToComplaints", "parent": "Customer", "child": "Complaint",
     "cardinality": "ONE_MANY", "joinField": "customer_code", "description": "一个客户有多条客诉。"},
    {"linkType": "CustomerToReceivables", "parent": "Customer", "child": "Receivable",
     "cardinality": "ONE_MANY", "joinField": "customer_code", "description": "一个客户有多笔应收。"},
    {"linkType": "ComplaintToMesWorkOrder", "parent": "Complaint", "child": "MES.WorkOrder",
     "cardinality": "MANY_ONE", "joinField": "work_order_no", "crossSystem": True,
     "description": "【跨系统】客诉追溯至 MES 工单，可进一步关联不良记录与设备。"},
    {"linkType": "MesProductToSalesOrders", "parent": "MES.Product", "child": "SalesOrder",
     "cardinality": "ONE_MANY", "joinField": "product_code", "crossSystem": True,
     "description": "【跨系统】MES 产品关联其 CRM 销售订单。"},
    {"linkType": "MesProductToOpportunities", "parent": "MES.Product", "child": "Opportunity",
     "cardinality": "ONE_MANY", "joinField": "product_code", "crossSystem": True,
     "description": "【跨系统】MES 产品关联其 CRM 商机。"},
]

CRM_ACTION_TYPES = [
    {"actionType": "submitQuotation", "operation": "MODIFY", "target": "Quotation",
     "description": "报价送审：将 status 置为「待审」。",
     "backingInterface": "POST /api/v1/quotations/{quotation_id}/submit",
     "parameters": {
         "quotation_id": {"type": "string", "description": "报价 ID"},
         "approver": {"type": "string", "description": "送审人"},
         "comment": {"type": "string", "description": "备注"},
     },
     "effects": {"status": "待审"},
    },
]

ERP_OBJECT_TYPES = [
    {
        "objectType": "Supplier", "primaryKey": "code",
        "title": "{code} · {name}（{category}）", "description": "供应商：原材料/外协/辅料，含账期与评级。",
        "backingInterface": "GET /api/v1/suppliers, GET /api/v1/suppliers/{code}",
        "properties": {
            "code": {"type": "string", "description": "供应商编码（主键）"},
            "name": {"type": "string", "description": "供应商名称"},
            "category": {"type": "string", "description": "原材料/外协加工/辅料包装"},
            "contact": {"type": "string", "description": "联系人"},
            "phone": {"type": "string", "description": "电话"},
            "payment_terms_days": {"type": "integer", "description": "账期（天）"},
            "currency": {"type": "string", "description": "结算币种"},
            "rating": {"type": "string", "description": "评级 A/B/C"},
            "status": {"type": "string", "description": "合作中/暂停/淘汰"},
        },
    },
    {
        "objectType": "PurchaseOrder", "primaryKey": "po_no",
        "title": "{po_no} · {supplier_name}（{status}）", "description": "采购订单：向供应商下达的物料采购单。",
        "backingInterface": "GET /api/v1/purchase-orders, GET /api/v1/purchase-orders/{po_no}",
        "properties": {
            "po_no": {"type": "string", "description": "采购订单号（主键）"},
            "supplier_code": {"type": "string", "description": "供应商编码，关联 Supplier"},
            "supplier_name": {"type": "string", "description": "供应商名称"},
            "buyer": {"type": "string", "description": "采购员"},
            "currency": {"type": "string", "description": "币种"},
            "total_amount": {"type": "number", "description": "订单总额"},
            "status": {"type": "string", "description": "草稿/已下单/部分到货/已入库/关闭"},
            "order_date": {"type": "string", "description": "下单日期"},
            "expected_date": {"type": "string", "description": "预计到货日期"},
        },
    },
    {
        "objectType": "PurchaseOrderLine", "primaryKey": "po_no#line_no",
        "title": "{po_no} · 行{line_no} {material_name}", "description": "采购订单行：物料/数量/单价/已收。",
        "backingInterface": "GET /api/v1/purchase-orders/{po_no}（嵌套 lines）",
        "properties": {
            "po_no": {"type": "string", "description": "所属采购订单，关联 PurchaseOrder"},
            "line_no": {"type": "integer", "description": "行号"},
            "material_code": {"type": "string", "description": "物料编码，关联 Material"},
            "material_name": {"type": "string", "description": "物料名称"},
            "qty": {"type": "number", "description": "采购数量"},
            "uom": {"type": "string", "description": "计量单位"},
            "unit_price": {"type": "number", "description": "单价"},
            "received_qty": {"type": "number", "description": "已收数量"},
        },
    },
    {
        "objectType": "Material", "primaryKey": "material_code",
        "title": "{material_code} · {name}", "description": "物料：原材料/半成品/辅料，含安全库存与单位成本（P-* 与 MES 成品同码）。",
        "backingInterface": "GET /api/v1/materials, GET /api/v1/materials/{material_code}",
        "properties": {
            "material_code": {"type": "string", "description": "物料编码（主键，P-* 跨系统同 MES.Product）"},
            "name": {"type": "string", "description": "物料名称"},
            "category": {"type": "string", "description": "原材料/半成品/成品/辅料包装"},
            "uom": {"type": "string", "description": "计量单位"},
            "default_supplier": {"type": "string", "description": "默认供应商，关联 Supplier"},
            "safety_stock": {"type": "number", "description": "安全库存"},
            "unit_cost": {"type": "number", "description": "单位成本"},
        },
    },
    {
        "objectType": "Inventory", "primaryKey": "material_code#warehouse",
        "title": "{material_code} @ {warehouse}", "description": "库存：物料在仓库的现存量与可用量。",
        "backingInterface": "GET /api/v1/inventory",
        "properties": {
            "material_code": {"type": "string", "description": "物料编码，关联 Material"},
            "material_name": {"type": "string", "description": "物料名称"},
            "warehouse": {"type": "string", "description": "仓库，关联 Warehouse"},
            "stock_qty": {"type": "number", "description": "现存量"},
            "available_qty": {"type": "number", "description": "可用量"},
            "safety_stock": {"type": "number", "description": "安全库存"},
            "uom": {"type": "string", "description": "计量单位"},
        },
    },
    {
        "objectType": "Warehouse", "primaryKey": "code",
        "title": "{code} · {name}", "description": "仓库：原料/半成品/成品/辅料仓（主数据）。",
        "backingInterface": "GET /api/v1/warehouses",
        "properties": {
            "code": {"type": "string", "description": "仓库编码（主键）"},
            "name": {"type": "string", "description": "仓库名称"},
            "type": {"type": "string", "description": "原料仓/半成品仓/成品仓/辅料仓"},
        },
    },
    {
        "objectType": "StockMovement", "primaryKey": "movement_id",
        "title": "{movement_id} · {type} · {material_code}", "description": "库存出入库流水；ref_no 跨系统关联采购/销售/工单单号。",
        "backingInterface": "GET /api/v1/stock-movements",
        "properties": {
            "movement_id": {"type": "string", "description": "流水号（主键）"},
            "type": {"type": "string", "description": "采购入库/生产领料/生产入库/销售出库/调拨"},
            "material_code": {"type": "string", "description": "物料编码，关联 Material"},
            "warehouse": {"type": "string", "description": "仓库，关联 Warehouse"},
            "qty": {"type": "number", "description": "数量"},
            "uom": {"type": "string", "description": "计量单位"},
            "ref_no": {"type": "string", "description": "关联单号：PO/SO/WO/TR（跨系统）"},
            "at": {"type": "string", "description": "发生时间"},
        },
    },
    {
        "objectType": "Payable", "primaryKey": "payable_id",
        "title": "{payable_id} · {supplier_name}（{status}）", "description": "应付对账：供应商发票/账期/逾期。",
        "backingInterface": "GET /api/v1/payables",
        "properties": {
            "payable_id": {"type": "string", "description": "应付 ID（主键）"},
            "supplier_code": {"type": "string", "description": "供应商编码，关联 Supplier"},
            "supplier_name": {"type": "string", "description": "供应商名称"},
            "invoice_no": {"type": "string", "description": "发票号"},
            "amount": {"type": "number", "description": "金额"},
            "currency": {"type": "string", "description": "币种"},
            "billing_date": {"type": "string", "description": "开票日期"},
            "due_date": {"type": "string", "description": "到期日期"},
            "status": {"type": "string", "description": "未到期/逾期/已付款"},
            "days_overdue": {"type": "integer", "description": "逾期天数"},
        },
    },
    {
        "objectType": "Voucher", "primaryKey": "voucher_no",
        "title": "{voucher_no} · {period}（{status}）", "description": "财务凭证：会计期间的借贷记账。",
        "backingInterface": "GET /api/v1/vouchers",
        "properties": {
            "voucher_no": {"type": "string", "description": "凭证号（主键）"},
            "period": {"type": "string", "description": "会计期间 YYYY-MM"},
            "entry_date": {"type": "string", "description": "录入日期"},
            "summary": {"type": "string", "description": "摘要"},
            "debit_total": {"type": "number", "description": "借方合计"},
            "credit_total": {"type": "number", "description": "贷方合计"},
            "status": {"type": "string", "description": "草稿/已复核/已过账"},
        },
    },
    {
        "objectType": "CostCenter", "primaryKey": "code",
        "title": "{code} · {name}", "description": "成本中心：车间/部门（主数据）。",
        "backingInterface": "GET /api/v1/cost-centers",
        "properties": {
            "code": {"type": "string", "description": "成本中心编码（主键）"},
            "name": {"type": "string", "description": "名称"},
            "type": {"type": "string", "description": "车间/部门"},
        },
    },
    {
        "objectType": "ProductionCost", "primaryKey": "cost_id",
        "title": "{cost_id} · {work_order_no}（{total_cost}）", "description": "生产成本：按 MES 工单归集料/工/费。",
        "backingInterface": "GET /api/v1/production-costs",
        "properties": {
            "cost_id": {"type": "string", "description": "成本单号（主键）"},
            "work_order_no": {"type": "string", "description": "关联工单号，跨系统关联 MES.WorkOrder"},
            "cost_center": {"type": "string", "description": "成本中心，关联 CostCenter"},
            "period": {"type": "string", "description": "会计期间"},
            "material_cost": {"type": "number", "description": "材料成本"},
            "labor_cost": {"type": "number", "description": "人工成本"},
            "overhead": {"type": "number", "description": "制造费用"},
            "total_cost": {"type": "number", "description": "总成本"},
        },
    },
]

ERP_LINK_TYPES = [
    {"linkType": "SupplierToPurchaseOrders", "parent": "Supplier", "child": "PurchaseOrder",
     "cardinality": "ONE_MANY", "joinField": "supplier_code", "description": "一个供应商有多个采购订单。"},
    {"linkType": "PurchaseOrderToLines", "parent": "PurchaseOrder", "child": "PurchaseOrderLine",
     "cardinality": "ONE_MANY", "joinField": "po_no", "description": "一张采购订单含多行物料。"},
    {"linkType": "MaterialToPOLines", "parent": "Material", "child": "PurchaseOrderLine",
     "cardinality": "ONE_MANY", "joinField": "material_code", "description": "一种物料出现在多行采购。"},
    {"linkType": "MaterialToInventory", "parent": "Material", "child": "Inventory",
     "cardinality": "ONE_MANY", "joinField": "material_code", "description": "一种物料存于多个仓库。"},
    {"linkType": "WarehouseToInventory", "parent": "Warehouse", "child": "Inventory",
     "cardinality": "ONE_MANY", "joinField": "warehouse", "description": "一个仓库存多种物料。"},
    {"linkType": "MaterialToStockMovements", "parent": "Material", "child": "StockMovement",
     "cardinality": "ONE_MANY", "joinField": "material_code", "description": "一种物料有多条出入库流水。"},
    {"linkType": "WarehouseToStockMovements", "parent": "Warehouse", "child": "StockMovement",
     "cardinality": "ONE_MANY", "joinField": "warehouse", "description": "一个仓库有多条出入库流水。"},
    {"linkType": "SupplierToPayables", "parent": "Supplier", "child": "Payable",
     "cardinality": "ONE_MANY", "joinField": "supplier_code", "description": "一个供应商有多笔应付。"},
    {"linkType": "CostCenterToProductionCosts", "parent": "CostCenter", "child": "ProductionCost",
     "cardinality": "ONE_MANY", "joinField": "cost_center", "description": "一个成本中心归集多项生产成本。"},
    {"linkType": "MesWorkOrderToProductionCosts", "parent": "MES.WorkOrder", "child": "ProductionCost",
     "cardinality": "ONE_MANY", "joinField": "work_order_no", "crossSystem": True,
     "description": "【跨系统】MES 工单的成本由 ERP 归集（料/工/费）。"},
    {"linkType": "CrmSalesOrderToStockMovements", "parent": "CRM.SalesOrder", "child": "StockMovement",
     "cardinality": "ONE_MANY", "joinField": "ref_no", "crossSystem": True,
     "description": "【跨系统】CRM 销售订单的销售出库流水在 ERP（type=销售出库）。"},
    {"linkType": "PurchaseOrderToStockMovements", "parent": "PurchaseOrder", "child": "StockMovement",
     "cardinality": "ONE_MANY", "joinField": "ref_no", "description": "采购订单的采购入库流水（type=采购入库）。"},
    {"linkType": "MesProductToMaterial", "parent": "MES.Product", "child": "Material",
     "cardinality": "ONE_ONE", "joinField": "product_code / material_code", "crossSystem": True,
     "description": "【跨系统】MES 成品(P-*)与 ERP 物料同码标识，实现产/销/存统一。"},
]

ERP_ACTION_TYPES = [
    {"actionType": "receivePurchaseOrder", "operation": "MODIFY", "target": "PurchaseOrder",
     "description": "采购收货入库：更新行已收量并生成采购入库流水。",
     "backingInterface": "POST /api/v1/purchase-orders/{po_no}/receive",
     "parameters": {
         "po_no": {"type": "string", "description": "采购订单号"},
         "line_no": {"type": "integer", "description": "收货行号"},
         "qty": {"type": "integer", "description": "本次收货数量"},
         "warehouse": {"type": "string", "description": "入库仓库"},
         "receiver": {"type": "string", "description": "收货人"},
     },
     "effects": {"received_qty": "+=qty", "StockMovement": "create(type=采购入库)"},
    },
    {"actionType": "postVoucher", "operation": "CREATE", "target": "Voucher",
     "description": "新建财务凭证（草稿态）。",
     "backingInterface": "POST /api/v1/vouchers",
     "parameters": {
         "period": {"type": "string", "description": "会计期间 YYYY-MM"},
         "summary": {"type": "string", "description": "摘要"},
         "debit_total": {"type": "number", "description": "借方合计"},
         "credit_total": {"type": "number", "description": "贷方合计"},
     },
     "effects": {"status": "草稿"},
    },
]

HRM_OBJECT_TYPES = [
    {
        "objectType": "Employee", "primaryKey": "emp_no",
        "title": "{emp_no} · {name}（{department}）", "description": "员工：车间工号与 MES 作业员同码、姓名与 CRM 负责人对齐、cost_center 归 ERP。",
        "backingInterface": "GET /api/v1/employees, GET /api/v1/employees/{emp_no}",
        "properties": {
            "emp_no": {"type": "string", "description": "工号（主键，车间员工跨系统同 MES.WorkOrder.operator）"},
            "name": {"type": "string", "description": "姓名（销售员工跨系统同 CRM.*.owner）"},
            "gender": {"type": "string", "description": "性别"},
            "department": {"type": "string", "description": "部门编码，关联 Department"},
            "position": {"type": "string", "description": "岗位编码，关联 Position"},
            "status": {"type": "string", "description": "在职/试用/离职"},
            "hire_date": {"type": "string", "description": "入职日期"},
            "phone": {"type": "string", "description": "电话"},
            "email": {"type": "string", "description": "邮箱"},
            "cost_center": {"type": "string", "description": "成本中心，跨系统关联 ERP.CostCenter"},
        },
    },
    {
        "objectType": "Department", "primaryKey": "code",
        "title": "{code} · {name}", "description": "部门：映射 ERP 成本中心（主数据）。",
        "backingInterface": "GET /api/v1/departments, GET /api/v1/departments/{code}",
        "properties": {
            "code": {"type": "string", "description": "部门编码（主键）"},
            "name": {"type": "string", "description": "部门名称"},
            "parent_code": {"type": "string", "description": "上级部门编码"},
            "manager_emp_no": {"type": "string", "description": "部门负责人，关联 Employee"},
            "cost_center": {"type": "string", "description": "成本中心，跨系统关联 ERP.CostCenter"},
        },
    },
    {
        "objectType": "Position", "primaryKey": "code",
        "title": "{code} · {name}", "description": "岗位：职级体系（主数据）。",
        "backingInterface": "GET /api/v1/positions",
        "properties": {
            "code": {"type": "string", "description": "岗位编码（主键）"},
            "name": {"type": "string", "description": "岗位名称"},
            "grade": {"type": "string", "description": "职类"},
            "level": {"type": "integer", "description": "职级"},
        },
    },
    {
        "objectType": "Attendance", "primaryKey": "emp_no#date",
        "title": "{emp_no} · {date}（{status}）", "description": "考勤：员工日出勤与加班。",
        "backingInterface": "GET /api/v1/attendance",
        "properties": {
            "emp_no": {"type": "string", "description": "工号，关联 Employee"},
            "name": {"type": "string", "description": "姓名"},
            "date": {"type": "string", "description": "日期"},
            "shift": {"type": "string", "description": "班次"},
            "check_in": {"type": "string", "description": "上班打卡"},
            "check_out": {"type": "string", "description": "下班打卡"},
            "status": {"type": "string", "description": "正常/迟到/早退/缺勤/加班"},
            "overtime_hours": {"type": "number", "description": "加班时长（h）"},
        },
    },
    {
        "objectType": "Leave", "primaryKey": "leave_id",
        "title": "{leave_id} · {name} {type}", "description": "请假：假期申请与审批。",
        "backingInterface": "GET /api/v1/leaves",
        "properties": {
            "leave_id": {"type": "string", "description": "请假单号（主键）"},
            "emp_no": {"type": "string", "description": "工号，关联 Employee"},
            "name": {"type": "string", "description": "姓名"},
            "department": {"type": "string", "description": "部门"},
            "type": {"type": "string", "description": "年假/病假/事假/调休/婚假"},
            "start": {"type": "string", "description": "开始日期"},
            "end": {"type": "string", "description": "结束日期"},
            "days": {"type": "number", "description": "天数"},
            "reason": {"type": "string", "description": "事由"},
            "status": {"type": "string", "description": "待批/已批/已驳/已销"},
            "approver": {"type": "string", "description": "审批人，关联 Employee"},
        },
    },
    {
        "objectType": "Payroll", "primaryKey": "payroll_id",
        "title": "{payroll_id} · {name}（{period}）", "description": "薪酬：按期间核算的工资明细，cost_center 归 ERP。",
        "backingInterface": "GET /api/v1/payrolls",
        "properties": {
            "payroll_id": {"type": "string", "description": "薪酬单号（主键）"},
            "emp_no": {"type": "string", "description": "工号，关联 Employee"},
            "name": {"type": "string", "description": "姓名"},
            "department": {"type": "string", "description": "部门"},
            "cost_center": {"type": "string", "description": "成本中心，跨系统关联 ERP.CostCenter"},
            "period": {"type": "string", "description": "会计期间 YYYY-MM"},
            "base_salary": {"type": "number", "description": "基本工资"},
            "overtime_pay": {"type": "number", "description": "加班费"},
            "bonus": {"type": "number", "description": "奖金"},
            "deduction": {"type": "number", "description": "扣款"},
            "net_pay": {"type": "number", "description": "实发工资"},
            "status": {"type": "string", "description": "已核算/已发放/待审批"},
        },
    },
    {
        "objectType": "Performance", "primaryKey": "perf_id",
        "title": "{perf_id} · {name} {grade}({score})", "description": "绩效：员工周期 KPI 与评级。",
        "backingInterface": "GET /api/v1/performances",
        "properties": {
            "perf_id": {"type": "string", "description": "绩效单号（主键）"},
            "emp_no": {"type": "string", "description": "工号，关联 Employee"},
            "name": {"type": "string", "description": "姓名"},
            "department": {"type": "string", "description": "部门"},
            "period": {"type": "string", "description": "考核期间"},
            "score": {"type": "integer", "description": "考核得分"},
            "grade": {"type": "string", "description": "A/B/C/D"},
            "kpi": {"type": "string", "description": "KPI 指标"},
            "comment": {"type": "string", "description": "评语"},
        },
    },
    {
        "objectType": "Recruitment", "primaryKey": "req_id",
        "title": "{req_id} · {department} ×{headcount}", "description": "招聘需求：部门编制缺口与进度。",
        "backingInterface": "GET /api/v1/recruitments",
        "properties": {
            "req_id": {"type": "string", "description": "需求单号（主键）"},
            "department": {"type": "string", "description": "部门编码，关联 Department"},
            "position": {"type": "string", "description": "岗位编码，关联 Position"},
            "headcount": {"type": "integer", "description": "招聘人数"},
            "status": {"type": "string", "description": "招聘中/已关闭"},
            "urgency": {"type": "string", "description": "紧急/常规/储备"},
            "owner": {"type": "string", "description": "负责人，关联 Employee"},
            "open_date": {"type": "string", "description": "开放日期"},
        },
    },
]

HRM_LINK_TYPES = [
    {"linkType": "DepartmentToEmployees", "parent": "Department", "child": "Employee",
     "cardinality": "ONE_MANY", "joinField": "department", "description": "一个部门有多个员工。"},
    {"linkType": "PositionToEmployees", "parent": "Position", "child": "Employee",
     "cardinality": "ONE_MANY", "joinField": "position", "description": "一个岗位有多个员工。"},
    {"linkType": "EmployeeToAttendance", "parent": "Employee", "child": "Attendance",
     "cardinality": "ONE_MANY", "joinField": "emp_no", "description": "一个员工有多条考勤。"},
    {"linkType": "EmployeeToLeaves", "parent": "Employee", "child": "Leave",
     "cardinality": "ONE_MANY", "joinField": "emp_no", "description": "一个员工有多条请假。"},
    {"linkType": "EmployeeToPayrolls", "parent": "Employee", "child": "Payroll",
     "cardinality": "ONE_MANY", "joinField": "emp_no", "description": "一个员工有多期薪酬。"},
    {"linkType": "EmployeeToPerformances", "parent": "Employee", "child": "Performance",
     "cardinality": "ONE_MANY", "joinField": "emp_no", "description": "一个员工有多期绩效。"},
    {"linkType": "DepartmentToRecruitments", "parent": "Department", "child": "Recruitment",
     "cardinality": "ONE_MANY", "joinField": "department", "description": "一个部门有多条招聘需求。"},
    {"linkType": "EmployeeToMesWorkOrders", "parent": "HRM.Employee", "child": "MES.WorkOrder",
     "cardinality": "ONE_MANY", "joinField": "emp_no / operator", "crossSystem": True,
     "description": "【跨系统】车间员工的 MES 工单（工号=作业员）。"},
    {"linkType": "EmployeeToErpCostCenter", "parent": "HRM.Employee", "child": "ERP.CostCenter",
     "cardinality": "MANY_ONE", "joinField": "cost_center", "crossSystem": True,
     "description": "【跨系统】员工归属 ERP 成本中心，用于成本归集。"},
    {"linkType": "PayrollToErpCostCenter", "parent": "HRM.Payroll", "child": "ERP.CostCenter",
     "cardinality": "MANY_ONE", "joinField": "cost_center", "crossSystem": True,
     "description": "【跨系统】薪酬成本归集到 ERP 成本中心。"},
    {"linkType": "EmployeeToCrmOpportunities", "parent": "HRM.Employee", "child": "CRM.Opportunity",
     "cardinality": "ONE_MANY", "joinField": "name / owner", "crossSystem": True,
     "description": "【跨系统】销售员工负责的 CRM 商机（姓名=负责人，软匹配）。"},
]

HRM_ACTION_TYPES = [
    {"actionType": "applyLeave", "operation": "CREATE", "target": "Leave",
     "description": "请假申请：创建待批请假单。",
     "backingInterface": "POST /api/v1/leaves",
     "parameters": {
         "emp_no": {"type": "string", "description": "工号"},
         "type": {"type": "string", "description": "年假/病假/事假/调休/婚假"},
         "start": {"type": "string", "description": "开始日期"},
         "end": {"type": "string", "description": "结束日期"},
         "days": {"type": "number", "description": "天数"},
         "reason": {"type": "string", "description": "事由"},
     },
     "effects": {"status": "待批"},
    },
    {"actionType": "runPayroll", "operation": "MODIFY", "target": "Payroll",
     "description": "生成薪酬：按期间/成本中心核算并汇总。",
     "backingInterface": "POST /api/v1/payrolls/run",
     "parameters": {
         "period": {"type": "string", "description": "会计期间 YYYY-MM"},
         "cost_center": {"type": "string", "description": "成本中心（可选）"},
     },
     "effects": {"status": "已核算"},
    },
]


# ───────────────────────── Markdown 渲染 ─────────────────────────

def render_object_types_md(title: str, intro: str, object_types: list) -> str:
    lines = [f"# {title}\n", f"> {intro}\n", "**对象类型（Object Types）**——每个类型含主键、标题、属性集与绑定数据接口。\n", "```ontology"]
    lines.append(json.dumps(object_types, ensure_ascii=False, indent=2))
    lines.append("```\n")
    for ot in object_types:
        lines.append(f"## {ot['objectType']}")
        lines.append(f"{ot.get('description', '')}\n")
        lines.append(f"- 主键：`{ot['primaryKey']}` ｜ 标题：`{ot.get('title', '')}`")
        if ot.get("backingInterface"):
            lines.append(f"- 数据接口：`{ot['backingInterface']}`")
        lines.append("\n| 属性 | 类型 | 说明 |")
        lines.append("|---|---|---|")
        for pname, pdef in ot["properties"].items():
            lines.append(f"| `{pname}` | {pdef['type']} | {pdef.get('description', '')} |")
        lines.append("")
    return "\n".join(lines)


def render_link_types_md(title: str, intro: str, link_types: list) -> str:
    lines = [f"# {title}\n", f"> {intro}\n", "**链接类型（Link Types）**——父子对象类型 + 基数 + join 字段。`crossSystem` 标记跨 MES/CRM 联动。\n", "```ontology"]
    lines.append(json.dumps(link_types, ensure_ascii=False, indent=2))
    lines.append("```\n")
    lines.append("| 链接类型 | 父对象 | 子对象 | 基数 | join 字段 | 跨系统 | 说明 |")
    lines.append("|---|---|---|---|---|---|---|")
    for lt in link_types:
        cross = "✅" if lt.get("crossSystem") else "—"
        lines.append(f"| {lt['linkType']} | {lt['parent']} | {lt['child']} | {lt['cardinality']} | `{lt['joinField']}` | {cross} | {lt.get('description', '')} |")
    return "\n".join(lines)


def render_action_types_md(title: str, intro: str, action_types: list) -> str:
    lines = [f"# {title}\n", f"> {intro}\n", "**动作类型（Action Types）**——CREATE/MODIFY/DELETE/EXECUTE + 目标对象 + 入参 + 效果。\n", "```ontology"]
    lines.append(json.dumps(action_types, ensure_ascii=False, indent=2))
    lines.append("```\n")
    for at in action_types:
        lines.append(f"## {at['actionType']}")
        lines.append(f"{at.get('description', '')}\n")
        lines.append(f"- 操作：`{at['operation']}` ｜ 目标：`{at['target']}`")
        if at.get("backingInterface"):
            lines.append(f"- 数据接口：`{at['backingInterface']}`")
        lines.append("\n| 参数 | 类型 | 说明 |")
        lines.append("|---|---|---|")
        for pname, pdef in at["parameters"].items():
            lines.append(f"| `{pname}` | {pdef['type']} | {pdef.get('description', '')} |")
        if at.get("effects"):
            lines.append(f"\n- 效果：`{json.dumps(at['effects'], ensure_ascii=False)}`")
        lines.append("")
    return "\n".join(lines)


def render_readme_md(title: str, folder: str, object_types: list, link_types: list, action_types: list, summary: str) -> str:
    cross = [lt for lt in link_types if lt.get("crossSystem")]
    lines = [
        f"# {title}", "", summary, "",
        "本文件为索引；详细定义见同目录：", "",
        f"- [`object-types.md`]({folder}/object-types.md)——对象类型",
        f"- [`link-types.md`]({folder}/link-types.md)——链接类型",
        f"- [`action-types.md`]({folder}/action-types.md)——动作类型", "",
        f"**对象类型 {len(object_types)}**：" + "、".join(ot["objectType"] for ot in object_types) + "  ",
        f"**链接类型 {len(link_types)}**（跨系统 {len(cross)}）：" + "、".join(lt["linkType"] for lt in link_types) + "  ",
        f"**动作类型 {len(action_types)}**：" + "、".join(at["actionType"] for at in action_types), "",
        "> 依据 Palantir Foundry Ontology 规范组织；属性与 mock 数据接口字段一一对应。agent 运行时按任务配置注入对应文件 content。",
    ]
    return "\n".join(lines)


# ───────────────────────── 单系统导入 ─────────────────────────

def _files_for(folder: str, label: str, object_types, link_types, action_types, summary) -> list[tuple[str, str, dict]]:
    meta = {"system": folder.lower(), "source": "mock"}
    return [
        (f"{folder}/README.md", render_readme_md(label, folder, object_types, link_types, action_types, summary), {**meta, "kind": "readme"}),
        (f"{folder}/object-types.md",
         render_object_types_md(f"{label} · 对象类型",
                                f"由 mock {folder} 数据接口（连接器 `mock-{folder.lower()}`）支撑。",
                                object_types),
         {**meta, "kind": "object-types"}),
        (f"{folder}/link-types.md",
         render_link_types_md(f"{label} · 链接类型",
                              f"定义 {label} 内部及跨系统对象间的关系。",
                              link_types),
         {**meta, "kind": "link-types"}),
        (f"{folder}/action-types.md",
         render_action_types_md(f"{label} · 动作类型",
                                f"定义 {label} 上可执行的写操作。",
                                action_types),
         {**meta, "kind": "action-types"}),
    ]


SYSTEMS = [
    {
        "folder": "MES", "label": "MES 制造执行本体",
        "summary": "生产侧本体：覆盖生产订单、工单、工序、设备、产线、产品、工艺路线、不良、班次产量、OEE、在制品。",
        "object_types": MES_OBJECT_TYPES, "link_types": MES_LINK_TYPES, "action_types": MES_ACTION_TYPES,
    },
    {
        "folder": "CRM", "label": "CRM 工业销售本体",
        "summary": "销售侧本体：覆盖客户、联系人、商机、报价、销售订单、跟进、客诉/8D、应收对账；客诉与产品跨系统关联 MES。",
        "object_types": CRM_OBJECT_TYPES, "link_types": CRM_LINK_TYPES, "action_types": CRM_ACTION_TYPES,
    },
    {
        "folder": "ERP", "label": "ERP 资源计划本体",
        "summary": "资源侧本体：覆盖供应商、采购订单、物料、库存、仓库、出入库、应付、财务凭证、成本中心、生产成本；工单成本与销售出库跨系统关联 MES/CRM。",
        "object_types": ERP_OBJECT_TYPES, "link_types": ERP_LINK_TYPES, "action_types": ERP_ACTION_TYPES,
    },
    {
        "folder": "HRM", "label": "HRM 人力资源本体",
        "summary": "人资侧本体：覆盖员工、部门、岗位、考勤、请假、薪酬、绩效、招聘；工号/姓名/成本中心跨系统关联 MES作业员、CRM负责人、ERP成本中心。",
        "object_types": HRM_OBJECT_TYPES, "link_types": HRM_LINK_TYPES, "action_types": HRM_ACTION_TYPES,
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
                "请先运行 seed_minrui_manufacturing.py，或用 MOCK_SEED_ORG_SLUG 指定。"
            )
        logger.info("seed_ontology_org", slug=org.slug, org_id=str(org.id))

        for s in SYSTEMS:
            await create_folder(db, org.id, SCOPE_TYPE, SCOPE_ID, s["folder"])
            files = _files_for(s["folder"], s["label"], s["object_types"], s["link_types"], s["action_types"], s["summary"])
            for path, content, meta in files:
                await upsert_file(db, org.id, SCOPE_TYPE, SCOPE_ID,
                                  OntologyFileCreate(path=path, content=content, metadata=meta, scope_type=SCOPE_TYPE, scope_id=SCOPE_ID))
                logger.info("ontology_file_upserted", path=path)
            overall["systems"].append({
                "folder": s["folder"], "label": s["label"],
                "object_types": len(s["object_types"]), "link_types": len(s["link_types"]),
                "action_types": len(s["action_types"]),
                "cross_system_links": sum(1 for lt in s["link_types"] if lt.get("crossSystem")),
            })

        await db.commit()
    return overall


def _print_report(result: dict) -> None:
    print("\n" + "=" * 64)
    print("Palantir 风格本体导入完成（覆盖式幂等，可安全重复执行）")
    print("-" * 64)
    print(f"{'文件夹':<10}{'对象类型':>10}{'链接类型':>10}{'跨系统':>8}{'动作类型':>10}")
    for s in result["systems"]:
        print(f"{s['folder']:<10}{s['object_types']:>10}{s['link_types']:>10}"
              f"{s['cross_system_links']:>8}{s['action_types']:>10}")
    print("-" * 64)
    print("位置：管理端「敏睿制造」组织 → 本体（Ontology）→ MES/、CRM/ 文件夹。")
    print("终端任务勾选对应本体文件后，agent 推理时注入其 Markdown。")
    print("=" * 64)


if __name__ == "__main__":
    res = asyncio.run(seed())
    _print_report(res)
