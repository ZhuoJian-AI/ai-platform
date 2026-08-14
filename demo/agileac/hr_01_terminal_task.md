# HR-01 招聘培训薪酬一体化 · 终端任务演示

> HR 部招聘专员 `hr-recruiter`（招聘子任务）/ 培训专员 `hr-trainer`（培训制度子任务）/ 薪酬专员 `hr-compensation`（薪酬子任务）登录终端，新建任务、配置 `glm-5.2` + `craft`、`/agileac-hr-hrm-query` 选技能、写提示词、运行，agent 自主多轮调 HRM `listRecruitments`/`listResumesByPosition`/`listPayrolls`/`listPerformances` + 检索「岗位JD与简历评估库」/ 组织级「员工综合知识库」，输出简历评估排序 + 面试题 + 到岗催办（招聘），或制度问答答案 + 引用源（培训制度），或薪酬报表（薪酬）。
>
> **员工 vibe working 视角**：招聘专员原本要翻简历库、对照 JD 手工打分排序；培训专员答员工制度问题要翻制度文档；薪酬专员要翻 HRM 薪酬 + ERP 凭证核对——现在一句话拿到简历评估短名单 + 面试题，或制度答案 + 引用源，或薪酬报表。AI 是 HR 专员的副驾驶。
>
> 本场景验证 **痛点 A3 简历筛选 + A 制度问答 + B 薪酬报表 + E 到岗催办**——三子任务按归口员工切换，RAG 按 scope 切换（招聘用 team 级 JD 库，培训制度用 org 级员工综合库 auto-load）。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 敏睿空调（slug = `agileac`） |
| 用户名 | `hr-recruiter`（招聘）/ `hr-trainer`（培训制度）/ `hr-compensation`（薪酬） |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |
| 部门 | HR 部 · 招聘组 `hr-recruiting` / 培训组 `hr-training` / 薪酬组 `hr-compensation` |

> 三子任务同属 HR 部，技能同源（部门级 `agileac-hr-hrm-query`，HRM 员工/部门/岗位/考勤/请假/薪酬/绩效/招聘/简历/会议只读）；RAG 主绑 team 级「岗位JD与简历评估库」（team: hr-recruiting，招聘子任务用），培训制度子任务走组织级「员工综合知识库」auto-load（含 HR 制度摘要）。按子任务切归口员工验证组级 scope 隔离。

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）+ `ai_infra_postgres` 容器在跑。
2. **数据已 seed**（按 `README.md` §9 顺序执行）：
   - `seed_agileac_org.py`（含 `hr-recruiter` / `hr-trainer` / `hr-compensation` 用户 + HR 部 + 三组）
   - mock 6 系统 agileac tenant 数据已内置，含 HRM 员工 AGOF/AGSA + 招聘需求 AGRC + 简历 AGRM + 薪酬 AGPR + 绩效；mock 容器重启即生效
   - `seed_agileac_mock_connectors.py`（含部门级技能 `agileac-hr-hrm-query`，HRM 13 端点：listEmployees/getEmployee/listDepartments/getDepartment/listPositions/listAttendance/listLeaves/listPayrolls/listPerformances/listRecruitments/listResumesByPosition/listMeetings；注 `shortlistResumes` 为 POST 不绑定，简历筛选用 listResumesByPosition）
   - `seed_agileac_ontology.py`（组织级 HRM `identifiers.md`——员工 AGSA/AGOF、招聘需求 AGRC、简历 AGRM、岗位 P-（与 PLM 款号 P-RC-/P-CC- 共享 P- 前缀按第二段区分）、部门 PD-、薪酬 AGPR）
   - `seed_agileac_rag.py`（含 team 级「岗位JD与简历评估库」12 部门典型岗位 JD + 胜任力 + 面试题库 + 5 维度评估规则；组织级「员工综合知识库」含 HR 制度摘要）
   - `seed_agileac_agents.py`（含 `agileac-hr-01-hr-ops` agent 模板配置，四层架构 system_prompt）
