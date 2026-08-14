# 场景归口用户与提示词索引

> 敏睿空调（agileac）demo 每个场景的**归口用户 + 提示词 + 模板/agent 绑定**单一事实源。
> 改提示词或归口用户时，先改这里 + 对应 `*_terminal_task.md` 的 §1 演示身份 / §3.4 提示词，
> 再落库（template 模式改 Agent `system_prompt` 后重跑 `seed_agileac_agents.py`）。
>
> - **归口用户**：终端以该业务用户登录跑场景（member 角色，无管理后台权限，密码统一 `12345678`）。
>   归口用户 → 部门映射见 `scripts/seed_agileac_org.py`（17 用户 / 11 部门 / 16 团队）。
> - **模式**：
>   - `template` = 四层架构：用户 composer 只写「目标+对象+技能 chip」（~140-216 字），persona/业务规则/输出骨架
>     由 Agent 模板 `system_prompt` 承载，任务 config 绑 `template_agent_id`（技能/模型留空从模板继承）。
>     详见 `SCENARIO_AUTHORING_GUIDE.md` 四层架构章。
>   - `playbook` = 老 long prompt：`system_prompt` 仍含 `AG-XXX` 代号 + 硬编码端点列表，**待四层化**（见 `KNOWN_ISSUES.md` A1）。
> - **agent slug / UUID**：见 `scripts/seed_agileac_agents.py` 的 `AGENTS` 列表；UUID 取自 `agents` 表（重跑 seed 不变）。
> - **归口用户执行约束**：每个场景由该场景归口用户登录终端跑——`scope_service.scope_filter` 始终含
>   `scope_type=="organization"`，故 org 级本体/数据接口对部门用户可见；部门级技能/RAG 按用户部门过滤。
>   Agent 行本身是组织级（无 scope 字段），scope 隔离在 Task/user 维度生效。

## 总览

| 场景 | 归口部门 | 归口用户 | 模式 | Agent slug | template_agent_id | 技能 | RAG | 模型 | 提示词 |
|---|---|---|---|---|---|---|---|---|---|
| SVC-01 售后故障诊断+8D | 售后服务部 | `svc-engineer` | **template** ✅ | agileac-svc-01-after-sales-diagnosis | c7aa5610-d06c-44ff-a9f9-fb3caa33a586 | svc-crm-mes-plm | 售后故障与维修知识库(dept) | glm-5.2 | ~200 字 composer |
| SAL-02 差旅报销进度问答 | 销售部·销售运营组 | `sal-ops` | **template** ✅ | agileac-sal-02-reimbursement-status | （seed 后取） | sal-crm-erp(dept) | 员工综合知识库(org) | glm-5.2 | ~20 字纯问题 |
| MKT-01 营销内容+培训课件 | 市场部 | `mkt-specialist` | **template** ✅ | agileac-mkt-01-marketing-content | af48fdf3-f9b4-42e9-88ab-690906a72d62 | mkt-plm-crm | 营销与竞品情报库(dept) | glm-5.2 | ~45 字纯业务请求 |
| RND-01 多语技术资料翻译 | 研发部·翻译组 | `rnd-translator` | **template** ✅ | agileac-rnd-01-translation | cd40f29c-1687-4735-9106-c965d8b980a9 | rnd-plm | 多语术语与海外资料库(team) | glm-5.2 | ~80 字原文+chip |
| PRD-01 产品参数核对+卖点 | 产品部 | `pm-product` | **template** ✅ | agileac-prd-01-product-params | 3f89c29c-c969-418f-ac73-e5b1d8a16128 | prd-plm-crm | 产品参数与卖点库(dept) | glm-5.2 | ~50 字 2 款产品 |
| MFG-01 工单进度+产能报表 | 生产制造部·排产组 | `mfg-planner` | **template** ✅ | agileac-mfg-01-production-report | a848552c-77d4-4196-894e-ba4319600acf | mfg-mes-erp-scm | 无 RAG | glm-5.2 | ~45 字纯业务请求 |
| QAL-01 质量数据+缺陷闭环 | 质量部·质量工程组 | `qal-engineer` | **template** ✅ | agileac-qal-01-quality-report | eb8e61bc-1a11-4949-b861-6452a16d88e0 | qal-mes-plm | 质量缺陷案例库(dept) | glm-5.2 | ~50 字三段报表+闭环 |
| SCM-01 供应商评审+采购物流 | 供应链部·采购+物流组 | `scm-buyer` / `scm-logistics` | **template** ✅ | agileac-scm-01-procurement-logistics | 19ef6052-fb0e-44c2-aca1-aa4567f17859 | scm-scm-erp | 供应商资质与历史表现库(dept) | glm-5.2 | ~70/55 字采购/物流分叉 |
| SAL-01 销售订单+电商退换货 | 销售部·销售运营+电商组 | `sal-ops` / `sal-ecom` | **template** ✅ | agileac-sal-01-sales-ecommerce | 52b17912-6291-4eb5-9fc1-1c257486af57 | sal-crm-erp | 无 RAG | glm-5.2 | ~40/35 字回款/退换货分叉 |
| FIN-01 对账+应收催办 | 财务部·对账+应收组 | `fin-accountant` / `fin-receivable` | **template** ✅ | agileac-fin-01-reconciliation-receivable | 53ca7af8-6937-4b1b-aede-8e5295962aaf | fin-erp-crm(跨5系统) | 无 RAG | glm-5.2 | ~60/35 字对账/应收分叉 |
| HR-01 招聘培训薪酬 | HR部·招聘+培训+薪酬组 | `hr-recruiter` / `hr-trainer` / `hr-compensation` | **template** ✅ | agileac-hr-01-hr-ops | 2d481531-d550-4718-ae0a-a84df5236bfd | hr-hrm | 岗位JD与简历评估库(team) + 员工综合知识库(org auto-load) | glm-5.2 | ~50/20/30 字招聘/培训/薪酬分叉 |

