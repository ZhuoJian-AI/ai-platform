# PostgreSQL 迁移回归与发布快照基建

## 任务与边界

- 分支：`test/schema-migration-infra-20260909`
- 基线：`b672b793e60e4fff57cc3afb833394484abf8926`
- 只增加数据库测试和只读发布审计脚本。
- 未创建 `0075` contract 迁移，未删除表，未修改业务实现、前端、线上数据库或部署。

## 新增能力

- `tests/test_migration_0074_user_role_compat.py`
  - 为每次测试创建唯一的临时 PostgreSQL 数据库，结束时终止残留连接并删除该数据库。
  - 先迁移到 `0073_native_assistant_default`，真实复现省略 `users.role` 时的 asyncpg `23502`。
  - 再迁移到 `0074_user_role_compat`，验证列默认值、Alembic 版本和真实管理员 API 员工闭环。
  - 覆盖创建、更新、重复用户名 409、软删、同名重建，并直接断言 asyncpg `23505` 与
    `uq_user_org_username`，不使用伪造驱动异常。
  - 数据库名必须包含 `test`；默认只允许本机。远端测试必须显式设置
    `MIGRATION_TEST_ALLOW_REMOTE=1`。
- `scripts/capture_protected_database_snapshot.py`
  - 在 `repeatable read + read only` 事务中生成受保护表的精确行数、主键 SHA-256、内容
    SHA-256 和完整 Schema 指纹。
  - 指纹覆盖关系、列、约束、索引、触发器、视图/物化视图、函数、扩展和 RLS 策略。
  - 报告不包含原始行、连接串、密码、令牌或文件正文；`bytea/vector` 大列被排除并显式列出。
- `scripts/report_retired_schema_preflight.py`
  - 报告待退役表的存在性、精确行数、列、外键、视图依赖及必须归档的非空表。
  - fail-closed 检查 DSH 活跃运行、Team 引用、无有效 UserRole 员工、旧 role 值、Agent/Run
    旧字段、无效 SkillFolder、旧应用工具绑定和 Platform Extension 对象引用。
  - `tool_call_logs` 作为条件退役对象单列，要求 Skill 监控先迁移到 `skill_executions`。
  - 不再使用时间等待门禁；非空退役数据没有归档时，`destructiveContractReady=false`。

## 验证

使用 Python `3.12.14`：

```text
python -m ruff check --config llm_router/backend/pyproject.toml \
  llm_router/backend/tests/test_migration_0074_user_role_compat.py \
  llm_router/backend/tests/test_database_release_scripts.py \
  scripts/capture_protected_database_snapshot.py \
  scripts/report_retired_schema_preflight.py
```

结果：通过。

```text
python -m pytest tests/test_database_release_scripts.py tests/test_user_integrity_errors.py -q
```

结果：`9 passed`。

```text
python -m pytest tests/test_migration_0074_user_role_compat.py -q -rs
```

结果：`1 skipped`。当前主机在 `127.0.0.1:5432/5433/5434/15432` 均无 PostgreSQL，且没有
可用 Docker/本地 PostgreSQL 进程。测试只因缺少真实实例跳过，不会切换 SQLite 或伪造成功。

已额外通过 `compileall`、脚本 `--help`、缺少 URL 返回码 2、未授权远端 URL 返回码 2、
`alembic heads` 与 `0073:0074` history 检查。

## 合并前必须补跑

在隔离的 pgvector PostgreSQL（测试用户需有 `CREATE DATABASE`）中执行：

```powershell
$env:MIGRATION_TEST_DATABASE_URL = 'postgresql+asyncpg://<test-user>:<password>@127.0.0.1:5434/ai_infra_test'
$env:REQUIRE_REAL_POSTGRES_MIGRATION_TESTS = '1'
python -m pytest tests/test_migration_0074_user_role_compat.py -q -rs
```

生成部署证据时通过环境变量提供数据库 URL，不把凭据写入命令历史、仓库或报告：

```text
python scripts/capture_protected_database_snapshot.py --allow-remote-read-only \
  --fail-on-missing --output <immutable-pre-release-path>.json
python scripts/report_retired_schema_preflight.py --allow-remote-read-only \
  --output <immutable-preflight-path>.json
```

报告默认拒绝覆盖已有文件。还必须单独完成 `pg_dump -Fc`、`pg_restore --list`、隔离恢复演练、
OSS 引用存在性抽样和不可变镜像 digest 记录；这些外部证据不由只读数据库脚本伪造。

## 风险与决定

- contract 迁移成功后的可接受回滚仍是“停止全部写入者 → 恢复迁移前数据库快照 → 恢复匹配的
  旧镜像 digest”，不能只降级镜像，也不能依赖历史 Alembic downgrade 恢复已删除数据。
- 两个审计脚本只读数据库，但可以在显式指定路径写 JSON 报告；不修改数据库或对象存储。
- 后续 0075 编写和表删除必须等待真实 PostgreSQL 回归、受保护数据快照、退役数据归档和代码
  引用审计全部通过。
