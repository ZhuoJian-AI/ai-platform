# 敏睿空调 · 员工 vibe working AI 痛点场景 Demo 设计

> 本设计基于《部门AI痛点需求汇总》——脱敏后合并的两个空调业务主体调研：**公司A（销售型，覆盖家用+商用空调销售/电商/经销渠道）+ 公司B（制造型，覆盖家用+商用空调研发/生产/售后）**，共 12 部门 / 8 痛点领域 / 16 项差异化需求。
>
> 「敏睿空调」（slug = `agileac`）按**纵贯家用+商用空调研发/制造/销售/服务的全产业链集团**建模——既是制造商也是销售商。
>
> ⚠️ **核心约束（4 条）**：
> 1. **全部终端任务方式**——8（实为 11）场景统一以业务用户身份登录 `/agileac/terminal`，新建任务、配置 `glm-5.2` + `craft`、/-mention 选技能、写提示词、运行。**无 shell 脚本**。
> 2. **员工 vibe working 视角**——AI 是员工的副驾驶，**不对客户直接交互**。剔除 B3 智能电话客服（AI 语音接听客户来电）+ A 智能问答中"客服电话/线上咨询重复应答"对外部分。
> 3. **场景按部门/团队边界划分，不跨部门合并**——同部门多个组可合一场景（如市场部内容组+竞情组+培训组合一），但跨部门工作流不合并到同一场景。每场景对应一个归口部门/团队 + 一个归口员工。
> 4. **资源 scope 分级**——数据接口/本体/知识库/技能默认**部门级** scope；仅全员共享的（如 Cross 跨系统本体、员工综合问答知识库）放**组织级**；团队专属资源放**团队级**。用户名**不用邮箱形式**（用 `it-specialist` / `rnd-translator` 等），密码统一 **`12345678`**。

---

## 0. 业务背景

### 0.1 行业定位

| 维度 | 取值 |
|---|---|
| 组织名称 | 敏睿空调 |
| slug | `agileac` |
| 行业 | 家用 + 商用空调全产业链（研发/制造/销售/服务） |
| 业务边界 | 自研产品（家用壁挂/柜机/移动 + 商用多联机/风管机/模块机组）+ 配件（压缩机/换热器/阀件/制冷剂）+ 经销/电商渠道 + 工程项目 + 售后服务网络 |
| 业务主体映射 | 覆盖调研中公司A（销售侧）+ 公司B（制造侧）全部员工侧痛点（剔除 B3 对外客服） |

### 0.2 产品线（mock 内置款号）

| 类别 | 款号 | 中文名 | 工单示例 |
|---|---|---|---|
| 家用·壁挂 | `P-RC-WALL-15` | 1.5 匹壁挂式家用空调 | `AWO20260101` |
| 家用·柜机 | `P-RC-CAB-30` | 3 匹立柜式家用空调 | `AWO20260105` |
| 家用·移动 | `P-RC-MOVE-10` | 1 匹移动空调 | `AWO20260108` |
| 商用·多联机 | `P-CC-VRV-360` | 360 型家用商用多联机外机 | `AWO20260210` |
| 商用·风管机 | `P-CC-DUCT-50` | 50 型商用风管机 | `AWO20260215` |
| 商用·模块机 | `P-CC-CHILL-100` | 100 RT 模块冷水机组 | `AWO20260220` |
| 配件·压缩机 | `M-COMP-GT-24K` | 24K 转子压缩机 | — |
| 配件·冷凝器 | `M-COND-FIN-30` | 30 平方英寸翅片冷凝器 | — |
| 配件·蒸发器 | `M-EVAP-FIN-30` | 30 平方英寸翅片蒸发器 | — |
| 配件·电子膨胀阀 | `M-EEV-15` | 15 步电子膨胀阀 | — |
| 配件·制冷剂 | `M-RF-R410A` | R410A 环保冷媒 | — |

### 0.3 跨系统数据闭环（mock 内置，供跨部门按授权访问）

- ERP `production_costs.work_order_no` → MES `work_orders.work_order_no`
- CRM `complaints.work_order_no` → MES `work_orders.work_order_no`
- PLM `defect_history.work_order_no` → MES `work_orders.work_order_no`
- SCM `quotations.material_code` → ERP `materials.code` → PLM `bom.material_code`
- HRM `recruitments.position_id` → CRM `opportunities.owner_id`
- ERP `payables.supplier_code` → SCM `suppliers.code`

> 跨部门访问通过数据接口 scope 授权实现，**不通过场景合并实现**。如售后工程师要调 MES 工单：MES 数据接口对售后服务部开放只读权限，技能 `agileac-svc-mes-query` 绑定该接口。

---

## 1. 痛点 → 场景映射（按部门归类）

### 1.1 场景编码规则

`AG-<DEPT>-<SEQ>` —— `AG` = 敏睿空调 AgileAC，`<DEPT>` = 部门三字母代号，`<SEQ>` = 该部门内场景序号。

| 部门代号 | 部门 | 团队（同部门可合并场景） |
|---|---|---|
| `RND` | 研发部 | 翻译组 / 结构组 / 电气组 |
| `PRD` | 产品部 | （不分团队，全员产品专员） |
| `MFG` | 生产制造部 | 排产计划组 / 总装车间 / 测试车间 |
| `QAL` | 质量部 | 质量工程组 |
| `SCM` | 供应链部 | 采购组 / 物流组 |
| `SAL` | 销售部 | 销售运营组 / 电商组 / 经销渠道组 |
| `SVC` | 售后服务部 | 工程师组 |
| `MKT` | 市场部 | 内容组 / 竞情组 / 培训组 |
| `FIN` | 财务部 | 对账组 / 应收组 / 应付组 |
| `HR`  | 人力资源部 | 招聘组 / 培训组 / 薪酬组 |
| `IT`  | 信息技术部 | 系统运维组 / AI 应用组 |

### 1.2 共性 6 痛点 → 场景归属（按部门边界拆）

| 共性痛点 | 涉及部门 | 归入场景（按部门拆分） | 拆分理由 |
|---|---|---|---|
| **A** 智能问答与知识库（仅员工内部） | 9 | SAL-02（销售员工报销进度问答）+ HR-01（HR 制度子任务）+ PRD-01（产品参数）+ SVC-01（技术 FAQ） | 不同部门员工问不同问题，知识库按部门分；员工日常问报销走全员问答知识库 |
| **B** 数据录入与报表自动化 | 9 | MFG-01（生产报表）+ SCM-01（采购物流报表）+ SAL-01（销售回款报表）+ FIN-01（财务对账）+ HR-01（薪酬报表）+ QAL-01（质量报表） | 报表用途分散在 6 部门，按部门拆场景 |
| **C** 文档/合同智能处理 | 7 | FIN-01（财务单据）+ SCM-01（报价审核）+ RND-01（技术资料核对）+ PRD-01（参数核对）+ QAL-01（质检报告） | 文档类型按部门归属分 |
| **D** 系统集成与体验优化 | 4 | FIN-01（ERP↔MES↔SCM↔PLM 对账，跨系统免登调用） | 财务跨系统对账在财务部，兼带跨系统免登调用演示 |
| **E** 审批流与流程催办 | 8 | SVC-01（8D 闭环催办）+ FIN-01（应收催办）+ HR-01（到岗催办）+ MFG-01（生产卡顿催办） | 催办对象按归口部门拆 |
| **F** AI 内容生成 | 4 | MKT-01（海报+视频+课件+竞品内容） | 全在市场部 3 个组，合一 |

### 1.3 公司A（销售侧）差异化 → 场景归属

| A 侧需求 | 归口部门 | 归入场景 | 落地方式 |
|---|---|---|---|
| A1 大量内容生成（海报/视频） | 市场部 | MKT-01 | agent 调 `generate_docx`，输入产品参数+卖点→输出海报文案+视频脚本 |
| A2 产品卖点提取 + 竞品对比 | 产品部 + 市场部 | PRD-01（产品部提取）+ MKT-01（市场部竞品对比） | 产品部提炼卖点→市场部用，分两个场景 |
| A3 简历筛选 + 招聘辅助 | 人力资源部 | HR-01 | agent 调 HRM `listRecruitments` + 岗位 JD RAG，输出匹配度排序 |
| A4 电商退换货 + 仓储物流 | 销售部（电商组）+ 供应链部（物流组） | SAL-01（电商退换货内部处理）+ SCM-01（仓储到货） | 退换货属员工内部处理，分两部门拆 |
| A5 AI 做课（大纲→PPT→考试） | 市场部·培训组 | MKT-01 | agent 按"大纲→课件→考题"三段输出，调 `generate_docx` 打包 |
| A6 供应商筛选 + 比价 | 供应链部 | SCM-01 | agent 调 SCM `compareQuotations` + 供应商资质 RAG |

