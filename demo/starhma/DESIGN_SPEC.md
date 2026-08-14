# 星途热熔胶 AI 底座 POC 设计规约（DESIGN_SPEC）

> 单一事实源：本文件 + 各 `*_terminal_task.md` H1 + curl `title` + README §1/§5。
> 参考 starexploration/agilestationery/agilesteel 四层架构。slug `starhma`，组织名「星途热熔胶」。
> **重要**：所有喂 LLM 的 prompt/composer 不含场景代号（RDM-01 等），用具体示例码（FORM-CUS-002/EXP-RHE-002/ING-RES-001/M-RES-001/M-FG-002/BAT-2026-0702/CC-2026-001/EQ-MTR-02/INQ-002/CT-HMA-001/INV202607001/BV-HMA-2026-0701）。

## 0. 业务背景
星途热熔胶（2005 年，杭州未来科技城，国家高新/专精特新），专注环保热熔胶/热熔压敏胶研发与生产。13 条产线（2 全自动），年产能 2 万吨，服务 4500+ 客户，覆盖汽车内饰/医疗/食品日化包装/物流快递袋/鞋材箱包/粘扣带/家居七大下游。战略：向「粘接解决方案服务商」转型。配方数据为核心机密，需本地私有化。

mock 系统 6 套（3 新建 + 3 复用扩展）：
- 新建：**FRM** 配方研发管理 / **PCM** 工艺与设备管理 / **QAS** 质量与技术服务（均 `tenants=("starhma",)`）
- 复用：**ERP** 资源计划 / **MES** 制造执行 / **CRM** 客户管理（均新增 starhma tenant）

## 1. 痛点 → 场景映射（9 场景）
| 场景 | 任务名 | 部门(slug) | 登录用户 | Model | Skill slug | RAG | template_agent_id | Phase |
|---|---|---|---|---|---|---|---|---|
| RDM-01 | 配方智能推荐与初始配比 | 研发中心(rd) | rd-formulator | glm-5.2 | starhma-rd-frm-erp-query | starhma-rd-formula-kb(dept rd) | e5188ebd-24e3-4adc-8fa7-8118832da288 | P0 |
| RDM-02 | 实验数据分析与报告生成 | 研发中心(rd) | rd-analyst | glm-5.2 | starhma-rd-lab-frm-query | starhma-rd-experiment-kb(dept rd) | fe5e56d7-84cc-426a-920d-a8a17d90be71 | P0 |
| SAL-01 | 智能询盘与初步粘接方案 | 营销销售中心(sales) | sales-rep | glm-5.2 | starhma-sales-crm-frm-erp-query | starhma-sales-kb(dept sales) | 911847f5-57a3-43f5-8d5b-b98b92918e21 | P0 |
| MFG-01 | 智能排产与订单冲突识别 | 生产制造部(mfg) | mfg-planner | glm-5.2 | starhma-mfg-mes-pcm-erp-query | starhma-mfg-schedule-kb(dept mfg) | f881da63-63d9-4d6d-a6ff-71ec404941c8 | P0 |
| EQP-01 | 设备预测性维护与保养提醒 | 生产制造部(mfg) | eqp-maintainer | glm-5.2 | starhma-eqp-pcm-mes-query | starhma-eqp-maintenance-kb(dept mfg) | 9f6a623a-88dd-4b3c-a40f-3b58e6fb1872 | P1 |
| SCM-01 | 库存智能预警与补货建议 | 供应链部(scm) | scm-manager | glm-5.2 | starhma-scm-erp-crm-query | starhma-scm-inventory-kb(dept scm) | 31065753-d025-44a4-8d7d-3fd48d5a0864 | P0 |
| QAS-01 | 售后粘接故障智能诊断 | 品质与技术服务部(qas) | qas-engineer | glm-5.2 | starhma-qas-qas-crm-frm-query | starhma-qas-aftersales-kb(dept qas) | 011fa0f8-ef5a-417e-a1a4-881694794c81 | P0 |
| ADM-01 | 跨系统经营数据汇总 | 综合管理部(admin) | admin-officer | glm-5.2 | starhma-admin-erp-crm-mes-query | starhma-admin-bi-kb(dept admin) | 269c904a-9a0b-4f35-81e1-2522e90989bf | P0 |
| DOC-01 | 文档智能处理与检索 | 综合管理部(admin) | doc-clerk | glm-5.2 | starhma-admin-doc-erp-crm-query | starhma-admin-doc-kb(dept admin) | 3c14d454-8f08-4e70-a613-83c14387036c | P0 |