3. **glm-5.2 已可用**：自检 `GET /api/v1/terminal/models`（hr-recruiter token）应含 `glm-5.2`。
4. **三账号已存在且 active**：
   ```bash
   docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
     "SELECT username, is_active FROM users WHERE username IN ('hr-recruiter','hr-trainer','hr-compensation');"
   ```
5. **HRM mock 端点正常**：
   ```bash
   curl -s "http://localhost:8010/hrm/recruitments" -H "X-API-Key: hrm-agileac-demo-key" | head
   curl -s "http://localhost:8010/hrm/resumes" -H "X-API-Key: hrm-agileac-demo-key" | head
   curl -s "http://localhost:8010/hrm/payrolls" -H "X-API-Key: hrm-agileac-demo-key" | head
   curl -s "http://localhost:8010/hrm/performances" -H "X-API-Key: hrm-agileac-demo-key" | head
   ```
   均应返回 JSON 列表。

> ⚠️ HR-01 关键依赖：HRM `listRecruitments`/`listResumesByPosition`（招聘）+ RAG「岗位JD与简历评估库」（JD + 5 维度评估规则 + 面试题库）；培训制度走组织级「员工综合知识库」auto-load（agent 显式主绑 team 级 JD 库，制度问答靠 org 级库 auto-load）；HRM `listPayrolls`/`listPerformances`（薪酬）。**薪酬凭证核对在 FIN-01 侧对账**（本场景技能仅绑 HRM 不直查 ERP 凭证，凭证号 BV-AG- 作交叉提示）。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问 `http://localhost:8000/agileac/terminal/login`：
- 招聘子任务：用户名 `hr-recruiter`
- 培训制度子任务：用户名 `hr-trainer`
- 薪酬子任务：用户名 `hr-compensation`

密码 `12345678`。左上角应显示「人力资源部」。

### 3.2 新建任务

点左栏「New Task / 新建任务」进入任务编辑器。

### 3.3 配置任务（TaskConfigDrawer）

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `hr-recruiter` / `hr-trainer` / `hr-compensation`（个人工作区） | 干净；记忆按四级自动载入 |
| Model | **`glm-5.2`** | 真实模型 id |
| Exec Mode | **`craft`** | 招聘/薪酬子任务需多轮 HRM + RAG + generate_docx；培训制度可单轮 |
| 场景模板 | `agileac-hr-01-hr-ops` | **必绑**——三子任务切分/5 维度评估规则/输出骨架由模板承载 |

> 若 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id`。
>
> **本体 / 记忆不在 drawer 配置**——按用户 scope 自动注入：招聘子任务主绑 team 级「岗位JD与简历评估库」；培训制度子任务靠组织级「员工综合知识库」auto-load。

### 3.4 在输入框写提示词 + /-mention 选择技能

敲 `/` 弹技能菜单，输入 `hr` 过滤，选中 **`agileac-hr-hrm-query`**。

**招聘子任务**提示词（`hr-recruiter` 登录，直接复制，约 50 字——**纯业务请求，不带编排/端点指令**）：

```
对敏睿空调售后工程师岗位 P-SVC 做简历评估，输出匹配度排序、推荐短名单、面试题与到岗催办。

/agileac-hr-hrm-query
```

**培训制度子任务**提示词（`hr-trainer` 登录，直接复制，约 20 字——纯员工问题）：

```
员工问：年假怎么请，跨年怎么清零？

/agileac-hr-hrm-query
```

**薪酬子任务**提示词（`hr-compensation` 登录，直接复制，约 30 字）：

```
出敏睿空调 2026-06 期薪酬报表，按部门汇总应发/扣减/实发。

