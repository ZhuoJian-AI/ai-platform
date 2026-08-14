# SAL-02 差旅报销进度问答 · 终端任务演示

> 销售运营员 `sal-ops` 登录终端，新建任务、配置 `glm-5.2` + `craft`、`/agileac-sal-crm-erp-query` 选技能、写一句提示词、运行，agent **先检索员工综合知识库**拿到差旅报销 5 步流程与状态枚举，**再调 ERP `listVouchers(period=2026-07)`** 取该期间凭证、按 summary 含"差旅费报销"定位员工那张单，组合答出"当前在财务复核中（第 4 步）、预计下周二/四打款"。
>
> **员工 vibe working 视角**：员工原本要开 ERP、等登录超时、重登、找凭证、看状态——现在一句话拿到答案。AI 是员工副驾驶，**不对客户直接交互**。
>
> 本场景验证 **痛点 A（智能问答与知识库）** + 「先 RAG 后接口」分工：静态流程/状态枚举走知识库，"我那张单现在到哪步"走活接口。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 敏睿空调（slug = `agileac`） |
| 用户名 | `sal-ops` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |
| 部门 | 销售部 · 销售运营组 |

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）+ `ai_infra_postgres` 容器在跑。
2. **数据已 seed**（按 `README.md` §9 顺序执行）：
   - `seed_agileac_org.py`（含 `sal-ops` 用户 + 销售部 + 销售运营组）
   - mock 6 系统 agileac tenant 数据已内置（`mock/mock/systems/*/data.py` 的 `_build_agileac`），含演示凭证 BV-AG-2026-0512（财务复核中、6800 元、2026-07-08 提交）；mock 容器重启即生效
   - `seed_agileac_mock_connectors.py`（含部门级技能 `agileac-sal-crm-erp-query`，绑 ERP `listVouchers`）
   - `seed_agileac_ontology.py`（33 组织级含 ERP 域 `identifiers.md`——凭证前缀 `BV-AG-`）
   - `seed_agileac_rag.py`（含「员工综合知识库」**组织级** RAG，差旅报销段已内联 5 步流程 + 状态枚举）
   - `seed_agileac_agents.py`（含 `agileac-sal-02-reimbursement-status` agent 模板配置，四层架构 system_prompt）
3. **glm-5.2 已可用**：组织已配智谱 AI provider，`supported_models` 含 `glm-5.2`。
   - 自检：`GET /api/v1/terminal/models`（用 sal-ops token）应在 `models` 里看到 `glm-5.2`。
4. **sal-ops 账号已存在且 active**：
   ```bash
   docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
     "SELECT username, is_active FROM users WHERE username='sal-ops';"
   ```
5. **ERP mock 凭证端点正常**：
   ```bash
   curl -s "http://localhost:8010/erp/api/v1/vouchers?period=2026-07" -H "X-API-Key: erp-agileac-demo-key"
   ```
   应返回 JSON 列表，**含 `BV-AG-2026-0512`（status=财务复核中、debit_total=6800、entry_date=2026-07-08、summary=差旅费报销-7月）**。
6. **员工综合知识库向量通道正常**：
   ```bash
   docker exec ai_infra_backend python -c "
   from app.rag.service import RAGService
   s = RAGService()
   c = s.get_collection_by_name('员工综合知识库')
   print('chunks:', c.chunk_count, 'embedded:', c.embedded_count)
   "
   ```
   应输出 `embedded == chunks`。若 `embedded < chunks`，跑 `reembed_agileac_rag.py --collection-name "员工综合知识库"` 回填。