> ✅ = 11 场景全部四层化（P0 三 + P1 三 + P2 五已铺文档与模板 prompt）且**全部端到端实测通过**（短 composer + template_agent_id + 归口用户执行），实测详情见 `KNOWN_ISSUES.md` A5（P0+P1 六场景）+ A1 P2 段（P2 五场景 8 次子任务跑）。
> 架构注入路径全绿：P0+P1 中 RND-01 用 glm-5.2 跑通，SCM-01/FIN-01 用 deepseek-v4-pro 跑通；P2 五场景中 PRD-01 用 glm-5.2 跑通，MFG/QAL/SAL-01（2 子任务）/HR-01（3 子任务）用 deepseek-v4-pro 跑通——glm-5.2 在 QAL 第 4 轮 LLM 流式卡死（A5 类 key 不稳定），deepseek-v4-pro 稳定。A6 model_aliases 表 workaround 已应用；A8 asyncpg 共享会话并发争用已修（runner._run_graph_bg 事件暂存内存 + 独立会话批量落库 + load_config 提前提交 run 行）。
>
> SAL-02 的 template_agent_id UUID 在 seed 后取：`SELECT id FROM agents WHERE slug='agileac-sal-02-reimbursement-status'`。

---

## SVC-01 售后故障 AI 诊断与 8D 闭环

- 归口：售后服务部 · 工程师组 · `svc-engineer`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = c7aa5610-d06c-44ff-a9f9-fb3caa33a586`，skill_ids/model 留空继承 → agileac-svc-crm-mes-plm-query + glm-5.2）
- 技能：`/agileac-svc-crm-mes-plm-query`（从模板继承）｜RAG：售后故障与维修知识库（dept: after-sales）
- 文档：`svc_01_terminal_task.md`

### composer 提示词（直接复制，约 200 字）

```
对敏睿空调当前未闭环客诉做故障诊断 + 8D 闭环分析，重点 3 条：
CR-AG-2026-0001（P-RC-WALL-15 不制冷）、CR-AG-2026-0002（P-CC-VRV-360 通讯故障）、CR-AG-2026-0003（P-RC-CAB-30 漏水）。
扫所有 status != "已闭环" 客诉，按故障类型检索售后故障与维修知识库给根因/排查/配件/8D 待办。

