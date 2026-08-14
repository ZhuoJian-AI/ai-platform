# PD-2 关键面料成本交期产能测算与异动检测 · 终端任务演示

> 与 PD-1 同样走**终端任务方式**：以业务用户 `fabric-dev` 登录终端，新建任务、配置
> 模型（glm-5.2）、写提示词、`/starclothing-scm-query` 选技能后运行，agent 自主
> 多轮调用 SCM 端点完成实时成本 / 交期 / 产能综合测算 + 异动检测。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 星途服装（slug = `starclothing`） |
| 用户名 | `fabric-dev` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）容器在跑。
2. **数据已 seed**：`seed_starclothing_apparel.py` / `seed_starclothing_mock_connectors.py` /
   `seed_starclothing_ontology.py` / `seed_starclothing_agents.py` 至少跑过一次（详见根
   `README.md` §2.2）。**PD-2 不依赖 RAG**，所以 `seed_starclothing_defect_rag.py`
   跑不跑都行。
3. **claude-opus-4 已可用**：Anthropic provider 的 `supported_models` 含 `claude-opus-4`。
   - 自检：`GET /api/v1/terminal/models`（用 fabric-dev token）应在 `models` 里看到 `claude-opus-4`。
4. **fabric-dev 账号已存在且 active**：自检 `SELECT username, is_active FROM users WHERE username='fabric-dev'`。
5. **SCM mock 端点正常**：
   ```bash
   curl -s http://localhost:8010/scm/quotations -H "X-API-Key: scm-starclothing-demo-key" | head
   ```
   应返回 JSON 列表。

> ⚠️ PD-2 关键依赖 SCM 的 4 个端点：`compareQuotations` / `estimateLeadtime`
> / `getLeadtimeDiff` / `listCapacityCalendar`。任一不可用都会导致闭环断链。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/starclothing/terminal/login
```

- 用户名：`fabric-dev`
- 密码：`12345678`

登录后落到 `/starclothing/terminal`。

### 3.2 新建任务

点左栏「New Task / 新建任务」进入 HomeView composer。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧 ⚙️ 打开 TaskConfigDrawer：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `fabric-dev`（个人工作区） | 干净；记忆仍按四级自动载入 |
| Model | **`claude-opus-4`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | agent 需多轮调 SCM 端点 + 异动检测；`ask` 只读单轮不够 |

> 本体 / 数据接口按 fabric-dev scope 自动注入：8 个本体文件（设计部 SCM proxy 4 个 + 组织级 Cross 4 个）+ 1 个数据系统
> 个数据接口（含 SCM 全集）按权限自动可见，无需在 drawer 里配。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 `MentionInput` 输入框敲 `/` 触发技能菜单，输入 `scm` 过滤，选中
**`starclothing-scm-query`** 即把技能 chip 插入提示词。

完整提示词如下（直接复制，约 140 字符）：

```
对当前在用的 4 款关键面料做实时成本/交期/产能综合测算 + 异动检测：
M-WOOL-DBL-360（双面呢 360g）、M-SHELL-3L-150（三层压胶）、M-TC-180（涤棉）、M-FLEECE-280（摇粒绒）。

