# 星途热熔胶 POC 已知问题（KNOWN_ISSUES）

> 与 starexploration / agilesteel / agilestationery 共享后端，编号沿用 A 系列。A1/A2/A4/A5/A6/A8/A9/A10 为共享后端问题，A3/A7 为星途热熔胶特有。

## A1 · backend 容器无 mock 包（共享）
backend 镜像未含 `mock` 包、无 volume 挂载。`seed_starhma_mock_connectors.py` 与 agent 运行时 `import mock.core.registry` 需先注入：

```bash
# 注意：docker cp mock/mock ai_infra_backend:/app/mock 会建嵌套 /app/mock/mock/，错误！
# 正确做法（按文件/目录把内容放进 /app/mock/）：
docker exec ai_infra_backend rm -rf /app/mock/mock
docker cp mock/mock/core/registry.py ai_infra_backend:/app/mock/core/registry.py
docker cp mock/mock/systems/frm ai_infra_backend:/app/mock/systems/frm
docker cp mock/mock/systems/pcm ai_infra_backend:/app/mock/systems/pcm
docker cp mock/mock/systems/qas ai_infra_backend:/app/mock/systems/qas
docker cp mock/mock/systems/erp/data.py ai_infra_backend:/app/mock/systems/erp/data.py
docker cp mock/mock/systems/mes/data.py ai_infra_backend:/app/mock/systems/mes/data.py
docker cp mock/mock/systems/crm/data.py ai_infra_backend:/app/mock/systems/crm/data.py
```

重建 backend 后必做（含 frm/pcm/qas + erp/mes/crm 改动）。根因修复：docker-compose 加 volume 挂载 mock 包。

## A2 · mock OpenAPI 快照（共享）
mock 重建后需重生成 `mock/openapi/{frm,pcm,qas}.json`（host py3.6 不支持 future annotations）：

```bash
docker exec ai_infra_mock python -m mock openapi
docker cp ai_infra_mock:/app/openapi/frm.json mock/openapi/frm.json
docker cp ai_infra_mock:/app/openapi/pcm.json mock/openapi/pcm.json
docker cp ai_infra_mock:/app/openapi/qas.json mock/openapi/qas.json
```

或 host `curl :8010/<sys>/openapi.json` 落盘。mock_connectors seed 优先打活网关 `MOCK_BASE_URL`，不可达才回退快照。

## A3 · provider 占位无 embedding/chat 能力（星途热熔胶特有，关键）
4 个占位 provider（Anthropic/OpenAI/DeepSeek/智谱 AI，api_key=PRESET-REPLACE-ME）**无 embedding/chat 能力**，RAG embedding 与 agent 运行都依赖真 key。从 agileac org 复制 `aliyun-embedding-openai`（text-embedding-v4）+ `aliyun-all-openai`（glm-5.2/deepseek-v4-pro/qwen3.7-plus）含加密 key：

```sql
INSERT INTO llm_providers (id, organization_id, name, provider_type, base_url, api_key_encrypted,
  api_key_version, is_active, priority, weight, timeout_seconds, max_retries, supported_models,
  health_status, config, created_at, updated_at)
SELECT gen_random_uuid(), (SELECT id FROM organizations WHERE slug='starhma' AND deleted_at IS NULL),
  p.name, p.provider_type, p.base_url, p.api_key_encrypted, p.api_key_version, true, p.priority, p.weight,
  p.timeout_seconds, p.max_retries, p.supported_models, 'unknown', p.config, now(), now()
FROM llm_providers p
WHERE p.organization_id=(SELECT id FROM organizations WHERE slug='agileac' AND deleted_at IS NULL)
  AND p.name IN ('aliyun-embedding-openai','aliyun-all-openai') AND p.deleted_at IS NULL;
-- GLM/DeepSeek 路由指向 aliyun-all-openai
UPDATE routing_policies SET provider_ids = jsonb_build_array(
  (SELECT id::text FROM llm_providers WHERE organization_id=(SELECT id FROM organizations WHERE slug='starhma')
   AND name='aliyun-all-openai' AND deleted_at IS NULL))
WHERE organization_id=(SELECT id FROM organizations WHERE slug='starhma')
  AND model_pattern IN ('glm-*','deepseek-*') AND deleted_at IS NULL;
```

**注意**：`llm_providers.id` 列无默认值，INSERT 必须显式 `gen_random_uuid()`，否则报 not-null。RAG seed 跑前必须先复制 embedding key，否则全部文档入库 failed。

## A4 · RAG 入库非幂等（共享）
RAG seed 按 (collection, source) 去重跳过已成功。但**前次入库残留 status=failed 的文档**按 source 去重会再次跳过（不会重试）。重跑前须清理：

