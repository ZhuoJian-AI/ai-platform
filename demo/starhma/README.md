# 星途热熔胶 AI 底座 POC demo

> 热熔胶制造企业 AI 底座 POC——参考 starclothing / agileac / agilesteel / agilestationery / starexploration 四层架构，9 场景按部门边界划分。slug `starhma`，组织名「星途热熔胶」。
> 两轮全完成：① demo + seed + P0 实测（9 场景端到端跑通）② 指南 HTML + 凭证访问页 + 真截图（9 终端 + 16 管理端）+ publish_guides.sh 加项发布。
> 对外地址：https://infra.aievolve.org.cn/guide/starhma-poc-guide.html ｜ https://infra.aievolve.org.cn/guide/starhma-poc-access.html

## 0. 业务背景
星途热熔胶（2005 年，杭州未来科技城，国家高新/专精特新），专注环保热熔胶/热熔压敏胶研发与生产。13 条产线（2 全自动），年产能 2 万吨，服务 4500+ 客户，覆盖汽车内饰/医疗/食品日化包装/物流快递袋/鞋材箱包/粘扣带/家居七大下游。战略：向「粘接解决方案服务商」转型。**配方数据为核心机密，需本地私有化**。配方研发（R&D）+ 工艺与设备（PCM）+ 质量与售后（QAS）三域为核心特色域。

mock 系统 6 套（3 新建 + 3 复用扩展）：**FRM** 配方研发管理 / **PCM** 工艺与设备管理 / **QAS** 质量与技术服务（新建）+ **ERP** 资源计划 / **MES** 制造执行 / **CRM** 客户管理（复用扩展）。

## 1. 痛点 → 场景映射
| 部门 | 痛点 | 旗舰场景 |
|---|---|---|
| 研发中心 | 配方设计依赖经验、相似配方复用难、初始配比靠手算 | RDM-01 配方智能推荐与初始配比 |
| 研发中心 | 实验数据散乱、异常难识别、报告生成耗时 | RDM-02 实验数据分析与报告生成 |
| 营销销售中心 | 询盘响应慢、初步粘接方案依赖人工、报价不联动样品 | SAL-01 智能询盘与初步粘接方案 |
| 生产制造部 | 排产靠经验、订单冲突识别滞后、换线成本不可控 | MFG-01 智能排产与订单冲突识别 |
| 生产制造部 | 设备故障被动维修、保养提醒不精准 | EQP-01 设备预测性维护与保养提醒 |
| 供应链部 | 库存预警滞后、补货建议不联动销售预测 | SCM-01 库存智能预警与补货建议 |
| 品质与技术服务部 | 售后粘接故障诊断靠经验、根因定位慢 | QAS-01 售后粘接故障智能诊断 |
| 综合管理部 | 跨系统经营数据汇总靠手工、对账繁琐 | ADM-01 跨系统经营数据汇总 |
| 综合管理部 | 文档处理量大、合同/凭证关键条款提取难 | DOC-01 文档智能处理与检索 |
| 信息中心 | （无对外场景，底座承载） | — |

## 2. 演示矩阵
见 [SCENARIO_ROSTER.md](SCENARIO_ROSTER.md)：9 场景 × 部门 × 登录用户 × model × skill × RAG × template_agent_id × Phase。

## 3. 前置条件
- docker compose 起 pg / redis / backend / mock
- mock 网关 :8010 含 frm/pcm/qas（`docker restart ai_infra_mock` 加载新系统）
- backend 注入 mock 包（A1，注意勿建嵌套 /app/mock/mock/）：
  ```bash
  docker exec ai_infra_backend rm -rf /app/mock/mock
  docker cp mock/mock/core/registry.py ai_infra_backend:/app/mock/core/registry.py
  docker cp mock/mock/systems/frm ai_infra_backend:/app/mock/systems/frm
  docker cp mock/mock/systems/pcm ai_infra_backend:/app/mock/systems/pcm
  docker cp mock/mock/systems/qas ai_infra_backend:/app/mock/systems/qas
  docker cp mock/mock/systems/erp/data.py ai_infra_backend:/app/mock/systems/erp/data.py
  docker cp mock/mock/systems/mes/data.py ai_infra_backend:/app/mock/systems/mes/data.py
  docker cp mock/mock/systems/crm/data.py ai_infra_backend:/app/mock/systems/crm/data.py
  ```
