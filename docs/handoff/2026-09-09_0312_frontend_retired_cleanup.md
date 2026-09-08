# 前端退役链路清理与明确 404

## 负责人和任务

- 负责人：`@codex-frontend-retired-cleanup`
- 任务：`FRONTEND-RETIRED-CLEANUP-20260909`
- 基线：`b672b79`
- 工作分支：`refactor/frontend-retired-cleanup-20260909`
- 范围仅限 `frontend/`、任务登记和本交接记录；未修改后端、数据库迁移、部署或 `aifabei-subsystem-builder`。

## 修改行为

- 删除终端的 Skills Pack 导出按钮、客户端方法和 `/skills-pack/export` 前端调用。
- 删除企业应用旧 `tool_endpoint` / `data_interface` / Skill 绑定类型、只读迁移表格和“连续七天观察”文案；应用详情改为直接展示已声明、已审核的 Manifest Action。
- 删除业务助手的 Ontology/Data Interface 进度类型、退役 Team 字段和 WebOffice 在线协作编辑冲突文案；保留用户上传 Skill、工作空间、RAG、Memory、Manifest Action 和 WebOffice 只读预览。
- 管理员未知路径、企业员工终端未知路径和通用员工终端未知路径统一显示中文 `404 页面不存在`，不再静默重定向。
- 将 Playwright 从生产依赖移到开发依赖，生产安装不再携带浏览器测试框架。
- 增加前端退役能力守卫测试，防止旧入口、类型和文案回流，同时确认保留能力仍存在。

## 验证

- `npx tsc -b --pretty false`：通过。
- `npm run test:presentation`：通过。
- `npm run test:file-links`：通过。
- `npm run test:file-events`：通过。
- `npm run test:csv-document`：通过。
- `npm run test:business-conversation`：通过。
- `npm run test:admin-session`：通过。
- `npm run test:login-feedback`：通过。
- `npm run test:subsystem-bridge`：通过。
- `npm run test:admin-quota`：通过。
- `npm run test:retired-frontend`：通过。
- `npm run test:file-ui`：通过（本地 Chromium）。
- `npm run build`：通过，Vite 生产构建成功。
- `npm run test:responsive`：通过，Chromium 共 8 个视口。
- `npm ls playwright --omit=dev`：生产依赖树中无 Playwright。
- `npm ls playwright --include=dev`：开发依赖为 `playwright@1.61.1`。
- `git diff --check`：通过。

## 未完成工作

- 未登录线上、未进行真实管理员/员工 E2E、未推送分支、未合并、未构建镜像、未部署；这些由主任务在吸收该提交后完成。
- `npm run lint` 无法启动：仓库存在 lint 脚本，但未安装 ESLint 且没有 ESLint 配置。这是基线已有的前端工具缺口，本次没有为了退役清理扩大依赖范围。

## 风险与决策

- `/org/roles`、`/enterprise-apps/navigation`、`/enterprise-apps/assistant` 和 `/org/voices` 虽未出现在主导航中，但仍承载保留功能，因此没有删除。
- WebOffice SDK、预览会话和只读“交互预览”继续保留；只删除在线协作编辑相关字段和提示。
- 企业应用 Overview 接口继续用于最近调用记录；能力数量和列表改以 Manifest Action 查询为唯一前端来源。
- 管理员和员工端的通配 404 只处理未知子路径；既有登录、文件深链和任务深链路由保持原顺序。
