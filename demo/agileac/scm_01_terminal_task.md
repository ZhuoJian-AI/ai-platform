# SCM-01 供应商评审与采购物流一体化 · 终端任务演示

> 供应链部采购员 `scm-buyer`（采购子任务）/ 物流员 `scm-logistics`（物流子任务）登录终端，新建任务、配置 `glm-5.2` + `craft`、`/agileac-scm-scm-erp-query` 选技能、写提示词、运行，agent 自主多轮调 SCM 报价/到货 + ERP 库存/应付 + 供应商资质与历史表现库 RAG，输出供应商评分 + 推荐份额（采购子任务）或到货监管 + 仓储报表 + 缺料预警（物流子任务）。
>
> **员工 vibe working 视角**：采购员原本要逐家拉报价、查资质、算评分、对账应付；物流员原本要逐单盯到货、盘库存、预警缺料——现在一句话拿到评审清单与缺料预警。AI 是供应链员工的副驾驶，**不对供应商/客户直接交互**。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 敏睿空调（slug = `agileac`） |
| 用户名 | `scm-buyer`（采购子任务）/ `scm-logistics`（物流子任务） |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |
| 部门 | 供应链部 · 采购组 `supply-procurement` / 物流组 `supply-logistics` |

> 两子任务同属供应链部，技能与 RAG 同源（部门级 `agileac-scm-scm-erp-query` + 供应商资质与历史表现库 dept: supply），可同一场景演示；按子任务切归口员工验证组级 scope 隔离。

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）+ `ai_infra_postgres` 容器在跑。
2. **数据已 seed**（按 `README.md` §9 顺序执行）：
   - `seed_agileac_org.py`（含 `scm-buyer` / `scm-logistics` 用户 + 供应链部 + 采购组/物流组）
   - mock 6 系统 agileac tenant 数据已内置（`mock/mock/systems/*/data.py` 的 `_build_agileac`），含供应商 S-COMP-001/002、换热器 S-HEX-001、阀件 S-VALVE-001、制冷剂 S-REF-001；报价 AGQ202607001~040；到货计划 AGFAP-001~010（含 AGFAP-002 延误样本）；mock 容器重启即生效，无需独立 seed 脚本
   - `seed_agileac_mock_connectors.py`（含部门级技能 `agileac-scm-scm-erp-query`，绑 SCM 全集 + ERP 采购/库存/应付只读端点）
   - `seed_agileac_ontology.py`（33 组织级含 SCM 域 `identifiers.md`——供应商前缀 S-、报价 AGQ、到货计划 AGFAP、物料 M- + 供应链部无专属本体，复用组织级 = 34 个本体文件对该用户可见——org scope 资源对所有部门用户可见）
   - `seed_agileac_rag.py`（含「供应商资质与历史表现库」**部门级** RAG，scope=`supply`，含 10 家核心供应商档案 + 5 维度评审规则 + 黑名单触发条件）
   - `seed_agileac_agents.py`（含 `agileac-scm-01-procurement-logistics` agent 模板配置，四层架构 system_prompt）
3. **glm-5.2 已可用**：组织已配智谱 AI provider，`supported_models` 含 `glm-5.2`。
   - 自检：`GET /api/v1/terminal/models`（用 scm-buyer token）应在 `models` 里看到 `glm-5.2`。
4. **scm-buyer / scm-logistics 账号已存在且 active**：
   ```bash
   docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
     "SELECT username, is_active FROM users WHERE username IN ('scm-buyer','scm-logistics');"
   ```
5. **SCM/ERP mock 端点正常**：
   ```bash
   curl -s "http://localhost:8010/scm/suppliers" -H "X-API-Key: scm-agileac-demo-key" | head
   curl -s "http://localhost:8010/scm/quotations/compare?material_code=M-COMP-GT-24K" -H "X-API-Key: scm-agileac-demo-key" | head
   curl -s "http://localhost:8010/scm/fabric-arrival-plans" -H "X-API-Key: scm-agileac-demo-key" | head
   curl -s "http://localhost:8010/erp/inventory" -H "X-API-Key: erp-agileac-demo-key" | head
   ```
   应返回 JSON 列表，含 S-COMP-001/002、AGFAP-002（延误）等样本。
