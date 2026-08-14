# FIN-01 多系统对账与应收催办 · 终端任务演示

> 财务部对账会计 `fin-accountant`（对账子任务）/ 应收会计 `fin-receivable`（应收子任务）登录终端，新建任务、配置 `glm-5.2` + `craft`、`/agileac-fin-erp-crm-query` 选技能、写提示词、运行，agent 自主多轮跨 ERP 凭证/生产成本/应付 + MES 工单 + SCM 报价 + PLM 成本台账做四方对账（对账子任务），或调 CRM 应收/客户做逾期催办（应收子任务）。
>
> **员工 vibe working 视角**：财务会计原本要在 ERP/MES/SCM/PLM 多系统间反复登录、导表、对差异、追逾期——现在通过 SSO 一次免登跨四系统查询，一句话拿到对账差异与催办清单。AI 是财务员工的副驾驶，**不对客户直接催收**（催办通过待办机制推送 sal-ops / fin-receivable）。
>
> 本场景验证 **痛点 B 录入报表 + C 对账 + D 系统集成与体验优化（SSO 免登跨系统）+ E 应收催办**——11 场景中唯一跨 4 系统对账 + SSO 演示场景。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 敏睿空调（slug = `agileac`） |
| 用户名 | `fin-accountant`（对账子任务）/ `fin-receivable`（应收子任务） |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |
| 部门 | 财务部 · 对账组 `fin-recon` / 应收组 `fin-receivable` |

> 两子任务同属财务部，技能同源（部门级 `agileac-fin-erp-crm-query`，绑 ERP 全集 + MES 工单成本 + SCM 报价 + PLM 成本台账 + CRM 应收只读，跨 5 系统对账 + SSO 演示）；无 RAG。按子任务切归口员工验证组级 scope 隔离。

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）+ `ai_infra_postgres` 容器在跑。
2. **数据已 seed**（按 `README.md` §9 顺序执行）：
   - `seed_agileac_org.py`（含 `fin-accountant` / `fin-receivable` 用户 + 财务部 + 对账组/应收组）
   - mock 6 系统 agileac tenant 数据已内置（`mock/mock/systems/*/data.py` 的 `_build_agileac`），含 ERP 生产成本（按工单归集，含 work_order_no）、应付 AGAP（含 2 条逾期：AGAP20260002/S-HEX-001、AGAP20260004/S-REF-001）、凭证 BV-AG-2026-0512（财务复核中，跨系统 SSO 演示）；CRM 应收（含逾期）；mock 容器重启即生效
   - `seed_agileac_mock_connectors.py`（含部门级技能 `agileac-fin-erp-crm-query`，**跨 5 系统只读**：ERP 凭证/应付/生产成本/成本中心/物料 + MES 工单 + SCM 报价 + PLM 成本台账 + CRM 应收/客户/订单）
   - `seed_agileac_ontology.py`（33 组织级含 ERP/MES/SCM/PLM/CRM 各域 `identifiers.md`——凭证 BV-AG-、应付 AGAP、应收 AGINV、工单 AWO、报价 AGQ、成本台账 AGCL = 33 个本体文件对该用户可见——org scope 资源对所有部门用户可见）
   - `seed_agileac_agents.py`（含 `agileac-fin-01-reconciliation-receivable` agent 模板配置，四层架构 system_prompt）
3. **glm-5.2 已可用**：组织已配智谱 AI provider，`supported_models` 含 `glm-5.2`。
   - 自检：`GET /api/v1/terminal/models`（用 fin-accountant token）应在 `models` 里看到 `glm-5.2`。
4. **fin-accountant / fin-receivable 账号已存在且 active**：
   ```bash
   docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
     "SELECT username, is_active FROM users WHERE username IN ('fin-accountant','fin-receivable');"
   ```
