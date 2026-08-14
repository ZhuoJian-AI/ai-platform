# SVC-01 售后故障 AI 诊断与 8D 闭环 · 终端任务演示

> 售后工程师 `svc-engineer` 登录终端，新建任务、配置 `glm-5.2` + `craft`、`/agileac-svc-crm-mes-plm-query` 选技能、写提示词、运行，agent 自主多轮调用 CRM 客诉 + MES 工单/缺陷 + PLM BOM/工程变更 + 售后故障与维修知识库 RAG，对当前未关闭客诉做根因分析 + 排查指引 + 8D 闭环待办。
>
> **员工 vibe working 视角**：AI 是售后工程师的副驾驶，做诊断分析与待办整理，**不对客户直接交互**——无 AI 接听客户来电、无 AI 自动外呼；客诉工单由 mock 内置 `listComplaints` 提供作为工程师的输入。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 敏睿空调（slug = `agileac`） |
| 用户名 | `svc-engineer` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |
| 部门 | 售后服务部 · 工程师组 |

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）+ `ai_infra_postgres` 容器在跑。
2. **数据已 seed**（按 `README.md` §9 顺序执行）：
   - `seed_agileac_org.py`（含 `svc-engineer` 用户 + 售后服务部 + 工程师组）
   - mock 6 系统 agileac tenant 数据已内置（`mock/mock/systems/*/data.py` 的 `_build_agileac`），mock 容器重启即生效，无需独立 seed 脚本
   - `seed_agileac_mock_connectors.py`（含部门级技能 `agileac-svc-crm-mes-plm-query` + 数据接口按售后服务部 scope 授权）
   - `seed_agileac_ontology.py`（33 组织级含 PLM/CRM/MES/HRM/ERP 各域 `identifiers.md` + 售后服务部 4 文件 = 37 个本体文件对该用户可见——org scope 资源对所有部门用户可见）
   - `seed_agileac_rag.py`（含「售后故障与维修知识库」部门级 RAG，scope=`after-sales`）
   - `seed_agileac_agents.py`（含 `agileac-svc-01-after-sales-diagnosis` agent 模板配置，四层架构 system_prompt）
3. **glm-5.2 已可用**：组织已配智谱 AI provider，`supported_models` 含 `glm-5.2`。
   - 自检：`GET /api/v1/terminal/models`（用 svc-engineer token）应在 `models` 里看到 `glm-5.2`。
4. **svc-engineer 账号已存在且 active**：
   ```bash
   docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
     "SELECT username, is_active FROM users WHERE username='svc-engineer';"
   ```
5. **CRM/MES/PLM mock 端点正常**：
   ```bash
   curl -s "http://localhost:8010/crm/complaints" -H "X-API-Key: crm-agileac-demo-key" | head
   curl -s "http://localhost:8010/mes/work-orders" -H "X-API-Key: mes-agileac-demo-key" | head
   curl -s "http://localhost:8010/plm/styles" -H "X-API-Key: plm-agileac-demo-key" | head
   ```
   应返回 JSON 列表。
6. **售后故障与维修知识库向量通道正常**：
   ```bash
   docker exec ai_infra_backend python -c "
   from app.rag.service import RAGService
   s = RAGService()
   c = s.get_collection_by_name('售后故障与维修知识库')
   print('chunks:', c.chunk_count, 'embedded:', c.embedded_count)
   "
   ```
   应输出 `chunks: ~80 embedded: ~80`（具体数视 seed 而定，关键是 `embedded == chunks`）。若 `embedded < chunks`，跑 `reembed_agileac_rag.py --collection-name "售后故障与维修知识库"` 回填。