```sql
DELETE FROM rag_documents WHERE collection_id IN (
  SELECT id FROM rag_collections WHERE organization_id=
    (SELECT id FROM organizations WHERE slug='starhma'));
```

或先删 collection 再重跑。本 demo 首次入库依赖 agileac 真 embedding key 通畅后 9 collection 6-10 文档 0 失败。

## A5 · agent_run_events.updated_at 列（共享，已修）
`agent_run_events` 表缺 `updated_at` 列致每轮 run 结束 bulk-persist 事件 `UndefinedColumnError`。已 `ALTER TABLE agent_run_events ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now() NOT NULL`（agileac/starclothing 同受益，DB 改动不入 repo）。

## A6 · generate_docx 需 workspace_id（共享）
curl 跑终端任务时若 agent 调 `generate_docx`，TaskConfig 需带 `workspace_id`，否则生成 docx 失败。终端任务界面创建会自带 workspace；纯 curl 复现须显式传。

## A7 · 跨码空间 no-guessing 标识符（星途热熔胶特有，关键）
星途热熔胶跨码空间映射规则（详见各域 identifiers.md + 本体 Cross）：

| from | to | 关联键 | 说明 |
|---|---|---|---|
| 原料组分 `ING-RES-001`(FRM) | 物料 `M-RES-001`(ERP) | material_code | **prefix 转换 ING-RES-→M-RES-**，勿直传 |
| 标准配方 `FORM-STD-001`(FRM) | 成品胶 `M-FG-001`(ERP) | product_code | 配方→成品胶 |
| 定制配方 `FORM-CUS-001`(FRM) | 批次 `BAT-2026-0703`(MES) | formula_no | 定制配方转产→批次 |
| 设备 `EQ-`(PCM) | 产线 `LINE-AUTO-02`(MES) | line | 设备→产线 |
| 工艺参数 `PP-REACT-002`(PCM) | 工单 `WO`(MES) | work_order_no | 排产建议→工单 |
| 批次 `BAT-2026-0702`(MES) | 检测报告 `QR-FG-`(QAS) | batch_no | 批次→成品质检 |
| 批次 `BAT-2026-0702`(MES) | 不良品 `NG-`(QAS) | batch_no | 批次→不良品 |
| 客诉 `CC-2026-001`(QAS) | 客户 `CLI-001`(CRM) | customer_code | 客诉→客户 |
| 发票 `INV202607001`(CRM) | 凭证 `BV-HMA-2026-0701`(ERP) | invoice_no | 回款发票↔凭证对账 |
| 合同 `CT-HMA-001`(CRM) | 生产成本 `PC-HMA-`(ERP) | work_order_no | 合同→生产成本 |
| 批次 `BAT-`(MES) | 生产成本 `PC-HMA-`(ERP) | heat_no | 批次→生产成本 |

path 参数端点必须用真实码（如 `FORM-CUS-002`、`BAT-2026-0702`、`EQ-MTR-02`、`CC-2026-001`），勿用 `{code}` 占位，否则 404。**跨码空间 ING-RES-↔M-RES- prefix 转换是星途热熔胶最易踩坑点**，FRM→ERP 调 `listMaterials` 必须先做 prefix 转换。

## A8 · path 参用真实码（共享）
GET path 参数端点（`getFormula/{formula_no}`、`getExperiment/{experiment_no}`、`getEquipment/{equipment_code}`、`getCustomerComplaint/{complaint_no}`、`getWorkOrder/{work_order_no}` 等）调时传真实码，勿传 `{code}` / `{formula_no}` 占位。

## A9 · memory/extract 长中文保守（共享）
`memory.extract` 对长中文文本提取可能返 0 facts，非致命（LLM 行为，非架构缺陷）。P0 验收不以此为准。

## A10 · admin 登录用 admins 表（共享）
org_admin 行不在 seed_org 脚本里，登录管理端用 `admins` 表（非 `users`）。手插：

```sql
INSERT INTO admins (id, organization_id, username, display_name, password_hash, role, is_active, created_at, updated_at)
SELECT gen_random_uuid(), (SELECT id FROM organizations WHERE slug='starhma'),
  'admin', '组织管理员',
  (SELECT password_hash FROM admins WHERE username='admin' LIMIT 1),  -- 复用 agileac 的 password_hash
  'admin', true, now(), now()
ON CONFLICT DO NOTHING;
```

密码同 agileac（`12345678`）。仅管理端截图需用，P0 终端任务用 users 表的 rd-formulator/sales-rep/mfg-planner 登录即可。
