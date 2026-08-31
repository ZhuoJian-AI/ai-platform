# 企业原生模块发布控制面

灼见只管理模块索引、身份、权限、Action、审计和事件；企业模块的前端、后端与业务数据库仍运行在企业 ECS。中央 Backend 通过 Coolify API 把经过组织发布 Key 授权的 Git commit 发布到该企业预先绑定的 Server。

## 中央配置

以下值只配置为灼见 Backend 的部署 Secret，不进入仓库、Skill 或企业 ECS：

```text
COOLIFY_MODULE_DEPLOYER_ENABLED=true
COOLIFY_API_URL=https://<trusted-coolify-host>/api/v1
COOLIFY_API_TOKEN=<central-api-token>
MODULE_SAAS_ORIGIN=https://ai-platform.staging.zhuojianai.com
```

`COOLIFY_API_TOKEN` 应限制在灼见自己的 Coolify Team。业务 AI 只持有 organization-scoped 平台发布 Key；它不能直接调用 Coolify API。

## 企业一次性部署档案

平台最高管理员或该企业管理员调用：

```text
PUT /api/v1/module-publisher/organizations/{organizationId}/deployment-profile
```

保存以下非敏感标识：

- `runtime_key`：企业内稳定运行环境标识；一台或多台 ECS 各自登记；
- `server_uuid`：企业 ECS 在 Coolify 中的 Server；
- `project_uuid` 与 Environment：该企业模块所在项目；
- `github_app_uuid`：能读取灼见组织私有模块仓库的 Coolify GitHub Source；
- `domain_suffix`：已经通过通配 DNS 指向该 ECS 的后缀，不带 `*.`；
- `destination_uuid`、`use_build_server`：可选部署能力。

不同企业使用不同 Profile，同一企业可以有多个 Runtime，并标记一个默认目标。模块首次发布后固定绑定 Runtime；普通更新不能借发布接口迁移服务器。发布接口自己派生仓库名和域名，调用方不能覆盖 Server 或 owner。

## 业务 AI 发布

1. `POST /api/v1/module-publisher/repositories` 创建/复用 `{companySlug}-{moduleSlug}` 私有仓库并返回短时单仓库 Token。
2. 推送 `HEAD:main`。
3. `POST /api/v1/module-publisher/deployments` 提交 `moduleSlug`、规范仓库名和 commit。
4. `GET /api/v1/module-publisher/deployments/{moduleSlug}` 轮询。

平台为同一模块复用 Coolify Application、域名和 `/data` 卷，并由中央生成 `ZHUOJIAN_INTEGRATION_SECRET`、`SESSION_SECRET`。部署成功后验证 `/health`、配置集成并同步 Manifest；响应为 `healthy` 时 `application_id` 已可用于 SaaS 授权。

## 失败和回退

状态包括 `deploying`、`verifying`、`healthy`、`failed`、`rolling_back`、`rolled_back` 与 `rollback_failed`。平台返回 `failure_stage`、脱敏日志摘要和 `next_action`。

有历史健康 commit 时失败版本会在同一 Coolify Application 自动回退；没有历史版本则保留失败记录。任何路径都不删除 Application、持久卷或企业数据库。
