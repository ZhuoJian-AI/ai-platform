# SC-1 来料批次物料校验与异常回写 · 终端任务演示

> 升级版：SC-1 不再走 shell 脚本 + 超管 curl 的方式，而是**通过「终端」以业务
> 用户身份创建任务**完成演示：登录 → 新建任务 → 配置模型（glm-5.2）→ 写提示词 →
> /-mention 选择技能 → 运行 → 观察 agent 调用 SCM + MES 数据接口、本体、记忆，
> 输出物料校验结果表 + 待处理项 + 闭环汇总。
>
> 旧 shell 脚本 `sc1_material_validation.sh` 保留以备对照（走超管 playground SSE）。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 星途服装（slug = `starclothing`） |
| 用户名 | `supply-lead` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）容器在跑。
2. **数据已 seed**：`seed_starclothing_apparel.py` / `seed_starclothing_mock_connectors.py` / `seed_starclothing_ontology.py` 至少跑过一次（详见根 `README.md` §2.2）。
3. **claude-sonnet-4 已可用**：Anthropic provider 的 `supported_models` 含 `claude-sonnet-4`。
   - 自检：`GET /api/v1/terminal/models`（用对应归口用户 token）应在 `models` 里看到 `claude-sonnet-4`。
4. **supply-lead 账号已存在且 active**：自检 `SELECT username, is_active FROM users WHERE username='supply-lead' AND organization_id=<starclothing org id>`。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/starclothing/terminal/login
```

- 用户名：`supply-lead`
- 密码：`12345678`

登录后落到 `/starclothing/terminal`（终端首页）。左上角应显示当前用户 `supply-lead` + 组织「星途服装」。

> 终端使用 **user-type JWT**（与超管 token 不同，scope 仅限本组织可见资源）。

### 3.2 新建任务

点击左栏「New Task / 新建任务」按钮，进入任务编辑器（HomeView composer）。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧的 ⚙️ 设置按钮，打开 TaskConfigDrawer，配置两项：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `supply-lead`（个人工作区）或「星途服装」 | 选个人工作区最干净；记忆仍按四级（组织+部门+团队+个人）自动载入 |
| Model | **`claude-sonnet-4`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | 让 agent 自主多轮调用 SCM + MES 工具；`ask` 是只读单轮、`plan` 只出方案不执行 |

> **本体 / RAG / 记忆不在 drawer 里配置**——这些是按用户 scope 自动注入的：
> - 9 个本体文件（供应链部 SCM 5 个含 README + 组织级 Cross 4 个）按部门级 scope 自动注入（MES 无本体文件）；
> - SC-1 无 RAG（`rag_collection_name=None`），不触发 RAG 检索；
> - 长期记忆按「组织+部门+团队+个人」四级全集自动载入。

> **场景模板（template_agent_id）**：SC-1 已改为四层架构——persona / 校验规则 /
> 输出骨架由 Agent 模板 `starclothing-sc1-material-validation` 的 `system_prompt`
> 承载，用户 composer 只写「目标 + 对象 + 技能 chip」（见 §3.4）。任务 config 必须
> 绑 `template_agent_id = <该 slug 的 UUID>`，运行时 `load_config` 才会把模板
> persona 拼到 system prompt 最前（`trace template` / `template:true` 出现），技能与
> 模型留空即从模板继承（`starclothing-scm-query` + `starclothing-mes-query` +
> claude-sonnet-4）。**前端 drawer 暂未暴露「场景模板」选择器**，用 §6 手工调
> API 在 `config` 里显式带 `template_agent_id` 绑定。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 composer 输入框（`MentionInput`，支持 `/` 触发技能、`@` 触发工作区文件）里输入：

> 敲 `/` 会弹出技能选择菜单，输入 `scm` 过滤，选中 **`starclothing-scm-query`**；
> 再敲 `/` 输入 `mes` 过滤，选中 **`starclothing-mes-query`**——两个技能 chip 都插入到提示词中。

完整提示词如下（直接复制，约 170 字符）：

```
本周面料/辅料到货批次做物料校验（BOM 一致性 / 数量 / 规格 / 供应商资质），工单 XWO20260788 等，异常项闭环回写 SCM。