### 1.4 公司B（制造侧）差异化 → 场景归属

| B 侧需求 | 归口部门 | 归入场景 | 落地方式 |
|---|---|---|---|
| B1 英/日技术资料翻译 | 研发部·翻译组 | RND-01 | agent 调术语词典 RAG + 海外资料 RAG，输出中文化 + 术语对照 |
| B2 售后故障 AI 诊断 | 售后服务部 | SVC-01 | agent 调 CRM 客诉（按授权）+ MES 工单 + 故障 RAG + 维修手册 RAG |
| ~~B3 智能电话客服（语音）~~ | — | **不纳入** | AI 语音接听客户来电属**对外服务**，违反约束 2 |
| B4 竞品情报自动采集 | 市场部·竞情组 | MKT-01 | 用竞品情报 RAG 模拟已爬取归档的资料，agent 检索+对比+出报告 |
| B5 CRM/ERP 登录体验 | 财务部 | FIN-01 | 跨系统对账时演示终端一次登录免登调 ERP/MES/SCM/PLM，员工不再受困频繁登录 |
| B6 项目跟踪 + 会议助理 | 各部门 PM 自管 | 不单独立场景 | PM 会议属各部门 vibe working，不集中到一个场景；IT 部作平台运维方支撑 |

> **覆盖核对**：调研 8 痛点领域 + A 侧 6 项 + B 侧 6 项，共 20 项。本期实现 18 项（剔除 B3 对外客服 + B6 集中场景改为 IT 平台支撑），11 场景覆盖全部"员工侧"痛点。

---

## 2. 演示矩阵（11 场景，全部终端任务方式）

| 场景编号 | 名称 | 归口部门/团队 | 归口用户 | 绑定技能（部门级） | RAG（scope） | 覆盖痛点 |
|---|---|---|---|---|---|---|
| **RND-01** | 多语技术资料翻译与术语统一 | 研发部·翻译组 | `rnd-translator` | `agileac-rnd-plm-query` | 多语术语与海外资料库（团队级） | B1 + C 技术核对 |
| **PRD-01** | 产品参数核对与卖点提炼 | 产品部 | `pm-product` | `agileac-prd-plm-crm-query` | 产品参数与卖点库（部门级） | A2 + C 参数核对 |
| **MFG-01** | 工单进度与产能报表 | 生产制造部·排产计划组 | `mfg-planner` | `agileac-mfg-mes-erp-scm-query` | —（无 RAG） | B 生产报表 + E 卡顿催办 |
| **QAL-01** | 质量数据报表与缺陷闭环 | 质量部 | `qal-engineer` | `agileac-qal-mes-plm-query` | 质量缺陷案例库（部门级） | B 质量报表 + C 质检报告 + 缺陷闭环 |
| **SCM-01** | 供应商评审与采购物流一体化 | 供应链部·采购组+物流组 | `scm-buyer` / `scm-logistics` | `agileac-scm-scm-erp-query` | 供应商资质与历史库（部门级） | A6 + B 采购物流报表 + C 报价审核 + A4 仓储 |
| **SAL-01** | 销售订单回款与电商退换货 | 销售部·销售运营组+电商组 | `sal-ops` / `sal-ecom` | `agileac-sal-crm-erp-query` | —（无 RAG） | B 销售回款 + A4 退换货内部 + E 应收催办 |
| **SVC-01** | 售后故障 AI 诊断与 8D 闭环 | 售后服务部·工程师组 | `svc-engineer` | `agileac-svc-crm-mes-plm-query` | 售后故障与维修知识库（部门级） | B2 + C + E 8D 催办 + A 技术 FAQ |
| **MKT-01** | 营销内容生成与培训课件自动化 | 市场部·内容组+竞情组+培训组 | `mkt-specialist` | `agileac-mkt-plm-crm-query` | 营销与竞品情报库（部门级，含 3 类 chunk） | F + A1 + A2 竞品 + A5 做课 + B4 |
| **FIN-01** | 多系统对账与应收催办 | 财务部·对账组+应收组 | `fin-accountant` / `fin-receivable` | `agileac-fin-erp-crm-query` | —（无 RAG，跨 5 系统只读） | B 录入 + C 对账 + D 集成 + E 应收催办 |
| **HR-01** | 招聘培训薪酬一体化 | 人力资源部·招聘组+培训组+薪酬组 | `hr-recruiter` / `hr-trainer` / `hr-compensation` | `agileac-hr-hrm-query` | 岗位JD库（团队级，招聘组）+ 员工综合知识库（组织级，培训制度 auto-load） | A3 + A 制度问答 + B 薪酬报表 + E 到岗催办 |
| **SAL-02** | 差旅报销进度问答 | 销售部·销售运营组 | `sal-ops` | `agileac-sal-crm-erp-query` | 员工综合知识库（组织级，多源 chunk） | A 全员问答（知识库）+ 先 RAG 后接口 |

> **11 场景全部终端任务方式**：业务用户登录 `/agileac/terminal`，新建任务、配置 `glm-5.2` + `craft`、/-mention 选技能、写提示词、运行。所有场景定位为**员工 vibe working 辅助**——AI 副驾驶，不对客户直接交互。
>
> **同部门多组场景合并**：SCM-01 / SAL-01 / MKT-01 / FIN-01 / HR-01 含多组子任务，但都在同一部门内，技能与数据接口同源，可合一场景；演示时按子任务切归口员工验证 scope 隔离。
>
> **部门↔场景非 1:1**：销售部含 2 场景（SAL-01 订单回款、SAL-02 报销进度问答，同归 `sal-ops`）；信息技术部不设对外场景，作平台运维方（`it-specialist` 留作运维用户，非演示场景）。

---

## 3. 前置条件

### 3.1 平台已部署

- Docker Compose 起 `ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）+ `ai_infra_postgres`（pgvector）。
- 容器互联：`ai_infra_backend` 容器内访问 mock 走 `http://ai_infra_mock:8010`；主机访问后端走 `http://localhost:8000`。

### 3.2 LLM Provider 已配

在管理端「敏睿空调」组织 → LLM Provider 页配至少一个可用 provider：
- **Anthropic Claude**（`claude-opus-4` / `claude-sonnet-4` / `claude-haiku-4`）
- **OpenAI**（`gpt-4o` / `gpt-4o-mini`）
- **DeepSeek**（`deepseek-chat` / `deepseek-reasoner`）
- **智谱**（`glm-5.2`，终端 demo 默认）
- **阿里云通义**（`text-embedding-v4`，用于 RAG embedding）

确保 `glm-5.2` / `claude-sonnet-4` 等真实模型 id 在 provider 的 `supported_models` 里且路由策略（`model_pattern` 如 `glm-*` / `claude-*`）指向可用 provider。embedding 通道：org 必须配一个 OpenAI 兼容的 embedding provider，否则 RAG trace 显示 `retriever=keyword_fallback`。

### 3.3 超管账号

- 演示用 `root / Sjp19831209`（super admin）仅用于初始化 seed + 配置；演示场景本身**不用超管 token**，全部走业务用户终端任务。
- 组织管理员 `admin / 12345678`（role=admin，限于敏睿空调组织内管理）。

### 3.4 mock 多租户

敏睿空调在 mock 中新增 `agileac` 租户（与 `minrui` / `starclothing` 并列）。6 个 mock 系统均需支持 `agileac` tenant：

| Mock 系统 | 端口 | 路径前缀 | agileac API Key | 用途 |
|---|---|---|---|---|
| PLM | 8010 | `/plm` | `plm-agileac-demo-key` | 产品/BOM/工程变更/技术资料/故障案例/成本台账/卖点 |
| SCM | 8010 | `/scm` | `scm-agileac-demo-key` | 供应商/报价/产能/到货/补货/交期快照/资质 |
| ERP | 8010 | `/erp` | `erp-agileac-demo-key` | 物料/采购/库存/应付应收/凭证/成本中心 |
| MES | 8010 | `/mes` | `mes-agileac-demo-key` | 工单/产线/设备/OEE/缺陷/在制品 |
| CRM | 8010 | `/crm` | `crm-agileac-demo-key` | 客户/商机/报价/销售订单/客诉/应收 |
| HRM | 8010 | `/hrm` | `hrm-agileac-demo-key` | 员工/部门/考勤/请假/薪酬/绩效/招聘/会议 |

