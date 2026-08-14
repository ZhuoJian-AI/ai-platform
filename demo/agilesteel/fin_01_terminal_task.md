# FIN-01 分钢种成本核算与多系统对账

> 归口财务部·对账组，用户 `fin-accountant`。glm-5.2 / craft。无 RAG（规则在模板）。
> template_agent_id `1b12d355-d41c-46bc-afbf-ceff8c44c668`（`agilesteel-fin-01-cost-reconciliation`）。

## 1. 演示身份
组织 `agilesteel`，用户 `fin-accountant` / `12345678`，部门 finance，团队 fin-recon。

## 2. 前置条件
平台 + mock + 5 seed + glm-5.2 路由。五方对账需 ERP/MES/SCM/PLM/CRM mock 均 health ok。

## 3. 操作步骤
登录 `/agilesteel/terminal/login` → glm-5.2 / craft / 绑智能体 `分钢种成本与对账` → 贴 composer：

```
做分钢种炉次成本核算与五方对账，重点炉次 HT2026062901（P-ST-Q345B）/HT2026062902（P-ST-45#）+ 凭证 BV-AS-2026-0512（财务复核中）。扫所有炉次成本，按凭证/报价/台账/应收做五方对账，差异率>2% 标异常。

/agilesteel-finance-erp-mes-scm-plm-crm-query
```

## 4. 期望输出
成本核算子任务：① 分钢种炉次成本表（HT|P-ST-|物料|人工|制造费用|总成本|吨钢）② 成本差异分析。
对账子任务：① 五方对账差异表（BV-AS-↔PC-AS-↔ASQ↔CL-AS-↔ASINV）② 异常清单 + 催办对象。
应收子任务：① 应收催办清单 ② 推送对象汇总。

## 5. 故障排查
- heat_no 跨系统：ERP PC-AS- 含 heat_no，MES getHeat(heat_no=HT2026062901) 直查勿转换
- BV-AS- 跨系统 SSO：ERP listVouchers + PLM getCostLedger 同号交叉查
- 五方对账按 heat_no/steel_grade/work_order_no 关联，勿直传异构编码

## 6. 附：手工调 API 复现
```bash
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug -H "Content-Type: application/json" -d '{"slug":"agilesteel","username":"fin-accountant","password":"12345678"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"title":"分钢种成本核算与多系统对账","config":{"template_agent_id":"1b12d355-d41c-46bc-afbf-ceff8c44c668","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"message":"做分钢种炉次成本核算与五方对账，重点炉次 HT2026062901（P-ST-Q345B）/HT2026062902（P-ST-45#）+ 凭证 BV-AS-2026-0512（财务复核中）。扫所有炉次成本，按凭证/报价/台账/应收做五方对账，差异率>2% 标异常。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 5 trace（无 rag；memory.load + ontology ERP/MES/SCM/PLM/CRM identifiers + data_interface 5 系统 + skill + memory.extract）
- [ ] tool_call 跨 5 系统：ERP listVouchers/listProductionCosts/listPayables + MES listHeats/getHeat + SCM listQuotations/compareQuotations + PLM getCostLedger + CRM listReceivables
- [ ] no-guessing：凭证 BV-AS-、炉次成本 PC-AS-（含 heat_no）、报价 ASQ、台账 CL-AS-、应收 ASINV 前缀正确
- [ ] 五方对账差异率 >2% 标异常
