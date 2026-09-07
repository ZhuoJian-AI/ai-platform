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
GitHub App Source 选择“卓建-github”。当前应用使用手动部署；更新 `main` 后由管理员点击
`Deploy`，不要假定 push 会自动上线。

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
- `OAUTH_SIGNING_KEY=<独立的随机长字符串>`
- `MASTER_ENCRYPTION_KEY=<Fernet key>`
- `MES_API_KEY=<随机长字符串>`
- `CRM_API_KEY=<随机长字符串>`
- `CODE_SKILLS_ENABLED=true`
- `SKILL_RUNNER_TOKEN=<随机长字符串>`
- `DSH_RUNTIME_TOKEN=<随机长字符串>`
- `EXTENSION_BUILDER_TOKEN=<随机长字符串>`
- `SKILL_RUNNER_TIMEOUT_SECONDS=120`
- `WORKSPACE_OBJECT_STORAGE_ENABLED=true`
- `STORAGE_GATEWAY_URL=https://storage.staging.zhuojianai.com`
- `STORAGE_PROJECT_TOKEN=<由平台 Provisioner 按仓库签发的项目令牌>`
- `STORAGE_PUBLIC_ENDPOINT=https://oss-cn-hongkong.aliyuncs.com`
- `STORAGE_INTERNAL_ENDPOINT=https://oss-cn-hongkong-internal.aliyuncs.com`
- `STORAGE_GATEWAY_TIMEOUT_SECONDS=60`
- `WORKSPACE_WEBOFFICE_ENABLED=true`
- `WORKSPACE_WEBOFFICE_MAX_BYTES=209715200`
- `WORKSPACE_PDF_DIRECT_PREVIEW_MAX_BYTES=20971520`
- `WORKSPACE_PREVIEW_JOB_POLL_SECONDS=1`
- `WORKSPACE_PREVIEW_JOB_LEASE_SECONDS=900`

工作空间二进制原文件通过 Storage Gateway 写入项目隔离前缀，AI Platform 不持有 OSS
AccessKey。ECS 与香港 OSS 之间使用 internal endpoint；浏览器下载仍先经过后端鉴权，
不会向终端用户暴露长期凭证或公开 Bucket。小型可编辑文本与 AI 提取文本继续存 PostgreSQL。

`MASTER_ENCRYPTION_KEY` 必须使用 Fernet 格式，可由服务器管理员在安全终端生成：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

密码若含 URL 特殊字符，必须在 `DATABASE_URL`、`REDIS_URL` 中进行 URL 编码。

## 首次登录与验收

空数据库不会自动创建默认管理员，也不存在 `root / root` 默认密码。首次部署时由服务器管理员
在 backend 容器中交互运行 `python scripts/bootstrap_platform_admin.py` 创建首个平台超级管理员；
不要把管理员密码写入命令、Compose 或 Git。

验收要求：

1. `postgres`、`redis`、`mock`、`skill-runner`、`dsh-runtime`、`extension-builder`、
   `backend`、`workspace-parser`、`workspace-preview`、`office-edit-reconcile`、`storage-lifecycle`、
   `multimodal-worker`、`frontend` 均健康；
2. `https://ai-platform.staging.zhuojianai.com/health` 返回 HTTP 200；
3. 管理员入口 `/login` 可以打开并登录；
4. Coolify 运行版本对应 GitHub `main` 的 SHA；
5. 手动部署记录显示成功，并且运行镜像的 `SOURCE_COMMIT` 对应本次源代码 SHA。

## 升级 DSH 版本后的发版步骤

`dsh_runtime/vendor` 里的 `@deepseek-ai/*` 升版（如 rc.5 → rc.8）后，只重建 app 镜像不够，
有两处会把旧版本带上线：dsh-runtime 的 app 镜像 `FROM` 一个预装 `node_modules` 的 deps 基础镜像；
数据库里已有的 `platform_extension_releases` 行 manifest 仍写着旧 `dsh_version`，新运行时的
`verifyRelease` 会拒绝激活它。按顺序做：

1. **合并**：功能分支合入 `main`。三处版本常量必须一致——`dsh_runtime/src/extensions.ts::DSH_VERSION`、
   `extension_builder/src/builder.ts::compatibleDsh`、
   `llm_router/backend/app/services/platform_extension_catalog.py::DSH_VERSION`（Python 侧唯一来源，
   基线 manifest、目录、自愈都读它）。核对：
   `grep -rn "0\.1\.0-rc\." --exclude-dir=node_modules --exclude-dir=vendor --exclude-dir=dist .`
