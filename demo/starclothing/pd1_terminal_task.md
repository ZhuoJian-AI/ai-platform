# PD-1 逾期订单风险汇总与推送 · 终端任务演示

> 与其他 6 个场景不同，PD-1 不再走 shell 脚本 + 超管 curl 的方式，而是**通过「终端」以业务用户身份创建任务**完成演示：登录 → 新建任务 → 配置模型（glm-5.2）→ 写提示词 → /-mention 选择技能 → 运行 → 观察 agent 调用 PLM 数据接口、本体、记忆，输出逾期推送清单。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 星途服装（slug = `starclothing`） |
| 用户名 | `dev-lead` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）容器在跑。
2. **数据已 seed**：`seed_starclothing_apparel.py` / `seed_starclothing_mock_connectors.py` / `seed_starclothing_ontology.py` / `seed_starclothing_defect_rag.py` 至少跑过一次（详见根 `README.md` §2.2）。
3. **claude-sonnet-4 已可用**：Anthropic provider 的 `supported_models` 含 `claude-sonnet-4`。
   - 自检：`GET /api/v1/terminal/models`（用对应归口用户 token）应在 `models` 里看到 `claude-sonnet-4`。
4. **dev-lead 账号已存在且 active**：自检 `SELECT username, is_active FROM users WHERE username='dev-lead' AND organization_id=<starclothing org id>`。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/starclothing/terminal/login
```

- 用户名：`dev-lead`
- 密码：`12345678`

登录后落到 `/starclothing/terminal`（终端首页）。左上角应显示当前用户 `dev-lead` + 组织「星途服装」。

> 终端使用 **user-type JWT**（与超管 token 不同，scope 仅限本组织可见资源）。

### 3.2 新建任务

点击左栏「New Task / 新建任务」按钮，进入任务编辑器（HomeView composer）。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧的 ⚙️ 设置按钮，打开 TaskConfigDrawer，配置两项：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `dev-lead`（个人工作区）或「星途服装」 | 选个人工作区最干净；记忆仍按四级（组织+部门+团队+个人）自动载入 |
| Model | **`claude-sonnet-4`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | 让 agent 自主多轮调用工具；`ask` 是只读单轮、`plan` 只出方案不执行 |

> **本体 / RAG / 记忆不在 drawer 里配置**——这些是按用户 scope 自动注入的：
> - 本体文件按部门级 scope 注入（dev-lead 看到开发部 PLM 5 个含 README + 组织级 Cross 4 个，共 9 个）；
> - 服装缺陷知识库 RAG 已下放到品控部 scope，dev-lead 看不到（PD-1 不需要 RAG）；
> - 长期记忆按「组织+部门+团队+个人」四级全集自动载入。

> **场景模板（template_agent_id）**：PD-1 已改为四层架构——persona / 职责 / 跨部门协同
> 规则 / 输出骨架由 Agent 模板 `starclothing-pd1-product-monitor` 的 `system_prompt` 承载，
> 用户 composer 只写「目标 + 对象 + 技能 chip」（见 §3.4）。任务 config 必须绑
> `template_agent_id = <该 slug 的 UUID>`，运行时 `load_config` 才会把模板 persona 拼到
> system prompt 最前（`trace template` / `template:true` 出现），技能与模型留空即从模板继承
>（`starclothing-plm-query` + claude-sonnet-4）。**前端 drawer 暂未暴露「场景模板」选择器**，
> 用 §6 手工调 API 在 `config` 里显式带 `template_agent_id` 绑定。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 composer 输入框（`MentionInput`，支持 `/` 触发技能、`@` 触发工作区文件）里输入：

> 敲 `/` 会弹出技能选择菜单，输入 `plm` 过滤，选中 **`starclothing-plm-query`** 即把技能 chip 插入到提示词中。

完整提示词如下（直接复制，约 70 字）：

```
扫描当前已逾期/7天内将逾期的订单，按款号汇总当前阶段、责任人、风险等级，给出推送对象和补救建议。

