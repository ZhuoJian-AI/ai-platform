# 星途勘探 AI 底座 POC demo

> 勘探设计企业 AI 底座 POC——参考 starclothing / agileac / agilesteel / agilestationery 四层架构，9 场景按部门边界划分。slug `starexploration`，组织名「星途勘探」。
> 本轮：demo + seed + P0 实测（同 agilesteel 首轮节奏）。指南 HTML + 凭证访问页 + 真截图作为第二轮（按 demo/starclothing/指南HTML生成方法.md）。

## 0. 业务背景
星途勘探是国内大型综合性工程设计研究院（隶属国机集团），业务覆盖工程咨询/勘察/设计/EPC 总承包/项目管理/监理/运营运维/检测检验全链条。三大领域：工业工程（电工装备/新能源电池/工程机械/智能制造）、能源环保（光伏风电/分布式能源/水环境/固废/海绵城市）、城乡服务（民用建筑/市政/风景园林/城乡规划）。**涉密资质单位**，保密管控为核心特色域。知识密集型、项目驱动型，多专业协同复杂、合规质量严格、项目地域分布广。

mock 系统 6 套（3 新建 + 3 复用）：DES 设计管理 / EPC 工程项目管理 / SEC 保密与合规（新建）+ ERP / HRM / CRM（复用扩展）。

## 1. 痛点 → 场景映射
| 部门 | 痛点 | 旗舰场景 |
|---|---|---|
| 设计研究院 | 重复绘图、合规校验繁琐、多专业协同低效 | DES-01 设计方案智能比选与规范合规校验 |
| 造价技经部 | 算量造价工作量大、与采购成本脱节 | QTO-01 智能算量与造价测算 |
| EPC 总承包部 | 项目分散管控难、成本进度风险不可控 | EPC-01 项目进度风险预警与成本管控 |
| 安全生产部 | 现场覆盖不足、风险预判难 | SAF-01 施工现场安全隐患智能识别 |
| 保密办公室 | 涉密内容管控难、风险预警滞后 | SEC-01 涉密内容检测与文档脱密 |
| 资产财务部 | 票据处理量大、数据统计繁琐 | FIN-01 票据识别审核与智能核算 |
| 综合管理部 | 事务性工作繁杂、文档处理量大 | ADM-01 公文生成与会议纪要闭环 |
| 法律合规部 | 合同审查量大、合规校验繁琐 | LEG-01 合同智能审查与履约风险校验 |
| 人力资源部 | 招聘筛选工作量大、人才培养个性化不足 | HR-01 智能招聘与人岗匹配 |
| 信息中心 | （无对外场景，底座承载） | — |

## 2. 演示矩阵
见 [SCENARIO_ROSTER.md](SCENARIO_ROSTER.md)：9 场景 × 部门 × 登录用户 × model × skill × RAG × template_agent_id × Phase。

## 3. 前置条件
- docker compose 起 pg / redis / backend / mock
- mock 网关 :8010 含 des/epc/sec（`docker restart ai_infra_mock` 加载新系统）
- backend 注入 mock 包（A1，注意勿建嵌套 /app/mock/mock/）：
  ```bash
  docker exec ai_infra_backend rm -rf /app/mock/mock
  docker cp mock/mock/core/registry.py ai_infra_backend:/app/mock/core/registry.py
  docker cp mock/mock/systems/des ai_infra_backend:/app/mock/systems/des
  docker cp mock/mock/systems/epc ai_infra_backend:/app/mock/systems/epc
  docker cp mock/mock/systems/sec ai_infra_backend:/app/mock/systems/sec
  docker cp mock/mock/systems/erp/data.py ai_infra_backend:/app/mock/systems/erp/data.py
  docker cp mock/mock/systems/hrm/data.py ai_infra_backend:/app/mock/systems/hrm/data.py
  docker cp mock/mock/systems/crm/data.py ai_infra_backend:/app/mock/systems/crm/data.py
  ```
- LLM provider 真 key 同步：org seed 落 4 占位 provider 后，从 agileac 复制 aliyun-embedding-openai + aliyun-all-openai 含加密 key，GLM/DeepSeek 路由指向 aliyun-all-openai（A3 SQL）
- 5 seed 脚本按序执行

## 4. 组织 / 部门 / 团队 / 用户
- org slug `starexploration`，10 部门（design/cost/epc/safety/security/finance/admin/legal/hr/it），13 团队，11 用户（admin + 9 场景用户 + it-specialist + it-infra），统一口令 `12345678`
- 终端登录 `/starexploration/terminal/login`，管理端登录用 admins 表（A10）

