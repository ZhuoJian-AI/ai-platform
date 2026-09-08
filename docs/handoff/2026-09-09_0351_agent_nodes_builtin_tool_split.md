# 原生智能体内置工具模块拆分

## 任务与边界

- 分支：`refactor/split-agent-nodes-20260909`
- 基线：`7a9228f`
- 仅拆分 `llm_router/backend/app/agents/graph/nodes.py` 中的内置工作空间、文件、Web、图片和多模态工具定义及执行辅助。
- 未修改 Team、Budget、ORM、数据库迁移、前端、Skill、部署或业务算法。

## 结果

- 新增 `app/agents/graph/builtin_tools.py`，承接内置工具目录、工作空间实时授权、文件输入输出校验、Artifact 记录、文件执行器调用及内置工具分发。
- `nodes.py` 从 6026 行降至 3531 行，减少 2495 行；新模块为 2590 行。
- `nodes.py` 保留原有常量和私有辅助的兼容导出，因此 Core、历史调用方及直接导入这些符号的测试不需要迁移。
- `get_deps` 和 `_fresh_user_principal` 保留运行时委托，确保已有测试注入和每次文件操作前重新加载权限的语义不变。
- 工具执行顺序、事件顺序、参数/结果校验、Artifact 完成判定和中文错误内容未改变。

## 验证

- 在独立 PostgreSQL 测试库 `ai_infra_test_nodes_split_20260909` 运行文件、Artifact、业务小助手、原生 Core、Manifest、应用上下文和企业导出相关测试：`224 passed in 64.78s`。
- `uv run python -m ruff check app/agents/graph/nodes.py app/agents/graph/builtin_tools.py`：通过。
- `uv run python -m compileall -q app/agents/graph/nodes.py app/agents/graph/builtin_tools.py`：通过。
- 兼容导出探针确认 20 个既有符号仍可从 `app.agents.graph.nodes` 导入。
- 完整套件曾在共享测试库运行到 `517 passed`，但该库残留已退役 `enterprise_application_tool_bindings` 外键，导致大量 `Base.metadata.drop_all` teardown 错误；切换全新测试库后，本机 PostgreSQL 服务被并行任务停止，无法完成第二次完整套件。上述 224 项隔离回归在服务停止前已全部通过。

## 后续协调

- 本分支原样保留了全部 14 处 `team_id=None`：其中 3 处随执行代码移动到 `builtin_tools.py`（当前约第 1728、1762、1803 行），其余 11 处仍在 `nodes.py`。父任务整合 Team 清理后应统一删除，不能在本提交中改变语义。
- 合并 Team 清理分支后需重跑本交接列出的 224 项测试，并用恢复后的独立 PostgreSQL 完成完整后端套件。
- 本拆分没有抽取 Manifest Action 执行器；现有企业 Action 逻辑仍在 `nodes.py`，避免在数据库/Team 清理并行期间扩大冲突面。