> ⚠️ SVC-01 关键依赖 4 件事：CRM `listComplaints` + MES `listWorkOrders`/`listDefects`/`getDefectRootCause` + PLM `getStyle`/`listBoms`/`listDefectHistory` 端点 + 售后故障与维修知识库 RAG 向量通道 + `_build_tools` 修复（确保 `tool_call.arguments` 不为 `{}`）。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/agileac/terminal/login
```

- 用户名：`svc-engineer`
- 密码：`12345678`

登录后落到 `/agileac/terminal`（终端首页）。左上角应显示 `svc-engineer` + 组织「敏睿空调」 + 部门「售后服务部」。

> 终端使用 **user-type JWT**（与超管 token 不同，scope 仅限本部门 + 组织级资源可见）。

### 3.2 新建任务

点左栏「New Task / 新建任务」按钮，进入任务编辑器（HomeView composer）。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧 ⚙️ 设置按钮，打开 TaskConfigDrawer，配置 4 项：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `svc-engineer`（个人工作区） | 干净；记忆仍按四级（组织+部门+团队+个人）自动载入 |
| Model | **`glm-5.2`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | 让 agent 自主多轮调用工具；`ask` 是只读单轮、`plan` 只出方案不执行 |
| 场景模板 | `agileac-svc-01-after-sales-diagnosis` | **v1 起必绑**——执行步骤/8D 规则/输出骨架由模板 system_prompt 承载；技能可留空从模板继承，或显式选 `agileac-svc-crm-mes-plm-query` |

> 若 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id`。
>
> **本体 / RAG / 记忆不在 drawer 里配置**——这些按用户 scope 自动注入：
> - 37 个本体文件（33 组织级含 identifiers.md + 4 售后服务部级）按 scope 自动注入（org scope 对所有部门用户可见）；
> - 「售后故障与维修知识库」RAG（部门级，scope=`after-sales`）自动可见；
> - 长期记忆按「组织+部门+团队+个人」四级全集自动载入。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 composer 输入框（`MentionInput`，支持 `/` 触发技能、`@` 触发工作区文件）里输入：

> 敲 `/` 会弹出技能选择菜单，输入 `svc` 过滤，选中 **`agileac-svc-crm-mes-plm-query`** 即把技能 chip 插入到提示词中。

完整提示词如下（直接复制，约 200 字符）：

```
对敏睿空调当前未闭环客诉做故障诊断 + 8D 闭环分析，重点 3 条：
CR-AG-2026-0001（P-RC-WALL-15 不制冷）、CR-AG-2026-0002（P-CC-VRV-360 通讯故障）、CR-AG-2026-0003（P-RC-CAB-30 漏水）。
扫所有 status != "已闭环" 客诉，按故障类型检索售后故障与维修知识库给根因/排查/配件/8D 待办。

/agileac-svc-crm-mes-plm-query
```

> **四层架构**（详见 `SCENARIO_AUTHORING_GUIDE.md`）：user composer 只写**目标 + 对象 + 阈值/时间窗 + 技能 chip**，执行步骤 / 异动规则 / 输出格式由 Agent 模板 `agileac-svc-01-after-sales-diagnosis` 的 `system_prompt` 承载（persona + RAG cue + 8D 闭环待办规则 + 3 段输出骨架）。任务 config 必须绑定 `template_agent_id = <agileac-svc-01-after-sales-diagnosis 的 UUID>`，运行时 `load_config` 才会注入模板（trace `template` 出现、`template:true`）。技能留空从模板继承 `agileac-svc-crm-mes-plm-query`；模型模板默认 `glm-5.2`（与 drawer 一致，无需覆写）。
>
> 若前端 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id` 复现（`SELECT id FROM agents WHERE slug='agileac-svc-01-after-sales-diagnosis'`）。

> ⚠️ **关键 1**：`/agileac-svc-crm-mes-plm-query` 必须从 `/` 菜单选中 chip，不能手敲文本。agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时 message 里写 `/agileac-svc-crm-mes-plm-query` 也会被同款正则解析（见 §6）。
>
> ⚠️ **关键 2**：composer 里「检索售后故障与维修知识库」字样**必须保留**——部门级 RAG 虽按 scope 自动装载，但 `retrieve_rag` 节点是否真去检索取决于查询文本相关性，明确写出检索意图才能稳定触发。
>
> ⚠️ **关键 3**：composer 写明 3 条重点工单 + 故障类型，让 agent 有明确检索锚点，避免泛化查询导致 RAG 命中度过低。本体 identifiers.md 已写明客诉主键 `AGCP-`、工单 `AWO`、MES 缺陷 `DF`、PLM 故障案例 `DF-AG-`、产品 `P-RC-/P-CC-` 与跨码空间映射（MES 缺陷号 DF ≠ PLM 故障案例号 DF-AG-，跨系统查历史按 product_code 关联勿直传 DF），agent 调 path 参数端点前读此表，杜绝 404。

#### 资源注入机制（任务运行时自动完成，无需配置）

任务运行时，agent runtime 会按 svc-engineer 的 scope 自动注入以下资源到 system prompt：

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | 按 scope 注入（组织级 33 含 identifiers.md + 售后服务部级 4） | 37 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出所有可调用的 mock 接口 | CRM/MES/PLM 3 systems / ~40 interfaces |
| **RAG** | 空数组 = 全集自动匹配；retrieve_rag 节点按 query 检索 top-k | 1 collection（售后故障与维修知识库），5 hits |
| **长期记忆** | 4 级（组织+部门+团队+个人）按权限聚合；load_memory 节点载入 | 4 history + 6 facts |
| **技能** | skill_ids 显式选 + /-mention 解析 | 1 skill（agileac-svc-crm-mes-plm-query） |
| **记忆沉淀** | extract_memory 节点抽取本轮可沉淀事实写入个人级 Memory | 0~3 facts |

### 3.5 提交运行

按回车（或点发送按钮）提交。前端会：
1. `POST /api/v1/terminal/tasks` 创建任务（把 composer 里的内容作为 `message` 字段存档）；
2. `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}` —— **这才是真正发给 agent 的输入**。

> ⚠️ 实测：`/run` 的 `message` 才是 agent 看到的指令；任务创建时存的 `message` 不会被 agent 读到。前端的做法是「同一段文本两次用」。如果你手工调 API，记得 `/run` 也要把完整提示词带上。

### 3.6 观察 SSE 事件流

任务运行后，右侧 ChatView 会渲染 SSE 事件。事件类型与含义：

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载任务配置（model / skill_ids / workspace） |
| `[trace]` (rag) | RAG 检索命中——售后故障与维修知识库被检索 |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 组织本体 + 售后服务部本体注入 system prompt |
| `[trace]` (data_interface) | 数据接口目录注入（按售后服务部权限，仅 CRM/MES/PLM 可见） |
| `[trace]` (skill) | /-mention 解析引用了哪个技能 |
| `[trace]` (memory/extract) | 记忆沉淀抽取（写个人级 Memory） |
| `[phase] llm #0/#1/#2/#3` | 每个 LLM 调用轮次 |
| `[tool_call]` | agent 调用工具（如 CRM 端点 / MES 端点 / PLM 端点 / generate_docx） |
| `[tool_result]` | 工具返回（ok / FAIL） |
| `[text]` | LLM 流式输出 token（直接渲染到对话气泡） |
| `[done]` | agent_loop 收口（带 usage 统计） |
| `[final]` | 任务结束，附 latency_ms + session_id |

