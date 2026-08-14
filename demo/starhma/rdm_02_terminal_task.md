# RDM-02 实验数据分析与报告生成

## 1. 演示身份
- 组织 slug：`starhma`（星途热熔胶）
- 登录用户：`rd-analyst` / 口令 `12345678`（研发中心·应用测试实验室，role=member）
- 终端登录：`/starhma/terminal/login`
- template_agent_id：`fe5e56d7-84cc-426a-920d-a8a17d90be71`（slug `starhma-rdm-02-experiment-report`）

## 2. 前置条件
- docker compose 起 pg/redis/backend/mock；mock 网关 :8010 含 frm/pcm/qas（已重启加载）
- 5 个 seed 按序跑完（org → mock_connectors → ontology → rag → agents）
- provider 真 key 已从 agileac 复制（A3）；backend 已注入 mock 包（A1）

## 3. 操作步骤
1. 浏览器登录 `/starhma/terminal/login`（用户 rd-analyst）
2. 新建任务，标题「实验数据分析与报告生成」
3. TaskConfigDrawer：model=`glm-5.2` / exec_mode=`craft` / 绑定 template agent `starhma-rdm-02-experiment-report` / 勾选归口技能 `starhma-rd-lab-frm-query`
4. 粘贴 composer（见下）→ 提交，观察 SSE 流
5. 资源注入表：

| template_agent_id | skill_slug | RAG collection | model_alias | exec_mode | scope |
|---|---|---|---|---|---|
| fe5e56d7-84cc-426a-920d-a8a17d90be71 | starhma-rd-lab-frm-query | starhma-rd-experiment-kb | glm-5.2 | craft | dept(rd) |

**Composer（L1 短问题，不含编排/场景代号）**：
```
对配方 FORM-CUS-002 做实验数据分析与报告生成：分析流变实验 EXP-RHE-001 与拉力实验 EXP-TEN-001 数据、识别异常、关联失效记录 FR-2025-021，生成标准化实验报告。
```

## 4. 期望输出
- 6 trace（template:true / rag vector starhma-rd-experiment-kb / memory.load / ontology / data_interface / memory.extract）
- tool_call 调 `getFormula`(FORM-CUS-002) / `listExperiments` / `getExperiment`(EXP-RHE-001/EXP-TEN-001) / `analyzeExperimentData`(EXP-RHE-001) / `generateExperimentReport` / `listFailureRecords`(FR-2025-021)，args 用真实码
- 多段文本：①实验数据汇总（流变/拉力曲线特征值）②异常识别（数据点+可能原因）③失效记录关联（FR-2025-021 现象对照）④标准化实验报告（结论+建议）

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：path 参数用真实码（EXP-RHE-001/EXP-TEN-001/FR-2025-021），见 A7/A8
- RAG keyword_fallback：embedding 真 key 未生效（A3）

## 6. 附：手工调 API 复现
```bash
BASE=http://127.0.0.1:8000
AGENT=fe5e56d7-84cc-426a-920d-a8a17d90be71
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starhma","username":"rd-analyst","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"RDM-02\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"对配方 FORM-CUS-002 做实验数据分析与报告生成：分析流变实验 EXP-RHE-001 与拉力实验 EXP-TEN-001 数据、识别异常、关联失效记录 FR-2025-021，生成标准化实验报告。","stream":true}'
```

## 7. 验收要点
- [ ] `template:true` + 6 trace
- [ ] tool_call args 真实码（FORM-CUS-002/EXP-RHE-001/EXP-TEN-001/FR-2025-021），no-guessing 精确命中无 404
- [ ] RAG vector 非 keyword_fallback
- [ ] 多段文本上屏（实验数据/异常识别/失效关联/标准化报告）
- [ ] 第二次重跑稳定
