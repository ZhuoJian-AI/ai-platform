# MKT-01 营销内容与培训课件 · 终端任务演示

> 市场部内容组 `mkt-specialist` 登录终端，新建任务、配置 `glm-5.2` + `craft`、`/agileac-mkt-plm-crm-query` 选技能、写提示词、运行，agent 自主多轮调用 PLM 产品卖点 + CRM 客户画像 + 营销与竞品情报库 RAG，为指定产品生成营销内容三段：卖点提炼 + 竞品对比、海报文案 + 视频脚本、课件大纲 + PPT 框架 + 考题。
>
> **员工 vibe working 视角**：AI 是市场部的副驾驶，批量产出营销内容素材，**员工制作后由员工投放**——AI 不对终端客户。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 敏睿空调（slug = `agileac`） |
| 用户名 | `mkt-specialist` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |
| 部门 | 市场部 · 内容组 |

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）+ `ai_infra_postgres` 容器在跑。
2. **数据已 seed**（按 `README.md` §9 顺序执行）：
   - `seed_agileac_org.py`（含 `mkt-specialist` 用户 + 市场部 + 内容组）
   - mock 6 系统 agileac tenant 数据已内置（`mock/mock/systems/*/data.py` 的 `_build_agileac`），mock 容器重启即生效，无需独立 seed 脚本
   - `seed_agileac_mock_connectors.py`（含部门级技能 `agileac-mkt-plm-crm-query` + 数据接口按市场部 scope 授权 PLM 卖点 + CRM 客户画像只读端点）
   - `seed_agileac_ontology.py`（33 组织级含 PLM/CRM 各域 `identifiers.md` + 市场部 4 文件 = 37 个本体文件对该用户可见——org scope 资源对所有部门用户可见）
   - `seed_agileac_rag.py`（含「营销与竞品情报库」部门级 RAG，scope=`marketing`，按 metadata.chunk_type 分段：selling_points / competitor / poster_template / courseware_template）
   - `seed_agileac_agents.py`（含 `agileac-mkt-01-marketing-content` agent 模板配置，四层架构 system_prompt）
3. **glm-5.2 已可用**：组织已配智谱 AI provider，`supported_models` 含 `glm-5.2`。
   - 自检：`GET /api/v1/terminal/models`（用 mkt-specialist token）应在 `models` 里看到 `glm-5.2`。
4. **mkt-specialist 账号已存在且 active**：
   ```bash
   docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
     "SELECT username, is_active FROM users WHERE username='mkt-specialist';"
   ```
5. **PLM/CRM mock 端点正常**：
   ```bash
   curl -s "http://localhost:8010/plm/styles" -H "X-API-Key: plm-agileac-demo-key" | head
   curl -s "http://localhost:8010/crm/customers" -H "X-API-Key: crm-agileac-demo-key" | head
   ```
   应返回 JSON 列表。
6. **营销与竞品情报库向量通道正常**：
   ```bash
   docker exec ai_infra_backend python -c "
   from app.rag.service import RAGService
   s = RAGService()
   c = s.get_collection_by_name('营销与竞品情报库')
   print('chunks:', c.chunk_count, 'embedded:', c.embedded_count)
   "
   ```
   应输出 `chunks: ~60 embedded: ~60`（关键是 `embedded == chunks`）。若 `embedded < chunks`，跑 `reembed_agileac_rag.py --collection-name "营销与竞品情报库"` 回填。