6. **供应商资质与历史表现库向量通道正常**：
   ```bash
   docker exec ai_infra_backend python -c "
   from app.rag.service import RAGService
   s = RAGService()
   c = s.get_collection_by_name('供应商资质与历史表现库')
   print('chunks:', c.chunk_count, 'embedded:', c.embedded_count)
   "
   ```
   应输出 `embedded == chunks`。若 `embedded < chunks`，跑 `reembed_agileac_rag.py --collection-name "供应商资质与历史表现库"` 回填。

> ⚠️ SCM-01 关键依赖 4 件事：SCM `compareQuotations`/`listQuotations`/`listSuppliers`/`listFabricArrivalPlans` 端点 + ERP `listInventory`/`listPayables` 端点 + 供应商资质与历史表现库 RAG 向量通道（5 维度评分 + 黑名单规则 chunk）+ mock 内置供应商/报价/到货样本（S-COMP-001/002、AGFAP-002 延误）。无 `getSupplierQualifications` 端点——供应商资质走 RAG 检索，不调接口。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/agileac/terminal/login
```

- 采购子任务：用户名 `scm-buyer`
- 物流子任务：用户名 `scm-logistics`
- 密码：`12345678`

登录后落到 `/agileac/terminal`。左上角应显示对应用户 + 组织「敏睿空调」 + 部门「供应链部」。

> 终端使用 **user-type JWT**。`scm-buyer`（采购组）/ `scm-logistics`（物流组）的 scope 包含：组织级资源（33 组织本体）+ 供应链部部门级资源（技能 `agileac-scm-scm-erp-query` + 供应商资质 RAG）+ 个人工作区。

### 3.2 新建任务

点左栏「New Task / 新建任务」按钮，进入任务编辑器（HomeView composer）。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧 ⚙️ 设置按钮，打开 TaskConfigDrawer，配置 4 项：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `scm-buyer` 或 `scm-logistics`（个人工作区） | 干净；记忆仍按四级（组织+部门+团队+个人）自动载入 |
| Model | **`glm-5.2`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | agent 需多轮调 SCM/ERP 端点 + RAG + generate_docx；`ask` 只读单轮不够 |
| 场景模板 | `agileac-scm-01-procurement-logistics` | **必绑**——评审规则/RAG cue/输出骨架由模板 system_prompt 承载；技能可留空从模板继承，或显式选 `agileac-scm-scm-erp-query` |

> 若 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id`。
>
> **本体 / RAG / 记忆不在 drawer 里配置**——这些按用户 scope 自动注入：
> - 34 个本体文件（33 组织级含 SCM identifiers.md + 供应链部无专属本体）按 scope 自动注入；
> - 「供应商资质与历史表现库」RAG（部门级，scope=`supply`）自动可见；
> - 长期记忆按「组织+部门+团队+个人」四级自动载入。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 composer 输入框（`MentionInput`）里输入：

> 敲 `/` 弹出技能菜单，输入 `scm` 过滤，选中 **`agileac-scm-scm-erp-query`** 即把技能 chip 插入提示词。

**采购子任务**提示词（`scm-buyer` 登录，直接复制，约 70 字——**纯采购业务请求，不带任何检索/编排指令**）：

```
对敏睿空调 5 类核心配件做供应商评审与比价：压缩机 M-COMP-GT-24K、换热器 M-COND-FIN-30/M-EVAP-FIN-30、电子膨胀阀 M-EEV-15、制冷剂 M-RF-R410A。

/agileac-scm-scm-erp-query
```

**物流子任务**提示词（`scm-logistics` 登录，直接复制，约 55 字）：

```
监管敏睿空调核心配件到货与仓储，标出延误与缺料预警（重点压缩机 M-COMP-GT-24K、蒸发器 M-EVAP-FIN-30）。

/agileac-scm-scm-erp-query
```

