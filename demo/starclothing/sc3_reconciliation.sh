#!/usr/bin/env bash
# SC-3 自动化单据对账：CRM 销售订单 ↔ MES 工单 ↔ ERP 成本/应收/应付/收款。
# 演示点：三系统（ERP + MES + CRM）跨系统对账。
set -euo pipefail
source "$(dirname "$0")/_common.sh"

export AGENT_SLUG="starclothing-sc3-reconciliation"
export DEMO_TITLE="SC-3 自动化单据对账（CRM↔MES↔ERP 三系统联动）"
export DEMO_MSG='星途服装本月单据对账：CRM 销售订单 ↔ MES 工单 ↔ ERP 生产成本/应收/应付/收款。
对账逻辑：(1) CRM listSalesOrders × MES listWorkOrders 按 work_order_no 交叉，订单数 vs 工单完成数差异 >2% 标注；(2) MES 工单 × ERP listProductionCosts 按 work_order_no，超支 >5% 标注；(3) CRM 销售 × ERP listReceivables 按订单号，应收 vs 订单金额；(4) ERP listPayables × listPayments 应付 vs 实际付款；(5) CRM listComplaints 关联工单，重复投诉高亮。
最终输出：(1) 对账结果表（单据类型|单据号|关联工单|标准金额|实际金额|差异|差异率|状态）；(2) 异常清单（单据号→异常类型→责任方→处理建议）；(3) 闭环待办（异常单据→责任部门→处理时限）；(4) 汇总（本期对账单据数/通过数/异常数/异常率）。'

run_demo