/starclothing-scm-query
```

> **v7d 起改为四层架构**（详见 `pd3_terminal_task.md` §5.17）：user composer 只写
> **目标 + 对象 + 技能 chip**，执行步骤 / 异动规则 / 输出格式由 Agent 模板
> `starclothing-pd2-fabric-library` 的 `system_prompt` 承载（714 字符：persona +
> 实时性/异动 policy + 3 段输出骨架）。任务 config 必须绑定
> `template_agent_id = <starclothing-pd2-fabric-library 的 UUID>`，运行时
> `load_config` 才会注入模板（trace `template` 出现、`template:true`）。技能与模型
> 留空即从模板继承（`starclothing-scm-query` + claude-opus-4）。
>
> 若前端 drawer 暂未暴露「场景模板」选择器，可用 §6 手工调 API 在 `config` 里显式带
> `template_agent_id` 复现（`SELECT id FROM agents WHERE slug='starclothing-pd2-fabric-library'`）。

> ⚠️ **关键 1**：`/starclothing-scm-query` 必须从 `/` 菜单选中 chip，不能手敲文本。
> agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时
> message 里写 `/starclothing-scm-query` 也会被同款正则解析（见 §6）。
>
> ~~⚠️ **关键 2**（v7d 起删除）~~：原版要求提示词保留「`cached:false`，永不缓存」
> 字样，但 v7d 回跑发现 `estimateLeadtime` 端点**根本没有 `cached` 参数**（入参仅
> `material_code` + `qty`，端点本身绝不缓存，实时性是端点内建属性）——该指令基于
> 不存在的参数，属陈旧文档错误，已从 template/§3.4 删除。agent 不传 `cached` 即得
> 实时值。详见 §4.6 v7d。
>
> ⚠️ **关键 3**：`getLeadtimeDiff` 的 `since` 参数是 ISO 时间戳（取该时刻之后的
> 最新快照为基线）。提示词写「7 天前」是为了让 agent 算出 `now-7d` 的 ISO 字符串
> 入参，触发异动检测。如果不写 since，agent 可能跳过这个端点。**另注**：
> `getLeadtimeDiff` 必传 `supplier_code`（v7d 修了 schema 把它标必填——原 schema
> 误标可选致 agent 省略后命中 500）。

#### 资源注入机制（任务运行时自动完成，无需配置）

任务运行时，agent runtime 会按 fabric-dev 的 scope 自动注入以下资源（**部门级 scope 拆分后**，fabric-dev 只看得到设计部范围内的资源）：

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | scope_filter 过滤后：设计部 SCM proxy 4 个 + 组织级 Cross 4 个 | 8 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出 fabric-dev 可调用的接口 | 1 system（SCM）/ 16 interfaces |
| **RAG** | fabric-dev scope 下无可访问的 RAG collection（缺陷知识库已下放到品控部） | 0 collection；PD-2 不依赖 RAG |
| **长期记忆** | 4 级（组织+部门+团队+个人）按权限聚合 | 见 trace memory/load |
| **技能** | skill_ids 显式选 + /-mention 解析 | 1 skill（设计部级 starclothing-scm-query） |
| **记忆沉淀** | extract_memory 节点抽取本轮可沉淀事实写入个人级 Memory | 0~N facts |

> **跨部门数据访问**：fabric-dev 只能调用设计部 scope 下的 SCM 数据接口（数据来自组织级 `tool_connector` starclothing-scm，按设计部开放端点子集）。如需调用开发部 PLM 或品控部 PLM 数据，需在设计部下重新实现一份 PLM 数据接口（绑定同一 `tool_connector`）。

### 3.5 提交运行

按回车或点发送按钮提交。前端会：
1. `POST /api/v1/terminal/tasks` 创建任务（把 composer 内容作为 `message` 存档）；
2. `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}` —— **这才是真正发给 agent 的输入**。

> ⚠️ 实测：`/run` 的 `message` 才是 agent 看到的指令；任务创建时存的 `message`
> 不会被 agent 读到。前端做法是「同一段文本两次用」。手工调 API 记得 `/run` 也要带完整提示词。

### 3.6 观察 SSE 事件流

任务运行后，右侧 ChatView 渲染 SSE。事件类型与含义：

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载任务配置（model / skill_ids / workspace） |
| `[trace]` (rag) | RAG 检索——PD-2 query 与缺陷知识库语义不相关，hits 预期 0 或低 |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 部门级本体注入 system prompt |
| `[trace]` (data_interface) | 数据接口目录注入（按用户权限全量，含 SCM 17 端点） |
| `[trace]` (skill) | /-mention 解析引用了哪个技能 |
| `[trace]` (memory/extract) | 记忆沉淀抽取 |
| `[phase] llm #0/#1/#2` | 每个 LLM 调用轮次 |
| `[tool_call]` | agent 调用工具（SCM 端点 / generate_docx / workspace_list_files） |
| `[tool_result]` | 工具返回（ok / FAIL） |
| `[text]` | LLM 流式输出 token |
| `[done]` | agent_loop 收口（带 usage 统计） |
| `[final]` | 任务结束，附 latency_ms + session_id |

> 终端前端 ChatView 目前只渲染 `text` / `tool_call` / `tool_result`；`trace`
> 事件保存在 assistant 消息的 `metadata_.traces` 里，管理后台或
> `GET /terminal/tasks/{id}/messages` 可见。

