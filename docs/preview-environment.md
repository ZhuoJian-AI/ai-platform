# DSH 加强版预览环境（ai-platform-dsh）

第二套独立的 Coolify 部署，跑 `dsh-enhanced` 分支（DSH rc.8 + 原生策略 / 审批），与 `main` 驱动的
staging（`https://ai-platform.staging.zhuojianai.com`）并行、互不共享容器 / 网络 / 卷 / 数据库 / 密钥。
目的：让 DSH 加强版在合回 `main` 之前有一个能给人用、能反复重发的环境。

| 项目 | 值 |
| --- | --- |
| 域名 | `https://ai-platform-dsh.staging.zhuojianai.com` |
| 仓库 / 分支 | `ZhuoJian-AI/ai-platform` / `dsh-enhanced` |
| Compose 路径 | `/docker-compose.preview.yml`（image-only，无 `build:`，全部 `image@sha256`） |
| 公网服务 / 端口 / 健康检查 | `frontend` / `80` / `/health` → 200 |
| Coolify 项目 / 环境 | `项目应用` (`5wv1rhfb0dirvj8xpveumbfu`) / `staging` (`cf7b2idiorxlwqm34ofjmiz2`) |
| GitHub App Source | `zhuojian-github` (`k5nbffgwr0jvahroluxdolll`) |
| 部署目标 | `酷乐`（`localhost`，与 staging 同一台 16G 机器） |
| 服务（12 个） | postgres redis mock skill-runner dsh-runtime extension-builder backend workspace-parser workspace-preview office-edit-reconcile multimodal-worker frontend |

与 `docker-compose.coolify.yml` 的全部差异写在 `docker-compose.preview.yml` 的文件头；服务名、镜像名、
环境变量名完全一致，只有默认值、卷名、内存上限不同，并且**没有 `storage-lifecycle`**（见下方「存储」）。

## 在 Coolify 里创建

1. `Root Team` → `项目应用` → `staging` → **Add** → **Private Git Repository (GitHub App)**，Source 选 `zhuojian-github`，
   仓库 `ZhuoJian-AI/ai-platform`，分支 **`dsh-enhanced`**，Build Pack **Docker Compose**，Compose 路径
   `/docker-compose.preview.yml`，部署目标 `酷乐`。API 方式：`POST /applications/private-github-app`，
   `docker_compose_domains` 传对象数组 `[{"name":"frontend","domain":"https://ai-platform-dsh.staging.zhuojianai.com"}]`。
2. 域名：只给 `frontend` 绑 `https` / `ai-platform-dsh.staging.zhuojianai.com` / Port `80` / Path 空。postgres、redis、
   mock、backend 不配域名、不发布宿主机端口。
3. 创建后从 URL 里记下 Application uuid，填进 `TRAEFIK_DOCKER_NETWORK`（Coolify 把每个 Application 的容器接到以
   uuid 命名的网络上，Traefik 只能从那个网络访问 frontend；staging 那套的默认值是 staging 自己的 uuid，不能沿用）。
4. **Auto Deploy 关掉**。这是 Registry-first 项目：普通源码 push 没有对应镜像，不能触发部署；只有
   `chore(deploy): pin preview images (...)` 那种 manifest 提交就绪后才手动 Deploy。
5. 填环境变量（下一节），保存后确认没有 **Changes pending**，再 Deploy。

## 环境变量

值只存在 Coolify Application 里，不进 Git。先照 `COOLIFY_DEPLOYMENT.md`「必填环境变量」把 staging 的清单复制一份，
然后**把下面这些改成预览栈自己的值**：

