# RND-01 多语技术资料翻译与术语统一 · 终端任务演示

> 研发翻译员 `rnd-translator` 登录终端，新建任务、配置 `glm-5.2` + `craft`、`/agileac-rnd-plm-query` 选技能、把一段外文（英/日）技术资料粘贴进 composer、运行，agent 自主多轮检索「多语术语与海外资料库」统一行业术语 + 调 PLM 产品参数核对型号/规格一致性，输出中文化译文 + 术语对照表 + 型号差异提示。
>
> **员工 vibe working 视角**：研发翻译员工原本要逐词查术语词典、逐型号查 PLM 参数、手填对照表——15 天的翻译核对压缩到 1 天。AI 是翻译员工的副驾驶，做术语统一与型号核对，**不直接对外交付**。
>
> 本场景验证 **痛点 B1（英/日技术资料翻译）+ C 技术核对** + 「先 RAG 后接口」分工：静态术语词典/翻译规则走知识库，型号参数一致性走 PLM 活接口。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 敏睿空调（slug = `agileac`） |
| 用户名 | `rnd-translator` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |
| 部门 | 研发部 · 翻译组 |

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）+ `ai_infra_postgres` 容器在跑。
2. **数据已 seed**（按 `README.md` §9 顺序执行）：
   - `seed_agileac_org.py`（含 `rnd-translator` 用户 + 研发部 + 翻译组 `rnd-translation`）
   - mock 6 系统 agileac tenant 数据已内置（`mock/mock/systems/*/data.py` 的 `_build_agileac`），mock 容器重启即生效，无需独立 seed 脚本
   - `seed_agileac_mock_connectors.py`（含团队级技能 `agileac-rnd-plm-query`，绑 PLM 只读端点 `listStyles`/`getStyle`/`listBoms`/`listDefectHistory`/`listCostLedger`/`listFeasibilityLogs`）
   - `seed_agileac_ontology.py`（33 组织级含 PLM 域 `identifiers.md`——产品款号前缀 P-RC-/P-CC-、物料前缀 M-COMP-/M-COND-/M-EVAP-/M-EEV-/M-RF-、故障案例号 DF-AG- + 翻译组 4 文件 = 37 个本体文件对该用户可见——org scope 资源对所有部门用户可见）
   - `seed_agileac_rag.py`（含「多语术语与海外资料库」**团队级** RAG，scope=`rnd-translation`，含 5 类英/日→中术语词典 + 商用 VRV 翻译样本段落）
   - `seed_agileac_agents.py`（含 `agileac-rnd-01-translation` agent 模板配置，四层架构 system_prompt）
3. **glm-5.2 已可用**：组织已配智谱 AI provider，`supported_models` 含 `glm-5.2`。
   - 自检：`GET /api/v1/terminal/models`（用 rnd-translator token）应在 `models` 里看到 `glm-5.2`。
4. **rnd-translator 账号已存在且 active**：
   ```bash
   docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
     "SELECT username, is_active FROM users WHERE username='rnd-translator';"
   ```
5. **PLM mock 端点正常**：
   ```bash
   curl -s "http://localhost:8010/plm/styles" -H "X-API-Key: plm-agileac-demo-key" | head
   curl -s "http://localhost:8010/plm/boms?style_code=P-RC-WALL-15" -H "X-API-Key: plm-agileac-demo-key" | head
   ```
   应返回 JSON 列表。
6. **多语术语与海外资料库向量通道正常**：
   ```bash
   docker exec ai_infra_backend python -c "
   from app.rag.service import RAGService
   s = RAGService()
   c = s.get_collection_by_name('多语术语与海外资料库')
   print('chunks:', c.chunk_count, 'embedded:', c.embedded_count)
   "
   ```
   应输出 `embedded == chunks`。若 `embedded < chunks`，跑 `reembed_agileac_rag.py --collection-name "多语术语与海外资料库"` 回填。

