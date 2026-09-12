# 跨轮恢复执行证据

修复历史工具记录仅传递 ok、丢失真实执行状态的问题。待确认工具的 ok=true 不再在历史上下文中表现得与完成操作相同。

- 原生循环记录业务 Action 原始 requestId 和未知执行结果标记。
- 下一轮保留 resultStatus，区分 completed、needs_confirmation、in_progress、unknown、not_completed、unverified。
- 旧记录缺少回执状态时保持 unverified，不反推成功；仅保留最近 20 条引用，不加载请求参数或完整业务回执。
- 历史证据只是主脑恢复上下文，不授予权限、不自动确认、不触发写入。完整跨轮去重及多目标自动恢复仍未完成。

验证：43 项恢复上下文/写入回执聚焦测试通过，Ruff 通过。未改变数据库 Schema、接口权限、前端或 OSS 链路。

已部署 staging：source `6b539e3e00688f7315f775e7cc140aaa944817a8`（PR #148），backend/共享 worker 镜像 `sha256:8ed83375e45605eb159a293dd3957b7bb78c166f18fdf457773793675b9ca4be`，manifest `55db9add4950c64e691651ddbffa43bc462ed273`（PR #149），Coolify `voicefixa0a2e35de8bda7c7` finished。前端沿用 source 28dcfbd、digest 23e69fe1c4e1e1fab64050502bf77630e6b7f6b98a0fe568b683e6759cfbbf9d。

Compose PASS，运行 backend digest/OCI revision 相符，9 服务 healthy，无待发布配置；必填运行值和共享令牌检查通过。公网 /health 200，root 真实浏览器会话刷新和 auth/me 200。没有重复全量 CRUD、模型或文件测试；无迁移和存储变化。临时构建归档已清理，旧镜像保留。部署规则 c948cd2。

剩余明确缺口：runner._history 当前仅在存在 application_id 时注入业务上下文，因此回到不带应用上下文的总入口仍需接续执行引用。此批不宣称完整总入口恢复、跨轮副作用去重或多目标自动恢复已经实现。