5. **ERP/MES/SCM/PLM/CRM mock 端点正常**：
   ```bash
   curl -s "http://localhost:8010/erp/vouchers?period=2026-06" -H "X-API-Key: erp-agileac-demo-key" | head
   curl -s "http://localhost:8010/erp/production-costs" -H "X-API-Key: erp-agileac-demo-key" | head
   curl -s "http://localhost:8010/mes/work-orders" -H "X-API-Key: mes-agileac-demo-key" | head
   curl -s "http://localhost:8010/scm/quotations?material_code=M-COMP-GT-24K" -H "X-API-Key: scm-agileac-demo-key" | head
   curl -s "http://localhost:8010/plm/cost-ledger?style_code=P-RC-WALL-15" -H "X-API-Key: plm-agileac-demo-key" | head
   curl -s "http://localhost:8010/crm/receivables" -H "X-API-Key: crm-agileac-demo-key" | head
   ```
   均应返回 JSON 列表。

> ⚠️ FIN-01 关键依赖 4 件事：ERP `listVouchers`/`listProductionCosts`/`listPayables` + MES `listWorkOrders`/`getWorkOrder` + SCM `compareQuotations`/`listQuotations` + PLM `getCostLedger`（跨 4 系统对账，全由财务部技能绑定，SSO 免登）+ CRM `listReceivables`/`listCustomers`（应收催办）。无 RAG——对账差异率阈值等规则由模板 system_prompt 承载。
>
> ⚠️ **技能 slug 保留 `agileac-fin-erp-crm-query`（历史命名）但实际绑定跨 5 系统（ERP+MES+SCM+PLM+CRM）**——为支撑 README §8.9 设计的四方对账 + SSO，FIN 技能在 P1 四层化时扩绑了 MES/SCM/PLM 只读端点（slug 不改，避免孤儿与 ripple）。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/agileac/terminal/login
```

- 对账子任务：用户名 `fin-accountant`
- 应收子任务：用户名 `fin-receivable`
- 密码：`12345678`

登录后落到 `/agileac/terminal`。左上角应显示对应用户 + 组织「敏睿空调」 + 部门「财务部」。

> 终端使用 **user-type JWT**。`fin-accountant`（对账组）/ `fin-receivable`（应收组）的 scope 包含：组织级资源（33 组织本体）+ 财务部部门级资源（跨 5 系统技能 `agileac-fin-erp-crm-query`）+ 个人工作区。跨系统 SSO 价值：员工一次登录即可免登调 ERP/MES/SCM/PLM/CRM，不再受困频繁登录。

### 3.2 新建任务

点左栏「New Task / 新建任务」按钮，进入任务编辑器（HomeView composer）。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧 ⚙️ 设置按钮，打开 TaskConfigDrawer，配置 4 项：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `fin-accountant` 或 `fin-receivable`（个人工作区） | 干净；记忆仍按四级（组织+部门+团队+个人）自动载入 |
| Model | **`glm-5.2`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | agent 需多轮跨 5 系统调用 + generate_docx；`ask` 只读单轮不够 |
| 场景模板 | `agileac-fin-01-reconciliation-receivable` | **必绑**——对账规则/SSO cue/输出骨架由模板 system_prompt 承载；技能可留空从模板继承，或显式选 `agileac-fin-erp-crm-query` |

> 若 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id`。
>
> **本体 / 记忆不在 drawer 里配置**——按用户 scope 自动注入：
> - 33 个组织级本体（含 ERP/MES/SCM/PLM/CRM 各域 identifiers.md）自动注入；
> - FIN-01 无 RAG（对账规则由模板 system_prompt 承载）；
> - 长期记忆按「组织+部门+团队+个人」四级自动载入。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 composer 输入框（`MentionInput`）里输入：

> 敲 `/` 弹出技能菜单，输入 `fin` 过滤，选中 **`agileac-fin-erp-crm-query`** 即把技能 chip 插入提示词。

**对账子任务**提示词（`fin-accountant` 登录，直接复制，约 60 字——**纯对账业务请求，不带任何编排/端点指令**）：

```
对敏睿空调 2026-06 期做四方对账：ERP 凭证 ↔ MES 工单成本 ↔ SCM 报价 ↔ PLM 成本台账，标出差异率 >2% 的异常。

/agileac-fin-erp-crm-query
```

**应收子任务**提示词（`fin-receivable` 登录，直接复制，约 35 字）：