- LLM provider 真 key 同步：org seed 落 4 占位 provider 后，从 agileac 复制 aliyun-embedding-openai + aliyun-all-openai 含加密 key，GLM/DeepSeek 路由指向 aliyun-all-openai（A3 SQL）
- 5 seed 脚本按序执行

## 4. 组织 / 部门 / 团队 / 用户
- org slug `starhma`，7 部门（rd/sales/mfg/scm/qas/admin/it），11 团队，11 用户（admin + 9 场景用户 + it-specialist），统一口令 `12345678`
- 终端登录 `/starhma/terminal/login`，管理端登录用 admins 表（A10）
- 团队划分（每部门 1-2 个）：
  - rd：formula-team(配方研发组) / lab-team(应用测试实验室)
  - sales：sales-team(国内销售+技术销售组)
  - mfg：schedule-team(生产排产组) / equip-team(设备运维组)
  - scm：scm-team(采购仓储组)
  - qas：qas-team(品质与售后技术组)
  - admin：admin-team(企管行政组) / doc-team(文档资质组)
  - it：it-infra(系统运维组) / it-ai(AI 应用组)

## 5. Mock 系统改造
**3 新建 leaf**（`tenants=("starhma",)`）：
- **FRM** 配方研发管理：配方 `FORM-`（FORM-STD-001/002/003 标准品 / FORM-CUS-001/002/003 定制）/ 原料组分 `ING-`（ING-RES-/ING-TK-/ING-WAX-/ING-AO-）/ 实验 `EXP-`（EXP-RHE- 流变 / EXP-TEN- 拉力 / EXP-ADH- 持粘）/ 性能预测 `PERF-` / 样品 `SMP-` / 测试方案 `TS-` / 失效记录 `FR-`；端点 listFormulas/getFormula/recommendFormula/predictPerformance/listExperiments/getExperiment/analyzeExperimentData/generateExperimentReport/listTestSamples/listTestSchemes/listFailureRecords
- **PCM** 工艺与设备管理：工艺参数 `PP-`（PP-STIR-/PP-REACT-/PP-COOL-）/ 设备 `EQ-`（EQ-RX- 反应釜 / EQ-MTR- 电机 / EQ-GRN- 造粒机）/ 排产建议 `PSCH-` / 故障预测 `PM-`；端点 listProcessParams/recommendProcessParams/listEquipment/getEquipment/predictEquipmentFault/getEquipmentRunData/optimizeProductionSchedule/listScheduleRules
- **QAS** 质量与技术服务：检测报告 `QR-`（QR-IN- 来料 / QR-FG- 成品）/ 客诉 `CC-`（开胶/拉丝/堵枪/低温失效）/ 故障案例 `FC-` / 不良品 `NG-` / 根因 `RCA-`；端点 listQualityReports/getQualityReport/generateInspectionReport/listCustomerComplaints/getCustomerComplaint/listFailureCases/diagnoseAfterSalesFault/analyzeRootCause/listNgRecords

**3 复用扩展**（各加 `_build_starhma()` + tenant 行 + `<sys>-starhma-demo-key`）：
- ERP：供应商 `S-HMA-` / 物料 `M-`（M-RES-/M-TK-/M-WAX-/M-AO-/M-FG-）/ 仓 `WH-HMA-` / 采购单 `POHMA` / 应付 `HMAAP` / 凭证 `BV-HMA-` / 成本中心 `CC-HMA-` / 生产成本 `PC-HMA-`（heat_no=BAT- 批次，work_order_no=CRM 合同 CT-HMA-）
- MES：产线 `LINE-AUTO-01/02`+`LINE-03/04` / 工单 `WO` / 批次 `BAT-2026-0701..0704` / 不良 `DF` / 工序 Routing / 炉次 Heat
- CRM：客户 `CLI-001..005` / 询盘 `INQ-` / 报价 `HMAQT-` / 合同 `CT-HMA-001/002/003` / 回款 `HMAAR-` / 发票 `INV202607001..005`（与 ERP 凭证 BV-HMA- 按 invoice_no 对齐）/ 争议 `DSP-HMA-`

## 6. RAG 知识库
9 collection（按场景 dept 归口，名见 SCENARIO_ROSTER §1），embedding text-embedding-v4，chunk 512/overlap 64。每 collection 入 6-10 文档（配方/实验/工艺/设备/库存/客诉/经营/合同等业务规则文档）。首次入库依赖 agileac 真 embedding key（README §3 SQL 同步后）。

