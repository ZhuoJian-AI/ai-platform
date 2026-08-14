# 场景归口用户与提示词索引

> Starclothing demo 每个场景的**归口用户 + 提示词 + 模板/agent 绑定**单一事实源。
> 改提示词或归口用户时，先改这里 + 对应 `*_terminal_task.md` 的 §1 演示身份 / §3.4 提示词，
> 再落库（template-mode 场景改 Agent `system_prompt`；playbook 场景改 composer 文本）。
>
> - **归口用户**：终端以该业务用户登录跑场景（member 角色，无管理后台权限）。
> - **模式**：
>   - `template` = 四层架构：用户 composer 只写「目标+对象+技能 chip」（~140-216 字），
>     persona/policy/输出骨架由 Agent 模板 `system_prompt` 承载，任务 config 绑
>     `template_agent_id`（技能/模型留空从模板继承）。详见 `pd3_terminal_task.md §5.17`。
>   - `playbook` = 老 fat prompt：composer 粘贴完整 persona+执行步骤+输出格式（~2000 字），
>     config 显式带 `skill_ids` / `model_alias`，不绑 `template_agent_id`。
> - **agent slug**：见 `scripts/seed_starclothing_agents.py` 的 `AGENTS` 列表。
> - 归口用户 → 部门映射见 `scripts/reorg_starclothing_scope.py` 的 `SCENARIO_DEPTS`。

## 总览

| 场景 | 归口部门 | 归口用户 | 模式 | Agent slug | 技能 | 模型 | 提示词长度 |
|---|---|---|---|---|---|---|---|
| PD-1 逾期订单风险汇总与推送 | 开发部 | `dev-lead` | **template** | `starclothing-pd1-product-monitor` | plm | `claude-sonnet-4` | ~70 字 composer |
| PD-2 关键面料成本交期产能测算与异动检测 | 设计部 | `fabric-dev` | **template** | `starclothing-pd2-fabric-library` | scm | `claude-opus-4` | ~140 字 composer |
| PD-3 新品缺陷风险预警与闭环待办 | 品控部 | `qc-lead` | **template** | `starclothing-pd3-defect-closure` | plm + RAG 缺陷库 | `claude-opus-4` | ~100 字 composer |
| SC-1 来料批次物料校验与异常回写 | 供应链部 | `supply-lead` | **template** | `starclothing-sc1-material-validation` | scm + mes | `claude-sonnet-4` | ~170 字 composer |
| SC-2 下周工单产线排程与风险提示 | 生产部 | `prod-lead` | **template** | `starclothing-sc2-factory-scheduling` | mes + scm | `claude-opus-4` | ~100 字 composer |
| SC-3 跨系统单据对账与差异闭环 | 财务部 | `finance-lead` | **template** | `starclothing-sc3-reconciliation` | erp+mes+crm | `claude-opus-4` | ~90 字 composer |
| SC-4 采购报价比对与成本台账建议 | 商品部 | `merch-lead` | **template** | `starclothing-sc4-price-comparison` | scm + erp | `claude-sonnet-4` | ~120 字 composer |

> **7 个终端场景（PD-1/2/3、SC-1/2/3/4）均已转 template 模式**：agent `system_prompt` 承载
> persona / policy / 输出骨架，用户 composer 只写「目标 + 对象 + 技能 chip」（v7d 起验证，
> tool_calls 0 占位符失败、输出段齐全 + docx 闭环）。7 份 `*_terminal_task.md` 的 §3.3/§3.4/
> §3.6/§6 均已同步为 template 绑定 + 短 composer 样式。SC-3 财务部无领域本体（仅 Cross 4），
> 对账靠数据接口目录 + 公共字段关联。SC-4 商品部有 SCM 本体（proxy 复制）但无 ERP 领域本体，
> ERP 侧靠数据接口目录 + 公共字段（`material_code` / `supplier_code`）关联。

---

## PD-1 逾期订单风险汇总与推送

- 归口：开发部 · `dev-lead`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = starclothing-pd1-product-monitor`，skill_ids/model 留空继承 → plm + claude-sonnet-4）
- 技能：`/starclothing-plm-query`（从模板继承）
- 文档：`pd1_terminal_task.md`

### composer 提示词（直接复制，约 70 字）

```
扫描当前已逾期/7天内将逾期的订单，按款号汇总当前阶段、责任人、风险等级，给出推送对象和补救建议。

/starclothing-plm-query
```

### 模板 system_prompt（512 字符，承载 persona + 职责 + 跨部门协同规则 + 输出骨架）
见 `scripts/seed_starclothing_agents.py` 的 `starclothing-pd1-product-monitor` 条目；落库方式见 §6。模板要点：归口产品开发部；全流程监管（按款号汇总阶段/责任人/风险等级/推送对象/补救建议）；跨部门协同规则（开发部无缺陷 RAG 权限，QC=FAIL 标注「需品控部协同出具规避要点」）；输出两段（全流程进度汇总表 / 逾期款号推送清单）；「结合本体与数据接口目录自主规划最少端点集」。

---

## PD-2 关键面料成本交期产能测算与异动检测

- 归口：设计部 · `fabric-dev`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = starclothing-pd2-fabric-library`，skill_ids/model 留空继承 → scm + claude-opus-4）
- 技能：`/starclothing-scm-query`（从模板继承）
- 文档：`pd2_terminal_task.md`

