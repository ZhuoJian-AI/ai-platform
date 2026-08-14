# SC-2 下周工单产线排程与风险提示 · 终端任务演示

> 升级版：SC-2 不再走 shell 脚本 + 超管 curl 的方式，而是**通过「终端」以业务
> 用户身份创建任务**完成演示：登录 → 新建任务 → 配置模型（glm-5.2）→ 写提示词 →
> /-mention 选择技能 → 运行 → 观察 agent 调用 MES + SCM 数据接口、本体、记忆，
> 输出排程表 + 风险提示 + 产线负载 + 补货建议四段。
>
> 旧 shell 脚本 `sc2_factory_scheduling.sh` 保留以备对照（走超管 playground SSE）。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 星途服装（slug = `starclothing`） |
| 用户名 | `prod-lead` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）容器在跑。
2. **数据已 seed**：`seed_starclothing_apparel.py` / `seed_starclothing_mock_connectors.py` / `seed_starclothing_ontology.py` 至少跑过一次（详见根 `README.md` §2.2）。
3. **claude-opus-4 已可用**：Anthropic provider 的 `supported_models` 含 `claude-opus-4`。
   - 自检：`GET /api/v1/terminal/models`（用对应归口用户 token）应在 `models` 里看到 `claude-opus-4`。
4. **prod-lead 账号已存在且 active**：自检 `SELECT username, is_active FROM users WHERE username='prod-lead' AND organization_id=<starclothing org id>`。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/starclothing/terminal/login
```

- 用户名：`prod-lead`
- 密码：`12345678`

登录后落到 `/starclothing/terminal`（终端首页）。左上角应显示当前用户 `prod-lead` + 组织「星途服装」。

> 终端使用 **user-type JWT**（与超管 token 不同，scope 仅限本组织可见资源）。

### 3.2 新建任务

点击左栏「New Task / 新建任务」按钮，进入任务编辑器（HomeView composer）。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧的 ⚙️ 设置按钮，打开 TaskConfigDrawer，配置两项：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `prod-lead`（个人工作区）或「星途服装」 | 选个人工作区最干净；记忆仍按四级（组织+部门+团队+个人）自动载入 |
| Model | **`claude-opus-4`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | 让 agent 自主多轮调用 MES + SCM 工具；`ask` 是只读单轮、`plan` 只出方案不执行 |

> **本体 / RAG / 记忆不在 drawer 里配置**——这些是按用户 scope 自动注入的：
> - 9 个本体文件（生产部 SCM 5 个含 README + 组织级 Cross 4 个）按部门级 scope 自动注入（MES 无本体文件）；
> - SC-2 无 RAG（`rag_collection_id=None`），不触发 RAG 检索；
> - 长期记忆按「组织+部门+团队+个人」四级全集自动载入。

> **场景模板（template_agent_id）**：SC-2 已改为四层架构——persona / 排产输入 /
> 排产逻辑（5 条）/ 输出骨架由 Agent 模板 `starclothing-sc2-factory-scheduling`
> 的 `system_prompt` 承载，用户 composer 只写「目标 + 对象 + 技能 chip」（见 §3.4）。
> 任务 config 必须绑 `template_agent_id = <该 slug 的 UUID>`，运行时 `load_config`
> 才会把模板 persona 拼到 system prompt 最前（`trace template` / `template:true` 出现），
> 技能与模型留空即从模板继承（`starclothing-mes-query` + `starclothing-scm-query` +
> claude-opus-4）。**前端 drawer 暂未暴露「场景模板」选择器**，用 §6 手工调 API 在
> `config` 里显式带 `template_agent_id` 绑定。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 composer 输入框（`MentionInput`，支持 `/` 触发技能、`@` 触发工作区文件）里输入：

> 敲 `/` 会弹出技能选择菜单，输入 `mes` 过滤，选中 **`starclothing-mes-query`**；
> 再敲 `/` 输入 `scm` 过滤，选中 **`starclothing-scm-query`**——两个技能 chip 都插入到提示词中。

完整提示词如下（直接复制，约 100 字符）：

```
下周排产：列出所有 pending 工单，结合产能日历、面料到货计划、补货建议做产线排程 + 风险提示。

