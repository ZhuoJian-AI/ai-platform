# QTO-01 智能算量与造价测算

## 1. 演示身份
组织 `starexploration` / 用户 `cost-estimator` / 口令 `12345678`（造价技经部·造价测算组）/ 终端 `/starexploration/terminal/login` / template_agent_id `5f8d0103-eec8-4329-888d-495bff80f642`（`starexploration-qto-01-quantity-cost`）

## 2. 前置条件
docker compose 起；5 seed 跑完；provider 真 key（A3）；backend 注入 mock 包（A1）。

## 3. 操作步骤
登录 cost-estimator → 新建任务 → TaskConfig(glm-5.2 / craft / 绑 template agent starexploration-qto-01-quantity-cost / 勾技能 starexploration-cost-des-erp-query) → 粘贴 composer。

| template_agent_id | skill | RAG | scope |
|---|---|---|---|
| 5f8d0103-eec8-4329-888d-495bff80f642 | starexploration-cost-des-erp-query | 工程算量与造价规则库 | dept(cost) |

**Composer**：
```
按 SCH-IND-001 方案做智能算量与造价测算：聚合算量项 QTI-CON-/QTI-STE-，联动 ERP 物料 M-CON-001/M-STE-001 查单价（prefix 转换），输出造价与成本偏差。
```

## 4. 期望输出
- 6 trace（template:true / rag vector 工程算量与造价规则库 / memory.load / ontology 34 / data_interface / memory.extract）
- tool_call 调 `computeQuantityTakeoff`(SCH-IND-001) / `listQuantityItems`(QTI-CON-) / `listMaterials`(M-CON-001) / `listCostCenters`(CC-IND-001) / `listProductionCosts`(PC-SE-)
- 多段文本：①算量汇总表 ②造价测算表 ③成本偏差分析
- 关键 no-guessing：QTI-CON-→M-CON- prefix 转换（A7）

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：算量项 QTI- 与物料 M- 按 material_code 关联需 prefix 转换，勿直传 QTI- 给 ERP（A7）；项目成本 PC-SE-.heat_no 承载 PRJ-，勿当 PRJ- 传 EPC

## 6. 手工 curl 复现
```bash
BASE=http://127.0.0.1:8000; AGENT=5f8d0103-eec8-4329-888d-495bff80f642
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starexploration","username":"cost-estimator","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"QTO-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"按 SCH-IND-001 方案做智能算量与造价测算：聚合算量项 QTI-CON-/QTI-STE-，联动 ERP 物料 M-CON-001/M-STE-001 查单价（prefix 转换），输出造价与成本偏差。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace
- [ ] tool_call 真实码（SCH-IND-001/QTI-CON-001/M-CON-001/CC-IND-001/PC-SE-），prefix 转换正确无 404
- [ ] RAG vector 非 keyword_fallback + 多段文本 + 重跑稳定
