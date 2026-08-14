# 星途服装 · 场景 Demo 编写指南

> 本文复盘 7 个场景 demo（PD-1～PD-3 / SC-1～SC-4）从无到有的搭建过程，沉淀
> 出一套可复用的方法论，让后续新增场景 demo 少走弯路。所有「坑」都是亲身踩过
> 才记录进来的，每一条都有具体症状、根因、规避方法。

---

## 0. 全局架构回顾

```
┌───────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  前端 (Vite+React) │  │ 后端 (FastAPI)   │  │ Mock (FastAPI)    │
│  :5173 / :8000    │  │ ai_infra_backend │  │ ai_infra_mock     │
│                   │←→│ :8000            │←→│ :8010             │
│  管理端 + 终端    │  │  LangGraph       │  │  5 系统 PLM/SCM/  │
│                   │  │  agent runtime   │  │  ERP/MES/CRM      │
└───────────────────┘  └──────────────────┘  └──────────────────┘
                              │
                              ↓
                       ┌──────────────┐
                       │ PostgreSQL   │
                       │ + pgvector   │
                       └──────────────┘
```

| 组件 | 角色 |
|---|---|
| 管理端（admin token） | 配置组织 / 用户 / Provider / APIKey / Agent / 技能 / 本体 / RAG |
| 终端（user-type JWT） | 业务用户跑任务，按 scope 自动注入资源 |
| LangGraph agent runtime | `load_config → retrieve_rag → load_memory → agent_loop → save_memory → extract_memory → judge → write_run_log` |
| Mock 多租户 | `X-API-Key` 区分租户：`plm-starclothing-demo-key` / `scm-starclothing-demo-key` / … |

---

## 1. 场景设计分类

按交付形式分两类，**新建场景前先决定走哪条路**：

### 1.1 终端任务方式（推荐用于"业务用户视角"场景）

适用：演示业务人员使用 AI 完成日常工作（监管 / 评审 / 排程 / 对账）。

- 用户身份登录终端，新建任务，配置模型 + 技能，写提示词，运行。
- 资源（本体 / RAG / 记忆 / 数据接口）按用户 scope 自动注入，无需在 TaskConfigDrawer 显式配置。
- 交付物：`<scenario>_terminal_task.md`（操作文档），脚本不需要。

参考：`pd1_terminal_task.md`。

### 1.2 Shell 脚本方式（推荐用于"超管批量调起 agent"场景）

适用：演示平台运营 / 调度类场景，agent 配置已固化、需要可重复运行。

- 用超管（或组织级 admin）token，调 `POST /api/v1/agents/{slug}/runs` SSE 流式接收。
- 交付物：`<scenario>_<feature>.sh` + 复用 `_common.sh`。

参考：`pd2_*.sh` / `sc1_*.sh` 等 6 个脚本。

> ⚠️ **不要混用**：终端任务用 user-type JWT，shell 脚本用 admin token；token
> 类型错了会出现"scope 拒绝"或"找不到组织"等隐晦错误。

---

## 2. 标准搭建流程（7 步法）

### 第 1 步：场景定义

回答 4 个问题：

1. **业务目标**：AI 替代了哪些人工动作？AI 增值在哪？（写进 README §5 的表格）
2. **数据依赖**：要调哪些 mock 系统的哪些端点？（先去 `mock/mock/systems/<sys>/routes.py` 确认端点存在 + 数据足够）
3. **资源依赖**：是否需要本体 / RAG / 记忆？需要新本体或新 RAG 集合吗？
4. **执行模式**：`ask`（只读单轮）/ `plan`（出方案不执行）/ `craft`（多轮自主执行）。绝大多数业务场景用 `craft`。

### 第 2 步：seed 顺序（按依赖链，不可乱序）

```
seed_starclothing_apparel.py            # 1. 组织/部门/用户/路由策略/org APIKey（无 model alias）
seed_starclothing_mock_connectors.py    # 2. 5 mock 连接器 + 技能 + 数据接口（依赖 1）
seed_starclothing_ontology.py           # 3. 本体文件（独立）
seed_starclothing_defect_rag.py          # 4. RAG 集合（独立，但若用 embedding 必须先配 provider）
seed_starclothing_agents.py              # 5. 7 个业务 Agent 配置（依赖 1+2，引用技能）
```

