# SAF-01 施工现场安全隐患智能识别

## 1. 演示身份
组织 `starexploration` / 用户 `saf-inspector` / 口令 `12345678`（安全生产部·安全巡检组）/ 终端 `/starexploration/terminal/login` / template_agent_id `4ee432cc-3376-4af8-bcf0-8953a797e17d`（`starexploration-saf-01-site-hazard`）

## 2. 前置条件
docker compose 起；5 seed 跑完；provider 真 key（A3）；backend 注入 mock 包（A1）。

## 3. 操作步骤
登录 saf-inspector → 新建任务 → TaskConfig(glm-5.2 / craft / 绑 template agent starexploration-saf-01-site-hazard / 勾技能 starexploration-safety-epc-query) → 粘贴 composer。

| template_agent_id | skill | RAG | scope |
|---|---|---|---|
| 4ee432cc-3376-4af8-bcf0-8953a797e17d | starexploration-safety-epc-query | 现场安全监管与巡检规则库 | dept(safety) |

**Composer**：
```
对 PRJ-IND-001 项目做现场安全隐患识别：摄像头 C07 画面『3 名作业人员未戴安全帽通过 2#塔吊下方作业区』，调 detectSiteHazard 识别隐患 HAZ- 与整改工单 RO-，闭环整改。
```

## 4. 期望输出
- 6 trace（template:true / rag vector 现场安全监管与巡检规则库 / memory.load / ontology 34 / data_interface / memory.extract）
- tool_call 调 `listSiteHazards`(PRJ-IND-001) / `detectSiteHazard`(project_code=PRJ-IND-001, sample_desc='摄像头 C07 画面...') / `listScheduleActivities`
- 多段文本：①隐患识别结果 ②整改工单闭环 ③风险分级与管控建议
- 感知类端点 detectSiteHazard：传 sample_desc 文本画面描述，返识别结果+整改工单，**不生成图片/视频**

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：隐患 HAZ- 关联项目 PRJ- 与进度 SCD-，勿把 HAZ- 当 PRJ- 传 EPC（A7）；sample_desc 用文本描述勿传图片

## 6. 手工 curl 复现
```bash
BASE=http://127.0.0.1:8000; AGENT=4ee432cc-3376-4af8-bcf0-8953a797e17d
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starexploration","username":"saf-inspector","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"SAF-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"对 PRJ-IND-001 项目做现场安全隐患识别：摄像头 C07 画面『3 名作业人员未戴安全帽通过 2#塔吊下方作业区』，调 detectSiteHazard 识别隐患 HAZ- 与整改工单 RO-，闭环整改。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace
- [ ] tool_call 真实码（PRJ-IND-001/HAZ-2026-001/RO-2026-001），detectSiteHazard 带 sample_desc（感知类不生成图片）
- [ ] RAG vector 非 keyword_fallback + 多段文本 + 重跑稳定
