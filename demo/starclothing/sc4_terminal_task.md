# SC-4 采购报价比对与成本台账建议 · 终端任务演示

> SC-4 不再走 shell 脚本 + 超管 curl 的方式，而是**通过「终端」以业务用户身份创建任务**
> 完成演示：登录 → 新建任务 → 配置模型（glm-5.2）→ 写提示词 → /-mention 选择技能 →
> 运行 → 观察 agent 调用 SCM + ERP 数据接口、本体、记忆，输出比价表 + 异动清单 +
> 成本台账建议 + 汇总四段。
>
> 旧 shell 脚本 `sc4_price_ledger.sh` 保留以备对照（走超管 playground SSE，已被终端任务方式取代）。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 星途服装（slug = `starclothing`） |
| 用户名 | `merch-lead` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）容器在跑。
2. **数据已 seed**：`seed_starclothing_apparel.py` / `seed_starclothing_mock_connectors.py` / `seed_starclothing_ontology.py` / `seed_starclothing_agents.py` 至少跑过一次（详见根 `README.md` §2.2）。
3. **claude-sonnet-4 已可用**：Anthropic provider 的 `supported_models` 含 `claude-sonnet-4`。
   - 自检：`GET /api/v1/terminal/models`（用对应归口用户 token）应在 `models` 里看到 `claude-sonnet-4`。
4. **merch-lead 账号已存在且 active**：自检 `SELECT username, is_active FROM users WHERE username='merch-lead' AND organization_id=<starclothing org id>`。
5. **SCM / ERP mock 端点正常**：
   ```bash
   curl -s "http://localhost:8010/scm/api/v1/quotations/compare?material_code=M-WOOL-DBL-360" -H "X-API-Key: scm-starclothing-demo-key" | head
   curl -s http://localhost:8010/erp/api/v1/materials -H "X-API-Key: erp-starclothing-demo-key" | head
   ```
   应返回 JSON 列表。

> ⚠️ SC-4 关键依赖 SCM 比价端点 + ERP 物料档案：SCM `compareQuotations` / `listQuotations`、
> ERP `listMaterials` / `listPurchaseOrders` / `listPayables`。任一不可用都会导致比价闭环断链。
> **ERP 无独立成本台账端点**（原 shell playbook + 老 agent prompt 误引的 `listCostLedger`
> 已在 v7e template 改写时删除——成本台账为输出建议，不调端点）。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/starclothing/terminal/login
```

- 用户名：`merch-lead`
- 密码：`12345678`

登录后落到 `/starclothing/terminal`（终端首页）。左上角应显示当前用户 `merch-lead` + 组织「星途服装」。

> 终端使用 **user-type JWT**（与超管 token 不同，scope 仅限本组织可见资源）。

### 3.2 新建任务

点击左栏「New Task / 新建任务」按钮，进入任务编辑器（HomeView composer）。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧的 ⚙️ 设置按钮，打开 TaskConfigDrawer，配置两项：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `merch-lead`（个人工作区）或「星途服装」 | 选个人工作区最干净；记忆仍按四级（组织+部门+团队+个人）自动载入 |
| Model | **`claude-sonnet-4`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | 让 agent 自主多轮调用 SCM + ERP 工具；`ask` 是只读单轮、`plan` 只出方案不执行 |

> **本体 / RAG / 记忆不在 drawer 里配置**——这些是按用户 scope 自动注入的：
> - **本体文件**按 scope 注入：商品部有 **SCM 本体**（`reorg_starclothing_scope.py` proxy 复制到商品部，含 identifiers 码空间映射）+ 组织级 Cross 4 个；**商品部无 ERP 领域本体**（ERP identifiers 未建——ERP 侧靠下方「数据接口目录」的参数 schema + 返回数据里的公共字段 `material_code` / `supplier_code` 交叉关联）。
> - SC-4 无 RAG（`rag_collection_name=None`），不触发 RAG 检索；
> - 长期记忆按「组织+部门+团队+个人」四级全集自动载入。

> **场景模板（template_agent_id）**：SC-4 已改为四层架构——persona / 比对输入 /
> 比对逻辑（5 条）/ 输出骨架由 Agent 模板 `starclothing-sc4-price-comparison`
> 的 `system_prompt` 承载，用户 composer 只写「目标 + 对象 + 技能 chip」（见 §3.4）。
> 任务 config 必须绑 `template_agent_id = <该 slug 的 UUID>`，运行时 `load_config`
> 才会把模板 persona 拼到 system prompt 最前（`trace template` / `template:true` 出现），
> 技能与模型留空即从模板继承（`starclothing-scm-query` + `starclothing-erp-query` +
> claude-sonnet-4）。**前端 drawer 暂未暴露「场景模板」选择器**，
> 用 §6 手工调 API 在 `config` 里显式带 `template_agent_id` 绑定。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 composer 输入框（`MentionInput`，支持 `/` 触发技能、`@` 触发工作区文件）里输入：

> 敲 `/` 会弹出技能选择菜单，输入 `scm` 过滤，选中 **`starclothing-scm-query`**；
> 再敲 `/` 输入 `erp` 过滤，选中 **`starclothing-erp-query`**——两个技能 chip 都插入到提示词中。

完整提示词如下（直接复制，约 120 字符）：

```
本季度面料/辅料采购报价比对：对 M-WOOL-DBL-360（双面呢）、M-SHELL-3L-150（三层压胶）、M-ZIP-YKK-5（YKK 拉链）做多供应商比价 + 历史异动 + 成本台账建议。

