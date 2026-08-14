#!/usr/bin/env bash
# SC-4 价格AI自动比对 + 成本台账自动生成。
# 演示点：SCM 报价评分（价格40%+交期30%+账期30%）+ ERP 成本台账自动写入。
set -euo pipefail
source "$(dirname "$0")/_common.sh"

export AGENT_SLUG="starclothing-sc4-price-comparison"
export DEMO_TITLE="SC-4 价格AI自动比对 + 成本台账自动生成"
export DEMO_MSG='星途服装本季度面料/辅料采购报价比对：对 M-WOOL-DBL-360（双面呢）、M-SHELL-3L-150（三层压胶面料）、M-ZIP-YKK-5（YKK拉链）做价格 AI 自动比对 + 成本台账自动生成。
比对逻辑：(1) SCM compareQuotations 拿多供应商评分明细（price_score 40%/leadtime_score 30%/payment_score 30%）；(2) SCM listQuotations 历史报价对比，波动 >5% 标注异动；(3) ERP listMaterials 拿物料标准成本，差异 >3% 建议更新；(4) ERP listCostLedger 看是否已有台账记录，无则建议新建（款号/物料/单价/供应商/有效期），有则比对是否需更新；(5) 账期评估：payment_score 加权，账期过长提示风险。
最终输出：(1) 比价表（物料编码|规格|候选供应商|报价|评分明细|综合评分|排名）；(2) 异动清单（物料|历史报价|当前报价|波动率）；(3) 成本台账建议（款号|物料|推荐供应商|单价|操作：新建/更新/保留）；(4) 汇总（本期比价物料数/异动数/台账待新建数/待更新数）。'

run_demo