> **四层架构**（详见 `SCENARIO_AUTHORING_GUIDE.md`）：user composer 只写**业务目标 + 配件对象 + 技能 chip**。5 维度评审规则（质量 35%/交期 25%/价格 20%/响应 10%/综合 10% + 黑名单触发条件）、双源策略、按供应商检索供应商资质与历史表现库、对账 ERP 应付、到货/仓储/缺料联动——**全部由 Agent 模板 `agileac-scm-01-procurement-logistics` 的 `system_prompt` 承载**（见 `## 检索供应商资质与历史表现库` / `## 评审规则` / `## 输出格式` 三节），不写进用户提示词。任务 config 必须绑定 `template_agent_id = <agileac-scm-01-procurement-logistics 的 UUID>`，运行时 `load_config` 才会注入模板（trace `template` 出现、`template:true`）。技能留空从模板继承 `agileac-scm-scm-erp-query`；模型模板默认 `glm-5.2`（与 drawer 一致，无需覆写）。
>
> 若前端 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id` 复现（`SELECT id FROM agents WHERE slug='agileac-scm-01-procurement-logistics'`）。

> ⚠️ **关键 1**：`/agileac-scm-scm-erp-query` 必须从 `/` 菜单选中 chip，不能手敲文本。agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时 message 里写 `/agileac-scm-scm-erp-query` 也会被同款正则解析（见 §6）。
>
> ⚠️ **关键 2**：提示词**只写业务目标 + 5 类配件款号**，不写"按 5 维度评分""查资质 RAG""对账应付"这类编排/检索指令——评审规则、RAG 检索、应付对账全由模板 system_prompt 驱动。
>
> ⚠️ **关键 3**：composer 写明 5 类核心配件物料号（M-COMP-GT-24K 等）——让 agent 有明确比价/到货检索锚点，避免泛化。本体 identifiers.md 已写明供应商前缀（S-COMP-/S-HEX-/S-VALVE-/S-REF-）、物料前缀（M-）、报价单 AGQ、到货计划 AGFAP，agent 调 `compareQuotations`/`listFabricArrivalPlans` 前读此表，杜绝 404。

#### 资源注入机制（任务运行时自动完成，无需配置）

任务运行时，agent runtime 会按 scm-buyer / scm-logistics 的 scope 自动注入以下资源到 system prompt：

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | 按 scope 注入（组织级 33 含 SCM identifiers） | 34 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出 | SCM/ERP 2 systems / ~20 interfaces |
| **RAG** | 空数组 = 全集自动匹配；retrieve_rag 节点按 query 检索 top-k | 1 collection（供应商资质与历史表现库），5 hits |
| **长期记忆** | 4 级聚合；load_memory 节点载入 | 若干 history + facts |
| **技能** | /-mention 解析 + 模板继承 | 1 skill（agileac-scm-scm-erp-query） |
| **记忆沉淀** | extract_memory 抽取本轮可沉淀事实 | 0~3 facts |

### 3.5 提交运行

按回车提交。前端 `POST /api/v1/terminal/tasks` 创建任务，再 `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}`——**这才是真正发给 agent 的输入**。手工调 API 时 `/run` 也要把完整提示词带上。

### 3.6 观察 SSE 事件流

事件类型同其他终端任务场景。SCM-01 关注：

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载配置（`template:true` 表示模板已注入） |
| `[trace]` (template) | 场景模板 `agileac-scm-01-procurement-logistics` 注入 |
| `[trace]` (rag) | RAG 检索命中——供应商资质与历史表现库（采购子任务必出） |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 34 组织本体注入（含 SCM identifiers） |
| `[trace]` (data_interface) | 数据接口目录注入（供应链部技能端点） |
| `[trace]` (skill) | /-mention 引用 `agileac-scm-scm-erp-query` |
| `[phase] llm` | LLM 调用轮次 |
| `[tool_call]` | agent 调 SCM `compareQuotations`/`listFabricArrivalPlans` + ERP `listInventory`/`listPayables` |
| `[tool_result]` | 工具返回（含 S-COMP-001/002、AGFAP-002 等样本） |
| `[text]` | LLM 流式输出评分表/仓储报表 |
| `[done]` / `[final]` | 收口 + usage + latency |

> 典型 SCM-01 运行约 4–6 分钟（2–3 轮 LLM + 4–6 次 tool 调用 + glm-5.2 推理 + 记忆/RAG 节点）。

---

## 4. 期望输出

### 4.1 采购子任务：供应商评分表 + 推荐清单

5 类核心配件按 5 维度评分（来自 RAG 资质库 + SCM 报价 + ERP 应付）：

#### 压缩机 M-COMP-GT-24K

| 排名 | 供应商 | 质量 | 交期 | 价格 | 响应 | 综合 | 推荐份额 |
|---|---|---|---|---|---|---|---|
| 1 | S-COMP-001 | A | A+ | B+ | A | A | 60% |
| 2 | S-COMP-002 | B+ | B | A- | B+ | B+ | 30% |

#### 推荐清单
- **主供**：S-COMP-001（份额 60%），原因：质量稳定（不良率 0.12%）、交期准时 99.2%、紧急 7 天交货。
- **备源**：S-COMP-002（份额 30%），原因：价格低 3%，但旺季交期异动 +15 天，需提前 60 天下单。
- **应付对账**：S-COMP-001 已对账；S-COMP-002 逾期（见 ERP `listPayables`）。

> 换热器 M-COND/M-EVAP-FIN-30（主供 S-HEX-001 A）、阀件 M-EEV-15（主供 S-VALVE-001 A+，建议培养 S-VALVE-002 备源）、制冷剂 M-RF-R410A（主供 S-REF-001 A）同理各一张评分表。

### 4.2 物流子任务：到货监管 + 仓储报表 + 缺料预警

#### 到货监管表

| 计划 ID | 物料 | 供应商 | 状态 | ETA | 延误天数 | 影响工单 |
|---|---|---|---|---|---|---|
| AGFAP-002 | M-COMP-GT-24K | S-COMP-002 | 延误 | 2026-07-10 | 7 | AWO20260105 |
| AGFAP-006 | M-RF-R410A | S-REF-001 | 在途 | 2026-07-12 | - | - |

#### 仓储报表

| 物料 | 仓库 | 现货 | 在途 | 安全库存 | 缺料预警 |
|---|---|---|---|---|---|
| M-COMP-GT-24K | WH-RAW-A | 50 | 100 | 30 | - |
| M-EVAP-FIN-30 | WH-RAW-B | 5 | 0 | 30 | ✗ 缺料 |

#### 缺料预警 + 催办
- M-EVAP-FIN-30 现货 5 < 安全库存 30，需立即补货 50 件。
- AGFAP-002 延误 7 天影响工单 AWO20260105，催办 supply-procurement 提前对接 S-COMP-002 或切 S-COMP-001。

### 4.3 .docx 报告附件

agent 调 `generate_docx` 工具把上述评分表/仓储报表打包成 `敏睿空调_供应商评审与采购物流_YYYYMMDD.docx`（约 40 KB），可下载分发归档。

### 4.4 SSE trace 事件（演示时截图可证）

| trace | 含义 | 期望实测值 |
|---|---|---|
| `category=template` | 场景模板注入（必出） | slug=agileac-scm-01-procurement-logistics + chars |
| `category=rag` | RAG 检索命中（采购子任务必出） | 1 collection / ≥3 hits（retriever=vector，覆盖供应商档案 + 5 维度规则 + 黑名单条件） |
| `category=memory, subtype=load` | 长期记忆载入 | 若干 history + facts |
| `category=ontology` | 组织本体注入（含 SCM identifiers） | 34 files |
| `category=data_interface` | 数据接口目录注入（按供应链部权限） | 2 systems / ~20 interfaces |
| `category=skill` | /-mention 引用技能 | 1 skill（agileac-scm-scm-erp-query） |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | 0~3 facts |

---

## 5. 故障排查

### 5.1 模型选择器里没有 `glm-5.2`
- 智谱 AI provider 未配或 `supported_models` 不含 `glm-5.2`。修复：管理端配智谱 AI provider（`supported_models` 含 `glm-5.2`）+ 路由策略 `model_pattern=glm-*`，重跑 `seed_agileac_org.py`。

### 5.2 提示词里 `/agileac-scm-scm-erp-query` 没被识别
- 必须从 `/` 弹窗选 chip，不能手敲。自检：task.message 里这段应是结构化 chip 标记。

### 5.3 `[tool_result FAIL]` SCM/ERP 接口调用失败
- mock 网关未起或 API key 不匹配。自检：
  ```bash
  curl -s "http://localhost:8010/scm/suppliers" -H "X-API-Key: scm-agileac-demo-key" | head
  curl -s "http://localhost:8010/scm/fabric-arrival-plans" -H "X-API-Key: scm-agileac-demo-key" | head
  curl -s "http://localhost:8010/erp/inventory" -H "X-API-Key: erp-agileac-demo-key" | head
  ```
  均应返回 JSON。

### 5.4 `scm-buyer`/`scm-logistics` 看不到 SCM/ERP 数据接口 / 供应商资质 RAG
- 部门级 scope 授权未配置——`seed_agileac_mock_connectors.py` 没把供应链部技能 `agileac-scm-scm-erp-query` 按 `scope_type=department, scope_id=supply_dept.id` 配好；或 `seed_agileac_rag.py` 没把供应商资质 RAG 按 dept supply 落库。
- 自检：`GET /api/v1/terminal/resources`（scm-buyer token）的 `skills` 应含 `agileac-scm-scm-erp-query`，`rag_collections` 应含「供应商资质与历史表现库」。
- 修复：重跑 `seed_agileac_mock_connectors.py` + `seed_agileac_rag.py`。

### 5.5 agent 输出「我没有收到任务」
- 检查 `/run` 请求体里 `message` 是否为空——必须把完整提示词作为 `message` 发送。

### 5.6 运行很久没动 / latency > 6 分钟
- glm-5.2 单轮推理慢，多轮 tool 调用累计 4–6 分钟正常。超过 10 分钟看 `docker logs ai_infra_backend --tail 100`。

### 5.7 trace `rag` 显示 `retriever=keyword_fallback`
- 向量 embedding 不可用，RAG 退化为 CJK 关键词检索。
- 修复：管理端配 OpenAI 兼容 embedding provider（如 aliyun `text-embedding-v4`）；chunks embedding 为 NULL 时跑 `reembed_agileac_rag.py --collection-name "供应商资质与历史表现库"` 回填。

### 5.8 agent 没主动触发 RAG 检索（采购子任务）
- 编排（检索供应商资质与历史表现库）由模板 `system_prompt` 的 `## 检索供应商资质与历史表现库（RAG，必做，采购子任务）` 节承载，**不应靠用户提示词加 cue**。若采购子任务 RAG 没触发：先确认 `load_config template:true` + `trace template` 出现；再确认模板 `system_prompt` 含"检索供应商资质与历史表现库"指令；最后看 retrieve_rag 节点 query 嵌入是否命中——embedding 未配时走 keyword_fallback，提示词含"S-COMP"/"供应商"/"评审"关键词仍应命中资质库 chunk。

