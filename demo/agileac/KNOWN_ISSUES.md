# 敏睿空调（agileac）Demo · 已知问题

> 本文件追踪 agileac demo 落地与运行中暴露的问题。与 `../starclothing/KNOWN_ISSUES.md`
> 共享同一后端（`llm_router/backend`）的问题（如 path-param 占位符 #1、memory/extract
> JSON fence #2、跨 agent 待办 #3 未实施）不再重复，此处只列 agileac 特有问题。
>
> 状态图例：✅ 已修 ｜ 🟡 部分修 ｜ ❌ 未修 ｜ 🚧 计划中

---

## Issue A1 — 11 场景全部四层化 ✅（11 场景全部端到端实测通过）

- **现象**：`seed_agileac_agents.py` 中 11 个 Agent 的 `system_prompt` 已全部重写为四段式（persona + 职责 + 业务规则 + 输出骨架，无 `AG-XXX` 代号 + 无硬编码端点列表）。P0 三场景（SVC-01/SAL-02/MKT-01）+ P1 三场景（RND-01/SCM-01/FIN-01）+ P2 五场景（PRD/MFG/QAL/SAL-01/HR）全四层化。本体 identifiers.md 已覆盖 PLM/CRM/MES/HRM/ERP/SCM 六域。
- **P2 落地（2026-07-13）**：
  - PRD/MFG/QAL/SAL-01/HR 五 Agent `system_prompt` 四段化（去掉硬编码端点列表与未实现端点 `getProductSellingPoints`/`getSupplierQualifications`/`listCapacityCalendar` 等，改"结合上方本体与数据接口目录自主规划"cue + identifiers 前缀提示）。
  - 五场景终端任务文档 `prd_01_terminal_task.md` / `mfg_01_terminal_task.md` / `qal_01_terminal_task.md` / `sal_01_terminal_task.md` / `hr_01_terminal_task.md` 写完（短 composer + §6 手工 API + §7 验收要点，对齐 P0/P1 结构）。
  - `SCENARIO_ROSTER.md` 五场景 🚧→✅ + composer 提示词 + 模板细节补齐 + 演示速查表加 5 行；`README.md` §14 状态列标注 P2 ✅（待实测）；§2 演示矩阵 + §8.x 设计段技能 slug 与端点修正（A4 一并清）。
  - **关键设计点**：PRD 卖点走 RAG（非 `getProductSellingPoints` 端点）；MFG 无 RAG，排产规则由模板承载（A2 待补非阻塞）；QAL 跨码空间 `DF` ≠ `DF-AG-` 按 product_code 关联；SAL 应收走 CRM `listReceivables`（ERP 无该端点），退换货转 svc-engineer 回流 SVC-01；HR 三子任务按归口员工切 RAG（招聘 team JD 库 / 培训制度 org 库 auto-load / 薪酬 HRM），`shortlistResumes` POST 不绑定用 `listResumesByPosition` 替代。
  - **P2 五场景端到端实测通过（2026-07-13/14，详见 A7）**：五 agent 四层 prompt 已落库（重跑 `seed_agileac_agents.py`）；PRD-01 用 glm-5.2 跑通，MFG/QAL/SAL-01（sal-ops + sal-ecom 两子任务）/HR-01（hr-recruiter + hr-trainer + hr-compensation 三子任务）用 deepseek-v4-pro 跑通。8 次子任务跑全部 `load_config template:true` + 6 类 trace + `tool_call` args 全非 `{}` + `generate_docx` 附件 + `final`，无一 error。glm-5.2 在 QAL 第 4 轮 LLM 流式卡死（A5 类 key 不稳定，无 timeout），改 deepseek-v4-pro 稳定；embedding provider 已配（vector retriever 8 hits，A5 旧 keyword_fallback 已消除）。
- **参考**：`seed_agileac_agents.py` P0+P1 六 Agent 范式 + `../starclothing/scripts/seed_starclothing_agents.py:97-142` PD-2/PD-3 范式。

## Issue A2 — MFG 场景无 RAG 🚧

