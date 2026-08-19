# AI Platform — Coolify 部署参数

本项目使用 `docker-compose.coolify.yml`。Coolify 直接把正式域名转发到 `frontend`
服务的内部端口 `80`。该容器同时提供 Vite 静态前端，并将 `/api`、`/v1` 和 `/mcp`
转发到内部 FastAPI 服务。

## 首次绑定

- GitHub 仓库：`ZhuoJian-AI/ai-platform`
- 分支：`main`
- 构建方式：Docker Compose
- Compose 路径：`/docker-compose.coolify.yml`
- 公网服务：`frontend`
- 内部端口：`80`
- 健康检查：`/health`
- 预期状态码：`200`
- 正式测试域名：`https://ai-platform.staging.zhuojianai.com`

Coolify 中选择 `Root Team` → `项目应用` → `舞台 / staging`，部署目标选择“酷乐”，
GitHub App Source 选择“卓建-github”，保持 Auto Deploy 开启。

域名表单选择 `https`，Domain 填 `ai-platform.staging.zhuojianai.com`，Port 填 `80`，
Path 留空。不要给 PostgreSQL、Redis、Mock 或 backend 配置公网域名或宿主机端口。

## 必填环境变量

这些值只保存在 Coolify Application 中，不得提交到 Git：

- `COMPOSE_PROJECT_NAME=ai-platform`
- `PUBLIC_ORIGIN=https://ai-platform.staging.zhuojianai.com`
- `POSTGRES_DB=ai_infra`
- `POSTGRES_USER=ai_infra`
- `POSTGRES_PASSWORD=<随机强密码>`
- `DATABASE_URL=postgresql+asyncpg://ai_infra:<URL编码后的数据库密码>@postgres:5432/ai_infra`
- `REDIS_PASSWORD=<随机强密码>`
- `REDIS_URL=redis://:<URL编码后的Redis密码>@redis:6379/0`
- `SECRET_KEY=<随机长字符串>`
- `MASTER_ENCRYPTION_KEY=<Fernet key>`
- `MES_API_KEY=<随机长字符串>`
- `CRM_API_KEY=<随机长字符串>`
- `CODE_SKILLS_ENABLED=true`
- `SKILL_RUNNER_TOKEN=<随机长字符串>`
- `SKILL_RUNNER_TIMEOUT_SECONDS=120`
- `WORKSPACE_OBJECT_STORAGE_ENABLED=true`
- `STORAGE_GATEWAY_URL=https://storage.staging.zhuojianai.com`
- `STORAGE_PROJECT_TOKEN=<由平台 Provisioner 按仓库签发的项目令牌>`
- `STORAGE_PUBLIC_ENDPOINT=https://oss-cn-hongkong.aliyuncs.com`
- `STORAGE_INTERNAL_ENDPOINT=https://oss-cn-hongkong-internal.aliyuncs.com`
- `STORAGE_GATEWAY_TIMEOUT_SECONDS=60`

工作空间二进制原文件通过 Storage Gateway 写入项目隔离前缀，AI Platform 不持有 OSS
AccessKey。ECS 与香港 OSS 之间使用 internal endpoint；浏览器下载仍先经过后端鉴权，
不会向终端用户暴露长期凭证或公开 Bucket。小型可编辑文本与 AI 提取文本继续存 PostgreSQL。

`MASTER_ENCRYPTION_KEY` 必须使用 Fernet 格式，可由服务器管理员在安全终端生成：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

密码若含 URL 特殊字符，必须在 `DATABASE_URL`、`REDIS_URL` 中进行 URL 编码。

## 首次登录与验收

空数据库首次启动会自动创建平台超级管理员 `root / root`。部署成功后应立即登录并修改
默认密码。

验收要求：

1. `postgres`、`redis`、`mock`、`skill-runner`、`backend`、`frontend` 均健康；
2. `https://ai-platform.staging.zhuojianai.com/health` 返回 HTTP 200；
3. 管理员入口 `/login` 可以打开并登录；
4. Coolify 运行版本对应 GitHub `main` 的 SHA；
5. 首次绑定后再 push 一次 `main`，确认 Webhook 自动部署成功。
