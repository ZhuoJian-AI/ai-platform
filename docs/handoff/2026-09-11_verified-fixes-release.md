# 已验证修复的独立发布

## 范围

从 df2301c 单独移植 9903007、4d3e3ce、1ebfa8f、eae003e、45bb6bd、6e41072 的代码及测试，不合并原候选分支。

- 工作空间共享读取只由角色授权，企业读取可独立配置；个人所有权不变。
- 中文会话和无权提示，文件ID拒绝继续隐藏为404。
- 拒绝绝对/非相对路径并向模型返回可纠正错误。
- 文件卡片下载按钮可访问名称。
- 非流式工具、Artifact及完成事件持久化。

不含视觉重构、模型能力扩展、统一会话追加改动、Excel编辑Artifact修复或网页编辑删除；不修改数据库结构、角色数据、外部Skill或业务子系统。

## 既有验证证据

原候选分支已完成：角色授予/撤销真实双端验证、中文拒绝、OSS浏览器上传下载、非流式事件重放、文件UI测试及前端构建。最终完整候选4584092后端702 passed/119.52s；此数字是候选全集，不冒充本次精选组合重跑结果。

按用户明确要求不重复跑测试；本次只做差异/依赖预检、构建制品和部署后健康检查。部署规则版本c948cd2。

## 发布状态

发布前确认Coolify目标jwbpxybciypgdidyzu2ebrlr对应ZhuoJian-AI/ai-platform main，自动部署关闭，当前完成部署q3vogb5vy63j2vpgj5vbdocc / df2301c，无需改变其他项目。

源码 PR #82 已合并，source SHA：388fafdc590ca7c3314ca5bdfa091025488bb2f9。

Registry 已确认新镜像：

- backend（含 parser/lifecycle/multimodal worker）：sha256:1059367699bd1ba2f0c5e5f88c6d8fd7967ecc8868758e629d41c434825bfa77
- frontend：sha256:c61b5b62bd2e005a1563804ccd49276e3c7323a760f36416be4ef3fbbc3e4281

回切镜像（保留，不清理）：

- backend：sha256:039960583b79b409e04960623e1ff91e5835185120dd5fe1d18c23c0dbd1ee10
- frontend：sha256:280874e48250ce9a43d0767a2cf6fecae8675058bd51ae1eac756d2cc1e1a01d

前端生产构建成功；后端复用既有依赖镜像，清空 /app 后复制此源码；依赖与迁移无变化。真实环境变量校验 PASS，backend/executor 令牌一致，无待生效配置。存储仍为 Storage Gateway / OSS，两个 STORAGE 变量存在；本次不修改存储链路、上传限制、CORS 或用户文件，不重复 OSS 上传验收。

最终部署及健康结果待发布完成后补充。
