# 统一 Task 浏览器回归扩展与失败证据

任务：PLATFORM-UNIFIED-ASSISTANT-RUNTIME-E2E-20260910。

## 本轮修改

- 扩展 `frontend/scripts/e2e-staging-core.mjs`：Excel 交付后打开同一个 Task 的总入口深链接，确认原用户消息和 Artifact 渲染，再点击企业导航回到页面侧栏，核对消息、文件版本及任务列表无新增。
- 生成测试增加等待按钮退出 loading，避免仅因首个 Artifact 出现便立即下载中间产物。
- 失败日志只输出页面路径、弹窗和文件卡片数量，以及下载文件扩展名/大小；不输出聊天正文、凭据或签名 URL。失败清理结果不再静默。

## 实际运行

独立 Chrome、真实管理员/员工表单、隔离 Context，运行时凭据且 E2E_MODEL_ALIAS 为空。未修改正式 API Key、部署配置或子系统。

在前一轮一次完整核心回归成功后，本轮重复运行发现不稳定性：

1. Excel 生成阶段 `getByRole('dialog').innerText()` 超时，尚未到新增跨视图测试。该次旧 finally 未打印清理详情，不能据此声称具体清理数量。
2. 再次运行出现 Artifact，但下载扩展名不是 XLSX，测试拒绝通过；失败清理返回 tasksDeleted=1、filesTrashed=1、failures=[]。当时未记录具体扩展名，不能断言是 TXT，也不能排除提前下载中间产物。
3. 增加完成等待后重跑，再次在生成阶段弹窗消失而失败；记录 dialogs=0、artifactSections=0，路径仍为 /alphabet/terminal。清理返回 tasksDeleted=1、filesTrashed=0、failures=[]。

每次管理员 17+4 导航、员工登录、18 个工作空间权限对照和 iframe 正文检查均先通过。失败集中于后续生成阶段，但原因尚未定位，不能归因为模型或路由中的任一项。

## 验证及待办

- `node --check scripts/e2e-staging-core.mjs`、`git diff --check` 通过。
- 新增跨视图断言尚未执行到，不计通过。一次旧脚本成功不足以证明稳定交付。
- 下一步捕获安全的视图状态与运行事件，定位弹窗消失原因；核对最终产物而非仅首个卡片，然后完成跨视图实际续问与文件引用复用。
- 未部署本地修复，整体目标继续保持未完成。
