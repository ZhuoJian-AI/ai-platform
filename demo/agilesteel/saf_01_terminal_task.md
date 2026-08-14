# SAF-01 现场违章识别与隐患排查

> 归口安全环保部·安全巡检组，用户 `saf-inspector`。glm-5.2 / craft。
> template_agent_id `97afc5c4-8609-4ec6-9b82-4bf11c4d317b`（`agilesteel-saf-01-hazard-closure`）。新 EHS 子系统作技能主体。

## 1. 演示身份
组织 `agilesteel`，用户 `saf-inspector` / `12345678`，部门 safety，团队 saf-inspection。

## 2. 前置条件
平台 + mock（含 EHS）+ 5 seed + glm-5.2 路由。EHS health：`curl -H "X-API-Key: ehs-agilesteel-demo-key" http://localhost:8010/ehs/health`。

## 3. 操作步骤
登录 `/agilesteel/terminal/login` → glm-5.2 / craft / 绑智能体 `违章识别与隐患闭环` → 贴 composer：

```
对当前未闭环隐患做违章分类与闭环管理，重点 HD20260002（1#高炉煤气泄漏，红）、HD20260001（2#转炉液渣喷溅，红）。扫所有未闭环隐患，按违章类型检索安全法规与隐患案例库给分类/规程/整改优先级。

/agilesteel-safety-ehs-query
```

## 4. 期望输出
四段：① 违章分类清单（类型/规程条款/整改建议/处置） ② 隐患优先级队列（P0/P1） ③ 风险点分级表 ④ 闭环待办。

## 5. 故障排查
- `detectViolationType`（GET /violation-classify）与 `scoreHazardPriority`（GET /hazard-priority）是静态路径，已避开 {code} 路由阴影
- 红色隐患 HD20260001/HD20260002 须 24h 闭环 + 联动应急
- 隐患 equipment_code 关联 EQ- 设备（HD20260002→EQ-BF-1）

## 6. 附：手工调 API 复现
```bash
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug -H "Content-Type: application/json" -d '{"slug":"agilesteel","username":"saf-inspector","password":"12345678"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"title":"现场违章识别与隐患排查","config":{"template_agent_id":"97afc5c4-8609-4ec6-9b82-4bf11c4d317b","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"message":"对当前未闭环隐患做违章分类与闭环管理，重点 HD20260002（1#高炉煤气泄漏，红）、HD20260001（2#转炉液渣喷溅，红）。扫所有未闭环隐患，按违章类型检索安全法规与隐患案例库给分类/规程/整改优先级。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace（rag=安全法规与隐患案例库 + memory + ontology EHS identifiers + data_interface + skill + memory.extract）
- [ ] tool_call 调 EHS 端点：listHazards/getHazard/listViolations/detectViolationType/listInspections/listSafetyRisks/listPpe/scoreHazardPriority
- [ ] no-guessing：隐患 HD-、违章 VIO-、巡检 INS- 前缀正确；隐患 equipment_code 关联 EQ- 正确
- [ ] 输出四段（含违章分类 + 隐患优先级 P0/P1 + 红色隐患应急）