/agileac-svc-crm-mes-plm-query
```

### 模板 system_prompt（859 字符，persona + 职责 + RAG cue + 8D 闭环规则 + 3 段输出骨架）
见 `scripts/seed_agileac_agents.py` 的 `agileac-svc-01-after-sales-diagnosis` 条目。落库：`docker cp seed_agileac_agents.py ai_infra_backend:/app/scripts/ && docker exec ai_infra_backend python3 /app/scripts/seed_agileac_agents.py`。

---

## SAL-02 差旅报销进度问答

- 归口：销售部 · 销售运营组 · `sal-ops`（密码 `12345678`）—— 11 场景中**唯一消费组织级 RAG** 的归口用户（员工综合知识库，全员可见）；复用销售部部门级技能 `agileac-sal-crm-erp-query`（已绑 ERP `listVouchers`），无组织级技能
- 模式：**template**（绑 `template_agent_id = <seed 后取>`，skill_ids/model 留空继承 → agileac-sal-crm-erp-query + glm-5.2）
- 技能：`/agileac-sal-crm-erp-query`（从模板继承，dept 级 sales）｜RAG：员工综合知识库（org，差旅报销段含 5 步流程 + 状态枚举）
- 文档：`sal_02_terminal_task.md`

### composer 提示词（直接复制，约 20 字——纯业务问题，编排归模板）

```
我上周提交的差旅报销走到哪一步了？

/agileac-sal-crm-erp-query
```

### 模板 system_prompt（persona + 知识库 cue + 端点 cue + 输出骨架）
见 `scripts/seed_agileac_agents.py` 的 `agileac-sal-02-reimbursement-status` 条目。落库：`docker cp seed_agileac_agents.py ai_infra_backend:/app/scripts/ && docker exec ai_infra_backend python3 /app/scripts/seed_agileac_agents.py`。

---

## MKT-01 营销内容与培训课件生成

- 归口：市场部 · 内容组 · `mkt-specialist`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = af48fdf3-f9b4-42e9-88ab-690906a72d62`，skill_ids/model 留空继承 → agileac-mkt-plm-crm + glm-5.2）
- 技能：`/agileac-mkt-plm-crm-query`（从模板继承）｜RAG：营销与竞品情报库（dept: marketing，按 chunk_type 分：selling_points/competitor/poster_template/courseware_template）
- 文档：`mkt_01_terminal_task.md`

### composer 提示词（直接复制，约 45 字——纯业务请求，编排归模板）

```
为敏睿空调 2 款主打产品生成一套营销内容与培训课件：P-RC-WALL-15（1.5 匹壁挂家用）、P-CC-VRV-360（360 型多联机商用）。

/agileac-mkt-plm-crm-query
```

### 模板 system_prompt（748 字符，persona + 职责 + 内容规则 + RAG cue + 3 段输出骨架）
见 `scripts/seed_agileac_agents.py` 的 `agileac-mkt-01-marketing-content` 条目。落库同上。

---

## RND-01 多语技术资料翻译与术语统一

- 归口：研发部 · 翻译组 · `rnd-translator`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = cd40f29c-1687-4735-9106-c965d8b980a9`，skill_ids/model 留空继承 → agileac-rnd-plm-query + glm-5.2）
- 技能：`/agileac-rnd-plm-query`（从模板继承）｜RAG：多语术语与海外资料库（team: rnd-translation）
- 文档：`rnd_01_terminal_task.md`

### composer 提示词（直接复制，约 80 字——翻译员工粘贴外文原文 + chip，无编排指令）

```
把这段英文技术资料中文化，统一行业术语并核对型号：
The DC inverter rotary compressor modulates refrigerant flow via the electronic expansion valve (EEV), achieving part-load COP up to 6.5. Standard configuration for P-RC-WALL-15 and P-CC-VRV-360, with R410A charge of 1.8 kg and 28 kg per module respectively.

