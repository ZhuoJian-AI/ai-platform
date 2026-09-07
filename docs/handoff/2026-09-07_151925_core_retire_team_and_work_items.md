# Team 与平台跨部门待办退役

- 执行者：Codex
- 任务：`PLAT-RETIRE-TEAM-001`
- 分支：`refactor/retire-team-work-items`

## 已完成

- 管理端和员工端组织树统一为“企业 → 部门 → 用户”，删除 Team 的列表、编辑、筛选与资源节点。
- 用户身份、SSO、Action、智能体、工作空间、模型路由和资源可见性不再使用 Team；新写入 Team 范围统一拒绝，旧 Team API 在兼容期返回中文 `410 Gone`。
- 页面、Action、工作空间和 AI 能力继续按用户绑定角色取并集；企业公共空间默认全员只读，`workspace.organization.manage` 或 `*` 可管理；部门共享空间的 `*` 仍不包含删除。
- 员工端删除“跨部门待办”；无目标应用的子系统事件仅记审计，有目标应用时继续进入安全投递 outbox。
- 增加迁移 `0069_retire_team_scope`：Team 成员转换为同名兼容角色，Team 资源改为角色范围，历史 Task/异步任务清空 `team_id`，Team 模型商和 API Key 停用，旧待办表删除。存在 Team 工作空间文件时迁移会拒绝执行，避免扩大文件可见范围。

## 验证

- `python -m pytest -q`：`549 passed in 420.33s`。
- 对所有改动 Python 文件执行 `python -m ruff check ...`：通过。
- `git diff --check`：通过。
- `tsc -b` 与 `vite build`：通过。
- 从空数据库升级到 `0068`，构造 Team 用户、Task 和 `multimodal_job` 后升级到 `0069`：三处 `team_id` 均为空、兼容角色已绑定、跨部门待办表已删除。
- staging 只读扫描：`0068_ai_quota_rollups`；1 个 Team、1 名成员、1 个 Team 工作空间且 0 个文件；13 条跨部门待办；1 个 Team 智能体、1 条 Team 长期记忆、1 个 Team 模型商和 1 把 Team API Key。

## 管理员迁移清单

- `production01` Team 下的 `deepseek` 模型商将在迁移中停用，不能自动扩大到生产部。
- `production01` Team 下的“爱法贝生产部”API Key 将被撤销，不能自动扩大到生产部。
- 原 Team 智能体“财务部-Wyz”和 Team 长期记忆转为同名兼容角色范围。
- 13 条平台跨部门待办随部署前整库备份保留，不迁移到其他子系统。

## 剩余发布步骤

- 合并 source commit、构建并推送 Backend/Frontend Registry 镜像、写入不可变 digest 后部署。
- 部署前创建并核验 PostgreSQL 整库备份；部署后核对 Schema revision、容器 digest、健康状态和真实账号 E2E。

## 决定与风险

- 本次是 expand/migrate 阶段，Team 表和兼容列暂时保留但不参与运行；稳定观察并确认零引用后再单独物理删除。
- 当前线上 Team 工作空间没有文件，因此没有文件 ACL 迁移阻断；若部署前复查出现文件，必须停止发布。