/starclothing-plm-query
```

> **v7d 起改为四层架构**（对齐 PD-2 `§3.4` / SC-1 `§3.4`）：user composer 只写
> **目标 + 对象 + 技能 chip**，persona / 职责（全流程监管：按款号汇总阶段/责任人/风险等级/
> 推送对象/补救建议）/ 跨部门协同规则（开发部无缺陷 RAG 权限，QC=FAIL 标注「需品控部
> 协同出具规避要点」）/ 输出骨架（全流程进度汇总表 + 逾期款号推送清单两段）由 Agent 模板
> `starclothing-pd1-product-monitor` 的 `system_prompt` 承载（512 字符）。任务 config 必须绑定
> `template_agent_id = <starclothing-pd1-product-monitor 的 UUID>`，运行时 `load_config` 才会
> 注入模板（trace `template` 出现、`template:true`）。技能与模型留空即从模板继承
>（`starclothing-plm-query` + claude-sonnet-4）。runtime 的 `[输出协议]`+`[工具调用策略]`
> 兜底「先 text 后 docx / 不要臆造 / 最少端点集」，本体 identifiers.md 兜底「标识符不猜」
>——故 composer 不再写执行步骤、输出要求、输出格式。
>
> 若前端 drawer 暂未暴露「场景模板」选择器，可用 §6 手工调 API 在 `config` 里显式带
> `template_agent_id` 复现（`SELECT id FROM agents WHERE slug='starclothing-pd1-product-monitor'`）。

> ⚠️ **关键 1**：`/starclothing-plm-query` 必须从 `/` 菜单选中 chip，不能手敲文本。agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时 message 里写 `/starclothing-plm-query` 也会被同款正则解析（见 §6）。
>
> ⚠️ **关键 2**：跨部门协同规则（QC=FAIL 标注「需品控部协同出具规避要点」）已固化在模板
> `system_prompt` 里，不在 composer。开发部 dev-lead 无缺陷知识库 RAG 访问权限（已下放品控部），
> 故 PD-1 不在本部门检索缺陷规避要点，由品控部 PD-3 场景负责 RAG 检索后回填。

#### 资源注入机制（任务运行时自动完成，无需配置）

任务运行时，agent runtime 会按 dev-lead 的 scope 自动注入以下资源到 system prompt（**部门级 scope 拆分后**，dev-lead 只看得到开发部范围内的资源）：

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | scope_filter 过滤后：开发部 PLM 5 个（含 README）+ 组织级 Cross 4 个 | 9 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出 dev-lead 可调用的接口 | 1 system（PLM）/ 24 interfaces |
| **RAG** | dev-lead scope 下无可访问的 RAG collection（缺陷知识库已下放到品控部） | 0 collection |
| **长期记忆** | 4 级（组织+部门+团队+个人）按权限聚合；load_memory 节点载入 | 4 history + 6 facts |
| **技能** | `template_agent_id` 继承 + /-mention chip 解析；config 留空 skill_ids 即从模板 `starclothing-pd1-product-monitor` 继承 | 1 skill（开发部级 starclothing-plm-query） |
| **记忆沉淀** | extract_memory 节点抽取本轮可沉淀事实写入个人级 Memory | v7d5 起正常抽取（详见 §5.11） |

> **跨部门数据访问**：dev-lead 只能调用开发部 scope 下的 PLM 数据接口；如需调用其他部门（如供应链部 SCM、品控部 PLM）的接口，需在调用方部门下重新实现一份数据接口（绑定同一组织级 `tool_connector`，按需开放端点）。这是按需开放模型——既允许跨部门数据流转，又确保每个部门的数据接口暴露面是显式授权的。

### 3.5 提交运行

按回车（或点发送按钮）提交。前端会：
1. `POST /api/v1/terminal/tasks` 创建任务（把 composer 里的内容作为 `message` 字段存档）；
2. `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}` —— **这才是真正发给 agent 的输入**。

> ⚠️ 实测：`/run` 的 `message` 才是 agent 看到的指令；任务创建时存的 `message` 不会被 agent 读到。前端的做法是「同一段文本两次用」。如果你手工调 API，记得 `/run` 也要把完整提示词带上。

### 3.6 观察 SSE 事件流

任务运行后，右侧 ChatView 会渲染 SSE 事件。事件类型与含义：

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载任务配置（model / skill_ids / workspace / template_agent_id） |
| `[trace]` (template) | 场景模板 persona 注入（`template:true`——PD-1 模板 system_prompt 拼到 system prompt 最前，继承 skill_ids/model_alias） |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 部门级本体注入 system prompt |
| `[trace]` (data_interface) | 数据接口目录注入（按用户权限全量） |
| `[trace]` (skill) | /-mention 解析引用了哪个技能 |
| `[trace]` (memory/extract) | 记忆沉淀抽取（写个人级 Memory） |
| `[phase] llm #0/#1/#2/#3` | 每个 LLM 调用轮次 |
| `[tool_call]` | agent 调用工具（如 PLM 端点 / generate_docx / workspace_list_files） |
| `[tool_result]` | 工具返回（ok / FAIL） |
| `[text]` | LLM 流式输出 token（直接渲染到对话气泡） |
| `[done]` | agent_loop 收口（带 usage 统计） |
| `[final]` | 任务结束，附 latency_ms + session_id |

