# 业务写入证据核实候选

- 任务：PLATFORM-BUSINESS-RECOVERY-20260912；分支 feat/business-recovery-20260912；基线 0788229，认领 f866b85。
- 仅当前 AI Platform；没有修改外部 Skill、子系统、数据库 Schema、模型配置或服务器。
- 应用详情“调用记录”新增核实面板，列出最近 100 条未知或已核实操作；不解密或展示请求参数和原始远端异常。
- 管理员读写沿用组织权限校验；API 按应用及租户约束查询。核实持有记录行锁，只有 failed/unknown 接受结论。executing 状态（包括进程退出遗留）继续阻止人工覆盖，须另有可信停执行证据才能扩展处理。
- 核实保存证据、管理员 ID、时间及来源，并同事务追加 AuditLog。相同管理员重复提交相同结论/证据幂等；其他覆盖返回 409。没有远端调用或自动恢复执行。
- executed 表示管理员依据证据确认执行，不伪造原始返回值/Artifact；保留加密参数绑定拦截相同操作的新调用 ID。not_executed 关闭旧记录，但保留绑定以强制新确认；核实前的旧确认卡片不可执行。
- 暂不实现多目标自动恢复、结构化远端回执补录或长回复语义口播摘要；不能将辅助核实视为整轮所有目标完成。

## 验证

- Python 3.12 项目 venv：`pytest --noconftest tests/test_action_reconciliation.py tests/test_action_unknown_outcome.py tests/test_enterprise_action_hardening.py -q`：103 passed（1.68 秒）。
- 聚焦 Ruff 通过；前端 `npm run build` 通过（类型检查及 Vite，15.85 秒），仅既有大包及 stream externalized 提示。
- 测试覆盖证据必填、不可覆盖活跃/终态、幂等核实、管理员跨租户先拒绝、旧确认禁止远端请求，并复用未知写入及 Action 现有聚焦回归。
- 上述真实 PostgreSQL、候选管理员提交闭环均已在“后续候选验收”完成；不得把它扩展为多目标自动恢复或历史 401 已解决。
- 已合并并部署：source `28dcfbdf2cc4aec50b4f6c0d6a7f684adbe54c92`，manifest `a8cdf4cbe6f840f1803562cb5934d5502a45b886`，Coolify 部署 `voicefix81b444abfc151da9`。
- Registry-first 镜像：backend/三个共享 worker `sha256:06718a3b061ff0e0acfac83aefc826daa87c7a633eb8bda5298bea5539918576`；frontend `sha256:23e69fe1c4e1e1fab64050502bf77630e6b7f6b98a0fe568b683e6759cfbbf9d`。
- Compose 校验通过，9 个服务健康；运行容器镜像和 OCI revision 均对应上述 source。`/health` 返回 200，运行时检查确认共享 Token 一致且必要运行值存在。
- staging 使用 root 真实会话完成只读验收：“调用记录”核实面板可见，`GET /api/v1/applications/{id}/action-reconciliations` 返回 200，页面无 JavaScript 错误。为避免制造真实未知业务写入，线上未提交核实证据；提交、持久化和重复拦截使用已清理的候选 E2E 数据验证。
- 本批没有数据库迁移、依赖、服务拓扑或存储配置变化，因此没有执行数据库迁移/快照或重复 OSS 验收；旧镜像保留。
- 部署规则版本：`c948cd20bc23e64d1d53596ce49699c525351284`。

## 后续候选验收

- 真实 PostgreSQL：`RECOVERY_TEST_DATABASE_URL` 指向经本机 5459 隧道访问的专用候选数据库，`pytest --noconftest tests/test_action_reconciliation_postgres.py -q --tb=short`：1 passed（110.01 秒，包含临时全 Schema 创建/删除）。并发相同核实仅一条审计，冲突结论 409；已执行屏障与未执行重新确认查询均通过，普通完成记录不进入核实列表。随机测试 Schema 已在 finally 清理。
- 本地候选 `--lifespan off` 禁止启动业务同步。真实候选 root 表单登录后在“调用记录”完成 E2E 核实提交、刷新后持久化、执行中/已核实按钮禁用；0 JavaScript errors。运行 `frontend/scripts/e2e-action-reconciliation.mjs`，凭据仅进程环境，不保存 Cookie/Trace。
- 查询显式禁止无关关系懒加载；行锁读取刷新 ORM 已缓存状态，避免旧对象覆盖并发结论。
- 浏览器只操作单独 E2E 企业记录；未向子系统发送业务请求。未测试真实员工多目标自动恢复，不将上述结果扩展为整份计划通过。
- E2E 企业 f7578846-3646-4b55-a804-8c703d8ce0e7 及其应用、操作、测试员工和核实审计已按精确 ID 清理；没有删除真实数据。候选 API、Vite 与数据库隧道验收后停止。
