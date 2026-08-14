# SC-3 跨系统单据对账与差异闭环 · 终端任务演示

> SC-3 不再走 shell 脚本 + 超管 curl 的方式，而是**通过「终端」以业务用户身份创建任务**
> 完成演示：登录 → 新建任务 → 配置模型（glm-5.2）→ 写提示词 → /-mention 选择技能 →
> 运行 → 观察 agent 调用 CRM + MES + ERP 数据接口、本体、记忆，输出对账结果表 +
> 异常清单 + 闭环待办 + 汇总四段。
>
> 旧 shell 脚本 `sc3_reconciliation.sh` 保留以备对照（走超管 playground SSE，已被终端任务方式取代）。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 星途服装（slug = `starclothing`） |
| 用户名 | `finance-lead` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）容器在跑。
2. **数据已 seed**：`seed_starclothing_apparel.py` / `seed_starclothing_mock_connectors.py` / `seed_starclothing_ontology.py` / `seed_starclothing_agents.py` 至少跑过一次（详见根 `README.md` §2.2）。
3. **claude-opus-4 已可用**：Anthropic provider 的 `supported_models` 含 `claude-opus-4`。
   - 自检：`GET /api/v1/terminal/models`（用对应归口用户 token）应在 `models` 里看到 `claude-opus-4`。
4. **finance-lead 账号已存在且 active**：自检 `SELECT username, is_active FROM users WHERE username='finance-lead' AND organization_id=<starclothing org id>`。
5. **ERP / MES / CRM mock 端点正常**：
   ```bash
   curl -s http://localhost:8010/crm/api/v1/sales-orders -H "X-API-Key: crm-starclothing-demo-key" | head
   curl -s http://localhost:8010/mes/api/v1/work-orders -H "X-API-Key: mes-starclothing-demo-key" | head
   curl -s http://localhost:8010/erp/api/v1/production-costs -H "X-API-Key: erp-starclothing-demo-key" | head
   ```
   应返回 JSON 列表。

> ⚠️ SC-3 关键依赖三系统的对账端点：CRM `listSalesOrders` / `listReceivables` / `listComplaints`、
> MES `listWorkOrders`、ERP `listProductionCosts` / `listPayables`。任一不可用都会导致对账闭环断链。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/starclothing/terminal/login
```

- 用户名：`finance-lead`
- 密码：`12345678`

登录后落到 `/starclothing/terminal`（终端首页）。左上角应显示当前用户 `finance-lead` + 组织「星途服装」。

> 终端使用 **user-type JWT**（与超管 token 不同，scope 仅限本组织可见资源）。

### 3.2 新建任务

点击左栏「New Task / 新建任务」按钮，进入任务编辑器（HomeView composer）。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧的 ⚙️ 设置按钮，打开 TaskConfigDrawer，配置两项：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `finance-lead`（个人工作区）或「星途服装」 | 选个人工作区最干净；记忆仍按四级（组织+部门+团队+个人）自动载入 |
| Model | **`claude-opus-4`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | 让 agent 自主多轮调用 CRM + MES + ERP 工具；`ask` 是只读单轮、`plan` 只出方案不执行 |

> **本体 / RAG / 记忆不在 drawer 里配置**——这些是按用户 scope 自动注入的：
> - **4 个本体文件**（仅组织级 Cross 4 个）按 scope 注入；**财务部无 ERP/CRM/MES 领域本体**（identifiers.md 未建）——SC-3 对账靠下方「数据接口目录」（43 端点 + 参数 schema）+ 跨系统公共字段（`work_order_no` / 销售订单号）交叉关联，不靠本体标识符前缀。
> - SC-3 无 RAG（`rag_collection_name=None`），不触发 RAG 检索；
> - 长期记忆按「组织+部门+团队+个人」四级全集自动载入。

> **场景模板（template_agent_id）**：SC-3 已改为四层架构——persona / 对账输入 /
> 对账逻辑（5 条）/ 输出骨架由 Agent 模板 `starclothing-sc3-reconciliation`
> 的 `system_prompt` 承载，用户 composer 只写「目标 + 对象 + 技能 chip」（见 §3.4）。
> 任务 config 必须绑 `template_agent_id = <该 slug 的 UUID>`，运行时 `load_config`
> 才会把模板 persona 拼到 system prompt 最前（`trace template` / `template:true` 出现），
> 技能与模型留空即从模板继承（`starclothing-crm-query` + `starclothing-mes-query` +
> `starclothing-erp-query` + claude-opus-4）。**前端 drawer 暂未暴露「场景模板」选择器**，
> 用 §6 手工调 API 在 `config` 里显式带 `template_agent_id` 绑定。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 composer 输入框（`MentionInput`，支持 `/` 触发技能、`@` 触发工作区文件）里输入：

> 敲 `/` 会弹出技能选择菜单，输入 `crm` 过滤，选中 **`starclothing-crm-query`**；
> 再敲 `/` 输入 `mes` 过滤，选中 **`starclothing-mes-query`**；再敲 `/` 输入 `erp`
> 过滤，选中 **`starclothing-erp-query`**——三个技能 chip 都插入到提示词中。

完整提示词如下（直接复制，约 90 字符）：

```
本月单据对账：CRM 销售订单 ↔ MES 工单 ↔ ERP 生产成本/应收/应付，输出对账差异 + 异常清单 + 闭环待办。

