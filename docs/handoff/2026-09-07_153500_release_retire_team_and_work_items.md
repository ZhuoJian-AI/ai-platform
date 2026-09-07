# Team 与平台跨部门待办退役发布

## 发布内容

- 产品源提交：`91251eed7bada1a19ef055b86cc3d6b479fb268e`
- 目标：`https://ai-platform.staging.zhuojianai.com`
- 仅更新 SaaS 后端共用镜像和前端镜像；数据库迁移由后端启动时执行。

## 镜像

- 后端旧 digest：`sha256:f15654f22c93f58758f62da41794d6730ff5473d5fc4b8d0a344f45b7bb76401`
- 后端新 digest：`sha256:3fa41d3dfd3828c4e96cba0db9f03c5fb9be45783deec9a590886ab415894c0a`
- 前端旧 digest：`sha256:235984fe482ef7f760093210e97292fa0c3cc3e02fdf47cd45d12cef1ae34f40`
- 前端新 digest：`sha256:0610e79af632e90746af2bc547fc64a0b73ad6b7da1a242deafcb022f203af8e`
- 两个新镜像的 OCI revision 均已核对为产品源提交。

## 数据备份

- 部署前 PostgreSQL custom-format 整库备份已通过 `pg_restore --list` 校验。
- OSS 前缀：`projects/platform-admin-backups/assets/ai-platform/20260907_153207`
- 数据库备份 SHA-256：`a1cd6c1dd8149e792ac1ffd8771039c7f132a5da3d5e8c22bd11393f97b516b7`
- 备份清单 SHA-256：`753d1c69dbe4c8d9dd4088b199048c6d83715cce54ae44bfc843087b1fd18990`
- 备份时数据库版本为 `0068_ai_quota_rollups`，包含 1 个活动 Team 和 13 条旧平台待办。

## 回退

- 应用异常时恢复上述旧镜像 digest，不回滚数据库。
- `0069` 保留兼容字段，旧镜像仍可读取；已删除的平台待办数据通过整库备份恢复。

## 发布后验证

- 核对数据库版本升级至 `0069_retire_team_scope`，Team 与待办引用归零。
- 核对全部容器健康、公开健康检查、管理员端和员工端均不再出现 Team。
- 核对旧 Team 与跨部门待办 API 返回中文 `410 Gone`。
- 使用真实企业管理员和普通员工完成 Playwright 回归。
