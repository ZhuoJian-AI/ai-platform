# 敏睿文具 Demo 场景总览（SCENARIO_ROSTER）

> 9 场景 = 9 部门 × 1 旗舰场景（行政与IT 部作支持，不设场景）。四层架构：L1 短 composer /
> L2 模板四段 system_prompt / L3 org-scope identifiers.md / L4 数据接口目录。org-scope 资源
> 全员可见，dept-scope 技能归口部门。喂 LLM 的内容不含场景代号（SAL-01 等），用具体示例
> （DLR-01 / SKU-ZB-G001 / CD202607001 / CTF20260701 / EV20260701）。剔除多模态生成——
> 营销物料仅纯文本，假货识别为感知类图像比对（不生成）。

## 总览表

| 场景 | 任务名（对象+动作+闭环） | 归口部门 | 登录用户 | 模型 | 技能 slug | RAG(scope) | template_agent_id | Phase |
|---|---|---|---|---|---|---|---|---|
| SAL-01 | 渠道健康度监测与销售补货预测 | 销售管理部 | sal-channel | glm-5.2 | agilestationery-sales-crm-erp-query | 经销商画像与渠道规则库(dept) | `31c218ce-605c-4844-85e7-fc81a37477a3` | P0 |
| SCM-01 | 报关单证智能处理与库存补货规划 | 供应链与物流部 | scm-customs | glm-5.2 | agilestationery-supply-cst-scm-erp-query | 报关合规与库存规则库(dept) | `a547d723-6bde-4edb-b400-f5d9d39c4787` | P0 |
| PRD-01 | 渠道假货识别与全渠道反馈分析 | 产品管理部 | prd-quality | glm-5.2 | agilestationery-product-pim-query | 假货特征与产品标准库(dept) | `083e3434-0ca8-4968-8752-4384784ad201` | P0 |
| ECM-01 | 线上渠道秩序管控与渠道效能分析 | 电商渠道部 | ecm-ops | glm-5.2 | agilestationery-ecom-chn-crm-query | 渠道秩序与平台规则库(dept) | `e2d0ac89-fbca-4a8a-99de-2ec4a47f0f3a` | P1 |
| FIN-01 | 发票识别审核与费用对账 | 财务部 | fin-accountant | glm-5.2 | agilestationery-finance-erp-cst-crm-query | 财务合规与发票规则库(dept) | `51c787d2-34ac-46dd-8004-f05bbafa5b12` | P1 |
| SVC-01 | 售后工单智能处理与B端客服辅助 | 客户服务部 | svc-agent | glm-5.2 | agilestationery-service-crm-erp-query | 售后政策与工单规则库(dept) | `3ea7092f-4a06-4619-9790-d23e81cdf0e6` | P1 |
| MKT-01 | 竞品动态监测与B端营销物料生成 | 市场营销部 | mkt-analyst | glm-5.2 | agilestationery-mkt-chn-query | 竞品情报与营销物料库(dept) | `a54ea1b8-2d19-435c-a3c2-6fcd1d053856` | P2 |
| LEG-01 | 合同智能审核与渠道维权合规 | 法务合规部 | leg-counsel | glm-5.2 | agilestationery-legal-chn-crm-query | 合同条款与合规规则库(dept) | `52393ef8-7b1e-41a0-85de-ab351f6637c0` | P2 |
| HR-01 | 招聘人岗匹配与人事事务 | 人力资源部 | hr-recruiter | glm-5.2 | agilestationery-hr-hrm-query | 岗位JD与人事制度库(team) | `005f421e-8a18-42f3-aa02-325b34ff5bc4` | P2 |

> 密码统一 `12345678`。终端登录 `/agilestationery/terminal/login`。
> 辅助用户：sal-ka（销售/KA）、scm-logistics（物流）、fin-receivable（应收）、hr-trainer（培训薪酬）、it-specialist/it-infra（平台运维）。

## composer（L1，纯业务问题+对象+技能 chip，不写编排）