### 5.9 `tool_call` args 全 `{}`
- 现象：所有 `tool_call.arguments={}`，需要参数的端点（如 `compareQuotations(material_code=...)`）返回 500。
- 根因：`_build_tools`（`app/agents/graph/nodes.py`）manifest 占位 schema 覆盖问题（详见 `SCENARIO_AUTHORING_GUIDE.md` §6.10）。
- 修复：只要有一条 `tool_call` args 非 `{}` 就说明 `_build_tools` 正常；全 `{}` 立即查 `nodes.py` `_build_tools`。

### 5.10 path 参数端点（`getSupplier`/`getQuotation`）返回 404
- 现象：agent 调 `getSupplier(code="S-COMP-001")` 返回 `{code} not found`——path 占位符未替换。
- 影响：**不阻塞闭环**。agent 自主降级到 `listSuppliers`/`listQuotations`（query 参数端点）仍能拿到完整信息。
- 修复（可选）：技能 wrapper 按 OpenAPI path 占位符替换。非阻塞性，本期按「agent 自主降级」通过。

### 5.11 供应商评分杜撰（不来自 RAG）
- 现象：评分表的 A/B+ 等级与 RAG 资质库不符或凭空生成。
- 根因：agent 没检索或忽略 RAG 资质 chunk，靠模型先验杜撰。
- 修复：确认 `load_config template:true` + 模板含"检索供应商资质与历史表现库"指令；embedding 未配时走 keyword_fallback，含"S-COMP-001"/"评分"关键词仍应命中。

