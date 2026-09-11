# 写操作未知结果：跨请求去重

- 仅修改 SaaS Action 执行服务，部署规则 c948cd2；不修改数据库表、子系统或 Skill。
- 写操作 ReadTimeout/WriteError、5xx、408、成功响应损坏等不能证明业务事务回滚。保留现有 `failed` 状态，在 result 写入 `executionOutcome=unknown`，保留加密参数，resolved_at 暂为空。
- ConnectError/ConnectTimeout/PoolTimeout 及明确 4xx 拒绝继续按普通失败处理；查询、导出不被未知写状态阻塞。
- 新 request_id 调用前，按组织、应用、当前员工、Action、模块查找未知记录，再比较参数、页面和预期版本。完全匹配时返回原请求号与未知回执，不新建确认卡、不发起第二次业务请求。
- 已在超时前创建的另一张确认卡在执行前也重查，防止走确认入口绕过检查。所有检查在现有权限检查之后；没有新增权限。
- 237 项相关测试通过，Ruff PASS。真实 PostgreSQL 临时库验证了跨会话持久化、JSONB 查询和用户/页面/参数隔离；只创建并删除本轮 e2e_unknown 随机库，无 staging 业务数据写入。
- 限制：本批不是完整事务协调器。进程退出且事务尚未提交、不同参数的语义重复、远端状态查询/人工核实后的安全解锁仍待实现；不自动断言成功，也不按超时自动放行。旧历史失败记录不反向猜测或批量改写。
- 未知状态的加密参数暂保留以核实，不将明文凭据或参数写入报告；无数据库结构迁移。旧镜像不具有这项新保护，回切时需特别注意未知记录仍需核实。

## 发布记录

- source `831001d8d3fa8f25bfe5e3017568a02c18039a68`（PR #111）。
- backend `sha256:43f7449110806eca49d8fd3aef766e8e76bf52a204e4f4ce9d9d86ed7d7f7709`；Registry 200，镜像源码哈希与本地相同。
- manifest `2e81c8bf0a85ba4b5948026f30d9e2e9ca3ec676`（PR #112）。
- Coolify `unknown54f67bf7cc810bef` 于 2026-09-11 08:15:18 UTC finished。九项服务 healthy，staging `/health` 200，运行 backend 的 digest/OCI revision 一致。
- Compose 与真实环境变量预检 PASS，无数据库结构迁移，无前端变化。本批以确定性故障注入与真实临时数据库验收，不冒充新增全量浏览器 E2E。
- 前一镜像 `sha256:eef81efc788cd2bf15ba0bfff1499cedbe9c1fdffbea71fc10da7ca07c0e824f` 保留；回切不删除未知记录或用户文件。
