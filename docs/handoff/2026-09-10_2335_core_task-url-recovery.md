# 同一 Task 实际续问通过，补齐刷新地址

任务：PLATFORM-UNIFIED-ASSISTANT-RUNTIME-E2E-20260910。

## 本轮实际证据

- 旧执行 handle 92753 最终 exit 1：侧栏 locator 超时，清理 DELETE 返回 HTTP 504。随后只读核对测试 Task `b5b78812-0fa0-4a07-a244-8be65935ec80` 的 `deleted_at` 已设置，因此清理响应超时但数据库已软删除；不得仅凭 504 判断业务没有提交。
- SaaS 主栈 9 服务 healthy，检查时 PostgreSQL 无阻塞事务，后台日志最近 45 分钟未发现选定的超时/连接池/死锁异常。这些只代表检查时状态，不能解释之前的间歇故障。
- 新执行 handle 93472 使用独立 Chrome、真实 root/zhangsan 表单登录，`E2E_EXPLICIT_XLSX=1 node scripts/e2e-staging-core.mjs` exit 0。下载 XLSX 6854 字节、预览 ready；总入口实际续问“刚才文件是什么格式”得到回复，再通过 UI 返回子系统侧栏，续问与原 Artifact 均存在，Task 不增加。
- 新测试 Task `ff6aa415-d7aa-4398-a556-e1713adb5af0` 清理报告对话 1、回收文件 1，双端退出成功；只读数据库核对 Task 已软删除。
- 该成功运行发生在新增刷新断言之前，不证明刷新已通过，更不证明间歇侧栏消失/504 已修好。

## 本地修改

- `onAskAI` 新建侧栏 Task 后立即把 `conversation` ID 写入应用地址，保留页面上下文。原通用路由同步守卫会在 route Task 与新选中 Task 不同时返回，实际多轮观察地址均没有 conversation，无法依靠该守卫保存新会话。
- 增加源代码契约断言，并扩大 E2E：在切换总入口前先核对 conversation、真实刷新、重新打开侧栏并核对原消息和 Artifact。
- `node scripts/test-subsystem-bridge.mjs` 通过；`node --check scripts/e2e-staging-core.mjs` 通过；`npm run build` 通过（现有大 chunk、stream externalized 警告保留）；`git diff --check` 通过。

## 未完成

- 新的刷新断言尚未在包含本地修复的浏览器环境运行。
- 侧栏消失与 504 根因仍未证实，不能把本地 URL 修复冒充其修复。
- MiMo/阿里云完整能力交付、权限撤销、全量数据库测试与不可变镜像发布仍未完成。本轮没有 push、merge 或 deploy，没有修改 Skill、业务子系统或线上配置。
- 本轮所有进程均已结束，无需要继续轮询的 handle。部署规则重新获取为 c948cd2。
