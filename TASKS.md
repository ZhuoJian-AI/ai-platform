# Active tasks

## PLATFORM-VERIFIED-RELEASE-20260911 (@codex)

- [ ] 仅移植已验证的工作空间、中文错误、下载及非流式事件修复。
- [ ] 复用既有测试证据，完成发布预检、不可变镜像和 staging 健康核验。
- [ ] 不合并未验收的助手链路，不修改业务子系统或外部 Skill。

## PLATFORM-RETIRE-RAG-SKILLS-20260909 (@codex)

- [ ] 删除知识库及全部 RAG 产品、运行时、接口、数据表、向量依赖和 Embedding 模型能力，保留工作空间解析器。
- [ ] 删除平台用户 Skill 上传、安装、执行、接口、数据表与任意代码 Runner；将 `skill-runner` 收口为受控 `tool-executor`。
- [ ] 将自定义智能体简化为文本角色定义，并继承个人助手的实时模型、工作空间、文件、Web、多模态和长期记忆能力。
- [ ] 完成迁移副本演练、空库基线、后端/前端/Compose/OpenAPI 测试及 staging 双端真实回归。
- [ ] 不修改 `aifabei-subsystem-builder`、业务子系统或其他服务器项目。