> ⚠️ mock API Key 是**组织级**（一把 key 全 agileac 用），但平台侧 DataInterface / SkillFolder / RAG / Ontology 按**部门/团队级** scope 授权——同样的 mock 端点，不同部门技能绑不同的子集。

---

## 4. 组织 / 部门 / 团队 / 用户

### 4.1 组织

| 字段 | 值 |
|---|---|
| name | 敏睿空调 |
| slug | `agileac` |
| description | 家用+商用空调全产业链 AI 应用 demo——11 场景按部门边界划分，员工 vibe working 辅助 |
| rate_limit_rpm | 1500 |
| rate_limit_tpm | 800_000 |
| budget_cap_usd | 3000 |
| settings | `{"locale": "zh-CN", "industry": "hvac"}` |

### 4.2 部门（11 个，对应调研的 11 个有场景的部门）

| slug | 名称 | 代号 | 归口场景 | rate_limit_rpm | budget_cap_usd |
|---|---|---|---|---|---|
| `rnd` | 研发部 | RND | RND-01 | 350 | 400 |
| `product` | 产品部 | PRD | PRD-01 | 250 | 300 |
| `production` | 生产制造部 | MFG | MFG-01 | 350 | 350 |
| `quality` | 质量部 | QAL | QAL-01 | 250 | 250 |
| `supply` | 供应链部 | SCM | SCM-01 | 300 | 300 |
| `sales` | 销售部 | SAL | SAL-01 | 300 | 300 |
| `after-sales` | 售后服务部 | SVC | SVC-01 | 300 | 300 |
| `marketing` | 市场部 | MKT | MKT-01 | 350 | 400 |
| `finance` | 财务部 | FIN | FIN-01 | 200 | 200 |
| `hr` | 人力资源部 | HR | HR-01 | 200 | 200 |
| `it` | 信息技术部 | IT | （平台运维，非对外场景） | 350 | 400 |

> 总经办不单独成场景，跨部门协调工作流不纳入 demo。

### 4.3 团队（按部门拆组）

- **研发部**: `rnd-translation`（翻译组） / `rnd-mechanical`（结构组） / `rnd-electrical`（电气组）
- **产品部**: （不分团队）
- **生产制造部**: `prod-planning`（排产计划组） / `prod-assembly`（总装车间） / `prod-test`（测试车间）
- **质量部**: `qal-engineering`（质量工程组）
- **供应链部**: `supply-procurement`（采购组） / `supply-logistics`（物流组）
- **销售部**: `sales-ops`（销售运营组） / `sales-ecom`（电商组） / `sales-dealer`（经销渠道组）
- **售后服务部**: `svc-engineer`（工程师组）
- **市场部**: `mkt-content`（内容组） / `mkt-competitive`（竞情组） / `mkt-training`（培训组）
- **财务部**: `fin-recon`（对账组） / `fin-receivable`（应收组） / `fin-payable`（应付组）
- **人力资源部**: `hr-recruiting`（招聘组） / `hr-training`（培训组） / `hr-compensation`（薪酬组）
- **信息技术部**: `it-infra`（系统运维组） / `it-ai`（AI 应用组）

### 4.4 演示用户（用户名非邮箱，密码统一 `12345678`）

| username | display_name | role | 部门 | 团队 | 归口场景 |
|---|---|---|---|---|---|
| `admin` | 组织管理员 | admin | — | — | 管理端配置 |
| `it-specialist` | IT AI 应用专员 | member | `it` | `it-ai` | 平台运维（非对外场景） |
| `rnd-translator` | 研发翻译员 | member | `rnd` | `rnd-translation` | RND-01 |
| `pm-product` | 产品专员 | member | `product` | — | PRD-01 |
| `mfg-planner` | 排产计划员 | member | `production` | `prod-planning` | MFG-01 |
| `qal-engineer` | 质量工程师 | member | `quality` | `qal-engineering` | QAL-01 |
| `scm-buyer` | 采购员 | member | `supply` | `supply-procurement` | SCM-01（采购子任务） |
| `scm-logistics` | 物流员 | member | `supply` | `supply-logistics` | SCM-01（物流子任务） |
| `sal-ops` | 销售运营员 | member | `sales` | `sales-ops` | SAL-01（订单回款）+ SAL-02（报销进度） |
| `sal-ecom` | 电商运营员 | member | `sales` | `sales-ecom` | SAL-01（退换货子任务） |
| `svc-engineer` | 售后工程师 | member | `after-sales` | `svc-engineer` | SVC-01 |
| `mkt-specialist` | 市场专员 | member | `marketing` | `mkt-content` | MKT-01 |
| `fin-accountant` | 财务会计 | member | `finance` | `fin-recon` | FIN-01（对账子任务） |
| `fin-receivable` | 应收会计 | member | `finance` | `fin-receivable` | FIN-01（应收子任务） |
| `hr-recruiter` | 招聘专员 | member | `hr` | `hr-recruiting` | HR-01（招聘子任务） |
| `hr-trainer` | 培训专员 | member | `hr` | `hr-training` | HR-01（培训制度子任务） |
| `hr-compensation` | 薪酬专员 | member | `hr` | `hr-compensation` | HR-01（薪酬子任务） |

> 全部 17 个用户，密码统一 `12345678`。命名规则统一为 `<部门代号>-<角色>`（如 `it-specialist` / `rnd-translator` / `svc-engineer`），无邮箱形式。多组场景（SCM-01 / SAL-01 / FIN-01 / HR-01）的主演示用第一个归口员工，验证 scope 隔离时切到对应组员工。

### 4.5 模型（终端下拉，真实模型 id）

终端模型下拉直接列**真实模型 id**（按用户可访问的 API Key 聚合 provider 的 `supported_models`，embedding 模型已过滤）。任务 config 的 `model_alias` 字段直接填这些 id 之一（或 `default` 走组织默认路由），**不再有别名解析层**。

agileac 配 4 个 provider，可用模型：

| provider | supported_models | 用途 |
|---|---|---|
| 智谱 AI | `glm-5.2` / `glm-4.6` / `glm-4-plus` | 终端 demo 默认（`glm-5.2`） |
| Anthropic 官方 | `claude-opus-4` / `claude-sonnet-4` / `claude-haiku-4` | Claude 系列 |
| OpenAI 官方 | `gpt-4o` / `gpt-4o-mini` / `gpt-4-turbo` | GPT 系列 |
| DeepSeek | `deepseek-chat` / `deepseek-reasoner` | DeepSeek 系列 |

### 4.6 组织级 API Key（demo 用）

| key_name | scope | 说明 |
|---|---|---|
| 敏睿空调 默认 Key | organization | seed 脚本默认（组织级备用） |
| 研发翻译组 Key | team | `rnd / rnd-translation` |
| 产品部 Key | department | `product` |
| 排产计划组 Key | team | `production / prod-planning` |
| 质量工程组 Key | team | `quality / qal-engineering` |
| 采购组 Key | team | `supply / supply-procurement` |
| 物流组 Key | team | `supply / supply-logistics` |
| 销售运营组 Key | team | `sales / sales-ops` |
| 电商组 Key | team | `sales / sales-ecom` |
| 售后工程师组 Key | team | `after-sales / svc-engineer` |
| 市场内容组 Key | team | `marketing / mkt-content` |
| 财务对账组 Key | team | `finance / fin-recon` |
| 财务应收组 Key | team | `finance / fin-receivable` |
| 招聘组 Key | team | `hr / hr-recruiting` |
| 培训组 Key | team | `hr / hr-training` |
| 薪酬组 Key | team | `hr / hr-compensation` |
| AI 应用组 Key | team | `it / it-ai` |

---

## 5. Mock 系统改造清单

### 5.1 mock 数据改造（6 系统 × agileac 租户）

| 系统 | 文件 | 改造点 |
|---|---|---|
| PLM | `mock/mock/systems/plm/data.py` | 追加 `_build_agileac()`：7 款空调产品 + 5 类配件 + BOM + 工程变更 + 故障案例（家用漏水/不制冷/异音，商用通讯故障/高压保护/冷媒泄漏/化霜失效）+ 成本台账 + 卖点库 |
| SCM | `mock/mock/systems/scm/data.py` | 追加 agileac 供应商（压缩机/换热器/阀件/制冷剂厂商）+ 报价 + 产能日历 + 到货计划 + 资质档案 |
| ERP | `mock/mock/systems/erp/data.py` | 追加 agileac 物料档案 + 采购订单 + 库存 + 应付应收 + 凭证 + 成本中心 |
| MES | `mock/mock/systems/mes/data.py` | 追加 agileac 产线（家用总装线/商用总装线/测试线）+ 设备 + 工单（含故障工单）+ 缺陷 + 在制品 |
| CRM | `mock/mock/systems/crm/data.py` | 追加 agileac 客户（经销商/电商平台/工程客户）+ 商机 + 报价 + 销售订单 + 客诉（含退换货 + 故障报修）+ 应收 |
| HRM | `mock/mock/systems/hrm/data.py` | 追加 agileac 员工 + 部门 + 考勤 + 请假 + 薪酬 + 绩效 + 招聘需求 + 会议纪要 |

