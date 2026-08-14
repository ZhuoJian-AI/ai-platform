# SVC-01 售后工单智能处理与B端客服辅助

> 场景文档（7 节）。归口客户服务部·客服与售后组，登录用户 `svc-agent`。模型 `glm-5.2`，exec_mode `craft`。
> template_agent_id `3ea7092f-4a06-4619-9790-d23e81cdf0e6`（`agilestationery-svc-01-after-sales`）。

## 1. 演示身份
- 组织 slug：`agilestationery`（敏睿文具）
- 用户名：`svc-agent` / 密码：`12345678`（统一）
- 角色：member，部门 service，团队 service-front
- template_agent_id：`3ea7092f-4a06-4619-9790-d23e81cdf0e6`（`agilestationery-svc-01-after-sales`）

## 2. 前置条件
- 平台 + mock 网关运行（`docker compose up -d`，mock 含 CRM/ERP）
- 5 个 seed 已跑（org / mock_connectors / ontology / rag / agents）
- glm-5.2 路由指向 `aliyun-all-openai`（真实 key 由 README §3 从 agileac 复制，A3）
- mock health：`curl -H "X-API-Key: crm-agilestationery-demo-key" http://localhost:8010/crm/health` 与 `erp-agilestationery-demo-key`/erp

## 3. 操作步骤
1. 登录 `http://localhost:8000/agilestationery/terminal/login`（svc-agent / 12345678）
2. 新建任务
3. TaskConfigDrawer：模型 `glm-5.2` / exec_mode `craft` / 绑定智能体 `售后工单智能处理与B端客服辅助`
4. composer 提示词（贴入）：

```
对当前售后工单做智能处理与客服辅助，重点 CASE-0002（KA-02 笔夹松动脱落，严重，8D）、CASE-0006（DLR-01 中性笔 整批笔尖偏磨，严重，8D）+ CASE-0005（运输破损补发）。扫所有未闭环工单，按问题类型检索售后政策与工单规则库给资质校验/分派/超时升级建议。

/agilestationery-service-crm-erp-query
```

5. 提交运行，观察 SSE

**资源注入表**：

| 项 | 值 |
|---|---|
| template_agent_id | `3ea7092f-4a06-4619-9790-d23e81cdf0e6` |
| skill_slug | `agilestationery-service-crm-erp-query`（dept scope，归口 service） |
| RAG collection | 售后政策与工单规则库（dept） |
| model_alias | `glm-5.2` |
| exec_mode | `craft` |
| scope | dept（service） |

## 4. 期望输出
三段分析上屏 + generate_docx：

1. 工单资质校验与分派（CASE-0002/CASE-0006/CASE-0005 | 客户 KA-02/DLR-01 | 问题 | 严重度 | 8D | 分派对象）
2. 超时升级建议（工单 | SLA | 剩余 | 升级对象）
3. CASE-0005 运输破损补发方案（库存 M-ZB- | 采购 PO- | 补发交期）

**SSE trace 表（6 类）**：

| trace 类 | 命中内容 |
|---|---|
| template | `load_config` `template:true`（四段 system_prompt 注入） |
| rag | 售后政策与工单规则库（dept），retriever=vector（非 keyword_fallback） |
| memory | memory.load（+ memory.extract，中文保守 0 facts 非致命，A9） |
| ontology | CRM/ERP identifiers.md + object/link/action types（39 文件中相关域） |
| data_interface | CRM + ERP，10 bound endpoints（A8 path-param 用真实码） |
| skill | `agilestationery-service-crm-erp-query` bound（10 endpoints，args 非空） |

## 5. 故障排查
- model not available → 检查 glm-5.2 路由指向 aliyun-all-openai（README §3，A3）
- skill chip 不识别 → 检查 `agilestationery-service-crm-erp-query` 技能已绑（管理端技能页）
- tool_call args `{}` → 检查端点 spec 已导入（mock_connectors seed，A1/A2）
- `getComplaint(CASE-0002)` not found → 工单号写对，path-param 勿用 `{case_no}` 占位符（A8）
- 工单 CASE-(CRM) 客户 KA-/DLR- 同码直查；销售订单 SO-(CRM)↔ERP 出库同 so_no 直查（A7）
- 物料 M-ZB-(ERP) ↔ 产品 SKU-ZB-(PIM) prefix 转换（本场景跨 CRM/ERP，按 material_code 关联，A7）
- RAG retriever=keyword_fallback → embedding 未通（A3）
- 无 docx 落盘 → 任务未绑 workspace_id（A6）

## 6. 附：手工调 API 复现
```bash
# 1) 登录取 token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agilestationery","username":"svc-agent","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) 创建任务（绑 template_agent_id + 模型 + craft）
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"售后工单智能处理与B端客服辅助","config":{"template_agent_id":"3ea7092f-4a06-4619-9790-d23e81cdf0e6","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "task=$TASK"

# 3) 运行（SSE 流）
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"对当前售后工单做智能处理与客服辅助，重点 CASE-0002（KA-02 笔夹松动脱落，严重，8D）、CASE-0006（DLR-01 中性笔 整批笔尖偏磨，严重，8D）+ CASE-0005（运输破损补发）。扫所有未闭环工单，按问题类型检索售后政策与工单规则库给资质校验/分派/超时升级建议。","stream":true}'
```

## 7. 验收要点
- [ ] `load_config` event `template:true`（模板注入）
- [ ] 6 类 trace：rag（售后政策与工单规则库 vector）+ memory.load + ontology（CRM/ERP identifiers）+ data_interface（CRM+ERP）+ skill + memory.extract
- [ ] `tool_call` args 非全 `{}`（listComplaints/getComplaint/listCustomers/getCustomer/listSalesOrders/getSalesOrder/listFollowUps/listInventory/listMaterials/listPurchaseOrders 带真实 CASE-0002/CASE-0006/CASE-0005/KA-02/DLR-01/SO-/M-ZB-）
- [ ] no-guessing：工单 CASE-0002/CASE-0006/CASE-0005、客户 KA-02/DLR-01、物料 M-ZB- 命中正确前缀（A7）
- [ ] RAG retriever=vector（非 keyword_fallback）
- [ ] 输出含三段（8D 资质校验 + 超时升级 + CASE-0005 补发方案）+ generate_docx 附件
- [ ] 同一 prompt 跑 2 次，第二次 text 字符数不暴跌（稳定性）
