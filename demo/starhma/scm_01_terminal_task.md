# SCM-01 库存智能预警与补货建议

## 1. 演示身份
- 组织 slug：`starhma`（星途热熔胶）
- 登录用户：`scm-manager` / 口令 `12345678`（供应链部·采购仓储组，role=member）
- 终端登录：`/starhma/terminal/login`
- template_agent_id：`31065753-d025-44a4-8d7d-3fd48d5a0864`（slug `starhma-scm-01-inventory-replenish`）

## 2. 前置条件
- docker compose 起 pg/redis/backend/mock；mock 网关 :8010 含 frm/pcm/qas（已重启加载）
- 5 个 seed 按序跑完（org → mock_connectors → ontology → rag → agents）
- provider 真 key 已从 agileac 复制（A3）；backend 已注入 mock 包（A1）

## 3. 操作步骤
1. 浏览器登录 `/starhma/terminal/login`（用户 scm-manager）
2. 新建任务，标题「库存智能预警与补货建议」
3. TaskConfigDrawer：model=`glm-5.2` / exec_mode=`craft` / 绑定 template agent `starhma-scm-01-inventory-replenish` / 勾选归口技能 `starhma-scm-erp-crm-query`
4. 黏贴 composer（见下）→ 提交，观察 SSE 流
5. 资源注入表：

| template_agent_id | skill_slug | RAG collection | model_alias | exec_mode | scope |
|---|---|---|---|---|---|
| 31065753-d025-44a4-8d7d-3fd48d5a0864 | starhma-scm-erp-crm-query | starhma-scm-inventory-kb | glm-5.2 | craft | dept(scm) |

**Composer（L1 短问题，不含编排/场景代号）**：
```
做库存智能预警与补货建议：查 ERP 原料 M-RES-001/M-TK-002/M-AO-001 与成品 M-FG-002 库存对比安全库存，列低库存预警与补货建议，联动采购单 POHMA 与销售预测。
```

## 4. 期望输出
- 6 trace（template:true / rag vector starhma-scm-inventory-kb / memory.load / ontology / data_interface / memory.extract）
- tool_call 调 ERP `listInventory`(M-RES-001/M-TK-002/M-AO-001/M-FG-002) / `listMaterials` / `listPurchaseOrders`(POHMA) / `listStockMovements` / `listWarehouses` / `listSuppliers` / CRM `listSalesOrders`，args 用真实码
- 多段文本：①库存现状表（物料/当前库存/安全库存/缺口）②低库存预警清单（优先级）③补货建议（采购量/供应商/到货建议日）④联动销售预测与采购单 POHMA 状态
- 跨系统：ERP 物料 M- ↔ CRM 销售预测（销售订单驱动补货）

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：path 参数用真实码（M-RES-001/M-TK-002/M-AO-001/M-FG-002/POHMA），见 A7/A8
- RAG keyword_fallback：embedding 真 key 未生效（A3）

## 6. 附：手工调 API 复现
```bash
BASE=http://127.0.0.1:8000
AGENT=31065753-d025-44a4-8d7d-3fd48d5a0864
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starhma","username":"scm-manager","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"SCM-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"做库存智能预警与补货建议：查 ERP 原料 M-RES-001/M-TK-002/M-AO-001 与成品 M-FG-002 库存对比安全库存，列低库存预警与补货建议，联动采购单 POHMA 与销售预测。","stream":true}'
```

## 7. 验收要点
- [ ] `template:true` + 6 trace
- [ ] tool_call args 真实码（M-RES-001/M-TK-002/M-AO-001/M-FG-002/POHMA），ERP↔CRM 闭环无 404
- [ ] RAG vector 非 keyword_fallback
- [ ] 多段文本上屏（库存表/预警清单/补货建议/销售联动）
- [ ] 第二次重跑稳定
