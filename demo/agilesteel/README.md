# 敏睿钢铁 · 9 场景 Demo 演示

> 钢铁制造全产业链 AI 应用 demo——9 部门 × 1 旗舰场景，普转优·优转特·特转精战略。
> 复用 agileac 四层架构（L1 短 composer / L2 模板四段 system_prompt / L3 org-scope identifiers.md /
> L4 数据接口目录）。org-scope 资源全员可见，dept-scope 技能归口部门，`model_alias=glm-5.2`，`exec_mode=craft`。

## 0. 业务背景
敏睿钢铁（slug `agilesteel`），员工万余，年产钢 1000 万吨，优特钢占比 75%，覆盖建筑/交通/能源/机械四大领域，
出口 113 国。业务布局：钢铁制造/先进材料/贸易物流/清洁能源/现代服务五大板块。
6 复用 mock 系统（PLM/SCM/ERP/MES/CRM/HRM）+ 3 新建钢铁特有子系统（EQM 设备预测维护 / EMS 能源环保 / EHS 安全）= 9 mock 系统。

## 1. 痛点 → 场景映射
9 部门各 1 旗舰场景（详见 [SCENARIO_ROSTER.md](SCENARIO_ROSTER.md)）：

| 场景 | 任务名 | 归口部门 | 痛点 |
|---|---|---|---|
| MFG-01 | 转炉终点碳温预测与一体化排产闭环 | 生产制造部 | 冶炼黑箱/排产依赖人工/工序割裂 |
| EQP-01 | 关键设备预测性维护与备件建议闭环 | 设备管理部 | 事后维修/状态感知不足/备件粗放 |
| QAL-01 | 表面缺陷检测与全流程质量追溯闭环 | 质量管理部 | 检测滞后/人工目检/追溯链长 |
| SCM-01 | 大宗原料价格预测与供应商风控闭环 | 采购与供应链管理部 | 价格波动/供应商粗放/废钢判级主观 |
| SAL-01 | 销售需求预测与订单评审交期答复闭环 | 销售公司 | 需求预判不准/响应慢/信用管控难 |
| ENE-01 | 能源介质平衡调度与排放预警闭环 | 能源环保部 | 介质平衡难/排放波动/碳管理粗 |
| SAF-01 | 现场违章识别与隐患闭环管理 | 安全环保部 | 违章难发现/泄漏滞后/闭环慢 |
| FIN-01 | 分钢种成本核算与多系统对账闭环 | 财务部 | 成本粒度粗/对账滞后 |
| HR-01 | 招聘人岗匹配与培训薪酬一体化闭环 | 人力资源部 | 招聘匹配低/培训一面/绩效主观 |

## 2. 演示矩阵
见 [SCENARIO_ROSTER.md](SCENARIO_ROSTER.md) 总览表（场景 / 部门 / 用户 / 模型 / 技能 / RAG / template_agent_id）。

## 3. 前置条件
1. 平台部署（docker compose：postgres/redis/backend/mock），`docker compose up -d`
2. mock 网关含 EQM/EMS/EHS：`docker compose build mock && docker compose up -d mock`
3. backend 注入 mock 包：`docker cp mock/mock ai_infra_backend:/app/mock`（A6 根治前每次重建 backend 后必做）
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
           st=(await db.execute(select(Organization).where(Organization.slug=='agilesteel'))).scalar_one()
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
org slug=`agilesteel`，name=`敏睿钢铁`。9 业务部门 + IT：production/equipment/quality/supply/sales/energy/safety/finance/hr/it。
17 团队、16 用户（9 场景用户 + admin + it-specialist + 辅助），密码统一 `12345678`（hash 直写 password_hash）。详见 `seed_agilesteel_org.py`。

## 5. Mock 系统改造
- 6 复用：PLM/SCM/ERP/MES/CRM/HRM 各加 `_build_agilesteel()` builder + agilesteel tenant 行 + `<sys>-agilesteel-demo-key`。MES 加炉次(HT)+listHeats/getHeat；PLM 加钢种(P-ST-)+listSteelGrades/getSteelGrade；SCM 加废钢(SCR-)+listScrapGrades/getScrapPrice。
- 3 新建：EQM/EHS/EMS 各 `__init__.py`/`data.py`/`routes.py`，全 GET（业务端点 verb-noun+query）。EQM（设备/备件/传感器/故障/维护建议+predictEquipmentFailure/scoreMaintenancePriority）、EMS（计量点/介质平衡/排放/能耗/调度/预警+predictMediaShortfall/scoreEmissionRisk）、EHS（隐患/违章/巡检/风险点/劳保+detectViolationType/scoreHazardPriority）。
- registry.py 加 3 SystemDef + 6 系统加 agilesteel tenant。openapi 快照 `mock/openapi/{eqm,ems,ehs}.json` 已重生成。

