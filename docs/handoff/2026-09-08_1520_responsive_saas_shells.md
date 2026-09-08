# SaaS 全端响应式适配

## Task

- 让管理员端、员工端、工作空间、应用外壳和业务小助手使用同一套前端组件，同时兼容电脑、平板、手机竖屏与手机横屏。
- 本次只修改前端；不修改后端 API、鉴权、模型调用、额度、数据库、域名或任何业务子系统。

## Changed behavior

- 管理员端与员工端在手机上使用受控抽屉导航，并支持遮罩、关闭按钮、Escape、浏览器返回、焦点约束、焦点归还和背景交互隔离。
- 工作空间在手机上改为“空间列表 → 文件区域”的同 DOM 两阶段导航；平板和桌面继续保留高密度文件管理布局。
- 应用外壳在窄屏保留应用、模块和业务小助手入口，次要操作进入“更多”；iframe 不因旋转、打开助手或断点变化而重建。
- 业务小助手在手机上全屏，处理动态视口、安全区、软键盘、长内容和输入草稿；平板与桌面保持自适应抽屉。
- 管理表单、Finder 弹窗、权限矩阵和表格采用连续响应式布局；复杂表格只在自身容器滚动，页面根节点不横向溢出。
- 增加统一断点 Hook、VisualViewport 高度同步和可重复运行的多浏览器响应式验收脚本。

## Verification

- `npm run build`: passed.
- `RESPONSIVE_ENGINES=chromium,webkit,firefox npm run test:responsive`: passed across 8 viewport sizes per engine, including real touch activation for emulated handsets, portrait/landscape rotation, workspace navigation, iframe identity preservation, full-screen assistant, focus/inert behavior, browser Back and visual screenshots.
- Existing frontend contract suites passed: business conversation, subsystem Bridge, workspace file UI, presentation, file links, file events, Office edit, CSV/document, admin session and login feedback.
- `git diff --check`: passed.
- `npm run lint` cannot start on the current baseline because the repository defines the script but does not install an `eslint` executable. No dependency was added in this frontend-only change.

## Decisions and risks

- Layout is shared responsive Web, not a second mobile application or duplicated mobile DOM.
- CSS controls continuous layout; JavaScript is limited to interaction state such as drawers, focus, inert and dynamic viewport height.
- The browser suite uses a deterministic mock subsystem solely to validate the SaaS iframe shell and Bridge-ready behavior; it does not claim that existing third-party subsystem pages are already responsive.

## Remaining work

- Integrate the latest `origin/main`, merge the source change and deploy only the SaaS frontend image through the current Registry-first deployment process.
- Record the previous/new frontend image digests and live staging smoke test in a separate release handoff.
