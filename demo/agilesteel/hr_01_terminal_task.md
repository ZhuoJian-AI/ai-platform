# HR-01 招聘人岗匹配

> 归口人力资源部·招聘组 + 培训组 + 薪酬组，用户 `hr-recruiter`。glm-5.2 / craft。
> template_agent_id `ff7a8ae4-a7b0-4f15-897c-764736ba740d`（`agilesteel-hr-01-hr-ops`）。team+org 双 RAG（岗位JD库 team + 员工综合库 org）。

## 1. 演示身份
组织 `agilesteel`，用户 `hr-recruiter` / `12345678`，部门 hr，团队 hr-recruiting。

## 2. 前置条件
平台 + mock + 5 seed + glm-5.2 路由。HRM health：`curl -H "X-API-Key: hrm-agilesteel-demo-key" http://localhost:8010/hrm/health`。岗位JD库（team）已 embedded。**任务须绑 `workspace_id`**（归口用户个人工作空间，前端自动填；curl 须显式传）否则 generate_docx 不在工具列表、无 docx 落盘。

## 3. 操作步骤
登录 `/agilesteel/terminal/login` → glm-5.2 / craft / 绑智能体 `招聘人岗匹配` → 贴 composer：

```
对炼钢工程师 P-MELT 岗位做简历筛选与人岗匹配。

/agilesteel-hr-hrm-query
```

## 4. 期望输出（按子任务分段，每段「子任务N·标题」）
- 子任务一·简历筛选与人岗匹配：简历评估表（排名 | 姓名 | 学历 | 经验 | 行业 | 技能 | 软技能 | 综合 | 状态）
- 子任务二·推荐短名单：top 5 + 各人匹配要点与短板
- 子任务三·面试题：3 通用 + 5 专业 + 2 案例
- 子任务四·到岗催办：招聘需求 ASRC | headcount | 已招 | 缺口 | 催办对象
- .docx 附件（generate_docx 落盘到归口用户工作空间）

## 5. 故障排查
- P- vs P-ST- 坑：岗位 P-MELT（炼钢工程师）≠ PLM 钢种 P-ST-Q345B，listResumesByPosition(position='P-MELT') ✓，getSteelGrade('P-ST-') 另码空间
- shortlistResumes 是 POST 不绑定 → 用 listResumesByPosition + LLM 评估替代
- 无 docx 落盘 → 任务未绑 workspace_id（前端自动填；curl 须显式传，见 §6）

## 6. 附：手工调 API 复现
```bash
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug -H "Content-Type: application/json" -d '{"slug":"agilesteel","username":"hr-recruiter","password":"12345678"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"title":"招聘人岗匹配","config":{"template_agent_id":"ff7a8ae4-a7b0-4f15-897c-764736ba740d","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft","workspace_id":"<归口用户个人工作空间 id>"}}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"message":"对炼钢工程师 P-MELT 岗位做简历筛选与人岗匹配。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace（rag=岗位JD库 team + memory + ontology HRM identifiers + data_interface + skill + memory.extract）
- [ ] tool_call：listRecruitments/listResumesByPosition/listPositions/listDepartments，args 带真实 P-MELT/ASRC/ASRM/ASSA
- [ ] 子任务结构可见：子任务一/二/三/四 分段（简历评估 → 短名单 → 面试题 → 到岗催办）
- [ ] generate_docx 调用 + docx 落盘到 hr-recruiter 工作空间（任务须绑 workspace_id）
- [ ] no-guessing：岗位 P-MELT vs 钢种 P-ST- 不互传；员工 ASSA/ASOF、简历 ASRM 前缀正确
