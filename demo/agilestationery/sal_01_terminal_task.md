# SAL-01 渠道健康度监测与销售补货预测

> 场景文档（7 节）。归口销售管理部·渠道运营组，登录用户 `sal-channel`。模型 `glm-5.2`，exec_mode `craft`。
> template_agent_id `31c218ce-605c-4844-85e7-fc81a37477a3`（`agilestationery-sal-01-channel-health`）。

## 1. 演示身份
- 组织 slug：`agilestationery`（敏睿文具）
- 用户名：`sal-channel` / 密码：`12345678`（统一）
- 角色：member，部门 sales，团队 sales-channel
- template_agent_id：`31c218ce-605c-4844-85e7-fc81a37477a3`（`agilestationery-sal-01-channel-health`）

## 2. 前置条件
- 平台 + mock 网关运行（`docker compose up -d`，mock 含 ERP/CRM/SCM/HRM/PIM/CST/CHN）
- 5 个 seed 已跑（org / mock_connectors / ontology / rag / agents）
- glm-5.2 路由指向 `aliyun-all-openai`（真实 key 由 README §3 从 agileac 复制，A3）
- mock health：`curl -H "X-API-Key: crm-agilestationery-demo-key" http://localhost:8010/crm/health` 与 `curl -H "X-API-Key: erp-agilestationery-demo-key" http://localhost:8010/erp/health`

## 3. 操作步骤
1. 登录 `http://localhost:8000/agilestationery/terminal/login`（sal-channel / 12345678）
2. 新建任务
3. TaskConfigDrawer：模型 `glm-5.2` / exec_mode `craft` / 绑定智能体 `渠道健康度监测与销售补货预测`
4. composer 提示词（贴入）：

```
对经销商渠道做健康度监测 + 销售预测与补货建议，重点 DLR-01（华东经销商）、DLR-03（华南）。扫所有经销商与未交付订单，按渠道检索经销商画像与渠道规则库给健康度评分与补货建议。

/agilestationery-sales-crm-erp-query
```

5. 提交运行，观察 SSE

**资源注入表**：

| 项 | 值 |
|---|---|
| template_agent_id | `31c218ce-605c-4844-85e7-fc81a37477a3` |
| skill_slug | `agilestationery-sales-crm-erp-query`（dept scope，归口 sales） |
| RAG collection | 经销商画像与渠道规则库（dept） |
| model_alias | `glm-5.2` |
| exec_mode | `craft` |
| scope | dept（sales） |

## 4. 期望输出
三段分析上屏 + generate_docx：

1. 经销商渠道健康度评分表（DLR- | 区域 | 健康分 | 库销比 | 回款 | 窝货 | 建议）
2. 销售预测与补货建议（SKU-ZB- / M-ZB- | 预测销量 | 当前库存 | 补货量 | 交期）
3. 未交付订单与应收风险（SO202607001 等 | DLR- | 逾期 | REC-）

**SSE trace 表（6 类）**：

| trace 类 | 命中内容 |
|---|---|
| template | `load_config` `template:true`（四段 system_prompt 注入） |
| rag | 经销商画像与渠道规则库（dept），retriever=vector（非 keyword_fallback） |
| memory | memory.load（+ memory.extract，中文保守 0 facts 非致命，A9） |
| ontology | CRM/ERP identifiers.md + object/link/action types（39 文件中相关域） |
| data_interface | CRM + ERP，11 bound endpoints（A8 path-param 用真实码） |
| skill | `agilestationery-sales-crm-erp-query` bound（11 endpoints，args 非空） |

## 5. 故障排查
- model not available → 检查 glm-5.2 路由指向 aliyun-all-openai（README §3，A3）
- skill chip 不识别 → 检查 `agilestationery-sales-crm-erp-query` 技能已绑（管理端技能页）
- tool_call args `{}` → 检查端点 spec 已导入（mock_connectors seed，A1/A2）
- `getCustomer(DLR-01)` not found → 经销商码 DLR-01 写对（CRM↔ERP 客户同码直查，A7）
- 销售订单 SO202607001 → CRM↔ERP 同 so_no 直查，勿转换
- RAG retriever=keyword_fallback → embedding 未通（A3，跑 reembed 或检查 aliyun-embedding provider）
- 无 docx 落盘 → 任务未绑 workspace_id（A6，前端自动填；curl 须显式传）

## 6. 附：手工调 API 复现
```bash
# 1) 登录取 token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agilestationery","username":"sal-channel","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) 创建任务（绑 template_agent_id + 模型 + craft）
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"渠道健康度监测与销售补货预测","config":{"template_agent_id":"31c218ce-605c-4844-85e7-fc81a37477a3","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "task=$TASK"

# 3) 运行（SSE 流）
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"对经销商渠道做健康度监测 + 销售预测与补货建议，重点 DLR-01（华东经销商）、DLR-03（华南）。扫所有经销商与未交付订单，按渠道检索经销商画像与渠道规则库给健康度评分与补货建议。","stream":true}'
```

## 7. 验收要点
- [ ] `load_config` event `template:true`（模板注入）
- [ ] 6 类 trace：rag（经销商画像与渠道规则库 vector）+ memory.load + ontology（CRM/ERP identifiers）+ data_interface（CRM+ERP）+ skill + memory.extract
- [ ] `tool_call` args 非全 `{}`（listCustomers/getCustomer/listSalesOrders/getSalesOrder/listReceivables/listInventory/listMaterials 带真实 DLR-/SO202607001/REC-/M-ZB-）
- [ ] no-guessing：经销商 DLR-01/DLR-03、销售订单 SO202607001、物料 M-ZB-/产品 SKU-ZB- 命中正确前缀（A7）
- [ ] RAG retriever=vector（非 keyword_fallback）
- [ ] 输出含三段 + generate_docx 附件
- [ ] 同一 prompt 跑 2 次，第二次 text 字符数不暴跌（稳定性）