## 7. 本体文件
6 域（FRM/PCM/QAS/ERP/MES/CRM）+ Cross，每域 README.md / object-types.md / link-types.md / action-types.md / identifiers.md，外加 cross/README.md + cross/identifiers.md（跨码空间映射，承载 §4 8 条闭环）。约 34+ 对象类型、40+ 链接类型（跨系统 20+）。identifiers.md 写明每域码空间前缀 + 跨系统 prefix 转换规则（no-guessing 骨架，A7）。

## 8. Agent 配置
9 agent，四段 system_prompt（职责/RAG 检索/规则/输出格式，**不含场景代号**，用具体示例码 FORM-CUS-002/EXP-RHE-001/ING-RES-001/M-RES-001/M-FG-002/BAT-2026-0702/CC-2026-001/EQ-MTR-02/INQ-002/CT-HMA-001/INV202607001/BV-HMA-2026-0701）。model_alias=glm-5.2，exec_mode=craft，temperature=0.3，max_tokens=8192，template_agent_id 绑定（UUID 见 SCENARIO_ROSTER）。dept skill + RAG 绑定。org-scope 资源全员可见 + dept-scope 技能归口。

## 9. Seed 脚本清单与顺序
1. `seed_starhma_org.py` — 组织/部门/团队/用户/Provider/Routing/APIKey
2. `seed_starhma_mock_connectors.py` — Connector/DataSystem/DataInterface/Skill（6 系统 9 dept 技能），`MOCK_BASE_URL=http://ai_infra_mock:8010`
3. `seed_starhma_ontology.py` — 本体 6 域 + Cross
4. `seed_starhma_rag.py` — 9 RAG collection（依赖 embedding 真 key）
5. `seed_starhma_agents.py` — 9 agent 四段 prompt

执行：
```bash
docker cp demo/starhma/scripts/seed_*.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_starhma_org.py
docker exec -e MOCK_BASE_URL=http://ai_infra_mock:8010 ai_infra_backend python scripts/seed_starhma_mock_connectors.py
docker exec ai_infra_backend python scripts/seed_starhma_ontology.py
docker exec ai_infra_backend python scripts/seed_starhma_rag.py        # 真 key 已复制后
docker exec ai_infra_backend python scripts/seed_starhma_agents.py
```

## 10. 演示运行
终端 `/starhma/terminal/login` → 选场景用户登录 → 新建任务 → TaskConfig(model=glm-5.2 / exec_mode=craft / 绑 template agent / 勾归口技能) → 粘贴 composer（见各 *_terminal_task.md）→ 提交观察 SSE。curl 三步复现见各 terminal_task §6。

## 11. 跨场景合并原则
- 部门内不合并；跨部门不合并；IT 无场景（同 agilestationery/starexploration）
- 跨系统闭环靠本体 identifiers.md no-guessing 映射 + L4 数据接口目录，agent 自主规划端点

## 12. 验收清单
- [ ] 9 agent（9 skill + 9 RAG + 9 dept scope）
- [ ] 6 系统 mock（3 新 FRM/PCM/QAS + 3 复用 ERP/MES/CRM）+ openapi 快照
- [ ] 6 域 + Cross 本体文件 + 8 跨系统闭环
- [ ] P0 实测选定 RDM-01 / SAL-01 / MFG-01 端到端通过（覆盖新建 FRM/PCM + 复用 ERP/MES/CRM）

## 13. 文件清单
```
demo/starhma/
  README.md / SCENARIO_ROSTER.md / KNOWN_ISSUES.md / DESIGN_SPEC.md
  CROSS_AGENT_HANDOFF_DESIGN.md -> ../starclothing/  (symlink)
  NEW_ORG_DEMO_CHECKLIST.md -> ../starclothing/       (symlink)
  SCENARIO_AUTHORING_GUIDE.md -> ../starclothing/     (symlink)
  rdm_01_terminal_task.md / rdm_02_ / sal_01_ / mfg_01_ /
  eqp_01_ / scm_01_ / qas_01_ / adm_01_ / doc_01_terminal_task.md
  scripts/
    seed_starhma_org.py / seed_starhma_mock_connectors.py /
    seed_starhma_ontology.py / seed_starhma_rag.py /
    seed_starhma_agents.py
mock/mock/systems/{frm,pcm,qas}/  + erp/mes/crm data.py + registry.py + openapi/{frm,pcm,qas}.json
```

