# 业务助手意图协议字段规范化

## 负责人和任务

- 负责人：Codex
- 任务：`PLAT-BUSINESS-INTENT-DEEPSEEK-COMPAT-004`

## 已修改

- 结构化控制器只负责选择 `intent`、目标和查询条件；SaaS 根据选定意图规范化实时数据、确认和输出类型等协议字段。
- 修改确认仍由服务端读取获权 Action 元数据决定，模型不能降低或扩大确认要求。
- Pydantic 校验失败时只反馈字段路径与错误类型，不回显模型输入，使兼容重试能修正具体字段。

## 已验证

- `python -m pytest tests/test_business_assistant_orchestration.py tests/test_llm_tool_choice_pure.py tests/test_dsh_bridge.py -q`：`37 passed`。
- `python -m ruff check app/services/business_assistant_orchestration.py tests/test_business_assistant_orchestration.py`：通过。
- `git diff --check`：通过，仅有 Windows 换行提示。

## 未完成

- 需构建不可变后端镜像、更新部署清单并部署 staging。
- 需使用张三真实账号完成页面说明、实时查询、Excel Artifact、对话隔离和 URL 恢复回归。

## 决定与风险

- 本次不加入关键词路由，不修改 Nginx、域名、数据库、模型计费或管理员登录。
- 仍严格校验模型选择的意图、目标、筛选条件与服务端授权范围；只有由协议确定的派生字段会被规范化。