/starclothing-scm-query
/starclothing-mes-query
```

> **v7d 起改为四层架构**（对齐 PD-2 `§3.4` / PD-3 `§5.17`）：user composer 只写
> **目标 + 对象 + 技能 chip**，persona / 流程角色 / 校验规则（缺数 >5% 退货、超数
> >3% 让步、规格克重门幅缩率色牢度、供应商资质有效期）/ 输出骨架（校验结果表 +
> 待处理项 + 闭环汇总三段）由 Agent 模板 `starclothing-sc1-material-validation`
> 的 `system_prompt` 承载（672 字符）。任务 config 必须绑定
> `template_agent_id = <starclothing-sc1-material-validation 的 UUID>`，运行时
> `load_config` 才会注入模板（trace `template` 出现、`template:true`）。技能与模型
> 留空即从模板继承（`starclothing-scm-query` + `starclothing-mes-query` +
> claude-sonnet-4）。runtime 的 `[输出协议]`+`[工具调用策略]` 兜底「先 text 后
> docx / 不要臆造 / 最少端点集」，本体 identifiers.md 兜底「标识符不猜」——故
> composer 不再写执行步骤、输出要求、输出格式。
>
> 若前端 drawer 暂未暴露「场景模板」选择器，可用 §6 手工调 API 在 `config` 里显式带
> `template_agent_id` 复现（`SELECT id FROM agents WHERE slug='starclothing-sc1-material-validation'`）。

> ⚠️ **关键 1**：`/starclothing-scm-query` 和 `/starclothing-mes-query` 这两段必须是真的从 `/` 菜单里选中的 chip，不是手敲文本。agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时 message 里写 `/starclothing-scm-query` 也会被同款正则解析（见 §6）。
>
> ⚠️ **关键 2**：composer 里的 `工单 XWO20260788` 是举例锚点，agent 据此结合本体
> 标识符规则自主取真实批次（`listMaterialValidations` / `listWorkOrders`）；若该工单号
> 在 mock 数据里不存在，agent 会降级到 list 端点取真实批次后闭环（与 PD-3 `getFabric` /
> SC-1 v7 同类「标识符推断偏差」，非占位符 bug，闭环仍完整）。详见 §5.7。

#### 资源注入机制（任务运行时自动完成，无需配置）

任务运行时，agent runtime 会按 supply-lead 的 scope 自动注入以下资源到 system prompt（**部门级 scope 拆分后**，supply-lead 看到供应链部范围内的资源）：

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | scope_filter 过滤后：供应链部 SCM 5 个（含 README）+ 组织级 Cross 4 个（MES 无本体文件） | 9 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出 supply-lead 可调用的接口 | 2 systems（SCM 16 + MES 13）/ 29 interfaces |
| **RAG** | 供应链部 scope 下无 RAG collection | 0 collection |
| **长期记忆** | 4 级（组织+部门+团队+个人）按权限聚合；load_memory 节点载入 | 4 history + 6 facts |
| **技能** | `template_agent_id` 继承 + /-mention chip 解析；config 留空 skill_ids 即从模板 `starclothing-sc1-material-validation` 继承 | 2 skills（供应链部级 starclothing-scm-query + starclothing-mes-query） |
| **记忆沉淀** | extract_memory 节点抽取本轮可沉淀事实写入个人级 Memory | 0~3 facts（详见 §5.8） |

> **跨部门数据访问**：supply-lead 只能调用供应链部 scope 下的 SCM + MES 数据接口。如需调用品控部 PLM（查缺陷规避要点）或开发部 PLM（查款号设计档案），需在供应链部下重新实现一份 PLM 数据接口（绑定同一 `tool_connector` starclothing-plm，按需开放端点子集）。SC-1 当前已覆盖 SCM + MES 两个核心系统，物料校验闭环所需数据完整。

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
| `[trace]` (template) | 场景模板 persona 注入（`template:true`——SC-1 模板 system_prompt 拼到 system prompt 最前，继承 skill_ids/model_alias） |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 部门级本体注入 system prompt |
| `[trace]` (data_interface) | 数据接口目录注入（按用户权限全量） |
| `[trace]` (skill) | /-mention 解析引用了哪个技能 |
| `[trace]` (memory/extract) | 记忆沉淀抽取（写个人级 Memory） |
| `[phase] llm #0/#1/#2/#3` | 每个 LLM 调用轮次 |
| `[tool_call]` | agent 调用工具（如 SCM `listMaterialValidations` / MES `listWorkOrders` / `generate_docx`） |
| `[tool_result]` | 工具返回（ok / FAIL） |
| `[text]` | LLM 流式输出 token（直接渲染到对话气泡） |
| `[done]` | agent_loop 收口（带 usage 统计） |
| `[final]` | 任务结束，附 latency_ms + session_id |