> ⚠️ **关键**：每个 seed 脚本必须 **幂等 + 增量**。新增数据只追加，已有数据按
> 业务主键 `slug` / `code` 去重，**绝不能 DROP**。星途 demo 用的去重模式：
> `select 现有记录 by slug → if name mismatch → rename in place`，避免遗留
> "星图服装" 旧名残留。

### 第 3 步：seed_starclothing_apparel.py（基础组织数据）

必须包含：
- 组织（slug=`starclothing`，name=`星途服装`）—— slug 一旦定下不要改，name 可改
- 部门 / 团队 / 用户（演示账号 `sjp` / `12345678`，role=member，绑定到「产品开发部」）
- 路由策略（`model_pattern` 如 `claude-*` / `gpt-*` / `deepseek-*`，按真实模型 id 匹配）
- **演示用模型**：agent 的 `model_alias` 字段直接填真实模型 id（如 `glm-5.2` / `claude-sonnet-4`）；终端下拉直接列真实 id，无别名解析层。新场景用别的模型，agent seed 里直接写真实 id 即可。
- 组织级 APIKey：每条 key 用稳定的 `key_name`（如「星途服装 默认 Key」），
  脚本里**用 `in_([new_name, legacy_name])` 查重**，保留最早的 key、重命名
  in-place、撤销重复 key。**不要简单 revoke**，否则旧 demo 脚本里硬编码的
  key 会失效。

### 第 4 步：seed_starclothing_mock_connectors.py（数据接口）

每个 mock 系统（PLM/SCM/ERP/MES/CRM）：
- 创建 `DataSystem`（name = `<系统中文名>（星途）`）
- 创建 `Connector`（按 `mock_starclothing_<sys>_key`）
- 创建 `SkillFolder`（slug=`starclothing-<sys>-query`，name=`星途 · <系统中文名> 查询技能`）
- 拉取 mock 的 OpenAPI 自动同步 `DataInterface`

> ⚠️ **星图→星途 rename 经验**：如果之前已 seed 过「星图」版本，rename 不能
> 简单 DELETE+INSERT，因为 `DataInterface` 外键 + skill slug 都依赖原 record。
> 用 `select by name.in_([new_name, legacy_name])` → `if found: rename in place`，
> SkillFolder 同理用 `if name != new_name: rename`。

### 第 5 步：seed_starclothing_ontology.py（本体）

- 在 `mock/openapi/ontology/<domain>/` 下放 README + object-types + link-types + action-types
- seed 脚本遍历文件夹，每个文件 → `OntologyFile` 记录
- scope_type=organization，scope_id=org.id
- agent 运行时按用户 scope 自动注入 12 个文件到 system prompt

> 经验：本体文件命名固定 `README.md` / `object-types.md` / `link-types.md` /
> `action-types.md`，前端管理界面按这 4 个名字分组展示。不要起别的名字。

### 第 6 步：seed_starclothing_defect_rag.py（RAG）

- 创建 `RagCollection`（embedding_model 必须先在 org 配好 embedding provider）
- `chunk_size=512` / `chunk_overlap=64`（适合中文长文，过小切片碎、过大检索精度差）
- 文档分块 → 每个 chunk 调 `llm_client.embed()` 写 embedding 列
- **`_EMBED_BATCH` 上游批次上限**：Aliyun `text-embedding-v4` 是 **10/batch**，
  OpenAI `text-embedding-3-small` 是 **2048/batch**。`rag_service.py` 当前
  写死 `_EMBED_BATCH = 8`（保守值），换 provider 时记得检查这个常量。
- 如果跑完发现 chunks embedding 列全为 NULL：用
  `demo/starclothing/scripts/reembed_defect_rag.py`（参数化 collection_id 后可改名通用化）一次性回填。

### 第 7 步：seed_starclothing_agents.py（agent 配置）

- 每场景一个 agent：`slug=starclothing-<scenario>-<feature>`，绑技能 / 模型 / exec_mode
- `system_prompt` 里写明：归口部门 / 任务边界 / 必调端点 / 输出格式 / 闭环要求
- 如果是终端任务方式（PD-1），agent 不需要在 seed 里建，直接在终端新建任务时
  `exec_mode=craft` + `skill_ids=[<从 /-mention 选>]` 即可

