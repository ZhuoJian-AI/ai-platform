# QAS-01 售后粘接故障智能诊断

## 1. 演示身份
- 组织 slug：`starhma`（星途热熔胶）
- 登录用户：`qas-engineer` / 口令 `12345678`（品质与技术服务部·品质与售后技术组，role=member）
- 终端登录：`/starhma/terminal/login`
- template_agent_id：`011fa0f8-ef5a-417e-a1a4-881694794c81`（slug `starhma-qas-01-aftersales-diagnose`）

## 2. 前置条件
- docker compose 起 pg/redis/backend/mock；mock 网关 :8010 含 frm/pcm/qas（已重启加载）
- 5 个 seed 按序跑完（org → mock_connectors → ontology → rag → agents）
- provider 真 key 已从 agileac 复制（A3）；backend 已注入 mock 包（A1）

## 3. 操作步骤
1. 浏览器登录 `/starhma/terminal/login`（用户 qas-engineer）
2. 新建任务，标题「售后粘接故障智能诊断」
3. TaskConfigDrawer：model=`glm-5.2` / exec_mode=`craft` / 绑定 template agent `starhma-qas-01-aftersales-diagnose` / 勾选归口技能 `starhma-qas-qas-crm-frm-query`
4. 黏贴 composer（见下）→ 提交，观察 SSE 流
5. 资源注入表：

| template_agent_id | skill_slug | RAG collection | model_alias | exec_mode | scope |
|---|---|---|---|---|---|
| 011fa0f8-ef5a-417e-a1a4-881694794c81 | starhma-qas-qas-crm-frm-query | starhma-qas-aftersales-kb | glm-5.2 | craft | dept(qas) |

**Composer（L1 短问题，不含编排/场景代号）**：
```
对客诉 CC-2026-001 开胶故障做智能诊断：调 diagnoseAfterSalesFault 按现象/基材/工况匹配故障案例 FC-2025-008 与历史客诉，给排查方案与配方 FORM-CUS-001 调整建议。
```

## 4. 期望输出
- 6 trace（template:true / rag vector starhma-qas-aftersales-kb / memory.load / ontology / data_interface / memory.extract）
- tool_call 调 QAS `listCustomerComplaints`/`getCustomerComplaint`(CC-2026-001) / `diagnoseAfterSalesFault`(现象/基材/工况) / `listFailureCases` / `analyzeRootCause` / `listNgRecords` / CRM `getCustomer`(CLI-001) / `listComplaints` / FRM `getFormula`(FORM-CUS-001)，args 用真实码
- 多段文本：①客诉现象解析（开胶+基材+工况）②故障案例匹配（FC-2025-008 相似度+历史客诉）③根因分析（配方/工艺/施工因素）④排查方案与配方 FORM-CUS-001 调整建议
- 跨系统：QAS CC-2026-001 → CRM CLI-001（customer_code）；QAS → FRM FORM-CUS-001（formula_no）

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：path 参数用真实码（CC-2026-001/FC-2025-008/FORM-CUS-001/CLI-001），见 A7/A8
- RAG keyword_fallback：embedding 真 key 未生效（A3）

## 6. 附：手工调 API 复现
```bash
BASE=http://127.0.0.1:8000
AGENT=011fa0f8-ef5a-417e-a1a4-881694794c81
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starhma","username":"qas-engineer","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"QAS-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"对客诉 CC-2026-001 开胶故障做智能诊断：调 diagnoseAfterSalesFault 按现象/基材/工况匹配故障案例 FC-2025-008 与历史客诉，给排查方案与配方 FORM-CUS-001 调整建议。","stream":true}'
```

## 7. 验收要点
- [ ] `template:true` + 6 trace
- [ ] tool_call args 真实码（CC-2026-001/FC-2025-008/FORM-CUS-001/CLI-001），QAS→CRM/FRM 闭环无 404
- [ ] RAG vector 非 keyword_fallback
- [ ] 多段文本上屏（客诉解析/案例匹配/根因分析/排查+配方建议）
- [ ] 第二次重跑稳定
