# 总入口自动导航修复

- 目标仅 AI Platform staging，部署规则 c948cd2；无数据库、OSS 配置或子系统变更。
- 原线上 Task ce6d00be-8bde-4d98-82c9-b92ba4136b46 已成功调用 enterprise_navigate 并持久化 ui_intent，但浏览器未跳转，不能将工具回执当用户已看到页面。
- 前端 SSE 改为调用最新事件处理器，避免长连接捕获请求开始时的空应用目录及陈旧上下文。
- 候选前端 + 真实线上登录/API/子系统验收通过：Task dc47eb79-5e06-442f-8d50-cb034e75e884 从总入口自然语言定位款号资料中心并自动跳转，URL 保留同一 conversation，真实 Action 查询成功且原 Task 有回答。没有修改业务数据。
- 当前查询返回图片类别统计（4 份），不返回逐张图片明细；未宣称已展示图片文件。
- 前端类型检查/生产构建、路由、Bridge、Artifact 定向测试通过。新增脚本默认使用线上前端，E2E_CANDIDATE=1 才覆盖本地构建静态资源。
- 部署摘要与最终线上回归待补；AI 编辑另存、网页编辑退出及其他未完成项不属于本次通过证据。

## 已部署与线上回归

- 实现 PR #94；前端 source `b07f7f24071067d149c3a506c7afac88bb280a8a`。
- 所有候选 dist 文件与服务器发布目录逐文件 SHA-256 核对通过；Registry HTTP 核实 digest `sha256:792fdd1c480bccf5aaaed752b1163227f7e05d7f2432f58424baba0f5e9d7367`。
- manifest `b9deb58b1b0167d481c5fcc4c2150fcc1104fa7d`（PR #95），Coolify 部署 `navigationa96a14c2cf22d3b2` 于 2026-09-11 06:35:58 UTC finished。运行前端 digest/source 一致，9 服务 healthy，公网 /health 200。Compose 与实际环境变量预检均通过。
- 后端维持 `38b0543409bfdeb55362f4f74e81f2a3e9e08b01f2471109a301a7d025d5e2f3`，无数据库迁移或 OSS/CORS 修改。前端回切 digest `f32748f29969706317436692d0e065b66451305699ce96345a3d6203ec484c95` 保留。
- 线上真实员工 Playwright 通过（未覆盖本地静态资源）：Task `d4c04c61-06fa-4488-bc32-3e9300a222ec` 从总入口自然请求自动进入款号页面，URL conversation 保持同一 Task，真实查询成功，侧栏可见 204A231，最终状态 success，无 pageerror；只读操作，无业务数据修改。
- 该验证不表示图片明细交付已完成：Action 只有分类数量，没有单张图片标识或预览地址。模型仍有重复查询及冗长回复，记录为待优化，不为一次最终成功重写模型参数约束。
- 下批已定位但未修改：`BrowserDrawer.tsx` 仍有文本/CSV 网页编辑；`builtin_tools.py` 的目标文件编辑仍调用 replace_file_artifact。需分别移除手工网页编辑、落实 AI 修改另存新文件，并覆盖原件不变和幂等。