> 经验：`system_prompt` 要写**闭环要求**，比如"QC=FAIL 必须检索 RAG 找规避要点"。
> 没写的话 agent 可能跳过 RAG 调用，导致 trace 事件缺一项。

---

## 3. 终端任务方式 · 4 个关键陷阱

只有 PD-1 用了终端任务方式，4 个坑都踩过：

### 3.1 `/run` 的 `message` 才是 agent 看到的输入

任务创建时 `POST /terminal/tasks` 的 `message` 字段被存档但 agent 不读。
真正发给 agent 的是 `POST /terminal/tasks/{id}/run` body 里的 `message`。

- 前端做法：同一段提示词两次用（创建时存档 + run 时发）。
- 手工 curl：记得 `/run` 也带完整提示词，否则 agent 输出"我没有收到任务"。
- 自检：`GET /terminal/tasks/{id}/messages` 看 user 消息的 content 是否完整。

### 3.2 `/-mention` 必须 chip，不能手敲文本

`/` 弹出技能菜单后选中才会插入结构化 chip 标记。手敲 `/starclothing-plm-query`
纯文本会被当成普通字符，agent 运行时不会解析为技能调用。

- 自检：保存的 `task.message` 里技能段应该是 chip 标记（不是 plain text）。
- 前端 `MentionInput` 组件负责解析；纯 curl 测时需手动构造 chip 标记。

### 3.3 提示词必须**显式写出**要触发的 RAG / 本体 / 记忆

retrieve_rag 节点的 query 是整段 user message，命中靠语义相关性。如果提示词
只写"扫逾期订单"，glm-5.2 的 query 嵌入可能命中度不够，retrieve_rag 不会主动
检索缺陷知识库。

**修复模板**：在提示词里加一句：

> "对 QC=FAIL 的款号，必须检索「服装缺陷知识库」RAG 找出该缺陷类型的规避要点"

明确写出"检索服装缺陷知识库"字样，才能稳定触发 RAG 节点。

### 3.4 资源注入靠 scope 自动完成，不要在 TaskConfigDrawer 里手配

`_load_config_general` 节点会按 user scope 自动注入：
- 本体：按组织 scope 全集注入
- RAG：`rag_collection_ids=[]`（空数组）= 自动匹配用户 scope 内全部 RAG
- 记忆：按「组织+部门+团队+个人」4 级 scope 聚合
- 数据接口：`scope_service.list_data_interfaces_for_user` 按权限全量列出

TaskConfigDrawer 里只配 `workspace` / `model_alias` / `exec_mode` / `skill_ids`
（显式选技能是因为 /-mention 需要知道绑定哪个技能）。其他留空 = 自动。

> 反例：如果在 drawer 里手填 `rag_collection_ids=[某 collection]`，反而限制
> 了 scope 自动匹配；除非要限定 RAG 范围，否则保持空数组。

---

## 4. Shell 脚本方式 · 复用 `_common.sh`

```bash
source "$(dirname "$0")/_common.sh"

BACKEND_HOST="${BACKEND_HOST:-localhost}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
ADMIN_USER="${ADMIN_USER:-root}"
ADMIN_PASS="${ADMIN_PASS:-Sjp19831209}"
ORG_SLUG="${ORG_SLUG:-starclothing}"
AGENT_SLUG="${AGENT_SLUG:-starclothing-pd2-fabric-library}"   # ← 改这里

login_admin                                   # 拿 admin token + org_id
AGENT_ID=$(resolve_agent_id "$AGENT_SLUG")   # 解析 agent id

run_agent_sse "$AGENT_ID" "<完整提示词>"     # SSE 流式打印
```

`_common.sh` 提供：`login_admin` / `resolve_org_id` / `resolve_agent_id` /
`run_agent_sse`（解析 SSE 并按 `[step] / [phase] / [text] / [tool_call] /
[tool_result] / [final] / [error]` 分行打印）。

---

## 5. SSE trace 事件 · 资源调用的"证据"