> ⚠️ RND-01 关键依赖 3 件事：多语术语与海外资料库 RAG 向量通道（英/日→中术语词典 + 翻译样本 chunk）+ PLM `listStyles`/`getStyle`/`listBoms` 端点（研发组技能已绑）+ 用户 composer 粘贴一段真实外文技术资料作翻译输入（无 `listPendingTranslations` 端点——待翻译资料由翻译员工粘贴，更贴近真实工作流）。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/agileac/terminal/login
```

- 用户名：`rnd-translator`
- 密码：`12345678`

登录后落到 `/agileac/terminal`（终端首页）。左上角应显示 `rnd-translator` + 组织「敏睿空调」 + 部门「研发部」。

> 终端使用 **user-type JWT**（与超管 token 不同，scope 仅限本部门/团队 + 组织级资源可见）。`rnd-translator` 属翻译组（team 级），其 scope 含：组织级资源（33 组织本体）+ 研发部部门级 + 翻译组团队级（多语术语 RAG + 研发组技能 `agileac-rnd-plm-query`）+ 个人工作区。

### 3.2 新建任务

点左栏「New Task / 新建任务」按钮，进入任务编辑器（HomeView composer）。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧 ⚙️ 设置按钮，打开 TaskConfigDrawer，配置 4 项：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `rnd-translator`（个人工作区） | 干净；记忆仍按四级（组织+部门+团队+个人）自动载入 |
| Model | **`glm-5.2`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | 让 agent 自主多轮调 RAG + PLM + generate_docx；`ask` 只读单轮不够 |
| 场景模板 | `agileac-rnd-01-translation` | **必绑**——翻译规则/RAG cue/输出骨架由模板 system_prompt 承载；技能可留空从模板继承，或显式选 `agileac-rnd-plm-query` |

> 若 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id`。
>
> **本体 / RAG / 记忆不在 drawer 里配置**——这些按用户 scope 自动注入：
> - 37 个本体文件（33 组织级含 PLM identifiers.md + 4 翻译组级）按 scope 自动注入（org scope 对所有部门用户可见）；
> - 「多语术语与海外资料库」RAG（团队级，scope=`rnd-translation`）自动可见；
> - 长期记忆按「组织+部门+团队+个人」四级全集自动载入。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 composer 输入框（`MentionInput`，支持 `/` 触发技能、`@` 触发工作区文件）里输入：

> 敲 `/` 会弹出技能选择菜单，输入 `rnd` 过滤，选中 **`agileac-rnd-plm-query`** 即把技能 chip 插入到提示词中。

完整提示词如下（直接复制，约 80 字——**就是翻译员工把外文段贴进来的自然用法，不带任何检索/编排指令**）：

```
把这段英文技术资料中文化，统一行业术语并核对型号：
The DC inverter rotary compressor modulates refrigerant flow via the electronic expansion valve (EEV), achieving part-load COP up to 6.5. Standard configuration for P-RC-WALL-15 and P-CC-VRV-360, with R410A charge of 1.8 kg and 28 kg per module respectively.

/agileac-rnd-plm-query
```

