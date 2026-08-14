# 敏睿文具 · 9 场景 Demo 演示

> 文具贸易企业 AI 应用 demo——9 部门 × 1 旗舰场景，进口贸易 + B 端分销 + 渠道管控 + 防伪维权。
> 复用 agileac/agilesteel 四层架构（L1 短 composer / L2 模板四段 system_prompt / L3 org-scope
> identifiers.md / L4 数据接口目录）。org-scope 资源全员可见，dept-scope 技能归口部门，
> `model_alias=glm-5.2`，`exec_mode=craft`。剔除多模态生成——保留文本智能 / 数据智能 / 单据图像识别（感知类）。

## 0. 业务背景
敏睿文具（slug `agilestationery`）是一家书写工具进口贸易与 B 端分销企业（POC demo），核心做书写工具进口贸易
+ 全国 B 端分销网络运营 + KA 大客户管理 + 渠道品牌管控。业务覆盖经销商体系、大型零售连锁、政企采购等多元 B 端客户。
4 复用 mock 系统（ERP/CRM/SCM/HRM）+ 3 新建文具特有子系统（PIM 产品与防伪 / CST 报关与单证 / CHN 渠道与电商秩序）= 7 mock 系统。

## 1. 痛点 → 场景映射
9 部门各 1 旗舰场景（详见 [SCENARIO_ROSTER.md](SCENARIO_ROSTER.md)）：

| 场景 | 任务名 | 归口部门 | 痛点 |
|---|---|---|---|
| SAL-01 | 渠道健康度监测与销售补货预测闭环 | 销售管理部 | 渠道黑箱/窜货/断货风险/回款逾期 |
| ECM-01 | 线上渠道秩序管控与渠道效能分析闭环 | 电商渠道部 | 非授权店铺/低价窜货/投放低效 |
| MKT-01 | 竞品动态监测与B端营销物料生成闭环 | 市场营销部 | 竞品响应慢/物料制作成本高/合规风险 |
| SCM-01 | 报关单证智能处理与库存补货规划闭环 | 供应链与物流部 | 单证录入错/归类风险/库存粗放/汇兑成本 |
| PRD-01 | 渠道假货识别与全渠道反馈分析闭环 | 产品管理部 | 假货难识别/反馈分散/改进滞后 |
| SVC-01 | 售后工单智能处理与B端客服辅助闭环 | 客户服务部 | 工单流转慢/客服响应慢/超时 |
| FIN-01 | 发票识别审核与费用对账闭环 | 财务部 | 发票录入/对账滞后/应收逾期 |
| HR-01 | 招聘人岗匹配与人事事务闭环 | 人力资源部 | 简历初筛低/招聘周期长/事务重复 |
| LEG-01 | 合同智能审核与渠道维权合规闭环 | 法务合规部 | 合同风险/维权取证难/合规风险 |

> 行政与IT 部作支持部门（IT 运维/信息安全/AI 应用落地），不设对外场景，同 agilesteel 的 IT。

## 2. 演示矩阵
见 [SCENARIO_ROSTER.md](SCENARIO_ROSTER.md) 总览表（场景 / 部门 / 用户 / 模型 / 技能 / RAG / template_agent_id）。

## 3. 前置条件
1. 平台部署（docker compose：postgres/redis/backend/mock），`docker compose up -d`
2. mock 网关含 PIM/CST/CHN：`docker compose build mock && docker compose up -d mock`（A6 根治前：`docker cp mock/mock ai_infra_backend:/app/mock`，每次重建 backend 后必做）
3. backend 注入 mock 包：见上条（backend 镜像无 mock 包，seed 脚本 `import mock.core.registry` 依赖此）
4. LLM provider 同步自 agileac（占位 key 无 embedding/chat 能力）。从 agileac org 复制 2 把真实 provider：
   ```bash
   docker exec ai_infra_backend python -c "
   import asyncio
   from app.database import async_session_factory
   from app.models.organization import Organization
   from app.models.llm_provider import LlmProvider
   from app.models.routing_policy import RoutingPolicy
   from sqlalchemy import select
   async def main():
       async with async_session_factory() as db:
           ac=(await db.execute(select(Organization).where(Organization.slug=='agileac'))).scalar_one()
           st=(await db.execute(select(Organization).where(Organization.slug=='agilestationery'))).scalar_one()
           for p in (await db.execute(select(LlmProvider).where(LlmProvider.organization_id==ac.id,LlmProvider.deleted_at.is_(None)))).scalars().all():
               ex=(await db.execute(select(LlmProvider).where(LlmProvider.organization_id==st.id,LlmProvider.name==p.name))).scalar_one_or_none()
               if not ex:
                   db.add(LlmProvider(organization_id=st.id,name=p.name,provider_type=p.provider_type,base_url=p.base_url,api_key_encrypted=p.api_key_encrypted,api_key_version=p.api_key_version,is_active=True,priority=p.priority,weight=p.weight,timeout_seconds=p.timeout_seconds,max_retries=p.max_retries,supported_models=p.supported_models,health_status='unknown',config=p.config))
           ali=(await db.execute(select(LlmProvider).where(LlmProvider.organization_id==st.id,LlmProvider.name=='aliyun-all-openai'))).scalar_one()
           for pat in ['glm-*','deepseek-*']:
               rp=(await db.execute(select(RoutingPolicy).where(RoutingPolicy.organization_id==st.id,RoutingPolicy.model_pattern==pat))).scalar_one_or_none()
               if rp: rp.provider_ids=[str(ali.id)]
           await db.commit(); print('providers synced')
   asyncio.run(main())"
   ```
