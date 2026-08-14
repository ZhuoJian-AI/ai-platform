#!/usr/bin/env bash
# SC-2 工厂排产：MES 工单 + SCM 产能日历 + 面料到货 + 补货节奏联动。
# 演示点：跨系统（MES + SCM）— 工单/产线/产能/到货/补货四源联动排产。
set -euo pipefail
source "$(dirname "$0")/_common.sh"

export AGENT_SLUG="starclothing-sc2-factory-scheduling"
export DEMO_TITLE="SC-2 工厂排产（产能 + 面料到货 + 补货节奏联动）"
export DEMO_MSG='星途服装下周排产：列出所有 pending 状态工单（MES listWorkOrders status=pending），结合 SCM listCapacityCalendar 产能日历、listFabricArrivalPlans 面料到货计划、listReplenishmentSuggestions 补货建议，输出可执行产线排程。
排产规则：(1) 面料优先级：工单按面料到货日升序排，未到货不可上裁床；(2) 产线占用：按产能日历-已占用匹配，同品类优先专产线（压胶冲锋衣→车缝A，双面呢→车缝B）；(3) 交期优先级：交期近的优先；(4) 补货节奏：紧急补货工单提到队首；(5) 瓶颈识别：满载月份提示外协/加班。
最终输出：(1) 排程表（工单号|款号|数量|面料到货日|上裁床日|上车缝日|上整烫日|入库日|产线）；(2) 风险提示（工单→风险类型→应对建议）；(3) 产线负载（产线→当月已排产/总产能/占用率→瓶颈月份）；(4) 补货建议（面料→紧急程度→建议补货日→影响工单）。'

run_demo
