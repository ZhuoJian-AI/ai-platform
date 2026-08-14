# LLM Router — 企业级AI基础设施

一个统一的 LLM API 中转平台，具备组织架构管理、分层权限控制、DLP 安全围栏和多协议兼容能力。

## 🌟 核心功能

- **多提供商管理** — 统一配置 Anthropic、OpenAI、Azure OpenAI 等多个 LLM 提供商的 API Key
- **组织架构权限** — 公司→部门→团队三级组织架构，每层级可独立配置 API Key 和权限
- **协议兼容** — 同时兼容 Anthropic SDK (`/v1/messages`) 和 OpenAI SDK (`/v1/chat/completions`)
- **DLP 安全围栏** — 实时检测并拦截请求/响应中的敏感信息（身份证、银行卡、API Key 等）
- **模型路由** — 支持 glob 模式匹配、别名映射、负载均衡和故障转移
- **用量管控** — 分层速率限制（RPM/TPM）和预算上限，子级不得突破父级限制

## 🚀 快速开始

### 环境准备

```bash
# 启动 PostgreSQL 和 Redis
docker compose up -d postgres redis

# 安装依赖
cd backend
pip install -e ".[dev]"

# 运行数据库迁移
alembic upgrade head

# 启动开发服务器
uvicorn app.main:app --reload --port 8000
```

### 接入 Claude Code

```bash
# 设置环境变量
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=lr_sk_org_your_api_key_here

# 正常使用 Claude Code
claude
```

### 接入 OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="lr_sk_org_your_api_key_here"
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

## 📁 项目结构

```
llm_router/
├── backend/           # Python FastAPI 后端
│   ├── app/
│   │   ├── api/       # 管理 REST API
│   │   ├── auth/      # 认证与权限
│   │   ├── dlp/       # DLP 安全围栏引擎
│   │   ├── models/    # SQLAlchemy ORM 模型
│   │   ├── proxy/     # LLM API 代理层（核心）
│   │   ├── routing/   # 模型→提供商路由
│   │   ├── schemas/   # Pydantic 模式
│   │   └── services/  # 业务逻辑层
│   └── alembic/       # 数据库迁移
├── frontend/          # React + TypeScript 管理界面
├── docker-compose.yml
└── Makefile
```

## 🔐 API Key 层级体系

```
lr_sk_org_a3f8b2c1d4e5...    # 组织级 — 可访问组织所有模型
lr_sk_dept_7f9e0d2c4b6a...   # 部门级 — 受部门权限约束
lr_sk_team_1c3e5g7i9k1m...   # 团队级 — 最细粒度控制
```

**权限级联规则：**
- 模型列表：子级与父级取交集（只能缩小范围）
- 速率限制：取所有层级的最小值（不能突破父级上限）
- 预算上限：取所有层级的最小值
- DLP 规则：取所有层级的并集（安全规则只增不减）

## 🛡️ DLP 安全围栏

内置检测模式：

| 类别 | 检测内容 |
|------|---------|
| PII | 中国身份证号、美国SSN、护照号、手机号、邮箱 |
| 金融 | 银行卡号(Luhn校验)、SWIFT代码、IBAN |
| 凭证 | AWS密钥、OpenAI/Anthropic API Key、PEM私钥 |
| 医疗 | ICD疾病编码、医疗记录号、诊断关键词 |

**动作类型：**
- `block` — 拦截请求，返回错误
- `redact` — 替换敏感内容为 `[REDACTED]`
- `warn` — 放行但标记警告
- `log` — 静默记录

## 📋 管理 API

```bash
# 创建组织
POST /api/v1/organizations

# 创建部门
POST /api/v1/organizations/{org_id}/departments

# 注册 LLM 提供商
POST /api/v1/organizations/{org_id}/providers

# 创建 API Key
POST /api/v1/organizations/{org_id}/api-keys

# 创建 DLP 规则
POST /api/v1/organizations/{org_id}/dlp-rules

# 查询审计日志
GET /api/v1/organizations/{org_id}/audit-logs
```

API 文档：`http://localhost:8000/docs`

## 🧪 测试

```bash
cd backend
pytest tests/ -v
```

## 📄 License

MIT
