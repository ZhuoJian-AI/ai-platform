# 星途勘探 POC 已知问题（KNOWN_ISSUES）

> 与 agilesteel / agilestationery 共享后端，编号沿用 A 系列。A1/A2/A4/A5/A6/A8/A9/A10 为共享后端问题，A3/A7 为星途勘探特有。

## A1 · backend 容器无 mock 包（共享）
backend 镜像未含 `mock` 包、无 volume 挂载。`seed_starexploration_mock_connectors.py` 与 agent 运行时 `import mock.core.registry` 需先注入：

```bash
# 注意：docker cp mock/mock ai_infra_backend:/app/mock 会建嵌套 /app/mock/mock/，错误！
# 正确做法（按文件/目录把内容放进 /app/mock/）：
docker exec ai_infra_backend rm -rf /app/mock/mock
docker cp mock/mock/core/registry.py ai_infra_backend:/app/mock/core/registry.py
docker cp mock/mock/systems/des ai_infra_backend:/app/mock/systems/des
docker cp mock/mock/systems/epc ai_infra_backend:/app/mock/systems/epc
docker cp mock/mock/systems/sec ai_infra_backend:/app/mock/systems/sec
docker cp mock/mock/systems/erp/data.py ai_infra_backend:/app/mock/systems/erp/data.py
docker cp mock/mock/systems/hrm/data.py ai_infra_backend:/app/mock/systems/hrm/data.py
docker cp mock/mock/systems/crm/data.py ai_infra_backend:/app/mock/systems/crm/data.py
```

重建 backend 后必做（含 des/epc/sec + erp/hrm/crm 改动）。根因修复：docker-compose 加 volume 挂载 mock 包。

## A2 · mock OpenAPI 快照（共享）
mock 重建后需重生成 `mock/openapi/{des,epc,sec}.json`（host py3.6 不支持 future annotations）：

```bash
docker exec ai_infra_mock python -m mock openapi
docker cp ai_infra_mock:/app/openapi/des.json mock/openapi/des.json
docker cp ai_infra_mock:/app/openapi/epc.json mock/openapi/epc.json
docker cp ai_infra_mock:/app/openapi/sec.json mock/openapi/sec.json
```

或 host `curl :8010/<sys>/openapi.json` 落盘。mock_connectors seed 优先打活网关 `MOCK_BASE_URL`，不可达才回退快照。

## A3 · provider 占位无 embedding/chat 能力（星途勘探特有，关键）
4 个占位 provider（Anthropic/OpenAI/DeepSeek/智谱 AI，api_key=PRESET-REPLACE-ME）**无 embedding/chat 能力**，RAG embedding 与 agent 运行都依赖真 key。从 agileac org 复制 `aliyun-embedding-openai`（text-embedding-v4）+ `aliyun-all-openai`（glm-5.2/deepseek-v4-pro/qwen3.7-plus）含加密 key：

```sql
INSERT INTO llm_providers (id, organization_id, name, provider_type, base_url, api_key_encrypted,
  api_key_version, is_active, priority, weight, timeout_seconds, max_retries, supported_models,
  health_status, config, created_at, updated_at)
SELECT gen_random_uuid(), (SELECT id FROM organizations WHERE slug='starexploration' AND deleted_at IS NULL),
  p.name, p.provider_type, p.base_url, p.api_key_encrypted, p.api_key_version, true, p.priority, p.weight,
  p.timeout_seconds, p.max_retries, p.supported_models, 'unknown', p.config, now(), now()
FROM llm_providers p
WHERE p.organization_id=(SELECT id FROM organizations WHERE slug='agileac' AND deleted_at IS NULL)
  AND p.name IN ('aliyun-embedding-openai','aliyun-all-openai') AND p.deleted_at IS NULL;
-- GLM/DeepSeek 路由指向 aliyun-all-openai
UPDATE routing_policies SET provider_ids = jsonb_build_array(
  (SELECT id::text FROM llm_providers WHERE organization_id=(SELECT id FROM organizations WHERE slug='starexploration')
   AND name='aliyun-all-openai' AND deleted_at IS NULL))
WHERE organization_id=(SELECT id FROM organizations WHERE slug='starexploration')
  AND model_pattern IN ('glm-*','deepseek-*') AND deleted_at IS NULL;
```

