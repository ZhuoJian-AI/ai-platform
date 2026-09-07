# 业务查询编译与历史页面上下文修复

## 负责人和任务

- 负责人：Codex
- 任务：`PLAT-BUSINESS-ORCHESTRATION-RELEASE-003`、`PLAT-BUSINESS-INTENT-DEEPSEEK-COMPAT-004`

## 已修改

- 当结构化查询包含 Action Schema 无法直接表达的筛选、排序或聚合，而 Action 提供字符串 `query` 参数时，SaaS 从当前轮服务端持有的原始用户请求编译自由文本查询；不再让执行模型反复猜测参数。
- 结构化字段仍优先按闭合 Schema 精确注入，`limit` 仍由服务端限制；没有可用自由文本参数时继续拒绝未映射条件，禁止静默扩大为全量查询。
- 业务 Task 保存页面上下文时，以 Manifest 校验后的应用、模块、页面键和页面名覆盖 Bridge 显示字段。
- 历史列表读取旧 Task 时，可从持久化的服务端 `business_turn_envelope` 恢复规范页面名，不需要数据库迁移。

## 已验证

- `python -m pytest tests/test_business_assistant_orchestration.py tests/test_workspace_presentation.py tests/test_llm_tool_choice_pure.py tests/test_dsh_bridge.py -q`：`49 passed`。
- `python -m ruff check app/agents/graph/nodes.py app/api/terminal.py tests/test_business_assistant_orchestration.py tests/test_workspace_presentation.py`：通过。
- `python -c "import app.main"`：通过。
- `git diff --check`：通过，仅有 Windows 换行提示。
- 完整后端测试的纯单元部分 `297 passed`；其余 `273 errors` 均在会话级测试数据库夹具连接本机 PostgreSQL 时发生 `ConnectionRefusedError`，本机未运行项目测试数据库，未进入对应测试正文。

## 未完成

- 构建不可变后端镜像、更新部署清单并部署 staging。
- 使用张三真实账号确认风险订单查询只执行一次 Action，并验证历史对话页面名、URL 恢复和 iframe 不重建。

## 决定与风险

- 自由文本回退不是关键词路由：结构化意图仍由模型输出并由 SaaS 校验，只有在已授权 Action 的 Schema 只能表达自然语言查询时，执行层才使用同一轮原始请求作为确定性参数。
- 本次不修改 Nginx、前端、数据库、模型计费、Skill、生产协同系统或域名。
