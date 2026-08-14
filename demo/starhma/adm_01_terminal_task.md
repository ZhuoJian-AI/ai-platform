# ADM-01 跨系统经营数据汇总

## 1. 演示身份
- 组织 slug：`starhma`（星途热熔胶）
- 登录用户：`admin-officer` / 口令 `12345678`（综合管理部·企管行政组，role=member）
- 终端登录：`/starhma/terminal/login`
- template_agent_id：`269c904a-9a0b-4f35-81e1-2522e90989bf`（slug `starhma-adm-01-bi-summary`）

## 2. 前置条件
- docker compose 起 pg/redis/backend/mock；mock 网关 :8010 含 frm/pcm/qas（已重启加载）
- 5 个 seed 按序跑完（org → mock_connectors → ontology → rag → agents）
- provider 真 key 已从 agileac 复制（A3）；backend 已注入 mock 包（A1）

## 3. 操作步骤
1. 浏览器登录 `/starhma/terminal/login`（用户 admin-officer）
2. 新建任务，标题「跨系统经营数据汇总」
3. TaskConfigDrawer：model=`glm-5.2` / exec_mode=`craft` / 绑定 template agent `starhma-adm-01-bi-summary` / 勾选归口技能 `starhma-admin-erp-crm-mes-query`
4. 黏贴 composer（见下）→ 提交，观察 SSE 流
5. 资源注入表：

| template_agent_id | skill_slug | RAG collection | model_alias | exec_mode | scope |
|---|---|---|---|---|---|
| 269c904a-9a0b-4f35-81e1-2522e90989bf | starhma-admin-erp-crm-mes-query | starhma-admin-bi-kb | glm-5.2 | craft | dept(admin) |

**Composer（L1 短问题，不含编排/场景代号）**：
```
做跨系统经营数据汇总：汇总 ERP 营收/采购/库存、CRM 订单/客户/回款、MES 产能/工单，生成经营简报（营收/产能/订单/客户统计+应收应付对账 INV↔BV-HMA-）。
```

## 4. 期望输出
- 6 trace（template:true / rag vector starhma-admin-bi-kb / memory.load / ontology / data_interface / memory.extract）
- tool_call 调 ERP `listVouchers`(BV-HMA-) / `listPayables`(HMAAP) / `listInventory` / `listProductionCosts`(PC-HMA-) / `listCostCenters` / CRM `listSalesOrders` / `listCustomers` / `listReceivables`(HMAAR) / `listComplaints` / MES `listWorkOrders` / `listShiftOutputs` / `listProductionOrders`，args 用真实码
- 多段文本：①ERP 经营面（营收/采购/库存/应付 HMAAP/凭证 BV-HMA-）②CRM 销售面（订单/客户/回款 HMAAR/客诉）③MES 产能面（工单/批次/产线 OEE）④经营简报（关键指标+应收应付对账 INV↔BV-HMA-）
- 跨系统闭环：CRM INV202607001 ↔ ERP BV-HMA-2026-0701（invoice_no 对账）；CRM CT-HMA- ↔ ERP PC-HMA-（work_order_no）

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：path 参数用真实码（INV202607001/BV-HMA-2026-0701/CT-HMA-001/PC-HMA-），见 A7/A8
- RAG keyword_fallback：embedding 真 key 未生效（A3）

## 6. 附：手工调 API 复现
```bash
BASE=http://127.0.0.1:8000
AGENT=269c904a-9a0b-4f35-81e1-2522e90989bf
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starhma","username":"admin-officer","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"ADM-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"做跨系统经营数据汇总：汇总 ERP 营收/采购/库存、CRM 订单/客户/回款、MES 产能/工单，生成经营简报（营收/产能/订单/客户统计+应收应付对账 INV↔BV-HMA-）。","stream":true}'
```

## 7. 验收要点
- [ ] `template:true` + 6 trace
- [ ] tool_call args 真实码（INV202607001/BV-HMA-2026-0701/CT-HMA-001/PC-HMA-），CRM↔ERP↔MES 闭环无 404
- [ ] RAG vector 非 keyword_fallback
- [ ] 多段文本上屏（ERP/CRM/MES/经营简报+对账）
- [ ] 第二次重跑稳定