> 终端前端 ChatView 目前只渲染 `text` / `tool_call` / `tool_result`；`trace` 事件保存在 assistant 消息的 `metadata_.traces` 里，管理后台或 `GET /terminal/tasks/{id}/messages` 可见。

典型 SC-1 运行约 4–6 分钟（3–4 轮 LLM + 6–8 次 tool 调用 + glm-5.2 推理 + 记忆节点）。

---

## 4. 期望输出

agent 会输出三段 + 1 个附件：

### 4.1 校验结果表

7 列（物料编码 / 工单号 / BOM 一致性 / 数量差异 / 规格差异 / 供应商资质 / 校验结论），共 10 条物料校验记录（SCM `listMaterialValidations` 返回 10 行 MV-001 ~ MV-010）：

| 物料编码 | 工单号 | BOM 一致性 | 数量差异 | 规格差异 | 供应商资质 | 校验结论 |
|---|---|---|---|---|---|---|
| M-WOOL-DBL-360 | XWO20260607 | ✓ 一致 | 0% | 无 | 在期 | 通过 |
| M-ZIP-YKK-5 | XWO20260607 | ✓ 一致 | 0% | 无 | 在期 | 通过 |
| M-WOOL-DBL-360 | XWO20260789 | ✗ 不一致 | -8% | 无 | 在期 | 让步接收 |
| … | … | … | … | … | … | … |

> 校验结论判定规则（agent 会自洽定义）：缺数 >5% 退货；超数 >3% 让步接收并补差价；规格超标立即退货；资质过期立即退货。

### 4.2 待处理项（按异常类型分组）

4 个分组（缺数 / 超数 / 规格 / 资质失效），每条 = 物料 + 工单 + 异常类型 + 处理建议 + 责任人：

| 异常类型 | 物料编码 | 工单号 | 处理建议 | 责任人 |
|---|---|---|---|---|
| 缺数 | M-WOOL-DBL-360 | XWO20260789 | 退货 + 加急补货 | 面料采购员 |
| 超数 | M-ZIP-YKK-5 | XWO20260788 | 让步接收 + 补差价 5% | 辅料采购员 |
| 规格 | M-COTTON-SINGLE-180 | XWO20260801 | 退货 + 重新打样 | QC 检验员 |
| 资质失效 | M-WOOL-CASHMERE-280 | XWO20260810 | 立即退货 + 供应商整改 | 供应链部长 |

### 4.3 闭环汇总

```
本次校验总数：10 批
通过数：N 批
异常数：M 批（其中 缺数 X / 超数 Y / 规格 Z / 资质失效 W）
已回写数：K 批（createMaterialValidation 写回 SCM，闭环完成率 K/M）
```

### 4.4 .docx 报告附件

agent 会调 `generate_docx` 工具把上述分析打包成 `星途服装_物料AI校验报告_YYYYMMDD.docx`（约 30~40 KB），可下载分发。

