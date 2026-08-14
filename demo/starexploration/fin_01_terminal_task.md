# FIN-01 票据识别审核与智能核算

## 1. 演示身份
- 组织 `starexploration` / 用户 `fin-accountant` / 口令 `12345678`（资产财务部·核算与票据组）
- 终端登录 `/starexploration/terminal/login`
- template_agent_id：`fdbda49c-c8bf-45f3-b080-faca64cff369`（`starexploration-fin-01-invoice-accounting`）

## 2. 前置条件
docker compose 起；5 seed 跑完；provider 真 key 已复制（A3）；backend 注入 mock 包（A1）。

## 3. 操作步骤
登录 fin-accountant → 新建任务 → TaskConfig(model=glm-5.2 / exec_mode=craft / 绑 template agent starexploration-fin-01-invoice-accounting / 勾技能 starexploration-finance-erp-crm-query) → 粘贴 composer → 提交。

| template_agent_id | skill | RAG | model | exec_mode | scope |
|---|---|---|---|---|---|
| fdbda49c-c8bf-45f3-b080-faca64cff369 | starexploration-finance-erp-crm-query | 财务核算与票据规则库 | glm-5.2 | craft | dept(finance) |

**Composer**：
```
做票据识别审核与智能核算：查发票 INV202607001 关联凭证 BV-SE-2026-0701 对账，应收 REC- 与应付 SEAP- 差异闭环，列出逾期风险。
```

## 4. 期望输出
- 6 trace（template:true / rag vector hits>0 财务核算与票据规则库 / memory.load / ontology 34 / data_interface / memory.extract）
- tool_call 调 `listVouchers`(BV-SE-) / `listPayables`(SEAP-) / `listReceivables`(INV202607001) / `listSalesOrders`(CT-SE-)，跨 ERP/CRM 对账
- 多段文本：①票据审核结果 ②跨系统对账表 ③财务风险预警
- 可选 generate_docx

## 5. 故障排查
- LLM 无文本 latency ~800ms：`insufficient_quota` 429（A3/环境）
- 对账 404：发票 INV- 与凭证 BV-SE- 按 invoice_no 关联（INV202607001↔BV-SE-2026-0701），勿直传异构码（A7）
- RAG keyword_fallback：embedding key 未生效（A3）

## 6. 手工 curl 复现
```bash
BASE=http://127.0.0.1:8000; AGENT=fdbda49c-c8bf-45f3-b080-faca64cff369
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starexploration","username":"fin-accountant","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"FIN-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"做票据识别审核与智能核算：查发票 INV202607001 关联凭证 BV-SE-2026-0701 对账，应收 REC- 与应付 SEAP- 差异闭环，列出逾期风险。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace
- [ ] tool_call 用真实码（INV202607001/BV-SE-2026-0701/SEAP202607001/CT-SE-001），跨 ERP/CRM 对账无 404
- [ ] RAG vector 非 keyword_fallback
- [ ] 多段文本 + 可选 docx + 重跑稳定
