# AI Infra — 企业级 AI 基础设施平台

一个统一的 AI 基础设施平台，围绕大模型路由、工具接入、应用监控与智能体编排提供一站式能力。平台由四个子系统组成，共享同一套后台管理控制台与基础设施（PostgreSQL / Redis）。

## 🧩 子系统

| 子系统 | 目录 | 说明 | 状态 |
|--------|------|------|------|
| 模型路由器 (llm_router) | [`llm_router/`](llm_router/) | 统一 LLM API 中转：多提供商管理、组织架构权限、DLP 安全围栏、协议兼容、模型路由与用量管控 | ✅ 已实现 |
| 工具连接器 (tool_connector) | [`tool_connector/`](tool_connector/) | ERP/CRM/HRM 系统 API 接入、技能（function-tool）、本体（ontology）与测试广场 | ✅ 已实现 |
| 应用监控台 (app_monitor) | [`app_monitor/`](app_monitor/) | 路由器 / 智能体 / 工具 三子系统统一监控看板 | ✅ 已实现 |
| 智能体平台 (agent_platform) | [`agent_platform/`](agent_platform/) | 基于 LangGraph 的智能体编排（系统提示词 / workflow / memory / judge / RAG / 工具）、测试广场 | ✅ 已实现 |

后台管理控制台位于 [`frontend/`](frontend/)，顶部一级菜单切换五个子系统：①组织管理 ②模型路由器 ③智能体平台 ④工具连接器 ⑤应用监控台，左侧二级菜单为当前子系统的功能页面。所有子系统共享同一套后端（`llm_router/backend/app/` 下的组织架构 / Admin 鉴权 / 审计 / DB 基础设施）与统一 API client。

## ✨ 新增能力一览（基于 LangGraph）

- **组织管理**（一级菜单①）：从模型路由器剥离为独立一级菜单，下设组织架构、管理员管理、用户管理。
- **智能体平台**（一级菜单③）：工作空间（文件沙箱）、智能体配置（系统提示词 / 模型 / workflow / 记忆 / 判官 / RAG / 技能绑定）、RAG（pgvector 向量检索 + 文档分块入库 + 检索测试）、Judge 模板、测试广场（LangGraph 运行时：`load_config → retrieve_rag → load_memory → agent_loop(LLM↔工具多步) → save_memory → judge → write_run_log`，SSE 流式输出）。
- **工具连接器**（一级菜单④）：连接器（ERP/CRM/HRM，OpenAPI spec 导入端点）、技能（OpenAI function-tool 定义 + 绑定端点 + 测试）、本体（JSONB 实体/关系图 + 一致性校验）。
- **应用监控台**（一级菜单⑤）：路由器 / 智能体 / 工具 三子系统近 24h 指标聚合（调用量、token、延迟、错误率、DLP 违规、成功率），recharts 图表。

智能体运行时与 RAG 嵌入复用模型路由器的 provider 解析 / 密钥解密 / 路由能力（`app/agents/llm_client.py`），不二次自建上游调用。

## 📁 项目结构

```
ai_infra/
├── frontend/                 # 平台统一控制台（React + TypeScript + Ant Design）
├── llm_router/               # 模型路由器子系统
│   ├── backend/              # FastAPI 后端（包名 app）
│   └── README.md             # 子系统详细文档
├── tool_connector/           # 工具连接器（规划中）
├── app_monitor/              # 应用监控台（规划中）
├── agent_platform/           # 智能体平台（规划中）
├── docker/                   # 共享基础设施配置
├── docker-compose.yml        # PostgreSQL + Redis
└── Makefile                  # 平台级开发命令
```

## 🚀 快速开始

```bash
# 1. 启动共享基础设施（PostgreSQL + Redis）
make dev-db

# 2. 安装并启动模型路由器后端
make setup
make migrate
make dev          # http://localhost:8000  （文档 /docs）

# 3. 启动平台控制台
make dev-fe       # http://localhost:5173
```

模型路由器的接入方式（Claude Code / OpenAI SDK）、API Key 层级体系、DLP 安全围栏等详细说明，见 [llm_router/README.md](llm_router/README.md)。

## 🛠 常用命令

```bash
make help          # 查看全部命令
make setup         # 安装后端依赖
make migrate       # 执行数据库迁移
make dev           # 启动后端开发服务器
make dev-fe        # 启动前端控制台
make test          # 运行后端测试
make lint          # 代码检查
make dev-stop      # 停止基础设施
```

## 📄 License

MIT