/agileac-rnd-plm-query
```

### 模板 system_prompt（persona + 职责/自主规划端点 cue + RAG cue + 翻译规则 + 3 段输出骨架）
见 `scripts/seed_agileac_agents.py` 的 `agileac-rnd-01-translation` 条目。落库：`docker cp seed_agileac_agents.py ai_infra_backend:/app/scripts/ && docker exec ai_infra_backend python3 /app/scripts/seed_agileac_agents.py`。

> RND-01 无 `listPendingTranslations` 端点（README §5.3 列为新增但未实现）——待翻译资料由翻译员工直接粘贴进 composer，更贴近真实工作流；术语统一走 RAG，型号核对走 PLM `getStyle`/`listBoms`。

---

## PRD-01 产品参数核对与卖点提炼

- 归口：产品部 · `pm-product`（密码 `12345678`，产品部不分团队）
- 模式：**template**（绑 `template_agent_id = 3f89c29c-c969-418f-ac73-e5b1d8a16128`，skill_ids/model 留空继承 → agileac-prd-plm-crm-query + glm-5.2）
- 技能：`/agileac-prd-plm-crm-query`（PLM listStyles/getStyle/listBoms + CRM listCustomers/getCustomer/listOpportunities/listFollowUps）｜RAG：产品参数与卖点库（dept: product，6 款参数表 + 5 段式方法论 + 内部款/竞品对照）
- 文档：`prd_01_terminal_task.md`

### composer 提示词（直接复制，约 50 字——纯业务请求，编排归模板）

```
对敏睿空调 2 款主打产品做参数核对与卖点提炼：P-RC-WALL-15（1.5 匹壁挂家用）、P-CC-VRV-360（360 型多联机商用）。

/agileac-prd-plm-crm-query
```

### 模板 system_prompt（persona + 职责 + RAG cue + 5 段式卖点规则 + 输出骨架）
见 `scripts/seed_agileac_agents.py` 的 `agileac-prd-01-product-params` 条目。落库：`docker cp seed_agileac_agents.py ai_infra_backend:/app/scripts/ && docker exec ai_infra_backend python3 /app/scripts/seed_agileac_agents.py`。

> PRD-01 卖点不走 `getProductSellingPoints` 端点（未实现/未绑定）——卖点段来自 RAG「产品参数与卖点库」5 段式方法论 + 历史卖点 chunk，参数来自 PLM `getStyle`/`listBoms`，客户画像来自 CRM；输出交付市场部，MKT-01 接力。

---

## MFG-01 工单进度与产能报表

- 归口：生产制造部 · 排产计划组 · `mfg-planner`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = a848552c-77d4-4196-894e-ba4319600acf`，skill_ids/model 留空继承 → agileac-mfg-mes-erp-scm-query + glm-5.2）
- 技能：`/agileac-mfg-mes-erp-scm-query`（MES 工单/产线/OEE/WIP + ERP 物料库存 + SCM 到货/补单/交期快照）｜RAG：无
- 文档：`mfg_01_terminal_task.md`

### composer 提示词（直接复制，约 45 字——纯业务请求，编排归模板）

```
扫敏睿空调当前在制/逾期工单与产线产能，标出卡顿节点与缺料预警，输出催办清单。

/agileac-mfg-mes-erp-scm-query
```

### 模板 system_prompt（persona + 职责 + 排产与卡顿规则 + 输出骨架）
见 `scripts/seed_agileac_agents.py` 的 `agileac-mfg-01-production-report` 条目。落库同上。

