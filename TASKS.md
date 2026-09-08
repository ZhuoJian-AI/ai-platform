# Active tasks

## PLATFORM-SIMPLIFY-20260908 — 原生 Assistant Core 与冗余链路清理 (@codex-platform-simplification)

- 从 DSH 迁移个人助手、业务助手和自定义智能体，保留 Task、AgentRunEvent、Artifact 与工作空间能力。
- 兼容退役 Platform Extensions、Connector、Data Interface、Ontology、Judge、MCP/OAuth、Team 和 WebOffice 在线编辑。
- 完成 expand/migrate/contract 数据库迁移、9 服务 Registry-first 发布及真实账号端到端验收。
- 不修改 aifabei-subsystem-builder、业务子系统、生产站点和手工 aipcopy01 栈。

## NATIVE-DEDUPE-20260908 — 原生工具副作用去重热修 (@codex-native-dedupe)

- 修复同一模型回合返回重复同名同参副作用工具时重复创建 Artifact 的问题。
- 复用首次成功结果，并为重复调用记录可审计的策略事件。
- 增加原生执行循环回归测试并重新完成李四业务导出端到端验收。
