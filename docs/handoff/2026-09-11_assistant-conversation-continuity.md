# 统一助手会话接续修复

## 范围与状态

接续 Draft PR #85，仅修改 AI Platform 前端。未修改 Skill、子系统、数据库或 OSS 配置；本批未合并、未部署。

## 修复

- 应用路由从 conversation 恢复 Task，不因路径没有 taskId 清空会话。
- 导航保留同一 Task；流回调通过 ref 获取当前 Task，避免捕获创建前的空值。
- 历史入口不再因最初 application_id 强制切到独立业务视图。
- 同一个 Task 新增消息后更新总入口，且不覆盖正在输出的全局 SSE 缓冲。

## 验证

- `node scripts/test-assistant-conversation-route.mjs`：通过。
- `node scripts/test-terminal-artifacts.mjs`：通过。
- `node scripts/test-subsystem-bridge.mjs`：通过。
- `npx tsc --noEmit`、`npx vite build`：通过，保留既有大包警告。
- `scripts/e2e-unified-assistant-continuity.mjs`：独立 headless Chrome，真实员工登录；仅使用候选静态前端，API、SSO、子系统全部使用真实 staging。
- Task `0f8ae437-f399-4c01-b23f-6d3e4057e83f`：总入口历史 → 真实生产协同 → 侧栏同一回复 → 刷新同一 Task，通过。
- 侧栏真实生成 E2E-CONTINUITY 回复；修正测试关闭按钮和折叠导航定位后，最终一轮复用该回复，验证返回总入口仍可见，通过。复用模式不是再次调用模型的证据。
- 浏览器 pageerror 为空。未新建或修改业务记录；验收消息保留在已有 E2E 对话供追溯。

## 尚未覆盖

真实业务写入确认卡片、专业 AI 组合、文件另存和媒体验收仍待继续。不能把此会话接续结果表述为全部计划完成。