agent 运行时会发射 6 类 `trace` 事件，是"调用了本体 / 知识库 / 记忆 / 数据接口"
的可视化证据。终端前端 ChatView 目前**只渲染** `text` / `tool_call` /
`tool_result`，trace 落在 `TaskMessage.metadata_.traces` 里，要从管理后台或
`GET /terminal/tasks/{id}/messages` 看。

| trace | 含义 | 出现条件 |
|---|---|---|
| `category=rag` | RAG 检索命中 | retrieve_rag 节点，必须有 `rag_collection_ids` 非空 |
| `category=memory, subtype=load` | 长期记忆载入 | load_memory 节点 |
| `category=ontology` | 组织本体注入 | load_config 时按 scope 注入 |
| `category=data_interface` | 数据接口目录注入 | load_config 时按用户权限列出 |
| `category=skill` | /-mention 引用技能 | 用户提示词里有 chip |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | extract_memory 节点 |

> **验证清单**：新场景跑完必须检查 SSE 含全部应有的 trace。缺哪个就回查对应
> 节点的触发条件——常见缺失：rag（提示词没明写检索） / skill（手敲文本非 chip）。

`retriever=vector` vs `keyword_fallback`：trace 的 `retriever` 字段指示 RAG
走的是 pgvector 向量检索还是 CJK 关键词兜底。**两者都能命中**，但 vector 精度
高。如果一直显示 keyword_fallback，看后端日志
`rag_embed_failed_fallback_keyword` 警示，根因通常是 org 未配 embedding provider。

---

## 6. 常见故障与排查（按踩坑顺序）

### 6.1 seed 脚本 slug 不一致

症状：`未找到组织 slug=<期望值>`

根因：历史上有过 slug 重命名（早期 demo 用 `xingtu`，后统一改为 `starclothing`，
文件夹 / mock 租户 / API key / 技能 slug 前缀全部对齐）。新组织拷贝 seed 脚本
后若忘改 `ORG_SLUG` 默认值，会找不到组织。

修复：所有 seed 脚本顶部用
`ORG_SLUG = os.getenv("MOCK_SEED_ORG_SLUG", "starclothing")`，环境变量可覆盖。
新组织建议把 `"starclothing"` 默认值改成自己的 slug。

### 6.2 旧 API key 残留导致 MultipleResultsFound

症状：`seed_starclothing_apparel.py` 抛 `MultipleResultsFound` 在 ApiKey 查询。

根因：组织改过名（星图→星途），同一个 key_name 在 db 里有两条 active 记录，
`scalar_one_or_none()` 抛错。

修复：脚本里改用 `.scalars().all()` 取列表，保留 created_at 最早的、撤销其他
重复行；并对保留行做 in-place rename（`keep.key_name = kdef["key_name"]`）。
**不要简单 revoke 旧 key**——下游 demo 脚本里硬编码的 key 会失效。

### 6.3 终端任务"agent 没收到任务"

症状：SSE 输出"我没有收到任务"或 generic fallback 文本。

根因：`POST /terminal/tasks` 创建时存了 `message`，但 `POST /terminal/tasks/{id}/run`
的 body 里 `message=""` 空，agent 读不到指令。

修复：`/run` 的 body 必须带完整提示词作为 `message`。

### 6.4 `/starclothing-plm-query` 没被识别为技能

症状：SSE 没有 `trace category=skill`，agent 也没调技能端点。

根因：手敲 `/starclothing-plm-query` 文本，不是 chip 标记。

修复：从 `/` 弹窗里选中 chip。自检 `task.message` 里该段应为结构化 chip。

### 6.5 RAG 显示 `keyword_fallback`

症状：trace `retriever=keyword_fallback`，title="知识库检索（关键词兜底）"。

根因（按出现频率排）：
1. org 没配 embedding provider（`text-embedding-v4` 不可达）→
   后端日志 `rag_embed_failed_fallback_keyword error="no provider available
   for model 'text-embedding-v4' in org ..."`
2. `_EMBED_BATCH` 超上游批次上限（Aliyun 是 10），ingest 时静默失败导致
   chunks embedding 列全 NULL
3. provider 配了但 key 失效 / 网络不通

修复：
1. 管理端配 `aliyun-all-openai` 或其他 OpenAI 兼容 embedding provider
2. `rag_service.py` `_EMBED_BATCH` 改为 8
3. 跑 `reembed_defect_rag.py` 回填 NULL chunks
4. 自检 `SELECT COUNT(*) FROM rag_chunks WHERE collection_id=<id> AND embedding IS NOT NULL`
   应等于 chunk 总数

