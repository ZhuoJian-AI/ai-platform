# MFG-01 转炉终点碳温预测与一体化排产

> 场景文档（7 节）。归口生产制造部·排产计划组，登录用户 `mfg-planner`。模型 `glm-5.2`，exec_mode `craft`。

## 1. 演示身份
- 组织 slug：`agilesteel`（敏睿钢铁）
- 用户名：`mfg-planner` / 密码：`12345678`（统一）
- 角色：member，部门 production，团队 prod-planning
- template_agent_id：`528bb570-9f30-4769-b54c-ff89ae630ef7`（`agilesteel-mfg-01-endpoint-scheduling`）

## 2. 前置条件
- 平台 + mock 网关运行（`docker compose up -d`，mock 含 EQM/EMS/EHS）
- 5 个 seed 已跑（org / mock_connectors / ontology / rag / agents）
- glm-5.2 路由指向 `aliyun-all-openai`（真实 key，见 README §3）
- mock health：`curl -H "X-API-Key: mes-agilesteel-demo-key" http://localhost:8010/mes/health`

## 3. 操作步骤
1. 登录 `http://localhost:8000/agilesteel/terminal/login`（mfg-planner / 12345678）
2. 新建任务
3. TaskConfigDrawer：模型 `glm-5.2` / exec_mode `craft` / 绑定智能体 `终点碳温预测与排产`
4. composer 提示词（贴入）：

```
对当前在制炉次做转炉终点碳温命中率预测 + 炼钢-连铸-轧钢一体化排产方案，重点 HT2026063001（P-ST-Q345B，EQ-CV-1 在制）、HT2026063002（P-ST-45#，EQ-CV-2 待吹炼）。扫所有未完工炉次，按钢种检索排产与炼钢规则库给排产优先级与命中率预测。

/agilesteel-production-mes-erp-query
```

5. 提交运行，观察 SSE

## 4. 期望输出
四段分析上屏 + generate_docx：
1. 一体化排产方案表（炉次 | 钢种 | 转炉 | 计划吨位 | 连铸 | 轧制线 | 开工 | 交期 | 关联销售订单 ASSO | 优先级）
2. 终点碳温命中率预测（近期命中率 | 预测下批 | 达标判定 | 改进建议）
3. 风险提示（设备停机 EQ-CV-2/EQ-RM-3 | 钢坯库存 | 交期冲突 | 能耗）

## 5. 故障排查
- model not available → 检查 glm-5.2 路由指向 aliyun-all-openai（README §3）
- skill chip 不识别 → 检查 `agilesteel-production-mes-erp-query` 技能已绑（管理端技能页）
- tool_call args `{}` → 检查端点 spec 已导入（mock_connectors seed）
- `getHeat(HT...) not found` → 炉次号 HT2026063001/3002 写对（identifiers.md P- 坑不适用，HT 前缀）
- RAG retriever=keyword_fallback → embedding 未通（跑 reembed 或检查 aliyun-embedding provider）

## 6. 附：手工调 API 复现
```bash
# 1) 登录取 token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agilesteel","username":"mfg-planner","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) 创建任务（绑 template_agent_id + 模型 + craft）
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"转炉终点碳温预测与一体化排产","config":{"template_agent_id":"528bb570-9f30-4769-b54c-ff89ae630ef7","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "task=$TASK"

# 3) 运行（SSE 流）
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"对当前在制炉次做转炉终点碳温命中率预测 + 炼钢-连铸-轧钢一体化排产方案，重点 HT2026063001（P-ST-Q345B，EQ-CV-1 在制）、HT2026063002（P-ST-45#，EQ-CV-2 待吹炼）。扫所有未完工炉次，按钢种检索排产与炼钢规则库给排产优先级与命中率预测。","stream":true}'
```

## 7. 验收要点
- [ ] `load_config` event `template:true`（模板注入）
- [ ] 6 类 trace：rag + memory.load + ontology + data_interface + skill + memory.extract
- [ ] `tool_call` args 非全 `{}`（listHeats/getHeat/listProductionOrders 等带真实参数）
- [ ] no-guessing：炉次号 HT2026063001 / 钢种 P-ST-Q345B / 设备 EQ-CV-1 命中正确前缀
- [ ] 输出含三段 + generate_docx 附件
- [ ] 同一 prompt 跑 2 次，第二次 text 字符数不暴跌（稳定性）
