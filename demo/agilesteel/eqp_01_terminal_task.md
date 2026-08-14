# EQP-01 关键设备预测性维护与备件建议

> 归口设备管理部·设备工程组，登录用户 `eqp-engineer`。模型 `glm-5.2`，exec_mode `craft`。

## 1. 演示身份
- 组织 `agilesteel`，用户 `eqp-engineer` / `12345678`，member，部门 equipment，团队 eqp-engineering
- template_agent_id `736bae0e-8d55-43df-b2ed-4d0fc455ad1f`（`agilesteel-eqp-01-predictive-maintenance`）

## 2. 前置条件
平台 + mock（含 EQM）+ 5 seed + glm-5.2 路由（README §3）。EQM health：`curl -H "X-API-Key: eqm-agilesteel-demo-key" http://localhost:8010/eqm/health`。

## 3. 操作步骤
登录 `/agilesteel/terminal/login` → 新建任务 → 模型 `glm-5.2` / craft / 绑定智能体 `设备预测性维护` → 贴 composer：

```
对关键设备做预测性维护与备件建议，重点 EQ-CV-2（2#转炉，fault）、EQ-RM-3（3#连轧机，maintenance）。扫所有待执行维护建议，按设备类型检索设备故障案例库给根因/排查/备件/优先级。

/agilesteel-equipment-eqm-query
```

## 4. 期望输出
四段：① 设备健康与故障预测表 ② 维护优先级队列 ③ 备件建议清单 ④ 同类故障案例根因与预防（RAG 命中）。

## 5. 故障排查
- `predictEquipmentFailure(code)` not found → 设备码 EQ-CV-2 写对（identifiers.md：EQ- 与 MES 共享码空间，勿转换）
- 备件 below_safety → listSpareParts 返回标低安全库存项
- RAG keyword_fallback → embedding 未通（README §3 provider 同步）

## 6. 附：手工调 API 复现
```bash
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug -H "Content-Type: application/json" -d '{"slug":"agilesteel","username":"eqp-engineer","password":"12345678"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"title":"关键设备预测性维护与备件建议","config":{"template_agent_id":"736bae0e-8d55-43df-b2ed-4d0fc455ad1f","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"message":"对关键设备做预测性维护与备件建议，重点 EQ-CV-2（2#转炉，fault）、EQ-RM-3（3#连轧机，maintenance）。扫所有待执行维护建议，按设备类型检索设备故障案例库给根因/排查/备件/优先级。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace（rag=设备故障案例库 vector + memory.load + ontology EQM identifiers + data_interface + skill + memory.extract）
- [ ] tool_call 调 EQM 端点：listEquipment/getEquipment/listSensorReadings/predictEquipmentFailure/scoreMaintenancePriority/listSpareParts/listFaultHistory，args 带真实设备码 EQ-CV-2/EQ-RM-3
- [ ] no-guessing：设备码 EQ-CV-2/EQ-RM-3、备件 SP-CV-TUYERE/SP-RM-ROLL 命中正确前缀
- [ ] 输出四段（含故障概率、优先级队列、备件库存）
