# 原生 Assistant Core 与 9 服务收口

## 范围

- 仅发布 `ai-platform.staging.zhuojianai.com` 的 Coolify 主栈。
- 不修改 `aifabei-subsystem-builder`、任何业务子系统、旧业务服务器、`academy.zhuojianai.com` 或手工 `aipcopy01` 栈。
- 工作空间、文件版本、OSS、Artifact、Task、TaskMessage、AgentRunEvent、RAG 与长期记忆均为受保护数据。

## 本次变更

- 三种助手统一由原生 Assistant Core 执行，移除 DSH 客户端、内部桥接 API、运行时服务、外部扩展市场、扩展构建器和 SDK。
- 保留平台固定工具、工作空间文件执行器、RAG、Web、多模态、记忆、用户上传 Skill，以及实时授权的 Manifest Action。
- Coolify 编排从 11 个服务收口为 9 个服务：PostgreSQL、Redis、Backend、Frontend、Skill Runner、Workspace Parser、Workspace Preview、Storage Lifecycle、Multimodal Worker。
- 工具监控不再读取 Connector/Data Interface 库存；新增 Manifest Action 调用、错误率和延迟明细，并继续展示用户 Skill。
- 新建 `AgentRun` 的数据库默认执行引擎由 `dsh` 改为 `native`；历史行继续允许保留原值，不做数据重写。
- 帮助文档删除已下线的 DSH、Connector、Data Interface、Ontology、Judge 和测试广场说明。

## 发布前验证

- Backend 完整回归（清理监控前）：`522 passed, 15 skipped`。
- Assistant Core 与监控真实 PostgreSQL 集成回归：`52 passed`。
- Frontend 生产构建：通过。
- 空数据库 Alembic：`0001 -> 0073 -> 0072 -> 0073` 通过，`0073` 仅修改 `agent_runs.assistant_engine` 的服务端默认值。
- Ruff、compileall、`git diff --check`：通过。
- Coolify Compose 展开后服务数：9。

## 数据与回切

- 发布前数据库备份：`/data/backups/ai-platform/20260908T175200+0800_pre_platform_simplification_0070.dump`。
- 备份 SHA-256：`c5b43190adbaee070a466b62ce4157de5239f43ae7004a9b066c638933ccb285`，已通过 `pg_restore --list` 验证。
- 数据库迁移为向前兼容，不回滚数据库。异常时只回切 Backend/Frontend 的不可变镜像 digest。
- 旧 DSH/Extension 镜像、旧 Compose 与废弃密钥保留七天；用户 Skill Runner 仍显式屏蔽这些密钥。

## 延后门禁

- 线上仍有 5 条历史 `enterprise_application_tool_bindings`，最后一次旧 Connector 调用为 `2026-09-05T18:28:10Z`。
- Connector、Tool Endpoint 和应用工具绑定的物理删除必须满足连续七天无调用，因此本次仅退出产品入口和新运行注入，不删除历史表或记录。
- Platform Extension 历史目录数据继续作为存储生命周期引用保留，等兼容期和对象引用审计结束后再做 contract 迁移。

## 发布结果

- Source commit/PR：待发布后补充。
- Backend/Frontend 新旧 digest：待发布后补充。
- Coolify deployment UUID 与健康检查：待发布后补充。
- 管理员、员工、个人助手、业务助手、Artifact 与自定义智能体浏览器验收：待发布后补充。