> 终端前端 ChatView 目前只渲染 `text` / `tool_call` / `tool_result`；`trace` 事件保存在 assistant 消息的 `metadata_.traces` 里，管理后台或 `GET /terminal/tasks/{id}/messages` 可见。

典型 PD-1 运行约 5–7 分钟（3–4 轮 LLM + 6–7 次 tool 调用 + glm-5.2 推理 + 记忆/RAG 节点）。

---

## 4. 期望输出

agent 会输出两段 + 1 个附件：

### 4.1 全流程进度汇总表

11 列（含 # 序号），共 9 条订单（7 已逾期 + 2 即将逾期），涉及 7 个款号、3 家工厂、2 家客户：

| # | 款号 | 品类 | 单号 | 当前阶段 | 逾期状态 | 剩余天数 | 责任人 | 风险等级 | 推送对象 | 补救建议 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | P-FW2026-001 | 双面呢长大衣 | SMP20260009 | 打样·确认样（已退回） | 🔴 已逾期 | -45天 | 开发-陈/设计师-林/F-XT-DG | 极高 | 开发-陈、设计师-林、F-XT-DG 生产主管 | 加急+换料 |
| 2 | P-SS2026-020 | 牛仔裤 | SMP20260005 | 打样·二样（打样中） | 🔴 已逾期 | -30天 | … | 极高 | … | 加急+降级接收 |
| 3 | P-FW2026-001 | 双面呢长大衣 | BLK20260007 | 大货（QC=FAIL） | 🔴 已逾期 | -8天 | … | 极高 | …（含客户经理） | 调产+降级接收 |
| … | … | … | … | … | … | … | … | … | … | … |

> 风险等级判定规则 agent 会自洽定义（如：逾期≥30天 或 QC=FAIL+逾期≥7天 → 极高；逾期 7~14天 → 中；等）。

### 4.2 逾期款号推送清单（按风险等级分组）

每组下每条订单用表格展示，字段：款号 / 单号 / 推送对象 / 关键提示 / 补救建议。

**对 QC=FAIL 的款号**（实测：BLK20260007 整烫烫花 / BLK20260002 压胶脱落 / BLK20260009 即将逾期+FAIL），agent 会**额外附「⚠️ QC=FAIL 缺陷规避要点」表**，按来源分行：