/starclothing-crm-query
/starclothing-mes-query
/starclothing-erp-query
```

> **v7d 起改为四层架构**（对齐 PD-2 `§3.4` / SC-1 / SC-2 `§3.4`）：user composer 只写
> **目标 + 对象 + 技能 chip**，persona / 对账输入（CRM 销售订单+客诉+应收 / MES 工单 /
> ERP 生产成本+应付付款状态）/ 对账逻辑 5 条（销售↔工单 / 工单↔成本 / 销售↔应收 /
> 应付付款状态 / 客诉↔工单）/ 输出骨架（对账结果表 + 异常清单 + 闭环待办 + 汇总四段）
> 由 Agent 模板 `starclothing-sc3-reconciliation` 的 `system_prompt` 承载（649 字符）。
> 任务 config 必须绑定 `template_agent_id = <starclothing-sc3-reconciliation 的 UUID>`，
> 运行时 `load_config` 才会注入模板（trace `template` 出现、`template:true`）。技能与模型
> 留空即从模板继承（`starclothing-crm-query` + `starclothing-mes-query` +
> `starclothing-erp-query` + claude-opus-4）。runtime 的 `[输出协议]`+`[工具调用策略]`
> 兜底「先 text 后 docx / 不要臆造 / 最少端点集」——故 composer 不再写执行步骤、输出要求、输出格式。
>
> 若前端 drawer 暂未暴露「场景模板」选择器，可用 §6 手工调 API 在 `config` 里显式带
> `template_agent_id` 复现（`SELECT id FROM agents WHERE slug='starclothing-sc3-reconciliation'`）。

> ⚠️ **关键 1**：三个 `/starclothing-*-query` chip 必须从 `/` 菜单选中，不能手敲文本。agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时 message 里写 `/starclothing-crm-query` 等也会被同款正则解析（见 §6）。
>
> ⚠️ **关键 2**：模板 `system_prompt` 不硬编码端点名（如 `listSalesOrders` / `listWorkOrders` /
> `listProductionCosts` / `listPayables` / `listReceivables` / `listComplaints`），由 agent 结合
> 数据接口目录自主发现。**原 shell playbook 误引的不存在端点 `listPayments` 已删除**——对账逻辑 4
> 改用 `listPayables` 返回的付款状态字段（已付/未付/部分付）核对，不再依赖独立的收款端点。
>
> ⚠️ **关键 3**：财务部无领域本体（仅 Cross 4 个通用文件），跨系统对账全靠数据接口目录的参数
> schema + 返回数据里的公共字段（`work_order_no` 串 MES 工单与 ERP 生产成本；`so_no`/销售订单号
> 串 CRM 销售订单与应收）。agent 据公共字段自主关联，本体贡献弱于 SC-1/SC-2（非阻塞）。

#### 资源注入机制（任务运行时自动完成，无需配置）

任务运行时，agent runtime 会按 finance-lead 的 scope 自动注入以下资源（**部门级 scope 拆分后**，finance-lead 看到财务部范围内的资源）：

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | scope_filter 过滤后：仅组织级 Cross 4 个（财务部无 ERP/CRM/MES 领域本体，identifiers 未建——agent 据数据接口目录 + 公共字段关联对账） | 4 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出 finance-lead 可调用的接口 | 3 systems（CRM 14 + MES 13 + ERP 16）/ 43 interfaces |
| **RAG** | 财务部 scope 下无 RAG collection | 0 collection |
| **长期记忆** | 4 级（组织+部门+团队+个人）按权限聚合；load_memory 节点载入 | 4 history + 6 facts |
| **技能** | `template_agent_id` 继承 + /-mention chip 解析；config 留空 skill_ids 即从模板 `starclothing-sc3-reconciliation` 继承 | 3 skills（财务部级 starclothing-crm-query + starclothing-mes-query + starclothing-erp-query） |
| **记忆沉淀** | extract_memory 节点抽取本轮可沉淀事实写入个人级 Memory | 0~N facts（详见 §5.8） |

> **跨部门数据访问**：finance-lead 调用的是财务部 scope 下 proxy 复制的 CRM/MES/ERP 数据接口（绑定同一组织级 `tool_connector`，按财务部开放端点子集）。SC-3 已覆盖 CRM + MES + ERP 三个核心系统，单据对账联动所需数据完整。

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
| `[trace]` (template) | 场景模板 persona 注入（`template:true`——SC-3 模板 system_prompt 拼到 system prompt 最前，继承 skill_ids/model_alias） |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 组织级 Cross 本体注入 system prompt（4 files，财务部无领域本体） |
| `[trace]` (data_interface) | 数据接口目录注入（按用户权限全量，3 systems 43 interfaces） |
| `[trace]` (skill) | /-mention 解析引用了哪三个技能 |
| `[trace]` (memory/extract) | 记忆沉淀抽取（写个人级 Memory） |
| `[phase] llm #0/#1/#2/#3` | 每个 LLM 调用轮次 |
| `[tool_call]` | agent 调用工具（如 CRM `listSalesOrders` / MES `listWorkOrders` / ERP `listProductionCosts` / `generate_docx`） |
| `[tool_result]` | 工具返回（ok / FAIL） |
| `[text]` | LLM 流式输出 token（直接渲染到对话气泡） |
| `[done]` | agent_loop 收口（带 usage 统计） |
| `[final]` | 任务结束，附 latency_ms + session_id |

