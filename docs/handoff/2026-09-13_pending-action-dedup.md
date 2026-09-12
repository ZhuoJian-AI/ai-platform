# 待确认业务操作去重

普通 enterprise_action 调用在创建请求前，根据当前 Task 的服务端助手历史引用，查找同应用、租户、用户、Action、模块的未过期待确认请求。只比较最近 20 个引用；参数摘要、页面、预期版本全部一致时沿用原 requestId，继续通过 invoke_action 的角色、Manifest、参数和版本校验。模型换 toolCallId 不再必然新建同一待确认方案。无历史、不匹配、已结束或过期请求不参与复用。

不直接执行远端、不自动点击确认、不按关键词推测用户意图。主体在调用前刷新；原请求期间若已被确认/取消，现有调用服务返回原状态，不新建写入。历史缺少加密参数时跳过，不补造绑定。

验证：`python -m pytest --noconftest tests/test_assistant_action_recovery.py tests/test_action_unknown_outcome.py tests/test_action_reconciliation.py tests/test_enterprise_action_hardening.py -q`：143 passed。Ruff 与 diff 检查通过。新增测试检查匹配边界、SQL 隔离过滤、普通调用复用及权限拒绝；本批未跑真实数据库并发或真人业务恢复，不将 mock 测试冒充端到端。

限制：当前只合并同对话中的相同待确认方案；两条没有共同历史的新并发调用、已完成操作再次调用及多目标自动恢复仍需逻辑操作关联机制，未完成。合法再次操作不能被参数相同永久封锁。无数据库迁移、前端或对外契约变化。

状态：2026-09-13 已部署 staging，部署规则版本 052b21a。

- 仓库：ZhuoJian-AI/ai-platform；域名 https://ai-platform.staging.zhuojianai.com；Coolify Application `jwbpxybciypgdidyzu2ebrlr`。
- source `566b70de832ff9d2638d133285217cf4736b523b`（PR #163）；manifest `df6c40069fa5c8973d247493a79e4c2ffc3a48ef`（PR #164）。
- backend/shared worker digest `sha256:58b54dd8640005b3d502ded34ae488859aec484ad51a80735ba0a2dedfbebbe7`；运行 backend digest 与 OCI source 均匹配。前端沿用 source `28dcfbd`，未改。
- Registry-first 镜像 compileall 与 Compose 校验 PASS；环境必填值及共享令牌一致性通过，无配置待提交、无并行部署。部署 `voicefix0250bc2e0ddb058e` finished；9 服务全部 healthy，公开 health 200。
- root 现有真实浏览器会话页面和 auth/me 200，本次页面加载无 JavaScript 异常。此为会话冒烟，不是员工操作恢复闭环。
- 无数据库迁移，不新增备份；OSS 链路未变，不重复上传验收。仅清理本批可重新生成的本地和 /tmp 构建归档、Dockerfile、构建目录；镜像、数据库及用户文件保留。