+ 信息中心(it) 无场景，仅作底座承载。共 7 部门、11 用户（admin + 9 场景用户 + it-specialist）、统一口令 `12345678`、终端登录 `/starhma/terminal/login`。

## 2. 组织 / 部门 / 团队 / 用户
7 部门：rd/sales/mfg/scm/qas/admin/it。团队（每部门 1-2 个）：
- rd: formula-team(配方研发组), lab-team(应用测试实验室)
- sales: sales-team(国内销售+技术销售组)
- mfg: schedule-team(生产排产组), equip-team(设备运维组)
- scm: scm-team(采购仓储组)
- qas: qas-team(品质与售后技术组)
- admin: admin-team(企管行政组), doc-team(文档资质组)
- it: it-infra(系统运维组), it-ai(AI 应用组)

11 用户（username/role/dept_slug/team_slug/scenario）：
- admin/admin/None/None/管理端配置
- it-specialist/member/it/it-ai/平台运维（非对外场景）
- rd-formulator/member/rd/formula-team/RDM-01 配方智能推荐
- rd-analyst/member/rd/lab-team/RDM-02 实验数据分析与报告
- sales-rep/member/sales/sales-team/SAL-01 智能询盘与初步方案
- mfg-planner/member/mfg/schedule-team/MFG-01 智能排产与订单冲突识别
- eqp-maintainer/member/mfg/equip-team/EQP-01 设备预测性维护
- scm-manager/member/scm/scm-team/SCM-01 库存智能预警与补货
- qas-engineer/member/qas/qas-team/QAS-01 售后粘接故障智能诊断
- admin-officer/member/admin/admin-team/ADM-01 跨系统经营数据汇总
- doc-clerk/member/admin/doc-team/DOC-01 文档智能处理与检索

LLM provider / 路由 / APIKey 完全照搬 starexploration（4 provider 占位 + 4 路由 + 1 组织级 Key + 每团队 Key），部署后用 README §3 SQL 从 agileac 复制真 key（aliyun-embedding-openai + aliyun-all-openai）。

## 3. Mock 系统端点（技能绑定用，全部 GET）
**FRM**（frm-starhma-demo-key）：listFormulas/getFormula/recommendFormula/predictPerformance/listExperiments/getExperiment/analyzeExperimentData/generateExperimentReport/listTestSamples/listTestSchemes/listFailureRecords
**PCM**（pcm-starhma-demo-key）：listProcessParams/recommendProcessParams/listEquipment/getEquipment/predictEquipmentFault/getEquipmentRunData/optimizeProductionSchedule/listScheduleRules
**QAS**（qas-starhma-demo-key）：listQualityReports/getQualityReport/generateInspectionReport/listCustomerComplaints/getCustomerComplaint/listFailureCases/diagnoseAfterSalesFault/analyzeRootCause/listNgRecords
**ERP**（erp-starhma-demo-key）：listSuppliers/getSupplier/listMaterials/getMaterial/listWarehouses/listPurchaseOrders/getPurchaseOrder/listInventory/listStockMovements/listPayables/listVouchers/listCostCenters/listProductionCosts
**MES**（mes-starhma-demo-key）：listProductionOrders/getProductionOrder/listWorkOrders/getWorkOrder/listEquipmentStatus/getEquipment/getOee/listDefects/getDefectRootCause/listShiftOutputs/listWip/getRouting/listHeats/getHeat
**CRM**（crm-starhma-demo-key）：listCustomers/getCustomer/listContacts/listOpportunities/getOpportunity/listQuotations/getQuotation/listSalesOrders/listFollowUps/listComplaints/getComplaint/listReceivables

