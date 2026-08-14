# 星途勘探 POC 场景总表（SCENARIO_ROSTER）

> 单一事实源：本表 + 各 `*_terminal_task.md` H1 标题 + curl `title` 字段 + README §1/§5「场景」列。
> 设计原则：四层架构 L1 短 composer / L2 模板四段 system_prompt / L3 org-scope identifiers.md / L4 数据接口目录。
> 命名约定：对象+动作+闭环产出式（去「数字/AI/自动化」修饰）。喂 LLM 的 prompt 不含场景代号（DES-01 等），用具体示例（SCH-IND-001/DWG-ARC-001/PRJ-BAT-001/CT-SE-001/INV202607001/BV-SE-2026-0701）。

## 总览表

| 场景 | 任务名（对象+动作+闭环） | 部门(slug) | 登录用户 | Model | Skill slug | RAG(scope) | template_agent_id | Phase |
|---|---|---|---|---|---|---|---|---|
| DES-01 | 设计方案智能比选与规范合规校验 | 设计研究院(design) | des-engineer | glm-5.2 | starexploration-design-des-erp-query | dept(design) | `3f879a34-46ec-49de-89b3-604bfe8dc1b0` | P0 |
| QTO-01 | 智能算量与造价测算 | 造价技经部(cost) | cost-estimator | glm-5.2 | starexploration-cost-des-erp-query | dept(cost) | `5f8d0103-eec8-4329-888d-495bff80f642` | P0 |
| FIN-01 | 票据识别审核与智能核算 | 资产财务部(finance) | fin-accountant | glm-5.2 | starexploration-finance-erp-crm-query | dept(finance) | `fdbda49c-c8bf-45f3-b080-faca64cff369` | P0 |
| ADM-01 | 公文生成与会议纪要闭环 | 综合管理部(admin) | admin-officer | glm-5.2 | starexploration-admin-hrm-query | dept(admin) | `788a9132-9bff-4e96-baee-774be4731294` | P0 |
| LEG-01 | 合同智能审查与履约风险校验 | 法律合规部(legal) | leg-counsel | glm-5.2 | starexploration-legal-crm-erp-query | dept(legal) | `bd6e5ba7-02ea-4e05-834c-89040e49aa26` | P0 |
| EPC-01 | 项目进度风险预警与成本管控 | EPC总承包部(epc) | epc-manager | glm-5.2 | starexploration-epc-epc-erp-query | dept(epc) | `8164ca06-32c3-4a72-8cca-3468ed5f7634` | P1 |
| SAF-01 | 施工现场安全隐患智能识别 | 安全生产部(safety) | saf-inspector | glm-5.2 | starexploration-safety-epc-query | dept(safety) | `4ee432cc-3376-4af8-bcf0-8953a797e17d` | P1 |
| SEC-01 | 涉密内容检测与文档脱密 | 保密办公室(security) | sec-officer | glm-5.2 | starexploration-security-sec-des-epc-query | dept(security) | `c45d1171-33d2-4e5c-a3fd-c0c76d46e621` | P1 |
| HR-01 | 智能招聘与人岗匹配 | 人力资源部(hr) | hr-recruiter | glm-5.2 | starexploration-hr-hrm-query | team(hr-recruiting) | `3f9b762c-e9ef-4ff3-8258-75478aff7029` | P1 |

+ 信息中心(it) 无场景，仅作底座承载。共 10 部门、11 用户（admin + 9 场景用户 + it-specialist）、统一口令 `12345678`、终端登录 `/starexploration/terminal/login`。

**P0 实测选定**：DES-01 / FIN-01 / LEG-01 —— 分别覆盖新建 DES 域、复用 ERP、复用 CRM，验证三新（DES/EPC/SEC）三旧（ERP/HRM/CRM）系统全打通。

## 各场景 composer（L1 短问题 + 技能 chip）

> composer 是终端任务创建时粘贴的短用户提示，不含编排、不含场景代号，靠 template_agent_id 注入四层 prompt + bound skill 提供工具。技能 chip 在 TaskConfig 勾选归口部门技能后自动绑定，composer 正文不写 chip（chip 由 template agent 的 skill_ids 提供）。

### DES-01 设计方案智能比选与规范合规校验
```
对 SCH-IND-001 电工装备制造厂房方案做规范合规校验：重点查图纸 DWG-ARC-001 与 DWG-STR-001 的强条合规性，并列出该方案内跨专业碰撞 CLS-。
```

### QTO-01 智能算量与造价测算
```
按 SCH-IND-001 方案做智能算量与造价测算：聚合算量项 QTI-CON-/QTI-STE-，联动 ERP 物料 M-CON-001/M-STE-001 查单价（prefix 转换），输出造价与成本偏差。
```

### FIN-01 票据识别审核与智能核算
```
做票据识别审核与智能核算：查发票 INV202607001 关联凭证 BV-SE-2026-0701 对账，应收 REC- 与应付 SEAP- 差异闭环，列出逾期风险。
```

### ADM-01 公文生成与会议纪要闭环
```
基于会议纪要 SEMT-20260002 周度经营调度会生成纪要与待办闭环：提取待办事项与责任人 SEOF-，跨部门分发设计院 PD-DES / 安全部 PD-SAF / 保密办 PD-SEC，跟踪任务闭环。
```

### LEG-01 合同智能审查与履约风险校验
```
对合同 CT-SE-002 电池工厂 EPC 总承包合同做智能审查：提取关键条款、识别风险点（付款里程碑/保密条款）、关联项目 PRJ-BAT-001 与履约争议 DSP-，给修改建议与履约节点提醒。
```

### EPC-01 项目进度风险预警与成本管控
```
对 PRJ-IND-001 电工装备厂房 EPC 项目做进度风险预警与成本管控：查关键路径工序 SCD- 延误、predictScheduleRisk 风险等级、项目成本 PC-SE- 与合同 CT-SE-001 偏差，输出赶工建议。
```

### SAF-01 施工现场安全隐患智能识别
```
对 PRJ-IND-001 项目做现场安全隐患识别：摄像头 C07 画面『3 名作业人员未戴安全帽通过 2#塔吊下方作业区』，调 detectSiteHazard 识别隐患 HAZ- 与整改工单 RO-，闭环整改。
```

### SEC-01 涉密内容检测与文档脱密
```
对来源图纸 DWG-STR-001 做涉密检测：调 scanConfidentiality 返密级与涉密标记 SECMARK-，机密/秘密则调 desensitizeDocument 产脱敏记录 DESEN-，并列保密行为预警 BHV-。
```

### HR-01 智能招聘与人岗匹配
```
对 P-DES 设计师急招需求 ASRC20260000 做人岗匹配：调 listResumesByPosition 查简历 SERM-，按学历/年限/技能标签/评分匹配，输出短名单与录用建议。
```

## Demo 速查（curl 三步复现）

见各 `*_terminal_task.md` §6。统一三步：
1. `POST /api/v1/users/login-by-slug` 取 JWT（slug=starexploration, username/password=12345678）
2. `POST /api/v1/terminal/tasks` 创建任务（config 带 template_agent_id + exec_mode=craft + model_alias=glm-5.2）
3. `POST /api/v1/terminal/tasks/$TASK/run` 跑任务（message=composer，stream=true）
