# LEG-01 合同智能审查与履约风险校验

## 1. 演示身份
- 组织 `starexploration` / 用户 `leg-counsel` / 口令 `12345678`（法律合规部·合同审查组）
- 终端登录 `/starexploration/terminal/login`
- template_agent_id：`bd6e5ba7-02ea-4e05-834c-89040e49aa26`（`starexploration-leg-01-contract-review`）

## 2. 前置条件
docker compose 起；5 seed 跑完；provider 真 key 已复制（A3）；backend 注入 mock 包（A1）。

## 3. 操作步骤
登录 leg-counsel → 新建任务 → TaskConfig(model=glm-5.2 / exec_mode=craft / 绑 template agent starexploration-leg-01-contract-review / 勾技能 starexploration-legal-crm-erp-query) → 粘贴 composer → 提交。

| template_agent_id | skill | RAG | model | exec_mode | scope |
|---|---|---|---|---|---|
| bd6e5ba7-02ea-4e05-834c-89040e49aa26 | starexploration-legal-crm-erp-query | 合同审查与合规规则库 | glm-5.2 | craft | dept(legal) |

**Composer**：
```
对合同 CT-SE-002 电池工厂 EPC 总承包合同做智能审查：提取关键条款、识别风险点（付款里程碑/保密条款）、关联项目 PRJ-BAT-001 与履约争议 DSP-，给修改建议与履约节点提醒。
```

## 4. 期望输出
- 6 trace（template:true / rag vector 合同审查与合规规则库 / memory.load / ontology 34 / data_interface / memory.extract）
- tool_call 调 `listSalesOrders`(CT-SE-002) / `listCustomers`(CLI-002) / `listComplaints`(DSP-) / `listReceivables`(INV-) / `listVouchers`(BV-SE-)，跨 CRM/ERP
- 多段文本：①合同审查意见（风险点+修改建议）②履约风险校验（节点提醒+争议 DSP-）③法律文书草稿

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：合同 CT-SE- 与项目 PRJ- 按 client_code 关联（PRJ-BAT-001.client_code='CT-SE-002'），履约争议 DSP-.product_code 承载 PRJ-，勿直传（A7）
- RAG keyword_fallback：embedding key 未生效（A3）

## 6. 手工 curl 复现
```bash
BASE=http://127.0.0.1:8000; AGENT=bd6e5ba7-02ea-4e05-834c-89040e49aa26
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starexploration","username":"leg-counsel","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"LEG-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"对合同 CT-SE-002 电池工厂 EPC 总承包合同做智能审查：提取关键条款、识别风险点（付款里程碑/保密条款）、关联项目 PRJ-BAT-001 与履约争议 DSP-，给修改建议与履约节点提醒。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace
- [ ] tool_call 用真实码（CT-SE-002/CLI-002/PRJ-BAT-001/DSP-0002/INV202607002），跨 CRM/ERP 无 404
- [ ] RAG vector 非 keyword_fallback
- [ ] 多段文本 + 可选 docx + 重跑稳定