## 14. 实施优先级
- P0（高优先级）：RDM-01 / RDM-02 / SAL-01 / MFG-01 / SCM-01 / QAS-01 / ADM-01 / DOC-01
- P1（管理价值）：EQP-01
- P2（后续）：产线数字孪生运营 / 环保排放预警 / 配方专利检索（按需扩展）

## 15. 与其它 demo 的关系
| 维度 | 星途热熔胶 | starexploration | agilesteel | agilestationery |
|---|---|---|---|---|
| 行业 | 热熔胶制造 | 勘探设计 | 钢铁制造 | 文具贸易 |
| 场景 | 9 | 9 | 9 | 9 |
| mock 系统 | 6（3 新 FRM/PCM/QAS + 3 复用 ERP/MES/CRM） | 6（3 新 DES/EPC/SEC + 3 复用 ERP/HRM/CRM） | 9（3 新 EQM/EMS/EHS + 6 复用） | 7（3 新 PIM/CST/CHN + 4 复用） |
| 主实体 | 配方 FORM-/批次 BAT-/设备 EQ-/客诉 CC- | 方案 SCH-/项目 PRJ-/图纸 DWG-/合同 CT-SE- | 炉次 HT/工单 SWO | SKU-ZB-/报关单 CD- |
| 特色域 | 配方研发 FRM | 涉密检测脱密 SEC | 设备预测维护 EQM | 渠道防伪 PIM |
| model | glm-5.2 | glm-5.2 | glm-5.2 | glm-5.2 |
| 架构 | 四层（同构） | 四层 | 四层 | 四层 |
| provider | 从 agileac 复制 aliyun 真 key | 同 | 同 | 同 |
| 多模态 | 全文本（无感知类） | 感知类仅文本 | 剔除 | 剔除 |

## 16. 后续行动
- [x] P0 实测选定 RDM-01 / SAL-01 / MFG-01 / QAS-01 端到端跑通（见下「实测状态」）
- [x] 第二轮：指南 HTML + starhma-poc-access.html + 真截图（9 终端 + 16 管理端）+ publish_guides.sh 加项发布（按 [[guide-html-generation-method]] + [[guide-credentials-in-separate-appendix]]）
- [x] 9 场景截图采集（capture_terminal.js + capture_mgmt.js，admin 行手插 admins 表后管理端可登录）
- P2 场景按需扩展（数字孪生/环保预警/专利情报/客户流失预警）

## 实测状态（2026-07-25）
**9 场景全部端到端实测 + 截图采集通过**（glm-5.2 / aliyun-all-openai 配额可用，embedding 通道生效）：

| 场景 | template:true | RAG vector hits | 6 trace | tool_calls | 文本 deltas | 输出大小 | 真实码无 404 |
|---|---|---|---|---|---|---|---|
| RDM-01 配方智能推荐 | ✅ | ✅ | ✅ | 17 | 1646 | 100KB | ✅ FORM-CUS-002/ING-RES-001/M-RES-001 |
| SAL-01 智能询盘 | ✅ | ✅ | ✅ | 11 | 1686 | 90KB | ✅ INQ-002/FORM-CUS-002/SMP-2026-002 |
| MFG-01 智能排产 | ✅ | ✅ | ✅ | 7 | 34 | 22KB | ✅ WO202607001/LINE-AUTO-01/optimizeProductionSchedule |
| QAS-01 售后故障诊断 | ✅ | ✅ | ✅ | 9 | 1634 | 87KB | ✅ CC-2026-001/FC-2025-008/FORM-CUS-001 |

- 6 trace = template / rag(retriever=vector) / memory.load / ontology(35 files) / data_interface / memory.extract
- tool_call 用真实码（no-guessing），跨码空间 prefix 转换正确（ING-RES-→M-RES-、INV↔BV-HMA-、CC-→CLI-），无真实 404
- 多段文本上屏（34-1686 deltas / 22-100KB），latency 68-180s，无 insufficient_quota
- 截图：9 终端（每场景 top+bottom）+ 16 管理端（org/users/keys/providers/dlp/workspaces/agents/rag/memory/data-interfaces/skills/ontology/monitor×4）