> 终端前端 ChatView 目前只渲染 `text` / `tool_call` / `tool_result`；`trace` 事件保存在 assistant 消息的 `metadata_.traces` 里，管理后台或 `GET /terminal/tasks/{id}/messages` 可见。

典型 SVC-01 运行约 5–7 分钟（3–4 轮 LLM + 6–7 次 tool 调用 + glm-5.2 推理 + 记忆/RAG 节点）。

---

## 4. 期望输出

agent 会输出三段 + 1 个附件：

### 4.1 客诉工单汇总表

9 列，含 3 条重点工单 + 其余未闭环客诉：

| # | 客诉号 | 款号 | 客户 | 故障类型 | 关联工单 | 严重等级 | 当前状态 | 接单时间 | 责任工程师 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | CR-AG-2026-0001 | P-RC-WALL-15 | 家电连锁 A | 不制冷 | AWO20260101 | 严重 | 8D 进行中 | 2026-07-08 | svc-engineer |
| 2 | CR-AG-2026-0002 | P-CC-VRV-360 | 工程项目 B | 通讯故障 | AWO20260210 | 致命 | 分析中 | 2026-07-09 | svc-engineer |
| 3 | CR-AG-2026-0003 | P-RC-CAB-30 | 家电连锁 C | 漏水 | AWO20260105 | 严重 | 8D 进行中 | 2026-07-10 | svc-engineer |
| … | … | … | … | … | … | … | … | … | … |

> 严重等级判定规则 agent 会自洽定义（如：致命 = 商用多联机+通讯故障+影响多台内机；严重 = 家用主功能失效；一般 = 次要功能异常）。

### 4.2 故障诊断报告

每条客诉一段，结构：根因分析 + 排查步骤 + 配件清单 + 维修手册引用。以 CR-AG-2026-0001（不制冷）为例：

**根因分析**：
- 主因：压缩机启动电容容量衰减（标称 30μF，实测 22μF，低于 ±10% 容差）
- 次因：室外机冷凝器翅片积灰导致散热不良，高压保护频发
- 关联历史缺陷案例：`DF-AG-2026-001`（P-RC-WALL-15 不制冷，电容衰减，严重）