### 4.5 SSE trace 事件（演示时截图可证）

任务运行期间，SSE 流除常规 `step` / `phase` / `text` / `tool_call` / `tool_result` / `final` 外，会发射 **5 个 `trace` 事件**（SC-1 无 RAG，比 PD-1/PD-3 少 1 个 rag trace）：

| trace | 含义 | 实测值 |
|---|---|---|
| `category=memory, subtype=load` | 长期记忆载入 | 4 history + 6 facts |
| `category=ontology` | 部门级本体注入 | 8 files（供应链部 SCM 4 + 组织级 Cross 4） |
| `category=data_interface` | 数据接口目录注入 | 2 systems / 29 interfaces（供应链部级 SCM + MES） |
| `category=skill` | /-mention 引用技能 | 2 skills（starclothing-scm-query + starclothing-mes-query） |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | 0~3 facts（详见 §5.8） |

### 4.6 实测延迟与 token 用量（v1/v2 稳定达标；v7 path-param 修复后回归）

| 指标 | v1（首次跑） | v2（稳定性确认） | **v7（path-param 修复后，prompt 去掉降级 workaround）** |
|---|---|---|---|
| latency_ms | 690922（≈11.5 分钟） | 497413（≈8.3 分钟） | 634228（≈10.6 分钟） |
| input_tokens | (后端日志 / final 未带 token 字段) | (同 v1，final 未带 token 字段) | 138132 |
| output_tokens | (同上) | (同上) | 23566 |
| tool_calls | 20 次（其中 13 次失败：6× getWorkOrder + 7× getSupplier，全部 path-param bug，agent 自主降级到 list 端点闭环） | 28 次（其中 13 次失败：6× getWorkOrder + 7× getSupplier，与 v1 一致；多出的 8 次是 `compareQuotations` 价格比对扩展调用） | 27 次（其中 6 次失败：6× getWorkOrder，**全部为 agent 猜测了不存在 / 错前缀的工单号，非占位符 bug**；getSupplier 7 次 **0 失败**） |
| text 事件字符数 | 9677 ✓ | 7278 ✓ | 7030 ✓ |
| 3 段分析是否上屏 | ✓（校验结果表 / 待处理项 / 闭环汇总 markers 各 1 次） | ✓（同 v1，3 markers 各 1 次） | ✓（3 markers 齐全） |
| 5 类 trace 是否全 | ✓（rag hits=5 / memory load facts=6 / ontology files=8 / data_interface systems=2 interfaces=29 / skill × 2 / memory extract facts=0） | ✓（同 v1） | ✓（同 v1） |
| listMaterialValidations 调用 | ✓（首调，返回 10 批待校验物料） | ✓（同 v1） | ✓ |
| `getSupplier` path 端点 | ✗ 7 次失败（`{code}` 占位符） | ✗ 7 次失败 | **✓ 7 次调用 0 失败** |
| memory/extract facts | 0（无新增事实，本轮信息全部来自工具返回） | 0（同 v1，无新增事实） | 0 |

