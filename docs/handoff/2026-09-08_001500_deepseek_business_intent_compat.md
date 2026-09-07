# DeepSeek 业务意图兼容热修发布

## 范围

- 产品源提交：`2cfe4ef736653902277e1affc21b57b5501c0c68`
- 目标：`https://ai-platform.staging.zhuojianai.com`
- 仅更新 SaaS 共用后端镜像；前端、数据库、模型计费、管理员登录、域名和子系统均不修改。

## 行为修复

- 保留具名结构化意图工具；若上游明确返回思考模式不支持 `tool_choice`，仅移除该字段并以同一工具集合重试一次。
- 重试结果仍经过 SaaS 的结构化 Schema、页面范围、Action 范围和服务端权限校验。
- 业务助手在准备阶段失败时持久化中文助手消息，刷新后不再出现整轮回复消失。

## 不可变镜像

- 后端旧 digest：`sha256:5525c253dc8d07e309fb8f4e7fb63a8c37bb16f4a62d50a6c25b01faee3d68d8`
- 后端新 digest：`sha256:ba47ba3891e57f83e8811a8a06dcccbc17d68c68af0602562038a1acbf20589e`
- 新镜像架构：`linux/amd64`
- OCI revision 已核对为产品源提交。

## 发布前验证

- 本地聚焦测试：35 passed；Ruff 通过；`git diff --check` 通过。
- 镜像内 `import app.main` 通过。
- 镜像内挂载只读测试集：35 passed；仅有 pytest 无法写只读缓存目录的预期警告。
- 源码归档本地/远端 SHA-256 一致：`f3b23ed7523f76604944db8a9353d98aed0cc607651f7815e49879537214981a`。
- 无数据库迁移，因此不执行数据库备份。

## 发布后验收

- Coolify 只拉取新 digest，核对 5 个后端服务均为新 digest、OCI revision 正确且所有长期服务 healthy。
- 使用张三真实员工账号验证页面说明、实时查询、Excel 工作空间 Artifact、多对话隔离、历史恢复和 URL `conversation` 恢复。

## 回退

- 异常时只将 5 个共用后端服务恢复到旧 digest，不回滚数据库。

## 规则依据

- `ZhuoJian-AI/zhuojian-server-deploy`：`c948cd2`
