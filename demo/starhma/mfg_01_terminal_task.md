# MFG-01 智能排产与订单冲突识别

## 1. 演示身份
- 组织 slug：`starhma`（星途热熔胶）
- 登录用户：`mfg-planner` / 口令 `12345678`（生产制造部·生产排产组，role=member）
- 终端登录：`/starhma/terminal/login`
- template_agent_id：`f881da63-63d9-4d6d-a6ff-71ec404941c8`（slug `starhma-mfg-01-schedule-conflict`）

## 2. 前置条件
- docker compose 起 pg/redis/backend/mock；mock 网关 :8010 含 frm/pcm/qas（已重启加载）
- 5 个 seed 按序跑完（org → mock_connectors → ontology → rag → agents）
- provider 真 key 已从 agileac 复制（A3）；backend 已注入 mock 包（A1）

## 3. 操作步骤
1. 浏览器登录 `/starhma/terminal/login`（用户 mfg-planner）
2. 新建任务，标题「智能排产与订单冲突识别」
3. TaskConfigDrawer：model=`glm-5.2` / exec_mode=`craft` / 绑定 template agent `starhma-mfg-01-schedule-conflict` / 勾选归口技能 `starhma-mfg-mes-pcm-erp-query`
4. 粘贴 composer（见下）→ 提交，观察 SSE 流
5. 资源注入表：

| template_agent_id | skill_slug | RAG collection | model_alias | exec_mode | scope |
|---|---|---|---|---|---|
| f881da63-63d9-4d6d-a6ff-71ec404941c8 | starhma-mfg-mes-pcm-erp-query | starhma-mfg-schedule-kb | glm-5.2 | craft | dept(mfg) |

**Composer（L1 短问题，不含编排/场景代号）**：
```
做智能排产与订单冲突识别：综合 MES 工单 WO202607001..005 交期、产线 LINE-AUTO-01/02 与 LINE-03 负荷、换线成本，调 optimizeProductionSchedule 给排产建议与冲突订单。
```

## 4. 期望输出
- 6 trace（template:true / rag vector starhma-mfg-schedule-kb / memory.load / ontology / data_interface / memory.extract）
- tool_call 调 MES `listWorkOrders`/`getWorkOrder`(WO202607001..005) / `listProductionOrders` / `listShiftOutputs` / `listWip` / PCM `optimizeProductionSchedule`(约束参数) / `listScheduleRules` / `recommendProcessParams` / ERP `listInventory`/`listProductionCosts`，args 用真实码
- 多段文本：①工单与产线负荷表 ②排产建议（推荐顺序/产线分配/时间窗）③冲突订单识别（逾期/换线冲突）④换线成本与优化建议
- 跨系统：PCM 排产 → MES 工单 WO（work_order_no）；PCM → MES LINE-（line）

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：path 参数用真实码（WO202607001/LINE-AUTO-01），见 A7/A8
- RAG keyword_fallback：embedding 真 key 未生效（A3）

## 6. 附：手工调 API 复现
```bash
BASE=http://127.0.0.1:8000
AGENT=f881da63-63d9-4d6d-a6ff-71ec404941c8
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starhma","username":"mfg-planner","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"MFG-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"做智能排产与订单冲突识别：综合 MES 工单 WO202607001..005 交期、产线 LINE-AUTO-01/02 与 LINE-03 负荷、换线成本，调 optimizeProductionSchedule 给排产建议与冲突订单。","stream":true}'
```

## 7. 验收要点
- [ ] `template:true` + 6 trace
- [ ] tool_call args 真实码（WO202607001..005/LINE-AUTO-01/LINE-AUTO-02/LINE-03），PCM→MES 闭环无 404
- [ ] RAG vector 非 keyword_fallback
- [ ] 多段文本上屏（负荷表/排产建议/冲突订单/换线优化）
- [ ] 第二次重跑稳定