/starclothing-scm-query
/starclothing-erp-query
```

> **v7e 起改为四层架构**（对齐 PD-2 `§3.4` / SC-1 / SC-2 / SC-3 `§3.4`）：user composer 只写
> **目标 + 对象（3 款真实物料码）+ 技能 chip**，persona / 比对输入（SCM 报价+历史报价 /
> ERP 物料档案+采购订单+应付）/ 比对逻辑 5 条（多供应商比价 / 历史比价 / 标准成本比价 /
> 账期评估 / 成本台账建议）/ 输出骨架（比价表 + 异动清单 + 成本台账建议 + 汇总四段）
> 由 Agent 模板 `starclothing-sc4-price-comparison` 的 `system_prompt` 承载（917 字符）。
> 任务 config 必须绑定 `template_agent_id = <starclothing-sc4-price-comparison 的 UUID>`，
> 运行时 `load_config` 才会注入模板（trace `template` 出现、`template:true`）。技能与模型
> 留空即从模板继承（`starclothing-scm-query` + `starclothing-erp-query` +
> claude-sonnet-4）。runtime 的 `[输出协议]`+`[工具调用策略]`
> 兜底「先 text 后 docx / 不要臆造 / 最少端点集」——故 composer 不再写执行步骤、输出要求、输出格式。

> 若前端 drawer 暂未暴露「场景模板」选择器，可用 §6 手工调 API 在 `config` 里显式带
> `template_agent_id` 复现（`SELECT id FROM agents WHERE slug='starclothing-sc4-price-comparison'`）。

> ⚠️ **关键 1**：两个 `/starclothing-*-query` chip 必须从 `/` 菜单选中，不能手敲文本。agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时 message 里写 `/starclothing-scm-query` 等也会被同款正则解析（见 §6）。
>
> ⚠️ **关键 2**：模板 `system_prompt` 不硬编码端点名（如 `compareQuotations` /
> `listQuotations` / `listMaterials` / `listPurchaseOrders` / `listPayables`），由 agent 结合
> 数据接口目录自主发现。**原 shell playbook 误引的不存在端点 `listCostLedger` 已删除**——成本台账
> 为输出建议，标准成本取自 `listMaterials` 的 `unit_cost` 字段，实际采购单价取自 `listPurchaseOrders`，
> 供应商应付付款状态取自 `listPayables`，不再依赖独立的成本台账端点。
>
> ⚠️ **关键 3**：商品部有 SCM 本体（含 identifiers：物料码 `M-` / 供应商码 `XS-` 前缀 + 码空间映射），
> 但无 ERP 领域本体——ERP 侧比价靠数据接口目录的参数 schema + 返回数据里的公共字段
> （`material_code` 串 SCM 报价与 ERP 物料档案；`supplier_code` 串 SCM 报价与 ERP 应付）。
> agent 据公共字段自主关联，ERP 侧本体贡献弱于 SCM 侧（非阻塞）。

#### 资源注入机制（任务运行时自动完成，无需配置）

任务运行时，agent runtime 会按 merch-lead 的 scope 自动注入以下资源（**部门级 scope 拆分后**，merch-lead 看到商品部范围内的资源）：

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | scope_filter 过滤后：商品部 SCM（proxy 复制）+ 组织级 Cross 4 个（无 ERP 领域本体——agent 据数据接口目录 + 公共字段关联 ERP 侧） | 9 files（SCM 5 + Cross 4） |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出 merch-lead 可调用的接口 | 3 systems（CRM + SCM + ERP）/ 46 interfaces（商品部 dept scope 授权 CRM+SCM+ERP 三系统，agent 实际用 scm+erp 两个技能） |
| **RAG** | 商品部 scope 下无 RAG collection | 0 collection |
| **长期记忆** | 4 级（组织+部门+团队+个人）按权限聚合；load_memory 节点载入 | 4 history + N facts |
| **技能** | `template_agent_id` 继承 + /-mention chip 解析；config 留空 skill_ids 即从模板 `starclothing-sc4-price-comparison` 继承 | 2 skills（商品部级 starclothing-scm-query + starclothing-erp-query；dept scope 另可见 crm，但模板只绑 scm+erp） |
| **记忆沉淀** | extract_memory 节点抽取本轮可沉淀事实写入个人级 Memory | 0~N facts（详见 §5.7） |

> **跨部门数据访问**：merch-lead 调用的是商品部 scope 下 proxy 复制的 SCM/ERP 数据接口（绑定同一组织级 `tool_connector`，按商品部开放端点子集）。SC-4 覆盖 SCM + ERP 两个核心系统，报价比对 + 成本台账建议联动所需数据完整。

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
| `[trace]` (template) | 场景模板 persona 注入（`template:true`——SC-4 模板 system_prompt 拼到 system prompt 最前，继承 skill_ids/model_alias） |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 本体注入 system prompt（商品部 SCM 5 + 组织级 Cross 4，无 ERP 领域本体） |
| `[trace]` (data_interface) | 数据接口目录注入（按用户权限全量，3 systems / 46 interfaces——商品部授权 CRM+SCM+ERP） |
| `[trace]` (skill) | /-mention 解析引用了哪两个技能 |
| `[trace]` (memory/extract) | 记忆沉淀抽取（写个人级 Memory） |
| `[phase] llm #0/#1/#2/#3` | 每个 LLM 调用轮次 |
| `[tool_call]` | agent 调用工具（如 SCM `compareQuotations` / `listQuotations` / ERP `listMaterials` / `listPurchaseOrders` / `listPayables` / `generate_docx`） |
| `[tool_result]` | 工具返回（ok / FAIL） |
| `[text]` | LLM 流式输出 token（直接渲染到对话气泡） |
| `[done]` | agent_loop 收口（带 usage 统计） |
| `[final]` | 任务结束，附 latency_ms + session_id |

