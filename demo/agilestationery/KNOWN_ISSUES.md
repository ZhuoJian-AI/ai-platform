# 敏睿文具 Demo 已知问题（KNOWN_ISSUES）

> 继承 backend 共享坑（与 agilesteel/agileac 同源）+ 文具贸易特有注意点。维护时按编号对照。

## A1 backend 无 mock 包（共享，根治前每次重建后必做）
backend 镜像不含 `mock` 包，`seed_agilestationery_mock_connectors.py` 与 `import mock.core.registry` 依赖。
临时修复：`docker cp mock/mock ai_infra_backend:/app/mock`（注意：会覆盖，须用最新含 PIM/CST/CHN + agilestationery tenant 的包）。
**根治**：docker-compose.yml backend 服务加 `volumes: - ../mock/mock:/app/mock:ro`。

## A2 mock openapi 快照（fallback）
`_fetch_spec` 优先 live 网关 `MOCK_BASE_URL`，回退 `mock/openapi/{key}.json`。PIM/CST/CHN 快照已 `make mock-export`
（在 mock 容器内 `python -m mock openapi` 后 `docker cp` 到主机 `mock/openapi/`）。重建 mock 后须重导出。

## A3 provider 同步自 agileac（占位 key 无 embedding/chat 能力）
seed_agilestationery_org.py 创建 4 占位 provider（PRESET-REPLACE-ME）。真实 embedding/chat key 由 README §3 SQL
从 agileac 复制（aliyun-embedding-openai / aliyun-all-openai），并把 glm-*/deepseek-* 路由指向 aliyun-all-openai。
**RAG embedding 依赖此**——未同步则 RAG chunk embedding=NULL，retriever 落 keyword_fallback。每次 org seed 重跑后须重做。

## A4 RAG failed doc 非幂等（共享）
重跑 seed_agilestationery_rag.py 会跳过 source 已存在的 doc，即使上次 ingest `status=failed`。
修复：清 failed doc+chunk 后重跑：
```sql
DELETE FROM rag_chunks WHERE document_id IN (SELECT id FROM rag_documents WHERE status='failed' AND organization_id=(SELECT id FROM organizations WHERE slug='agilestationery'));
DELETE FROM rag_documents WHERE status='failed' AND organization_id=(SELECT id FROM organizations WHERE slug='agilestationery');
```

## A5 agent_run_events.updated_at（共享，已修）
TimestampMixin 期望 updated_at 列。agilesteel 阶段已 `ALTER TABLE agent_run_events ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now() NOT NULL;`。agilestationery 复用同一 backend，无需再修。

## A6 generate_docx 需 workspace_id（共享）
内置 `generate_docx` 工具仅在 TaskConfig 带 `workspace_id` 时出现在 LLM 工具列表。前端从用户个人 workspace 自动填充；
curl 复现须显式传，否则无 docx 附件（不影响 text+tool_call+RAG 流）。

## A7 no-guessing identifiers（文具特有，关键）
喂 LLM 的 prompt 不含场景代号（SAL-01 等），用具体示例码。跨码空间映射（identifiers.md 显式消歧）：
- 产品 `SKU-ZB-`(PIM) ↔ 物料 `M-ZB-`(ERP)：prefix 转换，按 product_code/material_code 关联，**勿直传**。
- 报关单 `CD-`(CST) ↔ 采购单 `PO-`(ERP)：CD.po_no 引用 PO，按 po_no 关联，**勿直传 CD 给 ERP**。
- 发票 `INV-`(CST) ↔ 凭证 `BV-AS-`(ERP)：按 invoice_no/voucher_no 关联，**勿直传 INV 给 ERP**。
- 假货样本 `CTF-`(PIM) ↔ 取证 `EV-`(CHN) ↔ 违规商家 `MR-`(CHN)：CTF.evidence_code→EV→MR，按 evidence_code/merchant_code 关联，**勿直传 CTF 给 CHN**。
- 经销商 `DLR-`(CRM) ↔ ERP 客户：同码直查。
- 招聘需求 `ASRC`(HRM).position ↔ 岗位 `P-`(HRM)：按 position_code 关联；岗位 `P-` 与产品 `SKU-ZB-` 不同码空间（PIM 用 SKU-ZB- 不用 P-，无歧义）。
- 销售订单 `SO-`(CRM) ↔ ERP 出库：同 so_no 直查。

## A8 path-param 占位符（共享）
调 GET 端点用真实编码（如 `getProduct?...` / path `CD202607001`），勿用 `{product_code}` 占位符，否则 404。各 terminal_task.md §5 提醒。

## A9 memory/extract 对中文保守（共享）
extract 节点对中文长文本偏保守，返回 0 facts 非致命（trace 仍计 memory.load）。

## A10 admin 登录用 admins 表（共享）
管理端 `/auth/login` 用 `admins` 表非 `users` 表。agilestationery 复用 agileac/agilesteel 的 org_admin 行（admin / 12345678，org_admin 角色，自动锁 agilestationery）。