| 来源 | 类型 | 内容 |
|---|---|---|
| DF20260009 | 历史缺陷 | 款号 P-FW2026-001，缺陷类型「整烫烫花」，严重等级 严重 |
| DF20260009 | 根因 | 熨斗温度过高 180℃ |
| DF20260009 | 纠正措施 | 调至 150℃+垫布 |
| DF20260009 | 规避要点 | 羊绒款禁裸烫，必垫烫布 |
| RAG 知识库 | 工艺阶段 | 每工位挂熨烫温度对照表，关键部位必垫烫布 |
| RAG 知识库 | 设备阶段 | 熨斗每周校温度，误差 ≤5℃ |
| RAG 知识库 | 验证阶段 | 成品整烫后 100% 目视检查 |

**来源标注**让闭环可追溯：
- `DF20260xxx` 行 = PLM `listDefectHistory` 端点返回
- `RAG 知识库` 行 = 服装缺陷知识库 RAG 检索结果

### 4.3 .docx 报告附件

agent 会调 `generate_docx` 工具把上述分析打包成 `星途服装_产品全流程逾期监管报告_YYYYMMDD.docx`（约 40 KB），可下载分发。

### 4.4 SSE trace 事件（演示时截图可证）

任务运行期间，SSE 流除常规 `step` / `phase` / `text` / `tool_call` / `tool_result` / `final` 外，会发射 6 个 `trace` 事件，可作"调用了本体 / 知识库 / 记忆 / 数据接口"的证据：

| trace | 含义 | 实测值 |
|---|---|---|
| `category=rag` | RAG 检索命中 | 1 collection / 5 hits（retriever=vector，pgvector 余弦检索） |
| `category=memory, subtype=load` | 长期记忆载入 | 6 history + 6 facts |
| `category=ontology` | 部门级本体注入 | 8 files |
| `category=data_interface` | 数据接口目录注入 | 1 system（PLM）/ 24 interfaces |
| `category=skill` | /-mention 引用技能 | 1 skill（starclothing-plm-query） |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | 0~3 facts（详见 §5.9） |

### 4.5 实测延迟与 token 用量（v5/v6 修复版，v7 path-param 修复后 0 失败）

| 指标 | run3（原 prompt，运气好） | v4（原 prompt，运气差） | **v5（修复后 prompt）** | **v6（修复后 prompt，稳定性确认）** | **v7（path-param 修复后）** |
|---|---|---|---|---|---|
| latency_ms | 384432（~6.4 min） | 386513（~6.4 min） | 253878（~4.2 min） | 437725（~7.3 min） | 248280（~4.1 min） |
| input_tokens | 101003 | 197699 | 113402 | 198678 | 91539 |
| output_tokens | 14587 | 13625 | 8792 | 16125 | 9022 |
| tool_calls | 7（0 失败） | 28（13 失败） | 19（7 失败） | 23（11 失败） | **17（0 失败）** |
| text 事件字符数 | 7179 ✓ | 356 ✗ | **4517 ✓** | **7406 ✓** | **5146 ✓** |
| 4 段分析是否上屏 | ✓ | ✗ | ✓ | ✓ | ✓ |
| 6 类 trace 是否全 | ✓ | ✓ | ✓ | ✓ | ✓ |
| listOverdueOrders 调用 | ✓ | ✓ | ✓ | ✓ | ✓ |
| memory/extract facts | 0 | 0 | 3 | 0 | 0 |

