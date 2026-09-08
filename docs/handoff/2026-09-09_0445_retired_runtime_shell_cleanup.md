# 退役运行时壳与孤儿配置清理

- Owner: `@codex-schema-test-audit`
- Task: `RETIRED-RUNTIME-SHELL-CLEANUP-20260909`
- Base commit: `5bc98bf66421`
- Branch: `refactor/remove-retired-runtime-shells-20260909`

## Changed behavior

- 删除未被任何运行时模块导入、也未注册到 OpenAPI 的
  `app/api/retirement.py`。退役产品旧路由保持真实 `404`，不再保留孤立的
  `410 Gone` 响应构造器。
- 删除已经退出的旧 GitHub/Coolify 模块发布控制面文档及 `.env.example` 中
  14 行无配置模型、无运行消费者的环境变量；保留 ECS Publisher 使用的
  `MODULE_SAAS_ORIGIN`。
- 删除本地 Compose 中后端从未读取的 MCP OAuth discovery 环境变量。
- Nginx 不再把已经不存在的 `/mcp` 和 `/.well-known` 路径代理到 Backend；
  `/api`、`/v1`、健康检查和前端路由保持不变。
- 清理 Assistant 事件测试桩及员工登录代码中遗留的 Ontology、Judge、MCP/OAuth
  注释，不改变 Task、Artifact、工作空间、RAG、Skill 或权限行为。
- README 与 Coolify 文档改为当前真实状态：退役路由未注册并返回 404。

## Evidence

- 全仓查找确认 `retired_response`、`retired_api_dependency` 和
  `app.api.retirement` 除定义文件外没有引用。
- 应用 OpenAPI 共 234 条保留路径，Connector、Data Interface、Ontology、Judge、
  OAuth/MCP、Platform Extension、旧 Module Publisher、Team、Office Edit 和
  ScopeManager 路径命中数为 0。
- 已删除的 GitHub/Coolify/OAuth 环境变量在迁移和审计历史之外没有读取方。
- `MODULE_SAAS_ORIGIN` 仍由 ECS Publisher API 使用，因此明确保留。

## Verification

- changed-file Ruff：`All checks passed!`
- `python -m compileall -q llm_router/backend/app llm_router/backend/tests/test_tool_connector_api.py`：通过。
- 直接执行 `test_all_retired_product_routes_are_absent_from_openapi`：通过。
- `node scripts/test-retired-frontend.mjs`：`retired frontend cleanup tests passed`。
- `docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.local.yml config --quiet`：通过；仅提示本地未设置测试用 Secret。
- `git diff --check`：通过。

## Boundaries and remaining work

- 未修改数据库迁移、Schema、生产配置、Skill、业务子系统或部署状态。
- 未删除工作空间、文件/Artifact、知识库/RAG、个人/业务/自定义助手、Skill Runner、
  Manifest Action、Bridge、SSO、Event、Runtime、ECS Publisher、模型、额度或审计。
- `TODO.md` 和历史审计/迁移仍会提及退役产品：前者混有仍保留的自定义智能体规划，
  后两者属于不可变历史证据，本次不做整文件删除。
- 只读 WebOffice 预览仍是保留能力，所以相关配置、Storage Gateway token 接口和
  preview 服务没有删除。

## Risk and rollback

- 运行时变化仅缩小 Nginx 的退役路径代理范围。若外部仍错误依赖 `/mcp` 或
  `/.well-known`，其响应会从 Backend 404 变为前端 404，均不恢复已退役能力。
- 回滚可直接 revert 本提交；无数据库或用户数据恢复动作。