/starclothing-mes-query
/starclothing-scm-query
```

> **v7d 起改为四层架构**（对齐 PD-2 `§3.4` / SC-1 `§3.4`）：user composer 只写
> **目标 + 对象 + 技能 chip**，persona / 排产输入（MES 工单 + 产线 + SCM 产能日历 +
> 面料到货 + 补货建议）/ 排产逻辑 5 条（面料优先级 / 产线占用 / 交期优先级 / 补货节奏 /
> 瓶颈识别）/ 输出骨架（排程表 + 风险提示 + 产线负载 + 补货建议四段）由 Agent 模板
> `starclothing-sc2-factory-scheduling` 的 `system_prompt` 承载（655 字符）。任务 config
> 必须绑定 `template_agent_id = <starclothing-sc2-factory-scheduling 的 UUID>`，运行时
> `load_config` 才会注入模板（trace `template` 出现、`template:true`）。技能与模型留空
> 即从模板继承（`starclothing-mes-query` + `starclothing-scm-query` + claude-opus-4）。
> runtime 的 `[输出协议]`+`[工具调用策略]` 兜底「先 text 后 docx / 不要臆造 / 最少端点集」，
> 本体 identifiers.md 兜底「标识符不猜」——故 composer 不再写执行步骤、输出要求、输出格式。
>
> 若前端 drawer 暂未暴露「场景模板」选择器，可用 §6 手工调 API 在 `config` 里显式带
> `template_agent_id` 复现（`SELECT id FROM agents WHERE slug='starclothing-sc2-factory-scheduling'`）。

> ⚠️ **关键 1**：`/starclothing-mes-query` 和 `/starclothing-scm-query` 这两段必须是真的从 `/` 菜单里选中的 chip，不是手敲文本。agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时 message 里写 `/starclothing-mes-query` 也会被同款正则解析（见 §6）。
>
> ⚠️ **关键 2**：~~原版第 1 步「path-param bug 降级到 listWorkOrders」~~——该 bug 已随 Issue #1
> 根治（`executor.py execute_endpoint` 占位符替换），短 composer 不再写降级指引；agent 遇
> `getWorkOrder` 404（工单号 mock 不存在）会自主降级 `listWorkOrders` 后闭环（与 SC-1 v8
> 同类「标识符推断偏差」，非占位符 bug）。详见 §5.7。
>
> ⚠️ **关键 3**：排产逻辑 5 条现已全部由 template `system_prompt` 承载（不在 composer 里）；
> 「面料优先级」+「补货节奏」两条是跨系统联动的核心演示点，模板已固化，agent 不会漏。

#### 资源注入机制（任务运行时自动完成，无需配置）

任务运行时，agent runtime 会按 prod-lead 的 scope 自动注入以下资源到 system prompt（**部门级 scope 拆分后**，prod-lead 看到生产部范围内的资源）：

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | scope_filter 过滤后：生产部 SCM 5 个（含 README）+ 组织级 Cross 4 个（MES 无本体文件） | 9 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出 prod-lead 可调用的接口 | 2 systems（SCM 16 + MES 13）/ 29 interfaces |
| **RAG** | 生产部 scope 下无 RAG collection | 0 collection |
| **长期记忆** | 4 级（组织+部门+团队+个人）按权限聚合；load_memory 节点载入 | 4 history + 6 facts |
| **技能** | `template_agent_id` 继承 + /-mention chip 解析；config 留空 skill_ids 即从模板 `starclothing-sc2-factory-scheduling` 继承 | 2 skills（生产部级 starclothing-mes-query + starclothing-scm-query） |
| **记忆沉淀** | extract_memory 节点抽取本轮可沉淀事实写入个人级 Memory | 0~3 facts（详见 §5.8） |

> **跨部门数据访问**：prod-lead 只能调用生产部 scope 下的 MES + SCM 数据接口。如需调用品控部 PLM（查缺陷规避要点）或开发部 PLM（查款号设计档案），需在生产部下重新实现一份 PLM 数据接口（绑定同一 `tool_connector` starclothing-plm，按需开放端点子集）。SC-2 当前已覆盖 MES + SCM 两个核心系统，排产联动所需数据完整。

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
| `[trace]` (template) | 场景模板 persona 注入（`template:true`——SC-2 模板 system_prompt 拼到 system prompt 最前，继承 skill_ids/model_alias） |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 部门级本体注入 system prompt |
| `[trace]` (data_interface) | 数据接口目录注入（按用户权限全量） |
| `[trace]` (skill) | /-mention 解析引用了哪个技能 |
| `[trace]` (memory/extract) | 记忆沉淀抽取（写个人级 Memory） |
| `[phase] llm #0/#1/#2/#3` | 每个 LLM 调用轮次 |
| `[tool_call]` | agent 调用工具（如 MES `listWorkOrders` / SCM `listCapacityCalendar` / `generate_docx`） |
| `[tool_result]` | 工具返回（ok / FAIL） |
| `[text]` | LLM 流式输出 token（直接渲染到对话气泡） |
| `[done]` | agent_loop 收口（带 usage 统计） |
| `[final]` | 任务结束，附 latency_ms + session_id |

