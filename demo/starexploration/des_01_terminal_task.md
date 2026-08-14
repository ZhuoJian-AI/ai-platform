# DES-01 设计方案智能比选与规范合规校验

## 1. 演示身份
- 组织 slug：`starexploration`（星途勘探）
- 登录用户：`des-engineer` / 口令 `12345678`（设计研究院·设计合规组，role=member）
- 终端登录：`/starexploration/terminal/login`
- template_agent_id：`3f879a34-46ec-49de-89b3-604bfe8dc1b0`（slug `starexploration-des-01-scheme-compliance`）

## 2. 前置条件
- docker compose 起 pg/redis/backend/mock；mock 网关 :8010 含 des/epc/sec（已重启加载）
- 5 个 seed 按序跑完（org → mock_connectors → ontology → rag → agents）
- provider 真 key 已从 agileac 复制（aliyun-embedding-openai + aliyun-all-openai，GLM 路由指向 aliyun-all-openai）—— 见 KNOWN_ISSUES A3
- backend 已注入 mock 包（`docker cp mock/mock/systems/des ...` 等，见 A1）

## 3. 操作步骤
1. 浏览器登录 `/starexploration/terminal/login`（用户 des-engineer）
2. 新建任务，标题「设计方案比选与合规校验」
3. TaskConfigDrawer：model=`glm-5.2` / exec_mode=`craft` / 绑定 template agent `starexploration-des-01-scheme-compliance` / 勾选归口技能 `starexploration-design-des-erp-query`
4. 粘贴 composer（见下）→ 提交，观察 SSE 流
5. 资源注入表：

| template_agent_id | skill_slug | RAG collection | model_alias | exec_mode | scope |
|---|---|---|---|---|---|
| 3f879a34-46ec-49de-89b3-604bfe8dc1b0 | starexploration-design-des-erp-query | 设计规范与方案比选规则库 | glm-5.2 | craft | dept(design) |

**Composer（L1 短问题，不含编排/场景代号）**：
```
对 SCH-IND-001 电工装备制造厂房方案做规范合规校验：重点查图纸 DWG-ARC-001 与 DWG-STR-001 的强条合规性，并列出该方案内跨专业碰撞 CLS-。
```

## 4. 期望输出
- SSE trace（6 类）：`template:true`（step load_config）→ `template` 注入（slug starexploration-des-01-scheme-compliance）→ `rag` retriever=vector hits=5（设计规范与方案比选规则库）→ `memory.load` → `ontology` 34 files → `data_interface` 目录 → `memory.extract`
- tool_call 调 `listSchemes`/`getScheme`/`listDrawings`/`checkDrawingCompliance`(DWG-ARC-001/DWG-STR-001)/`detectClashes`(SCH-IND-001)，args 用真实码
- 多段文本：①方案比选表 ②规范合规校验结果（违规项+SPEC-GB-条款+修正建议+是否通过）③跨专业碰撞协调建议
- 分析完成可调 `generate_docx` 打包附件（glm-5.2 自主决定，text-only 收尾亦可）

## 5. 故障排查
- LLM 无文本输出 + latency ~800ms：查 backend 日志 `insufficient_quota` 429（aliyun-all-openai token-plan 耗尽，A3/环境），等配额恢复或换 provider
- 6 trace 缺一：检查 seed 是否全跑（ontology 34 / rag hits>0 / skill bound）
- tool_call 404：检查 path 参数用真实码（DWG-ARC-001 非 {code}），见 A7/A8
- RAG retriever=keyword_fallback：embedding provider 未生效（A3），查 aliyun-embedding-openai 真 key

## 6. 附：手工调 API 复现
```bash
BASE=http://127.0.0.1:8000
AGENT=3f879a34-46ec-49de-89b3-604bfe8dc1b0
# 1. 登录
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starexploration","username":"des-engineer","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
# 2. 建任务
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"DES-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
# 3. 跑任务
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"对 SCH-IND-001 电工装备制造厂房方案做规范合规校验：重点查图纸 DWG-ARC-001 与 DWG-STR-001 的强条合规性，并列出该方案内跨专业碰撞 CLS-。","stream":true}'
```

## 7. 验收要点
- [ ] `template:true`（step load_config）
- [ ] 6 trace 全出（template/rag/memory.load/ontology/data_interface/memory.extract）
- [ ] tool_call args 非空，用真实码（SCH-IND-001/DWG-ARC-001/DWG-STR-001/CLS-2026-001），no-guessing 精确命中无 404
- [ ] RAG retriever=vector 非 keyword_fallback
- [ ] 多段文本上屏 +（可选）generate_docx
- [ ] 第二次重跑稳定
