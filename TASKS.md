# Active tasks

## PLATFORM-UNIFIED-ASSISTANT-RUNTIME-E2E-20260910 (@codex)

- [ ] 核对模型实际可见工具与延迟注册表，补齐可验证的运行事件。
- [ ] 修复真实模型能力测试和统一助手端到端发现的问题。
- [ ] 完成管理员、员工、模型工具和工作空间产物验收后发布 staging。
- [ ] 不修改外部 Skill、业务系统、退役功能或其他任务的未提交文件。

## PLATFORM-RETIRE-RAG-SKILLS-20260909 (@codex)

- [ ] 删除知识库及全部 RAG 产品、运行时、接口、数据表、向量依赖和 Embedding 模型能力，保留工作空间解析器。
- [ ] 删除平台用户 Skill 上传、安装、执行、接口、数据表与任意代码 Runner；将 `skill-runner` 收口为受控 `tool-executor`。
- [ ] 将自定义智能体简化为文本角色定义，并继承个人助手的实时模型、工作空间、文件、Web、多模态和长期记忆能力。
- [ ] 完成迁移副本演练、空库基线、后端/前端/Compose/OpenAPI 测试及 staging 双端真实回归。
- [ ] 不修改 `aifabei-subsystem-builder`、业务子系统或其他服务器项目。