### 9 技能绑定（dept-scope，按场景归口）
1. starhma-rd-frm-erp-query (rd): frm=[listFormulas,getFormula,recommendFormula,predictPerformance,listExperiments,listTestSamples,listFailureRecords] + erp=[listMaterials,listInventory]
2. starhma-rd-lab-frm-query (rd): frm=[listExperiments,getExperiment,analyzeExperimentData,generateExperimentReport,predictPerformance,listTestSchemes,listFailureRecords,listFormulas,getFormula]
3. starhma-sales-crm-frm-erp-query (sales): crm=[listCustomers,getCustomer,listOpportunities,getOpportunity,listQuotations,getQuotation,listSalesOrders,listFollowUps] + frm=[recommendFormula,getFormula,listFormulas] + erp=[listMaterials]
4. starhma-mfg-mes-pcm-erp-query (mfg): mes=[listWorkOrders,getWorkOrder,listProductionOrders,listShiftOutputs,listWip,listDefects] + pcm=[optimizeProductionSchedule,listScheduleRules,recommendProcessParams,listProcessParams] + erp=[listInventory,listMaterials,listProductionCosts]
5. starhma-eqp-pcm-mes-query (mfg): pcm=[listEquipment,getEquipment,predictEquipmentFault,getEquipmentRunData,listProcessParams,recommendProcessParams] + mes=[listEquipmentStatus,getEquipment]
6. starhma-scm-erp-crm-query (scm): erp=[listInventory,listMaterials,listPurchaseOrders,listStockMovements,listWarehouses,listSuppliers] + crm=[listSalesOrders]
7. starhma-qas-qas-crm-frm-query (qas): qas=[listCustomerComplaints,getCustomerComplaint,diagnoseAfterSalesFault,listFailureCases,analyzeRootCause,listNgRecords,listQualityReports,getQualityReport] + crm=[listCustomers,getCustomer,listComplaints] + frm=[getFormula,listFormulas]
8. starhma-admin-erp-crm-mes-query (admin): erp=[listVouchers,listPayables,listPurchaseOrders,listInventory,listProductionCosts,listCostCenters,listMaterials] + crm=[listSalesOrders,listCustomers,listReceivables,listComplaints] + mes=[listWorkOrders,listShiftOutputs,listProductionOrders]
9. starhma-admin-doc-erp-crm-query (admin): erp=[listPurchaseOrders,getPurchaseOrder,listVouchers,listCostCenters] + crm=[listSalesOrders,getCustomer,listCustomers]

## 4. 码空间与跨系统闭环（no-guessing identifiers）
- 配方 `FORM-`（FORM-STD-001/002/003 标准品 / FORM-CUS-001/002/003 定制）。标准品 product_code→ERP 成品胶 `M-FG-001/002/003`；定制配方转产→MES 批次 `BAT-`（formula_no 关联）。
- 原料组分 `ING-`（ING-RES-/ING-TK-/ING-WAX-/ING-AO-）→ ERP 采购物料 `M-RES-/M-TK-/M-WAX-/M-AO-`（prefix 转换 ING-RES-→M-RES-，勿互传）。
- 实验 `EXP-`（EXP-RHE- 流变 / EXP-TEN- 拉力 / EXP-ADH- 持粘）；性能预测 `PERF-`；样品 `SMP-`；测试方案 `TS-`；失效记录 `FR-`。
- 工艺参数 `PP-`（PP-STIR-/PP-REACT-/PP-COOL-），formula_no→FRM FORM-，product_code→ERP M-FG-。
- 设备 `EQ-`（EQ-RX- 反应釜 / EQ-MTR- 电机 / EQ-GRN- 造粒机），line→MES `LINE-`；排产建议 `PSCH-`；故障预测 `PM-`。
- 检测报告 `QR-`（QR-IN- 来料 / QR-FG- 成品），batch_no→MES BAT-，material_code→ERP M-，formula_no→FRM FORM-。
- 客诉 `CC-`（售后粘接故障：开胶/拉丝/堵枪/低温失效），customer_code→CRM `CLI-`，formula_no/batch_no→FRM/MES。
- 故障案例 `FC-`；不良品 `NG-`（batch_no→MES BAT-）；根因 `RCA-`。
- ERP：供应商 `S-HMA-`、物料 `M-`、仓 `WH-HMA-`、采购单 `POHMA`、应付 `HMAAP`、凭证 `BV-HMA-`、成本中心 `CC-HMA-`、生产成本 `PC-HMA-`（heat_no=BAT- 批次，work_order_no=CRM 合同 CT-HMA-）。
- MES：产线 `LINE-AUTO-01/02`+`LINE-03/04`、工单 `WO`、批次 `BAT-2026-0701..0704`、不良 `DF`。
- CRM：客户 `CLI-001..005`、询盘 `INQ-`、报价 `HMAQT-`、合同 `CT-HMA-001/002/003`、回款 `HMAAR-`、发票 `INV202607001..005`（与 ERP 凭证 BV-HMA- 按 invoice_no 对齐）、争议 `DSP-HMA-`。

**跨系统闭环**（8 条）：
1. FRM ING-RES-001 → ERP M-RES-001（组分→采购物料，prefix 转换）
2. FRM FORM-STD-001 → ERP M-FG-001（配方→成品胶）
3. FRM FORM-CUS-001 → MES BAT-2026-0703（定制配方→生产批次，formula_no）
4. PCM EQ- → MES LINE-（设备→产线，line）；PCM 排产 → MES WO（work_order_no）
5. MES BAT-2026-0702 → QAS QR-FG-2026-002 / NG-2026-001（批次→质检/不良）
6. QAS CC-2026-001 → CRM CLI-001（客诉→客户，customer_code）
7. CRM INV202607001 → ERP BV-HMA-2026-0701（发票→凭证，invoice_no）
8. CRM CT-HMA-001 → ERP PC-HMA-202607001（合同→生产成本，work_order_no）；MES BAT- → ERP PC-HMA-.heat_no