```
催办敏睿空调逾期应收，输出催办清单与推送对象。

/agileac-fin-erp-crm-query
```

> **四层架构**（详见 `SCENARIO_AUTHORING_GUIDE.md`）：user composer 只写**业务目标 + 会计期间/对象 + 技能 chip**。四方对账路径（ERP 凭证 ↔ MES 工单成本 ↔ SCM 报价 ↔ PLM 成本台账）、差异率 >2% 阈值、SSO 免登跨系统、应收催办推送对象、按 work_order_no/material_code 跨码空间关联——**全部由 Agent 模板 `agileac-fin-01-reconciliation-receivable` 的 `system_prompt` 承载**（见 `## 职责` / `## 对账规则` / `## 输出格式` 三节），不写进用户提示词。任务 config 必须绑定 `template_agent_id = <agileac-fin-01-reconciliation-receivable 的 UUID>`，运行时 `load_config` 才会注入模板（trace `template` 出现、`template:true`）。技能留空从模板继承 `agileac-fin-erp-crm-query`；模型模板默认 `glm-5.2`（与 drawer 一致，无需覆写）。
>
> 若前端 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id` 复现（`SELECT id FROM agents WHERE slug='agileac-fin-01-reconciliation-receivable'`）。

> ⚠️ **关键 1**：`/agileac-fin-erp-crm-query` 必须从 `/` 菜单选中 chip，不能手敲文本。agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时 message 里写 `/agileac-fin-erp-crm-query` 也会被同款正则解析（见 §6）。
>
> ⚠️ **关键 2**：提示词**只写业务目标 + 会计期间**，不写"调 ERP 凭证再调 MES 工单成本"这类编排指令——四方对账路径、SSO 免登、差异阈值全由模板 system_prompt 驱动。这正是 SSO 价值演示点：composer 不需要告诉 agent 先登哪个系统后登哪个系统，agent 一次跨 4 系统免登调用。
>
> ⚠️ **关键 3**：composer 写明会计期间（2026-06 期）与四方对象——让 agent 有明确对账锚点。本体 identifiers.md 已写明凭证前缀 BV-AG-、应付/应收发票 AGAP/AGINV、工单 AWO、报价 AGQ、成本台账 AGCL，跨系统按 work_order_no / material_code 关联勿直传异构编码，agent 调跨系统端点前读此表，杜绝 404。

#### 资源注入机制（任务运行时自动完成，无需配置）

任务运行时，agent runtime 会按 fin-accountant / fin-receivable 的 scope 自动注入以下资源到 system prompt：

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | 按 scope 注入（组织级 33 含 5 域 identifiers） | 33 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出 | ERP/MES/SCM/PLM/CRM 5 systems / ~30 interfaces |
| **RAG** | 无（FIN-01 不绑 RAG） | — |
| **长期记忆** | 4 级聚合；load_memory 节点载入 | 若干 history + facts |
| **技能** | /-mention 解析 + 模板继承 | 1 skill（agileac-fin-erp-crm-query，跨 5 系统） |
| **记忆沉淀** | extract_memory 抽取本轮可沉淀事实 | 0~3 facts |

### 3.5 提交运行

按回车提交。前端 `POST /api/v1/terminal/tasks` 创建任务，再 `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}`——**这才是真正发给 agent 的输入**。手工调 API 时 `/run` 也要把完整提示词带上。

### 3.6 观察 SSE 事件流

事件类型同其他终端任务场景。FIN-01 关注：

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载配置（`template:true` 表示模板已注入） |
| `[trace]` (template) | 场景模板 `agileac-fin-01-reconciliation-receivable` 注入 |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 33 组织本体注入（含 5 域 identifiers） |
| `[trace]` (data_interface) | 数据接口目录注入（按财务部权限，5 系统可见） |
| `[trace]` (skill) | /-mention 引用 `agileac-fin-erp-crm-query` |
| `[trace]` (memory/extract) | 记忆沉淀抽取 |
| `[phase] llm` | LLM 调用轮次 |
| `[tool_call]` | agent 跨系统调用 ERP `listVouchers`/`listProductionCosts` + MES `listWorkOrders` + SCM `compareQuotations` + PLM `getCostLedger`（对账子任务）；或 CRM `listReceivables`/`listCustomers`（应收子任务） |
| `[tool_result]` | 工具返回（含 BV-AG-2026-0512 凭证、AGAP 逾期应付、AWO 工单等） |
| `[text]` | LLM 流式输出对账差异表/催办清单 |
| `[done]` / `[final]` | 收口 + usage + latency |

> 典型 FIN-01 运行约 4–8 分钟（5–7 轮 LLM + 15 次跨 5 系统 tool 调用 + LLM 推理 + 记忆节点）。FIN-01 无部门级 RAG，但 org 级员工综合库 auto-load 仍触发 `trace rag`。

---

## 4. 期望输出

### 4.1 对账子任务：四方对账差异表 + 异常清单

| 工单 | 产品 | ERP 生产成本 | PLM 成本台账 | SCM 报价 | MES 工单 | 差异 | 差异率 | 异常等级 |
|---|---|---|---|---|---|---|---|---|
| AWO20260101 | P-RC-WALL-15 | 4200 | 4180 | 4150 | 4220 | 70 | 1.67% | 中 |
| AWO20260105 | P-RC-CAB-30 | 6800 | 6450 | 6500 | 6850 | 400 | 5.88% | 高 ✗ |

#### 异常清单
- AWO20260101：ERP 4200 vs PLM 4180 差异 20（+0.48%，<2% 阈值，材料成本更新滞后），催办 scm-buyer 更新报价后回写 PLM 成本台账。
- AWO20260105：差异 5.88%（>2% 阈值），需重新核对物料成本——重点排查 SCM 报价是否含旺季附加、PLM 成本台账是否滞后。
- **跨系统 SSO 演示**：凭证 BV-AG-2026-0512（财务复核中）在 PLM 与 ERP 双侧呈现，agent 免登跨查两侧状态一致，避免重复登录。

### 4.2 应收子任务：催办清单 + 推送对象汇总

#### 应收催办清单

| 发票号 | 客户 | 应收余额 | 逾期天数 | 催办对象 | 关键提示 |
|---|---|---|---|---|---|
| AGINV202605005 | C-AG-002 | ¥100,000 | 35 | sal-ops | 客户已确认下周付款 |
| AGINV202605008 | C-AG-005 | ¥80,000 | 15 | fin-receivable | 邮件催办，未回复 |

#### 推送对象汇总
- sal-ops：3 单合计 ¥280,000
- fin-receivable：2 单合计 ¥150,000
- 催办方式：电话 + 邮件 + OA 待办（通过待办机制推送，不直接调用其他部门 agent）

### 4.3 .docx 报告附件

agent 调 `generate_docx` 工具把上述差异表/催办清单打包成 `敏睿空调_对账与应收催办_YYYYMMDD.docx`（约 35 KB），可下载分发归档。

### 4.4 SSE trace 事件（演示时截图可证）

| trace | 含义 | 期望实测值 |
|---|---|---|
| `category=template` | 场景模板注入（必出） | slug=agileac-fin-01-reconciliation-receivable + chars |
| `category=memory, subtype=load` | 长期记忆载入 | 若干 history + facts |
| `category=ontology` | 组织本体注入（含 5 域 identifiers） | 33 files |
| `category=data_interface` | 数据接口目录注入（按财务部权限，5 系统可见——SSO 价值） | 5 systems / ~30 interfaces |
| `category=skill` | /-mention 引用技能 | 1 skill（agileac-fin-erp-crm-query，跨 5 系统） |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | 0~3 facts |

> FIN-01 不绑部门级 RAG，但 org 级「员工综合知识库」对全员 auto-load，`trace rag` **仍会触发**（实测 5 hits，命中含"对账/凭证/应收"关键词的 chunk，非 FIN 部门 RAG）。6 类 trace（rag + memory.load + ontology + data_interface + skill + memory.extract）全出。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `glm-5.2`
- 智谱 AI provider 未配或 `supported_models` 不含 `glm-5.2`。修复：管理端配智谱 AI provider（`supported_models` 含 `glm-5.2`）+ 路由策略 `model_pattern=glm-*`，重跑 `seed_agileac_org.py`。

### 5.2 提示词里 `/agileac-fin-erp-crm-query` 没被识别
- 必须从 `/` 弹窗选 chip，不能手敲。自检：task.message 里这段应是结构化 chip 标记。

### 5.3 `[tool_result FAIL]` 跨系统接口调用失败
- mock 网关未起或 API key 不匹配。自检 5 系统端点（见 §2.5）均应返回 JSON。注意每个系统用各自的 agileac demo key（erp-agileac-demo-key / mes-agileac-demo-key / scm-agileac-demo-key / plm-agileac-demo-key / crm-agileac-demo-key）。

### 5.4 `fin-accountant` 看不到 MES/SCM/PLM 数据接口
- 现象：`data_interfaces` 只含 ERP/CRM，不含 MES/SCM/PLM——四方对账缺三方。
- 根因：FIN 技能未扩绑 MES/SCM/PLM（旧版只绑 ERP+CRM）。P1 四层化时已扩绑，但需重跑 `seed_agileac_mock_connectors.py` 落库。
- 自检：`GET /api/v1/terminal/resources`（fin-accountant token）的 `data_interfaces` 应含 MES `listWorkOrders`/`getWorkOrder`、SCM `listQuotations`/`compareQuotations`、PLM `getCostLedger`。
- 修复：重跑 `seed_agileac_mock_connectors.py`，确认 FIN 技能 `agileac-fin-erp-crm-query` 的 bindings 含 mes/scm/plm。

### 5.5 agent 输出「我没有收到任务」
- 检查 `/run` 请求体里 `message` 是否为空——必须把完整提示词作为 `message` 发送。

### 5.6 运行很久没动 / latency > 6 分钟
- 跨 5 系统 tool 调用累计 4–6 分钟正常。超过 10 分钟看 `docker logs ai_infra_backend --tail 100`。

### 5.7 trace 里没有 `rag` 事件
- 正常——FIN-01 不绑部门级 RAG（对账差异率阈值等规则由模板 system_prompt 承载），但 org 级员工综合库 auto-load 仍会触发 `trace rag`（实测 5 hits，非阻塞）。6 类 trace 全出。

### 5.8 agent 只调了 ERP 没跨系统对账
- 现象：对账子任务只调 ERP `listVouchers`/`listProductionCosts`，没调 MES/SCM/PLM，"四方对账"变 ERP 内部对账。
- 根因：FIN 技能未扩绑 MES/SCM/PLM（见 §5.4），或模板 `system_prompt` 的 `## 职责` 对账子任务段未引导跨系统调用。
- 修复：先确认 §5.4（技能扩绑已落库）；再确认 `load_config template:true` + 模板 `system_prompt` 含"调 SCM 报价 → 调 PLM 成本台账 → 调 MES 工单"跨系统路径。