- **现象**：`MFG-01 工单进度与产能报表` Agent 的 `rag_collection_name=None`，排产优先级规则（旺季家用优先 vs 商用项目优先、缺料卡顿优先级）散在 system_prompt 里，无独立可检索 playbook chunk。
- **影响**：排产规则无法按意图检索命中，agent 靠 prompt 内嵌规则推，多租户换种不灵活。
- **修复计划**：`seed_agileac_rag.py` 新增「排产与产能规则库」（dept: production），含排产优先级 / 缺料卡顿规则 / 产能预警阈值 playbook chunk，MFG-01 绑定。
- **参考**：`seed_agileac_rag.py` 供应商评审 5 维度 playbook chunk（`SCM-01`）作范式。

## Issue A3 — `seed_agileac_mock_tenants.py` 不存在（README 文档失配）🟡

- **现象**：README §13 目标结构列出 `scripts/seed_agileac_mock_tenants.py`，但实际不存在。agileac 租户数据直接写在 `mock/mock/systems/*/data.py` 的 `_build_agileac()` 内（HRM 见 `mock/mock/systems/hrm/data.py:414`），mock 容器重启即生效。
- **影响**：文档与实现不一致，新人按 README 找脚本会扑空。
- **修复状态**：P0 三终端任务文档 §2 已改为「mock 数据已内置，容器重启即生效，无需独立 seed 脚本」。README §13/§9 待统一修正。
- **参考**：`mock/mock/core/registry.py:68-136` 6 系统 `tenants` 元组已含 `agileac` + `keys_to_tenants` 加 `agileac` demo key。

## Issue A4 — README 技能名与 seed 不一致 ✅ 已修

- **现象**：README §2 演示矩阵 + §8.x 设计段写 `agileac-prd-plm-query` / `agileac-mfg-mes-scm-query` / `agileac-qal-mes-plm-scm-query` / `agileac-sal-crm-erp-scm-query` / `agileac-scm-scm-erp-plm-query` / `agileac-fin-erp-mes-scm-plm-query` / `agileac-hr-hrm-erp-query`（含 SCM/PLM 子集或漏 CRM），但 `seed_agileac_mock_connectors.py` 实际为 `agileac-prd-plm-crm-query` / `agileac-mfg-mes-erp-scm-query` / `agileac-qal-mes-plm-query` / `agileac-sal-crm-erp-query` / `agileac-scm-scm-erp-query` / `agileac-fin-erp-crm-query` / `agileac-hr-hrm-query`。
- **影响**：文档误导，按 README 找技能会扑空。
- **修复状态（2026-07-13）**：P2 五场景四层化时已统一修正 README §2 矩阵 + §8.2/§8.3/§8.4/§8.6/§8.10 设计段的技能 slug，同时修正 SCM（§8.5）/FIN（§8.9）slug 与实际 seed 一致；`SCENARIO_ROSTER.md` 总览表 + 演示速查表 slug 与 seed 一致（单一事实源）。同步清理未实现/未绑定端点引用（`getProductSellingPoints`/`getSupplierQualifications`/`listCapacityCalendar`/`getSalesOrder`/`listReceivables` 归属等）。

## Issue A5 — P0 端到端实测：架构注入路径已验证，LLM 执行被过期 key 卡住 🟡

- **已验证（架构层全绿）**：2026-07-13 跑 SVC-01（task 286b11a8，归口用户 svc-engineer，短 composer + template_agent_id 绑定），SSE 实测：
  - `load_config template:true` ✓
  - `trace category=template` slug=agileac-svc-01-after-sales-diagnosis chars=859 ✓（L3 四段 prompt 注入）
  - `trace category=ontology` 37 files **含 PLM/ERP/MES/CRM/HRM 的 identifiers.md** ✓（L2 注入）
  - `trace category=rag` 2 collections/8 hits（keyword_fallback）+ `data_interface` 6 systems/101 interfaces + `skill` 引用正确 + `memory` load/extract ✓
  - 归口用户 scope 过滤正确（37 ontologies / 101 interfaces / 2 rags / 1 skill，org scope 对部门用户可见）✓
  - 6 类 trace 全出 ✓
