#!/usr/bin/env bash
# SC-1 物料AI校验：我方发起 → 工厂到货确认 → SCM 校验 → MES 工单锁定。
# 演示点：跨系统（SCM + MES）— 工单号 XWO2026xxx 交叉引用。
set -euo pipefail
source "$(dirname "$0")/_common.sh"

export AGENT_SLUG="starclothing-sc1-material-validation"
export DEMO_TITLE="SC-1 物料AI校验（我方发起 → 工厂确认 → SCM 校验 → MES 锁定）"
export DEMO_MSG='星途服装本周面料/辅料到货批次待校验。校验由我方（品牌方）发起：先调 SCM listMaterialValidations 拿待校验物料，对每批按工单号（如 XWO20260788）调 MES getWorkOrder 拿工单 BOM，对比到货明细 vs BOM（数量/规格/供应商）。
覆盖点：(1) BOM 一致性（数量差异、规格差异、供应商资质）；(2) 供应商资质有效期（调 listSuppliers 拿 ISO/Oeko-Tex 等证书）；(3) 让步接收规则（缺数 >5% 退货，超数 >3% 让步）。
最终输出：校验结果表（物料编码|工单号|BOM一致性|数量差异|规格差异|供应商资质|校验结论）+ 待处理项（工单号→异常类型→处理建议→责任人）+ 闭环汇总。'

run_demo
