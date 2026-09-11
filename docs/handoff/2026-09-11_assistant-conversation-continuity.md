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

## 后续真实确认测试发现

- Task `38811f38-9186-4c78-9a9d-b1a9f0011762`：模型第一次查询传 `id:null` 失败，第二次省略该可选参数后真实查询成功。不要将这个已经恢复的参数错误作为修复目标。
- 模型未调用 create 工具，最终 mutation 完成守卫返回失败；未产生确认卡片。确认测试未通过，不能声称业务写入闭环完成。
- 已对真正配置 `approval=ask` 的工具补充确定性描述：调用先显示卡片、确认前不执行；未调整权限、参数 Schema 或绕过确认。
- 新增定向测试，`test_native_assistant_core.py` 共 39 passed；Ruff 与 TypeScript 通过。该描述修复尚待候选后端真实复测。
- 通用前端 Action 调用类型补充服务端已经支持的可选 `page_key`。诊断请求不带页面时返回 403，带已登记页面返回 200；这不是已证明的助手运行时鉴权故障。
- `e2e-assistant-confirmation-live.mjs` 的实际业务清理返回 passed，测试名称 `E2E-ASSISTANT-CONFIRM-1789104399862`；无残留厂商记录。测试中确认按钮定位已修正，但真正失败证据来自持久化运行记录，不只是定位超时。
- 已移除共享浏览器静态资源覆盖，停止本地 4176 静态服务。未改 CORS。
