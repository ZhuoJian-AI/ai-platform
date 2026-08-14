# SAL-01 销售需求预测与订单评审交期答复

> 归口销售公司·销售运营组，登录用户 `sal-ops`。模型 `glm-5.2`，exec_mode `craft`。

## 1. 演示身份
组织 `agilesteel`，用户 `sal-ops` / `12345678`，部门 sales，团队 sales-ops。
template_agent_id `a8c0f1b7-50ca-4511-bab3-2af295a2ff97`（`agilesteel-sal-01-order-review`）。

## 2. 前置条件
平台 + mock + 5 seed + glm-5.2 路由。CRM/ERP health：`curl -H "X-API-Key: crm-agilesteel-demo-key" http://localhost:8010/crm/health`。

## 3. 操作步骤
登录 `/agilesteel/terminal/login` → 新建任务 → glm-5.2 / craft / 绑智能体 `需求预测与订单评审` → 贴 composer：

```
对当前在制销售订单做需求预测与交期答复，重点 ASSO202607001（P-ST-Q345B，C-AS-PROJ-01 桥梁项目）、ASSO202607005（P-ST-40Cr，C-AS-OEM-01 三一直供）。扫所有未交付订单，按品种检索客户画像与行情库给需求预测与评审结论。

/agilesteel-sales-crm-erp-query
```

## 4. 期望输出
四段：① 需求与价格预测 ② 订单评审表 ③ 交期答复 ④ 客户信用与应收风险。

## 5. 故障排查
- `getSalesOrder(ASSO...)` not found → 销售订单号 ASSO202607001 写对（identifiers.md：ASSO 前缀）
- `getCustomer(C-AS-PROJ-01)` → 客户码 C-AS-PROJ-01 写对
- 交期答复须区分现货(listInventory available_qty) vs 排产(关联 SPO)

## 6. 附：手工调 API 复现
```bash
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug -H "Content-Type: application/json" -d '{"slug":"agilesteel","username":"sal-ops","password":"12345678"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"title":"销售需求预测与订单评审交期答复","config":{"template_agent_id":"a8c0f1b7-50ca-4511-bab3-2af295a2ff97","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"message":"对当前在制销售订单做需求预测与交期答复，重点 ASSO202607001（P-ST-Q345B，C-AS-PROJ-01 桥梁项目）、ASSO202607005（P-ST-40Cr，C-AS-OEM-01 三一直供）。扫所有未交付订单，按品种检索客户画像与行情库给需求预测与评审结论。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace（rag=客户画像与行情库 + memory + ontology CRM identifiers + data_interface + skill + memory.extract）
- [ ] tool_call 调 CRM/ERP：listCustomers/getCustomer/listSalesOrders/getSalesOrder/listReceivables/listInventory，args 带真实 ASSO/C-AS-/P-ST-
- [ ] no-guessing：订单 ASSO202607001、客户 C-AS-PROJ-01、钢种 P-ST-Q345B 命中正确前缀
- [ ] 输出四段（含交期答复：现货/排产 SPO 依据 + 应收逾期风险）
