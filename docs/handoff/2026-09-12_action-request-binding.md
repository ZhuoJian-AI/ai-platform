# 已有 Action 请求参数绑定

invoke_action 复用请求 ID 时，之前只比较 Action、模块、页面、版本，遗漏业务 params。现在对仍保留加密参数的请求进行规范化哈希比较；参数不同返回中文 409，不返回旧确认卡片、不新建请求、不执行子系统操作。同参数（含不同字段顺序）继续复用原记录；原有实时角色检查仍在复用前执行。此处约束请求身份，不收紧模型工具 Schema。

验证：test_action_unknown_outcome.py、test_action_reconciliation.py、test_enterprise_action_hardening.py 共 109 passed，Ruff 通过。新增覆盖 pending/executing/failed 的同参数及改参数调用。未改变数据库、前端、模型配置或存储。

边界：已结束且已清理 params_encrypted 的旧请求不能由这项比较恢复参数绑定；跨轮新工具 ID 的逻辑操作去重及完整多目标恢复仍未实现。不能把此补丁宣传为完整幂等完成。

后续实施要点：现有 request_id 由 task/client_request_id/tool_call_id 派生，不是跨轮稳定的逻辑操作标识。下一批需要持久化同一操作的 Task 归属与不可变参数绑定，恢复时引用原操作；新方案需新确认。不得直接删除 tool_call_id 或用相同参数永久去重。已完成且清理参数的旧记录不能凭猜测回填绑定，必须保留明确的历史兼容边界。

发布状态：已部署 staging。源码 PR #154，source `5d2d1fba6c85dfe3bafb994f9e8ccfbfc1fe74f0`；backend/共享 worker digest `sha256:fa3ceb0f71a977e6a032302b1d9a85191ccac4877bc94d15bb196b297dbba12f`；manifest PR #155、`75e470c9e86bb839790beab553d52d5a87ec5c07`；Coolify `voicefix6684cdd8383dd071` finished，无待发布配置。

运行 backend digest 与 OCI source 匹配；前端仍为 source 28dcfbd、digest `sha256:23e69fe1c4e1e1fab64050502bf77630e6b7f6b98a0fe568b683e6759cfbbf9d`。Compose 校验 PASS，registry-image，无源码构建及仓库 bind mount，数据库不公开端口。9 服务 healthy，必填运行值与共享令牌检查通过。公网 /health 200，root 现有真实浏览器会话刷新及 auth/me 200。未新增真实员工业务写入测试。

无迁移、不需数据库备份；未改 OSS，不重复存储验收。临时构建文件已清理，旧镜像和业务数据保留。部署规则 c948cd2。

仓库：https://github.com/ZhuoJian-AI/ai-platform；域名：https://ai-platform.staging.zhuojianai.com；Coolify：https://coolify.zhuojianai.com，Application jwbpxybciypgdidyzu2ebrlr，Registry-first 手动触发。