> v5 + v6 在 prompt 加了「先 text 流式输出 4 段分析，再生成 docx 附件」要求后
> （§3.4 输出要求段），连续 2 次跑都稳定达标——text 流式输出 4517 / 7406 字符
> （远超 v4 不达标版的 356 字符），4 段分析（全流程进度汇总表 / 逾期款号推送
> 清单 / RAG 规避要点 / listOverdueOrders 调用）全部出现在 ChatView 屏幕上。
> 方差只在延迟（4.2 / 7.3 min）和字符数（4.5K / 7.4K）上，核心达标指标 0 失败。
>
> v4 不达标版的 13 次失败 + v5/v6 的 7~11 次失败都是同一个 path-param 占位符
> 未替换 bug（getStyle / getBulkOrder / getSamplingProgress 三个端点），
> agent 自主降级到 `listStyles` / `listBulkOrders` / `listSamplingOrders`
> 拿到等价数据，不阻塞演示闭环——详见 §5.10。
>
> **v7（path-param 修复后）**：修了 `executor.py` 占位符替换 + 注入 `[工具调用策略]`
> 后重跑，tool_calls 17 次 **0 失败**（v6 的 11 次失败全部消失）。agent 不再
> 「试详情端点→失败→降级列表」，而是直接用真实编码命中 `getStyle` /
> `getBulkOrder` / `getSamplingProgress` 三个原本必失败的 path 端点，返回真实
> 数据。24 个可用接口里只调了真正需要的 6 个（listOverdueOrders / getStyle /
> getBulkOrder / getSamplingProgress / listQcReports / listDefectHistory）
> + generate_docx，无冗余调用、无失败重试——「先结合本体分析再调用」策略生效。
> 详见 §5.10。
>
> **v7d（template 层 + 真用户提示词，验证态）**：按 PD-3 四层架构（详见
> `pd3_terminal_task.md` §5.17）对 PD-1 落地——`starclothing-pd1-product-monitor`
> Agent system_prompt 重写为精简模板（persona + 跨部门协同规则 + 2 段输出骨架，
> 512 字符，删了老胖 playbook 的检索策略/工具调用要点）。用户 composer 收缩到
> **~80 字符**：只留「扫描当前已逾期/7天内将逾期的订单，按款号汇总当前阶段/
> 责任人/风险等级，给出推送对象和补救建议」+ 技能 chip——persona、跨部门协同
> 规则、输出格式全在 template。回跑（dev-lead + template_agent_id）：tool_calls 22
> **0 失败**（path 端点 getStyle/getBulkOrder/getSamplingProgress 全 0 失败）、
> template trace 加载、text 6510（2 段全流程进度汇总表 + 逾期款号推送清单上屏）、
> 跨部门协同规则生效（text 含「品控部」/「缺陷规避」/「QC=FAIL」标注）。
> runtime 输出协议 + PLM identifiers.md 本体 + template + 用户 80 字符目标，四层全绿。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `claude-sonnet-4`
- Anthropic provider 未配或 `supported_models` 不含 `claude-sonnet-4`。
- 自检：`GET /api/v1/terminal/models` 的 `models` 应含 `claude-sonnet-4`。
- 修复：管理端「星途服装」组织 → LLM Provider 页配 Anthropic provider（`supported_models` 含 `claude-sonnet-4`）+ 路由策略 `model_pattern=claude-*` 指向它，重跑 `seed_starclothing_apparel.py`。

### 5.2 提示词里 `/starclothing-plm-query` 没被识别
- 必须从 `/` 弹窗里选中 chip，不能手敲纯文本。
- 自检：保存的 task.message 里这段应该是结构化 chip 标记，不是 plain text。

### 5.3 `[tool_result FAIL]` PLM 接口调用失败
- mock 网关未起或 API key 不匹配。
- 自检：`curl -s http://localhost:8010/plm/styles -H "X-API-Key: plm-starclothing-demo-key" | head` 应返回 JSON。

### 5.4 agent 输出「我没有收到任务」
- 检查 `/run` 请求体里 `message` 是否为空——必须把完整提示词作为 `message` 发送，任务创建时存的 `message` 不会被 agent 读到。

### 5.5 运行很久没动 / latency > 5 分钟
- glm-5.2 单轮推理慢，多轮 tool 调用累计 3–4 分钟正常。超过 10 分钟大概率卡住，看后端日志 `docker logs ai_infra_backend --tail 100`。

