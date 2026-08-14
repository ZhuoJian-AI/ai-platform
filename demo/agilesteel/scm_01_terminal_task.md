# SCM-01 大宗原料价格预测与供应商风控

> 归口采购与供应链管理部·采购组，用户 `scm-buyer`。glm-5.2 / craft。
> template_agent_id `3793709f-9bc5-430a-8eaf-aba0bde7303b`（`agilesteel-scm-01-procurement-risk`）。

## 1. 演示身份
组织 `agilesteel`，用户 `scm-buyer` / `12345678`，部门 supply，团队 supply-procurement。

## 2. 前置条件
平台 + mock + 5 seed + glm-5.2 路由。SCM health：`curl -H "X-API-Key: scm-agilesteel-demo-key" http://localhost:8010/scm/health`。

## 3. 操作步骤
登录 `/agilesteel/terminal/login` → glm-5.2 / craft / 绑智能体 `原料价格与供应商风控` → 贴 composer：

```
对大宗原料做价格预测与供应商风控，重点 M-ORE-FINE（铁矿石 62%，2 家比价）、M-SCR-HMS1（废钢重废1型，2 家比价）。扫所有在有效期报价，按品类检索供应商资质与行情库给比价建议与废钢判级。

/agilesteel-supply-scm-erp-query
```

## 4. 期望输出
四段：① 大宗原料价格预测 ② 多家比价表 ③ 废钢判级 ④ 供应商风控清单。

## 5. 故障排查
- SCR- vs M-SCR- 坑：SCM 废钢分级 `SCR-HMS1` ↔ ERP 采购物料 `M-SCR-HMS1`，调 getScrapPrice 收 SCR-，调 listMaterials 收 M-SCR-（identifiers.md 前缀转换）
- `compareQuotations` → 按 material_code 比价
- 供应商信用风险 → ERP listPayables days_overdue>0

## 6. 附：手工调 API 复现
```bash
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug -H "Content-Type: application/json" -d '{"slug":"agilesteel","username":"scm-buyer","password":"12345678"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"title":"大宗原料价格预测与供应商风控","config":{"template_agent_id":"3793709f-9bc5-430a-8eaf-aba0bde7303b","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"message":"对大宗原料做价格预测与供应商风控，重点 M-ORE-FINE（铁矿石 62%，2 家比价）、M-SCR-HMS1（废钢重废1型，2 家比价）。扫所有在有效期报价，按品类检索供应商资质与行情库给比价建议与废钢判级。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace（rag=供应商资质与行情库 + memory + ontology SCM identifiers + data_interface + skill + memory.extract）
- [ ] tool_call：listSuppliers/listQuotations/compareQuotations/listScrapGrades/getScrapPrice/listPayables，args 带真实 S-STEEL-/ASQ/SCR-/M-SCR-
- [ ] no-guessing：SCR- vs M-SCR- 前缀转换正确
- [ ] 输出四段（含多家比价排序 + 废钢判级 + 应付逾期风险）