> ⚠️ MKT-01 关键依赖 4 件事：PLM `getStyle`/`getProductSellingPoints` + CRM `listCustomers` 端点 + 营销与竞品情报库 RAG 向量通道（4 类 chunk 按 metadata.chunk_type 区分）+ `_build_tools` 修复（确保 `tool_call.arguments` 不为 `{}`）。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/agileac/terminal/login
```

- 用户名：`mkt-specialist`
- 密码：`12345678`

登录后落到 `/agileac/terminal`。左上角应显示 `mkt-specialist` + 组织「敏睿空调」 + 部门「市场部」。

> 终端使用 **user-type JWT**（与超管 token 不同，scope 仅限本部门 + 组织级资源可见）。

### 3.2 新建任务

点左栏「New Task / 新建任务」按钮，进入任务编辑器（HomeView composer）。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧 ⚙️ 设置按钮，打开 TaskConfigDrawer，配置 4 项：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `mkt-specialist`（个人工作区） | 干净；记忆仍按四级（组织+部门+团队+个人）自动载入 |
| Model | **`glm-5.2`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | agent 需多轮调 PLM/CRM 端点 + RAG + generate_docx；`ask` 只读单轮不够 |
| 场景模板 | `agileac-mkt-01-marketing-content` | **v1 起必绑**——内容规则/RAG cue/输出骨架由模板 system_prompt 承载；技能可留空从模板继承，或显式选 `agileac-mkt-plm-crm-query` |

> 若 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id`。
>
> **本体 / RAG / 记忆不在 drawer 里配置**——这些按用户 scope 自动注入：
> - 37 个本体文件（33 组织级含 identifiers.md + 4 市场部级）按 scope 自动注入（org scope 对所有部门用户可见）；
> - 「营销与竞品情报库」RAG（部门级，scope=`marketing`）自动可见；
> - 长期记忆按「组织+部门+团队+个人」四级全集自动载入。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 composer 输入框（`MentionInput`）里输入：

> 敲 `/` 会弹出技能选择菜单，输入 `mkt` 过滤，选中 **`agileac-mkt-plm-crm-query`** 即把技能 chip 插入到提示词中。

完整提示词如下（直接复制，约 45 字——**就是市场专员的业务请求，不带任何检索/编排指令**）：

```
为敏睿空调 2 款主打产品生成一套营销内容与培训课件：P-RC-WALL-15（1.5 匹壁挂家用）、P-CC-VRV-360（360 型多联机商用）。

/agileac-mkt-plm-crm-query
```

> **四层架构**（详见 `SCENARIO_AUTHORING_GUIDE.md`）：user composer 只写**业务目标 + 产品对象 + 技能 chip**。三段交付结构（卖点+竞品对比 / 海报+视频脚本 / 课件+考题）、按 chunk_type 分段检索营销与竞品情报库、竞品对比覆盖格力/美的/海尔/大金/三菱 5 大品牌、卖点提取来源（PLM `getProductSellingPoints` + RAG 卖点库）——**全部由 Agent 模板 `agileac-mkt-01-marketing-content` 的 `system_prompt` 承载**（见 `## 检索营销与竞品情报库` / `## 内容规则` / `## 输出格式` 三节），不写进用户提示词。任务 config 必须绑定 `template_agent_id = <agileac-mkt-01-marketing-content 的 UUID>`，运行时 `load_config` 才会注入模板（trace `template` 出现、`template:true`）。技能留空从模板继承 `agileac-mkt-plm-crm-query`；模型模板默认 `glm-5.2`（与 drawer 一致，无需覆写）。
>
> 若前端 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id` 复现（`SELECT id FROM agents WHERE slug='agileac-mkt-01-marketing-content'`）。

> ⚠️ **关键 1**：`/agileac-mkt-plm-crm-query` 必须从 `/` 菜单选中 chip，不能手敲文本。agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时 message 里写 `/agileac-mkt-plm-crm-query` 也会被同款正则解析（见 §6）。
>
> ⚠️ **关键 2**：提示词**只写业务目标 + 产品款号**，不写"按 chunk_type 检索""竞品覆盖X品牌"这类编排/检索指令——三段交付结构、chunk_type 分段检索、5 大竞品品牌、卖点来源全由模板 system_prompt 驱动。实测（见 KNOWN_ISSUES A5 MKT-01 段）证明纯业务请求版 agent 仍稳定触发 RAG + PLM/CRM 端点 + 三段输出。
>
> ⚠️ **关键 3**：composer 写明 2 款主打产品款号（业务对象）——让 agent 有明确检索锚点，避免泛化。本体 identifiers.md 已写明产品款号前缀（P-RC- 家用 / P-CC- 商用）与示例值，agent 调 `getStyle`/`getProductSellingPoints` 前读此表，杜绝 404。卖点（静音/省电等）由 agent 从 PLM + RAG 提取，不在 composer 预写。

#### 资源注入机制（任务运行时自动完成，无需配置）

任务运行时，agent runtime 会按 mkt-specialist 的 scope 自动注入以下资源到 system prompt：

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | 按 scope 注入（组织级 33 含 identifiers.md + 市场部级 4） | 37 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出所有可调用的 mock 接口 | PLM/CRM 2 systems / ~15 interfaces |
| **RAG** | 空数组 = 全集自动匹配；retrieve_rag 节点按 query 检索 top-k | 1 collection（营销与竞品情报库），按 chunk_type 分段命中 |
| **长期记忆** | 4 级（组织+部门+团队+个人）按权限聚合；load_memory 节点载入 | 4 history + 6 facts |
| **技能** | skill_ids 显式选 + /-mention 解析 | 1 skill（agileac-mkt-plm-crm-query） |
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
| `[trace]` (template) | 场景模板注入（v1 起必出，slug + chars） |
| `[trace]` (rag) | RAG 检索命中——营销与竞品情报库被检索（按 chunk_type 分段命中） |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 组织本体 + 市场部本体注入 system prompt |
| `[trace]` (data_interface) | 数据接口目录注入（按市场部权限，PLM/CRM 可见） |
| `[trace]` (skill) | /-mention 解析引用了哪个技能 |
| `[trace]` (memory/extract) | 记忆沉淀抽取（写个人级 Memory） |
| `[phase] llm #0/#1/#2` | 每个 LLM 调用轮次 |
| `[tool_call]` | agent 调用工具（PLM 卖点 / CRM 客户 / generate_docx） |
| `[tool_result]` | 工具返回（ok / FAIL） |
| `[text]` | LLM 流式输出 token |
| `[done]` | agent_loop 收口（带 usage 统计） |
| `[final]` | 任务结束，附 latency_ms + session_id |