/agileac-hr-hrm-query
```

> **四层架构**：user composer 只写**业务目标 + 岗位/期间/问题 + 技能 chip**。三子任务切分、5 维度评估规则（学历15%/经验25%/行业25%/技能25%/软技能10%）、面试题模板（3通用+5专业+2案例）、制度问答引用源规则、薪酬报表结构——**全部由 Agent 模板 `agileac-hr-01-hr-ops` 的 `system_prompt` 承载**。任务 config 必须绑定 `template_agent_id`。
>
> ⚠️ **关键 1**：`/agileac-hr-hrm-query` 必须从 `/` 菜单选 chip。
> ⚠️ **关键 2**：提示词只写岗位/期间/问题，不写"调 HRM 简历再查 JD 库"这类编排——子任务切分与评估规则全由模板驱动。
> ⚠️ **关键 3**：本体 identifiers.md 已写明岗位 P-（与 PLM 款号 P-RC-/P-CC- 共享 P- 前缀，按第二段区分）、招聘需求 AGRC、简历 AGRM、薪酬 AGPR，按需选最少端点集。

#### 资源注入机制（任务运行时自动完成）

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | 按 scope 注入（组织级 HRM identifiers） | 若干 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` | HRM 1 system / ~13 interfaces |
| **RAG** | agent 主绑 team 级「岗位JD与简历评估库」+ org 级员工综合库 auto-load | 1~2 collections |
| **长期记忆** | 4 级聚合 | 若干 history + facts |
| **技能** | /-mention 解析 + 模板继承 | 1 skill（agileac-hr-hrm-query） |
| **记忆沉淀** | extract_memory 抽取 | 0~3 facts |

### 3.5 提交运行

按回车提交。前端创建任务后 `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}`。

### 3.6 观察 SSE 事件流

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载配置（`template:true`） |
| `[trace]` (template) | 场景模板 `agileac-hr-01-hr-ops` 注入 |
| `[trace]` (memory/load) | 长期记忆载入 |
| `[trace]` (ontology) | 组织本体注入（含 HRM identifiers） |
| `[trace]` (rag) | 招聘子任务命中「岗位JD与简历评估库」；培训制度命中 org 级员工综合库 HR 制度摘要 |
| `[trace]` (data_interface) | 数据接口目录（HRM） |
| `[trace]` (skill) | /-mention 引用 `agileac-hr-hrm-query` |
| `[trace]` (memory/extract) | 记忆沉淀 |
| `[tool_call]` | agent 调 HRM `listRecruitments`/`listResumesByPosition`（招聘）；或 `listPayrolls`/`listPerformances`（薪酬）；培训制度子任务可能仅 RAG 不调端点 |
| `[text]` | LLM 流式输出评估表/答案/薪酬表 |
| `[done]` / `[final]` | 收口 + usage + latency |

> 典型 HR-01 运行约 2–4 分钟（招聘/薪酬多轮 HRM + RAG；培训制度单轮 RAG 主导）。

---

## 4. 期望输出

### 4.1 招聘子任务：简历评估表 + 推荐短名单 + 面试题 + 到岗催办

**简历评估表·岗位 P-SVC**（排名 | 姓名 | 学历 | 经验 | 行业 | 技能 | 软技能 | 综合 | 状态）：

| 排名 | 姓名 | 学历 | 经验 | 行业 | 技能 | 软技能 | 综合 | 状态 |
|---|---|---|---|---|---|---|---|---|
| 1 | 孙售后 | 大专 | 4年 | 空调 | 90% | A | A+ | 推荐初面 |
| 2 | 李维修 | 大专 | 2年 | 家电 | 75% | B+ | B+ | 备选 |

**推荐短名单 top 5** + **面试题**（3 通用 + 5 JD 关键技能如空调不制冷排查/通讯故障/8D 流程 + 2 案例）+ **到岗催办**（招聘需求 AGRC | headcount | 已招 | 催办对象 hr-recruiter + 用人部门负责人）。

> 简历数据来自 HRM `listResumesByPosition`，评分严格按 RAG 5 维度加权（学历15%/经验25%/行业25%/技能25%/软技能10%），等级 A+/A 优先推荐、B+ 备选、B/C 不推荐。

### 4.2 培训制度子任务：问题 + 答案 + 引用源

- 员工问题（原话复述）
- 答案（从组织级「员工综合知识库」HR 制度摘要检索）
- 引用源（文档名 + 版本 + 生效日期，如「差旅报销制度 v3.2（2026-04-01 生效）」）

> 培训制度单问题不必调 `generate_docx`。

### 4.3 薪酬子任务：薪酬报表

