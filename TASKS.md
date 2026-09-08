# Active tasks

## STAGING-CORE-E2E-20260909 — 双端核心浏览器回归脚本 (@codex-e2e-matrix-audit)

- 从最新 `origin/main` 提供可复用的 staging 核心回归脚本，使用真实 UI 分别登录管理员与员工端。
- 覆盖中文登录错误、保留导航、管理员—员工权限只读闭环、企业应用 iframe 与业务助手 Artifact。
- 凭据只从运行时环境变量读取；不修改真实授权、不删除真实数据、不提交或部署到 `main`。

## PLATFORM-SLIM-E2E-20260909 — 鉴权回归修复、遗留链路物理清理与双端全量验收 (@codex-platform-slim-e2e)

- 修复升级数据库中 `users.role NOT NULL` 导致的新建员工回归，并精确区分用户名冲突与其他数据库错误。
- 在保留 Assistant Core、工作空间、RAG、用户 Skill、Manifest Action 与 Runtime 的前提下，物理删除已退役兼容链路。
- 以数据库副本演练 contract 迁移与新基线，完成 9 服务 Registry-first 发布。
- 使用真实 Root 管理员和 zhangsan 员工的独立浏览器会话，覆盖所有保留页面、API、CRUD、Action 与权限闭环。
- 不修改 `aifabei-subsystem-builder`、业务子系统或服务器上的其他项目；合并与部署前必须吸收同项目并行任务。

## PLATFORM-SIMPLIFY-20260908 — 原生 Assistant Core 与冗余链路清理 (@codex-platform-simplification)

- 从 DSH 迁移个人助手、业务助手和自定义智能体，保留 Task、AgentRunEvent、Artifact 与工作空间能力。
- 兼容退役 Platform Extensions、Connector、Data Interface、Ontology、Judge、MCP/OAuth、Team 和 WebOffice 在线编辑。
- 完成 expand/migrate/contract 数据库迁移、9 服务 Registry-first 发布及真实账号端到端验收。
- 不修改 aifabei-subsystem-builder、业务子系统、生产站点和手工 aipcopy01 栈。
- 当前：原生引擎和 9 服务主栈已发布，并完成管理员、员工、个人助手、业务助手、Excel Artifact 与自定义智能体真实验收。发布后未产生 DSH 运行；Connector 物理删除仍受“连续七天无调用”门禁约束，最早于 `2026-09-12 18:28:10 UTC`（北京时间 `2026-09-13 02:28:10`）复核。
