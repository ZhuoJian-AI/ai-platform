# Active tasks

## SUBSYSTEM-AI-20260909 — 子系统受控专业 AI 能力与嵌入式验收 (@codex-subsystem-ai)

- 在原生 Assistant Core 上提供组织、员工、应用、页面和 Action 绑定的专业 AI 能力，不恢复 DSH 或已退役扩展链。
- 支持 OCR、语音转写、图像比较/分类、结构化抽取和业务预测的异步运行、可信结果、人工确认与撤权。
- 完成后端、前端和真实员工嵌入式验收，并按 Registry-first 发布 SaaS；不修改任何业务子系统服务器。

## PLATFORM-SIMPLIFY-20260908 — 原生 Assistant Core 与冗余链路清理 (@codex-platform-simplification)

- 从 DSH 迁移个人助手、业务助手和自定义智能体，保留 Task、AgentRunEvent、Artifact 与工作空间能力。
- 兼容退役 Platform Extensions、Connector、Data Interface、Ontology、Judge、MCP/OAuth、Team 和 WebOffice 在线编辑。
- 完成 expand/migrate/contract 数据库迁移、9 服务 Registry-first 发布及真实账号端到端验收。
- 不修改 aifabei-subsystem-builder、业务子系统、生产站点和手工 aipcopy01 栈。
- 当前：原生引擎和 9 服务主栈已发布，并完成管理员、员工、个人助手、业务助手、Excel Artifact 与自定义智能体真实验收。发布后未产生 DSH 运行；Connector 物理删除仍受“连续七天无调用”门禁约束，最早于 `2026-09-12 18:28:10 UTC`（北京时间 `2026-09-13 02:28:10`）复核。
