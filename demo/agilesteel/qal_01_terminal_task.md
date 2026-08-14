# QAL-01 表面缺陷检测与质量追溯

> 归口质量管理部·质量工程组，用户 `qal-engineer`。glm-5.2 / craft。
> template_agent_id `9c8add96-7c8e-4c02-8721-34760bfd15aa`（`agilesteel-qal-01-defect-traceability`）。

## 1. 演示身份
组织 `agilesteel`，用户 `qal-engineer` / `12345678`，部门 quality，团队 qal-engineering。

## 2. 前置条件
平台 + mock + 5 seed + glm-5.2 路由。

## 3. 操作步骤
登录 `/agilesteel/terminal/login` → glm-5.2 / craft / 绑智能体 `缺陷检测与质量追溯` → 贴 composer：

```
对当前未闭环钢材表面缺陷做根因分析与全流程质量追溯，重点 DF20260701（P-ST-Q345B 表面裂纹）、DF20260703（P-ST-40Cr 非金属夹杂）。扫所有未闭环缺陷，按缺陷类型检索质量缺陷案例库给根因/纠正/预防与追溯链路。

/agilesteel-quality-mes-plm-query
```

## 4. 期望输出
四段：① 缺陷汇总表 ② 根因分析报告（5W2H + 炉次成分温度 + 同类历史案例 DF-AS-） ③ 全流程追溯链路（DF→SWO→HT→P-ST-→DF-AS-） ④ 闭环待办。

## 5. 故障排查
- DF vs DF-AS- 坑：MES 缺陷 `DF20260701`（裸码）≠ PLM 钢种历史 `DF-AS-2026001`，调 listDefectHistory 按 style_code=P-ST- 关联勿直传 DF
- `getHeat(HT...)` → 炉次号从缺陷工单 work_order_no 反查
- P-ST- vs P-MELT 坑：钢种 P-ST-Q345B ≠ HR 岗位 P-MELT，按第二段区分

## 6. 附：手工调 API 复现
```bash
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug -H "Content-Type: application/json" -d '{"slug":"agilesteel","username":"qal-engineer","password":"12345678"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"title":"表面缺陷检测与质量追溯","config":{"template_agent_id":"9c8add96-7c8e-4c02-8721-34760bfd15aa","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"message":"对当前未闭环钢材表面缺陷做根因分析与全流程质量追溯，重点 DF20260701（P-ST-Q345B 表面裂纹）、DF20260703（P-ST-40Cr 非金属夹杂）。扫所有未闭环缺陷，按缺陷类型检索质量缺陷案例库给根因/纠正/预防与追溯链路。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace（rag=质量缺陷案例库 + memory + ontology MES/PLM identifiers + data_interface + skill + memory.extract）
- [ ] tool_call：listDefects/getDefectRootCause/listHeats/getHeat/listSteelGrades/getSteelGrade/listDefectHistory，args 带真实 DF/HT/P-ST-
- [ ] no-guessing：缺陷 DF20260701 vs 历史 DF-AS- 不混传；钢种 P-ST-Q345B 前缀正确
- [ ] 追溯链路 DF→SWO→HT→P-ST-→DF-AS- 完整
