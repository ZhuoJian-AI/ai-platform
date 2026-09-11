# 查询完成状态口径修复

- 目标仅当前 AI Platform staging；部署规则 c948cd2，不修改业务子系统、外部 Skill、数据库结构或模型 Schema。
- 发现 runner 将 enterprise_action 的 `ok=true,status=error` 当作实时查询成功；复合导出也没有排除等待输入/执行中状态。传输成功不能替代业务完成。
- 两类工具统一排除 failed/error/pending/retryable_error/needs_input/needs_confirmation/queued/running/cancelled；后续真实成功仍计为完成，不因先前错误整轮拒绝。
- 新增 32 个组合用例（两类工具、八种未完成状态、有无成功纠正）。runner 与 policy 共 72 passed，Ruff passed；使用 D:/Agent_Project/.venv-ai-platform-py312/Scripts/python.exe，未重跑全量测试。
- 这不是专业 AI 失败与辅助查询成功的完整修复。不能把任何一次专业工具失败永久锁死：替代获权工具可能真正完成目标。该边界仍需区分主目标完成证据与辅助查询证据，当前不新增自然语言关键词门禁。
- 尚待：媒体剩余验收、写操作未知结果跨运行恢复、专业任务完成证据、此前员工 401 原因、旧临时输入清理。上一批另存/只读预览/管理员深链已部署通过，不重复验收。

## staging 发布记录

- source SHA：`9ca1c7c42e9c76c490a141c094bb7d097d12ce6f`（PR #102）。
- backend digest：`sha256:94bf832cdaf0fcc72c6703b4fa8da2c0bc9ae70a216e727a0d59a3be07dd1412`；运行容器的镜像引用与 OCI revision 已核对。
- manifest SHA：`29c16ccb17f65ba64bb1d1217cf647bb348b59d1`（PR #103）。
- Coolify deployment：`receipts98a4349062ba4560`，2026-09-11 07:37:37 UTC finished。
- Compose 与真实环境变量预检均 PASS；九项服务 healthy，正式 staging `/health` 返回 200。重建初期曾返回 503，服务就绪后恢复。
- frontend 未修改；没有数据库迁移、文件迁移或业务服务器变更。本批不重复上一批真实管理员/员工文件验收，不能把既有 E2E 写成本批重新执行。
- 回切 backend：`sha256:f93e2db43e3e5e98c8a98853c5df15d4a89420689f1736858f839c71d3d9a463`，不回滚数据库。
- 后续复核发现：`mutation_committed` 仍仅排除 pending/failed/error，需要单独验证其他未完成状态不会被写操作计为成功；尚未修复，不能宣称整个完成判定已收尾。