- **SAL-02 端到端实测通过（2026-07-13，glm-5.2 已可用）**：跑 SAL-02（task 225ec281，归口用户 sal-ops，**纯业务问题 composer ~20 字** + template_agent_id=8fc06c55 绑定，编排完全由模板 system_prompt 驱动），latency 65s / output 1676 token：
  - `load_config template:true` + `trace template` slug=agileac-sal-02-reimbursement-status chars=740 ✓
  - `trace rag` 5 hits（keyword_fallback，embedding provider 仍未配）——命中员工综合知识库报销 5 步流程 chunk ✓
  - `tool_call agileac-sal-crm-erp-query__listVouchers`（args=`{}`，`_build_tools` 占位 schema 已知问题，因 listVouchers 参数可选非阻塞）+ `tool_result ok` 含 BV-AG-2026-0512 ✓
  - agent 开头自述"我先从员工综合知识库确认流程步骤语义，再调 ERP listVouchers 取活数据"——证明**先 RAG 后接口编排源自模板而非用户提示词** ✓
  - 答案含「财务复核中（第 4 步）/ ¥6,800 / 2026-07-08 提交 / 预计周二/四打款 → 已打款 → 已闭环」+ 引用源（知识库 chunk + ERP 端点 + 凭证号）✓
  - 6 类 trace 全出 ✓
  - 说明：glm-5.2 key 已恢复可用（与 SVC-01 实测时的 401 状态不同）；embedding provider 仍未配，RAG 走 keyword_fallback 但纯问题含"差旅报销"关键词仍正确命中报销 chunk。
- **MKT-01 端到端实测通过（2026-07-13，glm-5.2）**：跑 MKT-01（task be3603b8，归口用户 mkt-specialist，**纯业务请求 composer ~45 字** + template_agent_id=af48fdf3 绑定，模板 `model_alias=glm-5.2`），latency ~12 min / output 25504 token：
  - `load_config template:true` + `trace template` slug=agileac-mkt-01-marketing-content chars=748 ✓
  - `trace rag` 8 hits（keyword_fallback）+ `data_interface` + `skill` + `memory` load/extract(8 facts) + `ontology` ✓（6 类 trace 全出）
  - 7 个 `tool_call`：PLM `getStyle`×2（2 款产品）+ CRM `listCustomers`×2/`listOpportunities`/`listComplaints` + `generate_docx`，**全由模板 system_prompt 驱动**（用户提示词只写"为2款产品生成营销内容与培训课件"，未提任何端点/检索）✓
  - agent 开头自述"我将按以下流程执行：1. PLM 产品详情+卖点 2. CRM 客户画像 3. RAG 知识库→竞品参数/海报模板/课件模板"——证明三段交付结构 + PLM→CRM→RAG 编排源自模板而非用户 ✓
  - 输出含三段（卖点+竞品对比表 / 海报文案+视频脚本 / 课件大纲+PPT+考题）+ 2 款产品（P-RC-WALL-15/P-CC-VRV-360）+ 5 大竞品（格力/美的/海尔/大金/三菱，**由模板"竞品覆盖5大品牌"指令驱动，composer 已不含**）+ generate_docx 附件 ✓
  - 说明：agileac 11 个 agent 模板 `model_alias` 已统一为 `glm-5.2`（真实模型 id，无别名层）；demo 演示时 drawer 选 `glm-5.2` 与模板默认一致，无需覆写。