典型 PD-2 运行约 4–6 分钟（5–6 轮 LLM + 18–22 次 tool 调用 + glm-5.2 推理，含 4 款面料 × 6 端点的并发并行调用）。

---

## 4. 期望输出

agent 会输出两段 + 1 个附件：

### 4.1 面料对比汇总表

10 列（不含序号），共 4 款面料 × N 候选供应商：

| 面料编码 | 规格 | 主供应商 | 报价(元/m) | 评分(price/leadtime/payment) | 实时交期(天) | 交期异动(Δ天) | 产能占用率 | 在途状态 | 推荐结论 |
|---|---|---|---|---|---|---|---|---|---|
| M-WOOL-DBL-360 | 360g/㎡ 30%羊绒 70%羊毛 门幅150cm | 吴江恒宇 (XS-FAB-002) | 165.0 | 40/30/15 | 22 | **+5 天** ⚠️ | 28%-45% | 延误4天 | 启用备选 |
| M-SHELL-3L-150 | 150D 三层复合 透气膜 148cm | 吴江恒宇 (XS-FAB-002) | 88.0 | 40/30/15 | 18 | **+4 天** ⚠️ | 28%-45% | 延误3天 | 启用备选 |
| M-TC-180 | 65/35 180g 平纹 160cm | 吴江恒宇 (XS-FAB-002) | 18.0 | 40/30/15 | 10 | **+2 天** ⚠️ | 28%-45% | 已到货 | 关注 |
| M-FLEECE-280 | 280g 抓绒 门幅150cm | 吴江恒宇 (XS-FAB-002) | 33.0 | 40/30/15 | 16 | **+4 天** ⚠️ | 28%-45% | 在途 | 启用备选 |

> 评分明细：`price_score` 越低价格越高（满 40）；`leadtime_score` 越短交期越高（满 30）；
> `payment_score` 越长账期越高（满 30，采购方资金占用少 = 高分）。
> 实测：M-WOOL-DBL-360 有 4 家报价、M-SHELL-3L-150 有 2 家、M-TC-180 有 2 家、
> M-FLEECE-280 有 2 家，共 10 条对比行。

### 4.2 选用建议清单

每款面料一条建议：

```
M-WOOL-DBL-360 双面呢 360g/㎡
  首选供应商：桐乡羊毛纺织（XS-FAB-003）—— 报价 165 元/m，评分 92/100
  备选供应商：绍兴盛峰纺织（XS-FAB-001）—— 报价 178 元/m，评分 88/100，交期稳
  推荐规格：360g/㎡ 30%羊绒 70%羊毛 门幅150cm
  预估成本：800m × 165 = 132,000 元
  预计到货日：T+22（含异动调整）
  ⚠️ 风险：桐乡产能占用 85%（接近满产），建议 F-XT-DG 工厂排产与绍兴双供
```

### 4.3 异动预警

对 `Δ > 0` 的面料单独标注：

```
⚠️ 异动预警 · M-WOOL-DBL-360
  当前交期：18 天（基线 15 天，Δ=+3）
  根因：桐乡羊毛纺织近 7 天产能占用从 70% 升至 85%
  替代供应商：
    1. 绍兴盛峰纺织（XS-FAB-001）—— 报价 178，交期 25 天，产能 70%
    2. 吴江恒宇面料（XS-FAB-002）—— 报价 195，交期 30 天，产能 60%
  补货建议：通过 listReplenishmentSuggestions 返回：
    - 紧急补货 500m（桐乡延期到货 4 天）
    - 备选 800m 转绍兴（PO 已建，待确认）
```

### 4.4 .docx 报告附件

agent 调 `generate_docx` 工具把上述分析打包成 `面料综合测算与异动预警报告_YYYYMMDD.docx`（约 40 KB），可下载分发。

### 4.5 SSE trace 事件（演示时截图可证）

| trace | 含义 | 实测值 |
|---|---|---|
| `category=rag` | RAG 检索 | 0 collection（fabric-dev 设计部 scope 下无 RAG，部门级拆分后已下放到品控部） |
| `category=memory, subtype=load` | 长期记忆载入 | 0 history + 6 facts |
| `category=ontology` | 部门级本体注入 | 8 files（设计部 SCM proxy 4 + 组织级 Cross 4） |
| `category=data_interface` | 数据接口目录注入 | 1 system / 16 interfaces（设计部级 SCM） |
| `category=skill` | /-mention 引用技能 | 1 skill（设计部级 starclothing-scm-query） |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | v7d5 起正常抽取（PD-2 v7d5 实测 **8 facts**，详见 §5.13） |