### 6.6 agent 不主动检索 RAG

症状：trace 缺 `category=rag`，或检索了但 hits=0。

根因：retrieve_rag 节点的 query 是整段 user message，靠语义相关性命中。
如果提示词只写"扫逾期订单"没提"缺陷知识库"，glm-5.2 的 query 嵌入可能命中度不够。

修复：提示词里**显式写出"检索服装缺陷知识库"字样**。

### 6.7 LLM 调用 403 / 超时

症状：SSE 显示 `[step] load_config → [phase] llm #0 → [final]` 但无 `[text]`。

根因：LLM Provider 未配 / API Key 失效 / 上游限流。

修复：管理端 → 组织 → LLM Provider 页配 provider；确保真实模型 id（如 `claude-sonnet-4` /
`glm-5.2`）在 provider 的 `supported_models` 里且路由策略（`model_pattern`）指向可用 provider；自检
`GET /api/v1/terminal/models` 的 `models` 含目标模型 id。

### 6.8 工具调用 404 / FAIL

症状：`[tool_result FAIL] tool error: ...`

根因：mock 系统未起 / API Key 不匹配 / 数据接口 slug 变了但 skill 未同步。

修复：
```bash
docker ps | grep ai_infra_mock
curl -s http://localhost:8010/plm/styles -H "X-API-Key: plm-starclothing-demo-key" | head
```
如果 mock 端点正常但 agent 调用失败，重跑 `seed_starclothing_mock_connectors.py`
同步数据接口到最新 mock schema。

### 6.9 运行很久没动 / latency > 5 分钟

症状：SSE 卡住无新事件，或单次 latency > 10 分钟。

根因：glm-5.2 单轮推理慢 + 多轮 tool 调用累计。正常 PD-1 跑 3–4 轮 LLM + 6–7
次 tool 调用约 5–7 分钟。超过 10 分钟大概率卡住。

修复：`docker logs ai_infra_backend --tail 100` 看后端日志，常见是上游 LLM
限流或 mock 端点 hang。

### 6.10 工具调用全 `args={}` / 必传参端点 FAIL 500

症状：所有 `tool_call` 的 `arguments={}`，需要参数的端点（如
`compareQuotations` / `estimateLeadtime` / `getLeadtimeDiff`）返回 500；
不带参数也能跑的端点（如 `listCapacityCalendar`）正常。

根因：`_build_tools`（`app/agents/graph/nodes.py`）原代码用
`manifest.parameters or ep.params_schema`，但 seed 脚本生成的
`manifest.parameters = {"type":"object","properties":{}}` 是**占位空 schema**
（非 None dict），truthy 判定让它覆盖了 `ep.params_schema`。LLM 看到工具
schema 无 properties 就不传参，可选参数端点跑全量查询、必传参数端点崩。

修复：`_build_tools` 改为检测 `manifest.parameters.properties` 是否真有字段，
没有就 fallback 到 `ep.params_schema`。已 fix；若重现检查 `nodes.py:491` 附近。

> ⚠️ **新场景搭建必查**：跑完一次后看 SSE 解析里的 `tool_call` args，**只要
> 有一条非 `{}`** 就说明 `_build_tools` 工作正常；如果全是 `{}` 立即查 nodes.py。

### 6.11 `getLeadtimeDiff` 返回空 / 无快照对比

症状：`getLeadtimeDiff` 返回 `{}` 或不含 `delta_days` 字段。

根因：mock 的 `leadtime_snapshots` 表对当前 supplier+material 组合没有快照
（`since` 之后无记录）。

影响：agent 会自动 fallback 到 `estimateLeadtime`（cached:false）实时总交期 vs
报价交期算 Δ，结果同样可信——`estimateLeadtime` 本身就是 PD-2 实时性演示点。

修复（可选）：在 `mock/mock/systems/scm/data.py` 的 `leadtime_snapshots` 里
补几条对应 supplier_code 的历史快照，让 `getLeadtimeDiff` 能返回结构化对比。

---

## 7. 验收清单（新场景上线前必过）

