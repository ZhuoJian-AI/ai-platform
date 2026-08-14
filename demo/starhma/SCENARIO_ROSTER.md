# 星途热熔胶 POC 场景总表（SCENARIO_ROSTER）

> 单一事实源：本表 + 各 `*_terminal_task.md` H1 标题 + curl `title` 字段 + README §1/§5「场景」列。
> 设计原则：四层架构 L1 短 composer / L2 模板四段 system_prompt / L3 org-scope identifiers.md / L4 数据接口目录。
> 命名约定：对象+动作+闭环产出式（去「数字/AI/自动化」修饰）。喂 LLM 的 prompt 不含场景代号（RDM-01 等），用具体示例（FORM-CUS-002/EXP-RHE-001/ING-RES-001/M-RES-001/M-FG-002/BAT-2026-0702/CC-2026-001/EQ-MTR-02/INQ-002/CT-HMA-001/INV202607001/BV-HMA-2026-0701）。

## 总览表

| 场景 | 任务名（对象+动作+闭环） | 部门(slug) | 登录用户 | Model | Skill slug | RAG(scope) | template_agent_id | Phase |
|---|---|---|---|---|---|---|---|---|
| RDM-01 | 配方智能推荐与初始配比 | 研发中心(rd) | rd-formulator | glm-5.2 | starhma-rd-frm-erp-query | dept(rd) | `e5188ebd-24e3-4adc-8fa7-8118832da288` | P0 |
| RDM-02 | 实验数据分析与报告生成 | 研发中心(rd) | rd-analyst | glm-5.2 | starhma-rd-lab-frm-query | dept(rd) | `fe5e56d7-84cc-426a-920d-a8a17d90be71` | P0 |
| SAL-01 | 智能询盘与初步粘接方案 | 营销销售中心(sales) | sales-rep | glm-5.2 | starhma-sales-crm-frm-erp-query | dept(sales) | `911847f5-57a3-43f5-8d5b-b98b92918e21` | P0 |
| MFG-01 | 智能排产与订单冲突识别 | 生产制造部(mfg) | mfg-planner | glm-5.2 | starhma-mfg-mes-pcm-erp-query | dept(mfg) | `f881da63-63d9-4d6d-a6ff-71ec404941c8` | P0 |
| EQP-01 | 设备预测性维护与保养提醒 | 生产制造部(mfg) | eqp-maintainer | glm-5.2 | starhma-eqp-pcm-mes-query | dept(mfg) | `9f6a623a-88dd-4b3c-a40f-3b58e6fb1872` | P1 |
| SCM-01 | 库存智能预警与补货建议 | 供应链部(scm) | scm-manager | glm-5.2 | starhma-scm-erp-crm-query | dept(scm) | `31065753-d025-44a4-8d7d-3fd48d5a0864` | P0 |
| QAS-01 | 售后粘接故障智能诊断 | 品质与技术服务部(qas) | qas-engineer | glm-5.2 | starhma-qas-qas-crm-frm-query | dept(qas) | `011fa0f8-ef5a-417e-a1a4-881694794c81` | P0 |
| ADM-01 | 跨系统经营数据汇总 | 综合管理部(admin) | admin-officer | glm-5.2 | starhma-admin-erp-crm-mes-query | dept(admin) | `269c904a-9a0b-4f35-81e1-2522e90989bf` | P0 |
| DOC-01 | 文档智能处理与检索 | 综合管理部(admin) | doc-clerk | glm-5.2 | starhma-admin-doc-erp-crm-query | dept(admin) | `3c14d454-8f08-4e70-a613-83c14387036c` | P0 |

+ 信息中心(it) 无场景，仅作底座承载。共 7 部门、11 用户（admin + 9 场景用户 + it-specialist）、统一口令 `12345678`、终端登录 `/starhma/terminal/login`。

**P0 实测选定**：RDM-01 / SAL-01 / MFG-01 —— 分别覆盖新建 FRM/PCM 域、复用 ERP/MES/CRM，验证三新（FRM/PCM/QAS）三旧（ERP/MES/CRM）系统全打通。

## 各场景 composer（L1 短问题 + 技能 chip）

> composer 是终端任务创建时粘贴的短用户提示，不含编排、不含场景代号，靠 template_agent_id 注入四层 prompt + bound skill 提供工具。技能 chip 在 TaskConfig 勾选归口部门技能后自动绑定，composer 正文不写 chip（chip 由 template agent 的 skill_ids 提供）。

### RDM-01 配方智能推荐与初始配比
```
对医疗用品低温热熔胶做配方智能推荐：客户基材无纺布/PE 膜、施胶温度 130℃、开放时间 6s、剥离力 14N、需 FDA 与 ISO-10993 环保、成本上限 40 元/kg；推荐历史相似配方 FORM-CUS-002 与初始配比 ING-RES-001/ING-TK-002，并给预估性能。
```

### RDM-02 实验数据分析与报告生成
```
对配方 FORM-CUS-002 做实验数据分析与报告生成：分析流变实验 EXP-RHE-001 与拉力实验 EXP-TEN-001 数据、识别异常、关联失效记录 FR-2025-021，生成标准化实验报告。
```

### SAL-01 智能询盘与初步粘接方案
```
对询盘 INQ-002 医疗用品客户做智能询盘：解析基材/工况需求、匹配配方 FORM-CUS-002、生成初步粘接方案与报价、联动样品 SMP-2026-002。
```

### MFG-01 智能排产与订单冲突识别
```
做智能排产与订单冲突识别：综合 MES 工单 WO202607001..005 交期、产线 LINE-AUTO-01/02 与 LINE-03 负荷、换线成本，调 optimizeProductionSchedule 给排产建议与冲突订单。
```

### EQP-01 设备预测性维护与保养提醒
```
对设备 EQ-MTR-02 做预测性维护：调 predictEquipmentFault 看振动/温升/健康分，给风险等级与保养提醒，关联产线 LINE-AUTO-02 与工艺参数 PP-REACT-002。
```

### SCM-01 库存智能预警与补货建议
```
做库存智能预警与补货建议：查 ERP 原料 M-RES-001/M-TK-002/M-AO-001 与成品 M-FG-002 库存对比安全库存，列低库存预警与补货建议，联动采购单 POHMA 与销售预测。
```

### QAS-01 售后粘接故障智能诊断
```
对客诉 CC-2026-001 开胶故障做智能诊断：调 diagnoseAfterSalesFault 按现象/基材/工况匹配故障案例 FC-2025-008 与历史客诉，给排查方案与配方 FORM-CUS-001 调整建议。
```

### ADM-01 跨系统经营数据汇总
```
做跨系统经营数据汇总：汇总 ERP 营收/采购/库存、CRM 订单/客户/回款、MES 产能/工单，生成经营简报（营收/产能/订单/客户统计+应收应付对账 INV↔BV-HMA-）。
```

### DOC-01 文档智能处理与检索
```
做文档智能处理与检索：检索合同 CT-HMA-001/002 与采购单 POHMA、凭证 BV-HMA- 的关键条款/摘要，提取付款里程碑与风险点，生成文档摘要。
```

## Demo 速查（curl 三步复现）

见各 `*_terminal_task.md` §6。统一三步：
1. `POST /api/v1/users/login-by-slug` 取 JWT（slug=starhma, username/password=12345678）
2. `POST /api/v1/terminal/tasks` 创建任务（config 带 template_agent_id + exec_mode=craft + model_alias=glm-5.2）
3. `POST /api/v1/terminal/tasks/$TASK/run` 跑任务（message=composer，stream=true）
