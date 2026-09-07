# 业务小助手生产编排修复发布

## 发布范围

- 产品源提交：`6ffd34a8b97fcbe8a8a1443e887a68f6eb75e108`
- 目标：`https://ai-platform.staging.zhuojianai.com`
- 只更新 SaaS 后端共用镜像和前端镜像；不含数据库迁移，不修改模型计费、管理员登录、域名或子系统。

## 不可变镜像

- 后端旧 digest：`sha256:bf150891e7abc4501cb5accf3ed794328b08996d85fc2f0e75b09be7d9a668d4`
- 后端新 digest：`sha256:5525c253dc8d07e309fb8f4e7fb63a8c37bb16f4a62d50a6c25b01faee3d68d8`
- 前端旧 digest：`sha256:62500ff13382fcb8dca9d907561f4f422730bb904b9d77eed71aae2419b106cc`
- 前端新 digest：`sha256:db9b8b9bea6d7dfd5f3d46666e8c567ec203729018a2675a5f55426e9e782c85`
- 两个新镜像均为 `linux/amd64`，OCI revision 均已核对为产品源提交。
- 后端以当前线上已验证的不可变后端镜像为依赖基座，删除旧 `/app` 后复制目标提交代码；前端使用内部缓存的 Node 22 与 Nginx 1.27 基础镜像构建。

## 已完成验证

- 产品分支聚焦测试：50 passed；Ruff、`test:business-conversation`、`test:subsystem-bridge`、前端生产构建及 `git diff --check` 通过。
- 镜像内后端 `import app.main` 通过。
- 镜像内同一组 50 项编排、权限与工具调用测试通过。
- 前端生产构建通过；Nginx 配置检查通过，仅保留既有 chunk-size 警告。
- Compose 入口校验通过：Registry-first、13 个长期服务均有健康检查、无源码构建、无仓库 bind mount、无公开内部端口。
- 当前 staging 的 14 个必填变量均通过非空校验；检查未输出 Secret 原文。
- 无数据库迁移，因此未执行数据库备份。

## 发布后验收

- 核对 Coolify 部署提交、运行容器 digest、OCI revision 与全部长期服务健康状态。
- 使用张三真实员工账号验证页面说明零 Action、实时查询正确 Action、Excel 工作空间 Artifact、多对话隔离/恢复和 URL `conversation` 恢复。
- 下载 Excel 并核对 OOXML 文件头、非空内容与个人工作空间落点。

## 回退

- 异常时只恢复上述旧镜像 digest，不回滚数据库。

## 规则依据

- `ZhuoJian-AI/zhuojian-server-deploy`：`c948cd2`
