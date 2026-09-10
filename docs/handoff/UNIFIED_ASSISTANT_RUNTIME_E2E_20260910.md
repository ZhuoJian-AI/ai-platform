# 统一助手运行验收续接

## 已核实

- 基线为 `df2301c`，独立分支 `fix/unified-assistant-runtime-e2e-20260910`。
- `_build_tools` 构建全部获权注册表；`_consume_native` 在调用模型前通过 `partition_tool_specs` 分为常驻和延迟工具；原生循环在能力搜索成功后才加载命中的工具。
- 先前根据“本轮授权工具集合”推断全部工具都发给模型的判断不成立。该事件记录的是分组前目录，不能作为供应商请求证据。

## 本次修改

- 分组前事件明确标注包含待加载工具。
- 分组后增加首次模型请求实际工具名称与延迟数量事件。
- 动态加载事件记录新增工具和当前可见工具。
- 回归测试将事件中的可见工具与模拟网关实际收到的工具比较。

## 验证

- `pytest tests/test_native_assistant_core.py tests/test_assistant_tool_catalog.py -q`：21 passed。
- `ruff check app/agents/core/runner.py app/agents/core/native.py`：通过。
- 未部署本次修改；上述测试使用模拟模型，不代表真实供应商和浏览器端到端完成。

## 继续工作

- 核对模型能力测试失败状态持久化、MiMo 多轮调用和全部语音模式。
- 完成真实管理员与员工双端、OSS 文件交付、权限撤销、确认取消和跨视图接力测试。
- 平台完整目标尚未完成；禁止仅凭本次测试发布完成结论。