## 5. Mock 系统改造
**3 新建 leaf**（`tenants=("starexploration",)`）：
- DES 设计管理：方案 SCH-（SCH-IND-/SCH-BAT-/SCH-CIV-）/图纸 DWG-（ARC/STR/MEP）/规范 SPEC-（GB-50011/50016/50007/50207/50058）/算量项 QTI-（CON/STE/ARC）/碰撞 CLS-；端点 listSchemes/getScheme/listDrawings/getDrawing/listSpecs/checkDrawingCompliance/listQuantityItems/computeQuantityTakeoff/detectClashes
- EPC 工程项目：项目 PRJ-/进度 SCD-/隐患 HAZ-（感知类）/文档 PDOC-；端点 listProjects/getProject/listScheduleActivities/predictScheduleRisk/listSiteHazards/detectSiteHazard/listProjectDocuments
- SEC 保密合规：涉密文档 SECDOC-/标记 SECMARK-/脱敏 DESEN-/行为 BHV-；端点 listConfidentialDocs/getConfidentialDoc/listConfidentialFlags/listDesensitizationRecords/listBehaviorLogs/scanConfidentiality/desensitizeDocument/listBehaviorAnomalies

**3 复用扩展**（各加 `_build_starexploration()` + tenant 行 + `<sys>-starexploration-demo-key`）：
- ERP：工程供应商 S-SE-/物料 M-CON-/M-STE-/M-ARC-/采购 POSE-/应付 SEAP-/凭证 BV-SE-/成本中心 CC-IND-/CC-BAT-/CC-CIV-+CC-SE-/项目成本 PC-SE-
- HRM：部门 PD-DES/PD-COST/.../岗位 P-DES/P-COST/.../员工 SESA/SEOF/招聘 ASRC/简历 SERM/会议 SEMT
- CRM（语义改客户与投标）：业主 CLI-/商机 SEOPP/报价 SEQT/合同 CT-SE-/履约争议 DSP-/回款 SEAR/发票 INV-

## 6. RAG 知识库
9 collection（8 dept + 1 team hr-recruiting），embedding text-embedding-v4，chunk 512/overlap 64。首次入库 10 文档 0 失败（embedding 通畅）。

## 7. 本体文件
34 文件：6 域（DES/EPC/SEC/ERP/HRM/CRM）+ Cross，每域 README/object-types/link-types/action-types + identifiers.md。36 对象类型、42 链接类型（23 跨系统）、8 条跨系统闭环。identifiers.md 含跨码空间映射（no-guessing 骨架，A7）。

## 8. Agent 配置
9 agent，四段 system_prompt（职责/RAG 检索/规则/输出格式，不含场景代号，用具体示例），model_alias=glm-5.2，exec_mode=craft，template_agent_id 绑定（UUID 见 SCENARIO_ROSTER），dept skill + RAG 绑定。org-scope 资源全员可见 + dept-scope 技能归口。

## 9. Seed 脚本清单与顺序
1. `seed_starexploration_org.py` — 组织/部门/团队/用户/Provider/Routing/APIKey
2. `seed_starexploration_mock_connectors.py` — Connector/DataSystem/DataInterface/Skill（6 系统 9 dept 技能），`MOCK_BASE_URL=http://ai_infra_mock:8010`
3. `seed_starexploration_ontology.py` — 本体 34 文件
4. `seed_starexploration_rag.py` — 9 RAG collection（依赖 embedding 真 key）
5. `seed_starexploration_agents.py` — 9 agent 四段 prompt

执行：
```bash
docker cp demo/starexploration/scripts/seed_*.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_starexploration_org.py
docker exec -e MOCK_BASE_URL=http://ai_infra_mock:8010 ai_infra_backend python scripts/seed_starexploration_mock_connectors.py
docker exec ai_infra_backend python scripts/seed_starexploration_ontology.py
docker exec ai_infra_backend python scripts/seed_starexploration_rag.py        # 真 key 已复制后
docker exec ai_infra_backend python scripts/seed_starexploration_agents.py
```

## 10. 演示运行
终端 `/starexploration/terminal/login` → 选场景用户登录 → 新建任务 → TaskConfig(model=glm-5.2 / exec_mode=craft / 绑 template agent / 勾归口技能) → 粘贴 composer（见各 *_terminal_task.md）→ 提交观察 SSE。curl 三步复现见各 terminal_task §6。

## 11. 跨场景合并原则
- 部门内不合并；跨部门不合并；IT 无场景（同 agilestationery）
- 跨系统闭环靠本体 identifiers.md no-guessing 映射 + L4 数据接口目录，agent 自主规划端点

## 12. 验收清单
- [x] 9 agent（9 skill + 9 RAG + 9 dept scope）
- [x] 6 系统 mock（3 新 + 3 复用）+ openapi 快照
- [x] 34 本体文件 + 8 跨系统闭环
- [x] P0+P1 九场景端到端实测全过（template:true + 6 trace + vector RAG + tool_call 真实码 + 多段文本）—— 见下「实测状态」