- **RND-01 端到端实测通过（2026-07-13，glm-5.2 provider 重置后）**：跑 RND-01（task 9e645fac，归口用户 rnd-translator，**纯业务 composer ~80 字（外文原文 + chip，无编排指令）** + template_agent_id=cd40f29c 绑定），latency 176s / output 5446 token / input 139955 token：
  - `load_config template:true` + `trace template` slug=agileac-rnd-01-translation chars=838 ✓（L3 四层 prompt 注入，P1 落地确认）
  - 6 类 trace 全出：`rag`（keyword_fallback，4 collections/8 hits，命中术语词典 chunk）+ `memory/load`（0/0）+ `ontology`（37 files，含 PLM/ERP/MES/CRM/HRM identifiers + rnd-translation 部门级）+ `data_interface`（6 systems/101 interfaces，org scope）+ `skill`（agileac-rnd-plm-query）+ `memory/extract`（0 facts）✓
  - 3 个 `tool_call`，**args 非 `{}`**：PLM `getStyle(style_code="P-RC-WALL-15")` ok + `getStyle(style_code="P-CC-VRV-360")` ok + `generate_docx`（filename=DC变频压缩机技术段_中文化译文_术语对照_型号核对.docx，38KB）ok ✓——证明四层 prompt 删掉硬编码 `listPendingTranslations`（未实现端点）后，agent 自主从数据接口目录选 `getStyle` 做型号核对，编排源自模板而非用户 ✓
  - agent 开头自述"我先检索 PLM 中两个产品款号的详情与 BOM，用于翻译时的型号与参数核对"——证明 PLM 核对编排源自模板 ✓
  - 输出含三段（中文化译文 / 术语对照表 / 型号差异提示）+ docx 附件 ✓；术语统一（rotary compressor→直流变频转子压缩机、refrigerant→制冷剂非冷媒、EEV/COP 首次括注缩写、型号段 P-RC-WALL-15/P-CC-VRV-360/R410A/M-COMP-GT-24K/M-EEV-15/M-RF-R410A 保留原文）✓；额外发现 3 项原文 vs PLM BOM 数据差异（R410A 充注量 1.8kg vs PLM 0.8kg、28kg vs 12kg、rotary vs 涡旋），型号核对真正发挥作用 ✓
  - 说明：glm-5.2 首次跑（task af466569 等）曾 429 `insufficient_quota`（token-plan 配额耗尽，与 A5 旧 401 不同 blocker），provider 重置后恢复；embedding provider 仍未配（RAG keyword_fallback，含英文术语关键词仍命中）；`getStyle` path-param 未 404（starclothing PD-1 path-param 修复覆盖 agileac）。
- **SCM-01 端到端实测通过（2026-07-13，deepseek-v4-pro）**：跑 SCM-01 采购子任务（task e6a610f8，归口用户 scm-buyer，纯业务 composer ~70 字 + template_agent_id=19ef6052 绑定），latency 220s / output 13428 token / input 276408 token：
  - `load_config template:true` + `trace template` slug=agileac-scm-01-procurement-logistics chars=1171 ✓（SCM identifiers 已注入：ontologies=34 含 SCM/identifiers.md）
  - 6 类 trace 全出：`rag`（keyword_fallback，4 collections/8 hits，命中供应商档案 + 5 维度规则 chunk）+ `memory/load` + `ontology`（34）+ `data_interface`（6/101）+ `skill` + `memory/extract` ✓
  - 30 个 `tool_call`，**全部带真实参（无一 `{}`）**：`compareQuotations(material_code=M-COMP-GT-24K/M-COND-FIN-30/M-EVAP-FIN-30/M-EEV-15/M-RF-R410A)` ×5 + `getSupplier(code=S-COMP-001/002/S-HEX-001/002/S-VALVE-001/S-REF-001)` + `listPayables(supplier_code=)` ×5 + `listInventory(material_code=)` ×5 + `listFabricArrivalPlans(material_code=)` ×5 + `listReplenishmentSuggestions(style_code=P-RC-WALL-15)` ✓——编排全由模板驱动（composer 只写"5 类配件做供应商评审与比价"）
  - 输出含三段：5 类配件比价表（报价单号 AGQ + 供应商 S- + 评级 + 单价/MOQ/交期/账期/比价得分）+ 供应商 5 维度评分表（RAG 资质映射 + 加权总分 + 等级 A+/A/B+/B，质量35%/交期25%/价格20%/响应10%/综合10%）+ 推荐份额清单（主供/备源 + 份额 + 应付对账 AGINV 逾期状态）+ generate_docx 附件（敏睿空调_5类核心配件_供应商评审比价报告_20260701.docx）✓
  - 优雅处理 S-VALVE-002 不存在（`getSupplier` ok=False，agent 标注"仅 1 家报价 + 单源风险极高需紧急寻源"）✓
  - 说明：glm-5.2 在 RND-01 跑完后再次 401（"令牌已过期"），改用 deepseek-v4-pro（同组织 models 列表含 deepseek-v4-pro/glm-5.2/qwen3.7-plus）；SCM-01 无 `getSupplierQualifications` 端点（未实现），供应商资质走 RAG 检索 + SCM `compareQuotations` 比价，验证四层化删硬编码端点后 agent 自主从目录选端点的设计正确。