> **四层架构**（详见 `SCENARIO_AUTHORING_GUIDE.md`）：user composer 只写**业务目标 + 外文资料原文 + 技能 chip**。术语统一规则（首次出现括注英文缩写、型号段保留原文、参数单位按 SI、HP→kW 换算）、按 5 类术语检索多语术语与海外资料库、调 PLM 核对 P-RC-WALL-15 / P-CC-VRV-360 型号参数一致性——**全部由 Agent 模板 `agileac-rnd-01-translation` 的 `system_prompt` 承载**（见 `## 检索多语术语与海外资料库` / `## 翻译规则` / `## 输出格式` 三节），不写进用户提示词。任务 config 必须绑定 `template_agent_id = <agileac-rnd-01-translation 的 UUID>`，运行时 `load_config` 才会注入模板（trace `template` 出现、`template:true`）。技能留空从模板继承 `agileac-rnd-plm-query`；模型模板默认 `glm-5.2`（与 drawer 一致，无需覆写）。
>
> 若前端 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id` 复现（`SELECT id FROM agents WHERE slug='agileac-rnd-01-translation'`）。

> ⚠️ **关键 1**：`/agileac-rnd-plm-query` 必须从 `/` 菜单选中 chip，不能手敲文本。agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时 message 里写 `/agileac-rnd-plm-query` 也会被同款正则解析（见 §6）。
>
> ⚠️ **关键 2**：composer **必须粘贴真实外文原文**——RND-01 没有待翻译任务端点（`listPendingTranslations` 未实现），待翻译资料由翻译员工直接粘贴进 composer，更贴近真实工作流（翻译员手上就有外文段）。RAG 术语词典 + PLM 产品参数核对都围绕这段原文展开。
>
> ⚠️ **关键 3**：composer 写明型号段（P-RC-WALL-15 / P-CC-VRV-360）——让 agent 有明确 PLM 核对锚点，避免泛化。本体 identifiers.md 已写明产品款号前缀（P-RC- 家用 / P-CC- 商用）与示例值，agent 调 `getStyle`/`listBoms` 前读此表，杜绝 404；型号段保留原文不翻译（模板翻译规则已约束）。

#### 资源注入机制（任务运行时自动完成，无需配置）

任务运行时，agent runtime 会按 rnd-translator 的 scope 自动注入以下资源到 system prompt：

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | 按 scope 注入（组织级 33 含 PLM identifiers + 翻译组级 4） | 37 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出所有可调用的 mock 接口 | PLM 1 system / ~10 interfaces |
| **RAG** | 空数组 = 全集自动匹配；retrieve_rag 节点按 query 检索 top-k | 1 collection（多语术语与海外资料库），5 hits |
| **长期记忆** | 4 级（组织+部门+团队+个人）按权限聚合；load_memory 节点载入 | 若干 history + facts |
| **技能** | skill_ids 显式选 + /-mention 解析 | 1 skill（agileac-rnd-plm-query） |
| **记忆沉淀** | extract_memory 节点抽取本轮可沉淀事实写入个人级 Memory | 0~3 facts |

### 3.5 提交运行

按回车（或点发送按钮）提交。前端会：
1. `POST /api/v1/terminal/tasks` 创建任务（把 composer 里的内容作为 `message` 字段存档）；
2. `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}` —— **这才是真正发给 agent 的输入**。

> ⚠️ 实测：`/run` 的 `message` 才是 agent 看到的指令；任务创建时存的 `message` 不会被 agent 读到。前端做法是「同一段文本两次用」。手工调 API 记得 `/run` 也要带完整提示词。

### 3.6 观察 SSE 事件流

任务运行后，右侧 ChatView 会渲染 SSE 事件。事件类型与含义：

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载任务配置（model / skill_ids / template_agent_id / workspace） |
| `[trace]` (template) | 场景模板注入（必出，slug + chars） |
| `[trace]` (rag) | RAG 检索命中——多语术语与海外资料库被检索（术语词典 + 翻译样本） |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 组织本体 + 翻译组本体注入 system prompt |
| `[trace]` (data_interface) | 数据接口目录注入（按研发部权限，PLM 可见） |
| `[trace]` (skill) | /-mention 解析引用了哪个技能 |
| `[trace]` (memory/extract) | 记忆沉淀抽取（写个人级 Memory） |
| `[phase] llm #0/#1/#2` | 每个 LLM 调用轮次 |
| `[tool_call]` | agent 调用工具（PLM `listStyles`/`getStyle`/`listBoms` / `generate_docx`） |
| `[tool_result]` | 工具返回（ok / FAIL） |
| `[text]` | LLM 流式输出 token（直接渲染到对话气泡） |
| `[done]` | agent_loop 收口（带 usage 统计） |
| `[final]` | 任务结束，附 latency_ms + session_id |

> 终端前端 ChatView 目前只渲染 `text` / `tool_call` / `tool_result`；`trace` 事件保存在 assistant 消息的 `metadata_.traces` 里，管理后台或 `GET /terminal/tasks/{id}/messages` 可见。

典型 RND-01 运行约 3–5 分钟（2–3 轮 LLM + 3–4 次 tool 调用 + glm-5.2 推理 + 记忆/RAG 节点）。

---

## 4. 期望输出

agent 会输出三段 + 1 个附件：