> PD-2 不依赖 RAG。部门级 scope 拆分后，缺陷知识库已下放到品控部，设计部 fabric-dev 无 RAG 访问权限——这是预期行为，不再发射 `trace rag` 事件。

### 4.6 实测延迟与 token 用量（v6 修复版，稳定达标）

| 指标 | v4（原 prompt，运气好） | v5（原 prompt，运气差） | **v6（修复后 prompt，稳定达标）** |
|---|---|---|---|
| latency_ms | 274874（~4.6 min） | 366773（~6.1 min） | 405698（~6.8 min） |
| input_tokens | — | — | 124924 |
| output_tokens | — | — | 15130 |
| tool_calls | 23（0 失败） | 26（0 失败） | 23（0 失败） |
| text 事件字符数 | 6378 ✓ | 1572 ⚠ | **7923 ✓** |
| 4 段结构上屏 | ✓ | ✗ | ✓ |
| 6 类 trace 是否全 | ✓ | ✓ | ✓ |
| 4 款面料 + 关键端点全调 | ✓ | ✓ | ✓ |

> v6 在 prompt 加了「先 text 流式输出 4 段分析，再生成 docx 附件」要求后
> （§3.4 输出要求段），text 流式输出从 1572 → 7923 字符（5×），4 段分析
> （面料对比 / 选用建议 / 异动预警）全部出现在 ChatView 屏幕上。代价是延迟
> +60~120s，可接受。
>
> PD-2 与 PD-3 共享同款"agent 偶尔跳过 text 直接生成 docx"非确定性现象，
> 通过在 prompt 里显式要求"先 text 后 docx"两场景都修复稳定。

> **v7d（template 层 + 真用户提示词 + SCM 本体 identifiers，验证态）**：按 PD-3
> 四层架构（详见 `pd3_terminal_task.md` §5.17）对 PD-2 落地——建 SCM 域本体
> `SCM/identifiers.md`（`SCM_IDENTIFIER_CONVENTIONS` + `SCM_CODE_SPACE_MAPPINGS`，
> 含 `Supplier` `XS-`、`MaterialValidation.work_order_no` WO→MES won XWO 不直接匹配
> 等规则），`starclothing-pd2-fabric-library` Agent system_prompt 重写为精简模板
> （persona + 实时性/异动 policy + 3 段输出骨架，714 字符，删了老胖 playbook 的
> 检索策略 5 步）。用户 composer 收缩到 **~140 字符**：只留「对当前在用 4 款关键
> 面料做实时成本/交期/产能综合测算+异动检测」+ 面料列表 + 技能 chip。回跑（v7d2）：
> tool_calls 27、3 段全上屏（面料对比/选用建议/异动预警）、异动 policy 生效
> （text 含 Δ/替代供应商/实时交期）、template trace 加载。**顺带暴露并修了两个
> 数据/schema 坑**：(1) `getLeadtimeDiff.params_schema` 把 `supplier_code` 标成可选
> （`required:[]`）但 mock 路由实际必填→agent 遵 schema 省略 supplier_code 命中 500；
> 已修 schema 标 `supplier_code` 必填 + 补描述，v7d2 失败从 4×500 降为 2×「no
> snapshot for material+supplier」（合法数据缺失，非 bug）。(2) §3.4「关键2 必须
> 保留 cached:false」是基于**不存在的参数**的陈旧指令——`estimateLeadtime` 根本
> 无 `cached` 参数（端点本身绝不缓存，入参仅 material_code+qty），agent 正确地没传，
> 已从 template/doc 删除该指令。详见 §5.x。
>
> **v7d3（补快照根治 2× no snapshot 失败）**：v7d2 残留的 2×「no snapshot for
> material+supplier」根因是 mock `leadtime_snapshots` 对两个候选 `(material, supplier)`
> 组合缺快照——`M-WOOL-DBL-360 / XS-FAB-004`（4 家比价之一）与
> `M-TC-180 / XS-FAB-001`（2 家比价之一）有报价但无交期快照，agent 做异动检测/替代
> 供应商探查时调 `getLeadtimeDiff` 命中 404。已在 `mock/mock/systems/scm/data.py`
> 补 LS-019/020（M-WOOL-DBL-360/XS-FAB-004：26→30，Δ+4）与 LS-021/022
> （M-TC-180/XS-FAB-001：12→14，Δ+2），两个组合现返回结构化 delta 对比而非 404。
> 4 款面料的全部候选供应商均有快照覆盖，`getLeadtimeDiff` 0 失败。详见 §5.10。
>
> **v7d3 实测回归（短 composer + 模板，task b4d34580）**：config 绑定
> `template_agent_id=starclothing-pd2-fabric-library`，user message 仅 140 字符短 composer
> （目标+4 款面料+`/starclothing-scm-query` chip）。`load_config` 显示 **`template:true`**、
> 注入模板 714 字符。**26 tool_call / 26 tool_result，0 失败**（无 404 / no snapshot / 5xx）。
> `getLeadtimeDiff` 调 **8 次跨 7 个 material×supplier 组合**（M-WOOL 的 002/001/003、
> M-SHELL 的 002/001、M-TC-180 的 002、M-FLEECE 的 001/002），全部返回结构化 delta
> （+5/+7/+15/+4/0/+2/0/+4，含 2 个 Δ=0 持平），**零 404**；`generate_docx` 出
> `星途服装_关键面料实时成本交期产能综合测算与异动检测报告_*.docx`；text 2951 事件
> （3 段全上屏）；latency 364881ms（~6.1 min）；input/output 101184/13451 tokens。
> **fix 硬证明在数据层**：curl 直打 v7d2 的 2 个 404 组合 `M-WOOL-DBL-360/XS-FAB-004`
> （Δ=+4）与 `M-TC-180/XS-FAB-001`（Δ=+2）确定性返回 delta；agent run 跨 7 组合 0 失败
> 证无回归。（两跑 agent 非确定性地未恰好选中 XS-FAB-004 做 diff，但数据层已堵死 404。）

