# 录音输入发布批次

- Source PR #119，source SHA `eb2e8738465a55158bc5e4e0871772de6d7be75e`。
- 后端 Registry digest：`sha256:a388d24504e549fb01bfa5cefa693295fc32df4f8f0111f8fc21a7cdc3512e6c`。
- 前端 Registry digest：`sha256:a5da2816d7b0e0a531dbb64461885b2f648c63e352bb3d43826158d7f3c64283`。
- 复用已验证依赖层，后端复制 source app，前端使用该 source 对应生产构建产物；两个镜像 OCI revision 均为上述 source。Registry HEAD 返回对应 digest，后端镜像 compileall 通过。
- 前端 npm run build 通过；沿用 12 项聚焦测试和候选录音 E2E，详见 temporary-recording 交接。原 CORS 已恢复；不重复全量测试。
- 发布入口与真实环境变量预检 PASS，Coolify 自动部署关闭、无排队部署、无 Changes pending。规则版本 `c948cd2`。
- 无数据库迁移，保持 9 服务。不修改角色、业务子系统、外部 Skill、数据盘或其他项目。
- 回切后端：`sha256:0904ede643ad72c47b5da69ae2248e56b563ca57cad5227bd5a2ab5868e0a289`；前端：`sha256:76c1d46679f4a9db9a8873ffeaf1dc4e2803e70f0f4154be694e95cb72054285`。
- 当前记录为镜像就绪，实际部署与上线回归结果待补充；不能将本记录当作已上线证据。
- 按需朗读、沉浸式模式、真人麦克风及 chouchou 真实会话仍未完成。