### 4.1 中文化译文

```
直流变频转子压缩机通过电子膨胀阀（EEV）调节制冷剂流量，部分负荷 COP 可达 6.5。P-RC-WALL-15 与 P-CC-VRV-360 标配，R410A 制冷剂充注量分别为 1.8 kg 与 28 kg/模块。
```

> 术语统一：rotary compressor → 转子式压缩机（词典首选）；electronic expansion valve → 电子膨胀阀（EEV）；refrigerant → 制冷剂（非"冷媒"）；part-load COP 保留缩写。型号段 P-RC-WALL-15 / P-CC-VRV-360 / R410A 保留原文。

### 4.2 术语对照表

| 英文 | 中文（首选） | 备注 |
|---|---|---|
| DC inverter rotary compressor | 直流变频转子式压缩机 | 区分直流/交流变频 |
| electronic expansion valve (EEV) | 电子膨胀阀（EEV） | 首次出现括注缩写 |
| refrigerant flow | 制冷剂流量 | "制冷剂"非"冷媒" |
| part-load COP | 部分负荷 COP | 保留 COP 缩写 |
| R410A charge | R410A 充注量 | 型号段保留原文，单位 kg |

### 4.3 型号差异提示

| 项 | 原文 | PLM 实际 | 一致性 | 备注 |
|---|---|---|---|---|
| P-RC-WALL-15 R410A 充注量 | 1.8 kg | 1.8 kg | ✓ | 与 PLM 参数一致 |
| P-CC-VRV-360 R410A 充注量 | 28 kg/模块 | 28 kg/模块 | ✓ | 与 PLM 参数一致 |
| 单位换算 | — | — | — | 原文无 HP 单位，无需换算（1 HP ≈ 0.746 kW 备查） |

> 若原文出现 HP（马力）单位，agent 按翻译规则换算为 kW 并在括号内保留原值，如「1 HP（≈ 0.746 kW）」。

### 4.4 .docx 报告附件

agent 调 `generate_docx` 工具把上述三段打包成 `敏睿空调_多语技术资料翻译_YYYYMMDD.docx`（约 30 KB），可下载分发归档。

### 4.5 SSE trace 事件（演示时截图可证）

| trace | 含义 | 期望实测值 |
|---|---|---|
| `category=template` | 场景模板注入（必出） | slug=agileac-rnd-01-translation + chars |
| `category=rag` | RAG 检索命中 | 1 collection / ≥3 hits（retriever=vector，pgvector 余弦检索，覆盖术语词典 + 翻译样本） |
| `category=memory, subtype=load` | 长期记忆载入 | 若干 history + facts |
| `category=ontology` | 组织本体 + 翻译组本体注入 | 37 files |
| `category=data_interface` | 数据接口目录注入（按研发部权限） | 1 system / ~10 interfaces |
| `category=skill` | /-mention 引用技能 | 1 skill（agileac-rnd-plm-query） |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | 0~3 facts |

---

## 5. 故障排查

### 5.1 模型选择器里没有 `glm-5.2`
- 智谱 AI provider 未配或 `supported_models` 不含 `glm-5.2`。
- 修复：管理端「敏睿空调」组织 → LLM Provider 页配智谱 AI provider（`supported_models` 含 `glm-5.2`）+ 路由策略 `model_pattern=glm-*` 指向它，重跑 `seed_agileac_org.py`。

### 5.2 提示词里 `/agileac-rnd-plm-query` 没被识别
- 必须从 `/` 弹窗里选中 chip，不能手敲纯文本。
- 自检：保存的 task.message 里这段应该是结构化 chip 标记，不是 plain text。

### 5.3 `[tool_result FAIL]` PLM 接口调用失败
- mock 网关未起或 API key 不匹配。
- 自检：
  ```bash
  curl -s http://localhost:8010/plm/styles -H "X-API-Key: plm-agileac-demo-key" | head
  curl -s "http://localhost:8010/plm/boms?style_code=P-RC-WALL-15" -H "X-API-Key: plm-agileac-demo-key" | head
  ```
  均应返回 JSON。