> 终端前端 ChatView 目前只渲染 `text` / `tool_call` / `tool_result`；`trace` 事件保存在 assistant 消息的 `metadata_.traces` 里，管理后台或 `GET /terminal/tasks/{id}/messages` 可见。

典型 MKT-01 运行约 4–6 分钟（2–3 轮 LLM + 5–6 次 tool 调用 + glm-5.2 推理 + 记忆/RAG 节点）。

---

## 4. 期望输出

agent 会输出三段 + 1 个附件：

### 4.1 卖点提炼 + 竞品对比表

每款产品卖点基于 PLM 产品参数 + RAG 卖点库，竞品对比覆盖 5 大品牌（参数来自 RAG competitor chunk 不杜撰）：

| 维度 | 敏睿 P-RC-WALL-15 | 格力 | 美的 | 海尔 | 大金 | 三菱 |
|---|---|---|---|---|---|---|
| 制冷量 kW | … | … | … | … | … | … |
| 能效 APF | … | … | … | … | … | … |
| 室内噪音 dB | … | … | … | … | … | … |
| 适用面积 ㎡ | … | … | … | … | … | … |

> P-CC-VRV-360 商用多联机同理一张对比表（主打高效+稳定）。

### 4.2 海报文案 + 视频脚本

每款产品一份：
- **海报文案**：主标题 + 副标题 + 核心卖点（3 条）+ 适用场景 + 行动号召（来自 RAG poster_template chunk）
- **视频脚本**（30 秒）：分镜秒数（0–5s / 5–20s / 20–30s）+ 画面 + 字幕

### 4.3 课件大纲 + PPT 框架 + 考题

- **课件大纲**（5 模块）：产品定位 / 核心卖点 / 技术原理 / 安装售后 / 销售技巧（来自 RAG courseware_template chunk）
- **PPT 框架**（10 页）：封面 / 目录 / 模块 1–5 / Q&A
- **考题**（25 题含答案）

### 4.4 .docx 报告附件

agent 调 `generate_docx` 工具把上述三段打包成 `敏睿空调_营销内容与培训课件_YYYYMMDD.docx`（约 40 KB），可下载分发。

### 4.5 SSE trace 事件（演示时截图可证）

| trace | 含义 | 期望实测值 |
|---|---|---|
| `category=template` | 场景模板注入（v1 起必出） | slug=agileac-mkt-01-marketing-content + chars（~748） |
| `category=rag` | RAG 检索命中 | 1 collection / ≥4 hits（retriever=vector，pgvector 余弦检索，覆盖 selling_points/competitor/poster_template/courseware_template 四类） |
| `category=memory, subtype=load` | 长期记忆载入 | 4 history + 6 facts |
| `category=ontology` | 组织本体 + 市场部本体注入 | 37 files |
| `category=data_interface` | 数据接口目录注入（按市场部权限） | 2 systems / ~15 interfaces |
| `category=skill` | /-mention 引用技能 | 1 skill（agileac-mkt-plm-crm-query） |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | 0~3 facts |

