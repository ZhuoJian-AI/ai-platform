# 总入口接续历史执行引用

总入口不带 application_id 时，runner 现在保留同 Task 历史消息中的 toolResultRefs 和 artifactRefs，各最多 20 条。页面侧栏原有上下文行为不变。不会将旧页面、角色或筛选条件当作当前授权；工具执行与文件读取仍走实时权限校验。

聚焦测试：test_assistant_runner.py 和 test_assistant_recovery_context.py，筛选 history/recovery/auxiliary_query/write_requires，49 passed；Ruff 与 git diff --check 通过。

本次是模型历史输入接续，不新增界面，不实现跨轮逻辑操作去重或完整多目标自动恢复。不按相同参数永久禁止后续合法业务修改。无数据库、依赖、前端和 OSS 变化。

发布状态：代码已完成并通过聚焦测试，尚未部署；运行镜像仍为上一批 source 6b539e3。部署证据另行补充，不将单元测试记为真实用户验收。