> 终端前端 ChatView 目前只渲染 `text` / `tool_call` / `tool_result`；`trace` 事件保存在 assistant 消息的 `metadata_.traces` 里，管理后台或 `GET /terminal/tasks/{id}/messages` 可见。

典型 SC-2 运行约 5–8 分钟（3–5 轮 LLM + 8–25 次 tool 调用 + glm-5.2 推理 + 跨 MES/SCM 多源数据联动）。

---

## 4. 期望输出

agent 会输出四段 + 1 个附件：

### 4.1 排程表

9 列（工单号 / 款号 / 数量 / 面料到货日 / 上裁床日 / 上车缝日 / 上整烫日 / 入库日 / 产线），共 5–7 条 pending 工单（MES `listWorkOrders` 返回，工单号如 XWO20260788 / XWO20260800 / XWO20260801 / XWO20260808 / XWO20260810 / XWO20260811 等）：

| 工单号 | 款号 | 数量 | 面料到货日 | 上裁床日 | 上车缝日 | 上整烫日 | 入库日 | 产线 |
|---|---|---|---|---|---|---|---|---|
| XWO20260788 | P-FW2026-002 | 800 | 2026-07-05 | 2026-07-06 | 2026-07-08 | 2026-07-12 | 2026-07-14 | 车缝 A |
| XWO20260801 | P-SS2026-010 | 1200 | 2026-07-03 | 2026-07-04 | 2026-07-06 | 2026-07-09 | 2026-07-11 | 车缝 B |
| … | … | … | … | … | … | … | … | … |

> 排产规则 agent 会自洽应用：(1) 面料未到货工单不可上裁床；(2) 压胶冲锋衣 → 车缝 A，双面呢大衣 → 车缝 B；(3) 紧急补货工单提到队首；(4) 满载月份提示外协。

### 4.2 风险提示

按风险类型分组（面料延迟 / 产能满载 / 交期紧），每条 = 工单 + 风险类型 + 应对建议：

| 工单号 | 风险类型 | 应对建议 |
|---|---|---|
| XWO20260800 | 面料延迟 | M-SHELL-3L-150 到货 +3 天，启动备选供应商 XS-FAB-003 加急 |
| XWO20260808 | 产能满载 | 车缝 B 7 月已满载，外协给合作工厂或 7 月底加班 2 班 |
| XWO20260810 | 交期紧 | 入库日距交期仅 1 天缓冲，建议提前 2 天上裁床 |

### 4.3 产线负载

每条产线一行，含当月已排产 / 总产能 / 占用率 / 瓶颈月份：

| 产线 | 当月已排产 | 总产能 | 占用率 | 瓶颈月份 |
|---|---|---|---|---|
| 裁床 | 4500 件 | 6000 件 | 75% | 无 |
| 车缝 A | 3200 件 | 3500 件 | 91% ⚠ | 2026-07 |
| 车缝 B | 2800 件 | 3000 件 | 93% ⚠ | 2026-07 |
| 整烫 | 6000 件 | 8000 件 | 75% | 无 |
| 包装 | 5500 件 | 7000 件 | 79% | 无 |

### 4.4 补货建议

对面料延迟或紧急补货工单，列出补货建议：

| 面料编码 | 紧急程度 | 建议补货日 | 影响工单 |
|---|---|---|---|
| M-SHELL-3L-150 | 高 | 2026-07-04 | XWO20260800 / XWO20260811 |
| M-WOOL-DBL-360 | 中 | 2026-07-10 | XWO20260789 |

### 4.5 .docx 报告附件

agent 会调 `generate_docx` 工具把上述分析打包成 `星途服装_下周工厂排产报告_YYYYMMDD.docx`（约 30~40 KB），可下载分发。

### 4.6 SSE trace 事件（演示时截图可证）

任务运行期间，SSE 流除常规 `step` / `phase` / `text` / `tool_call` / `tool_result` / `final` 外，会发射 **5 个 `trace` 事件**（SC-2 无 RAG，比 PD-3 少 1 个 rag trace）：

