# 单一 0075 基线合并审查与验证

## 范围

- 基线：`origin/main` 的 `fb800137f9a68b315b90776ab9483dc99f12b1fd`。
- 被审查提交：`1963c9b1f75bacd158fa113b22839f93fcb93209`。
- 只在独立工作树合并、测试本地 PostgreSQL；未连接线上数据库、未部署。

## 冲突处理

- `alembic/env.py` 是唯一内容冲突。保留 `bfdbb8a` 已进入 `main` 的 Schema 管理分类实现，
  包括精确的索引、唯一约束和管理员外键类型 allowlist，以及 Ruff 所需的
  `del context_, metadata_column`。被审查提交在该文件没有必须保留的新行为。
- Windows `core.autocrlf` 会把静态 SQL 的 LF 转为 CRLF，使迁移内置 SHA-256 校验立即失败。
  已在 `.gitattributes` 对 `0075_schema_baseline.sql` 固定 `eol=lf`。新的干净工作树中 SQL
  SHA-256 为 `e2cc9449c01eb17fb64987d5202498365962578889a73cfc195f7512e06d92a3`。

## 真实 PostgreSQL 验证

使用本机隔离 PostgreSQL 18、pgvector 0.8.2、Python 3.12.14。

```text
python -m pytest tests/test_migration_0075_baseline.py -q -rs
```

结果：`2 passed in 8.16s`。验证空库只执行单一 0075 基线、Schema 指纹为
`4017e5852a530337ea57e100e80f015f2bbb9f4a0cbf73a58c1be15476a03b95`，再次 upgrade
保持关系 OID/relfilenode 不变，`alembic check` 为零漂移。

另用最新 `origin/main` 的完整 0001→0075 链创建独立数据库，再切换为单一基线源码执行：

```text
python -m alembic upgrade head
python -m alembic check
```

结果：没有运行 migration；版本仍为 `0075_retired_schema_contract`，测试组织记录未变化，
关系 OID/relfilenode 摘要前后均为 `792b805dd7c9113dffeec790c2e24f9b`，Schema 指纹仍为
`4017e5852a530337ea57e100e80f015f2bbb9f4a0cbf73a58c1be15476a03b95`，并输出
`No new upgrade operations detected.`。

```text
ruff check --config pyproject.toml alembic/env.py \
  alembic/versions/0075_retired_schema_contract.py tests/test_migration_0075_baseline.py
python -m compileall -q alembic/env.py \
  alembic/versions/0075_retired_schema_contract.py tests/test_migration_0075_baseline.py scripts
python -m alembic heads
python -m alembic history --verbose
```

结果：Ruff、compileall 通过；Alembic 只有一个 root/head：`0075_retired_schema_contract`。

## 发布门禁与风险

- 这是同 revision ID 的历史重写。只有数据库已经由旧源码完整升级到 0075 时才是 no-op。
  任一仍在 0001–0074 的数据库在合并后都无法定位旧 revision，不能直接升级。
- 必须先部署包含完整迁移链的 Stage 1 镜像，并逐库确认 `alembic_version` 精确为 0075；
  然后完成受保护数据快照、`pg_dump -Fc`、`pg_restore --list` 和隔离恢复演练，才可发布单一基线。
- 新安装要求数据库镜像能提供 pgvector 0.8.2。当前固定数据库镜像和本地验证环境满足；更换
  PostgreSQL/pgvector 镜像前必须重跑真实空库测试。
- 合并单一基线后，正常回退旧应用镜像可读取等价 Schema，但不能依赖 Alembic downgrade。
  数据库异常的可接受恢复是停止写入者，恢复发布前数据库快照，并恢复匹配的旧镜像 digest。
- 旧迁移仍在 Git 历史中；不得在未确认所有数据库均为 0075 时清理相关镜像或快照。