- **SCM-01 物流子任务端到端实测通过（2026-07-13，deepseek-v4-pro）**：跑 SCM-01 物流子任务（task c3f81c48，归口用户 scm-logistics，纯业务 composer ~55 字 + template_agent_id=19ef6052 绑定）：
  - `load_config template:true` + `trace template` chars=1171 ✓；6 类 trace 全出（rag memory×2 ontology data_interface skill）。
  - 16 个 `tool_call` 全带真实参：SCM `listFabricArrivalPlans(material_code=)`×3 + `listInventory(material_code=)`×5 + `listReplenishmentSuggestions` + ERP `listPurchaseOrders`×3 + `listPayables`×3 + `generate_docx` ✓——编排全由模板驱动（composer 只写"监管核心配件到货与仓储，标延误与缺料预警"）。
  - 输出含核心配件到货监管表 + 延误/缺料预警（重点压缩机 M-COMP-GT-24K、蒸发器 M-EVAP-FIN-30）+ `generate_docx` 附件（敏睿空调_核心配件到货监管与缺料预警_20260702.docx，39803 bytes）✓，无一 error。
  - 至此 SCM-01 采购（scm-buyer）+ 物流（scm-logistics）双子任务均实测通过。
- **FIN-01 端到端实测通过（2026-07-13，deepseek-v4-pro）**：跑 FIN-01 对账子任务（task b1bdaf14，归口用户 fin-accountant，纯业务 composer ~60 字 + template_agent_id=53ca7af8 绑定），latency 503s / output 33038 token / input 377553 token：
  - `load_config template:true` + `trace template` slug=agileac-fin-01-reconciliation-receivable chars=1106 ✓
  - 6 类 trace：`template` + `rag`（5 hits，org 级员工综合库 auto-load，**FIN 无部门 RAG 但 org 级 RAG 仍触发**）+ `memory/load` + `ontology`（34）+ `data_interface`（6/101）+ `skill` + `memory/extract`（**8 facts**，deepseek 抽取优于 glm 的 0）✓
  - 15 个 `tool_call`，**跨 5 系统（SSO 免登验证）**：ERP `listVouchers(period=2026-06)` + `listProductionCosts(period=)` + `listMaterials(category=压缩机/换热器)` + MES `listWorkOrders` + `getWorkOrder(won=AWO20260210/0211/0215/0220)` ×4 + SCM `listQuotations(status=有效)` + PLM `getCostLedger(period=2026-06)` + CRM `listReceivables(status=逾期)` ✓——证明 FIN 技能扩绑（slug `agileac-fin-erp-crm-query` 保留，bindings 增 MES/SCM/PLM，14 端点）后四方对账真跨系统，SSO 价值落地
  - 输出含四方对账报告：数据概览（ERP 凭证 BV-AG- / ERP 生产成本 AGPC by 工单 / PLM 成本台账 AGCL / SCM 报价 AGQ）+ 物料级差异表（PLM↔SCM，6.42% 标⚠️）+ 工单级差异表（ERP↔PLM，124.8%/663.9% 标⚠️ + 智能解释 PLM 台账仅覆盖压缩机+冷凝器）+ 异常清单+催办 + generate_docx 附件（敏睿空调_2026-06期_四方对账报告.docx）✓；BV-AG-2026-0512 跨系统 SSO 演示凭证引用 7 次，"免登跨系统"cue 源自模板（composer 只写"做四方对账"）
  - no-guessing：跨系统码空间用对（BV-AG- 凭证 / AWO 工单 / AGCL 成本台账 / AGQ 报价 / AGPC 生产成本），按 work_order_no / material_code 关联不臆造 ✓
  - 说明：FIN-01 "无 RAG" 的说法需修正——agent 虽无部门级 RAG，但 org 级员工综合知识库对全员 auto-load，`trace rag` 仍会触发（5 hits，命中含"对账/凭证/应收"关键词的 chunk），非阻塞。
- **未通过（infra 阻塞，非设计）**：
  - **所有 4 个 LLM provider 的 API key 均已失效**：glm-5.2（智谱）→ 401「令牌已过期或验证不正确」；claude-sonnet-4（Anthropic）→ 403 forbidden；gpt-4o-mini（OpenAI）→ 120s 超时空返回；deepseek-reasoner → 401「invalid api key」。导致 `tool_call=0`/`text=0`，agent 末跑出真实推理与工具调用。
  - **embedding provider 未配**：`rag_embed_failed_fallback_keyword: no provider available for model 'text-embedding-v4'`，53 chunks 全未 embed，RAG 退化为 CJK keyword_fallback（仍命中 8 hits，但非 vector）。