| 变量 | 预览栈的值 | 为什么不能照抄 |
| --- | --- | --- |
| `COMPOSE_PROJECT_NAME` | `ai-platform-dsh` | Coolify 以 uuid 做项目名，这是兜底，防止和 staging 共用卷前缀 |
| `PUBLIC_ORIGIN` | `https://ai-platform-dsh.staging.zhuojianai.com` | backend 的 `PROXY_BASE_URL` / `OAUTH_ISSUER` / `OAUTH_PUBLIC_BASE_URL` / `BROWSER_ALLOWED_ORIGINS`（Cookie / CORS / OAuth origin）全由它派生 |
| `MODULE_SAAS_ORIGIN` | 同上 | 模块发布器回写的 SaaS 地址（文件默认值已改，显式设更稳） |
| `TRAEFIK_DOCKER_NETWORK` | 本 Application 的 uuid | 无默认值，必填 |
| `DATA_PLANE_PREFIX` | `10.0.11`（文件默认值） | staging 用 `10.0.10`；同一宿主机两条 `internal` 网段重叠会让 `up` 直接失败（Pool overlaps）。宿主机已占用就换一个空闲 /24 |
| `POSTGRES_PASSWORD` / `DATABASE_URL` / `REDIS_PASSWORD` / `REDIS_URL` | 新密码 | 独立数据库；URL 里主机名仍写 `postgres` / `redis`，密码含特殊字符要 URL 编码 |
| `SECRET_KEY` / `OAUTH_SIGNING_KEY` / `MASTER_ENCRYPTION_KEY` | 全新生成（`MASTER_ENCRYPTION_KEY` 为 Fernet） | 独立 DB，复用 staging 密钥没有意义、只增加泄露面 |
| `SKILL_RUNNER_TOKEN` / `DSH_RUNTIME_TOKEN` / `EXTENSION_BUILDER_TOKEN` / `MES_API_KEY` / `CRM_API_KEY` | 全新生成 | 栈内互认令牌；调用端与服务端在同一 Compose 里自动一致 |
| `STORAGE_PROJECT_TOKEN` | 平台按仓库签发的那个（与 staging 相同） | 见「存储」；能拿到预览专用令牌就用专用的 |

其余（`STORAGE_GATEWAY_URL`、`STORAGE_*_ENDPOINT`、`WORKSPACE_*`、`CODE_SKILLS_ENABLED`、功能开关…）与 staging 相同。
`COOLIFY_MODULE_DEPLOYER_ENABLED` / `GITHUB_MODULE_PUBLISHER_ENABLED` 保持 `false`（默认），预览栈不往外发布模块。
部署前用 `validate_runtime_env.py` 核对本环境（`is_preview:false` 那份）的真实值非空，`Managed by Compose` 不算。

首次登录：空库没有默认管理员，进 backend 容器交互运行 `python scripts/bootstrap_platform_admin.py` 建首个超管。

## 发版循环（每次要把 dsh-enhanced 的新提交放上预览）

发版服务器上有一份 `dsh-enhanced` 的检出：`/root/zhuojian-builds/ai-platform-dsh-enhanced`（与 main 的构建目录分开）。

1. **服务器**：`git -C /root/zhuojian-builds/ai-platform-dsh-enhanced pull --ff-only`，确认 HEAD 就是要发的 source SHA，工作树干净。
2. **服务器，只在 DSH 版本升级时**（`dsh_runtime/package.json` / `pnpm-lock.yaml` / `pnpm-workspace.yaml` / `vendor/` 变了）：
   `scripts/build-dsh-runtime-deps.sh` → 记下它打印的 `AI_PLATFORM_DSH_RUNTIME_DEPS_BASE=<ref>`。rc.5 → rc.8 这次必须做一遍。
3. **服务器**：`DSH_DEPS_BASE=<上一步的 ref> scripts/preview-release.sh`。脚本按「compose 里钉着的镜像的 revision 标签 → `git diff`
   构建上下文」只重建有变化的镜像（backend / workspace-preview / frontend / dsh-runtime / skill-runner / extension-builder / mock），
   `docker push`，读 `RepoDigests`，改写 `docker-compose.preview.yml` 的 `image:`（backend 镜像会一起改到 workspace-parser /
   office-edit-reconcile / multimodal-worker），打印汇总表、`git diff --stat`，并把补丁写到 `preview-pin-<short sha>.patch`。
   要重建 dsh-runtime 而 `DSH_DEPS_BASE` 没设时脚本拒绝执行。日志：`build-<svc>.log`。`--only backend,frontend` 只重建指定服务，
   `--no-push` 只构建。
