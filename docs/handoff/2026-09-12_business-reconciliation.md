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
- 尚未完成：真实 PostgreSQL 并发核实/事务审计验证、新卡片允许路径与已执行重复屏障数据库验证、候选真实管理员浏览器核实闭环。不得凭单测或构建直接宣布可以上线。
- 本批未合并、未构建镜像、未部署。staging 仍是 1999b1b 语音 source / 0d8ec7a manifest。
- 部署规则 fetch 与当前 HEAD 一致：c948cd20bc23e64d1d53596ce49699c525351284；当前只执行代码候选步骤，发布前需再次预检。