> 终端前端 ChatView 目前只渲染 `text` / `tool_call` / `tool_result`；`trace` 事件保存在 assistant 消息的 `metadata_.traces` 里，管理后台或 `GET /terminal/tasks/{id}/messages` 可见。

典型 SC-3 运行约 8–12 分钟（3 系统 5 类对账、跨 CRM/MES/ERP 多源数据联动，tool_call 预计 15–25 次）。

---

## 4. 期望输出

agent 会输出四段 + 1 个附件：

### 4.1 对账结果表

8 列（单据类型 / 单据号 / 关联工单 / 标准金额 / 实际金额 / 差异 / 差异率 / 状态），覆盖 5 类对账。mock 数据真实单据号前缀：CRM 销售订单 `XSO2026xxx`、CRM 应收 `XAR2026xxx`、CRM 客诉 `XCP2026xxx`、MES 工单 `XWO2026xxx`（SC-3 用 `WO` 前缀）、ERP 生产成本 `XPC2026xxx`、ERP 应付 `XAP2026xxx`：

| 单据类型 | 单据号 | 关联工单 | 标准金额 | 实际金额 | 差异 | 差异率 | 状态 |
|---|---|---|---|---|---|---|---|
| 销售订单 | XSO20260xxx | XWO2026xxx | 订单数量 | 工单完成数量 | ±N | ±x% | 一致/差异 |
| 生产成本 | XPC20260xxx | XWO2026xxx | 标准成本 | 实际成本 | ±N | ±x% | 正常/超支 |
| 应收 | XAR20260xxx | （按 so_no） | 订单金额 | 应收余额 | ±N | ±x% | 一致/差异 |
| 应付 | XAP20260xxx | （供应商） | 应付金额 | 付款状态 | — | — | 已付/未付/逾期 |
| 客诉 | XCP20260xxx | XWO2026xxx | — | — | — | — | 重复投诉高亮 |