- [ ] seed 脚本幂等：跑第二遍无报错、无重复行
- [ ] 演示账号能登录终端：`sjp / 12345678` 落到 `/starclothing/terminal`
- [ ] 模型下拉里能看到真实模型 id（如 `glm-5.2` / `claude-sonnet-4`）
- [ ] 任务配置后 `exec_mode=craft` 起作用（agent 自主多轮）
- [ ] SSE 6 类 trace 全部出现（rag / memory.load / ontology / data_interface /
      skill / memory.extract）
- [ ] `tool_call` args 不全是 `{}`（至少必传参端点要带 material_code 等参数）
- [ ] RAG trace 显示 `retriever=vector`（不是 keyword_fallback）
- [ ] agent 调用的端点都在 mock 里存在且返回 ok
- [ ] 输出格式符合场景定义（表格 / 推送清单 / .docx 附件）
- [ ] 提示词里"必须检索 RAG"等关键句被 agent 执行（trace 命中）
- [ ] 操作文档（`<scenario>_terminal_task.md` 或 .sh）写完且可复现
- [ ] README.md 场景矩阵表格更新

---

## 8. 文件清单 / 职责

```
demo/starclothing/
├── README.md                       # 场景总览 + 演示矩阵 + 故障排查
├── SCENARIO_AUTHORING_GUIDE.md     # 本文：搭建方法论
├── _common.sh                       # shell 脚本方式公共函数
├── pd1_terminal_task.md             # PD-1 终端任务操作文档（推荐演示方式）
├── pd1_overdue_push.sh              # PD-1 旧脚本（保留对照）
├── pd2_fabric_leadtime.sh           # PD-2～SC-4 shell 脚本
└── ...

demo/starclothing/scripts/                  # seed 脚本（docker cp 进容器后位于 /app/scripts/）
├── seed_starclothing_apparel.py           # 组织 / 用户 / 路由 / APIKey（无 model alias）
├── seed_starclothing_mock_connectors.py   # 5 mock 连接器 + 技能 + 数据接口
├── seed_starclothing_ontology.py          # 本体文件
├── seed_starclothing_defect_rag.py        # 服装缺陷知识库 RAG
├── seed_starclothing_agents.py            # 7 个业务 Agent 配置
└── reembed_defect_rag.py            # 维护脚本：NULL embedding 回填

llm_router/backend/app/services/
└── rag_service.py                   # _EMBED_BATCH=8（Aliyun 10/batch 限制）

mock/mock/systems/<sys>/              # mock 数据 + 路由（5 系统）
mock/openapi/ontology/<domain>/      # 本体源文件
```

---

## 9. 经验法则（一句话总结）

1. **slug 定下就不要改**，name 改了用 in-place rename，不要 DROP+INSERT。
2. **API key 用 rename 不 revoke**，保留最早的、撤销重复的。
3. **`/run` 的 message 才是 agent 输入**，任务创建时的 message 不被读。
4. **`/-mention` 必须 chip**，手敲文本不会被解析为技能。
5. **提示词显式写出"检索 X 知识库"**，否则 retrieve_rag 不主动触发。
6. **资源靠 scope 自动注入**，TaskConfigDrawer 只配 workspace / model / exec_mode / skill_ids。
7. **`_EMBED_BATCH` 受上游批次上限约束**（Aliyun 10 / OpenAI 2048），换 provider 必查。
8. **trace 6 类必须全有**，缺哪类就回查对应节点触发条件。
9. **seed 脚本幂等 + 增量**，绝不 DROP，新增只追加。
10. **新场景跑完按 §7 验收清单全过**，再合并到 main。
11. **`tool_call` args 不能全 `{}`**：跑完一次看 SSE 解析，所有 args 都是 `{}` 说明
    `_build_tools` 的 schema 选择又退化到 manifest 占位 schema 了，立即查
    `app/agents/graph/nodes.py` `_build_tools`（PD-2 搭建时栽过此坑）。
12. **必传参端点 mock 不能裸跑**：mock 的 critical 端点（如
    `compareQuotations` / `estimateLeadtime`）若 mock 实现假设参数必传、空参
    调用直接 raise，会触发 500；mock 端要么 422 要么兜底返回空，**不要 500**。