> v1 + v2 在 prompt 含「先 text 流式输出 3 段分析，再生成 docx 附件」要求后
> （§3.4 输出要求段），连续 2 次跑都稳定达标。方差只在延迟和字符数上，
> 核心达标指标 0 失败。
>
> **v7（path-param 修复后回归，prompt 已去掉「path-param bug 降级」workaround）**：
> `executor.py` 占位符替换 + Craft 分支注入 `[工具调用策略]` 全局生效后回跑，
> `getSupplier` 7 次调用 **0 失败**（v1/v2 的 7 次 `{code}` 占位符失败全部
> 消失），直接返回真实供应商档案。`getWorkOrder` 16 次调用中 6 次失败，但
> 错误信息是 `work order WO20260607 not found`…`WO20260612 not found`
> ——**占位符 `{won}` 已替换为真实值**（不再是 `work order {won} not found`），
> 失败原因是 agent 猜测了 6 个 `WO2026xxxx` 形式的工单号（缺 `X` 前缀），
> mock MES 真实工单号为 `XWO2026xxxx` 前缀；agent 自主降级到 `listWorkOrders`
> 拿到真实工单号后，剩余 10 次 `getWorkOrder` 调用全部成功。属 agent 标识符
> 推断偏差，**非 path-param bug**。prompt 去掉降级 workaround 后闭环仍完整，
> 证明该 workaround 已无必要（§3.4 关键 2 已删）。详见 §5.7。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `claude-sonnet-4`
- Anthropic provider 未配或 `supported_models` 不含 `claude-sonnet-4`。
- 自检：`GET /api/v1/terminal/models` 的 `models` 应含 `claude-sonnet-4`。
- 修复：管理端「星途服装」组织 → LLM Provider 页配 Anthropic provider（`supported_models` 含 `claude-sonnet-4`）+ 路由策略 `model_pattern=claude-*` 指向它，重跑 `seed_starclothing_apparel.py`。

### 5.2 提示词里 `/starclothing-scm-query` / `/starclothing-mes-query` 没被识别
- 必须从 `/` 弹窗里选中 chip，不能手敲纯文本。
- 自检：保存的 task.message 里这两段应该是结构化 chip 标记，不是 plain text。

### 5.3 `[tool_result FAIL]` SCM / MES 接口调用失败
- mock 网关未起或 API key 不匹配。
- 自检：
  ```bash
  curl -s http://localhost:8010/scm/api/v1/material-validations -H "X-API-Key: scm-starclothing-demo-key" | head
  curl -s http://localhost:8010/mes/api/v1/work-orders -H "X-API-Key: mes-starclothing-demo-key" | head
  ```
  应返回 JSON。

### 5.4 agent 输出「我没有收到任务」
- 检查 `/run` 请求体里 `message` 是否为空——必须把完整提示词作为 `message` 发送，任务创建时存的 `message` 不会被 agent 读到。

### 5.5 运行很久没动 / latency > 6 分钟
- glm-5.2 单轮推理慢，多轮 tool 调用累计 4–5 分钟正常。超过 8 分钟大概率卡住，看后端日志 `docker logs ai_infra_backend --tail 100`。

### 5.6 输出大量走 `generate_docx`，前端 `text` 输出较短（与 PD-1 / PD-2 / PD-3 同款）
- 现象：SSE 的 `text` 事件累计仅 ~300~1500 字符，但 `.docx` 报告 ~30KB。ChatView 屏幕上看不到完整 3 段分析（校验结果表 / 待处理项 / 闭环汇总）。
- 根因：与 PD-1 v4 / PD-2 v5 / PD-3 v1 同款非确定性问题——agent 末轮跳过 text 流式分析，直接调 `generate_docx` 把全部内容打包成附件。glm-5.2 在不同轮次里随机选择"先 text 后 docx"或"直接 docx"路径，原 prompt 没有强约束。
- 修复：prompt §3.4 已加「先在 text 里流式输出完整分析，再生成 docx 附件」要求（输出要求段）。重跑后 text 应 ≥ 3000 字符，3 段分析全部出现在屏幕上。代价是延迟略增，可接受。
- 稳定性：连续 2 次跑都达标说明 prompt 约束生效；若第二次仍暴跌到 1000 以下，检查 prompt 是否真的有「## 输出要求」段。

### 5.7 `getWorkOrder` / `getSupplier` 路径参数未替换（v7 已修，仅余标识符推断偏差）
- 现象（修复前）：agent 调 `getWorkOrder(won="WO20260607")` 返回
  `{"detail":"work order {won} not found"}`；调 `getSupplier(code="XS-FAB-001")`
  返回 `{"detail":"supplier {code} not found"}`——`{won}` / `{code}` 占位符
  未被替换为实际值。