> 终端前端 ChatView 目前只渲染 `text` / `tool_call` / `tool_result`；`trace` 事件保存在 assistant 消息的 `metadata_.traces` 里，管理后台或 `GET /terminal/tasks/{id}/messages` 可见。

典型 SC-4 运行约 3–6 分钟（2 系统 3 款物料多供应商比价 + 历史异动 + 成本台账建议，tool_call 预计 15–20 次；v1 首跑实测 ~2.96 min / 18 tool_calls，见 §4.7）。

---

## 4. 期望输出

agent 会输出四段 + 1 个附件：

### 4.1 比价表

7 列（物料编码 / 规格 / 候选供应商 / 报价 / 评分明细 / 综合评分 / 排名），覆盖 3 款物料。mock 数据真实编码：物料 `M-WOOL-DBL-360` / `M-SHELL-3L-150` / `M-ZIP-YKK-5`，供应商 `XS-FAB-001~004` / `XS-ACC-010/011/020`，报价单 `Q2026xxxxx`：

| 物料编码 | 规格 | 候选供应商 | 报价 | 评分明细（价格/交期/账期） | 综合评分 | 排名 |
|---|---|---|---|---|---|---|
| M-WOOL-DBL-360 | 360g/㎡ 30%羊绒 70%羊毛 门幅150cm | XS-FAB-002 吴江恒宇 | 165.0 | 40 / x / x | xx.xx | 1 |
| M-WOOL-DBL-360 | 360g/㎡ 30%羊绒 70%羊毛 门幅150cm | XS-FAB-004 张家港华纺 | 172.0 | x / x / x | xx.xx | 2 |
| M-ZIP-YKK-5 | 5# 树脂 3:1 双开 | XS-ACC-011 福建浔兴 | 4.5 | x / x / x | xx.xx | 1 |
| M-SHELL-3L-150 | 150D 三层复合 防水透气膜 | XS-FAB-002 吴江恒宇 | 88.0 | x / x / x | xx.xx | 1 |