> ⚠️ SAL-02 关键依赖 3 件事：员工综合知识库 RAG 向量通道（报销流程+状态枚举 chunk）+ ERP `listVouchers(period=)` 端点（销售部技能已绑）+ 演示凭证 BV-AG-2026-0512 在 mock 中存在且时间为 2026-07。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/agileac/terminal/login
```

- 用户名：`sal-ops`
- 密码：`12345678`

登录后落到 `/agileac/terminal`。左上角应显示 `sal-ops` + 组织「敏睿空调」 + 部门「销售部」。

> 终端使用 **user-type JWT**。`sal-ops` 的 scope 包含：组织级资源（员工综合知识库 RAG + 33 组织本体）+ 销售部部门级资源（销售部技能 `agileac-sal-crm-erp-query`，含 ERP `listVouchers`）+ 个人工作区。

### 3.2 新建任务

点左栏「New Task / 新建任务」按钮，进入任务编辑器（HomeView composer）。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧 ⚙️ 设置按钮，打开 TaskConfigDrawer，配置 4 项：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `sal-ops`（个人工作区） | 干净；记忆仍按四级自动载入 |
| Model | **`glm-5.2`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | 让 agent 自主多轮调 RAG + ERP |
| 场景模板 | `agileac-sal-02-reimbursement-status` | **必绑**——知识库 cue / 端点 cue / 输出骨架由模板 system_prompt 承载；技能可留空从模板继承，或显式选 `agileac-sal-crm-erp-query` |

> 若 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id`。
>
> **本体 / RAG / 记忆不在 drawer 里配置**——按用户 scope 自动注入：
> - 33 个组织级本体（含 ERP 域 `identifiers.md`——凭证前缀 `BV-AG-`）自动注入；
> - 「员工综合知识库」RAG（组织级，全员可见）自动可见；
> - 长期记忆按「组织+部门+团队+个人」四级自动载入。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 composer 输入框（`MentionInput`）里输入：

> 敲 `/` 弹出技能菜单，输入 `sal` 过滤，选中 **`agileac-sal-crm-erp-query`** 即把技能 chip 插入提示词。

完整提示词（直接复制，约 20 字——**就是业务人员的自然问法，不带任何编排**）：

```
我上周提交的差旅报销走到哪一步了？

/agileac-sal-crm-erp-query
```

> **四层架构**（详见 `SCENARIO_AUTHORING_GUIDE.md`）：user composer 只写**业务问题 + 技能 chip**。"先检索员工综合知识库取流程/状态枚举、再调 ERP `listVouchers` 取活凭证、按 summary 定位"这套**编排完全由 Agent 模板 `agileac-sal-02-reimbursement-status` 的 `system_prompt` 承载**（见 `## 知识库（先做）` / `## 数据接口（后做）` 两节），不写进用户提示词——业务人员不该也不必告诉 agent 先查什么后查什么。任务 config 必须绑定 `template_agent_id = <agileac-sal-02-reimbursement-status 的 UUID>`，运行时 `load_config` 才会注入模板（trace `template` 出现、`template:true`）。技能与模型留空即从模板继承（`agileac-sal-crm-erp-query` + `glm-5.2`）。

> ⚠️ **关键 1**：`/agileac-sal-crm-erp-query` 必须从 `/` 菜单选中 chip，不能手敲文本。agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时 message 里写 `/agileac-sal-crm-erp-query` 也会被同款正则解析（见 §6）。
>
> ⚠️ **关键 2**：提示词**只写业务问题**，不写"先查知识库/再调 ERP"这类编排指令——编排由模板 system_prompt 驱动。实测（task 225ec281）证明：纯问题版 agent 仍稳定触发 RAG（5 hits）+ listVouchers 调用 + 正确答案，agent 开头自行说明"我先从员工综合知识库确认流程步骤语义，再调 ERP listVouchers 取活数据"——编排源自模板而非用户。
>
> ⚠️ **关键 3**：提示词不写凭证号——让 agent `listVouchers(period=2026-07)` 后按 summary 含"差旅费报销"自己定位那张单，更接近真实员工问法（员工不会背凭证号）。

#### 资源注入机制（任务运行时自动完成，无需配置）

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | 按 scope 注入（33 组织级含 ERP identifiers） | 33 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出 | 销售部技能绑定的 CRM + ERP 端点 |
| **RAG** | 空数组 = 全集自动匹配；retrieve_rag 节点按 query 检索 top-k | 1 collection（员工综合知识库），~3–5 hits |
| **长期记忆** | 4 级聚合；load_memory 节点载入 | 若干 history + facts |
| **技能** | /-mention 解析 + 模板继承 | 1 skill（agileac-sal-crm-erp-query） |
| **记忆沉淀** | extract_memory 抽取本轮可沉淀事实 | 0–2 facts |

### 3.5 提交运行

按回车提交。前端 `POST /api/v1/terminal/tasks` 创建任务，再 `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}`——**这才是真正发给 agent 的输入**。手工调 API 时 `/run` 也要把完整提示词带上。

### 3.6 观察 SSE 事件流

