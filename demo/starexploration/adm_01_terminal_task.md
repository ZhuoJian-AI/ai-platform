# ADM-01 公文生成与会议纪要闭环

## 1. 演示身份
组织 `starexploration` / 用户 `admin-officer` / 口令 `12345678`（综合管理部·公文会议组）/ 终端 `/starexploration/terminal/login` / template_agent_id `788a9132-9bff-4e96-baee-774be4731294`（`starexploration-adm-01-document-meeting`）

## 2. 前置条件
docker compose 起；5 seed 跑完；provider 真 key（A3）；backend 注入 mock 包（A1）。

## 3. 操作步骤
登录 admin-officer → 新建任务 → TaskConfig(glm-5.2 / craft / 绑 template agent starexploration-adm-01-document-meeting / 勾技能 starexploration-admin-hrm-query) → 粘贴 composer。

| template_agent_id | skill | RAG | scope |
|---|---|---|---|
| 788a9132-9bff-4e96-baee-774be4731294 | starexploration-admin-hrm-query | 公文与会议纪要规则库 | dept(admin) |

**Composer**：
```
基于会议纪要 SEMT-20260002 周度经营调度会生成纪要与待办闭环：提取待办事项与责任人 SEOF-，跨部门分发设计院 PD-DES / 安全部 PD-SAF / 保密办 PD-SEC，跟踪任务闭环。
```

## 4. 期望输出
- 6 trace（template:true / rag vector 公文与会议纪要规则库 / memory.load / ontology 34 / data_interface / memory.extract）
- tool_call 调 `listMeetings`(SEMT-20260002) / `listDepartments`(PD-DES/PD-SAF/PD-SEC) / `listEmployees`(SEOF-)
- 多段文本：①会议纪要待办表（事项+责任人 SEOF-+部门 PD-+截止+状态）②公文草稿（纯文本）③任务闭环跟踪

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：会议 SEMT- 关联部门 PD- 与员工 emp_no(SEOF-)，勿把 SEMT- 当 emp_no 传（A7）

## 6. 手工 curl 复现
```bash
BASE=http://127.0.0.1:8000; AGENT=788a9132-9bff-4e96-baee-774be4731294
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starexploration","username":"admin-officer","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"ADM-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"基于会议纪要 SEMT-20260002 周度经营调度会生成纪要与待办闭环：提取待办事项与责任人 SEOF-，跨部门分发设计院 PD-DES / 安全部 PD-SAF / 保密办 PD-SEC，跟踪任务闭环。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace
- [ ] tool_call 真实码（SEMT-20260002/PD-DES/PD-SAF/PD-SEC/SEOF-），待办提取无 404
- [ ] RAG vector 非 keyword_fallback + 多段文本 + 重跑稳定