**排查步骤**（来自 RAG 维修手册 + PLM defect_history）：
| 步骤 | 内容 | 工具/标准 |
|---|---|---|
| 1 | 万用表测启动电容容量，标称 30μF ±10% | 实测 < 27μF 必换 |
| 2 | 测压缩机绕组阻值（C-R/C-S/R-S 三组） | 三组不平衡 > 5% 怀疑压缩机 |
| 3 | 测高/低压表，运行压力 vs 标称 R410A 0.8/2.5 MPa | 偏低查冷媒泄漏，偏高查冷凝器散热 |
| 4 | 目视冷凝器翅片积灰情况 | 积灰 > 50% 面积必清洗 |

**配件清单**：
| 配件编码 | 名称 | 数量 | 来源仓库 |
|---|---|---|---|
| M-COMP-GT-24K | 24K 转子压缩机启动电容 | 1 | WH-AG-PARTS-01 |

**维修手册引用**（标注来源，闭环可追溯）：
| 来源 | 类型 | 内容 |
|---|---|---|
| DF-AG-2026-001 | PLM 历史缺陷 | 款号 P-RC-WALL-15，故障类型"不制冷"，严重等级 严重 |
| DF-AG-2026-001 | 根因 | 启动电容容量衰减至 22μF |
| DF-AG-2026-001 | 纠正措施 | 更换 30μF 电容 + 清洗冷凝器 |
| RAG 知识库 | 排查阶段 | 不制冷类故障必查 4 步：电容→绕组→高低压→冷凝器 |
| RAG 知识库 | 验证阶段 | 维修后 30 分钟运行，测出风口温差 ≥ 8℃ |

### 4.3 8D 闭环待办清单（按催办对象分组）

**研发部待办**：
| 客诉号 | 待办类型 | 责任部门 | 截止建议 | 状态 |
|---|---|---|---|---|
| CR-AG-2026-0001 | 设计改进：电容选型升冗余（30μF → 35μF 工业级） | 研发部·电气组 | 2026-08-01 | 未落实 |
| CR-AG-2026-0002 | 设计改进：多联机通讯协议增加心跳重连机制 | 研发部·电气组 | 2026-08-15 | 未落实 |

**质量部待办**：
| 客诉号 | 待办类型 | 责任部门 | 截止建议 | 状态 |
|---|---|---|---|---|
| CR-AG-2026-0001 | 来料改进：电容来料 100% 容量分选 | 质量部·IQC | 2026-07-25 | 已落实 |
| CR-AG-2026-0003 | 工艺改进：总装后必做排水试漏 5min | 质量部·IPQC | 2026-07-30 | 未落实 |

**采购部待办**：
| 客诉号 | 待办类型 | 责任部门 | 截止建议 | 状态 |
|---|---|---|---|---|
| CR-AG-2026-0001 | 供应商改进：电容供应商月度评分扣分（≥3 起电容衰减投诉） | 供应链部·采购组 | 2026-08-05 | 未落实 |

> 8D 待办通过跨 agent 待办机制（见 `CROSS_AGENT_HANDOFF_DESIGN.md`）写入 `agent_followups` 表，目标 agent（研发/质量/采购对应 agent）启动时拉取——**不在本场景内直接调用其他部门 agent**，符合"场景按部门边界"约束。

### 4.4 .docx 报告附件

agent 会调 `generate_docx` 工具把上述分析打包成 `敏睿空调_售后故障诊断与8D闭环报告_YYYYMMDD.docx`（约 40 KB），可下载分发归档。

### 4.5 SSE trace 事件（演示时截图可证）

任务运行期间，SSE 流除常规 `step` / `phase` / `text` / `tool_call` / `tool_result` / `final` 外，会发射 6 个 `trace` 事件：

| trace | 含义 | 期望实测值 |
|---|---|---|
| `category=rag` | RAG 检索命中 | 1 collection / 5 hits（retriever=vector，pgvector 余弦检索） |
| `category=template` | 场景模板注入（v1 起必出） | slug=agileac-svc-01-after-sales-diagnosis + chars（~859） |
| `category=memory, subtype=load` | 长期记忆载入 | 6 history + 6 facts |
| `category=ontology` | 组织本体 + 售后服务部本体注入 | 37 files |
| `category=data_interface` | 数据接口目录注入（按售后服务部权限） | 3 systems / ~40 interfaces |
| `category=skill` | /-mention 引用技能 | 1 skill（agileac-svc-crm-mes-plm-query） |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | 0~3 facts |

---

## 5. 故障排查

### 5.1 模型选择器里没有 `glm-5.2`