### 5.9 `tool_call` args 全 `{}`
- 现象：所有 `tool_call.arguments={}`，需要参数的端点（如 `getCostLedger(style_code=...)`、`listWorkOrders(won=...)`）返回 500。
- 根因：`_build_tools`（`app/agents/graph/nodes.py`）manifest 占位 schema 覆盖问题（详见 `SCENARIO_AUTHORING_GUIDE.md` §6.10）。
- 修复：只要有一条 `tool_call` args 非 `{}` 就说明 `_build_tools` 正常；全 `{}` 立即查 `nodes.py` `_build_tools`。

### 5.10 path 参数端点（`getWorkOrder`/`getCostLedger`）返回 404
- 现象：agent 调 `getWorkOrder(won="AWO20260101")` 返回 `{won} not found`——path 占位符未替换。
- 影响：**不阻塞闭环**。agent 自主降级到 `listWorkOrders`/`listVouchers`（query 参数端点）仍能拿到完整信息做对账。
- 修复（可选）：技能 wrapper 按 OpenAPI path 占位符替换。非阻塞性，本期按「agent 自主降级」通过。

### 5.11 memory/extract 抽取 0~3 facts
- 非阻塞；长期记忆跨任务复用弱。修复（可选）：调整 `extract_memory` prompt 显式抽取工单→成本→差异三元组。