> 比价逻辑 agent 会自洽应用：(1) 多供应商比价按 `compareQuotations` 综合评分（价格 40% + 交期 30% + 账期 30%）排序；(2) 历史比价波动 >5% 标注；(3) 标准成本比价差异 >3% 标注；(4) 账期评估；(5) 成本台账建议。

### 4.2 异动清单

物料编码 + 历史报价 + 当前报价 + 波动率 + 备注：

| 物料编码 | 历史报价 | 当前报价 | 波动率 | 备注 |
|---|---|---|---|---|
| M-WOOL-DBL-360 | xx.x | 165.0 | ±x% | 价格上行 / 异动标注 |
| M-ZIP-YKK-5 | x.x | 4.5 | ±x% | 替代料价差 |

### 4.3 成本台账建议

款号 + 物料 + 推荐供应商 + 单价 + 操作（新建/更新/保留）：

| 款号 | 物料 | 推荐供应商 | 单价 | 操作 |
|---|---|---|---|---|
| P-FW2026-001 | M-WOOL-DBL-360 | XS-FAB-002 | 165.0 | 更新（标准成本 168 → 165） |
| P-FW2026-002 | M-SHELL-3L-150 | XS-FAB-002 | 88.0 | 更新（标准成本 92 → 88） |
| — | M-ZIP-YKK-5 | XS-ACC-011 | 4.5 | 保留（低于标准成本 6.8） |

> ERP 无独立成本台账端点——上表为 agent 据比价结果 + ERP `listMaterials.unit_cost` 生成的**台账建议**，落地需财务侧在凭证/应付侧人工确认录入。

### 4.4 汇总

本期比价物料数 / 异动数 / 台账待新建数 / 台账待更新数：

| 指标 | 值 |
|---|---|
| 本期比价物料数 | 3（M-WOOL-DBL-360 + M-SHELL-3L-150 + M-ZIP-YKK-5） |
| 异动数 | N |
| 台账待新建数 | N |
| 台账待更新数 | N |

### 4.5 .docx 报告附件

agent 会调 `generate_docx` 工具把上述分析打包成 `星途服装_本季度采购比价报告_YYYYMMDD.docx`（约 25~35 KB），可下载分发。

### 4.6 SSE trace 事件（演示时截图可证）

