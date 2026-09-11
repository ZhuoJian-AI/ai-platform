# 统一助手第一批修复发布

- 规则版本：c948cd2；目标仅 ai-platform.staging.zhuojianai.com / jwbpxybciypgdidyzu2ebrlr。
- source SHA：d248597e6e35437cdfe1dae9130b225eade5f0a6，PR #85 已合并。
- 范围：有界纠错、工具调用协议、可信 Artifact 版本、共享会话路由和确认工具说明。真实业务确认与专业 AI 尚待部署后验收，不宣称全计划完成。
- 新 backend digest：sha256:5a8c50afb6542877c8c12cf68528da693e142e8e34be4da2d8eeeea531565faf（parser/lifecycle/multimodal 复用）。
- 新 frontend digest：sha256:f32748f29969706317436692d0e065b66451305699ce96345a3d6203ec484c95。
- 上一版 backend：sha256:1059367699bd1ba2f0c5e5f88c6d8fd7967ecc8868758e629d41c434825bfa77；frontend：sha256:c61b5b62bd2e005a1563804ccd49276e3c7323a760f36416be4ef3fbbc3e4281。保留可回切，不清理。
- Registry HTTP 返回的 digest 已核实；应用镜像 OCI revision 为 source SHA。
- Compose 9 服务预检、真实环境变量预检通过，执行器共享令牌一致，Storage Gateway 配置非空。无待生效配置，自动部署关闭，无排队部署。
- 原生循环 39 项测试通过，复用先前 122 项定向证据；前端路由/Bridge/Artifact 测试、类型检查和构建通过；镜像内应用导入与确认描述检查通过。
- 本批无数据库迁移，无 OSS/CORS 配置变化，无业务服务器或外部 Skill 修改。
- 第一批部署 `g9y1f0ildohq6um8sgfa77k0` 成功，manifest `1bbcfcf1c72573a80681151776f158e9bc1e1354`；9 服务健康，运行镜像摘要与 OCI source 已逐项核对。
- 真实员工确认卡片验收通过：确认前查询无记录，点击后恰好创建一条测试厂商。首次清理漏传 expected_version，被子系统 422 拒绝；读取查询版本后删除成功，再查询零匹配。没有修改真实厂商。
- 专业 AI 实测 Task `81f08ddf-75d6-408c-82d1-9847cf413b96`：真实上传成功，主脑选择正确专业工具并重试，但执行器读取不存在的 `MultimodalJob.started_at` 而失败。测试图片已进入回收站。不能将此测试记为通过。
- 已修复上述字段错误，复用 `locked_at/locked_by/attempts`，以真实 ORM 对象替代掩盖缺陷的 SimpleNamespace；成功、失败清理和终态不重复执行共 8 项定向测试通过，Ruff 通过。
- 第二批 source `6873457aca03a7258289c455d3566ac038c35257`（PR #87），backend digest `sha256:a1a31affc37d13f6bc95fff47584b87af8565eb5ea12a740bdb8c187bf48793d`，Registry HTTP 核实；前端不变。manifest `b5384e7f61286853942f38d676d4d52053d856b1`（PR #88），部署 `specialist3ddd679c405cb03c` 已发起，最终状态和专业 AI 复测待补充。
- 尚未验收完成：总入口自然语言自动导航并接续 Action、专业 AI 完整最终回答、AI 编辑另存新文件及网页编辑退出。原先手工切换视图的共享会话证据不能替代自动导航闭环。

## 后续专业 AI 定位与修复

- 第二批部署成功、9 服务健康。复测发现前一次 started_at 异常留下两条 processing/attempts=0 的 E2E 任务，占用并发。仅取消 `eaa57ecc-85ae-4d52-99c2-735be610012a`、`ce246dcd-2c21-4000-a49f-3314f314f214`，均已核对员工和测试请求；前者仍有 inputCleanupPending，未宣称临时对象全部清理。
- 取消接口暴露另一个错误：flush 后 updated_at 过期，run_payload 同步读取触发 MissingGreenlet。已在 inline/cancel 路径显式 refresh，source `c4c74ef7a8ce1b68528930f194a1fcb4c2184013`，digest `sha256:274d02b79974b535a57ba382f17f8d0570ce3169d89ef19021166ab4fb2c1d90`。部署 `specialist014c4627e1d2bfd2` 成功，manifest `8601e426faabf6b0ff4b8ae63d060b74233b9e55`，9 服务健康，运行摘要/source 核实。
- Task `9a66f1f2-eb87-4942-8361-622407081468` 专业工具与视觉执行已 succeeded，但最终回答被 live-query guard 错误撤回。根因：上传报告分析被初始分类标记 query，完成阶段又强制要求数据库查询。
- 修复仅认可成功、completed 且具有结构化 draft 的专业分析；不计为数据库查询或业务修改回执。已经发生的业务查询失败和所有写操作完成门禁仍保留。24 项 runner/specialist 定向测试与 Ruff 通过。source `5df2b7dc719202e673493c3198dbecc833b8f3f1`，最终部署与 E2E 结果待补。
- 所有本轮上传的 E2E 图片均已移入工作空间回收站，未删除真实文件或业务附件。没有放宽并发、权限或版本校验。

## 本轮最终发布与通过证据

- 最终后端 source：`5df2b7dc719202e673493c3198dbecc833b8f3f1`；manifest：`2c2a540a2e45907d186a8bada90d658dd3981fce`（PR #92）。
- 最终后端 digest：`sha256:38b0543409bfdeb55362f4f74e81f2a3e9e08b01f2471109a301a7d025d5e2f3`；前端仍为第一批 `f32748f...484c95`，source `d248597...`。
- Coolify 部署：`specialist6d56d3511029adea`，2026-09-11 06:14:08 UTC finished；运行容器摘要和 OCI revision 均已核实，9 服务 healthy，公网 `/health` 返回 200。
- **专业 AI E2E 通过**：真实员工登录和 OSS 上传，专业工具执行成功，原 Task `d3c824b5-306c-4b95-8362-d4dc4cba7101` 最终回答包含正确款号 204A231、检验数量 100、缺陷数量 3；无 pageerror。测试 PNG 已移入回收站。本项不依赖本地静态覆盖，使用线上前后端。
- 业务确认闭环已通过，清理零匹配已单独核实；共享会话手工切换、刷新、返回主页的先前通过证据继续有效。
- 仍待后续：自然语言自动导航并接续业务目标的完整验收；AI 修改另存而非覆盖及网页编辑入口退出；媒体链路剩余验收；写操作未知结果的跨运行恢复；专业服务最终失败但辅助查询成功时，任务状态不得把辅助成功当目标完成；一条旧 E2E 专业临时输入的 pending cleanup。
- 本轮未重新运行管理员全量 CRUD，不将旧证据扩大为本轮全模块通过。未修改外部 Skill、子系统代码、数据库结构、其他服务栈或 OSS/CORS 配置。
