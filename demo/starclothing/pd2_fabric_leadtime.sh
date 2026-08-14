#!/usr/bin/env bash
# PD-2 数字面料库：实时交期计算 + 异动检测。
# 演示点：调用 estimate-leadtime（cached:false 永不缓存）+ getLeadtimeDiff 异动检测。
set -euo pipefail
source "$(dirname "$0")/_common.sh"

export AGENT_SLUG="starclothing-pd2-fabric-library"
export DEMO_TITLE="PD-2 数字面料库（实时交期 + 异动检测）"
export DEMO_MSG='对星途服装的面料 M-WOOL-DBL-360（双面呢）、M-SHELL-3L-150（三层压胶面料）、M-TC-180（涤棉）做实时成本/交期/产能测算。必须调用 estimate-leadtime（cached:false，取实时值）拿当前真实交期，再调 getLeadtimeDiff 对比基线检测异动。对每款面料输出：候选供应商、报价、评分明细（price/leadtime/payment）、实时交期、交期异动（Δ>0 时高亮）、产能占用、选用建议。'

run_demo
