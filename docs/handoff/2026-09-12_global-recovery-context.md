# 总入口接续历史执行引用

总入口不带 application_id 时，runner 现在保留同 Task 历史消息中的 toolResultRefs 和 artifactRefs，各最多 20 条。页面侧栏原有上下文行为不变。不会将旧页面、角色或筛选条件当作当前授权；工具执行与文件读取仍走实时权限校验。

聚焦测试：test_assistant_runner.py 和 test_assistant_recovery_context.py，筛选 history/recovery/auxiliary_query/write_requires，49 passed；Ruff 与 git diff --check 通过。

本次是模型历史输入接续，不新增界面，不实现跨轮逻辑操作去重或完整多目标自动恢复。不按相同参数永久禁止后续合法业务修改。无数据库、依赖、前端和 OSS 变化。

发布状态：已部署 staging。代码 PR #151，source `6452d6c0520479f420d319d2bd5c0aafcac4c3fb`；backend/共享 worker digest `sha256:3a88914ceaba6025c0d4fc6df694bea069167da5189f7e6190efd0efcc121f9e`；manifest PR #152、`c60fa17cc4889bf77550cdf4dae8032442ba0aa0`；Coolify `voicefixb8cad6f18679a85e` finished，无待发布配置。

运行 backend 镜像 digest 与 OCI source 相符。前端沿用 source `28dcfbdf2cc4aec50b4f6c0d6a7f684adbe54c92`，digest `sha256:23e69fe1c4e1e1fab64050502bf77630e6b7f6b98a0fe568b683e6759cfbbf9d`。9 服务 healthy，必填运行值非空、共享令牌一致，公网 /health 200。root 现有真实浏览器会话刷新页面和 auth/me 均 200，检查期间无页面 JavaScript 异常。没有新增员工自然语言跨视图业务实测，不将单元测试记为该场景验收。

Compose 校验 PASS（registry-image、无源码构建、无仓库 bind mount、数据库不公开端口）。未修改存储和依赖，无迁移、不需数据库备份；不重复全量 CRUD 或 OSS 验收。临时本地/服务器构建归档已清理，旧镜像和全部业务数据保留。部署规则版本 c948cd2。

目标仓库：https://github.com/ZhuoJian-AI/ai-platform；服务：https://ai-platform.staging.zhuojianai.com；Coolify Application：jwbpxybciypgdidyzu2ebrlr（https://coolify.zhuojianai.com）。Registry-first 手动触发，只部署当前 staging。