| 工号 | 姓名 | 部门 | 基本工资 | 岗位津贴 | 绩效奖金 | 加班/补贴 | 应发 | 扣减 | 实发 |
|---|---|---|---|---|---|---|---|---|---|
| AGOF0001 | 管理员 | IT | 15000 | 3000 | 5000 | 500 | 23500 | 2350 | 21150 |

> 薪酬数据来自 HRM `listPayrolls` + `listPerformances`，按部门汇总应发/扣减/实发；薪酬期凭证号 BV-AG- 作交叉提示（凭证核对在 FIN-01 侧对账）。

### 4.4 .docx 报告附件

招聘/薪酬子任务 agent 调 `generate_docx` 打包成 `敏睿空调_简历评估_YYYYMMDD.docx` / `敏睿空调_薪酬报表_YYYYMMDD.docx`（约 30 KB）；培训制度单问题不必 docx。

### 4.5 SSE trace 事件

| trace | 含义 | 期望实测值 |
|---|---|---|
| `category=template` | 场景模板注入（必出） | slug=agileac-hr-01-hr-ops + chars |
| `category=rag` | 招聘命中 JD 库 / 培训制度命中 org 员工综合库 | JD + 5 维度规则 / HR 制度摘要 chunk |
| `category=ontology` | 组织本体注入 | 含 HRM identifiers |
| `category=data_interface` | 数据接口目录 | HRM 1 system |
| `category=skill` | /-mention 引用技能 | 1 skill |
| `category=memory, subtype=load/extract` | 记忆载入/沉淀 | 若干 facts |

> 6 类 trace 全出。培训制度子任务 `trace rag` 命中 org 级员工综合库 HR 制度摘要（agent 显式主绑 team JD 库 + org 库 auto-load）。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `glm-5.2`
- 智谱 AI provider 未配。修复：管理端配智谱 AI provider + 路由策略 `model_pattern=glm-*`，重跑 `seed_agileac_org.py`。

### 5.2 提示词里 `/agileac-hr-hrm-query` 没被识别
- 必须从 `/` 弹窗选 chip，不能手敲。

### 5.3 `[tool_result FAIL]` HRM 接口调用失败
- mock 网关未起或 API key 不匹配。自检 HRM 端点（见 §2.5）均应返回 JSON。注意 HRM 用 `hrm-agileac-demo-key`。

### 5.4 agent 调 `shortlistResumes` 失败
- 现象：agent 试图调 `shortlistResumes`（POST，筛选简历）失败或端点不在目录。
- 根因：`shortlistResumes` 为 POST 端点，技能 binding 仅绑 GET（见 `seed_agileac_mock_connectors.py` 过滤逻辑），不绑定。
- 影响：**不阻塞**。agent 用 `listResumesByPosition`（GET）取简历后由 LLM 做 5 维度评估排序，输出推荐短名单（文字建议），不写入筛选状态。
- 修复：无需修；如需真写入筛选状态，后续扩绑 POST 端点。

### 5.5 培训制度子任务 trace rag 没命中 HR 制度
- 现象：培训制度问答答案空洞或"未找到"。
- 根因：agent 显式主绑 team 级 JD 库（hr-recruiting），培训制度靠 org 级「员工综合知识库」auto-load；若 org 库未 auto-load 或无 HR 制度摘要 chunk，则命中失败。
- 修复：确认 `seed_agileac_rag.py` 已建 org 级「员工综合知识库」含 HR 制度摘要；自检 `GET /api/v1/terminal/resources`（hr-trainer token）的 `rag_collections` 应含 org 级库。embedding 未配时走 keyword_fallback，含"年假/请假/清零"关键词仍可命中。

### 5.6 薪酬子任务直查 ERP 凭证
- 现象：agent 试图调 ERP `listVouchers`（本场景技能仅绑 HRM 不绑 ERP）失败。
- 根因：HR 技能只绑 HRM，ERP 凭证核对在 FIN-01 侧。
- 修复：模板 system_prompt 已写明"凭证号 BV-AG- 作交叉提示，凭证核对在 FIN-01 侧"；薪酬报表只出 HRM `listPayrolls` 数据。

