# 跨轮恢复执行证据

修复历史工具记录仅传递 ok、丢失真实执行状态的问题。待确认工具的 ok=true 不再在历史上下文中表现得与完成操作相同。

- 原生循环记录业务 Action 原始 requestId 和未知执行结果标记。
- 下一轮保留 resultStatus，区分 completed、needs_confirmation、in_progress、unknown、not_completed、unverified。
- 旧记录缺少回执状态时保持 unverified，不反推成功；仅保留最近 20 条引用，不加载请求参数或完整业务回执。
- 历史证据只是主脑恢复上下文，不授予权限、不自动确认、不触发写入。完整跨轮去重及多目标自动恢复仍未完成。

验证：43 项恢复上下文/写入回执聚焦测试通过，Ruff 通过。未改变数据库 Schema、接口权限、前端或 OSS 链路。

当前为代码候选，尚未部署；staging 仍是后端 source 8ec60f3、manifest 4b1e859。