> **RAG 多源 chunk 区分演示点**：trace `rag` 事件会显示命中 chunk 的 metadata.chunk_type 字段。2 款产品的三段内容应分别命中 `selling_points` / `competitor` / `poster_template` / `courseware_template` 四类来源——证明多源合集按 metadata 区分检索正常工作。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `glm-5.2`
- 智谱 AI provider 未配或 `supported_models` 不含 `glm-5.2`。
- 修复：管理端「敏睿空调」组织 → LLM Provider 页配智谱 AI provider（`supported_models` 含 `glm-5.2`）+ 路由策略 `model_pattern=glm-*` 指向它，重跑 `seed_agileac_org.py`。

### 5.2 提示词里 `/agileac-mkt-plm-crm-query` 没被识别
- 必须从 `/` 弹窗里选中 chip，不能手敲纯文本。
- 自检：保存的 task.message 里这段应该是结构化 chip 标记。

### 5.3 `[tool_result FAIL]` PLM/CRM 接口调用失败
- mock 网关未起或 API key 不匹配。
- 自检：`curl -s http://localhost:8010/plm/styles -H "X-API-Key: plm-agileac-demo-key" | head` 应返回 JSON。

### 5.4 `mkt-specialist` 看不到 PLM/CRM 数据接口
- 部门级 scope 授权未配置——`seed_agileac_mock_connectors.py` 没把市场部技能的端点按 `scope_type=department, scope_id=marketing_dept.id` 配好。
- 修复：重跑 `seed_agileac_mock_connectors.py`，确认市场部技能 `agileac-mkt-plm-crm-query` 绑定 PLM 卖点 + CRM 客户画像只读端点。

### 5.5 agent 输出「我没有收到任务」
- 检查 `/run` 请求体里 `message` 是否为空——必须把完整提示词作为 `message` 发送。

### 5.6 运行很久没动 / latency > 6 分钟
- glm-5.2 单轮推理慢，多轮 tool 调用累计 4–6 分钟正常。超过 10 分钟大概率卡住，看 `docker logs ai_infra_backend --tail 100`。

### 5.7 trace `rag` 显示 `retriever=keyword_fallback`
- 向量 embedding 不可用，RAG 退化为 CJK 关键词检索。
- 修复路径：管理端「敏睿空调」组织 → LLM Provider 配置 OpenAI 兼容 embedding provider（如 `aliyun-all-openai` 启用 `text-embedding-v4`）；若 chunks embedding 为 NULL，跑 `reembed_agileac_rag.py --collection-name "营销与竞品情报库"` 回填。

### 5.8 agent 没主动触发 RAG 检索
- 编排（按 chunk_type 分段检索营销与竞品情报库）由模板 `system_prompt` 的 `## 检索营销与竞品情报库（RAG，必做）` 节承载，**不应靠用户提示词加 cue**。若纯业务请求版（§3.4）RAG 没触发：先确认 `load_config template:true` + `trace template` 出现（模板没注入则编排丢了）；再确认模板 `system_prompt` 含"检索营销与竞品情报库"指令；最后看 retrieve_rag 节点 query 嵌入是否命中——embedding provider 未配时走 keyword_fallback，纯请求含"营销内容/竞品/课件"关键词仍应命中对应 chunk。

### 5.9 RAG 命中 chunk 的 metadata.chunk_type 全是同一个值
- 现象：三段内容命中的 chunk 都来自同一 chunk_type。
- 根因：`seed_agileac_rag.py` 多源 chunk 写入时 metadata 没正确区分。
- 修复：检查 `seed_agileac_rag.py` 「营销与竞品情报库」部分，确保 metadata 含 `chunk_type` 字段且取值为 `selling_points` / `competitor` / `poster_template` / `courseware_template` 四类之一。

### 5.10 `tool_call` args 全 `{}`
- 现象：所有 `tool_call.arguments={}`，需要参数的端点（如 `getStyle(style_code=...)`）返回 500。
- 根因：`_build_tools`（`app/agents/graph/nodes.py`）的 manifest 占位 schema 覆盖问题（starclothing PD-2 栽过此坑，详见 `SCENARIO_AUTHORING_GUIDE.md` §6.10）。
- 修复：只要有一条 `tool_call` args 非 `{}` 就说明 `_build_tools` 正常；全 `{}` 立即查 `nodes.py` `_build_tools`。