> 对账逻辑 agent 会自洽应用：(1) 销售订单 ↔ 工单按 `work_order_no` 交叉，差异 >2% 标注；(2) 工单 ↔ 生产成本按 `work_order_no` 比对，超支 >5% 标注；(3) 销售 ↔ 应收按订单号；(4) 应付按付款状态；(5) 客诉关联工单。

### 4.2 异常清单

按异常类型分组（数量差异 / 金额差异 / 单据缺失），每条 = 单据号 + 异常类型 + 责任方 + 处理建议：

| 单据号 | 异常类型 | 责任方 | 处理建议 |
|---|---|---|---|
| XSO2026xxx | 数量差异 | 销售部 | 订单数 vs 工单完成数差异 >2%，补料或冲销 |
| XPC2026xxx | 金额差异 | 生产部 | 实际成本超支 >5%，核因并审批 |
| XAP2026xxx | 单据缺失 | 采购部 | 应付逾期未付，催付或对账供应商 |

### 4.3 闭环待办

异常单据 → 责任部门 → 处理时限：

| 异常单据 | 责任部门 | 处理时限 |
|---|---|---|
| XSO2026xxx | 销售部 | 3 个工作日内补料或冲销 |
| XPC2026xxx | 生产部 | 5 个工作日内核因审批 |
| XAP2026xxx | 采购部 | 7 个工作日内催付对账 |

### 4.4 汇总

本期对账单据数 / 通过数 / 异常数 / 异常率：

| 指标 | 值 |
|---|---|
| 本期对账单据数 | N（CRM 销售 + MES 工单 + ERP 成本/应付/应收 + CRM 客诉合计） |
| 通过数 | N |
| 异常数 | N |
| 异常率 | x% |

### 4.5 .docx 报告附件

agent 会调 `generate_docx` 工具把上述分析打包成 `星途服装_本月单据对账报告_YYYYMMDD.docx`（约 30~40 KB），可下载分发。

### 4.6 SSE trace 事件（演示时截图可证）

任务运行期间，SSE 流除常规 `step` / `phase` / `text` / `tool_call` / `tool_result` / `final` 外，会发射 **5 个 `trace` 事件**（SC-3 无 RAG，无 rag trace）：

| trace | 含义 | 实测值 |
|---|---|---|
| `category=memory, subtype=load` | 长期记忆载入 | 4 history + 6 facts |
| `category=ontology` | 组织级本体注入 | 4 files（仅 Cross，财务部无领域本体） |
| `category=data_interface` | 数据接口目录注入 | 3 systems / 43 interfaces（财务部级 CRM + MES + ERP） |
| `category=skill` | /-mention 引用技能 | 3 skills（crm + mes + erp） |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | 0~N facts（详见 §5.8） |
| `category=template` | 场景模板 persona 注入 | `template:true`，chars=649 |

### 4.7 实测延迟与 token 用量（v1 首跑基线）

> v1 首跑基线待填（首次按 §6 跑通后回填 latency_ms / input_tokens / output_tokens / tool_calls /
> 失败数 / 4 段是否上屏 / docx 是否生成 / 6 类 trace 是否全）。预期：latency 8–12 min、tool_calls
> 15–25、4 段全上屏 + docx 闭环、`listPayments` 不再被引用。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `claude-opus-4`
- Anthropic provider 未配或 `supported_models` 不含 `claude-opus-4`。
- 自检：`GET /api/v1/terminal/models` 的 `models` 应含 `claude-opus-4`。
- 修复：管理端「星途服装」组织 → LLM Provider 页配 Anthropic provider（`supported_models` 含 `claude-opus-4`）+ 路由策略 `model_pattern=claude-*` 指向它，重跑 `seed_starclothing_apparel.py`。

### 5.2 提示词里 `/starclothing-crm-query` / `/starclothing-mes-query` / `/starclothing-erp-query` 没被识别
- 必须从 `/` 弹窗里选中 chip，不能手敲纯文本。
- 自检：保存的 task.message 里这三段应该是结构化 chip 标记，不是 plain text。

### 5.3 `[tool_result FAIL]` CRM / MES / ERP 接口调用失败
- mock 网关未起或 API key 不匹配。
- 自检：
  ```bash
  curl -s http://localhost:8010/crm/api/v1/sales-orders -H "X-API-Key: crm-starclothing-demo-key" | head
  curl -s http://localhost:8010/mes/api/v1/work-orders -H "X-API-Key: mes-starclothing-demo-key" | head
  curl -s http://localhost:8010/erp/api/v1/production-costs -H "X-API-Key: erp-starclothing-demo-key" | head
  ```
  应返回 JSON。