> MFG-01 无 RAG——排产优先级（旺季家用优先）/缺料卡顿优先级（压缩机 M-COMP-GT-24K 单源长交期最高）/产能预警阈值（OEE<70% 标 ⚠️）由模板 system_prompt 承载（与 FIN-01 对账规则同范式）。A2 排产规则库待补，非阻塞。

---

## QAL-01 质量数据报表与缺陷闭环

- 归口：质量部 · 质量工程组 · `qal-engineer`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = eb8e61bc-1a11-4949-b861-6452a16d88e0`，skill_ids/model 留空继承 → agileac-qal-mes-plm-query + glm-5.2）
- 技能：`/agileac-qal-mes-plm-query`（MES 缺陷/工单/生产订单 + PLM 历史故障案例/产品款式）｜RAG：质量缺陷案例库（dept: quality，8 类缺陷 5W2H + 质检 SOP IQC/IPQC/OQC + 8D 闭环）
- 文档：`qal_01_terminal_task.md`

### composer 提示词（直接复制，约 50 字——纯业务请求，编排归模板）

```
对敏睿空调本期来料/制程/出货质量做报表，对未闭环缺陷做根因分析与 8D 闭环待办（催办生产/研发/采购）。

/agileac-qal-mes-plm-query
```

### 模板 system_prompt（persona + 职责 + RAG cue + 闭环规则 + 输出骨架）
见 `scripts/seed_agileac_agents.py` 的 `agileac-qal-01-quality-report` 条目。落库同上。

> QAL-01 跨码空间关键：MES 缺陷号 `DF` ≠ PLM 故障案例号 `DF-AG-`，跨系统查历史按 `product_code`/`defect_type` 关联勿直传 DF，否则 404；与 SVC-01 共用故障案例库方法论但归口部门不同（QAL 来料/制程/出货 vs SVC 客户报修后诊断）。

---

## SCM-01 供应商评审与采购物流一体化

- 归口：供应链部 · 采购组 `scm-buyer` / 物流组 `scm-logistics`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = 19ef6052-fb0e-44c2-aca1-aa4567f17859`，skill_ids/model 留空继承 → agileac-scm-scm-erp-query + glm-5.2）
- 技能：`/agileac-scm-scm-erp-query`（从模板继承）｜RAG：供应商资质与历史表现库（dept: supply）
- 文档：`scm_01_terminal_task.md`

### composer 提示词·采购子任务（`scm-buyer` 登录，约 70 字）

```
对敏睿空调 5 类核心配件做供应商评审与比价：压缩机 M-COMP-GT-24K、换热器 M-COND-FIN-30/M-EVAP-FIN-30、电子膨胀阀 M-EEV-15、制冷剂 M-RF-R410A。

/agileac-scm-scm-erp-query
```

### composer 提示词·物流子任务（`scm-logistics` 登录，约 55 字）

```
监管敏睿空调核心配件到货与仓储，标出延误与缺料预警（重点压缩机 M-COMP-GT-24K、蒸发器 M-EVAP-FIN-30）。

/agileac-scm-scm-erp-query
```

### 模板 system_prompt（persona + 职责双子任务 + RAG cue + 评审规则 + 输出骨架）
见 `scripts/seed_agileac_agents.py` 的 `agileac-scm-01-procurement-logistics` 条目。落库同上。

> SCM-01 无 `getSupplierQualifications` 端点（未实现）——供应商资质走 RAG 检索（供应商资质与历史表现库含 5 维度评分 + 黑名单规则），比价走 SCM `compareQuotations`，应付对账走 ERP `listPayables`。

---

## SAL-01 销售订单回款与电商退换货

- 归口：销售部 · 销售运营组 `sal-ops` / 电商组 `sal-ecom`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = 52b17912-6291-4eb5-9fc1-1c257486af57`，skill_ids/model 留空继承 → agileac-sal-crm-erp-query + glm-5.2）
- 技能：`/agileac-sal-crm-erp-query`（CRM 客户/商机/订单/客诉/应收 + ERP 凭证/生产成本只读）｜RAG：无
- 文档：`sal_01_terminal_task.md`

### composer 提示词·销售运营子任务（`sal-ops` 登录，约 40 字）

```
对敏睿空调逾期应收做催办，输出订单回款报表与催办清单、推送对象。