**注意**：`llm_providers.id` 列无默认值，INSERT 必须显式 `gen_random_uuid()`，否则报 not-null。RAG seed 跑前必须先复制 embedding key，否则全部文档入库 failed。

## A4 · RAG 入库非幂等（共享）
RAG seed 按 (collection, source) 去重跳过已成功。但**前次入库残留 status=failed 的文档**按 source 去重会再次跳过（不会重试）。重跑前须清理：

```sql
DELETE FROM rag_documents WHERE collection_id IN (
  SELECT id FROM rag_collections WHERE organization_id=
    (SELECT id FROM organizations WHERE slug='starexploration'));
```

或先删 collection 再重跑。本 demo 首次入库 10 文档 0 失败（embedding 通畅）。

## A5 · agent_run_events.updated_at 列（共享，已修）
`agent_run_events` 表缺 `updated_at` 列致每轮 run 结束 bulk-persist 事件 `UndefinedColumnError`。已 `ALTER TABLE agent_run_events ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now() NOT NULL`（agileac/starclothing 同受益，DB 改动不入 repo）。

## A6 · generate_docx 需 workspace_id（共享）
curl 跑终端任务时若 agent 调 `generate_docx`，TaskConfig 需带 `workspace_id`，否则生成 docx 失败。终端任务界面创建会自带 workspace；纯 curl 复现须显式传。

## A7 · 跨码空间 no-guessing 标识符（星途勘探特有，关键）
星途勘探跨码空间映射规则（详见各域 identifiers.md + 上方本体 Cross）：

| from | to | 关联键 | 说明 |
|---|---|---|---|
| 算量项 `QTI-CON-`(DES) | 物料 `M-CON-`(ERP) | material_code | prefix 转换 QTI-CON-→M-CON-，勿直传 |
| 方案 `SCH-BAT-001`(DES) | 项目 `PRJ-BAT-001`(EPC) | scheme_no | 方案转项目，前缀不同需对齐 |
| 图纸 `DWG-ARC-001`(DES) | 项目文档 `PDOC-`(EPC) | linked_code | 图纸交付物 |
| 图纸 `DWG-STR-001`(DES) | 涉密文档 `SECDOC-`(SEC) | source_doc | 涉密检测/脱密对象 |
| 发票 `INV202607001`(CRM) | 凭证 `BV-SE-2026-0701`(ERP) | invoice_no | 回款发票↔凭证对账 |
| 合同 `CT-SE-001`(CRM) | 项目 `PRJ-IND-001`(EPC) | client_code | 合同关联项目 |
| 招聘需求 `ASRC.position` | 岗位 `P-`(HRM) | position_code | 同码空间直查 |
| 岗位 `P-DES`(HRM) | 物料 `M-CON-`(ERP) | prefix 区分 | 不同码空间勿互传（同 agilesteel P- 教训） |

path 参数端点必须用真实码（如 `DWG-ARC-001`），勿用 `{code}` 占位，否则 404。

## A8 · path 参用真实码（共享）
GET path 参数端点（`getScheme/{scheme_no}`、`getDrawing/{drawing_no}`、`getProject/{project_code}`、`getConfidentialDoc/{doc_no}`、`scanConfidentiality?source_doc=...` 等）调时传真实码，勿传 `{code}` / `{drawing_no}` 占位。

## A9 · memory/extract 长中文保守（共享）
`memory.extract` 对长中文文本提取可能返 0 facts，非致命（LLM 行为，非架构缺陷）。P0 验收不以此为准。

## A10 · admin 登录用 admins 表（共享）
org_admin 行不在 seed_org 脚本里，登录管理端用 `admins` 表（非 `users`）。手插：

```sql
INSERT INTO admins (id, organization_id, username, display_name, password_hash, role, is_active, created_at, updated_at)
SELECT gen_random_uuid(), (SELECT id FROM organizations WHERE slug='starexploration'),
  'admin', '组织管理员',
  (SELECT password_hash FROM admins WHERE username='admin' LIMIT 1),  -- 复用 agileac 的 password_hash
  'admin', true, now(), now()
ON CONFLICT DO NOTHING;
```

密码同 agileac（`12345678`）。仅管理端截图需用，P0 终端任务用 users 表的 des-engineer/fin-accountant/leg-counsel 登录即可。