### 5.4 `rnd-translator` 看不到 PLM 数据接口 / 多语术语 RAG
- 团队级 scope 授权未配置——`seed_agileac_mock_connectors.py` 没把研发组技能 `agileac-rnd-plm-query` 按 `scope_type=department, scope_id=rnd_dept.id` 配好；或 `seed_agileac_rag.py` 没把多语术语 RAG 按 `scope_type=team, scope_id=rnd-translation_team.id` 落库。
- 自检：`GET /api/v1/terminal/resources`（rnd-translator token）的 `skills` 应含 `agileac-rnd-plm-query`，`rag_collections` 应含「多语术语与海外资料库」（scope=team, rnd-translation）。
- 修复：重跑 `seed_agileac_mock_connectors.py` + `seed_agileac_rag.py`。

### 5.5 agent 输出「我没有收到任务」
- 检查 `/run` 请求体里 `message` 是否为空——必须把完整提示词（含外文原文 + `/agileac-rnd-plm-query` chip）作为 `message` 发送。

### 5.6 运行很久没动 / latency > 5 分钟
- glm-5.2 单轮推理慢，多轮 tool 调用累计 3–5 分钟正常。超过 10 分钟大概率卡住，看 `docker logs ai_infra_backend --tail 100`。

### 5.7 trace `rag` 显示 `retriever=keyword_fallback`
- 向量 embedding 不可用（org 未配 embedding provider 或 `text-embedding-v4` 不可达），RAG 退化为 CJK 关键词检索。
- 修复路径：
  1. 管理端「敏睿空调」组织配 OpenAI 兼容 embedding provider（如 aliyun `text-embedding-v4`）；
  2. 若 chunks 已存在但 embedding 列为 NULL，跑 `reembed_agileac_rag.py --collection-name "多语术语与海外资料库"` 回填；
  3. 自检：`SELECT COUNT(*) FROM rag_chunks WHERE collection_id=<多语术语与海外资料库 id> AND embedding IS NOT NULL` 应等于 chunk 总数。

### 5.8 agent 没主动触发 RAG 检索
- 编排（检索多语术语与海外资料库）由模板 `system_prompt` 的 `## 检索多语术语与海外资料库（RAG，必做）` 节承载，**不应靠用户提示词加 cue**。若纯原文版（§3.4）RAG 没触发：先确认 `load_config template:true` + `trace template` 出现（模板没注入则编排丢了）；再确认模板 `system_prompt` 含"检索多语术语与海外资料库"指令；最后看 retrieve_rag 节点 query 嵌入是否命中——embedding provider 未配时走 keyword_fallback，原文含 "compressor/EEV/refrigerant/COP" 等英文术语仍应命中术语词典 chunk。

### 5.9 `tool_call` args 全 `{}`
- 现象：所有 `tool_call.arguments={}`，需要参数的端点（如 `getStyle(style_code=...)`）返回 500。
- 根因：`_build_tools`（`app/agents/graph/nodes.py`）的 manifest 占位 schema 覆盖问题（starclothing PD-2 栽过此坑，详见 `SCENARIO_AUTHORING_GUIDE.md` §6.10）。
- 修复：跑完一次后看 SSE 解析里的 `tool_call` args，**只要有一条非 `{}`** 就说明 `_build_tools` 工作正常；如果全是 `{}` 立即查 `nodes.py` `_build_tools`。

### 5.10 path 参数端点（`getStyle`）返回 404 `{style_code} not found`
- 现象：agent 调 `getStyle(style_code="P-RC-WALL-15")` 返回 `{style_code} not found`——path 占位符未替换。
- 影响：**不阻塞闭环**。agent 自主降级到 `listStyles(keyword)` / `listBoms(style_code=...)`（query 参数端点，不受影响），仍能拿到完整产品参数做型号核对。
- 修复（可选）：在技能 wrapper 里按 OpenAPI path 占位符替换路径参数。非阻塞性问题，本期演示按「agent 自主降级」路径通过。

