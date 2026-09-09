# Embedding 能力退役部署交接

## 任务与边界

- 任务：`PLATFORM-RETIRE-RAG-SKILLS-20260909`
- 本提交只将已经测试、推送到 staging 本机 Registry 的 AI Platform 镜像摘要写入 Registry-first Compose。
- `aifabei-subsystem-builder` 是仓库外的子系统契约，本任务没有修改它的文件、版本、模板、Release 或 GitHub 仓库。
- 未修改业务子系统和其他服务器项目。

## 候选发布映射

- Source SHA：`1cbb6883cb1cb7d3ff9aa533149fdfb0477ef63a`
- Backend / Workspace Parser / Storage Lifecycle / Multimodal Worker：`sha256:bad17a600eba22b06807c98c857ef985d73c079eb04e81a2ec05221c04bd8cd6`
- Frontend：`sha256:b57754e1279b31785a7ca4e6cb40492d806c33bff1294ee4da421e2571892623`
- Tool Executor 与 Workspace Preview 镜像不变。

## 已验证

- `docker compose -f docker-compose.coolify.yml config --quiet`：通过。
- 部署规则 `validate_compose_entry.py`：`PASS`；9 个服务、9 个健康检查、image-only、不可变摘要、无公开数据库/缓存端口、无仓库 bind mount、Git blob 与 `HEAD` 一致。
- 摘要计数：旧 Backend 摘要 0，新 Backend 摘要 4，新 Frontend 摘要 1。
- `git diff --check`：通过。
- 仓库 Compose 聚焦测试受全局测试数据库 fixture 阻断：本机 `localhost:5434` 未运行，测试逻辑没有开始；这不是断言失败。

## 待完成

- 合并本部署清单后由 Coolify 部署 staging。
- 核对 9 个容器健康、运行镜像摘要、Source SHA、数据库 revision、OpenAPI 与退役路由。
- 使用隔离浏览器上下文完成 `root` 管理员和 `zhangsan` 员工的真实 staging 回归，再在本交接中补写部署 ID 与最终结论。

## 决策

- 采用 Registry-first；Coolify 只拉取不可变镜像，不在 staging 现场构建。
- 数据库已处于 `0076_retire_rag_and_user_skills`，本次摘要固定不新增迁移。
- 部署规则版本：`zhuojian-server-deploy@c948cd2`。