- **SAL-01**：`对经销商渠道做健康度监测 + 销售预测与补货建议，重点 DLR-01（华东经销商）、DLR-03（华南）。扫所有经销商与未交付订单，按渠道检索经销商画像与渠道规则库给健康度评分与补货建议。

/agilestationery-sales-crm-erp-query`
- **SCM-01**：`对当前进口报关单做单证识别与合规校验 + 库存补货规划，重点 CD202607001（SKU-ZB-G001 中性笔，已申报）、CD202607005（中性笔 0.4，异常-归类存疑）+ 发票 INV202607001 验真。扫所有在途报关单与低库存 SKU，按品类检索报关合规与库存规则库给归类/合规/补货/汇率建议。

/agilestationery-supply-cst-scm-erp-query`
- **PRD-01**：`对渠道抽检样本做假货识别与全渠道反馈分析，重点 CTF20260701（SKU-ZB-G001 华南电商抽检，假货）、CTF20260704（SKU-ZB-M001 华北电商抽检，假货）+ 反馈 FB20260706（中性笔整批笔尖偏磨，严重）。扫所有假货样本与反馈，按产品检索假货特征与产品标准库给鉴定/分布/反馈/改进建议。

/agilestationery-product-pim-query`
- **ECM-01**：`对线上渠道做秩序管控与渠道效能分析，重点 MR-EC-09（淘宝冒名店，假冒+低价）、MR-DL-12（义乌窜货商，假冒+跨区）+ 渠道效能拼多多 ROI 下降。扫所有非授权店铺与违规取证，按渠道检索渠道秩序与平台规则库给风险队列与处置建议。

/agilestationery-ecom-chn-crm-query`
- **FIN-01**：`做发票识别审核与费用对账，重点发票 INV202607001（进项，关联凭证 BV-AS-2026-0701）、INV202607007（存疑-发票代码异常）+ 应收 DLR-03 逾期。扫所有发票与凭证/应付/应收做对账，差异率>2% 标异常，按场景检索财务合规与发票规则库给验真/对账/催收建议。

/agilestationery-finance-erp-cst-crm-query`
- **SVC-01**：`对当前售后工单做智能处理与客服辅助，重点 CASE-0002（KA-02 笔夹松动脱落，严重，8D）、CASE-0006（DLR-01 中性笔整批笔尖偏磨，严重，8D）+ CASE-0005（运输破损补发）。扫所有未闭环工单，按问题类型检索售后政策与工单规则库给资质校验/分派/超时升级建议。

/agilestationery-service-crm-erp-query`
- **MKT-01**：`做竞品动态监测与 B 端营销物料生成，重点 CMP-01（百乐 V5 新品线上加码）、CMP-02（三菱政企集采）。扫所有竞品动态，按品类检索竞品情报与营销物料库给竞品周报 + 中性笔订货会宣讲文案（纯文本）+ 合规初审。

/agilestationery-mkt-chn-query`
- **LEG-01**：`做合同智能审核与渠道维权合规，重点 MR-EC-09（淘宝冒名店，取证 EV20260701 + 假货 CTF20260701）、MR-EC-15（拼多多冒名，EV20260706 + CTF20260706）。扫所有违规取证，按场景检索合同条款与合规规则库给合同风险条款/维权清单/合规审查。

/agilestationery-legal-chn-crm-query`
- **HR-01**：`对电商运营专员 P-EC 岗位做简历筛选与人岗匹配，招聘需求 ASRC（headcount 2，紧急）。扫该岗位所有简历，按岗位检索岗位JD与人事制度库给 5 维度评估排序 + 推荐短名单 + 面试题 + 到岗催办。

/agilestationery-hr-hrm-query`

## 演示速查（curl 复现）

详见各 `*_terminal_task.md` §6 手工调 API 复现。template_agent_id 落库后取自上表（重跑 seed 后可能变，查 `SELECT id FROM agents WHERE slug='agilestationery-...'`）。