### 5.7 path 参数端点（`getEmployee`）返回 404
- 现象：`getEmployee(emp_no=...)` 返回 `{emp_no} not found`——path 占位符未替换。
- 影响：**不阻塞闭环**。agent 自主降级到 `listEmployees`（query 端点）。
- 修复（可选）：技能 wrapper 按 OpenAPI path 占位符替换。非阻塞性。

### 5.8 `tool_call` args 全 `{}`
- 根因：`_build_tools`（`app/agents/graph/nodes.py`）manifest 占位 schema 覆盖问题。只要有一条 args 非 `{}`（如 `listResumesByPosition(position_code=...)`）即正常。

### 5.9 memory/extract 抽取 0~3 facts
- 非阻塞；长期记忆跨任务复用弱。

---

## 6. 附：手工调 API 复现

```bash
# 1) 登录拿 user token（招聘子任务用 hr-recruiter，培训制度换 hr-trainer，薪酬换 hr-compensation）
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agileac","username":"hr-recruiter","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 HR Agent 模板 id
TPL_ID=$(docker exec ai_infra_backend python3 -c "
import asyncio, asyncpg
async def m():
    c=await asyncpg.connect('postgresql://ai_infra:ai_infra@postgres:5432/ai_infra')
    r=await c.fetchrow(\"SELECT id FROM agents WHERE slug='agileac-hr-01-hr-ops'\")
    print(r['id']); await c.close()
asyncio.run(m())")

# 3) 创建任务（绑定模板；skill_ids 留空从模板继承，model=glm-5.2）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"HR-01 简历评估\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（招聘子任务短 composer，含 /agileac-hr-hrm-query chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"对敏睿空调售后工程师岗位 P-SVC 做简历评估，输出匹配度排序、推荐短名单、面试题与到岗催办。\\n\\n/agileac-hr-hrm-query\",\"stream\":true}"
```

培训制度/薪酬子任务换 `hr-trainer` / `hr-compensation` 登录 + §3.4 对应提示词。

---

## 7. 验收要点（演示前自检）

- [ ] `hr-recruiter` / `hr-trainer` / `hr-compensation` 能登录 `/agileac/terminal/login`，左上角显示「人力资源部」
- [ ] `GET /api/v1/terminal/resources`（hr-recruiter token）的 `skills` 含 `agileac-hr-hrm-query`（dept: hr）
- [ ] `rag_collections` 含「岗位JD与简历评估库」（team: hr-recruiting，招聘子任务主绑）+ org 级「员工综合知识库」（培训制度 auto-load）
- [ ] `data_interfaces` 含 HRM `listRecruitments`/`listResumesByPosition`/`listPayrolls`/`listPerformances`
- [ ] `load_config` 事件显示 **`template:true`**
- [ ] `trace category=template` 出现（slug=`agileac-hr-01-hr-ops` + chars）
- [ ] SSE 6 类 trace 出现（rag + memory.load + ontology + data_interface + skill + memory.extract）
- [ ] 招聘子任务 `tool_call` 覆盖 HRM `listRecruitments` + `listResumesByPosition`；薪酬子任务覆盖 `listPayrolls` + `listPerformances`
- [ ] `tool_call` args 不全 `{}`（至少 `listResumesByPosition(position_code=...)` 或 `listPayrolls(period=...)` 要带参）
- [ ] no-guessing：岗位 P-SVC（与 PLM 款号 P-RC-/P-CC- 共享 P- 前缀按第二段区分）；招聘需求 AGRC、简历 AGRM、薪酬 AGPR 用对前缀
- [ ] 招聘子任务输出含简历评估表 + 推荐短名单 + 面试题（3+5+2）+ 到岗催办；培训制度子任务输出含答案 + 引用源（标版本与生效日期）；薪酬子任务输出含薪酬报表
- [ ] 简历评分按 RAG 5 维度加权（学历15%/经验25%/行业25%/技能25%/软技能10%）；薪酬凭证核对在 FIN-01 侧，本场景凭证号作交叉提示