5. 5 个 seed 脚本按序跑（见 §9）。

## 4. 组织 / 部门 / 团队 / 用户
org slug=`agilestationery`，name=`敏睿文具`。9 业务部门 + 行政与IT：sales/ecommerce/marketing/supply/product/service/finance/hr/legal/it。
13 团队、16 用户（9 场景用户 + admin + it-specialist + 辅助），密码统一 `12345678`（hash 直写 password_hash）。详见 `seed_agilestationery_org.py`。

## 5. Mock 系统改造
- 4 复用：ERP/CRM/SCM/HRM 各加 `_build_agilestationery()` builder + agilestationery tenant 行 + `<sys>-agilestationery-demo-key`。
  - ERP 加文具 SKU 物料(M-ZB-) + 进口采购单(PO-，与 CST 报关单 CD- 对齐) + 凭证(BV-AS-，与 CST 发票 INV- 对齐) + 应付/库存/出入库/成本中心。
  - CRM 加经销商(DLR-)/KA(KA-)/电商(EC-)客户 + 销售订单(SO-) + 售后工单(CASE-) + 应收(REC-)。
  - SCM 加供应商(S-ZB-) + 物流/报关/包材多家比价(ASQ) + 在途到货/补货/交期异动/到货验收。
  - HRM 加 10 部门 + 岗位(P-) + 员工 + 简历库(ASRM) + 招聘需求(ASRC) + 考勤/薪酬/会议。
- 3 新建：PIM/CST/CHN 各 `__init__.py`/`data.py`/`routes.py`，全 GET（业务端点 verb-noun+query）。
  - PIM（产品/SKU/品类/防伪档案/假货样本 CTF-/反馈 FB- + identifyAuthenticity/scoreCounterfeitRisk）。
  - CST（报关单 CD-/HS 归类/发票 INV-/汇率 + recommendHsCode/verifyInvoice/checkCompliance/scoreDeclarationRisk）。
  - CHN（渠道商家 MR-/低价违规/非授权店铺/取证 EV-/渠道效能/竞品 CMP- + scoreViolationRisk）。
- registry.py 加 3 SystemDef + 4 系统加 agilestationery tenant。openapi 快照 `mock/openapi/{pim,cst,chn}.json` 已重生成。

## 6. RAG 知识库
9 collection（8 dept + 1 team）：经销商画像与渠道规则库/渠道秩序与平台规则库/竞品情报与营销物料库/
报关合规与库存规则库/假货特征与产品标准库/售后政策与工单规则库/财务合规与发票规则库/合同条款与合规规则库/
岗位JD与人事制度库。embedding=`text-embedding-v4`，chunk 512/overlap 64。9 场景均绑 RAG。

## 7. 本体文件
39 文件：7 组织级域（ERP/CRM/SCM/HRM/PIM/CST/CHN）+ Cross，每域 4 文件（README/object-types/link-types/action-types），
7 域含 identifiers.md（标识符约定 + 跨码空间映射，no-guessing 骨架）。8 条跨系统闭环链接
（销售订单SO-→采购PO-→报关CD-→发票INV-→凭证BV-→应收REC-；产品SKU-ZB-→物料M-ZB-→库存→补货；
假货CTF-→取证EV-→违规商家MR-；经销商DLR-→应收REC-→凭证BV-；客诉CASE-→反馈FB-→产品；
招聘RC-→岗位P-→员工→成本中心CC-ZB-；竞品CMP-→商机/营销物料；反馈FB-→产品改进日本总部）。