### 5.11 path 参数端点（`getStyle`）返回 404
- 现象：agent 调 `getStyle(style_code="P-RC-WALL-15")` 返回 `{style_code} not found`——path 占位符未替换。
- 影响：**不阻塞闭环**。agent 自主降级到 `listStyles(keyword)` 仍能拿到信息。
- 修复（可选）：技能 wrapper 按 OpenAPI path 占位符替换。非阻塞性，本期按「agent 自主降级」通过。

### 5.12 memory/extract 抽取 0~3 facts
- 现象：`trace memory/extract` 多数 `facts: 0`。
- 影响：非阻塞，本轮输出已完整；长期记忆跨任务复用弱。修复（可选）：调整 `extract_memory` prompt 显式抽取产品→卖点三元组。

### 5.13 竞品参数杜撰（不来自 RAG）
- 现象：竞品对比表的格力/美的等参数与 RAG competitor chunk 不符或凭空生成。
- 根因：agent 没检索或忽略 RAG competitor chunk，靠模型先验杜撰。
- 修复：确认 composer 写明「检索营销与竞品情报库」+「竞品对比覆盖格力/美的/海尔/大金/三菱」（见 §3.4 关键 3），让 agent 知道必须命中 competitor chunk。

---

## 6. 附：手工调 API 复现

不用前端的话，可以用 curl 走一遍：

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agileac","username":"mkt-specialist","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 MKT Agent 模板 id（v1 起任务 config 必须绑定 template_agent_id）
TPL_ID=$(docker exec ai_infra_backend python3 -c "
import asyncio, asyncpg
async def m():
    c=await asyncpg.connect('postgresql://ai_infra:ai_infra@postgres:5432/ai_infra')
    r=await c.fetchrow(\"SELECT id FROM agents WHERE slug='agileac-mkt-01-marketing-content'\")
    print(r['id']); await c.close()
asyncio.run(m())")

# 3) 创建任务（绑定模板；skill_ids 留空从模板继承，model=glm=glm-5.2）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"MKT-01 营销内容\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer 作为 message，见 §3.4；含 /agileac-mkt-plm-crm-query chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"为敏睿空调 2 款主打产品生成一套营销内容与培训课件：\\nP-RC-WALL-15（1.5 匹壁挂家用）、P-CC-VRV-360（360 型多联机商用）。\\n\\n/agileac-mkt-plm-crm-query\",\"stream\":true}"
```

短 composer 提示词文本见 §3.4（内容规则/RAG cue/输出格式由 MKT Agent 模板 `system_prompt` 承载，不在 composer 里）。

---

## 7. 验收要点（演示前自检）

- [ ] `mkt-specialist` 能登录 `/agileac/terminal/login`，左上角显示「市场部」
- [ ] `GET /api/v1/terminal/resources`（mkt-specialist token）的 `skills` 含 `agileac-mkt-plm-crm-query`
- [ ] `data_interfaces` 含 PLM/CRM 端点（不含 SCM/ERP/HRM/MES——非本部门权限）
- [ ] `rag_collections` 含「营销与竞品情报库」（scope=department, marketing）
- [ ] `load_config` 事件显示 **`template:true`**（绑定了 template_agent_id）
- [ ] `trace category=template` 出现（场景模板注入，slug + chars）
- [ ] 任务跑完，SSE 6 类 trace 全部出现（rag + memory.load + ontology + data_interface + skill + memory.extract）
- [ ] `retrieve_rag` 显示 `retriever=vector`，hits ≥ 4，覆盖 selling_points/competitor/poster_template/courseware_template 至少 3 种 chunk_type
- [ ] `tool_call` args 不全 `{}`（至少 `getStyle(style_code=P-RC-WALL-15)` 这类必传参端点要带参）
- [ ] no-guessing：agent 用对产品款号前缀（P-RC- 家用 / P-CC- 商用），不把岗位码/部门码当产品款号
- [ ] 竞品参数来自 RAG competitor chunk 不杜撰（覆盖格力/美的/海尔/大金/三菱 5 品牌）
- [ ] 输出含三段（卖点+竞品对比 / 海报文案+视频脚本 / 课件+PPT+考题）+ 1 个 .docx 附件