事件类型同其他终端任务场景。SAL-02 关注：

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载配置（`template:true` 表示模板已注入） |
| `[trace]` (rag) | RAG 检索命中——员工综合知识库「差旅报销流程」chunk |
| `[trace]` (template) | 场景模板 `agileac-sal-02-reimbursement-status` 注入 |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 33 组织本体注入（含 ERP identifiers） |
| `[trace]` (data_interface) | 数据接口目录注入（销售部技能端点） |
| `[trace]` (skill) | /-mention 引用 `agileac-sal-crm-erp-query` |
| `[phase] llm` | LLM 调用轮次 |
| `[tool_call]` listVouchers | agent 调 ERP 查凭证（args 可能为 `{}`，见 §5.4；返回全集后按 summary 含"差旅费报销"定位） |
| `[tool_result]` | 工具返回（含 BV-AG-2026-0512 行） |
| `[text]` | LLM 流式输出答案 |
| `[done]` / `[final]` | 收口 + usage + latency |

> 典型 SAL-02 运行约 2–3 分钟（1–2 轮 LLM + 1 次 RAG 检索 + 1 次 listVouchers 调用）。

---

## 4. 期望输出

agent 输出一段问答（单问题，不必调 `generate_docx`）：

**问题**：我上周提交的差旅报销走到哪一步了？

**RAG 命中**：员工综合知识库「差旅报销流程」chunk——5 步流程 + 状态枚举（申请中 → 直属经理审批中 → 部门总监联签中 → **财务复核中** → 已打款 → 已闭环）；报销时限 7 工作日内、打款日每周二/四、>¥5000 需总监联签。

**接口补全**：调 ERP `listVouchers(period="2026-07")` → 返回该期间凭证列表 → 按 `summary` 含"差旅费报销"定位到 `BV-AG-2026-0512`：`status=财务复核中`、`debit_total=6800`、`entry_date=2026-07-08`。

**答案**：
你的差旅报销 `BV-AG-2026-0512` 当前状态：**财务复核中**（报销流程第 4 步）
- 提交日期：2026-07-08（上周）
- 金额：6800 元
- 当前环节：财务对账组复核（≤2 个工作日）
- 下一步：复核通过 → 出纳打款（每周二、四）→「已打款」→「已闭环」
- 预计打款：本周四或下周二

**引用源**：员工综合知识库 chunk（差旅报销流程）+ ERP `listVouchers(period=2026-07)` + 凭证号 `BV-AG-2026-0512`

---

## 5. 故障排查

### 5.1 模型选择器里没有 `glm-5.2`
- 智谱 AI provider 未配或 `supported_models` 不含 `glm-5.2`。自检 `GET /api/v1/terminal/models` 的 `models` 应含 `glm-5.2`；修复：管理端「敏睿空调」组织 → LLM Provider 页配智谱 AI provider（`supported_models` 含 `glm-5.2`）+ 路由策略 `model_pattern=glm-*` 指向它，重跑 `seed_agileac_org.py`。

### 5.2 提示词里 `/agileac-sal-crm-erp-query` 没被识别
- 必须从 `/` 弹窗选 chip，不能手敲。自检：task.message 里这段应是结构化 chip 标记。

### 5.3 `[tool_result FAIL]` ERP `listVouchers` 调用失败
- mock 网关未起或 API key 不匹配。自检 `curl -s "http://localhost:8010/erp/api/v1/vouchers?period=2026-07" -H "X-API-Key: erp-agileac-demo-key"` 应返回 JSON。

### 5.4 `listVouchers` 调用没带 `period` 参数（args 全 `{}`）
- 现象：`tool_call.arguments={}`。`_build_tools`（`app/agents/graph/nodes.py`）的 manifest 占位 schema 覆盖问题（预存，非 SAL-02 引入）。因 `listVouchers` 的 period/status 参数可选，agent 拿全集后按 summary 自行定位，非阻塞。

### 5.5 agent 没主动触发 RAG 检索
- 编排（先 RAG 后接口）由模板 `system_prompt` 的 `## 知识库（先做）` 节承载，**不应靠用户提示词加 cue**。若纯问题版（§3.4）RAG 没触发：先确认 `load_config template:true` + `trace template` 出现（模板没注入则编排丢了）；再确认模板 `system_prompt` 含"先检索员工综合知识库"指令；最后看 retrieve_rag 节点 query 嵌入是否命中——embedding provider 未配时走 keyword_fallback，纯问题"差旅报销走到哪一步"含关键词仍应命中报销 chunk。

