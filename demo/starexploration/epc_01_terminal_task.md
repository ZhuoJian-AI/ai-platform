# EPC-01 项目进度风险预警与成本管控

## 1. 演示身份
组织 `starexploration` / 用户 `epc-manager` / 口令 `12345678`（EPC 总承包部·项目管控组）/ 终端 `/starexploration/terminal/login` / template_agent_id `8164ca06-32c3-4a72-8cca-3468ed5f7634`（`starexploration-epc-01-schedule-cost`）

## 2. 前置条件
docker compose 起；5 seed 跑完；provider 真 key（A3）；backend 注入 mock 包（A1）。

## 3. 操作步骤
登录 epc-manager → 新建任务 → TaskConfig(glm-5.2 / craft / 绑 template agent starexploration-epc-01-schedule-cost / 勾技能 starexploration-epc-epc-erp-query) → 粘贴 composer。

| template_agent_id | skill | RAG | scope |
|---|---|---|---|
| 8164ca06-32c3-4a72-8cca-3468ed5f7634 | starexploration-epc-epc-erp-query | 项目进度与成本管控规则库 | dept(epc) |

**Composer**：
```
对 PRJ-IND-001 电工装备厂房 EPC 项目做进度风险预警与成本管控：查关键路径工序 SCD- 延误、predictScheduleRisk 风险等级、项目成本 PC-SE- 与合同 CT-SE-001 偏差，输出赶工建议。
```

## 4. 期望输出
- 6 trace（template:true / rag vector 项目进度与成本管控规则库 / memory.load / ontology 34 / data_interface / memory.extract）
- tool_call 调 `getProject`(PRJ-IND-001) / `listScheduleActivities`(SCD-) / `predictScheduleRisk`(PRJ-IND-001) / `listProductionCosts`(PC-SE-) / `listCostCenters`(CC-IND-001)
- 多段文本：①进度风险预警表 ②成本管控表 ③关键路径优化建议
- no-guessing：项目成本 PC-SE-.heat_no 承载 PRJ-、work_order_no 引用 CT-SE-、cost_center 对齐 CC-（A7）

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：成本中心 CC- 与项目 PRJ- 按 cost_center_code 对齐，勿把 CC- 当 PRJ- 传 EPC；项目 PRJ- 挂方案 SCH- 按 scheme_no（A7）

## 6. 手工 curl 复现
```bash
BASE=http://127.0.0.1:8000; AGENT=8164ca06-32c3-4a72-8cca-3468ed5f7634
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starexploration","username":"epc-manager","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"EPC-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"对 PRJ-IND-001 电工装备厂房 EPC 项目做进度风险预警与成本管控：查关键路径工序 SCD- 延误、predictScheduleRisk 风险等级、项目成本 PC-SE- 与合同 CT-SE-001 偏差，输出赶工建议。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace
- [ ] tool_call 真实码（PRJ-IND-001/SCD-001/SCD-003/CC-IND-001/PC-SE-），跨 EPC/ERP 无 404
- [ ] RAG vector 非 keyword_fallback + 多段文本 + 重跑稳定