## 8. Agent 配置
9 Agent，四段 system_prompt，绑定归口部门技能 + RAG。`template_agent_id` 见 [SCENARIO_ROSTER.md](SCENARIO_ROSTER.md)。详见 `seed_agilestationery_agents.py`。

## 9. Seed 脚本清单与顺序
```bash
# 前置：mock-up + backend 注入 mock 包 + provider 同步（§3）
docker cp demo/agilestationery/scripts/seed_agilestationery_org.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_agilestationery_org.py
docker cp demo/agilestationery/scripts/seed_agilestationery_mock_connectors.py ai_infra_backend:/app/scripts/
docker exec -e MOCK_BASE_URL=http://ai_infra_mock:8010 ai_infra_backend python scripts/seed_agilestationery_mock_connectors.py
docker cp demo/agilestationery/scripts/seed_agilestationery_ontology.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_agilestationery_ontology.py
docker cp demo/agilestationery/scripts/seed_agilestationery_rag.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_agilestationery_rag.py
docker cp demo/agilestationery/scripts/seed_agilestationery_agents.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_agilestationery_agents.py
```

## 10. 演示运行
终端登录 `http://localhost:8000/agilestationery/terminal/login`（用户名见 SCENARIO_ROSTER，密码 `12345678`）→
新建任务 → TaskConfigDrawer 选 `glm-5.2` / exec_mode=`craft` / 绑 template agent（按场景） /
/-mention 选归口部门技能 / 贴 composer（见 SCENARIO_ROSTER）→ 运行，观察 SSE 6 trace + 多段分析 + generate_docx。
手工 curl 复现见各 `*_terminal_task.md` §6。

## 11. 跨场景合并原则
同部门多子任务合并（无）。跨部门不合并（一场景一 agent 一技能）。行政IT 部不设对外场景。

## 12. 验收清单
- [x] 9 agent 入库（四段 system_prompt，无代号）
- [x] 9 技能绑定（全 GET operationId，bound_endpoints 5-24）
- [x] 9 RAG collection embedded（vector 通道，非 keyword_fallback）
- [x] 39 本体文件入库，7 identifiers.md
- [ ] P0 三场景跑通：template:true + 6 trace + tool_call args 非空 + no-guessing identifiers（DLR-/SKU-ZB-/CD-/CTF-）

## 13. 文件清单
- `scripts/seed_agilestationery_{org,mock_connectors,ontology,rag,agents}.py`
- `SCENARIO_ROSTER.md` / `README.md` / `KNOWN_ISSUES.md`
- `{sal,ecm,mkt,scm,prd,svc,fin,hr,leg}_01_terminal_task.md`
- 软链：`CROSS_AGENT_HANDOFF_DESIGN.md` / `NEW_ORG_DEMO_CHECKLIST.md` / `SCENARIO_AUTHORING_GUIDE.md`（→ ../starclothing/）

## 14. 实施优先级
- **P0**：SAL-01 / SCM-01 / PRD-01（跨多系统 + 验证 PIM/CST 新子系统 + dept RAG）
- **P1**：ECM-01 / FIN-01 / SVC-01
- **P2**：MKT-01（CHN 竞品 + 纯文本物料）/ LEG-01（CHN 维权）/ HR-01（team RAG）

## 15. 与 agilesteel demo 的关系
| 维度 | agilesteel | agilestationery |
|---|---|---|
| 行业 | 钢铁 | 文具贸易 |
| 场景 | 9 | 9 |
| 部门 | 9+IT | 9+IT |
| mock 系统 | 9（6 复用+EQM/EMS/EHS） | 7（4 复用+PIM/CST/CHN） |
| 模型 | glm-5.2 | glm-5.2 |
| 四层架构 | ✅ | ✅（同构） |
| 主实体 | 炉次 HT | 报关单 CD- / 假货样本 CTF- |
| providers | 复制自 agileac | 复制自 agileac |
| 多模态 | — | 剔除生成类，保留感知（假货识别/单证识别） |

## 16. 后续行动
1. P0/P1/P2 逐场景端到端实测
2. backend 加 mock volume 根治 A6
3. 指南 HTML + 访问页 + 发布（按 agileac/agilesteel 指南方法）