| trace | 含义 | 实测值 |
|---|---|---|
| `category=memory, subtype=load` | 长期记忆载入 | 4 history + 6 facts |
| `category=ontology` | 部门级本体注入 | 8 files（生产部 SCM proxy 4 + 组织级 Cross 4） |
| `category=data_interface` | 数据接口目录注入 | 2 systems / 29 interfaces（生产部级 MES + SCM） |
| `category=skill` | /-mention 引用技能 | 2 skills（starclothing-mes-query + starclothing-scm-query） |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | 0~3 facts（详见 §5.8） |

### 4.7 实测延迟与 token 用量（v1 首跑基线）

| 指标 | v1（首跑，prod-lead） |
|---|---|
| latency_ms | 498596（≈8.3 分钟） |
| input_tokens | 125543 |
| output_tokens | 18351 |
| tool_calls | 24 次（其中 10 次失败：getRouting + getProductionOrder + getLeadtimeDiff 全部 path-param bug，agent 自主降级到 listProductionOrders / listLeadtimeSnapshots 等价端点闭环） |
| text 事件字符数 | 0（glm-5.2 跳过 text 流式，直接打包 docx，见 §5.6） |
| 4 段分析是否上屏 | ✗（屏幕上未出现 text 流式分析，但 docx 报告完整含 4 段全部内容，详见 §5.6 修复路径） |
| 5 类 trace 是否全 | ✓（memory load / ontology files=8 / data_interface systems=2 interfaces=29 / skill × 2 / memory extract） |
| listWorkOrders(status=pending) 调用 | ✓（首调，返回所有待排产工单） |
| generate_docx 生成 | ✓ `星途服装_下周排产分析报告_20260629.docx` |

> v1 首跑基线确立。第二次重跑可确认稳定性；若 text 字符数仍为 0，参考 §5.6 修复路径——prompt 已加「先 text 流式输出 4 段分析，再生成 docx 附件」要求，但 glm-5.2 非确定性导致部分轮次仍跳过 text 直接打包。docx 报告内容完整不影响演示闭环。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `claude-opus-4`
- Anthropic provider 未配或 `supported_models` 不含 `claude-opus-4`。
- 自检：`GET /api/v1/terminal/models` 的 `models` 应含 `claude-opus-4`。
- 修复：管理端「星途服装」组织 → LLM Provider 页配 Anthropic provider（`supported_models` 含 `claude-opus-4`）+ 路由策略 `model_pattern=claude-*` 指向它，重跑 `seed_starclothing_apparel.py`。

### 5.2 提示词里 `/starclothing-mes-query` / `/starclothing-scm-query` 没被识别
- 必须从 `/` 弹窗里选中 chip，不能手敲纯文本。
- 自检：保存的 task.message 里这两段应该是结构化 chip 标记，不是 plain text。

### 5.3 `[tool_result FAIL]` MES / SCM 接口调用失败
- mock 网关未起或 API key 不匹配。
- 自检：
  ```bash
  curl -s http://localhost:8010/mes/api/v1/work-orders?status=pending -H "X-API-Key: mes-starclothing-demo-key" | head
  curl -s http://localhost:8010/scm/api/v1/capacity-calendar -H "X-API-Key: scm-starclothing-demo-key" | head
  ```
  应返回 JSON。

### 5.4 agent 输出「我没有收到任务」
- 检查 `/run` 请求体里 `message` 是否为空——必须把完整提示词作为 `message` 发送，任务创建时存的 `message` 不会被 agent 读到。

### 5.5 运行很久没动 / latency > 8 分钟
- glm-5.2 单轮推理慢，多轮 tool 调用 + 跨 MES+SCM 数据联动累计 5–7 分钟正常。超过 8 分钟大概率卡住，看后端日志 `docker logs ai_infra_backend --tail 100`。

### 5.6 输出大量走 `generate_docx`，前端 `text` 输出较短（与 PD-1 / PD-2 / PD-3 / SC-1 同款）
- 现象：SSE 的 `text` 事件累计仅 ~0–1500 字符，但 `.docx` 报告 ~30KB。ChatView 屏幕上看不到完整 4 段分析（排程表 / 风险提示 / 产线负载 / 补货建议）。
- 根因：与 PD-1 / PD-2 / PD-3 / SC-1 同款非确定性问题——agent 末轮跳过 text 流式分析，直接调 `generate_docx` 把全部内容打包成附件。glm-5.2 在不同轮次里随机选择"先 text 后 docx"或"直接 docx"路径，原 prompt 没有强约束。
- 修复：prompt §3.4 已加「先在 text 里流式输出完整分析，再生成 docx 附件」要求（输出要求段）。重跑后 text 应 ≥ 3000 字符，4 段分析全部出现在屏幕上。代价是延迟略增，可接受。
- 稳定性：连续 2 次跑都达标说明 prompt 约束生效；若第二次仍暴跌到 1000 以下，检查 prompt 是否真的有「## 输出要求」段。

