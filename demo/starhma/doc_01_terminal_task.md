# DOC-01 文档智能处理与检索

## 1. 演示身份
- 组织 slug：`starhma`（星途热熔胶）
- 登录用户：`doc-clerk` / 口令 `12345678`（综合管理部·文档资质组，role=member）
- 终端登录：`/starhma/terminal/login`
- template_agent_id：`3c14d454-8f08-4e70-a613-83c14387036c`（slug `starhma-doc-01-doc-retrieval`）

## 2. 前置条件
- docker compose 起 pg/redis/backend/mock；mock 网关 :8010 含 frm/pcm/qas（已重启加载）
- 5 个 seed 按序跑完（org → mock_connectors → ontology → rag → agents）
- provider 真 key 已从 agileac 复制（A3）；backend 已注入 mock 包（A1）

## 3. 操作步骤
1. 浏览器登录 `/starhma/terminal/login`（用户 doc-clerk）
2. 新建任务，标题「文档智能处理与检索」
3. TaskConfigDrawer：model=`glm-5.2` / exec_mode=`craft` / 绑定 template agent `starhma-doc-01-doc-retrieval` / 勾选归口技能 `starhma-admin-doc-erp-crm-query`
4. 黏贴 composer（见下）→ 提交，观察 SSE 流
5. 资源注入表：

| template_agent_id | skill_slug | RAG collection | model_alias | exec_mode | scope |
|---|---|---|---|---|---|
| 3c14d454-8f08-4e70-a613-83c14387036c | starhma-admin-doc-erp-crm-query | starhma-admin-doc-kb | glm-5.2 | craft | dept(admin) |

**Composer（L1 短问题，不含编排/场景代号）**：
```
做文档智能处理与检索：检索合同 CT-HMA-001/002 与采购单 POHMA、凭证 BV-HMA- 的关键条款/摘要，提取付款里程碑与风险点，生成文档摘要。
```

## 4. 期望输出
- 6 trace（template:true / rag vector starhma-admin-doc-kb / memory.load / ontology / data_interface / memory.extract）
- tool_call 调 ERP `listPurchaseOrders`(POHMA) / `getPurchaseOrder` / `listVouchers`(BV-HMA-) / `listCostCenters` / CRM `listSalesOrders` / `getCustomer` / `listCustomers`，args 用真实码
- 多段文本：①合同 CT-HMA-001/002 关键条款（标的/金额/付款里程碑/违约/保密）②采购单 POHMA 摘要（供应商/物料/金额/到货）③凭证 BV-HMA- 关键信息（发票号/金额/对账状态）④付款里程碑与风险点汇总
- 跨系统：CRM CT-HMA- ↔ ERP PC-HMA-（work_order_no）；ERP BV-HMA- ↔ CRM INV（invoice_no）

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：path 参数用真实码（CT-HMA-001/CT-HMA-002/POHMA/BV-HMA-），见 A7/A8
- RAG keyword_fallback：embedding 真 key 未生效（A3）

## 6. 附：手工调 API 复现
```bash
BASE=http://127.0.0.1:8000
AGENT=3c14d454-8f08-4e70-a613-83c14387036c
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starhma","username":"doc-clerk","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"DOC-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"做文档智能处理与检索：检索合同 CT-HMA-001/002 与采购单 POHMA、凭证 BV-HMA- 的关键条款/摘要，提取付款里程碑与风险点，生成文档摘要。","stream":true}'
```

## 7. 验收要点
- [ ] `template:true` + 6 trace
- [ ] tool_call args 真实码（CT-HMA-001/CT-HMA-002/POHMA/BV-HMA-），CRM↔ERP 闭环无 404
- [ ] RAG vector 非 keyword_fallback
- [ ] 多段文本上屏（合同条款/采购摘要/凭证信息/付款里程碑+风险）
- [ ] 第二次重跑稳定