- **修复**：刷新至少一个 LLM provider 的有效 API key（glm-5.2 优先，agileac 终端任务默认 `model_alias=glm-5.2`），再重跑 SVC-01 §6 过 §7 验收（重点看 `tool_call` args 不全 `{}` + 三段输出上屏 + generate_docx 附件）。embedding 可选配 OpenAI 兼容 text-embedding-v4 provider 跑 `reembed_agileac_rag.py` 回填以切回 vector 检索。
- **参考**：SSE 原文 `docker logs ai_infra_backend` 2026-07-13 05:15–05:26；`../starclothing/pd2_terminal_task.md` §4.6 实测回归表作完整跑通范式。

## Issue A6 — `model_aliases` 表被删但 embed 代码仍查它，毒化事务致 RAG 场景随机崩 ❌

- **现象**：跑 SCM-01（task bd6118c1）时 `retrieve_rag` 报 `InFailedSQLTransactionError: current transaction is aborted`，SSE 只出 `step`+1 trace+`error`+`final`，无后续 trace / 无 text / 无 tool_call。
- **根因**：后端 RAG embed 路径解析 embedding 模型别名时执行 `SELECT FROM model_aliases WHERE alias='text-embedding-v4'`（`app/agents/graph/nodes.py` retrieve_rag 触发）。但 `model_aliases` 表在重构里被删（git status：`D llm_router/backend/app/models/model_alias.py` + `D .../schemas/model_alias.py` + `D .../api/model_aliases.py`），表已不存在 → `UndefinedTableError` → 同事务后续 `db.get(RagCollection)` 跟着 `InFailedSQLTransaction` 崩。
- **影响**：所有绑 RAG 的场景（RND/PRD/QAL/SCM/SVC/MKT/HR/SAL-02）retrieve_rag 都查 model_aliases。RND-01 靠事务边界差异侥幸躲过（embed 失败被 catch 走 keyword fallback，retrieve_rag 在干净事务里跑），SCM-01 撞上同事务中毒路径。**非确定性**——同一场景重跑可能崩可能不崩。
- **验证期临时解封（已应用）**：建空 `model_aliases` 表让 embed 查询返回空 → 走 keyword fallback（本就工作），事务不中毒：
  ```sql
  CREATE TABLE IF NOT EXISTS model_aliases (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      organization_id UUID, alias VARCHAR, target_model VARCHAR,
      description TEXT, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());
  ```
  建表后 SCM-01 / FIN-01 端到端跑通（A5 实测段）。**可逆**：`DROP TABLE model_aliases` 即还原。
- **真正修复**：后端 embed 代码不应再查 `model_aliases`（表已删）——改走 provider `supported_models` 直查或删除别名解析层。属 `llm_router/backend` 代码层，与 starclothing 共享，建议落到 `../starclothing/KNOWN_ISSUES.md` 共享条目。
- **参考**：`docker logs ai_infra_backend` 2026-07-13 11:33（SCM-01 task bd6118c1 崩溃栈）；`app/agents/graph/nodes.py:404` retrieve_rag `db.get(RagCollection, cid)`。

## Issue A7 — 终端任务执行与 SSE 连接耦合（刷新即死）✅ 已根治（2026-07-13）

