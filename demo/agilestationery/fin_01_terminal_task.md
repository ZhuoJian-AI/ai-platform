# FIN-01 发票识别审核与费用对账

> 场景文档（7 节）。归口财务部·对账组，登录用户 `fin-accountant`。模型 `glm-5.2`，exec_mode `craft`。
> template_agent_id `51c787d2-34ac-46dd-8004-f05bbafa5b12`（`agilestationery-fin-01-invoice-reconciliation`）。

## 1. 演示身份
- 组织 slug：`agilestationery`（敏睿文具）
- 用户名：`fin-accountant` / 密码：`12345678`（统一）
- 角色：member，部门 finance，团队 fin-recon
- template_agent_id：`51c787d2-34ac-46dd-8004-f05bbafa5b12`（`agilestationery-fin-01-invoice-reconciliation`）

## 2. 前置条件
- 平台 + mock 网关运行（`docker compose up -d`，mock 含 ERP/CST/CRM）
- 5 个 seed 已跑（org / mock_connectors / ontology / rag / agents）
- glm-5.2 路由指向 `aliyun-all-openai`（真实 key 由 README §3 从 agileac 复制，A3）
- mock health：`curl -H "X-API-Key: erp-agilestationery-demo-key" http://localhost:8010/erp/health`、`cst-agilestationery-demo-key`/cst、`crm-agilestationery-demo-key`/crm

## 3. 操作步骤
1. 登录 `http://localhost:8000/agilestationery/terminal/login`（fin-accountant / 12345678）
2. 新建任务
3. TaskConfigDrawer：模型 `glm-5.2` / exec_mode `craft` / 绑定智能体 `发票识别审核与费用对账`
4. composer 提示词（贴入）：

```
做发票识别审核与费用对账，重点发票 INV202607001（进项，关联凭证 BV-AS-2026-0701）、INV202607007（存疑-发票代码异常）+ 应收 DLR-03 逾期。扫所有发票与凭证/应付/应收做对账，差异率>2% 标异常，按场景检索财务合规与发票规则库给验真/对账/催收建议。

/agilestationery-finance-erp-cst-crm-query
```

5. 提交运行，观察 SSE

**资源注入表**：

| 项 | 值 |
|---|---|
| template_agent_id | `51c787d2-34ac-46dd-8004-f05bbafa5b12` |
| skill_slug | `agilestationery-finance-erp-cst-crm-query`（dept scope，归口 finance） |
| RAG collection | 财务合规与发票规则库（dept） |
| model_alias | `glm-5.2` |
| exec_mode | `craft` |
| scope | dept（finance） |

## 4. 期望输出
三段分析上屏 + generate_docx：

1. 发票识别验真（INV202607001/INV202607007 | 真伪 | 代码异常 | 金额 | 汇率 FX-）
2. 费用对账差异表（BV-AS-2026-0701↔INV202607001↔PO-↔REC- | 差异率 | >2% 异常）
3. 应收催收清单（DLR-03 | 逾期 | REC- | 催办对象）

**SSE trace 表（6 类）**：

| trace 类 | 命中内容 |
|---|---|
| template | `load_config` `template:true`（四段 system_prompt 注入） |
| rag | 财务合规与发票规则库（dept），retriever=vector（非 keyword_fallback） |
| memory | memory.load（+ memory.extract，中文保守 0 facts 非致命，A9） |
| ontology | ERP/CST/CRM identifiers.md + object/link/action types（39 文件中相关域） |
| data_interface | ERP + CST + CRM，14 bound endpoints（A8 path-param 用真实码） |
| skill | `agilestationery-finance-erp-cst-crm-query` bound（14 endpoints，args 非空） |

## 5. 故障排查
- model not available → 检查 glm-5.2 路由指向 aliyun-all-openai（README §3，A3）
- skill chip 不识别 → 检查 `agilestationery-finance-erp-cst-crm-query` 技能已绑（管理端技能页）
- tool_call args `{}` → 检查端点 spec 已导入（mock_connectors seed，A1/A2）
- INV.voucher_no ↔ BV 坑：发票 INV202607001 的 `voucher_no` 引用 ERP 凭证 BV-AS-2026-0701，按 voucher_no 关联，**勿直传 INV 给 ERP**（A7）
- 经销商 DLR-03（CRM）↔ ERP 客户同码直查（A7）
- `verifyInvoice(INV202607001)` not found → 发票号写对，path-param 勿用 `{invoice_no}` 占位符（A8）
- 对账差异率 >2% 标异常（核心判定逻辑）
- RAG retriever=keyword_fallback → embedding 未通（A3）
- 无 docx 落盘 → 任务未绑 workspace_id（A6）

## 6. 附：手工调 API 复现
```bash
# 1) 登录取 token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agilestationery","username":"fin-accountant","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) 创建任务（绑 template_agent_id + 模型 + craft）
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"发票识别审核与费用对账","config":{"template_agent_id":"51c787d2-34ac-46dd-8004-f05bbafa5b12","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "task=$TASK"

# 3) 运行（SSE 流）
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"做发票识别审核与费用对账，重点发票 INV202607001（进项，关联凭证 BV-AS-2026-0701）、INV202607007（存疑-发票代码异常）+ 应收 DLR-03 逾期。扫所有发票与凭证/应付/应收做对账，差异率>2% 标异常，按场景检索财务合规与发票规则库给验真/对账/催收建议。","stream":true}'
```

## 7. 验收要点
- [ ] `load_config` event `template:true`（模板注入）
- [ ] 6 类 trace：rag（财务合规与发票规则库 vector）+ memory.load + ontology（ERP/CST/CRM identifiers）+ data_interface（ERP+CST+CRM）+ skill + memory.extract
- [ ] `tool_call` args 非全 `{}`（listVouchers/listPayables/listPurchaseOrders/listCostCenters/verifyInvoice/getExchangeRate/listReceivables/listCustomers 带真实 INV202607001/INV202607007/BV-AS-2026-0701/DLR-03/REC-/PO-）
- [ ] no-guessing：发票 INV202607001/INV202607007、凭证 BV-AS-2026-0701、经销商 DLR-03 命中正确前缀；INV.voucher_no↔BV 跨码空间映射正确（A7）
- [ ] RAG retriever=vector（非 keyword_fallback）
- [ ] 输出含三段（对账差异率 >2% 标异常 + 应收催收）+ generate_docx 附件
- [ ] 同一 prompt 跑 2 次，第二次 text 字符数不暴跌（稳定性）