### 5.2 mock 网关注册

在 `mock/mock/core/registry.py` 的 6 条 SystemDef 的 `tenants` 元组追加 `"agileac"`，并在 `default_keys_to_tenants` 加 `"agileac": "<sys>-agileac-demo-key"`：

```python
SystemDef(
    key="mes", ...,
    tenants=("minrui", "starclothing", "agileac"),
    default_keys_to_tenants={
        "minrui": "mes-mock-demo-key",
        "starclothing": "mes-starclothing-demo-key",
        "agileac": "mes-agileac-demo-key",
    },
),
# 同样改 crm / erp / hrm / plm / scm
```

### 5.3 mock 端点改造（新增 / 调整）

| 系统 | 新增端点 | operationId | 用途 | 归口场景 |
|---|---|---|---|---|
| CRM | `GET /api/v1/complaints?type=return` | `listComplaints`（扩参） | 电商退换货内部处理 | SAL-01 |
| HRM | `GET /api/v1/recruitments/{position_id}/resumes` | `listResumesByPosition` | 简历筛选 | HR-01 |
| HRM | `POST /api/v1/recruitments/{position_id}/shortlist` | `shortlistResumes` | 候选人排序 | HR-01 |
| HRM | `GET /api/v1/meetings` | `listMeetings` | 会议列表 | HR-01 培训组 |
| HRM | `POST /api/v1/meetings/{mid}/minutes` | `postMeetingMinutes` | 纪要写入 | HR-01 培训组 |
| SCM | `GET /api/v1/suppliers/{code}/qualifications` | `getSupplierQualifications` | 供应商资质审查 | SCM-01 |
| PLM | `GET /api/v1/products/{style_code}/selling-points` | `getProductSellingPoints` | 卖点提取 | PRD-01 / MKT-01 |
| PLM | `GET /api/v1/translations/pending` | `listPendingTranslations` | 待翻译资料 | RND-01 |
| MES | `GET /api/v1/defects/{defect_id}/root-cause` | `getDefectRootCause` | 缺陷根因分析 | QAL-01 |

> 现有端点（`listCustomers` / `listComplaints` / `listDefects` / `listPayables` / `listReceivables` / `compareQuotations` / `estimateLeadtime` 等）直接复用。
>
> ⚠️ **不新增** `createComplaint` 端点——B3 智能电话客服已剔除，客诉数据由 mock 内置 `listComplaints` 提供作为售后工程师诊断输入。

### 5.4 自检命令

```bash
docker restart ai_infra_mock

# 6 系统健康检查
for SYS in plm scm erp mes crm hrm; do
  curl -s "http://localhost:8010/$SYS/health" -H "X-API-Key: $SYS-agileac-demo-key"
done

# agileac tenant 数据可见性
curl -s "http://localhost:8010/plm/styles" -H "X-API-Key: plm-agileac-demo-key" | head
curl -s "http://localhost:8010/crm/complaints" -H "X-API-Key: crm-agileac-demo-key" | head
curl -s "http://localhost:8010/hrm/recruitments" -H "X-API-Key: hrm-agileac-demo-key" | head
```

---

## 6. RAG 知识库设计（按 scope 分级）

### 6.1 RAG 集合清单

| Collection | scope | scope_id | 归口场景 | chunk_size | 内容 | chunks 估 |
|---|---|---|---|---|---|---|
| **多语术语与海外资料库** | team | `rnd-translation` | RND-01 | 512 | 英/日→中术语词典（500 词条）+ 历史翻译段落 | ~120 |
| **产品参数与卖点库** | department | `product` | PRD-01 | 384 | 7 款产品参数表 + 卖点提炼规则 + 型号差异对照 | ~80 |
| **质量缺陷案例库** | department | `quality` | QAL-01 | 512 | 8 类质量缺陷案例（根因/纠正/预防）+ 质检 SOP | ~70 |
| **供应商资质与历史表现库** | department | `supply` | SCM-01 | 384 | 50 家供应商档案（资质/历史评分/交期/质量/黑名单） | ~50 |
| **售后故障与维修知识库** | department | `after-sales` | SVC-01 | 512 | 8 类故障案例（家用漏水/不制冷/异音/控制板；商用通讯故障/高压保护/冷媒泄漏/化霜失效）+ 维修手册章节 | ~80 |
| **营销与竞品情报库** | department | `marketing` | MKT-01 | 512 | 7 款产品卖点库 + 竞品参数对比（格力/美的/海尔/大金/三菱）+ 海报文案模板 + 课件大纲模板 + 考题模板 | ~100 |
| **岗位JD与简历评估库** | team | `hr-recruiting` | HR-01（招聘） | 384 | 12 部门典型岗位 JD + 胜任力模型 + 面试题库 + 评估规则 | ~60 |
| **员工制度知识库** | department | `hr` | HR-01（培训）；报销段镜像至组织级员工综合知识库 | 512 | 报销/薪酬/请假/流程制度 + 工艺 SOP 摘要 | ~100 |
| **员工综合知识库** | organization | `agileac org.id` | SAL-02 | 512 | 多源合集：HR 制度 + 产品参数 FAQ + 工艺 SOP + 客服 FAQ（仅员工内部） | ~150 |

### 6.2 scope 规则

- **organization 级**：仅"员工综合知识库"——SAL-02 等全员问答用，包含多源 chunk，按 metadata 标注来源类型。
- **department 级**：6 个部门级 RAG——产品部/质量部/供应链部/售后服务部/市场部/人力资源部各有专属。
- **team 级**：2 个团队级 RAG——研发部翻译组、人力资源部招聘组，更细粒度。
- **不在场景中出现的部门**：生产制造部/销售部/财务部/信息技术部不需要专属 RAG（无文档型知识沉淀需求，纯数据接口驱动）。

### 6.3 embedding 与检索

- embedding_model：`text-embedding-v4`（阿里云通义）
- `chunk_overlap=64`（中文长文）
- `_EMBED_BATCH=8`（受 Aliyun 10/batch 上限制约）
- 检索方式：pgvector 余弦相似度 + top_k=5；CJK 关键词兜底
- 若 chunks embedding 列为 NULL：跑 `reembed_agileac_rag.py`（参数化 collection_id）回填

### 6.4 自检

```bash
docker exec ai_infra_backend python -c "
import asyncio
from app.database import async_session_factory
from sqlalchemy import select, func
from app.models.rag import RagCollection, RagChunk
COLLECTIONS = ['多语术语与海外资料库','产品参数与卖点库','质量缺陷案例库','供应商资质与历史表现库',
               '售后故障与维修知识库','营销与竞品情报库','岗位JD与简历评估库','员工制度知识库','员工综合知识库']
async def main():
    async with async_session_factory() as db:
        for name in COLLECTIONS:
            r = await db.execute(select(RagCollection).where(RagCollection.name==name))
            c = r.scalar_one_or_none()
            if not c: print(f'{name}: not found'); continue
            cnt = await db.execute(select(func.count(RagChunk.id)).where(RagChunk.collection_id==c.id))
            emb = await db.execute(select(func.count(RagChunk.id)).where(RagChunk.collection_id==c.id, RagChunk.embedding.isnot(None)))
            print(f'{name}: chunks={cnt.scalar()} embedded={emb.scalar()}')
asyncio.run(main())
"
```

---

## 7. 本体文件设计（Ontology，按 scope 分级）

每域 4 个固定文件名：`README.md` / `object-types.md` / `link-types.md` / `action-types.md`。

### 7.1 组织级本体（全员可见，跨系统数据模型）