## 5. 本体文件（seed_starhma_ontology.py，6 域 + Cross）
6 域：FRM/PCM/QAS/ERP/MES/CRM。每域 README.md + object-types.md + link-types.md + action-types.md + identifiers.md，外加 cross/README.md + cross/identifiers.md（跨码空间映射，承载 §4 8 条闭环）。对象类型约 34+、链接类型 40+（跨系统 20+）。identifiers.md 写明每域码空间前缀 + 跨系统 prefix 转换规则（no-guessing 骨架）。

## 6. RAG 知识库（seed_starhma_rag.py，9 collection）
embedding text-embedding-v4，chunk 512/overlap 64。9 collection（名见表 §1），每 collection 入 6-10 文档（配方/实验/工艺/设备/库存/客诉/经营/合同等业务规则文档）。首次入库依赖 agileac 真 embedding key（README §3 SQL 同步后）。

## 7. Agent 配置（seed_starhma_agents.py，9 agent）
9 agent，四段 system_prompt（职责/RAG 检索/规则/输出格式，**不含场景代号**，用具体示例码）。model_alias=glm-5.2，exec_mode=craft，temperature=0.3，max_tokens=8192，template_agent_id 绑定（UUID 见 §1）。dept skill + RAG 绑定。org-scope 资源全员可见 + dept-scope 技能归口。

## 8. 各场景 composer（L1 短问题，不含场景代号）
- RDM-01: `对医疗用品低温热熔胶做配方智能推荐：客户基材无纺布/PE 膜、施胶温度 130℃、开放时间 6s、剥离力 14N、需 FDA 与 ISO-10993 环保、成本上限 40 元/kg；推荐历史相似配方 FORM-CUS-002 与初始配比 ING-RES-001/ING-TK-002，并给预估性能。`
- RDM-02: `对配方 FORM-CUS-002 做实验数据分析与报告生成：分析流变实验 EXP-RHE-001 与拉力实验 EXP-TEN-001 数据、识别异常、关联失效记录 FR-2025-021，生成标准化实验报告。`
- SAL-01: `对询盘 INQ-002 医疗用品客户做智能询盘：解析基材/工况需求、匹配配方 FORM-CUS-002、生成初步粘接方案与报价、联动样品 SMP-2026-002。`
- MFG-01: `做智能排产与订单冲突识别：综合 MES 工单 WO202607001..005 交期、产线 LINE-AUTO-01/02 与 LINE-03 负荷、换线成本，调 optimizeProductionSchedule 给排产建议与冲突订单。`
- EQP-01: `对设备 EQ-MTR-02 做预测性维护：调 predictEquipmentFault 看振动/温升/健康分，给风险等级与保养提醒，关联产线 LINE-AUTO-02 与工艺参数 PP-REACT-002。`
- SCM-01: `做库存智能预警与补货建议：查 ERP 原料 M-RES-001/M-TK-002/M-AO-001 与成品 M-FG-002 库存对比安全库存，列低库存预警与补货建议，联动采购单 POHMA 与销售预测。`
- QAS-01: `对客诉 CC-2026-001 开胶故障做智能诊断：调 diagnoseAfterSalesFault 按现象/基材/工况匹配故障案例 FC-2025-008 与历史客诉，给排查方案与配方 FORM-CUS-001 调整建议。`
- ADM-01: `做跨系统经营数据汇总：汇总 ERP 营收/采购/库存、CRM 订单/客户/回款、MES 产能/工单，生成经营简报（营收/产能/订单/客户统计+应收应付对账 INV↔BV-HMA-）。`
- DOC-01: `做文档智能处理与检索：检索合同 CT-HMA-001/002 与采购单 POHMA、凭证 BV-HMA- 的关键条款/摘要，提取付款里程碑与风险点，生成文档摘要。`

## 9. Seed 脚本清单与顺序
1. seed_starhma_org.py — 组织/部门/团队/用户/Provider/Routing/APIKey
2. seed_starhma_mock_connectors.py — Connector/DataSystem/DataInterface/Skill（6 系统 9 dept 技能），MOCK_BASE_URL=http://ai_infra_mock:8010
3. seed_starhma_ontology.py — 本体 6 域 + Cross
4. seed_starhma_rag.py — 9 RAG collection（依赖 embedding 真 key）
5. seed_starhma_agents.py — 9 agent 四段 prompt
