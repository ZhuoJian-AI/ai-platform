# 录音输入发布批次

- Source PR #119，source SHA `eb2e8738465a55158bc5e4e0871772de6d7be75e`。
- 后端 Registry digest：`sha256:a388d24504e549fb01bfa5cefa693295fc32df4f8f0111f8fc21a7cdc3512e6c`。
- 前端 Registry digest：`sha256:a5da2816d7b0e0a531dbb64461885b2f648c63e352bb3d43826158d7f3c64283`。
- 复用已验证依赖层，后端复制 source app，前端使用该 source 对应生产构建产物；两个镜像 OCI revision 均为上述 source。Registry HEAD 返回对应 digest，后端镜像 compileall 通过。
- 前端 npm run build 通过；沿用 12 项聚焦测试和候选录音 E2E，详见 temporary-recording 交接。原 CORS 已恢复；不重复全量测试。
- 发布入口与真实环境变量预检 PASS，Coolify 自动部署关闭、无排队部署、无 Changes pending。规则版本 `c948cd2`。
- 无数据库迁移，保持 9 服务。不修改角色、业务子系统、外部 Skill、数据盘或其他项目。
- 回切后端：`sha256:0904ede643ad72c47b5da69ae2248e56b563ca57cad5227bd5a2ab5868e0a289`；前端：`sha256:76c1d46679f4a9db9a8873ffeaf1dc4e2803e70f0f4154be694e95cb72054285`。
- Manifest PR #120，manifest SHA `6e0f100d8b4c9eee9a401e6ae8fd29017951d83d`。
- Coolify 部署 `voicefixc4a292c4c91989f1` finished，无 Changes pending；9 服务 healthy，4 个后端消费者和前端使用新 digest，前后端 OCI revision 均与 source 一致；跨服务令牌一致且未输出值。
- 正式域名 `/health` 返回 200；本次成功与取消的候选录音任务临时引用均已由 worker 回收。
- 上线后 root 与 zhangsan 使用全新隔离浏览器上下文真实登录，管理员空间目录和员工文件视图通过，无 5xx。
- 线上 zhangsan 的 ASR/TTS 均返回 `permission_denied`；录音按钮 title 显示中文授权原因，点击未调用 getUserMedia，未修改角色。点击后的 toast 未被自动化捕获，不能声称点击即时反馈验收通过；后续聚焦核对这一体验问题。
- 线上未替 zhangsan 添加语音角色，因此本次 staging 不声称其录音成功。候选已有授权角色的浏览器 OSS→ASR→回填证据继续有效，不扩大权限来制造通过结果。
- 按需朗读、沉浸式模式、真人麦克风及 chouchou 真实会话仍未完成。