- 智谱 AI provider 未配或 `supported_models` 不含 `glm-5.2`。
- 自检：`GET /api/v1/terminal/models` 的 `models` 应含 `glm-5.2`。
- 修复：管理端「敏睿空调」组织 → LLM Provider 页配智谱 AI provider（`supported_models` 含 `glm-5.2`）+ 路由策略 `model_pattern=glm-*` 指向它，重跑 `seed_agileac_org.py`。

### 5.2 提示词里 `/agileac-svc-crm-mes-plm-query` 没被识别

- 必须从 `/` 弹窗里选中 chip，不能手敲纯文本。
- 自检：保存的 task.message 里这段应该是结构化 chip 标记，不是 plain text。

### 5.3 `[tool_result FAIL]` CRM/MES/PLM 接口调用失败

- mock 网关未起或 API key 不匹配。
- 自检：
  ```bash
  curl -s http://localhost:8010/crm/complaints -H "X-API-Key: crm-agileac-demo-key" | head
  curl -s http://localhost:8010/mes/work-orders -H "X-API-Key: mes-agileac-demo-key" | head
  curl -s http://localhost:8010/plm/styles -H "X-API-Key: plm-agileac-demo-key" | head
  ```
  均应返回 JSON。

### 5.4 `svc-engineer` 看不到 CRM/MES/PLM 数据接口

- 部门级 scope 授权未配置——`seed_agileac_mock_connectors.py` 没把 `DataInterface` 的 `scope_type=department, scope_id=after-sales_dept.id` 配好。
- 自检：`GET /api/v1/terminal/resources`（svc-engineer token）的 `data_interfaces` 应含 CRM/MES/PLM 端点。
- 修复：重跑 `seed_agileac_mock_connectors.py`，确认售后部技能 `agileac-svc-crm-mes-plm-query` 的 `skill_files` 绑定 CRM/MES/PLM 只读端点 manifest。

### 5.5 agent 输出「我没有收到任务」

- 检查 `/run` 请求体里 `message` 是否为空——必须把完整提示词作为 `message` 发送，任务创建时存的 `message` 不会被 agent 读到。

### 5.6 运行很久没动 / latency > 5 分钟

- glm-5.2 单轮推理慢，多轮 tool 调用累计 3–4 分钟正常。超过 10 分钟大概率卡住，看后端日志 `docker logs ai_infra_backend --tail 100`。

### 5.7 trace `rag` 显示 `retriever=keyword_fallback`

- 说明向量 embedding 不可用（org 未配 embedding provider 或 `text-embedding-v4` 不可达），RAG 退化为 CJK 关键词检索。仍能命中含关键词的 chunk 但语义精度差。
- 修复路径：
  1. 在管理端「敏睿空调」组织 → LLM Provider 页配置 OpenAI 兼容的 embedding provider（如 `aliyun-all-openai` 启用 `text-embedding-v4`）；
  2. 确认 `rag_service.py` `_EMBED_BATCH=8`（受 Aliyun 单批 10 条上限制约）；
  3. 若 chunks 已存在但 embedding 列为 NULL，跑 `reembed_agileac_rag.py --collection-name "售后故障与维修知识库"` 一次性回填；
  4. 自检：`SELECT COUNT(*) FROM rag_chunks WHERE collection_id=<售后故障与维修知识库 id> AND embedding IS NOT NULL` 应等于 chunk 总数。

### 5.8 agent 没主动触发 RAG 检索

- retrieve_rag 节点的 query 是整段 user message，命中靠语义相关性。
- 若提示词只写"诊断故障"而没提"售后故障与维修知识库"，glm-5.2 的 query 嵌入可能命中度不够。
- 修复：提示词里**明确写出「检索售后故障与维修知识库」字样**（见 §3.4 关键 2）。

### 5.9 `tool_call` args 全 `{}`

- 现象：所有 `tool_call` 的 `arguments={}`，需要参数的端点（如 `getDefectRootCause`）返回 500；不带参数也能跑的端点（如 `listComplaints`）正常。
- 根因：`_build_tools`（`app/agents/graph/nodes.py`）的 manifest 占位 schema 覆盖问题（starclothing PD-2 栽过此坑，详见 `SCENARIO_AUTHORING_GUIDE.md` §6.10）。
- 修复：跑完一次后看 SSE 解析里的 `tool_call` args，**只要有一条非 `{}`** 就说明 `_build_tools` 工作正常；如果全是 `{}` 立即查 `nodes.py` `_build_tools`。