### 5.11 memory/extract 抽取 0~3 facts
- 现象：`trace memory/extract` 多数情况下 `facts: 0`。
- 影响：非阻塞，本轮输出已完整；长期记忆通道跨任务复用弱。修复（可选）：调整 `extract_memory` 的 prompt，让其显式抽取结构化事实（型号 + 参数 + 术语三元组）。

### 5.12 术语未查 RAG 直接杜撰译法
- 现象：译文出现"冷媒"而非"制冷剂"、或术语译法与词典不符。
- 根因：agent 没检索或忽略术语词典 RAG chunk，靠模型先验杜撰。
- 修复：确认 `load_config template:true` + 模板 `system_prompt` 含"检索多语术语与海外资料库"指令；embedding 未配时走 keyword_fallback，原文含英文术语仍应命中术语词典 chunk。

---

## 6. 附：手工调 API 复现

不用前端的话，可以用 curl 走一遍：

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agileac","username":"rnd-translator","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 RND Agent 模板 id（任务 config 必须绑定 template_agent_id）
TPL_ID=$(docker exec ai_infra_backend python3 -c "
import asyncio, asyncpg
async def m():
    c=await asyncpg.connect('postgresql://ai_infra:ai_infra@postgres:5432/ai_infra')
    r=await c.fetchrow(\"SELECT id FROM agents WHERE slug='agileac-rnd-01-translation'\")
    print(r['id']); await c.close()
asyncio.run(m())")

# 3) 创建任务（绑定模板；skill_ids 留空从模板继承，model=glm-5.2）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"RND-01 多语翻译\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（外文原文 + /agileac-rnd-plm-query chip 作为 message）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"把这段英文技术资料中文化，统一行业术语并核对型号：\\nThe DC inverter rotary compressor modulates refrigerant flow via the electronic expansion valve (EEV), achieving part-load COP up to 6.5. Standard configuration for P-RC-WALL-15 and P-CC-VRV-360, with R410A charge of 1.8 kg and 28 kg per module respectively.\\n\\n/agileac-rnd-plm-query\",\"stream\":true}"
```

短 composer 提示词文本见 §3.4（翻译规则/RAG cue/输出格式由 RND Agent 模板 `system_prompt` 承载，不在 composer 里）。

---

## 7. 验收要点（演示前自检）

- [ ] `rnd-translator` 能登录 `/agileac/terminal/login`，左上角显示「研发部」
- [ ] `GET /api/v1/terminal/resources`（rnd-translator token）的 `skills` 含 `agileac-rnd-plm-query`（dept: rnd）
- [ ] `rag_collections` 含「多语术语与海外资料库」（scope=team, rnd-translation）——**不应**含其他部门级 RAG（如「售后故障与维修知识库」「产品参数与卖点库」），验证团队级资源隔离
- [ ] `data_interfaces` 含 PLM 端点（不含 SCM/ERP/HRM/MES/CRM——非本部门权限）
- [ ] `load_config` 事件显示 **`template:true`**（绑定了 template_agent_id）
- [ ] `trace category=template` 出现（slug=`agileac-rnd-01-translation` + chars）
- [ ] 任务跑完，SSE 6 类 trace 全部出现（rag + memory.load + ontology + data_interface + skill + memory.extract）
- [ ] `retrieve_rag` 显示 `retriever=vector`，hits ≥ 1，命中术语词典 chunk（未配 embedding 则 `keyword_fallback`，仍应命中含英文术语关键词的 chunk——见 §5.8）
- [ ] `tool_call` args 不全 `{}`（至少 `getStyle(style_code=P-RC-WALL-15)` 或 `listBoms(style_code=...)` 这类必传参端点要带参）
- [ ] no-guessing：agent 用对产品款号前缀（P-RC- 家用 / P-CC- 商用）与物料前缀（M-COMP-/M-EVAP- 等），不把岗位码 P-RND 当产品款号
- [ ] 输出含三段（中文化译文 / 术语对照表 / 型号差异提示）+ 1 个 .docx 附件
- [ ] 译文术语统一（rotary compressor→转子式压缩机、refrigerant→制冷剂非冷媒），型号段 P-RC-WALL-15/P-CC-VRV-360/R410A 保留原文
