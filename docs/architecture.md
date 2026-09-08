# AI Platform 架构

## 1. 边界

AI Platform 只承担三类核心责任：

1. 企业身份、角色、页面、Action 和工作空间权限；
2. 模型供应商、模型路由、配额、安全和审计；
3. 统一 Assistant Core，包括工具循环、文件执行、会话、任务、事件和 Artifact 交付。

业务系统保存自己的业务数据和业务附件，通过 Manifest Action 返回权限过滤后的结构化数据。AI 产物由平台文件执行器写入员工工作空间，业务 ECS 不保存 AI 临时文件或最终产物。

## 2. 运行链路

```text
浏览器
  └─ frontend
      ├─ 管理后台
      └─ 员工终端
          ├─ 个人助手
          └─ 业务小助手（Bridge 页面上下文）
                │
                ▼
FastAPI backend
  ├─ 身份与实时权限服务
  ├─ Assistant Core
  │   ├─ 模型网关
  │   ├─ AssistantToolRegistry
  │   ├─ Task / Message / Run / Event
  │   └─ Artifact 提交与 SSE 重放
  ├─ Manifest Action 执行器
  ├─ 工作空间/OSS/预览服务
  ├─ RAG/Web/多模态/记忆
  └─ 配额、DLP、审计与监控
```

每个工具调用在执行前重新校验当前员工、应用、页面、Action 或工作空间权限。模型不能指定组织、员工、应用凭证或未经服务端验证的页面上下文。

## 3. Assistant Tool Registry

工具只从下列来源按本轮上下文装配：

- 平台固定工具；
- 工作空间搜索、读取、创建和版本化修改；
- 文件执行器；
- RAG、Web、多模态和记忆；
- 用户上传 Skill 与 Skill Runner；
- 业务小助手当前页面获权的 Manifest Action。

个人助手不会自动获得业务 Action；业务小助手不会混入其他应用 Action、长期记忆、Connector、Data Interface、Ontology 或旧包装 Skill。

## 4. 文件与 Artifact

- 工作空间、文件、文件版本和 OSS 对象是平台长期事实源。
- 文件先在一次性沙箱生成和验证，再提交工作空间。
- Artifact 只能由工作空间文件服务提交成功后产生，不能从模型正文或服务器路径推断。
- 删除对话只删除消息与引用，不删除已交付文件。
- WebOffice 只保留只读预览；在线协作编辑、编辑房间、保存回调和对账服务已退役。

## 5. 企业业务系统

业务系统通过 Runtime 登记 Manifest。员工可见页面和 AI 可调用 Action 都由角色授权决定。业务助手运行时只接收服务端核验后的：

```text
application_id + module_key + page_key + action_key
```

导出 Action 返回有界分页数据集；SaaS 文件执行器逐页生成真实文件。Bridge 只传递页面上下文，不代替服务端授权。

## 6. 数据与身份

- 员工只有一个主部门；跨部门访问来自多个角色权限并集。
- 企业管理员 `*` 提供全部部门工作空间读取、上传和修改，但不隐式批准新应用页面或 Action。
- 管理员账户与员工身份分离。
- Team 和多部门成员表已退出运行语义；兼容数据仅在迁移门禁通过后物理清理。
- Task、TaskMessage、AgentRunEvent、Artifact、工作空间、RAG、记忆和审计记录不可因精简而丢失。

## 7. 部署单元

最终 Coolify 运行九个服务：

```text
postgres
redis
backend
frontend
skill-runner
workspace-parser
workspace-preview
storage-lifecycle
multimodal-worker
```

过渡发布仍临时保留 `dsh-runtime` 和 `extension-builder`，仅用于原生协调器 canary 和镜像回切。确认原生个人助手、业务助手、自定义智能体、文件 Artifact 全部通过且 DSH 运行归零后，再从 Compose 删除。

## 8. 退役与删除门禁

- 旧 API 先返回中文 `410 Gone`，随后停止后台注入和写入。
- Connector/Endpoint 连续七天无调用，且等价 Manifest Action 验证通过后才删除绑定与表。
- DSH 排队和运行任务为零后才删除 Runtime、市场、外部扩展和旧镜像依赖。
- 表删除前必须确认无 ORM、外键、路由、后台任务和工具注册引用。
- 部署前记录数据库备份、用户文件统计、镜像 digest 和 Git 提交；异常只切回镜像，不回滚数据库或 OSS。

## 9. 代码目录

| 目录 | 责任 |
|---|---|
| `llm_router/backend/app/agents/core/` | 原生 Assistant Core |
| `llm_router/backend/app/agents/graph/` | 工具定义、执行和通用运行支持 |
| `llm_router/backend/app/services/` | 权限、模型、文件、RAG、Skill、企业接入与治理服务 |
| `llm_router/backend/app/api/` | 管理端、员工端、Manifest/Runtime 和兼容 410 API |
| `frontend/src/` | 管理后台、员工终端、业务嵌入和 Artifact UI |
| `skill_runner/` | 用户上传 Skill 的隔离执行器 |
| `docker-compose.coolify.yml` | Staging 部署拓扑 |
