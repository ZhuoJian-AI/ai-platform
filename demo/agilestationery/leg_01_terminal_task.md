# LEG-01 合同智能审核与渠道维权合规

> 场景文档（7 节）。归口法务合规部·合同与维权组，登录用户 `leg-counsel`。模型 `glm-5.2`，exec_mode `craft`。
> template_agent_id `52393ef8-7b1e-41a0-85de-ab351f6637c0`（`agilestationery-leg-01-contract-enforcement`）。

## 1. 演示身份
- 组织 slug：`agilestationery`（敏睿文具）
- 用户名：`leg-counsel` / 密码：`12345678`（统一）
- 角色：member，部门 legal，团队 legal-contract
- template_agent_id：`52393ef8-7b1e-41a0-85de-ab351f6637c0`（`agilestationery-leg-01-contract-enforcement`）

## 2. 前置条件
- 平台 + mock 网关运行（`docker compose up -d`，mock 含 CHN/CRM）
- 5 个 seed 已跑（org / mock_connectors / ontology / rag / agents）
- glm-5.2 路由指向 `aliyun-all-openai`（真实 key 由 README §3 从 agileac 复制，A3）
- mock health：`curl -H "X-API-Key: chn-agilestationery-demo-key" http://localhost:8010/chn/health` 与 `crm-agilestationery-demo-key`/crm

## 3. 操作步骤
1. 登录 `http://localhost:8000/agilestationery/terminal/login`（leg-counsel / 12345678）
2. 新建任务
3. TaskConfigDrawer：模型 `glm-5.2` / exec_mode `craft` / 绑定智能体 `合同智能审核与渠道维权合规`
4. composer 提示词（贴入）：

```
做合同智能审核与渠道维权合规，重点 MR-EC-09（淘宝冒名店，取证 EV20260701 + 假货 CTF20260701）、MR-EC-15（拼多多冒名，EV20260706 + CTF20260706）。扫所有违规取证，按场景检索合同条款与合规规则库给合同风险条款/维权清单/合规审查。

/agilestationery-legal-chn-crm-query
```

5. 提交运行，观察 SSE

**资源注入表**：

| 项 | 值 |
|---|---|
| template_agent_id | `52393ef8-7b1e-41a0-85de-ab351f6637c0` |
| skill_slug | `agilestationery-legal-chn-crm-query`（dept scope，归口 legal） |
| RAG collection | 合同条款与合规规则库（dept） |
| model_alias | `glm-5.2` |
| exec_mode | `craft` |
| scope | dept（legal） |

## 4. 期望输出
三段分析上屏 + generate_docx：

1. 合同风险条款审查（合同 | 风险条款 | 建议）
2. 维权清单（MR-EC-09/MR-EC-15 | 取证 EV20260701/EV20260706 | 假货 CTF20260701/CTF20260706 | 诉求 | 管辖）
3. 合规审查意见（平台投诉/行政举报/诉讼路径）

**SSE trace 表（6 类）**：

| trace 类 | 命中内容 |
|---|---|
| template | `load_config` `template:true`（四段 system_prompt 注入） |
| rag | 合同条款与合规规则库（dept），retriever=vector（非 keyword_fallback） |
| memory | memory.load（+ memory.extract，中文保守 0 facts 非致命，A9） |
| ontology | CHN/CRM identifiers.md + object/link/action types（39 文件中相关域） |
| data_interface | CHN + CRM，10 bound endpoints（A8 path-param 用真实码） |
| skill | `agilestationery-legal-chn-crm-query` bound（10 endpoints，args 非空） |

## 5. 故障排查
- model not available → 检查 glm-5.2 路由指向 aliyun-all-openai（README §3，A3）
- skill chip 不识别 → 检查 `agilestationery-legal-chn-crm-query` 技能已绑（管理端技能页）
- tool_call args `{}` → 检查端点 spec 已导入（mock_connectors seed，A1/A2）
- `getMerchant(MR-EC-09)` not found → 渠道商家码写对，path-param 勿用 `{merchant_code}` 占位符（A8）
- CTF.evidence_code → EV → MR 坑：假货样本 CTF20260701 的 `evidence_code` 引用 CHN 取证 EV20260701，EV 再关联违规商家 MR-EC-09，**勿直传 CTF 给 CHN**（A7）。本场景 CHN 技能可查 EV-/MR-，CTF 在 PIM（不在本技能范围），须按 evidence_code 串联
- 经销商 DLR-(CRM)↔ERP 客户同码直查（A7）
- RAG retriever=keyword_fallback → embedding 未通（A3）
- 无 docx 落盘 → 任务未绑 workspace_id（A6）

## 6. 附：手工调 API 复现
```bash
# 1) 登录取 token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agilestationery","username":"leg-counsel","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) 创建任务（绑 template_agent_id + 模型 + craft）
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"合同智能审核与渠道维权合规","config":{"template_agent_id":"52393ef8-7b1e-41a0-85de-ab351f6637c0","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "task=$TASK"

# 3) 运行（SSE 流）
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"做合同智能审核与渠道维权合规，重点 MR-EC-09（淘宝冒名店，取证 EV20260701 + 假货 CTF20260701）、MR-EC-15（拼多多冒名，EV20260706 + CTF20260706）。扫所有违规取证，按场景检索合同条款与合规规则库给合同风险条款/维权清单/合规审查。","stream":true}'
```

## 7. 验收要点
- [ ] `load_config` event `template:true`（模板注入）
- [ ] 6 类 trace：rag（合同条款与合规规则库 vector）+ memory.load + ontology（CHN/CRM identifiers）+ data_interface（CHN+CRM）+ skill + memory.extract
- [ ] `tool_call` args 非全 `{}`（listMerchants/getMerchant/listPriceViolations/listUnauthorizedStores/listEvidence/scoreViolationRisk/listCompetitors/listCustomers 带真实 MR-EC-09/MR-EC-15/EV20260701/EV20260706/CTF20260701/CTF20260706/DLR-）
- [ ] no-guessing：渠道商家 MR-EC-09/MR-EC-15、取证 EV20260701/EV20260706、假货 CTF20260701/CTF20260706、CTF.evidence_code→EV→MR 跨码空间映射正确（A7）
- [ ] RAG retriever=vector（非 keyword_fallback）
- [ ] 输出含三段（合同风险条款 + 维权清单 + 合规审查）+ generate_docx 附件
- [ ] 同一 prompt 跑 2 次，第二次 text 字符数不暴跌（稳定性）