### 5.12 对账差异杜撰（不来自接口）
- 现象：差异表数值与 ERP/MES/SCM/PLM 接口返回不符。
- 根因：agent 没真调跨系统端点，靠模型先验杜撰数字。
- 修复：确认 §5.4 + §5.8（技能扩绑 + 模板跨系统路径）；看 `tool_call` 是否覆盖 4 系统。

---

## 6. 附：手工调 API 复现

```bash
# 1) 登录拿 user token（对账子任务用 fin-accountant，应收子任务换 fin-receivable）
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agileac","username":"fin-accountant","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 FIN Agent 模板 id
TPL_ID=$(docker exec ai_infra_backend python3 -c "
import asyncio, asyncpg
async def m():
    c=await asyncpg.connect('postgresql://ai_infra:ai_infra@postgres:5432/ai_infra')
    r=await c.fetchrow(\"SELECT id FROM agents WHERE slug='agileac-fin-01-reconciliation-receivable'\")
    print(r['id']); await c.close()
asyncio.run(m())")

# 3) 创建任务（绑定模板；skill_ids 留空从模板继承，model=glm-5.2）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"FIN-01 四方对账\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（对账子任务短 composer，含 /agileac-fin-erp-crm-query chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"对敏睿空调 2026-06 期做四方对账：ERP 凭证 ↔ MES 工单成本 ↔ SCM 报价 ↔ PLM 成本台账，标出差异率 >2% 的异常。\\n\\n/agileac-fin-erp-crm-query\",\"stream\":true}"
```

