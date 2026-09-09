# Embedding 能力退役部署交接

## 任务与边界

- 任务：`PLATFORM-RETIRE-RAG-SKILLS-20260909`
- 本提交只将已经测试、推送到 staging 本机 Registry 的 AI Platform 镜像摘要写入 Registry-first Compose。
- `aifabei-subsystem-builder` 是仓库外的子系统契约，本任务没有修改它的文件、版本、模板、Release 或 GitHub 仓库。
- 未修改业务子系统和其他服务器项目。

## 候选发布映射

- Source SHA：`12c9425ac5a897eb93fb2463782caa279bd14d05`
- Backend / Workspace Parser / Storage Lifecycle / Multimodal Worker：`sha256:c39897acf809843e69c04c1c672f4638b27a32530e7fbac78d58eeaf8f97f700`
- Frontend：`sha256:b57754e1279b31785a7ca4e6cb40492d806c33bff1294ee4da421e2571892623`
- Tool Executor 与 Workspace Preview 镜像不变。
- 上一版 Backend 回切摘要：`sha256:bad17a600eba22b06807c98c857ef985d73c079eb04e81a2ec05221c04bd8cd6`。

## Action 确认热修

- PR `#76` 修复员工端轮询过期 Action 确认时触发 `MissingGreenlet` 并返回 500 的问题。
- 后端全量测试 `501 passed`；企业应用测试 `29 passed`。
- 前端 12 组专项回归与生产构建通过；真实 staging E2E 在旧镜像上准确复现了该 500，并将在新摘要部署后重跑。

## 已验证

- `docker compose -f docker-compose.coolify.yml config --quiet`：通过。
- 部署规则 `validate_compose_entry.py`：`PASS`；9 个服务、9 个健康检查、image-only、不可变摘要、无公开数据库/缓存端口、无仓库 bind mount、Git blob 与 `HEAD` 一致。
- 摘要计数：旧 Backend 摘要 0，新 Backend 摘要 4，新 Frontend 摘要 1。
- `git diff --check`：通过。
- 仓库 Compose 聚焦测试受全局测试数据库 fixture 阻断：本机 `localhost:5434` 未运行，测试逻辑没有开始；这不是断言失败。

## Staging 部署结果

- Coolify 部署 ID：`dfk5gf2tcqxraftzluntbcyw`。
- 部署清单提交：`d2d7a7b9f5c448dfceb4e053e910faa9c355381a`。
- 部署状态：`finished`；9 个服务、9 个健康检查全部通过。
- Backend、Workspace Parser、Storage Lifecycle、Multimodal Worker 运行摘要均为
  `sha256:c39897acf809843e69c04c1c672f4638b27a32530e7fbac78d58eeaf8f97f700`，OCI revision
  与 Source SHA `12c9425ac5a897eb93fb2463782caa279bd14d05` 一致。
- Frontend 运行摘要保持为
  `sha256:b57754e1279b31785a7ca4e6cb40492d806c33bff1294ee4da421e2571892623`；本轮产品前端未变更。
- 数据库 revision：`0076_retire_rag_and_user_skills (head)`。
- OpenAPI 共 193 条路径；RAG、平台用户 Skill 和 Embedding 退役路径为 0。
- 退役环境变量为 0；Tool Executor 的服务间令牌指纹一致，未输出或落盘任何明文密钥。

## 真实双端验收结果

- 使用互相隔离的全新浏览器上下文完成管理员、员工真实账号密码登录，未伪造 Token 或注入 Cookie。
- 管理员错误密码中文提示、17 个可见保留入口、4 个隐藏直达入口、退役路由不可达：通过。
- 员工错误密码中文提示、核心导航、18 个有效工作空间及管理员预览—员工实时权限一致性：通过。
- 企业应用 iframe、一次性 SSO、Bridge 页面上下文：通过。
- 业务助手在健康对话模型下完成真实 `Excel` 交付：Manifest Action、XLSX 生成、工作空间提交、Artifact 卡片、下载、OOXML 包结构、当前版本、SHA-256 和表格预览均通过。
- 测试对话已软删除，测试文件已进入回收站；临时模型可见范围已恢复原值。
- 员工和管理员均通过界面退出，退出接口返回 204，会话撤销通过。
- 全程未出现未解释的 5xx、空白页、无限加载或 JavaScript 异常。

## 验收中发现并处理的问题

- DeepSeek 当前上游账户返回 HTTP 402 `Insufficient Balance`。这是模型供应商账户状态，不是业务助手、Artifact 或权限链路故障；测试显式使用已验证健康的阿里云百炼对话模型完成真实交付。
- 初版 E2E 脚本把 Ant Design Select 的隐藏无障碍选项当作可点击选项，已改为定位实际可见选项。
- E2E 临时模型授权通过现有管理员 API 完成并在 `finally` 恢复；CSRF 沿用当前会话 Cookie，避免刷新令牌导致退出请求被误判为 403。

## 决策

- 采用 Registry-first；Coolify 只拉取不可变镜像，不在 staging 现场构建。
- 数据库已处于 `0076_retire_rag_and_user_skills`，本次摘要固定不新增迁移。
- 部署规则版本：`zhuojian-server-deploy@c948cd2`。
