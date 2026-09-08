# Team 运行时退役清理

- Owner: `@codex-schema-test-audit`
- Task: `TEAM-RUNTIME-RETIRE-20260909`
- Base commit: `9ebcd86`
- Branch: `refactor/retire-team-runtime-20260909`

## Changed behavior

- 删除 `Team` 与无运行消费者的 `BudgetUsage` ORM；经主任务授权同步移除
  `models/__init__.py` 中对应 import/export。
- 从用户、API Key、模型供应商、审计、额度事件、Agent、RAG、Memory、
  Workspace、DLP、路由、模型网关、多模态和 Skill scope 中移除
  `team_id` 运行时兼容。
- 组织、部门、员工、多角色并集和工作空间权限语义不变。
- 历史未知额度 scope 聚合为只读的“退役范围历史用量”；不访问退役资源表，
  不改写 append-only `ai_quota_events`，也不让历史范围参与当前限额层级。
- 示例数据和 ClawHub 导入脚本只接受组织、部门或用户范围；原团队级示例 Key
  改为对应部门级 Key。
- 删除 Team API 兼容断言，保留部门成员阻止删除、未知工作空间范围 fail-closed
  等核心测试。

## Verification

- `python -m compileall -q llm_router/backend/app llm_router/backend/scripts llm_router/backend/tests`
  - 通过。
- 共享项目虚拟环境的 Ruff 对全部本次变更 Python 文件执行 `ruff check`
  - 通过。
- `pytest -q tests/test_quota_scope_propagation.py tests/test_scope_model_visibility.py tests/test_assistant_policy.py -k 'not vision_fallback'`
  - `33 passed, 1 deselected`。
- `pytest -q tests/test_budget_scope_report.py`
  - `2 passed`。
- 独立本地 PostgreSQL 测试库执行部门 CRUD、工作空间权限及员工 Skill scope：
  - `9 passed`。
- `import app.main` 及 ORM metadata 断言：
  - `teams`、`budget_usage` 均不再注册，验证通过。
- `git diff --check`
  - 通过。

## Integration work still required

- 按任务边界未修改 `app/agents/graph/nodes.py`。该文件仍有 14 个
  `team_id=None` 调用或 ORM 构造；合并 nodes 拆分提交后必须统一删除，再跑全测。
- 按冲突边界未修改 `api/router.py` 和 `enterprise_application*`。其中 router 有一处
  退役注释，两个 enterprise application 测试文件仍有 4 处 Team 兼容参数，合并时清理。
- 本提交不创建 contract migration。现有数据库仍保留 `teams` 表以及历史可空列；
  后续 0075 必须在运行时提交合并后删除物理表/列。迁移前的共享测试库由于遗留
  `teams.department_id` 外键，`Base.metadata.drop_all()` 不能独立清理，这是预期的
  expand/contract 时序限制。
- 本提交不能与旧镜像单独发布；先合并所有调用方清理，再配套 contract migration。

## Decisions and risks

- 线上历史 quota 中仍存在退役 scope，且账本为 append-only 并有唯一约束；禁止将
  这些行原地改写成部门 scope。报表保留聚合历史用量是唯一安全兼容方式。
- 历史 inactive API Key / Provider / Workspace 不再通过 Team 资源解析；当前运行时
  只识别组织和部门范围。
- 未修改、未连接线上数据库，未创建迁移，未部署。
