# HR-01 智能招聘与人岗匹配

## 1. 演示身份
组织 `starexploration` / 用户 `hr-recruiter` / 口令 `12345678`（人力资源部·招聘组）/ 终端 `/starexploration/terminal/login` / template_agent_id `3f9b762c-e9ef-4ff3-8258-75478aff7029`（`starexploration-hr-01-recruitment-matching`）

## 2. 前置条件
docker compose 起；5 seed 跑完；provider 真 key（A3）；backend 注入 mock 包（A1）。

## 3. 操作步骤
登录 hr-recruiter → 新建任务 → TaskConfig(glm-5.2 / craft / 绑 template agent starexploration-hr-01-recruitment-matching / 勾技能 starexploration-hr-hrm-query) → 粘贴 composer。

| template_agent_id | skill | RAG | scope |
|---|---|---|---|
| 3f9b762c-e9ef-4ff3-8258-75478aff7029 | starexploration-hr-hrm-query | 岗位JD与人岗匹配规则库 | team(hr-recruiting) |

**Composer**：
```
对 P-DES 设计师急招需求 ASRC20260000 做人岗匹配：调 listResumesByPosition 查简历 SERM-，按学历/年限/技能标签/评分匹配，输出短名单与录用建议。
```

## 4. 期望输出
- 6 trace（template:true / rag vector 岗位JD与人岗匹配规则库（team scope）/ memory.load / ontology 34 / data_interface / memory.extract）
- tool_call 调 `listRecruitments`(ASRC20260000) / `listResumesByPosition`(position_code=P-DES) / `listPositions`(P-DES) / `listDepartments`(PD-DES)
- 多段文本：①招聘需求概览 ②简历短名单（SERM-+评分+匹配度）③录用建议
- no-guessing：岗位 P- 与 ERP 物料 M- 不同码空间（P-DES vs M-CON-），按 prefix 区分勿互传（A7，同 agilesteel P- 教训）

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：招聘需求 ASRC.position 字段值即岗位码 P-，按 position_code 关联，勿把 ASRC 当 P- 传（A7）

## 6. 手工 curl 复现
```bash
BASE=http://127.0.0.1:8000; AGENT=3f9b762c-e9ef-4ff3-8258-75478aff7029
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starexploration","username":"hr-recruiter","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"HR-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"对 P-DES 设计师急招需求 ASRC20260000 做人岗匹配：调 listResumesByPosition 查简历 SERM-，按学历/年限/技能标签/评分匹配，输出短名单与录用建议。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace（RAG team scope hr-recruiting）
- [ ] tool_call 真实码（ASRC20260000/P-DES/SERM20260001/PD-DES），P- vs M- prefix 区分无 404
- [ ] RAG vector 非 keyword_fallback + 多段文本 + 重跑稳定