### 5.4 agent 输出「我没有收到任务」
- 检查 `/run` 请求体里 `message` 是否为空——必须把完整提示词作为 `message` 发送，任务创建时存的 `message` 不会被 agent 读到。

### 5.5 运行很久没动 / latency > 12 分钟
- SC-3 跨 3 系统 5 类对账，tool_call 多、延迟 8–12 min 正常。超过 12 分钟大概率卡住，看后端日志 `docker logs ai_infra_backend --tail 100`。

### 5.6 输出大量走 `generate_docx`，前端 `text` 输出较短（与 PD-1~PD-3 / SC-1~SC-2 同款）
- 现象：SSE 的 `text` 事件累计较短，但 `.docx` 报告 ~30KB。ChatView 屏幕上看不到完整 4 段分析。
- 根因：与其它场景同款——agent 末轮跳过 text 流式分析，直接调 `generate_docx` 打包。runtime `[输出协议]` 已兜底「先 text 后 docx」，重跑通常达标；glm-5.2 非确定性导致偶发跳过。
- 修复：runtime `[输出协议]`+`[工具调用策略]` 已注入；重跑后 text 应 ≥ 3000 字符，4 段分析全部出现在屏幕上。

### 5.7 agent 试图调 `listPayments` 失败
- 现象：agent 调 `listPayments` 返回 404 / 端点不存在。
- 根因：**mock ERP/CRM 无 `listPayments` 端点**（原 shell playbook + 老 agent prompt 误引，已在 v7d template 改写时删除）。
- 修复状态：**已修**（template `system_prompt` 对账逻辑 4 改用 `listPayables` 返回的付款状态字段核对，不再依赖独立收款端点）。若仍出现，说明跑的是旧 prompt——重新落库 SC-3 agent system_prompt（§6 步骤 2 解析的 TPL_ID 应对应 649 字 prompt）。

### 5.8 memory/extract 抽取 0~3 facts
- 现象：`trace memory/extract` 多数情况下 `facts: 0`，偶尔抽到 1~3 facts。
- 根因：与其它场景同款老问题，extract_memory 节点对中文长文本 + 多段结构化输出的抽取策略偏保守（`KNOWN_ISSUES.md` #2 已修 v7d5，正常抽取）。
- 影响：非阻塞，本轮输出已完整。

### 5.9 旧 shell 脚本 `sc3_reconciliation.sh` 还能用吗
- 能跑（走超管 root token + `/agents/{id}/playground` SSE），但**已被终端任务方式取代**，不再作为标准演示路径。新组织 demo 一律走 §3 终端任务方式（业务用户身份 + template）。shell 脚本保留仅作历史对照。

---

## 6. 附：手工调 API 复现

不用前端的话，可以用 curl 走一遍：

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"starclothing","username":"finance-lead","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 SC-3 Agent 模板 id（v7d 起任务 config 必须绑 template_agent_id；
#    skill_ids 留空从模板继承，model 留空继承 claude-opus-4）
TPL_ID=$(docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -tAc \
  "SELECT id FROM agents WHERE slug='starclothing-sc3-reconciliation' AND deleted_at IS NULL AND organization_id='54f5f892-cf08-4a75-88b2-b649fea392a4'")
echo "template_agent_id=$TPL_ID"

# 3) 创建任务（绑模板；skill_ids 留空从模板继承，model_alias 留空继承 claude-opus-4）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"SC-3 跨系统单据对账与差异闭环\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"claude-opus-4\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer 作为 message，见 §3.4；含三个技能 chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"本月单据对账：CRM 销售订单 ↔ MES 工单 ↔ ERP 生产成本/应收/应付，输出对账差异 + 异常清单 + 闭环待办。\\n\\n/starclothing-crm-query\\n/starclothing-mes-query\\n/starclothing-erp-query\",\"stream\":true}"
```

短 composer 提示词文本见 §3.4（persona / 对账输入 / 对账逻辑 / 输出格式由 SC-3 Agent 模板
`system_prompt` 承载，不在 composer 里）。