任务运行期间，SSE 流除常规 `step` / `phase` / `text` / `tool_call` / `tool_result` / `final` 外，会发射 **5 个 `trace` 事件**（SC-4 无 RAG，无 rag trace）：

| trace | 含义 | 实测值 |
|---|---|---|
| `category=memory, subtype=load` | 长期记忆载入 | 0 history + 4 facts |
| `category=ontology` | 本体注入 | 9 files（商品部 SCM 5 + Cross 4，无 ERP 领域本体） |
| `category=data_interface` | 数据接口目录注入 | 3 systems / 46 interfaces（商品部级 CRM + SCM + ERP） |
| `category=skill` | /-mention 引用技能 | 2 skills（scm + erp） |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | 0~N facts（详见 §5.7） |
| `category=template` | 场景模板 persona 注入 | `template:true`，chars=917 |

### 4.7 实测延迟与 token 用量（v1 首跑基线）

> v1 首跑基线（v7e，2026-07-13，glm-5.2 + balanced，merch-lead）：

| 指标 | 实测值 |
|---|---|
| latency_ms | 177769（~2.96 min） |
| input_tokens | 96248 |
| output_tokens | 8942 |
| tool_calls | 18（0 失败） |
| 4 段输出 | docx 内齐全（比价表/异动清单/成本台账建议/汇总），**text 流式 0 字符**（§5.6 已知问题——agent 末轮跳过 text 直接打包 docx） |
| docx 附件 | `星途服装_本季度面料辅料采购报价比对报告_Q3_2026.docx`（40108 bytes） |
| `listCostLedger` 引用 | 0 次（已根治） |
| 6 类 trace | 全（template chars=917 / memory-load 0 history+4 facts / ontology 9 files / data_interface 3 systems 46 interfaces / skill 2 / memory-extract） |

tool_call 明细：`compareQuotations` ×3（每物料一次）+ `listQuotations` ×3（历史比价）+ `getSupplier` ×7（账期/产能明细）+ ERP `getMaterial` ×3（unit_cost 标准成本）+ `listPurchaseOrders` ×1（实际采购单价）+ `generate_docx` ×1。无 `listCostLedger`、无 FAIL。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `claude-sonnet-4`
- Anthropic provider 未配或 `supported_models` 不含 `claude-sonnet-4`。
- 自检：`GET /api/v1/terminal/models` 的 `models` 应含 `claude-sonnet-4`。
- 修复：管理端「星途服装」组织 → LLM Provider 页配 Anthropic provider（`supported_models` 含 `claude-sonnet-4`）+ 路由策略 `model_pattern=claude-*` 指向它，重跑 `seed_starclothing_apparel.py`。

### 5.2 提示词里 `/starclothing-scm-query` / `/starclothing-erp-query` 没被识别
- 必须从 `/` 弹窗里选中 chip，不能手敲纯文本。
- 自检：保存的 task.message 里这两段应该是结构化 chip 标记，不是 plain text。

### 5.3 `[tool_result FAIL]` SCM / ERP 接口调用失败
- mock 网关未起或 API key 不匹配。
- 自检：
  ```bash
  curl -s "http://localhost:8010/scm/api/v1/quotations/compare?material_code=M-WOOL-DBL-360" -H "X-API-Key: scm-starclothing-demo-key" | head
  curl -s http://localhost:8010/erp/api/v1/materials -H "X-API-Key: erp-starclothing-demo-key" | head
  ```
  应返回 JSON。

### 5.4 agent 输出「我没有收到任务」
- 检查 `/run` 请求体里 `message` 是否为空——必须把完整提示词作为 `message` 发送，任务创建时存的 `message` 不会被 agent 读到。

### 5.5 运行很久没动 / latency > 6 分钟
- SC-4 跨 2 系统 3 款物料多供应商比价，tool_call 多、延迟 3–6 min 正常（v1 首跑实测 ~2.96 min / 18 tool_calls，见 §4.7）。超过 6 分钟大概率卡住，看后端日志 `docker logs ai_infra_backend --tail 100`。

