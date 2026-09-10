# 当前后端全套真实 PostgreSQL 回归

任务：PLATFORM-UNIFIED-ASSISTANT-RUNTIME-E2E-20260910。

## 环境与隔离

- 本机 Docker Linux daemon 仍不可用。使用 SaaS 主机已有镜像创建本任务隔离网络和两个临时容器，不发布端口、不连接 staging 数据库、不挂载用户文件。后台容器明确覆盖 DATABASE_URL 与 TEST_DATABASE_URL，均指向新建 ai_infra_test。
- 源码为 Git 归档 `6329a90`，测试容器工作目录 `/repo/llm_router/backend`；复跑前仅同步下述测试断言修改。依赖使用当前已部署 backend 镜像，pytest/pytest-asyncio 只安装在临时测试容器，不进入生产镜像。
- 初次 PostgreSQL 512MB/384MB tmpfs 太小，OOM 且盘满：290 passed、10 setup errors，不算通过。核对容器退出后只替换该测试 PG，改用 2GB 限额、1.5GB tmpfs、32MB shared_buffers 与 64MB max_wal_size。

## 测试与修正

- 第二次：593 passed、1 failed、3 errors。三项迁移测试要求显式允许远端测试主机，确认隔离网络/数据库后设置 `MIGRATION_TEST_ALLOW_REMOTE=1`，未移除安全门禁。
- 唯一断言失败：模型验证实现已经使用 512 token，`test_mock_gateway_chat_vision_image_and_stream` 仍要求纯文本请求为 128。将该断言同步为 512，未更改产品行为。
- 最终命令：`docker exec -e MIGRATION_TEST_ALLOW_REMOTE=1 -w /repo/llm_router/backend ai-platform-e2e-backend-6329a90 python -m pytest tests -q --maxfail=10 --tb=short`。
- 最终结果：**597 passed in 100.91s**，exit 0。相关 Python Ruff 与 git diff --check 通过。

## 清理与边界

- 逐个验证本任务标签后删除两个临时容器及其临时数据，确认网络无容器后删除隔离网络；未删除 staging 数据、OSS、业务容器或镜像。
- 临时源码归档仍在 `/tmp/ai-platform-e2e-6329a90-2jlfbg/`，不含运行密钥；可用于后续候选验证准备。没有仍需轮询的测试进程。
- 这是完整仓库后端测试集合的结果，模型供应商/OSS 部分使用测试替身，不是实际 MiMo、阿里云、统一助手浏览器交付或发布通过。
- 仍需候选后端真实模型/文件交付、刷新恢复、角色撤销、间歇侧栏消失/504 调查及不可变镜像部署。未 push、merge 或 deploy。