4. **操作者机器**：把补丁拿回来 `git apply`，`git commit -am "chore(deploy): pin preview images (<short sha>)"`，`git push origin dsh-enhanced`。
   服务器上没有写凭据，不在服务器提交。这就是 manifest SHA。
5. **Coolify**：在预览 Application 手动 **Deploy**，确认运行的是这个 manifest SHA、12 个容器 healthy、
   `https://ai-platform-dsh.staging.zhuojianai.com/health` 返回 200；DSH 升级那次还要看 backend 日志里
   `platform_extension_release_version_healed` / `platform_extension_runtime_activated`，dsh-runtime `/health` 报 `0.1.0-rc.8`。
6. **服务器**：`git pull --ff-only` 把 pin 提交同步回检出，下次变更检测才有正确的基线。

`source SHA → image digest → manifest SHA → Coolify 部署 ID → 运行容器 digest` 这条映射与 staging 的要求一样，发版记录里写全。

## 存储：为什么没有 storage-lifecycle，以及代价

`STORAGE_PROJECT_TOKEN` 由平台按 GitHub 仓库签发，两套栈拿到的是同一个令牌，也就是**同一个 OSS 项目前缀**。
`storage-lifecycle` 每天做一次孤儿回收（`storage_lifecycle_service.reconcile_orphan_objects`）：列出前缀下超过
`storage_orphan_grace_days`（7 天）的对象，凡是**本栈数据库**没引用的就删。预览栈跑它 = 把 staging 的全部文件当孤儿删掉。
所以：

- `docker-compose.preview.yml` 不含 `storage-lifecycle`；任何 `STORAGE_ORPHAN` 类的 GC 在预览环境必须保持关闭，
  也不要用 `docker exec` 手动跑 `app.workers.storage_lifecycle`。
- 上传不受影响：backend 经 Storage Gateway 签名直传照常工作。
- 预览栈的回收站到期清理、上传会话过期、技能版本物理删除都不会发生，只留 DB tombstone——预览环境可接受。
- **反向风险依然存在**：staging 的 storage-lifecycle 会把预览栈上传、超过 7 天的对象当孤儿删掉。预览里的文件按 7 天寿命看待。
- 不要用 staging 的数据库 dump 初始化预览库：两库引用同一批 object_key，任何一边删文件都会删掉另一边的对象。
- 根治办法是让平台 Provisioner 为预览签发**独立的** `STORAGE_PROJECT_TOKEN`（独立前缀）；拿到后可以把 storage-lifecycle 加回来。

## 资源预算（16G 机器上的第三套栈）

内存上限（cgroup 上限，不是常驻占用）：postgres 1536M · redis 384M · mock 256M · skill-runner 2560M（含 1G tmpfs）·
dsh-runtime 1536M · extension-builder 1G（含 512M tmpfs）· backend 2G · workspace-parser 1280M · workspace-preview 2G
（含 1G tmpfs，LibreOffice）· office-edit-reconcile 384M · multimodal-worker 1280M · frontend 256M，合计约 14.4G 上限，
比 staging 少 2.4G（去掉 storage-lifecycle 384M + 各项下调）。同一时间只跑一个部署，部署期间 Registry 拉取与解压会有短时峰值。
两套栈同时压测会互相挤，预览栈里 `DSH_RUNTIME_HARD_CONCURRENCY` / `AGENT_GLOBAL_CONCURRENCY` 可以按需调低。

## 下线

1. Coolify 里 **Stop** 预览 Application，确认 12 个容器已停。
2. 删除 Application（勾选删除卷）：`dsh_postgres_data` / `dsh_redis_data` / `dsh_skill_cache` / `dsh_extension_cache`
   都是本栈命名卷，不会碰 staging 的 `postgres_data` 等。
3. 预览栈留在 OSS 里的对象不用手清：它们在 staging 数据库里没有引用，staging 的 storage-lifecycle 会在 7 天宽限后当孤儿回收。
4. Registry 里 `ai-platform-*-app:preview-*` 的镜像按 Registry 清理规则处理，只删确认没有被任何活动 / 回滚 manifest 引用的 digest。
5. `dsh-enhanced` 合回 `main` 后，`docker-compose.preview.yml`、`scripts/preview-release.sh` 和本文可以一起删除。