### 5.7 `getWorkOrder` / `getRouting` / `getProductionOrder` 路径参数未替换
- 现象：agent 调 `getWorkOrder(work_order_no="XWO20260788")` 返回 `{"detail":"work order {work_order_no} not found"}`；调 `getRouting(product_code="P-FW2026-001")` 返回 `{"detail":"routing {product_code} not found"}`；调 `getProductionOrder(order_no="XPO20260833")` 返回 `{"detail":"production order {order_no} not found"}`——占位符未被替换为实际值。
- 根因：技能 wrapper 把 path 参数当作 query 参数透传，未替换到 OpenAPI path 占位符。SC-2 共 3 个 MES 端点 + SCM `getLeadtimeDiff` 受影响（与 SC-1 同款，跨多个 mock 系统普遍存在）。
- 影响：**不阻塞 SC-2 闭环**。agent 自主降级：`getWorkOrder` 404 → `listWorkOrders(work_order_no=...)`；`getRouting` 404 → `listRoutings(product_code=...)`；`getProductionOrder` 404 → `listProductionOrders(product_code=...)`；`getLeadtimeDiff` 404 → `estimateLeadtime`。prompt 第 1 步明确告诉 agent 遇到 404 时降级路径，省 1~2 轮 LLM 推理。
- 实测：v1 跑 10 次失败（getRouting + getProductionOrder + getLeadtimeDiff），演示时屏幕会看到红色 ✗ 标记，但 agent 自行降级后闭环仍完整（排程表 + 风险提示 + 产线负载 + 补货建议四段全部在 docx 里输出）。
- 修复（可选）：在技能 wrapper 里按 OpenAPI path 占位符替换路径参数。非阻塞性问题，本期演示按「agent 自主降级」路径通过。详见 `KNOWN_ISSUES.md` #1。

### 5.8 memory/extract 抽取 0~3 facts
- 现象：`trace memory/extract` 多数情况下 `facts: 0`，偶尔抽到 1~3 facts。
- 根因：与 PD-1 / PD-2 / PD-3 / SC-1 同款老问题，extract_memory 节点对中文长文本 + 多段结构化输出的抽取策略偏保守。
- 影响：非阻塞，本轮输出已完整；但长期记忆通道没真正发挥作用，跨任务复用能力弱。SC-2 同 PD-1~PD-3 / SC-1，记忆通道需要单独优化。
- 修复（可选）：调整 `extract_memory` 的 prompt，让其显式抽取结构化事实（工单号 + 排产产线 + 入库日三元组），非本期 SC-2 演示范围。详见 `KNOWN_ISSUES.md` #2。

---

## 6. 附：手工调 API 复现

不用前端的话，可以用 curl 走一遍：

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"starclothing","username":"prod-lead","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 SC-2 Agent 模板 id（v7d 起任务 config 必须绑 template_agent_id；
#    skill_ids 留空从模板继承，model 留空继承 claude-opus-4）
TPL_ID=$(docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -tAc \
  "SELECT id FROM agents WHERE slug='starclothing-sc2-factory-scheduling' AND deleted_at IS NULL AND organization_id='54f5f892-cf08-4a75-88b2-b649fea392a4'")
echo "template_agent_id=$TPL_ID"

# 3) 创建任务（绑模板；skill_ids 留空从模板继承，model_alias 留空继承 claude-opus-4）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"SC-2 下周工单产线排程与风险提示\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"claude-opus-4\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer 作为 message，见 §3.4；含两个技能 chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"下周排产：列出所有 pending 工单，结合产能日历、面料到货计划、补货建议做产线排程 + 风险提示。\\n\\n/starclothing-mes-query\\n/starclothing-scm-query\",\"stream\":true}"
```

短 composer 提示词文本见 §3.4（persona / 排产输入 / 排产逻辑 / 输出格式由 SC-2 Agent 模板
`system_prompt` 承载，不在 composer 里）。