/agileac-sal-crm-erp-query
```

### composer 提示词·电商退换货子任务（`sal-ecom` 登录，约 35 字）

```
处理敏睿空调电商退换货客诉，输出内部处理清单，客诉转 svc-engineer 检测。

/agileac-sal-crm-erp-query
```

### 模板 system_prompt（persona + 职责双子任务 + 规则 + 输出骨架）
见 `scripts/seed_agileac_agents.py` 的 `agileac-sal-01-sales-ecommerce` 条目。落库同上。

> SAL-01 应收走 CRM `listReceivables`（ERP 无 listReceivables 端点，AGINV 发票号与 ERP 共享码空间）；退换货客诉（type=return）转 svc-engineer 检测闭环回流 SVC-01，不在本场景直调售后 agent；不对客户直接交互（B3 AI 语音客服不开放）。无 RAG。

---

## FIN-01 多系统对账与应收催办

- 归口：财务部 · 对账组 `fin-accountant` / 应收组 `fin-receivable`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = 53ca7af8-6937-4b1b-aede-8e5295962aaf`，skill_ids/model 留空继承 → agileac-fin-erp-crm-query + glm-5.2）
- 技能：`/agileac-fin-erp-crm-query`（从模板继承；**slug 历史命名，实际跨 5 系统**：ERP+MES+SCM+PLM+CRM 只读，P1 四层化时扩绑以支撑四方对账 + SSO）｜RAG：无
- 文档：`fin_01_terminal_task.md`

### composer 提示词·对账子任务（`fin-accountant` 登录，约 60 字）

```
对敏睿空调 2026-06 期做四方对账：ERP 凭证 ↔ MES 工单成本 ↔ SCM 报价 ↔ PLM 成本台账，标出差异率 >2% 的异常。

/agileac-fin-erp-crm-query
```

### composer 提示词·应收子任务（`fin-receivable` 登录，约 35 字）

```
催办敏睿空调逾期应收，输出催办清单与推送对象。

/agileac-fin-erp-crm-query
```

### 模板 system_prompt（persona + 职责双子任务 + 对账规则/SSO + 输出骨架）
见 `scripts/seed_agileac_agents.py` 的 `agileac-fin-01-reconciliation-receivable` 条目。落库同上。重跑 `seed_agileac_mock_connectors.py` 让 FIN 技能扩绑的 MES/SCM/PLM 端点生效。

> FIN-01 是 11 场景中唯一跨 4 系统对账 + SSO 演示场景（痛点 D）；对账规则（差异率 >2% 阈值）由模板 system_prompt 承载，无 RAG。

---

## HR-01 招聘培训薪酬一体化

- 归口：HR 部 · 招聘组 `hr-recruiter` / 培训组 `hr-trainer` / 薪酬组 `hr-compensation`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = 2d481531-d550-4718-ae0a-a84df5236bfd`，skill_ids/model 留空继承 → agileac-hr-hrm-query + glm-5.2）
- 技能：`/agileac-hr-hrm-query`（HRM 员工/部门/岗位/考勤/请假/薪酬/绩效/招聘/简历/会议只读）｜RAG：岗位JD与简历评估库（team: hr-recruiting，招聘子任务主绑）+ 员工综合知识库（org，培训制度子任务 auto-load）
- 文档：`hr_01_terminal_task.md`

### composer 提示词·招聘子任务（`hr-recruiter` 登录，约 50 字）

```
对敏睿空调售后工程师岗位 P-SVC 做简历评估，输出匹配度排序、推荐短名单、面试题与到岗催办。

/agileac-hr-hrm-query
```

### composer 提示词·培训制度子任务（`hr-trainer` 登录，约 20 字纯问题）

```
员工问：年假怎么请，跨年怎么清零？