## 13. 文件清单
```
demo/starexploration/
  README.md / SCENARIO_ROSTER.md / KNOWN_ISSUES.md
  CROSS_AGENT_HANDOFF_DESIGN.md -> ../starclothing/  (symlink)
  NEW_ORG_DEMO_CHECKLIST.md -> ../starclothing/       (symlink)
  SCENARIO_AUTHORING_GUIDE.md -> ../starclothing/     (symlink)
  des_01_terminal_task.md / qto_01_ / fin_01_ / adm_01_ / leg_01_ /
  epc_01_ / saf_01_ / sec_01_ / hr_01_terminal_task.md
  scripts/
    seed_starexploration_org.py / seed_starexploration_mock_connectors.py /
    seed_starexploration_ontology.py / seed_starexploration_rag.py /
    seed_starexploration_agents.py
mock/mock/systems/{des,epc,sec}/  + erp/hrm/crm data.py + registry.py + openapi/{des,epc,sec}.json
```

## 14. 实施优先级
- P0（高优先级）：DES-01 / QTO-01 / FIN-01 / ADM-01 / LEG-01
- P1（管理价值）：EPC-01 / SAF-01 / SEC-01 / HR-01
- P2（后续）：审计纪委廉政预警 / 董办经营决策 / 党委宣传 / 数字孪生运营（文档 §3.12/§3.13/§3.3/§2.3 未建场景，按需扩展）

## 15. 与 agilesteel / agilestationery demo 的关系
| 维度 | 星途勘探 | agilesteel | agilestationery |
|---|---|---|---|
| 行业 | 勘探设计 | 钢铁制造 | 文具贸易 |
| 场景 | 9 | 9 | 9 |
| mock 系统 | 6（3 新 DES/EPC/SEC + 3 复用 ERP/HRM/CRM） | 9（3 新 EQM/EMS/EHS + 6 复用） | 7（3 新 PIM/CST/CHN + 4 复用） |
| 主实体 | 方案 SCH-/项目 PRJ-/图纸 DWG-/合同 CT-SE-/涉密 SECDOC- | 炉次 HT/工单 SWO | SKU-ZB-/报关单 CD- |
| 特色域 | 涉密检测脱密 SEC | 设备预测维护 EQM | 渠道防伪 PIM |
| model | glm-5.2 | glm-5.2 | glm-5.2 |
| 架构 | 四层（同构） | 四层 | 四层 |
| provider | 从 agileac 复制 aliyun 真 key | 同 | 同 |
| 多模态 | 感知类仅文本（detectSiteHazard 不生成图片） | 剔除 | 剔除 |

## 16. 后续行动
- P0/P1 逐个实测（待 glm-5.2 配额恢复，A3）
- 第二轮：指南 HTML + poc-access.html + 真截图 + publish_guides.sh 加项（按 [[guide-html-generation-method]] + [[guide-credentials-in-separate-appendix]]）
- P2 场景按需扩展（审计/纪委/董办/党委/数字孪生）

## 实测状态（2026-07-23）
**9 场景全部端到端实测通过**（provider 重置后，glm-5.2 / aliyun-all-openai 配额恢复）：

| 场景 | template:true | RAG vector hits | 6 trace | tool_calls | 文本 deltas | 输出大小 | 真实码无 404 |
|---|---|---|---|---|---|---|---|
| DES-01 | ✅ | 5 | ✅ | 3 | 794 | 44KB | ✅ SCH-/DWG-/CLS- |
| QTO-01 | ✅ | 4 | ✅ | 14 | 1842 | 100KB | ✅ QTI-→M- prefix 转换 |
| FIN-01 | ✅ | 4 | ✅ | 8 | 2173 | 112KB | ✅ INV-↔BV-SE- 对账 |
| ADM-01 | ✅ | 4 | ✅ | 8 | 1272 | 69KB | ✅ SEMT-/PD-/SEOF- |
| LEG-01 | ✅ | 4 | ✅ | 8 | 2723 | 141KB | ✅ CT-SE-↔PRJ- 关联 |
| EPC-01 | ✅ | 4 | ✅ | 10 | 2053 | 107KB | ✅ PRJ-/SCD-/PC-SE- |
| SAF-01 | ✅ | 4 | ✅ | 4 | 658 | 41KB | ✅ HAZ-/detectSiteHazard 带 sample_desc |
| SEC-01 | ✅ | 5 | ✅ | 3 | 1044 | 55KB | ✅ source_doc=DWG- 跨系统跳转 |
| HR-01 | ✅ | 4 | ✅ | 3 | 1058 | 58KB | ✅ ASRC→P- 岗位关联 |

- 6 trace = template / rag(retriever=vector) / memory.load / ontology(34 files) / data_interface / memory.extract
- tool_call args 用真实码（no-guessing），跨码空间 prefix 转换正确（QTI-CON-→M-CON-、INV-↔BV-SE-、source_doc DWG-→SECDOC-），无真实 404
- 多段文本上屏（658-2723 deltas / 41-141KB），latency 68-283s，无 insufficient_quota 错误
- P0 五场景（DES/QTO/FIN/ADM/LEG）+ P1 四场景（EPC/SAF/SEC/HR）全过
