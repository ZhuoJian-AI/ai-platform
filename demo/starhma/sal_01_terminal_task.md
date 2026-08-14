# SAL-01 智能询盘与初步粘接方案

## 1. 演示身份
- 组织 slug：`starhma`（星途热熔胶）
- 登录用户：`sales-rep` / 口令 `12345678`（营销销售中心·国内销售+技术销售组，role=member）
- 终端登录：`/starhma/terminal/login`
- template_agent_id：`911847f5-57a3-43f5-8d5b-b98b92918e21`（slug `starhma-sal-01-inquiry-solution`）

## 2. 前置条件
- docker compose 起 pg/redis/backend/mock；mock 网关 :8010 含 frm/pcm/qas（已重启加载）
- 5 个 seed 按序跑完（org → mock_connectors → ontology → rag → agents）
- provider 真 key 已从 agileac 复制（A3）；backend 已注入 mock 包（A1）

## 3. 操作步骤
1. 浏览器登录 `/starhma/terminal/login`（用户 sales-rep）
2. 新建任务，标题「智能询盘与初步粘接方案」
3. TaskConfigDrawer：model=`glm-5.2` / exec_mode=`craft` / 绑定 template agent `starhma-sal-01-inquiry-solution` / 勾选归口技能 `starhma-sales-crm-frm-erp-query`
4. 粘贴 composer（见下）→ 提交，观察 SSE 流
5. 资源注入表：

| template_agent_id | skill_slug | RAG collection | model_alias | exec_mode | scope |
|---|---|---|---|---|---|
| 911847f5-57a3-43f5-8d5b-b98b92918e21 | starhma-sales-crm-frm-erp-query | starhma-sales-kb | glm-5.2 | craft | dept(sales) |

**Composer（L1 短问题，不含编排/场景代号）**：
```
对询盘 INQ-002 医疗用品客户做智能询盘：解析基材/工况需求、匹配配方 FORM-CUS-002、生成初步粘接方案与报价、联动样品 SMP-2026-002。
```

## 4. 期望输出
- 6 trace（template:true / rag vector starhma-sales-kb / memory.load / ontology / data_interface / memory.extract）
- tool_call 调 CRM `listOpportunities`/`getOpportunity`(INQ-002) / `listQuotations` / `getCustomer` / FRM `recommendFormula`(需求参数) / `getFormula`(FORM-CUS-002) / ERP `listMaterials`，args 用真实码
- 多段文本：①询盘需求解析（基材/工况/性能/认证）②配方匹配与推荐（FORM-CUS-002 + 推荐理由）③初步粘接方案（施胶参数/工艺建议）④报价单与样品 SMP-2026-002 联动
- 跨系统：CRM 询盘 INQ-002 → FRM 配方 FORM-CUS-002 → ERP 物料 M-FG-/M-RES- cost，闭环

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：path 参数用真实码（INQ-002/FORM-CUS-002/SMP-2026-002），见 A7/A8
- RAG keyword_fallback：embedding 真 key 未生效（A3）

## 6. 附：手工调 API 复现
```bash
BASE=http://127.0.0.1:8000
AGENT=911847f5-57a3-43f5-8d5b-b98b92918e21
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starhma","username":"sales-rep","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"SAL-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"对询盘 INQ-002 医疗用品客户做智能询盘：解析基材/工况需求、匹配配方 FORM-CUS-002、生成初步粘接方案与报价、联动样品 SMP-2026-002。","stream":true}'
```

## 7. 验收要点
- [ ] `template:true` + 6 trace
- [ ] tool_call args 真实码（INQ-002/FORM-CUS-002/SMP-2026-002），跨系统 CRM→FRM→ERP 闭环无 404
- [ ] RAG vector 非 keyword_fallback
- [ ] 多段文本上屏（询盘解析/配方匹配/粘接方案/报价+样品）
- [ ] 第二次重跑稳定
