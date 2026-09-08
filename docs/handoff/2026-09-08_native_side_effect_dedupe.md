# 原生 Assistant Core 副作用去重热修

## 任务

李四灰度端到端导出发现：同一模型回合返回两个同名、同参的 `business_export_to_workspace_file` 调用时，原生执行循环会分别执行，导致一次请求产生两份 Excel Artifact。

## 修改行为

- 原生执行循环以“工具名 + 服务端校验后的规范参数”为签名，缓存本次运行中成功的非并发安全工具结果。
- 后续相同副作用调用不再进入执行器，复用首次成功结果，并记录 `duplicate_side_effect_reused` 策略事件。
- 每个模型 `tool_call_id` 仍获得对应的工具结果，保证 OpenAI/Anthropic 工具消息协议完整。
- 只对 `concurrency_safe=false`（未声明时按非并发安全处理）的工具启用跨步骤去重；只读查询仍可按业务需要重复执行。

## 验证

- `python -m pytest tests/test_native_assistant_core.py -q`：5 passed。
- `python -m pytest tests/test_native_assistant_core.py tests/test_dsh_approval.py tests/test_dsh_policy.py -q`：42 passed。
- `python -m ruff check app/agents/core/native.py tests/test_native_assistant_core.py`：通过。
- `git diff --check`：通过。

## 发布与风险

- 该热修不修改数据库、权限、Workspace、Skill、Manifest 或业务子系统。
- 发布时只重建并替换 Backend 系列镜像；Frontend 镜像保持不变。
- 先继续保持 `ASSISTANT_ENGINE=dsh`，只让李四进入 native 灰度；重复导出端到端验证通过后，才能扩大原生引擎范围。
- Connector 的七天无调用门禁仍未满足，不执行物理删除。
