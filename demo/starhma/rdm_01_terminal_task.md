# RDM-01 配方智能推荐与初始配比

## 1. 演示身份
- 组织 slug：`starhma`（星途热熔胶）
- 登录用户：`rd-formulator` / 口令 `12345678`（研发中心·配方研发组，role=member）
- 终端登录：`/starhma/terminal/login`
- template_agent_id：`e5188ebd-24e3-4adc-8fa7-8118832da288`（slug `starhma-rdm-01-formula-recommend`）

## 2. 前置条件
- docker compose 起 pg/redis/backend/mock；mock 网关 :8010 含 frm/pcm/qas（已重启加载）
- 5 个 seed 按序跑完（org → mock_connectors → ontology → rag → agents）
- provider 真 key 已从 agileac 复制（aliyun-embedding-openai + aliyun-all-openai，GLM 路由指向 aliyun-all-openai）—— 见 KNOWN_ISSUES A3
- backend 已注入 mock 包（`docker cp mock/mock/systems/frm ...` 等，见 A1）

## 3. 操作步骤
1. 浏览器登录 `/starhma/terminal/login`（用户 rd-formulator）
2. 新建任务，标题「配方智能推荐与初始配比」
3. TaskConfigDrawer：model=`glm-5.2` / exec_mode=`craft` / 绑定 template agent `starhma-rdm-01-formula-recommend` / 勾选归口技能 `starhma-rd-frm-erp-query`
4. 粘贴 composer（见下）→ 提交，观察 SSE 流
5. 资源注入表：

| template_agent_id | skill_slug | RAG collection | model_alias | exec_mode | scope |
|---|---|---|---|---|---|
| e5188ebd-24e3-4adc-8fa7-8118832da288 | starhma-rd-frm-erp-query | starhma-rd-formula-kb | glm-5.2 | craft | dept(rd) |

**Composer（L1 短问题，不含编排/场景代号）**：
```
对医疗用品低温热熔胶做配方智能推荐：客户基材无纺布/PE 膜、施胶温度 130℃、开放时间 6s、剥离力 14N、需 FDA 与 ISO-10993 环保、成本上限 40 元/kg；推荐历史相似配方 FORM-CUS-002 与初始配比 ING-RES-001/ING-TK-002，并给预估性能。
```

## 4. 期望输出
- SSE trace（6 类）：`template:true`（step load_config）→ `template` 注入（slug starhma-rdm-01-formula-recommend）→ `rag` retriever=vector hits（starhma-rd-formula-kb）→ `memory.load` → `ontology` → `data_interface` 目录 → `memory.extract`
- tool_call 调 `listFormulas`/`recommendFormula`(需求参数) / `getFormula`(FORM-CUS-002) / `predictPerformance` / `listMaterials`(M-RES-001/M-TK-002) / `listInventory`，args 用真实码
- 多段文本：①相似配方命中表 ②初始配比（组分 ING-RES-001/ING-TK-002 + 比例）③预估性能（开放时间/剥离力/施胶温度）④成本测算 vs 40 元/kg
- no-guessing：ING-RES-001→M-RES-001 prefix 转换（A7）调用 ERP listMaterials 时正确转码

## 5. 故障排查
- LLM 无文本输出 + latency ~800ms：查 backend 日志 `insufficient_quota` 429（aliyun-all-openai token-plan 耗尽，A3/环境），等配额恢复或换 provider
- 6 trace 缺一：检查 seed 是否全跑（ontology / rag hits>0 / skill bound）
- tool_call 404：检查 path 参数用真实码（FORM-CUS-002 非 {code}），见 A7/A8
- RAG retriever=keyword_fallback：embedding provider 未生效（A3），查 aliyun-embedding-openai 真 key

## 6. 附：手工调 API 复现
```bash
BASE=http://127.0.0.1:8000
AGENT=e5188ebd-24e3-4adc-8fa7-8118832da288
# 1. 登录
TOKEN=$(curl -s -X POST "$BASE/api/v1/users/login-by-slug" -H 'Content-Type: application/json' \
  -d '{"slug":"starhma","username":"rd-formulator","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
# 2. 建任务
TASK=$(curl -s -X POST "$BASE/api/v1/terminal/tasks" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d "{\"title\":\"RDM-01\",\"config\":{\"template_agent_id\":\"$AGENT\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
# 3. 跑任务
curl -sN -X POST "$BASE/api/v1/terminal/tasks/$TASK/run" -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"对医疗用品低温热熔胶做配方智能推荐：客户基材无纺布/PE 膜、施胶温度 130℃、开放时间 6s、剥离力 14N、需 FDA 与 ISO-10993 环保、成本上限 40 元/kg；推荐历史相似配方 FORM-CUS-002 与初始配比 ING-RES-001/ING-TK-002，并给预估性能。","stream":true}'
```

## 7. 验收要点
- [ ] `template:true`（step load_config）
- [ ] 6 trace 全出（template/rag/memory.load/ontology/data_interface/memory.extract）
- [ ] tool_call args 非空，用真实码（FORM-CUS-002/ING-RES-001/ING-TK-002/M-RES-001），no-guessing 精确命中无 404
- [ ] RAG retriever=vector 非 keyword_fallback
- [ ] 多段文本上屏（相似配方/初始配比/预估性能/成本测算）
- [ ] 第二次重跑稳定
