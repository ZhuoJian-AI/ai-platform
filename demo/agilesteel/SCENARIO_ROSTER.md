# 敏睿钢铁 Demo 场景总览（SCENARIO_ROSTER）

> 9 场景 = 9 部门 × 1 旗舰场景。四层架构：L1 短 composer / L2 模板四段 system_prompt /
> L3 org-scope identifiers.md / L4 数据接口目录。org-scope 资源全员可见，dept-scope 技能归口部门。
> 喂 LLM 的内容不含场景代号（MFG-01 等），用具体示例（HT2026062901 / P-ST-Q345B / EQ-CV-2）。

## 总览表

| 场景 | 任务名（对象+动作+闭环） | 归口部门 | 登录用户 | 模型 | 技能 slug | RAG(scope) | template_agent_id | Phase |
|---|---|---|---|---|---|---|---|---|
| MFG-01 | 转炉终点碳温预测与一体化排产 | 生产制造部 | mfg-planner | glm-5.2 | agilesteel-production-mes-erp-query | 排产与炼钢规则库(dept) | `528bb570-9f30-4769-b54c-ff89ae630ef7` | P0 |
| EQP-01 | 关键设备预测性维护与备件建议 | 设备管理部 | eqp-engineer | glm-5.2 | agilesteel-equipment-eqm-query | 设备故障案例库(dept) | `736bae0e-8d55-43df-b2ed-4d0fc455ad1f` | P0 |
| SAL-01 | 销售需求预测与订单评审交期答复 | 销售公司 | sal-ops | glm-5.2 | agilesteel-sales-crm-erp-query | 客户画像与行情库(dept) | `a8c0f1b7-50ca-4511-bab3-2af295a2ff97` | P0 |
| QAL-01 | 表面缺陷检测与质量追溯 | 质量管理部 | qal-engineer | glm-5.2 | agilesteel-quality-mes-plm-query | 质量缺陷案例库(dept) | `9c8add96-7c8e-4c02-8721-34760bfd15aa` | P1 |
| SCM-01 | 大宗原料价格预测与供应商风控 | 采购与供应链管理部 | scm-buyer | glm-5.2 | agilesteel-supply-scm-erp-query | 供应商资质与行情库(dept) | `3793709f-9bc5-430a-8eaf-aba0bde7303b` | P1 |
| FIN-01 | 分钢种成本核算与多系统对账 | 财务部 | fin-accountant | glm-5.2 | agilesteel-finance-erp-mes-scm-plm-crm-query | None（规则在模板） | `1b12d355-d41c-46bc-afbf-ceff8c44c668` | P1 |
| ENE-01 | 能源介质平衡调度与排放预警 | 能源环保部 | ene-dispatcher | glm-5.2 | agilesteel-energy-ems-query | 能源调度规则库(dept) | `0a7c2db4-56f6-4418-827b-11ba5866ac62` | P2 |
| SAF-01 | 现场违章识别与隐患排查 | 安全环保部 | saf-inspector | glm-5.2 | agilesteel-safety-ehs-query | 安全法规与隐患案例库(dept) | `97afc5c4-8609-4ec6-9b82-4bf11c4d317b` | P2 |
| HR-01 | 招聘人岗匹配 | 人力资源部 | hr-recruiter | glm-5.2 | agilesteel-hr-hrm-query | 岗位JD库(team) | `ff7a8ae4-a7b0-4f15-897c-764736ba740d` | P2 |

> 密码统一 `12345678`。终端登录 `/agilesteel/terminal/login`。

## composer（L1，纯业务问题+对象+技能 chip，不写编排）

- **MFG-01**：`对当前在制炉次做转炉终点碳温命中率预测 + 炼钢-连铸-轧钢一体化排产方案，重点 HT2026063001（P-ST-Q345B，EQ-CV-1 在制）、HT2026063002（P-ST-45#，EQ-CV-2 待吹炼）。扫所有未完工炉次，按钢种检索排产与炼钢规则库给排产优先级与命中率预测。

/agilesteel-production-mes-erp-query`
- **EQP-01**：`对关键设备做预测性维护与备件建议，重点 EQ-CV-2（2#转炉，fault）、EQ-RM-3（3#连轧机，maintenance）。扫所有待执行维护建议，按设备类型检索设备故障案例库给根因/排查/备件/优先级。

/agilesteel-equipment-eqm-query`
- **SAL-01**：`对当前在制销售订单做需求预测与交期答复，重点 ASSO202607001（P-ST-Q345B，C-AS-PROJ-01 桥梁项目）、ASSO202607005（P-ST-40Cr，C-AS-OEM-01 三一直供）。扫所有未交付订单，按品种检索客户画像与行情库给需求预测与评审结论。

/agilesteel-sales-crm-erp-query`
- **QAL-01**：`对当前未闭环钢材表面缺陷做根因分析与全流程质量追溯，重点 DF20260701（P-ST-Q345B 表面裂纹）、DF20260703（P-ST-40Cr 非金属夹杂）。扫所有未闭环缺陷，按缺陷类型检索质量缺陷案例库给根因/纠正/预防与追溯链路。

/agilesteel-quality-mes-plm-query`
- **SCM-01**：`对大宗原料做价格预测与供应商风控，重点 M-ORE-FINE（铁矿石 62%，2 家比价）、M-SCR-HMS1（废钢重废1型，2 家比价）。扫所有在有效期报价，按品类检索供应商资质与行情库给比价建议与废钢判级。

/agilesteel-supply-scm-erp-query`
- **FIN-01**：`做分钢种炉次成本核算与五方对账，重点炉次 HT2026062901（P-ST-Q345B）/HT2026062902（P-ST-45#）+ 凭证 BV-AS-2026-0512（财务复核中）。扫所有炉次成本，按凭证/报价/台账/应收做五方对账，差异率>2% 标异常。

/agilesteel-finance-erp-mes-scm-plm-crm-query`
- **ENE-01**：`对本班次做能源介质平衡调度与排放预警，重点煤气放散（EM-GAS-BF1 压力低）+ 烧结 SO2（EMS-SO2-SINTER 临界）。扫所有介质缺口与排放临界，按介质检索能源调度规则库给调度方案与碳足迹。

/agilesteel-energy-ems-query`
- **SAF-01**：`对当前未闭环隐患做违章分类与闭环管理，重点 HD20260002（1#高炉煤气泄漏，红）、HD20260001（2#转炉液渣喷溅，红）。扫所有未闭环隐患，按违章类型检索安全法规与隐患案例库给分类/规程/整改优先级。

/agilesteel-safety-ehs-query`
- **HR-01**：`对炼钢工程师 P-MELT 岗位做简历筛选与人岗匹配。

/agilesteel-hr-hrm-query`

## 演示速查（curl 复现）

详见各 `*_terminal_task.md` §6 手工调 API 复现。template_agent_id 落库后取自上表（重跑 seed 后可能变，查 `SELECT id FROM agents WHERE slug='agilesteel-...'`）。
