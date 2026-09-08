# AI Platform

面向企业的统一 AI 底座。平台把模型供应商、员工权限、工作空间文件和业务系统 Action 收口到同一套 Assistant Core 中。

## 保留的产品能力

- 模型路由：OpenAI/Anthropic 兼容接口、LLM、Embedding、多模态、图像和音频能力。
- AI 助手：个人助手、业务小助手和自定义智能体共用 Task、Message、Run、Event、Artifact 与 SSE。
- 文件与知识：个人/企业/部门工作空间、文件版本、OSS、预览、下载、Skill Runner、知识库、RAG、Web 和记忆。
- 企业接入：Bridge、Manifest、页面与 Action 授权、Event、SSO、Runtime 与 ECS Publisher。
- 管理治理：企业、部门、员工、角色、权限、配额、审计、安全策略和轻量监控。

## Assistant Core

```text
统一 Assistant Core
├─ 模型路由与工具循环
├─ 工作空间文件执行器与 Artifact
├─ RAG / Web / 多模态 / 记忆
├─ 用户上传 Skill 与 Skill Runner
├─ 个人助手：个人工作空间和通用工具
└─ 业务小助手：Bridge 上下文 + 当前页面获权 Manifest Action
```

平台正在用原生协调器替换历史 DSH Runtime。过渡期间每次运行在开始时固定选择 `native` 或 `dsh`，不会在运行中切换。旧 Connector 工具绑定只读保留至连续七天无调用；新业务助手不再注入 Connector、Data Interface、Ontology 或外部扩展。

## 本地开发

```bash
make setup
make dev-db
make migrate
make dev
make dev-fe
```

后端测试：

```bash
cd llm_router/backend
pytest tests/ -q
```

前端验证：

```bash
cd frontend
npm ci
npm run build
```

## 部署

Staging 使用 `docker-compose.coolify.yml`，具体参数见 [COOLIFY_DEPLOYMENT.md](COOLIFY_DEPLOYMENT.md)。发布使用不可变镜像 digest；数据库变更前必须备份，异常只切回旧镜像，不回滚用户文件。

## 已退役能力

DSH 市场与外部扩展、Connector/Data Interface/Ontology 重复抽象、Judge 与管理员测试广场、MCP/OAuth Skill Pack、旧模块发布器、Team、Production Mock 和 WebOffice 在线协作编辑均不再接受新配置。兼容路由在一个发布期内统一返回中文 `410 Gone`，数据只会在迁移门禁满足后物理删除。