### composer 提示词（直接复制，约 140 字）

```
对当前在用的 4 款关键面料做实时成本/交期/产能综合测算 + 异动检测：
M-WOOL-DBL-360（双面呢 360g）、M-SHELL-3L-150（三层压胶）、M-TC-180（涤棉）、M-FLEECE-280（摇粒绒）。

/starclothing-scm-query
```

### 模板 system_prompt（714 字符，承载 persona + 实时性/异动 policy + 3 段输出骨架）
见 `scripts/seed_starclothing_agents.py` 的 `starclothing-pd2-fabric-library` 条目；落库方式见 §6（手工 API 解析 template_agent_id 后绑 config）。

---

## PD-3 新品缺陷风险预警与闭环待办

- 归口：品控部 · `qc-lead`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = starclothing-pd3-defect-closure`，skill_ids/model 留空继承 → plm + claude-opus-4；v7d2 回跑 tool_calls 11 0 失败、RAG 5 hits）
- 技能：`/starclothing-plm-query` + RAG 服装缺陷知识库（强依赖，须跑 `seed_starclothing_defect_rag.py`）
- 文档：`pd3_terminal_task.md`

### composer 提示词（直接复制，约 100 字）

```
新品开发评审会：款号 P-FW2026-002 压胶冲锋衣即将进入大货试产，款号 P-FW2026-001 双面呢大衣即将进入量产。请基于历史缺陷知识库做风险预警。

/starclothing-plm-query
```

### 模板 system_prompt（796 字符，承载 persona + RAG 检索 cue + 闭环待办规则 + 输出骨架）
见 `scripts/seed_starclothing_agents.py` 的 `starclothing-pd3-defect-closure` 条目；落库方式见 §6。模板要点：归口品质保证部；检索服装缺陷知识库（8 类缺陷关键词示例 + 品类 fallback）；feasibility_log 闭环待办规则（仅覆盖成本/交期/产能三维度，缺陷预防措施未留痕项标注待办提示监管 Agent 跟进）；输出四段（风险预警表/评审必查项/闭环验证建议/闭环待办）；「结合本体与数据接口目录自主规划最少端点集」。

---

## SC-1 来料批次物料校验与异常回写

- 归口：供应链部 · `supply-lead`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = starclothing-sc1-material-validation`，skill_ids/model 留空继承 → scm+mes + claude-sonnet-4）
- 技能：`/starclothing-scm-query` + `/starclothing-mes-query`（从模板继承）
- 文档：`sc1_terminal_task.md`

### composer 提示词（直接复制，约 110 字）

```
本周面料/辅料到货批次做物料校验（BOM 一致性 / 数量 / 规格 / 供应商资质），异常项闭环回写 SCM。

/starclothing-scm-query
/starclothing-mes-query
```

> composer 只写目标 + 技能 chip，**不含示例码 / 工单号锚点**——具体待校验物料与工单号由
> agent 据 SCM 本体 identifiers（`MV-` validation_id、`WO` work_order_no、跨码空间经
> `listWorkOrders` 查真实 won）+ TOOL_STRATEGY 从 `listMaterialValidations` /
> `listWorkOrders` 自主发现。原版 composer 曾硬编码一个从 ontology 示例搬来的虚构工单
> 号锚点（mock MES 实际用 `WO` 前缀、无 `XWO`），agent 照搬调 `getWorkOrder` 必然 404
> ——示例码属本体层，不进 composer（详见 `pd2_terminal_task.md` §3.4 四层架构）。

### 模板 system_prompt（672 字符，承载 persona + 流程角色 + 校验规则 + 输出骨架）
见 `scripts/seed_starclothing_agents.py` 的 `starclothing-sc1-material-validation` 条目；落库方式见 §6。模板要点：归口供应链+品质保证部；校验规则（缺数>5%退货、超数>3%让步、规格克重门幅缩率色牢度、供应商资质有效期 ISO/Oeko-Tex/重金属、闭环回写 createMaterialValidation）；输出三段（校验结果表 / 待处理项 / 闭环汇总）；「结合本体与数据接口目录自主规划最少端点集」。

---

## SC-2 下周工单产线排程与风险提示

- 归口：生产部 · `prod-lead`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = starclothing-sc2-factory-scheduling`，skill_ids/model 留空继承 → mes+scm + claude-opus-4）
- 技能：`/starclothing-mes-query` + `/starclothing-scm-query`（从模板继承）
- 文档：`sc2_terminal_task.md`

### composer 提示词（直接复制，约 100 字）

```
下周排产：列出所有 pending 工单，结合产能日历、面料到货计划、补货建议做产线排程 + 风险提示。

