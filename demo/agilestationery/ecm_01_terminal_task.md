# ECM-01 线上渠道秩序管控与渠道效能分析

> 场景文档（7 节）。归口电商渠道部·电商运营组，登录用户 `ecm-ops`。模型 `glm-5.2`，exec_mode `craft`。
> template_agent_id `e2d0ac89-fbca-4a8a-99de-2ec4a47f0f3a`（`agilestationery-ecm-01-channel-order`）。

## 1. 演示身份
- 组织 slug：`agilestationery`（敏睿文具）
- 用户名：`ecm-ops` / 密码：`12345678`（统一）
- 角色：member，部门 ecommerce，团队 ecom-ops
- template_agent_id：`e2d0ac89-fbca-4a8a-99de-2ec4a47f0f3a`（`agilestationery-ecm-01-channel-order`）

## 2. 前置条件
- 平台 + mock 网关运行（`docker compose up -d`，mock 含 CHN/CRM）
- 5 个 seed 已跑（org / mock_connectors / ontology / rag / agents）
- glm-5.2 路由指向 `aliyun-all-openai`（真实 key 由 README §3 从 agileac 复制，A3）
- mock health：`curl -H "X-API-Key: chn-agilestationery-demo-key" http://localhost:8010/chn/health` 与 `crm-agilestationery-demo-key`/crm

## 3. 操作步骤
1. 登录 `http://localhost:8000/agilestationery/terminal/login`（ecm-ops / 12345678）
2. 新建任务
3. TaskConfigDrawer：模型 `glm-5.2` / exec_mode `craft` / 绑定智能体 `线上渠道秩序管控与渠道效能分析`
4. composer 提示词（贴入）：

```
对线上渠道做秩序管控与渠道效能分析，重点 MR-EC-09（淘宝冒名店，假冒+低价）、MR-DL-12（义乌窜货商，假冒+跨区）+ 渠道效能拼多多 ROI 下降。扫所有非授权店铺与违规取证，按渠道检索渠道秩序与平台规则库给风险队列与处置建议。

/agilestationery-ecom-chn-crm-query
```

5. 提交运行，观察 SSE

**资源注入表**：

| 项 | 值 |
|---|---|
| template_agent_id | `e2d0ac89-fbca-4a8a-99de-2ec4a47f0f3a` |
| skill_slug | `agilestationery-ecom-chn-crm-query`（dept scope，归口 ecommerce） |
| RAG collection | 渠道秩序与平台规则库（dept） |
| model_alias | `glm-5.2` |
| exec_mode | `craft` |
| scope | dept（ecommerce） |

## 4. 期望输出
三段分析上屏 + generate_docx：

1. 非授权店铺/违规风险队列（MR-EC-09/MR-DL-12 | 类型 | 风险分 | 取证 EV- | 处置建议）
2. 渠道效能分析（平台 | ROI | 投放 | 下降原因，拼多多 ROI 下降重点）
3. 处置建议清单（下架/投诉/取证补全/平台申诉）

**SSE trace 表（6 类）**：

| trace 类 | 命中内容 |
|---|---|
| template | `load_config` `template:true`（四段 system_prompt 注入） |
| rag | 渠道秩序与平台规则库（dept），retriever=vector（非 keyword_fallback） |
| memory | memory.load（+ memory.extract，中文保守 0 facts 非致命，A9） |
| ontology | CHN/CRM identifiers.md + object/link/action types（39 文件中相关域） |
| data_interface | CHN + CRM，9 bound endpoints（A8 path-param 用真实码） |
| skill | `agilestationery-ecom-chn-crm-query` bound（9 endpoints，args 非空） |

## 5. 故障排查
- model not available → 检查 glm-5.2 路由指向 aliyun-all-openai（README §3，A3）
- skill chip 不识别 → 检查 `agilestationery-ecom-chn-crm-query` 技能已绑（管理端技能页）
- tool_call args `{}` → 检查端点 spec 已导入（mock_connectors seed，A1/A2）
- `getMerchant(MR-EC-09)` not found → 渠道商家码写对，path-param 勿用 `{merchant_code}` 占位符（A8）
- MR-/EV-/CMP- 均 CHN 码空间；经销商 DLR- 在 CRM，跨查时按 customer_code 关联（A7）
- 取证 EV- 通过 listEvidence 查询，按 evidence_code 关联违规商家 MR-
- RAG retriever=keyword_fallback → embedding 未通（A3）
- 无 docx 落盘 → 任务未绑 workspace_id（A6）

## 6. 附：手工调 API 复现
```bash
# 1) 登录取 token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agilestationery","username":"ecm-ops","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) 创建任务（绑 template_agent_id + 模型 + craft）
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"线上渠道秩序管控与渠道效能分析","config":{"template_agent_id":"e2d0ac89-fbca-4a8a-99de-2ec4a47f0f3a","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "task=$TASK"

# 3) 运行（SSE 流）
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"对线上渠道做秩序管控与渠道效能分析，重点 MR-EC-09（淘宝冒名店，假冒+低价）、MR-DL-12（义乌窜货商，假冒+跨区）+ 渠道效能拼多多 ROI 下降。扫所有非授权店铺与违规取证，按渠道检索渠道秩序与平台规则库给风险队列与处置建议。","stream":true}'
```

## 7. 验收要点
- [ ] `load_config` event `template:true`（模板注入）
- [ ] 6 类 trace：rag（渠道秩序与平台规则库 vector）+ memory.load + ontology（CHN/CRM identifiers）+ data_interface（CHN+CRM）+ skill + memory.extract
- [ ] `tool_call` args 非全 `{}`（listMerchants/getMerchant/listPriceViolations/listUnauthorizedStores/listEvidence/listChannelPerformance/scoreViolationRisk/listCustomers 带真实 MR-EC-09/MR-DL-12/EV-/DLR-）
- [ ] no-guessing：渠道商家 MR-EC-09/MR-DL-12、取证 EV-、经销商 DLR- 命中正确前缀（A7）
- [ ] RAG retriever=vector（非 keyword_fallback）
- [ ] 输出含三段 + generate_docx 附件
- [ ] 同一 prompt 跑 2 次，第二次 text 字符数不暴跌（稳定性）