### 5.6 trace `rag` 显示 `retriever=keyword_fallback`
- 说明向量 embedding 不可用（org 未配 embedding provider 或 `text-embedding-v4` 不可达），RAG 退化为 CJK 关键词检索。仍能命中含关键词的 chunk 但语义精度差。
- 修复路径：
  1. 在管理端「星途服装」组织 → LLM Provider 页配置 OpenAI 兼容的 embedding provider（如 `aliyun-all-openai` 启用 `text-embedding-v4`）；
  2. 修复 `rag_service.py` `_EMBED_BATCH`（曾为 64，超 Aliyun 单批 10 条上限导致静默失败、所有 chunk embedding 列为 NULL）。当前已改为 8；
  3. 若 chunks 已存在但 embedding 列为 NULL，需跑 `reembed_defect_rag.py`（位于 `demo/starclothing/scripts/`）一次性回填；
  4. 自检：`SELECT COUNT(*) FROM rag_chunks WHERE collection_id=<defect_rag_collection_id> AND embedding IS NOT NULL` 应等于 chunk 总数（61）。
- 当前状态：星途服装 demo 环境向量检索已可用，trace 显示 `retriever=vector`，5 hits，相似度 0.57+。

### 5.7 agent 没主动触发 RAG 检索
- retrieve_rag 节点的 query 是整段 user message，命中靠语义相关性。
- 若提示词只写"扫逾期订单"而没提"缺陷知识库"，glm-5.2 的 query 嵌入可能命中度不够。
- 修复：提示词里**明确写出「检索服装缺陷知识库」字样**（见 §3.4 关键 2）。

### 5.8 trace 事件没在 SSE 里显示
- 终端前端目前只渲染 `text` / `tool_call` / `tool_result`，`trace` 事件落在 `TaskMessage.metadata_.traces` 里（assistant 消息元数据），UI 不直接展示。
- 查看方式：管理后台 → 终端任务详情页 → 消息 traces 标签；或 `GET /api/v1/terminal/tasks/{id}/messages` 看元数据。

### 5.9 输出大量走 `generate_docx`，前端 `text` 输出较短（与 PD-2 / PD-3 同款）
- 现象：SSE 的 `text` 事件累计仅 ~356 字符（v4 实测），但 `.docx` 报告 ~40KB。
  ChatView 屏幕上看不到完整 4 段分析（全流程进度汇总表 / 逾期款号推送清单等）。
- 根因：与 PD-2 v5 / PD-3 v1 同款非确定性问题——agent 末轮跳过 text 流式分析，
  直接调 `generate_docx` 把全部内容打包成附件。glm-5.2 在不同轮次里随机选择
  "先 text 后 docx"或"直接 docx"路径，原 prompt 没有强约束。
- 实测（v4 不达标）：text 356 字符，4 段结构中"全流程进度汇总表"段缺失。
- 修复：prompt §3.4 已加「先在 text 里流式输出完整分析，再生成 docx 附件」
  要求（输出要求段）。v5/v6 重跑后 text 356 → 4517 / 7406 字符（12~20×），
  4 段分析全部出现在屏幕上，演示体验达标。代价是延迟略增，可接受。
- 稳定性：v5（4517）+ v6（7406）连续 2 次跑都达标，方差只在延迟和字符数上，
  核心达标指标 0 失败。

### 5.10 `getStyle` / `getBulkOrder` / `getSamplingProgress` 路径参数未替换（v7 已修）
- 现象：agent 调 `getStyle(style_code="P-FW2026-001")` 返回
  `{"detail":"style {style_code} not found"}`——`{style_code}` 占位符未被
  替换为实际值；`getBulkOrder(bulk_no=...)` / `getSamplingProgress(sampling_no=...)`
  同样问题。**PD-1 影响面比 PD-3 大**——PD-3 只有 getStyle/getFabric 2 个端点
  受影响，PD-1 有 3 个端点（getStyle / getBulkOrder / getSamplingProgress）。