- **现象**：跑 PRD-01/MFG-01 时刷新页面，右栏进度全部消失、`agent_runs.status` 卡 `running`。根因是**执行模型缺口**（非配置）：`runner.py` 的 `stream_general_agent` 把 `graph.astream` 塞进 SSE `StreamingResponse` 的 body 迭代器 → 图执行生命周期 = HTTP 连接生命周期，无 `asyncio.create_task` detach、进度事件不落库、无 resume/replay 端点；前端 `Terminal.tsx` 刷新即断 EventSource 且无重连，任务列表 `invalidateQueries` 只在流结束后触发（执行期间左栏看不到任务，诱使用户刷新）。
- **修复**（平台层，agileac + starclothing 同受益）：
  - 后台 detach 执行：`stream_general_agent` 改为 `asyncio.create_task(_run_graph_bg)`，独立 `async_session_factory()` 会话，图执行与 SSE 连接解耦（`runner.py` + `run_registry.py`）。
  - 事件落库：新增 `agent_run_events` 表（迁移 0031）+ `AgentRunEvent` 模型，每条 SSE 事件边产边落库（按 seq 回放）；首事件 `load_config` 带 `run_id`（`nodes.py` 一行）使后台 consumer 即时持久化。
  - resume 端点 `GET /terminal/tasks/{id}/stream`：registry 有 live handle → 回放 buffer + 续接 queue；run 已完成 → 回放落库事件；孤儿（进程重启后 status=running 无 live handle）→ 标 interrupted + 回放 + 合成 final。
  - 取消端点 `POST /terminal/tasks/{id}/cancel`：`run_registry.cancel` → 后台 Task.cancel → astream 抛 CancelledError → runner 标 run error（Stop 按钮真停后台，非仅断读端）。
  - 启动期清理：`main.py` lifespan startup `UPDATE agent_runs SET status='error' WHERE status='running'`（上一进程的内存图任务已死，幂等）。
  - 前端：抽 `consumeSSE`/`dispatchEvent` 复用 POST /run 与 GET /stream；`startTask` createTask 后立即 `invalidateQueries(['terminal-tasks'])`（左栏即时出现）；选任务/挂载时 `selectedTask.run_status==='running'` 自动 `streamTask` 重连；unmount `abortRef.abort()`；`stopStream` 调 `cancelTask`。`TaskReadWithMessages` 增 `run_status` 字段。
- **实测通过（curl，2026-07-13）**：detach 跑完整事件流（step+6 trace+phase+41 text deltas）；mid-run GET /stream 回放 37 事件 + 续接；post-completion 回放 79 落库事件；run status running→success（output 164）；cancel 标 run error 'cancelled by user/shutdown' + 事件不丢；lifespan 清孤儿 `count=1`。
- **未覆盖**：agent 模式（管理端 playground `stream_agent`）同款 SSE-coupled 缺口未修——本期只修 general（终端）模式，agent 模式留后续（同样套 run_registry 即可）。单 uvicorn worker 假设成立（`Dockerfile:22`）；若未来多 worker 需换外部队列。

## Issue A8 — `_run_graph_bg` 共享 AsyncSession 致 asyncpg 并发争用崩（P2 实测期暴露）✅ 已修

- **现象**：P2 实测期（2026-07-13），跑 MFG-01/QAL-01 时 SSE 在 10–20s 内出 `step`+6 trace+少量 `tool_call` 后戛然而止，backend 日志 `general_bg_error: (asyncpg.InterfaceError) cannot perform operation: another operation is in progress`，崩在 `SELECT tool_endpoints WHERE connector_id IN (...)`（`_execute_tool_call` 取 `ToolConnector` 触发的 lazy-load）+ `await db.flush()`（`execute_endpoint` 落 `ToolCallLog`）。**非确定性**——PRD-01 同期跑通（525s / 7 tool_call），MFG 首跑也跑通（仅末尾 generate_docx 落库撞 `workspaces connection closed`），但 backend 重启后变得**确定性可复现**（连接池热状态变了）。
- **根因**：`runner._run_graph_bg` 把同一个 `async_session_factory()` 会话既设进 `ctx["db"]`（图节点 `get_deps()` 用它做 `db.get`/`db.flush`），又由 consumer 循环 `db.add(AgentRunEvent)` + 每 25 条 `await db.commit()`。langgraph 把图执行跑在内部任务里、`async for chunk in graph.astream` consumer 在外层任务里——两者**并发复用同一 AsyncSession/asyncpg 连接**：consumer 的 `commit`（flush INSERT 走 asyncpg）与图节点的 `db.get`/`flush` 在同一连接上交叠 → asyncpg 拒绝「another operation is in progress」。SQLAlchemy AsyncSession 明确不支持跨并发任务共享。
- **影响**：所有终端 general 模式任务（agileac 11 场景 + starclothing 全部终端场景）在触发时机不对时都会崩；概率随 run 内 tool_call 数与事件数上升。agent 模式（playground `stream_agent`）不落 `AgentRunEvent`、不并发 commit，不受影响。
- **修复**（`llm_router/backend/app/agents/graph/runner.py` + `nodes.py`，已 docker cp 进 `ai_infra_backend` 容器 + 重启生效；宿主机工作树已改，待 rebuild image / 加 volume mount 持久化）：
  - `_run_graph_bg` 不再 mid-run `db.add(AgentRunEvent)` + `db.commit()`：事件先暂存内存 `staged: list[dict]`，live SSE 仍由 `run_registry.publish`（内存 buffer + queue）即时下发不受影响；run 收口时 `await db.commit()` 提交图写入（memory facts / write_run_log 状态 / audit），再用**独立会话** `_persist_run_events` 批量落 `agent_run_events`（run 行已由 load_config 提交，FK 安全；与图会话连接隔离，杜绝并发争用）。崩溃/取消路径也调 `_persist_run_events` 落已暂存事件（便于回放定位崩溃点），`_finalize_bg_error` 仍以高位 seq 补 error/final。
  - `nodes._load_config_general`：`db.add(run); await db.flush()` 后**立即 `await db.commit()`** 提交 run 行——让 `agent_runs` 行对其他会话即时可见（崩溃收口 `_finalize_bg_error` 能据此置 status=error；事件落库独立会话的 FK 也安全），consumer 不再需要在首事件处 commit graph 会话。
  - 行为变化：`agent_run_events` 表行从「边产边落」改为「run 收口批量落」；live SSE 不变（读 run_registry 内存），resume 端点 mid-run 重连会回放已落库事件（首事件 `load_config` 落库时间推迟到收口，mid-run 重连仅见 live buffer）——可接受，换取不再崩。`_EVENT_FLUSH_BATCH=25` 常量保留未删（无害）。