---

## 5. 故障排查

### 5.1 模型选择器里没有 `claude-opus-4`
- Anthropic provider 未配或 `supported_models` 不含 `claude-opus-4`。
- 自检：`GET /api/v1/terminal/models` 的 `models` 应含 `claude-opus-4`。
- 修复：`docker cp` + `docker exec ai_infra_backend python /app/scripts/seed_starclothing_apparel.py`。

### 5.2 提示词里 `/starclothing-scm-query` 没被识别
- 必须从 `/` 弹窗里选中 chip，不能手敲纯文本。
- 自检：保存的 task.message 里这段应该是结构化 chip 标记。

### 5.3 `[tool_result FAIL]` SCM 接口调用失败
- mock 网关未起或 API key 不匹配。
- 自检：`curl -s http://localhost:8010/scm/quotations -H "X-API-Key: scm-starclothing-demo-key" | head` 应返回 JSON。
- 检查 `seed_starclothing_mock_connectors.py` 是否跑过最新版（含 SCM 连接器）。

### 5.4 agent 没调 `estimateLeadtime`（只用了 `listLeadtimeSnapshots`）
- 提示词里漏写了「`cached:false`，永不缓存」字样。
- `estimateLeadtime` 是 PD-2 的实时演示点，必须显式调；如果只调快照列表，
  实时性卖点就丢了。
- 修复：在提示词执行步骤 2 加上「调用 `estimateLeadtime`（cached:false）」。

### 5.5 agent 没调 `getLeadtimeDiff`
- 提示词里没写 `since` 参数的取值约定，agent 不知道怎么传。
- 修复：提示词里明确写「`since` 取 7 天前 ISO 时间戳（如 `2026-06-22T00:00:00Z`）」。

### 5.6 agent 输出「我没有收到任务」
- 检查 `/run` 请求体里 `message` 是否为空——必须把完整提示词作为 `message` 发送。

### 5.7 运行很久没动 / latency > 5 分钟
- glm-5.2 单轮推理慢，多轮 tool 调用累计 3–4 分钟正常。超过 8 分钟大概率卡住，
  看后端日志 `docker logs ai_infra_backend --tail 100`。