2. **重建 deps 基础镜像**：在发版服务器、该 commit 的 checkout 里运行 `scripts/build-dsh-runtime-deps.sh`。
   脚本以仓库根为 build context 构建 `infra/base-images/dsh-runtime-deps.Dockerfile`（COPY
   `dsh_runtime/package.json`、`pnpm-lock.yaml`、`pnpm-workspace.yaml`、`vendor/`），先校验
   `vendor/SHA256SUMS`，构建后核对镜像内 `@deepseek-ai/dsh-agent-loop` 版本等于 `DSH_VERSION`，
   打 `127.0.0.1:5000/zhuojian/ai-platform-dsh-runtime-deps:<short sha>` 并 push，最后打印下一步要用的
   `AI_PLATFORM_DSH_RUNTIME_DEPS_BASE=<digest>` 和完整的 app 镜像构建命令。
   extension-builder 的 deps 镜像不含 `@deepseek-ai/*`（只有 `semver`），DSH 升级本身不需要重建它；
   只有 `extension_builder/pnpm-lock.yaml` 变了才按同样方式重建：
   `DOCKER_BUILDKIT=1 docker build --build-arg AI_PLATFORM_NODE22_BASE=127.0.0.1:5000/zhuojian/ai-platform-node22-pnpm:20260824-v1 -f infra/base-images/extension-builder-deps.Dockerfile -t 127.0.0.1:5000/zhuojian/ai-platform-extension-builder-deps:<short sha> .`
3. **构建 app 镜像**：dsh-runtime 用脚本打印的命令（`--build-arg AI_PLATFORM_DSH_RUNTIME_DEPS_BASE=<新 digest>`）。
   extension-builder 的 `builder.ts` 里有版本字面量，app 镜像也要重建：
   `DOCKER_BUILDKIT=1 docker build --build-arg AI_PLATFORM_EXTENSION_BUILDER_DEPS_BASE=<deps 镜像> --build-arg AI_PLATFORM_NODE22_BASE=127.0.0.1:5000/zhuojian/ai-platform-node22-pnpm:20260824-v1 --build-arg SOURCE_COMMIT=<sha> -f extension_builder/Dockerfile.coolify -t 127.0.0.1:5000/zhuojian/ai-platform-extension-builder-app:source-<short sha> extension_builder`。
   backend 镜像照常构建（本次含 alembic 数据迁移 `0069_dsh_release_rc8`）。所有镜像都传 `SOURCE_COMMIT`。
4. **pin digest**：`docker push` 后用 `docker image inspect --format '{{index .RepoDigests 0}}' <tag>` 取 digest，
   改 `docker-compose.coolify.yml` 中 `dsh-runtime`、`extension-builder`、`backend`（含共用 backend 镜像的
   worker 服务）的 `image:`，以 `chore(deploy): pin ...` 提交到 `main`。钉之前先 `git pull` 并逐个比对
   运行镜像的 `org.opencontainers.image.revision`，不要把别人刚钉的新镜像换回旧构建。
5. **部署**：Coolify 手动 `Deploy`。backend 启动时 alembic 执行 `0069_dsh_release_rc8`：把只含平台基线项的
   历史发布行从 `0.1.0-rc.5` 改写到 `0.1.0-rc.8` 并重算 checksum（幂等；每行记一条
   `dsh_version_migrated` 事件，downgrade 依此还原）。含外部扩展的行不由迁移处理，交给下一步的自愈。
6. **确认基线已自愈**：看 backend 启动日志（`platform_extension_service.sync_active_release_to_runtime`）：
   - `platform_extension_release_version_healed`：活动发布已被新行取代，`mode=baseline_regenerated`
     （平台基线按新目录重生成）或 `version_rewritten`（自定义发布只改版本号），旧行转为 `superseded`；
     活动发布本来就是新版本时没有这条。
   - `platform_extension_runtime_activated` 或 `platform_extension_runtime_in_sync`：运行时已接受该发布。
   - `platform_extension_release_version_incompatible`：活动发布是自定义的且含不兼容外部扩展（日志与
     `release_version_heal_skipped` 事件列出原因），运行时停在内建基线，需超管在扩展中心重新发布。
   - `platform_extension_runtime_activation_failed`：`runtime_response` 字段带运行时的拒绝原因。
   扩展中心概览里「活动发布」版本号应比升级前 +1，manifest 的 `dsh_version` 为新版本，
   dsh-runtime `/health` 报的 `release_id` 与之一致。