- **实测**（P2 五场景 8 次子任务跑 + SCM-01 物流子任务补跑，详见 A1 P2 段 + A5 SCM 段）：MFG-01（26 tool_call，MES+ERP+SCM，docx 41KB）/ QAL-01（20 tool_call，`getDefectRootCause(defect_id=DF20260101…)`×13，docx 41KB）/ SAL-01 sal-ops+sal-ecom（4/10 tool_call，`listReceivables(status=逾期)`/退换货转 svc-engineer 回流 SVC-01）/ HR-01 招聘+培训+薪酬（7/0/13 tool_call，`listResumesByPosition(position=P-SVC)`/vector RAG 8 hits/`listPayrolls(period=2026-06)`）/ SCM-01 物流子任务 scm-logistics（16 tool_call，SCM 到货 + ERP 采购/应付，docx 40KB）9 次子任务跑无一 error、无一 `another operation` 崩。修复前 MFG/QAL 重试必崩。
- **参考**：`docker logs ai_infra_backend` 2026-07-13 15:21–15:45（run 102–106 崩栈）；`app/agents/graph/runner.py:266` `async with async_session_factory() as db` + `:290` `db.add(AgentRunEvent)` + `:294` `if pending >= _EVENT_FLUSH_BATCH: await db.commit()`；`app/tools/executor.py:131` `db.add(ToolCallLog)` + `:144` `await db.flush()`。属 `llm_router/backend` 共享代码，starclothing 同受益；建议同步落 `../starclothing/KNOWN_ISSUES.md`。

---

## 与 starclothing 共享的后端问题（见 `../starclothing/KNOWN_ISSUES.md`）

以下问题在后端代码层，agileac 同款受益，详情见 starclothing KNOWN_ISSUES：

- **#1 path-param 占位符未替换**：`getStyle(style_code="P-RC-WALL-15")` 可能 404 `{style_code} not found`。agileac P0 三场景 §5.10/5.11 已记「agent 自主降级到 list 端点」非阻塞路径。starclothing 已修（commit 3602f20 PD-1 path-param），agileac 待确认同一修复是否覆盖。
- **#2 memory/extract JSON fence**：glm-5.2 把 JSON 包 markdown 围栏致 `facts:0`。starclothing `_parse_json_lenient` 已修，agileac 同后端受益。
- **#3 跨 agent 待办（agent_followups 表）未实施**：`CROSS_AGENT_HANDOFF_DESIGN.md` 设计了 `create_followup/resolve_followup` 工具 + `load_pending_followups` 节点，本期 SVC-01 8D 闭环待办仍只生成文字记录，不真正跨 agent 落地。