| 域 | 文件夹 | scope | 内容要点 |
|---|---|---|---|
| **Cross 跨系统** | `mock/openapi/ontology/cross/` | organization | 款号↔工单↔客户↔供应商↔员工↔岗位↔故障↔RAG 检索语义 |
| **PLM** | `mock/openapi/ontology/plm/` | organization | 产品/BOM/工程变更/故障案例/成本台账/卖点 |
| **SCM** | `mock/openapi/ontology/scm/` | organization | 供应商/报价/产能/到货/资质 |
| **ERP** | `mock/openapi/ontology/erp/` | organization | 物料/采购/库存/应付应收/凭证 |
| **MES** | `mock/openapi/ontology/mes/` | organization | 工单/产线/设备/OEE/缺陷/在制品 |
| **CRM** | `mock/openapi/ontology/crm/` | organization | 客户/商机/报价/销售订单/客诉/应收 |
| **HRM** | `mock/openapi/ontology/hrm/` | organization | 员工/部门/考勤/请假/薪酬/招聘/会议 |

> 6 域 × 4 文件 + Cross 4 文件 = 28 个本体文件，全部组织级——数据模型本身是组织级共识，全员可见。

### 7.2 部门级本体（部门专属业务概念）

| 部门 | 文件夹 | scope | 内容 |
|---|---|---|---|
| 研发部·翻译组 | `mock/openapi/ontology/rnd-translation/` | team | 翻译流程/术语条目/核对规则 |
| 售后服务部 | `mock/openapi/ontology/after-sales/` | department | 故障诊断流程/8D 阶段/排查步骤/配件更换 |
| 市场部 | `mock/openapi/ontology/marketing/` | department | 营销内容类型/竞品对比维度/课件结构 |
| 人力资源部 | `mock/openapi/ontology/hr/` | department | 招聘流程/培训体系/薪酬结构 |

> 4 个部门/团队级本体 × 4 文件 = 16 个本体文件。其他部门（生产/质量/供应链/销售/财务/产品/IT）不建专属本体，复用 6 域组织级本体即可满足场景需要。

### 7.3 本体文件总数

**28 组织级 + 16 部门/团队级 = 44 个本体文件**。

---

## 8. Agent 配置设计（11 个 agent）

每个 agent 一份 `system_prompt`，写明：归口部门 / 任务边界 / 必调端点 / 输出格式 / 闭环要求。每个 agent 的 skill_ids 与 rag_collection_ids 严格按部门级 scope 授权。

### 8.1 RND-01 多语技术资料翻译与术语统一

- **slug**: `agileac-rnd-01-translation`
- **归口**: 研发部 · 翻译组
- **员工 vibe**: 研发翻译员工处理外文技术资料时，用 AI 副驾驶统一术语 + 核对型号，缩短 15 天→1 天
- **绑技能**: `agileac-rnd-plm-query`（团队级，绑 PLM 只读端点：`listStyles` / `getProductSellingPoints` / `listPendingTranslations`）
- **RAG**: 多语术语与海外资料库（team 级，`rnd-translation`）
- **exec_mode**: `craft`
- **任务**: 接收外文技术资料（PDF 提取段）→ 检索术语词典 RAG 统一行业术语 → 调 PLM 产品参数核对型号/规格一致性 → 输出中文化译文 + 术语对照表 + 型号差异提示。
- **输出**: 翻译稿 + 术语对照表 + 参数差异核对表 + `generate_docx` 附件

### 8.2 PRD-01 产品参数核对与卖点提炼

- **slug**: `agileac-prd-01-product-params`
- **归口**: 产品部
- **员工 vibe**: 产品专员做型号配置核对 + 提炼卖点供市场部使用
- **绑技能**: `agileac-prd-plm-crm-query`（部门级，绑 PLM `listStyles`/`getStyle`/`listBoms` + CRM `listCustomers`/`getCustomer`/`listOpportunities`/`listFollowUps` 只读）
- **RAG**: 产品参数与卖点库（部门级，`product`，含 6 款参数表 + 5 段式卖点方法论 + 内部款/竞品对照）
- **exec_mode**: `craft`
- **任务**: 接收产品款号 → 检索 RAG 取标称参数 + 5 段式卖点方法论 + 竞品对照 → 调 PLM `getStyle`/`listBoms` 核对 BOM/型号一致性 → 调 CRM 取客户画像做场景化卖点 → 输出参数表 + 卖点提炼（产品部交付给市场部使用）。**卖点不走 `getProductSellingPoints` 端点（未实现/未绑定）——卖点段来自 RAG，参数来自 PLM。**
- **输出**: 参数核对表 + 卖点提炼清单

### 8.3 MFG-01 工单进度与产能报表

- **slug**: `agileac-mfg-01-production-report`
- **归口**: 生产制造部 · 排产计划组
- **员工 vibe**: 排产计划员每日扫工单进度 + 产能占用 + 卡顿节点
- **绑技能**: `agileac-mfg-mes-erp-scm-query`（部门级，绑 MES 工单/产线/OEE/WIP + ERP 物料库存 + SCM 到货/补单/交期快照只读）
- **RAG**: 无（排产优先级/缺料卡顿/产能预警阈值规则由模板 system_prompt 承载，A2 排产规则库待补）
- **exec_mode**: `craft`
- **任务**: 调 MES `listWorkOrders` + `listEquipmentStatus` + `getOee` + `listWip` → 调 ERP `listInventory` 看物料现货 → 调 SCM `listFabricArrivalPlans` + `listReplenishmentSuggestions` 看到货与补单 → 按"在制/逾期/卡顿"分组输出工单进度表 + 产能报表 + 卡顿节点催办对象。
- **输出**: 工单进度汇总表 + 产能报表 + 卡顿催办清单

### 8.4 QAL-01 质量数据报表与缺陷闭环

- **slug**: `agileac-qal-01-quality-report`
- **归口**: 质量部 · 质量工程组
- **员工 vibe**: 质量工程师做来料/制程/出货质量报表 + 缺陷闭环
- **绑技能**: `agileac-qal-mes-plm-query`（部门级，绑 MES 缺陷/工单/生产订单 + PLM 历史故障案例/产品款式只读）
- **RAG**: 质量缺陷案例库（部门级，`quality`，8 类缺陷 5W2H + 质检 SOP IQC/IPQC/OQC + 8D 闭环）
- **exec_mode**: `craft`
- **任务**: 调 MES `listDefects` + `getDefectRootCause` → 调 PLM `listDefectHistory` → 检索质量缺陷案例 RAG 找相似历史根因 → 输出质量报表 + 缺陷闭环待办（催办对象：生产/研发/采购）。
- **输出**: 质量数据报表 + 缺陷闭环清单

### 8.5 SCM-01 供应商评审与采购物流一体化

- **slug**: `agileac-scm-01-procurement-logistics`
- **归口**: 供应链部 · 采购组 + 物流组（同部门两个组）
- **员工 vibe**: 采购员做比价 + 资质审查；物流员做到货监管 + 仓储报表
- **绑技能**: `agileac-scm-scm-erp-query`（部门级，绑 SCM 全集 + ERP 采购/库存/应付只读）
- **RAG**: 供应商资质与历史表现库（部门级，`supply`）
- **exec_mode**: `craft`
- **任务**: 两子任务（演示时按 prompt 切换）：
  - **采购子任务**：对 5 类核心配件调 SCM `compareQuotations` + `listQuotations`/`listSuppliers` 比价 → 检索供应商资质 RAG 做 5 维度评审 → 调 ERP `listPayables` 看应付 → 输出供应商评分 + 推荐清单。**无 `getSupplierQualifications` 端点（未实现）——供应商资质走 RAG 检索。**
  - **物流子任务**：调 SCM `listFabricArrivalPlans` + ERP `listInventory` + SCM `listReplenishmentSuggestions` → 输出到货监管 + 仓储报表 + 缺料预警。
- **输出**: 供应商评分表 / 到货监管表 / 仓储报表（按子任务）

### 8.6 SAL-01 销售订单回款与电商退换货

- **slug**: `agileac-sal-01-sales-ecommerce`
- **归口**: 销售部 · 销售运营组 + 电商组（同部门两个组）
- **员工 vibe**: 销售运营员做订单/回款报表；电商运营员处理退换货内部流程
- **绑技能**: `agileac-sal-crm-erp-query`（部门级，绑 CRM 客户/商机/订单/客诉/应收 + ERP 凭证/生产成本只读）
- **RAG**: 无
- **exec_mode**: `craft`
- **任务**: 两子任务：
  - **销售运营子任务**：调 CRM `listSalesOrders` + CRM `listReceivables`（status=逾期）→ 输出订单回款报表 + 应收催办清单 + 推送对象。**应收走 CRM `listReceivables`（ERP 无该端点，AGINV 发票号与 ERP 共享码空间）。**
  - **电商退换货子任务**：调 CRM `listComplaints`（type=return）+ `listCustomers` → 输出退换货内部处理清单，客诉转 svc-engineer 检测闭环回流 SVC-01（员工流程，不对客户直接交互）。
