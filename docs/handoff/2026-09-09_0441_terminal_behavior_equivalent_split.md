# Terminal 行为等价拆分交接

## 范围

- 基线：`5bc98bf66421`
- 分支：`refactor/split-terminal-20260909`
- Worktree：`D:\Agent_Project\ai-platform-split-terminal-20260909`
- 仅拆分 `frontend/src/pages/terminal/Terminal.tsx`；未修改 API、鉴权、工作空间语义、数据库、Skill 或部署配置。

## 改动

- `Terminal.tsx`：4588 行降至 3342 行，保留页面编排、状态和用户交互入口。
- `TerminalAssistantMessage.tsx`：承接助手消息、执行状态、工具/Trace 卡片、Artifact 预览下载、朗读和 Markdown 文件链接渲染。
- `terminalConversationModel.ts`：承接 SSE 数据流消费、持久化消息恢复、附件/文件/Artifact 元数据解析和按轮删除的纯状态辅助。
- `terminalConversationTypes.ts`：集中聊天消息、Block、附件、文件引用和 Artifact 类型。
- `TerminalPanels.tsx`：承接资源、工作空间文件预览和记忆三个右侧面板。
- `test-subsystem-bridge.mjs`：流终止断言改为读取 SSE 实现的新模块；产品行为断言不变。

SSE 编排和业务小助手任务状态仍由 `Terminal.tsx` 持有；只抽取共享流解析器，避免在本次低风险重构中改变运行时序。

## 验证

- `npx tsc -b --pretty false`：通过。
- `npm run build`：通过（仅保留原有 Vite 大 chunk 与 `stream` externalize 提示）。
- `npm run test:presentation`：通过。
- `npm run test:file-links`：通过。
- `npm run test:file-events`：通过。
- `npm run test:csv-document`：通过。
- `npm run test:file-ui`：通过。
- `npm run test:subsystem-bridge`：通过。
- `npm run test:business-conversation`：通过。
- `npm run test:responsive`：通过，8 个 viewport。
- `npm run test:retired-frontend`：通过。
- `git diff --check`：通过。

`npm run lint` 无法启动：仓库定义了 `eslint .` 脚本，但当前 `package.json` 未声明/安装 `eslint`；本任务未为纯拆分擅自增加依赖。

## 合并注意

- 可 cherry-pick 本交接对应的产品提交。
- 若并行分支修改了 `Terminal.tsx`，优先保留其业务逻辑，再将对应职责放入上述模块；不要恢复已抽出的重复实现。