### 5.8 trace 事件没在 SSE 里显示
- 终端前端目前只渲染 `text` / `tool_call` / `tool_result`，`trace` 事件落在
  `TaskMessage.metadata_.traces` 里。
- 查看方式：管理后台 → 终端任务详情页 → 消息 traces 标签；或
  `GET /api/v1/terminal/tasks/{id}/messages` 看元数据。

### 5.9 trace `rag` 显示 `retriever=keyword_fallback` 或 hits=0
- PD-2 query 与缺陷知识库语义不相关，hits 内容作 system prompt 上下文但与 PD-2
  闭环解耦，hits 高低都不影响演示。
- 若 `retriever=keyword_fallback`，说明向量通道未配好（embedding provider 缺失
  或 `_EMBED_BATCH` 问题），参考 PD-1 §5.6 修复路径。
- PD-2 不依赖 RAG，此项不影响演示闭环。

### 5.10 `getLeadtimeDiff` 返回空对象 / 无快照对比
- 现象：`getLeadtimeDiff` 返回 `{}` 或不含 `delta_days` 字段，或 404「no snapshot for
  material+supplier」。
- 根因：mock 的 `leadtime_snapshots` 表对当前 supplier+material 组合没有快照记录
  （`since` 时间戳之后无快照，或该组合压根无快照）。
- 影响：agent 会自动 fallback 到 `estimateLeadtime`（cached:false）实时总交期 vs
  报价交期算 Δ，结果同样可信——`estimateLeadtime` 本身就是 PD-2 实时性演示点。
- **修复状态（已修，v7d3）**：v7d2 残留的 2× 404「no snapshot for material+supplier」
  根因是两个候选组合缺快照——`M-WOOL-DBL-360 / XS-FAB-004`（4 家比价之一）与
  `M-TC-180 / XS-FAB-001`（2 家比价之一）有报价但无交期快照。已在
  `mock/mock/systems/scm/data.py` 补 LS-019/020（26→30，Δ+4）与 LS-021/022
  （12→14，Δ+2）。两个组合现返回结构化 delta 对比而非 404。4 款面料的全部候选
  供应商均有快照覆盖，`getLeadtimeDiff` 0 失败。改完需 `docker cp` 进 `ai_infra_mock`
  容器再 `docker restart`（mock 容器无 volume mount，见 KNOWN_ISSUES Issue #7）。

### 5.11 工具调用全部 `args={}`（agent 不传参）
- 现象：所有 `tool_call` 的 `arguments` 是 `{}`，`compareQuotations` /
  `estimateLeadtime` / `getLeadtimeDiff` 全部 FAIL 500。
- 根因：`_build_tools`（`app/agents/graph/nodes.py`）原代码用
  `manifest.parameters or ep.params_schema`，但 seed 脚本生成的
  `manifest.parameters = {"type":"object","properties":{}}` 是占位空 schema（非 None），
  truthy 判定让它覆盖了 `ep.params_schema`，LLM 看不到参数 schema 就不传参。
- 修复：已 fix（改为检测 `manifest.parameters.properties` 是否真有字段，否则用
  `ep.params_schema`）。若重现，检查 `nodes.py` `_build_tools` 的 params 选择逻辑。

### 5.12 输出大量走 `generate_docx`，前端 `text` 输出较短（与 PD-3 同款）
- 现象：SSE 的 `text` 事件累计仅 ~1500 字符（v5 实测），但 `.docx` 报告 ~40KB。
  ChatView 屏幕上只看到"我将按步骤..."、"全部 4 款面料的交期异动 Δ..."这种
  过渡性语句，完整 3 段分析（对比表 / 选用建议 / 异动预警）没有上屏。
- 根因：与 PD-3 v1 同款非确定性问题——agent 末轮跳过 text 流式分析，直接调
  `generate_docx` 把全部内容打包成附件。glm-5.2 在不同轮次里随机选择"先 text
  后 docx"或"直接 docx"路径，原 prompt 没有强约束。
- 实测（v5 不达标）：text 1572 字符，4 段结构未上屏。
- 修复：prompt §3.4 已加「先在 text 里流式输出完整分析，再生成 docx 附件」
  要求（输出要求段）。v6 重跑后 text 1572 → 7923 字符（5×），3 段分析全部
  出现在屏幕上，演示体验达标。代价是延迟 +60~120s，可接受。