- 根因：技能 wrapper 把 path 参数当作 query/body 参数透传，未替换到
  OpenAPI path 占位符（`/api/v1/styles/{style_code}` /
  `/api/v1/bulk-orders/{bulk_no}` / `/api/v1/sampling-orders/{sampling_no}`）。
- 影响（修复前）：**不阻塞 PD-1 闭环**。agent 自主降级到 `listStyles(keyword)` /
  `listBulkOrders` / `listSamplingOrders`（这些 list 端点用 query 参数，不受
  影响），仍能拿到款式 / 工单 / 打样单完整信息。
- 实测（修复前）：v4 共 13 次失败 / v5 共 7 次失败 / v6 共 11 次失败——失败数随
  agent 探索深度变化，但每次都集中在这 3 个端点。演示时屏幕会看到红色 ✗ 标记，
  但 agent 自行降级后闭环仍完整。
- 修复状态（v7 已根治）：在 `executor.py` `execute_endpoint` 里于拼装 URL 前
  按 `{name}` 占位符替换路径参数（`urllib.parse.quote` 编码）并从 query/body
  移除已用于 path 的参数，混合端点（path+query）也正确；同时在 `agent_loop`
  Craft 分支注入 `[工具调用策略]` prompt，约束 agent 结合本体/数据接口目录先
  分析「最少且最直接可达的端点集」、按参数清单准备入参、详情/列表端点按需
  选择、失败后据返回信息修正而非无差别重试。v7 重跑：tool_calls 17 次 **0 失败**，
  `getStyle` / `getBulkOrder` / `getSamplingProgress` 全部直接返回真实数据，
  无降级、无冗余调用。详见 §4.5 v7 列。

### 5.11 memory/extract 抽取 0~3 facts（已修，v7d5）
- 现象（修复前）：`trace memory/extract` 多数情况下 `facts: 0`，偶尔（v5）抽到 3 facts。
- 根因：与 PD-2 / PD-3 同款——extract_memory prompt 偏保守 +（真因）glm-5.2 非流式
  把 JSON 包在 ``` ```json ``` ``` 围栏里，`json.loads` 抛 `char 0` 被吞 → facts 静默归零。
- 修复（已实施，见 KNOWN_ISSUES Issue #2 / `pd2_terminal_task.md` §5.13）：`nodes.py`
  `extract_memory` prompt 改三元组抽取 + 新增 `_parse_json_lenient` 容错解析（剥围栏 /
  fallback `{...}` 子串 / 全失败返回 `{}`）。PD-1 同款受益，跨任务记忆复用正式生效。

---

## 6. 附：手工调 API 复现

不用前端的话，可以用 curl 走一遍：

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"starclothing","username":"dev-lead","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 PD-1 Agent 模板 id（v7d 起任务 config 必须绑 template_agent_id；
#    skill_ids 留空从模板继承，model 留空继承 claude-sonnet-4）
TPL_ID=$(docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -tAc \
  "SELECT id FROM agents WHERE slug='starclothing-pd1-product-monitor' AND deleted_at IS NULL AND organization_id='54f5f892-cf08-4a75-88b2-b649fea392a4'")
echo "template_agent_id=$TPL_ID"

# 3) 创建任务（绑模板；skill_ids 留空从模板继承，model_alias 留空继承 claude-sonnet-4）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"PD-1 逾期订单风险汇总与推送\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"claude-sonnet-4\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer 作为 message，见 §3.4；含技能 chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"扫描当前已逾期/7天内将逾期的订单，按款号汇总当前阶段、责任人、风险等级，给出推送对象和补救建议。\\n\\n/starclothing-plm-query\",\"stream\":true}"
```

短 composer 提示词文本见 §3.4（persona / 职责 / 跨部门协同规则 / 输出格式由 PD-1 Agent 模板
`system_prompt` 承载，不在 composer 里）。
