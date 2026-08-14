#!/usr/bin/env bash
# PD-1 产品全流程AI监管：扫描 PLM 逾期订单 → 推送清单。
# 演示点：调用 listOverdueOrders 端点（PLM PD-1 关键端点）+ 交叉查询款号详情。
set -euo pipefail
source "$(dirname "$0")/_common.sh"

export AGENT_SLUG="starclothing-pd1-product-monitor"
export DEMO_TITLE="PD-1 产品全流程AI监管（逾期订单捕获 + 推送）"
export DEMO_MSG='扫描星途服装当前所有已逾期/7天内将逾期的订单，按款号汇总当前阶段、责任人、风险等级，并给出每条订单的推送对象和补救建议。优先调用 listOverdueOrders 端点，再交叉查询 listBulkOrders / listSamplingOrders 补全款号、品类、客户信息。最终输出：(1) 全流程进度汇总表；(2) 逾期款号推送清单（每条=款号+推送对象+关键提示+补救建议）。'

run_demo
