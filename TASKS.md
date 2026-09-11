# Active tasks

## PLATFORM-ASSISTANT-COMPLETION-20260911 (@codex)

- [ ] 完成统一会话与真实业务确认闭环，专业 AI 返回主脑。
- [ ] 允许三次纠正调用，限制重复错误，以任务完成验收。
- [ ] 收尾候选文件与媒体修复，AI 编辑另存，移除网页编辑。
- [ ] 只做受影响链路验收，分批发布 staging，不修改外部 Skill 或业务服务器。

## PLATFORM-RETIRE-RAG-SKILLS-20260909 (@codex)

- [ ] 删除知识库及全部 RAG 产品、运行时、接口、数据表、向量依赖和 Embedding 模型能力，保留工作空间解析器。
- [ ] 删除平台用户 Skill 上传、安装、执行、接口、数据表与任意代码 Runner；将 `skill-runner` 收口为受控 `tool-executor`。
- [ ] 将自定义智能体简化为文本角色定义，并继承个人助手的实时模型、工作空间、文件、Web、多模态和长期记忆能力。
- [ ] 完成迁移副本演练、空库基线、后端/前端/Compose/OpenAPI 测试及 staging 双端真实回归。
- [ ] 不修改 `aifabei-subsystem-builder`、业务子系统或其他服务器项目。
