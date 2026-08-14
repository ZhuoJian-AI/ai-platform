# HR-01 招聘人岗匹配与人事事务

> 场景文档（7 节）。归口人力资源部·招聘组（+ 培训与薪酬组），登录用户 `hr-recruiter`。模型 `glm-5.2`，exec_mode `craft`。
> template_agent_id `005f421e-8a18-42f3-aa02-325b34ff5bc4`（`agilestationery-hr-01-recruitment`）。team-scope RAG（岗位JD与人事制度库，team）。

## 1. 演示身份
- 组织 slug：`agilestationery`（敏睿文具）
- 用户名：`hr-recruiter` / 密码：`12345678`（统一）
- 角色：member，部门 hr，团队 hr-recruiting
- template_agent_id：`005f421e-8a18-42f3-aa02-325b34ff5bc4`（`agilestationery-hr-01-recruitment`）

## 2. 前置条件
- 平台 + mock 网关运行（`docker compose up -d`，mock 含 HRM）
- 5 个 seed 已跑（org / mock_connectors / ontology / rag / agents）
- glm-5.2 路由指向 `aliyun-all-openai`（真实 key 由 README §3 从 agileac 复制，A3）
- mock health：`curl -H "X-API-Key: hrm-agilestationery-demo-key" http://localhost:8010/hrm/health`
- 岗位JD与人事制度库（team）已 embedded
- **任务须绑 `workspace_id`**（归口用户个人工作空间，前端自动填；curl 须显式传）否则 generate_docx 不在工具列表、无 docx 落盘（A6）

## 3. 操作步骤
1. 登录 `http://localhost:8000/agilestationery/terminal/login`（hr-recruiter / 12345678）
2. 新建任务
3. TaskConfigDrawer：模型 `glm-5.2` / exec_mode `craft` / 绑定智能体 `招聘人岗匹配与人事事务`
4. composer 提示词（贴入）：

```
对电商运营专员 P-EC 岗位做简历筛选与人岗匹配，招聘需求 ASRC（headcount 2，紧急）。扫该岗位所有简历，按岗位检索岗位JD与人事制度库给 5 维度评估排序 + 推荐短名单 + 面试题 + 到岗催办。

/agilestationery-hr-hrm-query
```

5. 提交运行，观察 SSE

**资源注入表**：

| 项 | 值 |
|---|---|
| template_agent_id | `005f421e-8a18-42f3-aa02-325b34ff5bc4` |
| skill_slug | `agilestationery-hr-hrm-query`（dept scope，归口 hr） |
| RAG collection | 岗位JD与人事制度库（team） |
| model_alias | `glm-5.2` |
| exec_mode | `craft` |
| scope | dept（hr） / RAG 为 team（hr-recruiting） |

## 4. 期望输出
四段分析上屏 + generate_docx：

1. 简历 5 维度评估排序表（排名 | 简历 ASRM20260001 | 学历 | 经验 | 技能 | 软技能 | 综合 | 状态）
2. 推荐短名单（top N + 各人匹配要点与短板）
3. 面试题（3 通用 + 5 专业 + 2 案例）
4. 到岗催办（招聘需求 ASRC | headcount 2 | 已招 | 缺口 | 催办对象）

**SSE trace 表（6 类）**：

| trace 类 | 命中内容 |
|---|---|
| template | `load_config` `template:true`（四段 system_prompt 注入） |
| rag | 岗位JD与人事制度库（team），retriever=vector（非 keyword_fallback） |
| memory | memory.load（+ memory.extract，中文保守 0 facts 非致命，A9） |
| ontology | HRM identifiers.md + object/link/action types（39 文件中相关域） |
| data_interface | HRM，12 bound endpoints（A8 path-param 用真实码） |
| skill | `agilestationery-hr-hrm-query` bound（12 endpoints，args 非空） |

## 5. 故障排查
- model not available → 检查 glm-5.2 路由指向 aliyun-all-openai（README §3，A3）
- skill chip 不识别 → 检查 `agilestationery-hr-hrm-query` 技能已绑（管理端技能页）
- tool_call args `{}` → 检查端点 spec 已导入（mock_connectors seed，A1/A2）
- P-EC vs SKU-ZB- 坑：岗位 P-EC（HRM 电商运营专员）≠ PIM 产品 SKU-ZB-，listResumesByPosition(position='P-EC') ✓，不同码空间（A7）
- ASRC.position ↔ P- 坑：招聘需求 ASRC 的 `position` 引用岗位 P-EC，按 position_code 关联（A7）
- `shortlistResumes` 是 POST 不绑定 → 用 listResumesByPosition + LLM 评估替代（技能仅全 GET）
- 无 docx 落盘 → 任务未绑 workspace_id（A6，前端自动填；curl 须显式传，见 §6）
- `listResumesByPosition(P-EC)` not found → 岗位码写对，path-param 勿用 `{position_code}` 占位符（A8）
- RAG retriever=keyword_fallback → embedding 未通（A3，team 库须 reembed）

## 6. 附：手工调 API 复现
```bash
# 1) 登录取 token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agilestationery","username":"hr-recruiter","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) 创建任务（绑 template_agent_id + 模型 + craft + workspace_id，A6）
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"招聘人岗匹配与人事事务","config":{"template_agent_id":"005f421e-8a18-42f3-aa02-325b34ff5bc4","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft","workspace_id":"<归口用户个人工作空间 id>"}}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "task=$TASK"

# 3) 运行（SSE 流）
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"对电商运营专员 P-EC 岗位做简历筛选与人岗匹配，招聘需求 ASRC（headcount 2，紧急）。扫该岗位所有简历，按岗位检索岗位JD与人事制度库给 5 维度评估排序 + 推荐短名单 + 面试题 + 到岗催办。","stream":true}'
```

## 7. 验收要点
- [ ] `load_config` event `template:true`（模板注入）
- [ ] 6 类 trace：rag（岗位JD与人事制度库 team vector）+ memory.load + ontology（HRM identifiers）+ data_interface（HRM）+ skill + memory.extract
- [ ] `tool_call` args 非全 `{}`（listEmployees/listDepartments/listPositions/listAttendance/listLeaves/listPayrolls/listPerformances/listRecruitments/listResumesByPosition/listMeetings 带真实 P-EC/ASRC/ASRM20260001/EMP-/PD-）
- [ ] no-guessing：岗位 P-EC、招聘需求 ASRC、简历 ASRM、员工 EMP-、部门 PD- 命中正确前缀；P-EC vs SKU-ZB- 不互传（A7）
- [ ] RAG retriever=vector（非 keyword_fallback）
- [ ] 输出含四段（5 维度评估排序 → 短名单 → 面试题 → 到岗催办）+ generate_docx 附件
- [ ] generate_docx 调用 + docx 落盘到 hr-recruiter 工作空间（任务须绑 workspace_id，A6）
- [ ] 同一 prompt 跑 2 次，第二次 text 字符数不暴跌（稳定性）