/starclothing-mes-query
/starclothing-scm-query
```

### 模板 system_prompt（655 字符，承载 persona + 排产输入 + 排产逻辑 5 条 + 输出骨架）
见 `scripts/seed_starclothing_agents.py` 的 `starclothing-sc2-factory-scheduling` 条目；落库方式见 §6。模板要点：归口生产计划+供应链协同部；排产输入（MES pending 工单/产线 + SCM 产能日历/面料到货/补货建议）；排产逻辑 5 条（面料优先级/产线占用/交期优先级/补货节奏/瓶颈识别）；输出四段（排程表/风险提示/产线负载/补货建议）；「结合本体与数据接口目录自主规划最少端点集」。原 playbook 的「path-param bug 降级」指引已删（bug 随 Issue #1 根治，agent 遇 404 自主降级 list 端点）。

---

## SC-3 跨系统单据对账与差异闭环

- 归口：财务部 · `finance-lead`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = starclothing-sc3-reconciliation`，skill_ids/model 留空继承 → crm+mes+erp + claude-opus-4）
- 技能：`/starclothing-crm-query` + `/starclothing-mes-query` + `/starclothing-erp-query`（从模板继承）
- 文档：`sc3_terminal_task.md`（**v7d 起从 shell 模式转终端任务方式**，旧 `sc3_reconciliation.sh` 保留作历史对照）

### composer 提示词（直接复制，约 90 字）

```
本月单据对账：CRM 销售订单 ↔ MES 工单 ↔ ERP 生产成本/应收/应付，输出对账差异 + 异常清单 + 闭环待办。

/starclothing-crm-query
/starclothing-mes-query
/starclothing-erp-query
```

### 模板 system_prompt（649 字符，承载 persona + 对账输入 + 对账逻辑 5 条 + 输出骨架）
见 `scripts/seed_starclothing_agents.py` 的 `starclothing-sc3-reconciliation` 条目；落库方式见 §6。模板要点：归口财务+供应链协同部；对账输入（CRM 销售订单+客诉+应收 / MES 工单 / ERP 生产成本+应付付款状态）；对账逻辑 5 条（销售↔工单按 work_order_no 差异>2%、工单↔成本超支>5%、销售↔应收、应付付款状态、客诉↔工单）；输出四段（对账结果表/异常清单/闭环待办/汇总）；「结合数据接口目录自主规划最少端点集」。

> ⚠️ SC-3 两处特殊点：(1) 财务部**无领域本体**（仅 org 级 Cross 4 个，无 ERP/CRM/MES identifiers.md），对账靠数据接口目录 43 端点 + 跨系统公共字段（`work_order_no` / 销售订单号）关联；(2) 原 shell playbook 误引的**不存在端点 `listPayments` 已删**，对账逻辑 4 改用 `listPayables` 付款状态字段核对。

---

## SC-4 采购报价比对与成本台账建议

- 归口：商品部 · `merch-lead`（密码 `12345678`）
- 模式：**template**（绑 `template_agent_id = starclothing-sc4-price-comparison`，skill_ids/model 留空继承 → scm + erp + claude-sonnet-4）
- 技能：`/starclothing-scm-query` + `/starclothing-erp-query`（从模板继承）
- 文档：`sc4_terminal_task.md`（**v7e 起从 shell 模式转终端任务方式**，旧 `sc4_price_ledger.sh` 保留作历史对照）

### composer 提示词（直接复制，约 120 字）

```
本季度面料/辅料采购报价比对：对 M-WOOL-DBL-360（双面呢）、M-SHELL-3L-150（三层压胶）、M-ZIP-YKK-5（YKK 拉链）做多供应商比价 + 历史异动 + 成本台账建议。

/starclothing-scm-query
/starclothing-erp-query
```

### 模板 system_prompt（917 字符，承载 persona + 比对输入 + 比对逻辑 5 条 + 输出骨架）
见 `scripts/seed_starclothing_agents.py` 的 `starclothing-sc4-price-comparison` 条目；落库方式见 §6（手工 API 解析 template_agent_id 后绑 config）。模板要点：归口商品部（采购定价+成本协同）；比对输入（SCM 报价+历史报价 / ERP 物料档案 unit_cost+采购订单+应付）；比对逻辑 5 条（多供应商比价综合评分 40/30/30、历史比价波动>5%、标准成本比价差异>3%、账期评估、成本台账建议）；输出四段（比价表/异动清单/成本台账建议/汇总）；「结合本体与数据接口目录自主规划最少端点集」。

> ⚠️ SC-4 两处特殊点：(1) 商品部**无 ERP 领域本体**（有 SCM 本体 proxy 复制含 identifiers `M-`/`XS-` 码空间映射，但无 ERP identifiers.md），ERP 侧靠数据接口目录参数 schema + 返回数据公共字段（`material_code` / `supplier_code`）关联；(2) 原 shell playbook + 老 prompt 误引的**不存在端点 `listCostLedger` 已删**，比对逻辑 5 改为「成本台账建议」输出，标准成本取自 `listMaterials.unit_cost`，实际采购单价取自 `listPurchaseOrders`，应付付款状态取自 `listPayables`。

---
