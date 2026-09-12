# 待确认业务操作去重

普通 enterprise_action 调用在创建请求前，根据当前 Task 的服务端助手历史引用，查找同应用、租户、用户、Action、模块的未过期待确认请求。只比较最近 20 个引用；参数摘要、页面、预期版本全部一致时沿用原 requestId，继续通过 invoke_action 的角色、Manifest、参数和版本校验。模型换 toolCallId 不再必然新建同一待确认方案。无历史、不匹配、已结束或过期请求不参与复用。

不直接执行远端、不自动点击确认、不按关键词推测用户意图。主体在调用前刷新；原请求期间若已被确认/取消，现有调用服务返回原状态，不新建写入。历史缺少加密参数时跳过，不补造绑定。

验证：`python -m pytest --noconftest tests/test_assistant_action_recovery.py tests/test_action_unknown_outcome.py tests/test_action_reconciliation.py tests/test_enterprise_action_hardening.py -q`：143 passed。Ruff 与 diff 检查通过。新增测试检查匹配边界、SQL 隔离过滤、普通调用复用及权限拒绝；本批未跑真实数据库并发或真人业务恢复，不将 mock 测试冒充端到端。

限制：当前只合并同对话中的相同待确认方案；两条没有共同历史的新并发调用、已完成操作再次调用及多目标自动恢复仍需逻辑操作关联机制，未完成。合法再次操作不能被参数相同永久封锁。无数据库迁移、前端或对外契约变化。

状态：代码完成，尚未部署。部署规则版本 052b21a。待完成发布后补充 source、manifest、digest 和服务健康证据。