/agileac-hr-hrm-query
```

### composer 提示词·薪酬子任务（`hr-compensation` 登录，约 30 字）

```
出敏睿空调 2026-06 期薪酬报表，按部门汇总应发/扣减/实发。

/agileac-hr-hrm-query
```

### 模板 system_prompt（persona + 职责三子任务 + RAG cue + 评估规则 + 输出骨架）
见 `scripts/seed_agileac_agents.py` 的 `agileac-hr-01-hr-ops` 条目。落库同上。

> HR-01 三子任务按归口员工切换：招聘用 team 级 JD 库（5 维度评估：学历15%/经验25%/行业25%/技能25%/软技能10%）；培训制度靠 org 级员工综合库 auto-load（含 HR 制度摘要，引用源标版本与生效日期）；薪酬用 HRM listPayrolls，凭证核对在 FIN-01 侧（本场景技能仅绑 HRM 不直查 ERP 凭证）。`shortlistResumes` 为 POST 不绑定，筛选用 `listResumesByPosition`（GET）+ LLM 评估排序。

---

## 演示速查（11 场景全四层化，可直接复制运行）

> 前置：glm-5.2 API key 已刷新（见 `KNOWN_ISSUES.md` A5）；mock 容器在跑；P1 三场景需重跑 `seed_agileac_mock_connectors.py`（FIN 扩绑 MES/SCM/PLM）+ `seed_agileac_ontology.py`（SCM identifiers）+ `seed_agileac_agents.py`（三 agent 四层 prompt）；P2 五场景需重跑 `seed_agileac_agents.py`（五 agent 四层 prompt 落库）。

| 场景 | 归口用户 | TPL_ID（template_agent_id） |
|---|---|---|
| SVC-01 | `svc-engineer` | `c7aa5610-d06c-44ff-a9f9-fb3caa33a586` |
| SAL-02 | `sal-ops` | seed 后取（`SELECT id FROM agents WHERE slug='agileac-sal-02-reimbursement-status'`） |
| MKT-01 | `mkt-specialist` | `af48fdf3-f9b4-42e9-88ab-690906a72d62` |
| RND-01 | `rnd-translator` | `cd40f29c-1687-4735-9106-c965d8b980a9` |
| SCM-01 | `scm-buyer` / `scm-logistics` | `19ef6052-fb0e-44c2-aca1-aa4567f17859` |
| FIN-01 | `fin-accountant` / `fin-receivable` | `53ca7af8-6937-4b1b-aede-8e5295962aaf` |
| PRD-01 | `pm-product` | `3f89c29c-c969-418f-ac73-e5b1d8a16128` |
| MFG-01 | `mfg-planner` | `a848552c-77d4-4196-894e-ba4319600acf` |
| QAL-01 | `qal-engineer` | `eb8e61bc-1a11-4949-b861-6452a16d88e0` |
| SAL-01 | `sal-ops` / `sal-ecom` | `52b17912-6291-4eb5-9fc1-1c257486af57` |
| HR-01 | `hr-recruiter` / `hr-trainer` / `hr-compensation` | `2d481531-d550-4718-ae0a-a84df5236bfd` |

```bash
# 通用：登录拿归口用户 token（换 username 即可）
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agileac","username":"svc-engineer","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 通用：建任务绑模板（换 TPL_ID + 标题）→ 跑短 composer（换 message）
TPL_ID="c7aa5610-d06c-44ff-a9f9-fb3caa33a586"   # SVC；其余见上表
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"SVC-01\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"<本文件对应场景的 §composer 提示词，含 /技能 chip>\",\"stream\":true}"
```

验证硬指标：SSE `load_config template:true` + `trace category=template` + 6 类 trace（FIN-01 无 rag，5 类）+ `tool_call` args 不全 `{}` + 输出分段上屏 + `generate_docx` 附件（详见各 `*_terminal_task.md` §7）。
