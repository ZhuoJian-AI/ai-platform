# SCM-01 报关单证智能处理与库存补货规划

> 场景文档（7 节）。归口供应链与物流部·报关与单证组，登录用户 `scm-customs`。模型 `glm-5.2`，exec_mode `craft`。
> template_agent_id `a547d723-6bde-4edb-b400-f5d9d39c4787`（`agilestationery-scm-01-customs-replenishment`）。

## 1. 演示身份
- 组织 slug：`agilestationery`（敏睿文具）
- 用户名：`scm-customs` / 密码：`12345678`（统一）
- 角色：member，部门 supply，团队 supply-customs
- template_agent_id：`a547d723-6bde-4edb-b400-f5d9d39c4787`（`agilestationery-scm-01-customs-replenishment`）

## 2. 前置条件
- 平台 + mock 网关运行（`docker compose up -d`，mock 含 CST/SCM/ERP）
- 5 个 seed 已跑（org / mock_connectors / ontology / rag / agents）
- glm-5.2 路由指向 `aliyun-all-openai`（真实 key 由 README §3 从 agileac 复制，A3）
- mock health：`curl -H "X-API-Key: cst-agilestationery-demo-key" http://localhost:8010/cst/health`、`scm-agilestationery-demo-key`/scm、`erp-agilestationery-demo-key`/erp

## 3. 操作步骤
1. 登录 `http://localhost:8000/agilestationery/terminal/login`（scm-customs / 12345678）
2. 新建任务
3. TaskConfigDrawer：模型 `glm-5.2` / exec_mode `craft` / 绑定智能体 `报关单证智能处理与库存补货规划`
4. composer 提示词（贴入）：

```
对当前进口报关单做单证识别与合规校验 + 库存补货规划，重点 CD202607001（SKU-ZB-G001 中性笔，已申报）、CD202607005（中性笔 0.4，异常-归类存疑）+ 发票 INV202607001 验真。扫所有在途报关单与低库存 SKU，按品类检索报关合规与库存规则库给归类/合规/补货/汇率建议。

/agilestationery-supply-cst-scm-erp-query
```

5. 提交运行，观察 SSE

**资源注入表**：

| 项 | 值 |
|---|---|
| template_agent_id | `a547d723-6bde-4edb-b400-f5d9d39c4787` |
| skill_slug | `agilestationery-supply-cst-scm-erp-query`（dept scope，归口 supply） |
| RAG collection | 报关合规与库存规则库（dept） |
| model_alias | `glm-5.2` |
| exec_mode | `craft` |
| scope | dept（supply） |

## 4. 期望输出
四段分析上屏 + generate_docx：

1. 报关单证识别与归类（CD202607001/CD202607005 | SKU-ZB-G001 | HS 归类 | 合规 | 归类风险）
2. 发票验真（INV202607001 | 真伪 | 金额 | 汇率 FX-）
3. 库存补货规划（M-ZB-/SKU-ZB- | 当前库存 | 补货量 | 供应商 SUP-/S-ZB- 比价 ASQ）
4. 汇率与成本建议（FX- | 汇兑成本 | 锁汇建议）

**SSE trace 表（6 类）**：

| trace 类 | 命中内容 |
|---|---|
| template | `load_config` `template:true`（四段 system_prompt 注入） |
| rag | 报关合规与库存规则库（dept），retriever=vector（非 keyword_fallback） |
| memory | memory.load（+ memory.extract，中文保守 0 facts 非致命，A9） |
| ontology | CST/SCM/ERP identifiers.md + object/link/action types（39 文件中相关域） |
| data_interface | CST + SCM + ERP，24 bound endpoints（A8 path-param 用真实码） |
| skill | `agilestationery-supply-cst-scm-erp-query` bound（24 endpoints，args 非空） |

## 5. 故障排查
- model not available → 检查 glm-5.2 路由指向 aliyun-all-openai（README §3，A3）
- skill chip 不识别 → 检查 `agilestationery-supply-cst-scm-erp-query` 技能已绑（管理端技能页）
- tool_call args `{}` → 检查端点 spec 已导入（mock_connectors seed，A1/A2）
- CD.po_no ↔ PO 坑：报关单 CD202607001 的 `po_no` 引用 ERP 采购单 PO-，按 po_no 关联，**勿直传 CD 给 ERP**（A7）
- INV.voucher_no ↔ BV 坑：发票 INV202607001 的 `voucher_no` 引用 ERP 凭证 BV-AS-，**勿直传 INV 给 ERP**（A7）
- 产品 SKU-ZB-(PIM) ↔ 物料 M-ZB-(ERP) prefix 转换，按 product_code/material_code 关联（A7）
- `getDeclaration(CD202607001)` not found → 报关单号写对，path-param 勿用 `{declaration_no}` 占位符（A8）
- RAG retriever=keyword_fallback → embedding 未通（A3）
- 无 docx 落盘 → 任务未绑 workspace_id（A6）

## 6. 附：手工调 API 复现
```bash
# 1) 登录取 token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agilestationery","username":"scm-customs","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) 创建任务（绑 template_agent_id + 模型 + craft）
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"报关单证智能处理与库存补货规划","config":{"template_agent_id":"a547d723-6bde-4edb-b400-f5d9d39c4787","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "task=$TASK"

# 3) 运行（SSE 流）
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"对当前进口报关单做单证识别与合规校验 + 库存补货规划，重点 CD202607001（SKU-ZB-G001 中性笔，已申报）、CD202607005（中性笔 0.4，异常-归类存疑）+ 发票 INV202607001 验真。扫所有在途报关单与低库存 SKU，按品类检索报关合规与库存规则库给归类/合规/补货/汇率建议。","stream":true}'
```

## 7. 验收要点
- [ ] `load_config` event `template:true`（模板注入）
- [ ] 6 类 trace：rag（报关合规与库存规则库 vector）+ memory.load + ontology（CST/SCM/ERP identifiers）+ data_interface（CST+SCM+ERP）+ skill + memory.extract
- [ ] `tool_call` args 非全 `{}`（listDeclarations/getDeclaration/recommendHsCode/verifyInvoice/listSuppliers/compareQuotations/suggestReplenishment/listInventory/listPurchaseOrders 带真实 CD202607001/INV202607001/SKU-ZB-G001/M-ZB-/PO-/SUP-）
- [ ] no-guessing：报关单 CD202607001/CD202607005、发票 INV202607001、物料 M-ZB-/产品 SKU-ZB-G001、CD.po_no↔PO、INV.voucher_no↔BV 跨码空间映射正确（A7）
- [ ] RAG retriever=vector（非 keyword_fallback）
- [ ] 输出含四段 + generate_docx 附件
- [ ] 同一 prompt 跑 2 次，第二次 text 字符数不暴跌（稳定性）