- **输出**: 订单回款报表 / 退换货处理清单

### 8.7 SVC-01 售后故障 AI 诊断与 8D 闭环

- **slug**: `agileac-svc-01-after-sales-diagnosis`
- **归口**: 售后服务部 · 工程师组
- **员工 vibe**: 售后工程师接报修后用 AI 副驾驶做根因分析 + 排查指引 + 8D 闭环，**不对客户直接交互**
- **绑技能**: `agileac-svc-crm-mes-plm-query`（部门级，绑 CRM 客诉只读 + MES 工单/缺陷 + PLM BOM/工程变更/故障案例只读）
- **RAG**: 售后故障与维修知识库（部门级，`after-sales`）
- **exec_mode**: `craft`
- **任务**: 调 CRM `listComplaints` 拿客诉工单 → 调 MES 工单/缺陷/设备故障历史 → 调 PLM 产品 BOM/工程变更 → 检索故障案例 RAG 找相似历史根因 + 维修手册 → 输出根因分析 + 排查步骤 + 配件清单 + 8D 闭环待办（催办对象：研发/质量/采购，通过待办机制，不直接调用其他部门 agent）。
- **trace 必出**: rag + memory.load + ontology + data_interface + skill + memory.extract（全 6 类）
- **输出**: 故障诊断报告 + 8D 待办清单 + `generate_docx` 附件

### 8.8 MKT-01 营销内容生成与培训课件自动化

- **slug**: `agileac-mkt-01-marketing-content`
- **归口**: 市场部 · 内容组 + 竞情组 + 培训组（同部门三个组）
- **员工 vibe**: 市场专员/培训师用 AI 副驾驶批量产出海报文案+视频脚本+课件+考题+竞品对比，**员工制作后由员工投放，AI 不对终端客户**
- **绑技能**: `agileac-mkt-plm-crm-query`（部门级，绑 PLM 产品参数/卖点 + CRM 客户画像只读）
- **RAG**: 营销与竞品情报库（部门级，`marketing`，含 3 类 chunk：卖点库/竞品/课件模板，按 metadata 区分）
- **exec_mode**: `craft`
- **任务**: 接收"为某款产品生成营销内容"请求 → 调 PLM `getProductSellingPoints` → 检索营销 RAG（按 chunk type 分段检索）→ 输出三段：(1) 卖点提炼+竞品对比表；(2) 海报文案+视频脚本；(3) 课件大纲+PPT 框架+考题。
- **覆盖**: F 内容生成 + A1 海量 + A2 卖点（市场部视角，与 PRD-01 产品部视角互补）+ A5 做课 + B4 竞品情报
- **输出**: 卖点对比表 + 海报文案 + 视频脚本 + 课件大纲 + 考题 + `generate_docx` 打包

### 8.9 FIN-01 多系统对账与应收催办

- **slug**: `agileac-fin-01-reconciliation-receivable`
- **归口**: 财务部 · 对账组 + 应收组（同部门两个组）
- **员工 vibe**: 对账会计做跨系统对账 + 成本稽核；应收会计做应收逾期催办
- **绑技能**: `agileac-fin-erp-crm-query`（部门级，slug 历史命名但实际跨 5 系统：ERP 凭证/应付/生产成本/物料 + MES 工单 + SCM 报价 + PLM 成本台账 + CRM 应收/客户/订单只读，SSO 免登跨系统）
- **RAG**: 无
- **exec_mode**: `craft`
- **任务**: 两子任务：
  - **对账子任务**：ERP 凭证 ↔ MES 工单成本 ↔ SCM 报价 ↔ PLM 成本台账 四方对账 → 差异率 >2% + 异常清单。
  - **应收子任务**：调 CRM `listReceivables`（status=逾期）+ `listCustomers` → 输出应收催办清单 + 推送对象。**应收走 CRM `listReceivables`（AGINV 与 ERP 共享码空间）。**
- **演示 SSO 价值**: prompt 里写"通过 SSO 免登跨 ERP/MES/SCM/PLM 查询"，agent 在调多系统端点时不需要重复登录。
- **输出**: 差异汇总表 / 应收催办清单

### 8.10 HR-01 招聘培训薪酬一体化

- **slug**: `agileac-hr-01-hr-ops`
- **归口**: 人力资源部 · 招聘组 + 培训组 + 薪酬组（同部门三个组）
- **员工 vibe**: 招聘专员筛简历；培训专员管员工制度问答；薪酬专员做薪酬报表
- **绑技能**: `agileac-hr-hrm-query`（部门级，绑 HRM 员工/部门/岗位/考勤/请假/薪酬/绩效/招聘/简历/会议只读；`shortlistResumes` 为 POST 不绑定，筛选用 `listResumesByPosition` + LLM 评估排序）
- **RAG**: 岗位JD与简历评估库（team 级，`hr-recruiting`，招聘子任务主绑）+ 员工综合知识库（organization 级，培训制度子任务 auto-load，含 HR 制度摘要）
- **exec_mode**: `craft`
- **任务**: 三子任务（按 prompt 切换）：
  - **招聘子任务**：调 HRM `listRecruitments` + `listResumesByPosition` → 检索岗位 JD RAG（5 维度评估：学历15%/经验25%/行业25%/技能25%/软技能10%）→ 输出简历匹配度排序 + 推荐短名单 + 面试题（3 通用+5 专业+2 案例）+ 到岗催办。
  - **培训制度子任务**：接收员工问题 → 检索组织级员工综合知识库（auto-load）→ 输出答案 + 引用源（标文档版本与生效日期）。
  - **薪酬子任务**：调 HRM `listPayrolls` + `listPerformances` → 输出薪酬报表。**本场景技能仅绑 HRM 不直查 ERP 凭证，薪酬期凭证号 BV-AG- 作交叉提示（凭证核对在 FIN-01 侧对账）。**
- **输出**: 简历评估表 / 制度问答答案 / 薪酬报表

### 8.11 SAL-02 差旅报销进度问答

- **slug**: `agileac-sal-02-reimbursement-status`
- **归口**: 销售部 · 销售运营组
- **员工 vibe**: 销售运营员问"我上周提交的差旅报销走到哪一步了"——原本要开 ERP、等登录超时、找凭证、看状态，现在一句话拿到答案
- **绑技能**: `agileac-sal-crm-erp-query`（部门级，复用销售部技能，已绑 ERP `listVouchers` + CRM 端点）
- **RAG**: 员工综合知识库（organization 级，差旅报销段含 5 步流程 + 状态枚举）
- **exec_mode**: `craft`
- **任务**: 接收员工报销进度问题 → **先检索员工综合知识库**拿差旅报销 5 步流程与状态枚举（申请中→直属经理审批中→部门总监联签中→财务复核中→已打款→已闭环）→ **再调 ERP `listVouchers(period=2026-07)`** 取该期间凭证、按 summary 含"差旅费报销"定位员工那张单 → 组合答出当前状态 + 第几步 + 金额 + 预计打款日。验证痛点 A（知识库）+「先 RAG 后接口」分工。
- **输出**: 报销进度答案 + 引用源（知识库 chunk + ERP 端点 + 凭证号）

> SAL-02 是 11 场景中**唯一消费组织级 RAG** 的场景（员工综合知识库）；不再有组织级技能——SAL-02 复用销售部部门级技能 `agileac-sal-crm-erp-query`（已含 ERP `listVouchers`），无需跨部门数据权限。

---

## 9. Seed 脚本清单与顺序

按依赖链顺序执行，**幂等 + 增量**（slug 去重，绝不 DROP）。

```
demo/agileac/scripts/
├── seed_agileac_org.py                # 1. 组织/部门/团队/用户/路由/APIKey（无 model alias）
├── seed_agileac_mock_tenants.py       # 2. mock 6 系统追加 agileac 租户数据
├── seed_agileac_mock_connectors.py    # 3. 6 mock 连接器 + 部门级技能 + 数据接口（按部门 scope 授权）
├── seed_agileac_ontology.py           # 4. 28 组织级 + 16 部门/团队级 = 44 个本体文件
├── seed_agileac_rag.py                # 5. 9 个 RAG collection（1 组织级 + 6 部门级 + 2 团队级）
├── seed_agileac_agents.py             # 6. 11 个业务 Agent 配置（按部门级 skill_ids + rag_collection_ids）
└── reembed_agileac_rag.py             # 维护脚本：NULL embedding 回填（参数化 collection_id）
```