- 根因（修复前）：技能 wrapper 把 path 参数当作 query 参数透传，未替换到 OpenAPI path
  占位符（`/api/v1/work-orders/{won}`、`/api/v1/suppliers/{code}`）。SC-1 共
  2 个端点受影响（PD-1 有 3 个、PD-3 有 2 个）。
- 修复状态（v7 已根治）：随 `executor.py` `execute_endpoint` 占位符替换 +
  Craft 分支注入 `[工具调用策略]` 全局修复（见 `pd1_terminal_task.md` §5.10）。
  v7 回跑实测：`getSupplier` 7 次调用 **0 失败**（v1/v2 的 7 次 `{code}` 失败
  全部消失）；`getWorkOrder` 16 次调用 6 次失败，但占位符已替换为真实值
  （`work order WO20260607 not found`，非 `work order {won} not found`），
  失败原因是 agent 猜测了缺 `X` 前缀的工单号（mock MES 真实工单号为 `XWO2026xxxx`
  前缀），agent 降级到 `listWorkOrders` 拿到真实工单号后剩余 10 次 `getWorkOrder`
  全部成功。**属 agent 标识符推断偏差，非 path-param bug。**
- 历史影响（修复前）：**不阻塞 SC-1 闭环**。agent 自主降级：
  - `getWorkOrder` 404 → `listWorkOrders`（query 参数端点，不受 bug 影响）仍能拿到工单 BOM；
  - `getSupplier` 404 → `listSuppliers`（已先调过）档案已就位，直接复用。
  v1 跑 6× getWorkOrder + 7× getSupplier 共 13 次失败，演示时屏幕会看到
  红色 ✗ 标记，但 agent 自行降级后闭环仍完整（10 批物料校验全部出结论）。
- v7 起 prompt §3.4 步骤 2 的「path-param bug 降级」workaround 已删除——
  bug 根治后该降级指引不再必要，回跑证明去掉后闭环仍完整。详见 `KNOWN_ISSUES.md` #1。

### 5.8 memory/extract 抽取 0~3 facts
- 现象：`trace memory/extract` 多数情况下 `facts: 0`，偶尔抽到 1~3 facts。
- 根因：与 PD-1 / PD-2 / PD-3 同款老问题，extract_memory 节点对中文长文本 +
  多段结构化输出的抽取策略偏保守。
- 影响：非阻塞，本轮输出已完整；但长期记忆通道没真正发挥作用，跨任务复用
  能力弱。SC-1 同 PD-1~PD-3，记忆通道需要单独优化。
- 修复（可选）：调整 `extract_memory` 的 prompt，让其显式抽取结构化事实
  （物料编码 + 校验结论 + 责任人三元组），非本期 SC-1 演示范围。
  详见 `KNOWN_ISSUES.md` #2。

---

## 6. 附：手工调 API 复现

不用前端的话，可以用 curl 走一遍：

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"starclothing","username":"supply-lead","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 SC-1 Agent 模板 id（v7d 起任务 config 必须绑 template_agent_id；
#    skill_ids 留空从模板继承，model 留空继承 claude-sonnet-4）
TPL_ID=$(docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -tAc \
  "SELECT id FROM agents WHERE slug='starclothing-sc1-material-validation' AND deleted_at IS NULL AND organization_id='54f5f892-cf08-4a75-88b2-b649fea392a4'")
echo "template_agent_id=$TPL_ID"

# 3) 创建任务（绑模板；skill_ids 留空从模板继承，model_alias 留空继承 claude-sonnet-4）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"SC-1 来料批次物料校验与异常回写\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"claude-sonnet-4\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer 作为 message，见 §3.4；含两个技能 chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"本周面料/辅料到货批次做物料校验（BOM 一致性 / 数量 / 规格 / 供应商资质），工单 XWO20260788 等，异常项闭环回写 SCM。\\n\\n/starclothing-scm-query\\n/starclothing-mes-query\",\"stream\":true}"
```

短 composer 提示词文本见 §3.4（persona / 校验规则 / 输出格式由 SC-1 Agent 模板
`system_prompt` 承载，不在 composer 里）。