### 5.6 RAG 命中了但 chunk 不含报销流程
- 现象：命中的是产品参数/工艺 SOP 等不相关 chunk。根因：员工综合知识库的差旅报销 chunk 没被正确 embed。修复：跑 `reembed_agileac_rag.py --collection-name "员工综合知识库"` 回填。

### 5.7 凭证找不到（listVouchers period=2026-07 返回不含差旅报销单）
- 现象：返回空或不含 `BV-AG-2026-0512`。根因：mock 凭证时间没更新到 2026-07，或 mock 容器没重启。修复：确认 `erp/data.py` 中该凭证 `period="2026-07"`、offset=9（entry_date=2026-07-08），并 `docker restart ai_infra_mock`。

### 5.8 trace `rag` 显示 `retriever=keyword_fallback`
- 向量 embedding 不可用（org 未配 embedding provider 或 `text-embedding-v4` 不可达），RAG 退化为 CJK 关键词检索。修复：管理端「敏睿空调」组织配 OpenAI 兼容 embedding provider（如 aliyun `text-embedding-v4`），跑 reembed 回填。

---

## 6. 附：手工调 API 复现

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agileac","username":"sal-ops","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 SAL-02 Agent 模板 id
TPL_ID=$(docker exec ai_infra_backend python3 -c "
import asyncio, asyncpg
async def m():
    c=await asyncpg.connect('postgresql://ai_infra:ai_infra@postgres:5432/ai_infra')
    r=await c.fetchrow(\"SELECT id FROM agents WHERE slug='agileac-sal-02-reimbursement-status'\")
    print(r['id']); await c.close()
asyncio.run(m())")

# 3) 创建任务（绑定模板；skill_ids 留空从模板继承，model=glm=glm-5.2）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"SAL-02 报销进度问答\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer 作为 message，含 /agileac-sal-crm-erp-query chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"我上周提交的差旅报销走到哪一步了？\\n\\n/agileac-sal-crm-erp-query\",\"stream\":true}"
```

短 composer 提示词文本见 §3.4（知识库 cue / 端点 cue / 输出骨架由 SAL-02 模板 system_prompt 承载，不在 composer 里）。

---

## 7. 验收要点（演示前自检）

- [ ] `sal-ops` 能登录 `/agileac/terminal/login`，左上角显示「销售部」
- [ ] `GET /api/v1/terminal/resources`（sal-ops token）的 `skills` 含 `agileac-sal-crm-erp-query`（dept），**不应**含 `agileac-it-hrm-erp-plm-mes-query`（IT 组织级技能已删）
- [ ] 同一端点 `rags` 字段含「员工综合知识库」（scope=organization），**不应**含其他部门级 RAG（如「售后故障与维修知识库」「产品参数与卖点库」）——验证部门级资源隔离
- [ ] 数据接口不在 resources 列表里——运行时 `trace category=data_interface` 应含 ERP `listVouchers`（销售部技能 `bound_endpoint_ids` 解析，period/status 参数可见）
- [ ] `load_config` 事件显示 **`template:true`**（绑定了 template_agent_id）
- [ ] `trace category=template` 出现（slug=`agileac-sal-02-reimbursement-status` + chars）
- [ ] `trace category=rag` 出现，hits ≥ 1，命中 chunk 含差旅报销 5 步流程/状态枚举（`retriever=vector` 需 embedding provider 已配；未配则 `keyword_fallback`，仍应命中含"差旅/报销/财务复核"关键词的 chunk——见 §5.8）
- [ ] `tool_call` 调 `listVouchers`（args 可能为 `{}`——`_build_tools` 占位 schema 已知问题，因 listVouchers 的 period/status 参数可选、非阻塞，agent 拿全集后按 summary 自行定位；见 §5.4）
- [ ] `tool_result` 含 `BV-AG-2026-0512`（财务复核中 / 6800 / 2026-07-08）
- [ ] 输出答案含"财务复核中（第 4 步）+ 6800 + 预计打款日" + 引用源（知识库 chunk + ERP 端点 + 凭证号）
- [ ] no-guessing：agent 用对凭证前缀 `BV-AG-`，不臆造凭证号或状态