应收子任务换 `fin-receivable` 登录 + §3.4 应收子任务提示词。短 composer 提示词文本见 §3.4（对账规则/SSO cue/输出格式由 FIN Agent 模板 `system_prompt` 承载，不在 composer 里）。

---

## 7. 验收要点（演示前自检）

- [ ] `fin-accountant` / `fin-receivable` 能登录 `/agileac/terminal/login`，左上角显示「财务部」
- [ ] `GET /api/v1/terminal/resources`（fin-accountant token）的 `skills` 含 `agileac-fin-erp-crm-query`（dept: finance）
- [ ] `data_interfaces` 含 ERP/MES/SCM/PLM/CRM 5 系统端点（**SSO 价值**：财务部跨 5 系统只读，非本部门系统也可见只读）——若缺 MES/SCM/PLM 见 §5.4 重跑 connectors
- [ ] `rag_collections` 不含任何部门级 RAG（FIN-01 无 RAG，对账规则由模板承载）
- [ ] `load_config` 事件显示 **`template:true`**（绑定了 template_agent_id）
- [ ] `trace category=template` 出现（slug=`agileac-fin-01-reconciliation-receivable` + chars）
- [ ] 对账子任务跑完，SSE 6 类 trace 出现（rag + memory.load + ontology + data_interface + skill + memory.extract）——FIN-01 虽无部门级 RAG，但 org 级员工综合库 auto-load 仍触发 `trace rag`（命中含"对账/凭证"关键词 chunk）
- [ ] 对账子任务 `tool_call` 跨 4 系统（ERP `listVouchers`/`listProductionCosts` + MES `listWorkOrders` + SCM `compareQuotations` + PLM `getCostLedger`），证明 SSO 免登跨系统
- [ ] `tool_call` args 不全 `{}`（至少 `getCostLedger(style_code=...)` 或 `listWorkOrders(won=...)` 这类必传参端点要带参）
- [ ] no-guessing：agent 用对凭证前缀 BV-AG-、应付/应收 AGAP/AGINV、工单 AWO、报价 AGQ、成本台账 AGCL；跨系统按 work_order_no / material_code 关联，不把凭证号当工单号直传
- [ ] 对账子任务输出含四方对账差异表 + 异常清单（差异率 >2% 标异常）+ SSO 演示凭证 BV-AG-2026-0512 双侧一致；应收子任务输出含催办清单 + 推送对象汇总
- [ ] 应收催办通过待办机制推送 sal-ops / fin-receivable（不直接调用其他部门 agent）