- 稳定性：v4（6378）+ v6（7923）连续 2 次跑都达标，方差只在延迟和字符数上，
  核心达标指标 0 失败。

### 5.13 memory/extract 抽取 0 facts（已修，v7d5）
- 现象（修复前）：`trace memory/extract` 显示 `facts: 0`——本轮面料对比 / 异动预警
  本是可沉淀事实，但 extract 节点未抽取。后端日志连发
  `extract_memory_failed error='Expecting value: line 1 column 1 (char 0)'`。
- 根因（两层，第二层才是真因）：
  1. **prompt 偏保守**——原 prompt「不要抽取一次性任务细节、不要抽取临时数据」
     把面料→首选供应商、面料→异动 Δ 这类结论性事实也当任务细节跳过。
  2. **（真因）JSON 解析失败**——glm-5.2 非流式返回常把 JSON 包在
     ``` ```json ``` ``` markdown 围栏里（assistant_final 大输入时尤甚），
     `json.loads("```json\n{...}")` 首字符是反引号 → 抛 `char 0` 被吞 → facts 静默归零。
- 修复（已实施，`nodes.py`）：
  - `extract_memory` prompt 改为显式「实体 → 属性 → 值」三元组抽取，区分可复用结论
    vs 过程性数据，给具体示例，限 8 条宁缺毋滥。
  - 新增 `_parse_json_lenient`：先剥 ``` ```json ``` ``` 围栏，再 fallback 取 `{...}` 子串，
    全失败返回 `{}`（不抛、不静默归零）。
- 验证（PD-2 v7d5，task 2d8e4f23）：`trace memory/extract` **facts: 0 → 8** ✓；
  后端 `extract_memory_failed` 本轮 **0 条** ✓；个人记忆行 `updated_at` 刷新，含 8 条
  结构化三元组（如「M-FLEECE-280 → 首选供应商 → XS-FAB-001（36元/m，Δ=0）」
  「XS-FAB-003 → 产能状态 → 91%满载+异动+15天」）✓。`add_user_memory` 是 upsert 进
  单行 profile 记忆（不产生多行），8 条合并写入。
- 影响范围：此修复在 `extract_memory` 节点（general 模式共用），PD-1 / PD-3 / SC-1
  同款 glm-5.2 + 同款 fence 解析坑一并受益，跨任务记忆复用正式生效。
  详见 KNOWN_ISSUES Issue #2。

---

## 6. 附：手工调 API 复现

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"starclothing","username":"fabric-dev","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 SCM 技能 id（若用模板继承技能则可省略）
SKILL_ID=$(curl -sS http://localhost:8000/api/v1/terminal/resources \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; r=json.load(sys.stdin); print(next(s['id'] for s in r['skills'] if s['slug']=='starclothing-scm-query'))")

# 2.5) 解析 PD-2 Agent 模板 id（v7d 起任务 config 必须绑定 template_agent_id）
TPL_ID=$(docker exec ai_infra_backend python3 -c "
import asyncio, asyncpg
async def m():
    c=await asyncpg.connect('postgresql://ai_infra:ai_infra@postgres:5432/ai_infra')
    r=await c.fetchrow(\"SELECT id FROM agents WHERE slug='starclothing-pd2-fabric-library'\")
    print(r['id']); await c.close()
asyncio.run(m())")

# 3) 创建任务（绑定模板；skill_ids 留空从模板继承，model=glm=glm-5.2）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"PD-2 关键面料成本交期产能测算与异动检测\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"claude-opus-4\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer 作为 message，见 §3.4；含 /starclothing-scm-query chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"对当前在用的 4 款关键面料做实时成本/交期/产能综合测算 + 异动检测：\\nM-WOOL-DBL-360（双面呢 360g）、M-SHELL-3L-150（三层压胶）、M-TC-180（涤棉）、M-FLEECE-280（摇粒绒）。\\n\\n/starclothing-scm-query\",\"stream\":true}"
```

短 composer 提示词文本见 §3.4（执行步骤/异动规则/输出格式由 PD-2 Agent 模板 `system_prompt` 承载，不在 composer 里）。
