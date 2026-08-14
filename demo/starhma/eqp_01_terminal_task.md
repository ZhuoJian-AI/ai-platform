# EQP-01 设备预测性维护与保养提醒

## 1. 演示身份
- 组织 slug：`starhma`（星途热熔胶）
- 登录用户：`eqp-maintainer` / 口令 `12345678`（生产制造部·设备运维组，role=member）
- 终端登录：`/starhma/terminal/login`
- template_agent_id：`9f6a623a-88dd-4b3c-a40f-3b58e6fb1872`（slug `starhma-eqp-01-predictive-maintenance`）

## 2. 前置条件
- docker compose 起 pg/redis/backend/mock；mock 网关 :8010 含 frm/pcm/qas（已重启加载）
- 5 个 seed 按序跑完（org → mock_connectors → ontology → rag → agents）
- provider 真 key 已从 agileac 复制（A3）；backend 已注入 mock 包（A1）

## 3. 操作步骤
1. 浏览器登录 `/starhma/terminal/login`（用户 eqp-maintainer）
2. 新建任务，标题「设备预测性维护与保养提醒」
3. TaskConfigDrawer：model=`glm-5.2` / exec_mode=`craft` / 绑定 template agent `starhma-eqp-01-predictive-maintenance` / 勾选归口技能 `starhma-eqp-pcm-mes-query`
4. 粘贴 composer（见下）→ 提交，观察 SSE 流
5. 资源注入表：

| template_agent_id | skill_slug | RAG collection | model_alias | exec_mode | scope |
|---|---|---|---|---|---|
| 9f6a623a-88dd-4b3c-a40f-3b58e6fb1872 | starhma-eqp-pcm-mes-query | starhma-eqp-maintenance-kb | glm-5.2 | craft | dept(mfg) |

**Composer（L1 短问题，不含编排/场景代号）**：
```
对设备 EQ-MTR-02 做预测性维护：调 predictEquipmentFault 看振动/温升/健康分，给风险等级与保养提醒，关联产线 LINE-AUTO-02 与工艺参数 PP-REACT-002。
```

## 4. 期望输出
- 6 trace（template:true / rag vector starhma-eqp-maintenance-kb / memory.load / ontology / data_interface / memory.extract）
- tool_call 调 PCM `listEquipment`/`getEquipment`(EQ-MTR-02) / `predictEquipmentFault`(EQ-MTR-02) / `getEquipmentRunData` / `listProcessParams`(PP-REACT-002) / `recommendProcessParams` / MES `listEquipmentStatus`/`getEquipment`，args 用真实码
- 多段文本：①设备运行数据（振动/温升/健康分趋势）②故障风险等级与预测（高/中/低+预估时间窗）③保养提醒与建议措施④关联产线 LINE-AUTO-02 与工艺参数 PP-REACT-002 的影响分析
- 跨系统：PCM EQ-MTR-02 → MES LINE-AUTO-02（line）；PCM PP-REACT-002 → MES 工单

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：path 参数用真实码（EQ-MTR-02/PP-REACT-002/LINE-AUTO-02），见 A7/A8
- RAG keyword_fallback：embedding 真 key 未生效（A3）

## 6. 附：手工调 API 复现
```bash
BASE=http://127.0.0.1:8000
AGENT=9f6a623a-88dd-4b3c-a40f-3b58e6fb1872
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starhma","username":"eqp-maintainer","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"EQP-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"对设备 EQ-MTR-02 做预测性维护：调 predictEquipmentFault 看振动/温升/健康分，给风险等级与保养提醒，关联产线 LINE-AUTO-02 与工艺参数 PP-REACT-002。","stream":true}'
```

## 7. 验收要点
- [ ] `template:true` + 6 trace
- [ ] tool_call args 真实码（EQ-MTR-02/PP-REACT-002/LINE-AUTO-02），PCM→MES 闭环无 404
- [ ] RAG vector 非 keyword_fallback
- [ ] 多段文本上屏（运行数据/风险等级/保养提醒/产线工艺关联）
- [ ] 第二次重跑稳定
