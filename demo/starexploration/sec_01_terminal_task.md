# SEC-01 涉密内容检测与文档脱密

> 星途勘探涉密资质单位特色场景：保密管控为核心域。

## 1. 演示身份
组织 `starexploration` / 用户 `sec-officer` / 口令 `12345678`（保密办公室·保密检测组）/ 终端 `/starexploration/terminal/login` / template_agent_id `c45d1171-33d2-4e5c-a3fd-c0c76d46e621`（`starexploration-sec-01-confidentiality-desensitize`）

## 2. 前置条件
docker compose 起；5 seed 跑完；provider 真 key（A3）；backend 注入 mock 包（A1）。

## 3. 操作步骤
登录 sec-officer → 新建任务 → TaskConfig(glm-5.2 / craft / 绑 template agent starexploration-sec-01-confidentiality-desensitize / 勾技能 starexploration-security-sec-des-epc-query) → 粘贴 composer。

| template_agent_id | skill | RAG | scope |
|---|---|---|---|
| c45d1171-33d2-4e5c-a3fd-c0c76d46e621 | starexploration-security-sec-des-epc-query | 涉密检测与脱密规则库 | dept(security) |

**Composer**：
```
对来源图纸 DWG-STR-001 做涉密检测：调 scanConfidentiality 返密级与涉密标记 SECMARK-，机密/秘密则调 desensitizeDocument 产脱敏记录 DESEN-，并列保密行为预警 BHV-。
```

## 4. 期望输出
- 6 trace（template:true / rag vector 涉密检测与脱密规则库 / memory.load / ontology 34 / data_interface / memory.extract）
- tool_call 调 `scanConfidentiality`(source_doc=DWG-STR-001, source_system=DES) / `desensitizeDocument`(DWG-ARC-001, DES) / `listConfidentialDocs`(SECDOC-) / `listBehaviorAnomalies`(BHV-)
- 多段文本：①涉密检测结果（密级+SECMARK-+是否需脱密）②脱密记录（DESEN-，前密级→后内部）③保密行为预警
- no-guessing：SECDOC-.source_doc 按 source_system 跳转 DES→DWG- / EPC→PDOC-（A7）

## 5. 故障排查
- LLM 无文本：`insufficient_quota` 429（A3/环境）
- 404：涉密文档 SECDOC-.source_doc 关联 DES DWG- 或 EPC PDOC-，勿把 SECDOC- 当 DWG- 传 DES、勿当 PDOC- 传 EPC（A7）

## 6. 手工 curl 复现
```bash
BASE=http://127.0.0.1:8000; AGENT=c45d1171-33d2-4e5c-a3fd-c0c76d46e621
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starexploration","username":"sec-officer","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"SEC-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"对来源图纸 DWG-STR-001 做涉密检测：调 scanConfidentiality 返密级与涉密标记 SECMARK-，机密/秘密则调 desensitizeDocument 产脱敏记录 DESEN-，并列保密行为预警 BHV-。","stream":true}'
```

## 7. 验收要点
- [ ] template:true + 6 trace
- [ ] tool_call 真实码（DWG-STR-001/SECDOC-001/SECMARK-001/DESEN-2026-001/BHV-2026-001），按 source_system 跳转无 404
- [ ] RAG vector 非 keyword_fallback + 多段文本 + 重跑稳定