### 5.12 memory/extract 抽取 0~3 facts
- 非阻塞；长期记忆跨任务复用弱。修复（可选）：调整 `extract_memory` prompt 显式抽取供应商→评分→份额三元组。

---

## 6. 附：手工调 API 复现

```bash
# 1) 登录拿 user token（采购子任务用 scm-buyer，物流子任务换 scm-logistics）
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agileac","username":"scm-buyer","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 SCM Agent 模板 id
TPL_ID=$(docker exec ai_infra_backend python3 -c "
import asyncio, asyncpg
async def m():
    c=await asyncpg.connect('postgresql://ai_infra:ai_infra@postgres:5432/ai_infra')
    r=await c.fetchrow(\"SELECT id FROM agents WHERE slug='agileac-scm-01-procurement-logistics'\")
    print(r['id']); await c.close()
asyncio.run(m())")

# 3) 创建任务（绑定模板；skill_ids 留空从模板继承，model=glm-5.2）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"SCM-01 供应商评审\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（采购子任务短 composer，含 /agileac-scm-scm-erp-query chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"对敏睿空调 5 类核心配件做供应商评审与比价：压缩机 M-COMP-GT-24K、换热器 M-COND-FIN-30/M-EVAP-FIN-30、电子膨胀阀 M-EEV-15、制冷剂 M-RF-R410A。\\n\\n/agileac-scm-scm-erp-query\",\"stream\":true}"
```