### 9.1 执行命令

```bash
SCRIPTS=(
  seed_agileac_org.py
  seed_agileac_mock_tenants.py
  seed_agileac_mock_connectors.py
  seed_agileac_ontology.py
  seed_agileac_rag.py
  seed_agileac_agents.py
)
for s in "${SCRIPTS[@]}"; do
  docker cp /root/ai_infra/demo/agileac/scripts/$s ai_infra_backend:/app/scripts/$s
  docker exec ai_infra_backend python scripts/$s
done

docker restart ai_infra_mock
```

### 9.2 顺序依赖

```
seed_agileac_org ──┐
                   ├──→ seed_agileac_mock_connectors ──┐
seed_agileac_mock_tenants (改 mock) ──┘              ├──→ seed_agileac_agents
                                                     │
seed_agileac_ontology (独立) ────────────────────────┤
seed_agileac_rag (独立，需 embedding provider 已配) ──┘
```

### 9.3 部门级 scope 关键实现

`seed_agileac_mock_connectors.py` 创建技能时按部门 scope：

```python
# 部门级技能示例：售后部技能绑 CRM+MES+PLM 只读
SkillFolder(
    slug="agileac-svc-crm-mes-plm-query",
    name="敏睿·售后部 查询技能",
    scope_type="department",
    scope_id=after_sales_dept.id,
    skill_files=[...绑定 crm/mes/plm 的只读端点 manifest...],
)
# 数据接口按部门授权
DataInterface.scope_type="department", scope_id=after_sales_dept.id
```

> SAL-02 复用销售部部门级技能 `agileac-sal-crm-erp-query`（已绑 ERP `listVouchers`），`scope_type="department", scope_id=<sales dept id>`，不另建组织级技能。

---

## 10. 演示运行（全部终端任务方式）

### 10.1 登录终端

浏览器访问：

```
http://localhost:8000/agileac/terminal/login
```

按场景归口用户登录（密码统一 `12345678`）：

| 场景 | 登录用户 |
|---|---|
| RND-01 | `rnd-translator` |
| PRD-01 | `pm-product` |
| MFG-01 | `mfg-planner` |
| QAL-01 | `qal-engineer` |
| SCM-01（采购子任务） | `scm-buyer` |
| SCM-01（物流子任务） | `scm-logistics` |
| SAL-01（销售运营子任务） | `sal-ops` |
| SAL-01（电商退换货子任务） | `sal-ecom` |
| SVC-01 | `svc-engineer` |
| MKT-01 | `mkt-specialist` |
| FIN-01（对账子任务） | `fin-accountant` |
| FIN-01（应收子任务） | `fin-receivable` |
| HR-01（招聘子任务） | `hr-recruiter` |
| HR-01（培训制度子任务） | `hr-trainer` |
| HR-01（薪酬子任务） | `hr-compensation` |
| SAL-02 | `sal-ops` |

### 10.2 通用任务配置（TaskConfigDrawer）

| 字段 | 取值 |
|---|---|
| Workspace | 当前登录用户名（个人工作区） |
| Model | `glm-5.2`（真实模型 id；终端下拉直接列真实 id，无别名层） |
| Exec Mode | `craft`（自主多步执行） |
| Skills | 按 /-mention 选对应场景的技能 chip |

### 10.3 资源自动注入（按 scope，不在 drawer 里配）

- 44 个本体文件按 scope 注入（组织级 28 全员可见 + 部门级/团队级 16 按用户 scope 注入）
- 9 个 RAG collection 按 scope 可见（组织级 1 全员 + 部门级 6 按部门 + 团队级 2 按团队）
- 长期记忆按"组织+部门+团队+个人"4 级聚合
- 数据接口按用户 scope 权限列出

### 10.4 SSE trace 事件（演示截图证据）

每场景跑完应包含应有的 trace 类（无 RAG 的场景 rag 不出现）：

| trace | 含义 |
|---|---|
| `category=rag` | RAG 检索命中（RND-01/PRD-01/QAL-01/SCM-01/SVC-01/MKT-01/HR-01/SAL-02 有；MFG-01/SAL-01/FIN-01 无） |
| `category=memory, subtype=load` | 长期记忆载入（4 级 scope 聚合） |
| `category=ontology` | 组织本体注入（按用户 scope） |
| `category=data_interface` | 数据接口目录注入（按部门级 scope） |
| `category=skill` | /-mention 引用技能 |
| `category=memory, subtype=extract` | 记忆沉淀抽取 |

---

## 11. 跨场景合并原则（按部门边界）

### 11.1 同部门多组可合一场景

| 场景 | 合并的组 | 合合理由 |
|---|---|---|
| SCM-01 | 采购组 + 物流组 | 同部门，技能/RAG/数据接口同源 |
| SAL-01 | 销售运营组 + 电商组 | 同部门，技能同源（CRM+ERP+SCM 只读） |
| MKT-01 | 内容组 + 竞情组 + 培训组 | 同部门，RAG 用 chunk metadata 区分三类内容 |
| FIN-01 | 对账组 + 应收组 | 同部门，技能同源（ERP+MES+SCM+PLM 只读） |
| HR-01 | 招聘组 + 培训组 + 薪酬组 | 同部门，技能同源（HRM+ERP 只读），RAG 按子任务切换 |

### 11.2 跨部门不合并（关键拆分决策）

| 原合并 | 拆分理由 |
|---|---|
| AG-PD2 销售运营+应收催办 → 拆 SAL-01 + FIN-01（+ SAL-02 报销进度同归销售部） | 销售运营归销售部，应收催办归财务部——2 个部门不能合并 |
| AG-SC2 翻译+卖点 → 拆 RND-01 + PRD-01 | 翻译归研发部，卖点提炼归产品部——2 个部门不能合并 |
| AG-SC4 营销内容+竞品+培训 → 保留 MKT-01（市场部 3 组） | 3 组都在市场部，同部门可合 |
| AG-SC5 招聘+项目会议 → 拆 HR-01 + 不单独立 PM 会议场景 | 招聘归 HR 部；PM 会议归各部门自管，不集中到一个场景；IT 部作平台运维方支撑 |

### 11.3 反例（不合并的）

- SVC-01 与 QAL-01 不合并——前者是售后服务部（客户报修后诊断），后者是质量部（来料/制程/出货质量），部门不同。
- PRD-01 与 MKT-01 不合并——产品部做参数核对+卖点提炼，市场部做内容生成+竞品对比，部门不同。但两者 RAG 内容有交集（卖点库），通过 RAG scope（产品部级 vs 市场部级）+ chunk 内容差异化解决。

### 11.4 剔除项

- B3 智能电话客服（AI 语音接听客户来电）——对外服务，违反约束 2
- A 智能问答中"客服电话/线上咨询重复应答"对外部分——同上
- B6 项目跟踪会议助理不单独立场景——PM 会议属各部门 vibe working，不集中到一个跨部门场景；IT 部作平台运维方支撑各部门 PM 自用

---

## 12. 验收清单（新组织 demo 上线前必过）

参考 `SCENARIO_AUTHORING_GUIDE.md` §7 + `NEW_ORG_DEMO_CHECKLIST.md`：

- [ ] mock 6 系统 `agileac` tenant 全部 health 返回 ok
- [ ] curl 验证 6 系统 agileac API Key 均能取到 agileac 数据集
- [ ] seed 脚本幂等：跑第二遍无报错、无重复行
- [ ] 17 个用户全部能登录 `/agileac/terminal`（密码统一 `12345678`）
- [ ] 模型下拉含 `glm-5.2`（真实模型 id）
- [ ] 44 个本体文件入库（28 组织级 + 16 部门/团队级）
- [ ] 9 个 RAG collection chunks 数 = embedded 数（无 NULL embedding）
- [ ] 11 个 agent 入库，skill_ids / rag_collection_ids 严格按部门/团队 scope 绑定
- [ ] RND-01 跑通：术语 RAG + 参数核对
- [ ] PRD-01 跑通：产品参数 RAG + 卖点提炼
- [ ] MFG-01 跑通：MES+SCM 报表，无 RAG 但 trace 含 ontology+data_interface+memory
- [ ] QAL-01 跑通：质量缺陷案例 RAG + 缺陷闭环
- [ ] SCM-01 跑通：采购子任务（供应商 RAG）+ 物流子任务
- [ ] SAL-01 跑通：销售运营子任务 + 电商退换货子任务（无 RAG）
- [ ] SVC-01 跑通：trace 含全 6 类，retrieve_rag `retriever=vector`，hits ≥ 1
- [ ] MKT-01 跑通：3 段输出（卖点对比 / 海报+视频脚本 / 课件+考题）
- [ ] FIN-01 跑通：对账子任务（4 系统对账）+ 应收子任务
- [ ] HR-01 跑通：3 子任务（招聘/培训制度/薪酬）
- [ ] SAL-02 跑通：员工综合知识库 RAG 命中报销流程 chunk + ERP `listVouchers(period)` 查凭证状态
- [ ] `tool_call` args 不全 `{}`（必传参端点要带 `material_code` 等参数；若全 `{}` 查 `app/agents/graph/nodes.py` `_build_tools`）
- [ ] 输出格式符合场景定义（表格 / 推送清单 / docx 附件）
- [ ] 11 个场景操作文档 `<scenario>_terminal_task.md` 写完且可复现
- [ ] scope 隔离验证：每个场景的归口用户登录后，`GET /api/v1/terminal/resources` 只能看到本部门/团队级技能+RAG+数据接口（不能看到其他部门资源，除组织级）

