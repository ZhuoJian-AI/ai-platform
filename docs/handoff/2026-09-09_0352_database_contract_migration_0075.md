# 0075 退役 Schema contract 迁移

- Owner: `@codex-contract-migration-0075`
- Task: `CONTRACT-MIGRATION-0075-20260909`
- Base: `7a9228f`
- Scope: 仅新增 0075 Alembic 迁移并扩展真实 PostgreSQL 迁移测试；未修改运行时、前端、Skill、部署配置或旧迁移。

## 行为变更

- 新增不可逆迁移 `0075_retired_schema_contract`，前置 revision 为 `0074_user_role_compat`。
- 迁移在同一事务中设置 `lock_timeout=5s`、`statement_timeout=120s`，执行前验证所有预期旧表/字段、保留表外键和视图依赖。
- 活跃 DSH 运行、活跃 Team API Key/模型供应商/工作空间/DLP、Team 用户归属、仍在授权链路中的 Team scope、无法映射的 Team 资源、冲突的审计或配额历史、有效 Agent workflow/Judge 配置都会阻止迁移。
- Team API Key、模型供应商和 DLP 的停用历史映射到原 Team 所属部门；已退役空 Team 工作空间保留为 `legacy_team` 历史范围，不扩大为部门权限。
- `audit_logs.team_id` 写入既有 `metadata.legacy_team_id` 后删除；配额 Team scope 改为非授权历史标签 `legacy_team`，删除冗余 `team_id`，保留所有 `ai_quota_events` 事实和 append-only 触发器。
- 保留全部 `agent_runs` 和 `agent_run_events` 行；删除运行时已退出的 Agent/AgentRun 旧字段，并把单一 RAG 绑定并入 `rag_collection_ids`。
- 重建不含 Team 维度的 `ai_quota_monthly_rollups`，使用 `WITH NO DATA`，避免迁移期间长时间刷新。
- 删除 27 个 preflight 批准的退役表；迁移未使用隐式依赖级联删除。
- downgrade 明确拒绝恢复，避免伪造已删除的历史数据。

## 删除对象

字段：

- `users.role`, `users.team_id`
- `api_keys.team_id`, `llm_providers.team_id`
- `tasks.team_id`, `multimodal_jobs.team_id`
- `audit_logs.team_id`, `ai_quota_events.team_id`
- `agents.workflow`, `agents.judge_config`, `agents.judge_template_id`, `agents.rag_collection_id`
- `agent_runs.assistant_engine`, `agent_runs.messages`, `agent_runs.steps`, `agent_runs.judge_score`

表：

- `agent_messages`, `budget_usage`, `data_interfaces`, `data_systems`
- `enterprise_application_tool_bindings`, `judge_templates`
- `module_deployment_profiles`, `module_deployments`
- `oauth_authorization_codes`, `oauth_clients`, `oauth_refresh_tokens`
- `office_edit_rooms`, `office_save_events`
- `ontologies`, `ontology_files`, `ontology_folders`
- `platform_extension_catalog_entries`, `platform_extension_release_events`, `platform_extension_releases`, `platform_extension_sources`
- `scope_manager_assignments`, `skills`, `teams`
- `tool_call_logs`, `tool_connectors`, `tool_endpoints`
- `user_department_memberships`

迁移、preflight 的无条件表加条件表、测试三份清单已用 AST 做集合比对：27 个表完全一致，无遗漏或多余项。

## 验证

隔离 PostgreSQL 18.3，端口 15433：

```text
python -m pytest tests/test_migration_0074_user_role_compat.py -q -rs
3 passed in 16.69s

python -m pytest tests/test_database_release_scripts.py -q
6 passed in 0.04s

python -m ruff check alembic/versions/0075_retired_schema_contract.py tests/test_migration_0074_user_role_compat.py
All checks passed!

python -m compileall -q alembic/versions/0075_retired_schema_contract.py tests/test_migration_0074_user_role_compat.py
通过
```

真实 PostgreSQL 测试覆盖：

- 空数据的 `0073 → 0074 → 0075`。
- 带 Team 凭证、供应商、工作空间、Audit、Quota、AgentRun 和 AgentRunEvent 的代表性数据。
- 活跃 DSH 运行阻断并保持 revision 0074。
- Team 历史映射、Audit/Quota 保留、append-only 触发器、AgentRunEvent 保留和退役对象完全消失。
- downgrade 拒绝且 revision 保持 0075。

## 发布风险与后续要求

- 这是物理删除数据的不可逆 contract 迁移。部署前必须完成全量 `pg_dump`、恢复演练并记录对应旧镜像；应用镜像和数据库归档必须成对回切。
- 迁移会删除退役表历史以及 AgentRun 的冗余 JSON 字段；这些内容只能从部署前归档恢复。保留的 TaskMessage、AgentRunEvent、Quota 和 Audit 不受删除。
- `legacy_team` 只表示历史用量/已退役工作空间，不得重新进入授权判断。运行时汇总应把非 `organization/department/api_key` 的范围归入“退役范围历史用量”。
- 配额物化视图迁移后为空；部署完成且写入恢复后，应由现有刷新流程或人工命令刷新一次。
- 如果线上出现迁移未识别的保留表外键、视图依赖或活跃旧资源，迁移会主动失败；应先清理依赖，禁止绕过 precondition。