物流子任务换 `scm-logistics` 登录 + §3.4 物流子任务提示词。短 composer 提示词文本见 §3.4（评审规则/RAG cue/输出格式由 SCM Agent 模板 `system_prompt` 承载，不在 composer 里）。

---

## 7. 验收要点（演示前自检）

- [ ] `scm-buyer` / `scm-logistics` 能登录 `/agileac/terminal/login`，左上角显示「供应链部」
- [ ] `GET /api/v1/terminal/resources`（scm-buyer token）的 `skills` 含 `agileac-scm-scm-erp-query`（dept: supply）
- [ ] `rag_collections` 含「供应商资质与历史表现库」（scope=department, supply）——**不应**含其他部门级 RAG（如「售后故障与维修知识库」「质量缺陷案例库」），验证部门级资源隔离
- [ ] `data_interfaces` 含 SCM/ERP 端点（不含 PLM/MES/CRM/HRM——非本部门权限）
- [ ] `load_config` 事件显示 **`template:true`**（绑定了 template_agent_id）
- [ ] `trace category=template` 出现（slug=`agileac-scm-01-procurement-logistics` + chars）
- [ ] 采购子任务跑完，SSE 6 类 trace 全部出现（rag + memory.load + ontology + data_interface + skill + memory.extract）；物流子任务 rag 仍应出（query 含供应商/物料关键词命中资质库）
- [ ] `retrieve_rag` 显示 `retriever=vector`，采购子任务 hits ≥ 1，命中供应商档案/5 维度规则 chunk
- [ ] `tool_call` args 不全 `{}`（至少 `compareQuotations(material_code=...)` 或 `listFabricArrivalPlans(...)` 这类必传参端点要带参）
- [ ] no-guessing：agent 用对供应商前缀（S-COMP-/S-HEX-/S-VALVE-/S-REF-）、物料前缀（M-）、到货计划 AGFAP，不把报价单 AGQ 当到货计划 AGFAP 直传
- [ ] 采购子任务输出含 5 类配件供应商评分表 + 推荐清单（主供/备源 + 份额 + 应付对账）；物流子任务输出含到货监管 + 仓储报表 + 缺料预警
- [ ] 评分来自 RAG 资质库 + SCM 报价不杜撰；缺料预警催办 supply-procurement（同部门跨组，不直接调用其他部门 agent）
