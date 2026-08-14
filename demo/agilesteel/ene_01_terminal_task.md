# ENE-01 能源介质平衡调度与排放预警

> 归口能源环保部·能源调度组，用户 `ene-dispatcher`。glm-5.2 / craft。
> template_agent_id `0a7c2db4-56f6-4418-827b-11ba5866ac62`（`agilesteel-ene-01-energy-dispatch`）。新 EMS 子系统作技能主体。

## 1. 演示身份
组织 `agilesteel`，用户 `ene-dispatcher` / `12345678`，部门 energy，团队 ene-dispatch。

## 2. 前置条件
平台 + mock（含 EMS）+ 5 seed + glm-5.2 路由。EMS health：`curl -H "X-API-Key: ems-agilesteel-demo-key" http://localhost:8010/ems/health`。

## 3. 操作步骤
登录 `/agilesteel/terminal/login` → glm-5.2 / craft / 绑智能体 `能源调度与排放预警` → 贴 composer：

```
对本班次做能源介质平衡调度与排放预警，重点煤气放散（EM-GAS-BF1 压力低）+ 烧结 SO2（EMS-SO2-SINTER 临界）。扫所有介质缺口与排放临界，按介质检索能源调度规则库给调度方案与碳足迹。

/agilesteel-energy-ems-query
```

## 4. 期望输出
四段：① 介质平衡调度方案（含缺口 + EDP 调度建议 + 预计节能） ② 排放预警清单（SO2/NOx/颗粒物/CO2 + 风险 + 整改优先级） ③ 工序能耗标杆对比 ④ 碳足迹核算。

## 5. 故障排查
- `predictMediaShortfall` 返回 gap<0 为缺口，调度建议关联 EDP 调度方案
- `scoreEmissionRisk` value/limit≥0.95 为高风险 P0
- 计量点 EM- 前缀（EM-GAS-BF1/EM-STM-LF1/EM-PWR-MAIN），排放源 EMS- 前缀

## 6. 附：手工调 API 复现
```bash
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug -H "Content-Type: application/json" -d '{"slug":"agilesteel","username":"ene-dispatcher","password":"12345678"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"title":"能源介质平衡调度与排放预警","config":{"template_agent_id":"0a7c2db4-56f6-4418-827b-11ba5866ac62","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"message":"对本班次做能源介质平衡调度与排放预警，重点煤气放散（EM-GAS-BF1 压力低）+ 烧结 SO2（EMS-SO2-SINTER 临界）。扫所有介质缺口与排放临界，按介质检索能源调度规则库给调度方案与碳足迹。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace（rag=能源调度规则库 + memory + ontology EMS identifiers + data_interface + skill + memory.extract）
- [ ] tool_call 调 EMS 端点：listMeters/listMediaBalance/predictMediaShortfall/listEmissions/scoreEmissionRisk/listEnergyConsumption/listDispatchPlans/listAlarms，args 带真实 EM-/EMS-
- [ ] no-guessing：计量点 EM-、排放 EMS-、调度 EDP、预警 EA 前缀正确
- [ ] 输出四段（含介质缺口调度 + 排放超标风险 + 碳足迹达标判定）