### 5.6 输出大量走 `generate_docx`，前端 `text` 输出较短（与 PD-1~PD-3 / SC-1~SC-3 同款）
- 现象：SSE 的 `text` 事件累计较短，但 `.docx` 报告 ~40KB。ChatView 屏幕上看不到完整 4 段分析。
- 根因：与其它场景同款——agent 末轮跳过 text 流式分析，直接调 `generate_docx` 打包。runtime `[输出协议]` 已兜底「先 text 后 docx」，重跑通常达标；glm-5.2 非确定性导致偶发跳过。
- v1 首跑实测命中本问题：**text 流式 0 字符**，但 docx（40108 bytes）内 4 段全齐（比价表/异动清单/成本台账建议/汇总）——闭环完整，仅屏幕呈现缺流式 text。重跑通常 text ≥ 3000 字符上屏。
- 修复：runtime `[输出协议]`+`[工具调用策略]` 已注入；重跑后 text 应 ≥ 3000 字符，4 段分析全部出现在屏幕上。

### 5.7 memory/extract 抽取 0~3 facts
- 现象：`trace memory/extract` 多数情况下 `facts: 0`，偶尔抽到 1~3 facts。
- 根因：与其它场景同款老问题，extract_memory 节点对中文长文本 + 多段结构化输出的抽取策略偏保守（`KNOWN_ISSUES.md` #2 已修 v7d5，正常抽取）。
- 影响：非阻塞，本轮输出已完整。

### 5.8 agent 试图调 `listCostLedger` 失败
- 现象：agent 调 `listCostLedger` 返回 404 / 端点不存在。
- 根因：**mock ERP 无 `listCostLedger` 端点**（原 shell playbook + 老 agent prompt 误引，已在 v7e template 改写时删除）。
- 修复状态：**已修**（template `system_prompt` 比对逻辑 5 改为「成本台账建议」输出，标准成本取自 `listMaterials.unit_cost`，不再依赖独立成本台账端点）。若仍出现，说明跑的是旧 prompt——重新落库 SC-4 agent system_prompt（§6 步骤 2 解析的 TPL_ID 应对应 917 字 prompt）。

### 5.9 旧 shell 脚本 `sc4_price_ledger.sh` 还能用吗
- 能跑（走超管 root token + `/agents/{id}/playground` SSE），但**已被终端任务方式取代**，不再作为标准演示路径。新组织 demo 一律走 §3 终端任务方式（业务用户身份 + template）。shell 脚本保留仅作历史对照。

---

## 6. 附：手工调 API 复现

不用前端的话，可以用 curl 走一遍：

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"starclothing","username":"merch-lead","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 SC-4 Agent 模板 id（v7e 起任务 config 必须绑 template_agent_id；
#    skill_ids 留空从模板继承，model 留空继承 claude-sonnet-4）
TPL_ID=$(docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -tAc \
  "SELECT id FROM agents WHERE slug='starclothing-sc4-price-comparison' AND deleted_at IS NULL AND organization_id='54f5f892-cf08-4a75-88b2-b649fea392a4'")
echo "template_agent_id=$TPL_ID"

# 3) 创建任务（绑模板；skill_ids 留空从模板继承，model_alias 留空继承 claude-sonnet-4）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"SC-4 采购报价比对与成本台账建议\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"claude-sonnet-4\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer 作为 message，见 §3.4；含两个技能 chip + 3 款物料码）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"本季度面料/辅料采购报价比对：对 M-WOOL-DBL-360（双面呢）、M-SHELL-3L-150（三层压胶）、M-ZIP-YKK-5（YKK 拉链）做多供应商比价 + 历史异动 + 成本台账建议。\\n\\n/starclothing-scm-query\\n/starclothing-erp-query\",\"stream\":true}"
```

短 composer 提示词文本见 §3.4（persona / 比对输入 / 比对逻辑 / 输出格式由 SC-4 Agent 模板
`system_prompt` 承载，不在 composer 里）。