### 5.10 path 参数端点（`getStyle` / `getWorkOrder` / `getComplaint`）返回 404 `{style_code} not found`

- 现象：agent 调 `getStyle(style_code="P-RC-WALL-15")` 返回 `{"detail":"style {style_code} not found"}`——path 占位符未替换为实际值。
- 影响：**不阻塞闭环**。agent 自主降级到 `listStyles(keyword)` / `listWorkOrders` / `listComplaints`（这些 list 端点用 query 参数，不受影响），仍能拿到完整信息。
- 修复（可选）：在技能 wrapper 里按 OpenAPI path 占位符替换路径参数。非阻塞性问题，本期演示按「agent 自主降级」路径通过。

### 5.11 memory/extract 抽取 0~3 facts

- 现象：`trace memory/extract` 多数情况下 `facts: 0`，偶尔抽到 3 facts。
- 根因：extract_memory 节点对中文长文本 + 多段结构化输出的抽取策略偏保守。
- 影响：非阻塞，本轮输出已完整；但长期记忆通道没真正发挥作用，跨任务复用能力弱。修复（可选）：调整 `extract_memory` 的 prompt，让其显式抽取结构化事实（客诉号 + 根因 + 配件三元组）。

---

## 6. 附：手工调 API 复现

不用前端的话，可以用 curl 走一遍：

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agileac","username":"svc-engineer","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 SVC Agent 模板 id（v1 起任务 config 必须绑定 template_agent_id）
TPL_ID=$(docker exec ai_infra_backend python3 -c "
import asyncio, asyncpg
async def m():
    c=await asyncpg.connect('postgresql://ai_infra:ai_infra@postgres:5432/ai_infra')
    r=await c.fetchrow(\"SELECT id FROM agents WHERE slug='agileac-svc-01-after-sales-diagnosis'\")
    print(r['id']); await c.close()
asyncio.run(m())")

# 3) 创建任务（绑定模板；skill_ids 留空从模板继承，model=glm=glm-5.2）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"SVC-01 售后故障诊断\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer 作为 message，见 §3.4；含 /agileac-svc-crm-mes-plm-query chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"对敏睿空调当前未闭环客诉做故障诊断 + 8D 闭环分析，重点 3 条：\\nCR-AG-2026-0001（P-RC-WALL-15 不制冷）、CR-AG-2026-0002（P-CC-VRV-360 通讯故障）、CR-AG-2026-0003（P-RC-CAB-30 漏水）。\\n扫所有 status != \\\"已闭环\\\" 客诉，按故障类型检索售后故障与维修知识库给根因/排查/配件/8D 待办。\\n\\n/agileac-svc-crm-mes-plm-query\",\"stream\":true}"
```

短 composer 提示词文本见 §3.4（执行步骤/8D 规则/输出格式由 SVC Agent 模板 `system_prompt` 承载，不在 composer 里）。

---

## 7. 验收要点（演示前自检）

- [ ] `svc-engineer` 能登录 `/agileac/terminal/login`，左上角显示「售后服务部」
- [ ] `GET /api/v1/terminal/resources`（svc-engineer token）的 `skills` 含 `agileac-svc-crm-mes-plm-query`
- [ ] `data_interfaces` 仅含 CRM/MES/PLM 端点（不含 SCM/ERP/HRM——非本部门权限）
- [ ] `rag_collections` 含「售后故障与维修知识库」（scope=department, after-sales）
- [ ] `load_config` 事件显示 **`template:true`**（绑定了 template_agent_id）
- [ ] `trace category=template` 出现（场景模板注入，slug + chars）
- [ ] 任务跑完，SSE 6 类 trace 全部出现（rag + memory.load + ontology + data_interface + skill + memory.extract）
- [ ] `retrieve_rag` 显示 `retriever=vector`，hits ≥ 1
- [ ] `tool_call` args 不全 `{}`（至少 `getDefectRootCause(defect_id=...)` 这类必传参端点要带参）
- [ ] no-guessing：agent 用对标识符前缀（客诉主键 AGCP-、工单 AWO、PLM 故障案例 DF-AG-），不把 MES 缺陷号 DF 当 PLM 故障案例号 DF-AG- 直传
- [ ] 输出含三段（客诉工单汇总表 / 故障诊断报告 / 8D 闭环待办）+ 1 个 .docx 附件
- [ ] 8D 闭环待办按"研发/质量/采购"3 部门分组，不直接调用其他部门 agent（仅生成待办记录）
