# PRD-01 渠道假货识别与全渠道反馈分析

> 场景文档（7 节）。归口产品管理部·产品与防伪组，登录用户 `prd-quality`。模型 `glm-5.2`，exec_mode `craft`。
> template_agent_id `083e3434-0ca8-4968-8752-4384784ad201`（`agilestationery-prd-01-counterfeit-feedback`）。

## 1. 演示身份
- 组织 slug：`agilestationery`（敏睿文具）
- 用户名：`prd-quality` / 密码：`12345678`（统一）
- 角色：member，部门 product，团队 product-quality
- template_agent_id：`083e3434-0ca8-4968-8752-4384784ad201`（`agilestationery-prd-01-counterfeit-feedback`）

## 2. 前置条件
- 平台 + mock 网关运行（`docker compose up -d`，mock 含 PIM）
- 5 个 seed 已跑（org / mock_connectors / ontology / rag / agents）
- glm-5.2 路由指向 `aliyun-all-openai`（真实 key 由 README §3 从 agileac 复制，A3）
- mock health：`curl -H "X-API-Key: pim-agilestationery-demo-key" http://localhost:8010/pim/health`

## 3. 操作步骤
1. 登录 `http://localhost:8000/agilestationery/terminal/login`（prd-quality / 12345678）
2. 新建任务
3. TaskConfigDrawer：模型 `glm-5.2` / exec_mode `craft` / 绑定智能体 `渠道假货识别与全渠道反馈分析`
4. composer 提示词（贴入） :

```
对渠道抽检样本做假货识别与全渠道反馈分析，重点 CTF20260701（SKU-ZB-G001 华南电商抽检，假货）、CTF20260704（SKU-ZB-M001 华北电商抽检，假货）+ 反馈 FB20260706（中性笔 黑整批笔尖偏磨，严重）。扫所有假货样本与反馈，按产品检索假货特征与产品标准库给鉴定/分布/反馈/改进建议。

/agilestationery-product-pim-query
```

5. 提交运行，观察 SSE

**资源注入表**：

| 项 | 值 |
|---|---|
| template_agent_id | `083e3434-0ca8-4968-8752-4384784ad201` |
| skill_slug | `agilestationery-product-pim-query`（dept scope，归口 product） |
| RAG collection | 假货特征与产品标准库（dept） |
| model_alias | `glm-5.2` |
| exec_mode | `craft` |
| scope | dept（product） |

## 4. 期望输出
四段分析上屏 + generate_docx：

1. 假货鉴定结果（CTF20260701/CTF20260704 | SKU-ZB-G001/SKU-ZB-M001 | 真伪 | 风险分 | 鉴定依据）
2. 假货分布分析（渠道/区域 | 样本数 | 假货占比 | 趋势）
3. 全渠道反馈分析（FB20260706 | 中性笔 黑 | 问题 | 严重度 | 批次趋势）
4. 产品改进建议（反馈→日本总部改进闭环）

**SSE trace 表（6 类）**：

| trace 类 | 命中内容 |
|---|---|
| template | `load_config` `template:true`（四段 system_prompt 注入） |
| rag | 假货特征与产品标准库（dept），retriever=vector（非 keyword_fallback） |
| memory | memory.load（+ memory.extract，中文保守 0 facts 非致命，A9） |
| ontology | PIM identifiers.md + object/link/action types（39 文件中相关域） |
| data_interface | PIM，9 bound endpoints（A8 path-param 用真实码） |
| skill | `agilestationery-product-pim-query` bound（9 endpoints，args 非空） |

## 5. 故障排查
- model not available → 检查 glm-5.2 路由指向 aliyun-all-openai（README §3，A3）
- skill chip 不识别 → 检查 `agilestationery-product-pim-query` 技能已绑（管理端技能页）
- tool_call args `{}` → 检查端点 spec 已导入（mock_connectors seed，A1/A2）
- CTF.evidence_code → EV → MR 坑：假货样本 CTF20260701 的 `evidence_code` 引用 CHN 取证 EV-，EV 再关联违规商家 MR-，**勿直传 CTF 给 CHN**（A7）
- 产品 SKU-ZB-(PIM) ↔ 物料 M-ZB-(ERP) prefix 转换（本场景技能仅 PIM，不跨 ERP，但 identifiers.md 须消歧，A7）
- `getProduct(SKU-ZB-G001)` not found → 产品码写对，path-param 勿用 `{product_code}` 占位符（A8）
- 反馈 FB20260706 → listFeedback 查询，按 feedback_no 关联
- RAG retriever=keyword_fallback → embedding 未通（A3）
- 无 docx 落盘 → 任务未绑 workspace_id（A6）

## 6. 附：手工调 API 复现
```bash
# 1) 登录取 token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agilestationery","username":"prd-quality","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) 创建任务（绑 template_agent_id + 模型 + craft）
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"渠道假货识别与全渠道反馈分析","config":{"template_agent_id":"083e3434-0ca8-4968-8752-4384784ad201","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "task=$TASK"

# 3) 运行（SSE 流）
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"对渠道抽检样本做假货识别与全渠道反馈分析，重点 CTF20260701（SKU-ZB-G001 华南电商抽检，假货）、CTF20260704（SKU-ZB-M001 华北电商抽检，假货）+ 反馈 FB20260706（中性笔 黑整批笔尖偏磨，严重）。扫所有假货样本与反馈，按产品检索假货特征与产品标准库给鉴定/分布/反馈/改进建议。","stream":true}'
```

## 7. 验收要点
- [ ] `load_config` event `template:true`（模板注入）
- [ ] 6 类 trace：rag（假货特征与产品标准库 vector）+ memory.load + ontology（PIM identifiers）+ data_interface（PIM）+ skill + memory.extract
- [ ] `tool_call` args 非全 `{}`（listProducts/getProduct/listAntiCounterfeitSamples/getAuthenticityProfile/identifyAuthenticity/listFeedback/listFeedbackStats/scoreCounterfeitRisk 带真实 CTF20260701/CTF20260704/SKU-ZB-G001/SKU-ZB-M001/FB20260706）
- [ ] no-guessing：假货样本 CTF20260701/CTF20260704、产品 SKU-ZB-G001/SKU-ZB-M001、反馈 FB20260706、CTF.evidence_code→EV→MR 跨码空间映射正确（A7）
- [ ] RAG retriever=vector（非 keyword_fallback）
- [ ] 输出含四段 + generate_docx 附件
- [ ] 同一 prompt 跑 2 次，第二次 text 字符数不暴跌（稳定性）
