# 已有 Action 请求参数绑定

invoke_action 复用请求 ID 时，之前只比较 Action、模块、页面、版本，遗漏业务 params。现在对仍保留加密参数的请求进行规范化哈希比较；参数不同返回中文 409，不返回旧确认卡片、不新建请求、不执行子系统操作。同参数（含不同字段顺序）继续复用原记录；原有实时角色检查仍在复用前执行。此处约束请求身份，不收紧模型工具 Schema。

验证：test_action_unknown_outcome.py、test_action_reconciliation.py、test_enterprise_action_hardening.py 共 109 passed，Ruff 通过。新增覆盖 pending/executing/failed 的同参数及改参数调用。未改变数据库、前端、模型配置或存储。

边界：已结束且已清理 params_encrypted 的旧请求不能由这项比较恢复参数绑定；跨轮新工具 ID 的逻辑操作去重及完整多目标恢复仍未实现。不能把此补丁宣传为完整幂等完成。

发布状态：代码及聚焦测试完成，待部署。上线证据后补。