---

## 13. 文件清单（实施完成后的目标结构）

```
demo/agileac/
├── README.md                              # 本设计文档
├── SCENARIO_AUTHORING_GUIDE.md            # 复用 starclothing 版（场景搭建方法论，仅参考终端任务章节）
├── NEW_ORG_DEMO_CHECKLIST.md               # 复用 starclothing 版（实施 checklist）
├── CROSS_AGENT_HANDOFF_DESIGN.md          # 复用 starclothing 版（跨 agent 待办设计，SVC-01 8D 闭环可落地）
├── rnd_01_terminal_task.md                 # RND-01 多语技术资料翻译
├── prd_01_terminal_task.md                 # PRD-01 产品参数核对与卖点提炼
├── mfg_01_terminal_task.md                 # MFG-01 工单进度与产能报表
├── qal_01_terminal_task.md                 # QAL-01 质量数据与缺陷闭环
├── scm_01_terminal_task.md                 # SCM-01 供应商评审与采购物流
├── sal_01_terminal_task.md                 # SAL-01 销售订单与电商退换货
├── svc_01_terminal_task.md                 # SVC-01 售后故障诊断与 8D 闭环
├── mkt_01_terminal_task.md                 # MKT-01 营销内容与培训课件
├── fin_01_terminal_task.md                 # FIN-01 对账与应收催办
├── hr_01_terminal_task.md                  # HR-01 招聘培训薪酬
├── sal_02_terminal_task.md                 # SAL-02 差旅报销进度问答
└── scripts/
    ├── seed_agileac_org.py
    ├── seed_agileac_mock_tenants.py
    ├── seed_agileac_mock_connectors.py
    ├── seed_agileac_ontology.py
    ├── seed_agileac_rag.py
    ├── seed_agileac_agents.py
    └── reembed_agileac_rag.py
```

> ⚠️ **无 `.sh` 脚本与 `_common.sh`**——11 场景全部终端任务方式。`SCENARIO_AUTHORING_GUIDE.md` 中"shell 脚本方式"章节对 agileac 不适用，仅参考"终端任务方式"章节。

---

## 14. 实施优先级建议

> 全部落地工作量约 5~7 人日；按优先级分阶段交付。所有场景统一终端任务方式 + 员工 vibe working 视角。

| 优先级 | 范围 | 工作量 | 价值 | 状态 |
|---|---|---|---|---|
| **P0（首期 demo）** | SVC-01 + SAL-02 + MKT-01 | 1.5 人日 | 售后故障诊断 + 报销进度问答 + 营销内容——3 个最痛点场景，覆盖 B2 + A + F | ✅ 四层化 + 终端任务文档 + 端到端实测（A5） |
| **P1（二期）** | FIN-01 + SCM-01 + RND-01 | 1.5 人日 | 财务对账 + 供应商 + 翻译——覆盖 B + C + D + A6 + B1 | ✅ 四层化 + 终端任务文档已铺（待刷新 key 实测） |
| **P2（三期）** | PRD-01 + MFG-01 + QAL-01 + SAL-01 + HR-01 | 2 人日 | 产品参数 + 生产报表 + 质量缺陷 + 销售退换货 + HR 一体化——覆盖 A2 + B + C + A3 + A4 | ✅ 四层化 + 终端任务文档已铺（待刷新 key 实测，见 `KNOWN_ISSUES.md` A1 P2 段） |
| 全套完成 | 11 场景全跑通 | 5~7 人日 | 调研 8 痛点 + A 侧 6 项 + B 侧 5 项（剔除 B3）全覆盖 | 11/11 文档已铺（P0 三 + P1 三实测通过，P2 五待实测） |

> P1 落地伴随两处资源补齐：① `seed_agileac_ontology.py` 补 SCM 域 `identifiers.md`（SCM-01 四层化前置，见 `KNOWN_ISSUES.md` A1 修复）；② `seed_agileac_mock_connectors.py` 扩绑 FIN 技能（`agileac-fin-erp-crm-query` slug 保留，bindings 增 MES `listWorkOrders`/`getWorkOrder` + SCM `listQuotations`/`compareQuotations` + PLM `getCostLedger`）以支撑 README §8.9 设计的四方对账 + SSO。重跑顺序：connectors → ontology → agents。

---

## 15. 与 starclothing demo 的关系

| 维度 | starclothing | agileac |
|---|---|---|
| 行业 | 服装 | 家用+商用空调全产业链 |
| 场景数 | 7（PD1~3 + SC1~4） | 11（按 11 部门边界划分） |
| 编码规则 | PD（产品研发）+ SC（供应链） | `AG-<DEPT>-<SEQ>`（部门三字母代号 + 序号） |
| Demo 方式 | 3 终端任务 + 4 shell 脚本 | **11 终端任务（无 shell）** |
| mock 系统数 | 5（PLM/SCM/ERP/MES/CRM，跳 HRM） | 6（含 HRM，因招聘/培训/制度/会议场景需要） |
| RAG 数 | 1（服装缺陷，组织级） | 9（1 组织级 + 6 部门级 + 2 团队级，按 scope 分级） |
| 本体文件数 | 12（3 域 × 4，组织级） | 44（28 组织级 + 16 部门/团队级） |
| 业务主体映射 | 单一服装企业 | 覆盖销售侧（A）+ 制造侧（B）两主体痛点 |
| 定位 | 业务流程演示 | **员工 vibe working 辅助**——AI 副驾驶，不对客户直接交互 |
| 场景合并原则 | 业务流程合并 | **部门边界合并**——同部门多组可合，跨部门不合 |
| 资源 scope | 全组织级 | **分级**——组织级 / 部门级 / 团队级 |
| 演示用户 | `it-specialist` 单一 | 17 个归口用户（统一 `<部门代号>-<角色>` 命名，密码 `12345678`） |
| 剔除需求 | — | B3 智能电话客服 + A 客服对外应答 + B6 集中 PM 场景 |
| 复用资产 | — | `SCENARIO_AUTHORING_GUIDE.md` / `NEW_ORG_DEMO_CHECKLIST.md` / `CROSS_AGENT_HANDOFF_DESIGN.md` / `MOCK_SUBSYSTEM_TEMPLATE.md` 复用（**不复用 `_common.sh` 与 shell 脚本模板**） |

> 设计原则：**agileac 不是从零搭建，而是复用 starclothing 终端任务方法论 + 扩展 HRM 域 + 多 RAG 集合 + 部门级 scope 分级**。所有方法论文档（指南 / checklist / 跨 agent 设计 / mock 模板）直接软链或拷贝自 starclothing，仅在敏睿空调目录里追加 11 个 `*_terminal_task.md` 终端任务操作文档。

---

## 16. 后续行动

1. **审批本设计**：本 README 作为敏睿空调 demo 顶层设计，确认 11 场景按部门边界划分 + scope 分级 + 用户名非邮箱规则。
2. **分阶段实施**：按 §14 优先级，P0 三场景先跑通（SVC-01/SAL-02/MKT-01），验证 9 RAG + HRM 改造 + 部门级 scope 可行后铺开。
3. **mock 改造先行**：§5 mock 系统追加 agileac 租户是全部场景的前置，最先完成。
4. **scope 隔离验证**：每个场景落地后必须验证归口用户只能看到本部门资源（不能看到其他部门技能/RAG/数据接口，除组织级共享）。
5. **每个场景跑 §12 验收清单**，全 6 类 trace + `tool_call` args 不全 `{}` 是硬指标。