## 6. RAG 知识库
9 collection（7 dept + 1 team + 1 org）：排产与炼钢规则库/设备故障案例库/质量缺陷案例库/供应商资质与行情库/客户画像与行情库/能源调度规则库/安全法规与隐患案例库/岗位JD库/员工综合知识库。embedding=`text-embedding-v4`，chunk 512/overlap 64。FIN-01 无 RAG（规则在模板）。

## 7. 本体文件
69 文件：9 组织级域（PLM/SCM/ERP/MES/CRM/HRM/EQM/EMS/EHS）+ Cross，每域 4 文件（README/object-types/link-types/action-types），9 域含 identifiers.md（标识符约定 + 跨码空间映射，no-guessing 骨架）。+ 5 部门/团队级（equipment/energy/safety/hr + hr-recruiting）。8 条跨系统闭环链接（销售订单→生产订单→炉次→钢种+废钢→缺陷→设备→能耗→隐患→炉次成本）。

## 8. Agent 配置
9 Agent，四段 system_prompt，绑定归口部门技能 + RAG（FIN-01 无）。`template_agent_id` 见 [SCENARIO_ROSTER.md](SCENARIO_ROSTER.md)。详见 `seed_agilesteel_agents.py`。

## 9. Seed 脚本清单与顺序
```bash
# 前置：mock-up + backend 注入 mock 包 + provider 同步（§3）
docker cp demo/agilesteel/scripts/seed_agilesteel_org.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_agilesteel_org.py
docker cp demo/agilesteel/scripts/seed_agilesteel_mock_connectors.py ai_infra_backend:/app/scripts/
docker exec -e MOCK_BASE_URL=http://ai_infra_mock:8010 ai_infra_backend python scripts/seed_agilesteel_mock_connectors.py
docker cp demo/agilesteel/scripts/seed_agilesteel_ontology.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_agilesteel_ontology.py
docker cp demo/agilesteel/scripts/seed_agilesteel_rag.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_agilesteel_rag.py
docker cp demo/agilesteel/scripts/seed_agilesteel_agents.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_agilesteel_agents.py
```

## 10. 演示运行
终端登录 `http://localhost:8000/agilesteel/terminal/login`（用户名见 SCENARIO_ROSTER，密码 `12345678`）→
新建任务 → TaskConfigDrawer 选 `glm-5.2` / exec_mode=`craft` / 绑 template agent（按场景） /
/-mention 选归口部门技能 / 贴 composer（见 SCENARIO_ROSTER）→ 运行，观察 SSE 6 trace + 4 段分析 + generate_docx。
手工 curl 复现见各 `*_terminal_task.md` §6。

## 11. 跨场景合并原则
同部门多子任务合并（HR-01 招聘/培训/薪酬；FIN-01 成本/对账/应收）。跨部门不合并（一场景一 agent 一技能）。

## 12. 验收清单
- [ ] 9 agent 入库（4 段 system_prompt，无代号）
- [ ] 9 技能绑定（全 GET operationId，bound_endpoints≥9）
- [ ] 9 RAG collection embedded（vector 通道，非 keyword_fallback）
- [ ] 69 本体文件入库，9 identifiers.md
- [ ] P0 三场景跑通：template:true + 6 trace + tool_call args 非空 + no-guessing identifiers（HT/P-ST-/EQ-）

## 13. 文件清单
- `scripts/seed_agilesteel_{org,mock_connectors,ontology,rag,agents}.py`
- `SCENARIO_ROSTER.md` / `README.md` / `KNOWN_ISSUES.md`
- `{mfg,eqp,qal,scm,sal,ene,saf,fin,hr}_01_terminal_task.md`
- 软链：`CROSS_AGENT_HANDOFF_DESIGN.md` / `NEW_ORG_DEMO_CHECKLIST.md` / `SCENARIO_AUTHORING_GUIDE.md`（→ ../starclothing/）

## 14. 实施优先级
- **P0**（✅ 已铺）：MFG-01 / EQP-01 / SAL-01（跨多系统 + 验证 EQM 新子系统 + dept RAG + 无 RAG 范式）
- **P1**：QAL-01 / SCM-01 / FIN-01
- **P2**：ENE-01（EMS 新域）/ SAF-01（EHS 新域）/ HR-01（team+org 双 RAG）

## 15. 与 agileac demo 的关系
| 维度 | agileac | agilesteel |
|---|---|---|
| 行业 | 空调 | 钢铁 |
| 场景 | 11 | 9 |
| 部门 | 11 | 9+IT |
| mock 系统 | 6 | 9（+EQM/EMS/EHS） |
| 模型 | glm-5.2 | glm-5.2 |
| 四层架构 | ✅ | ✅（同构） |
| 主实体 | 工单 AWO | 炉次 HT |
| providers | agileac 2 把 aliyun | 照搬（复制自 agileac） |

## 16. 后续行动
1. P0/P1/P2 逐场景端到端实测（见 KNOWN_ISSUES A5）
2. backend 加 mock volume 根治 A6
3. 指南 HTML + 访问页 + 发布（按 agileac 指南方法，后续单独一轮）
