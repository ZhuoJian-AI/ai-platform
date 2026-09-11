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
- 部署 ID、最终健康与真实业务复测结果待补充。
