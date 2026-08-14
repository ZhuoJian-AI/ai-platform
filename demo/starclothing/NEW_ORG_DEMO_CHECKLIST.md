# 新组织 demo 搭建 step-by-step checklist

> 复制 Starclothing 模式到新组织（如敏睿制造→XX 零售→YY 物流）的有序操作清单。
> 每步含「做什么 / 自检命令 / 通过条件 / 失败回退」四要素。

---

## 第 0 步：规划（不写代码）

### 0.1 业务建模
- [ ] 确定新组织行业（如服装 / 制造 / 零售 / 物流）
- [ ] 选 3~7 个核心场景（参考 Starclothing 的 PD-1~PD-3 + SC-1~SC-4 划分：产品开发 + 供应链）
- [ ] 每场景列出：触发角色 / 输入数据 / 期望输出格式 / 跨系统调用链 / RAG 依赖

### 0.2 技术规划
- [ ] mock 子系统数量（Starclothing 用 5 个：PLM/SCM/ERP/MES/CRM，新组织按业务定）
- [ ] RAG 知识库数量（Starclothing 用 1 个：服装缺陷知识库，新组织按场景定）
- [ ] Agent 数量 = 场景数（每个场景一个 agent）
- [ ] 用户角色：1 个业务用户（如 sjp）+ 1 个超管（如 root）

### 0.3 命名规约

星途 demo 当前 4 层命名统一用 `starclothing`（早期是 `xingtu`，已全套改名对齐）：

| 层 | 含义 | 星途现状 | 新组织举例 |
|---|---|---|---|
| **org slug** | 组织在 DB `organizations.slug` 字段，出现在终端 URL `/starclothing/terminal/login` | `starclothing` | `minrui` |
| **org name** | 中文显示名 `organizations.name` | `星途服装` | `敏睿制造` |
| **mock 租户名** | mock 中间件 `request.state.tenant` 值，在 `mock/mock/systems/*/data.py` 与 `SystemDef.keys_to_tenants` 中 | `starclothing` | `minrui` |
| **API key / skill / agent slug 前缀** | `plm-starclothing-demo-key` / `starclothing-plm-query` / `starclothing-pd1-product-monitor` | 前缀 `starclothing-` | 前缀 `minrui-` |

> **关键**：org slug 与 mock 租户名是**两个不同的字段**，分别落在 `organizations` 表
> 与 mock 中间件 `SystemDef.keys_to_tenants` 字典里。星途 demo 早期 `xingtu` 时代
> 两者不同步（org slug 改了但 mock 租户名没改），后续统一成 `starclothing` 后才
> 消除混淆。新组织建议一开始就用同一个 slug 全套覆盖，避免后续维护时割裂。

- [ ] org slug（如 `starclothing` → `minrui`）
- [ ] org name（中文显示名）
- [ ] mock 租户名（如 `starclothing` → `minrui`，需改 `mock/mock/systems/*/data.py` + `registry.py` 的 `keys_to_tenants`）
- [ ] 业务用户 username + password（星途用 `sjp` / `12345678`）
- [ ] API key 命名前缀（如 `plm-starclothing-demo-key` → `plm-minrui-demo-key`）
- [ ] skill / agent slug 前缀（如 `starclothing-plm-query` → `minrui-plm-query`）

---

## 第 1 步：seed 组织 / 用户 / 路由策略

### 1.1 复制 + 改名 seed 脚本
```bash
cp demo/starclothing/scripts/seed_starclothing_apparel.py \
   demo/<neworg>/scripts/seed_<neworg>_apparel.py
```

### 1.2 替换关键变量（必改）
- `ORG_SLUG = "starclothing"` → 新 slug
- `ORG_NAME_FALLBACK = "星途服装"` → 新名
- 用户名 / 密码 / 部门名 / 团队名 / 模型（真实 id，如 `glm-5.2` / `claude-sonnet-4`）

### 1.3 跑脚本
```bash
docker cp demo/<neworg>/scripts/seed_<neworg>_apparel.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_<neworg>_apparel.py
```

### 1.4 自检
```bash
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
  "SELECT slug, name FROM organizations WHERE slug='<neworg>';"
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
  "SELECT username, is_active FROM users WHERE username='<user>';"
```

### 1.5 通过条件
- 组织记录存在且 slug 正确
- 用户记录存在且 `is_active=true`
- provider 的 `supported_models` 含目标真实模型 id（如 `claude-sonnet-4`）

### 1.6 失败回退
- 跑脚本报 org 已存在 → 检查 `LEGACY_ORG_NAME_FALLBACK` 是否需要兼容旧名
- `terminal/models` 看不到目标模型 → 检查 LlmProvider 是否配好 `supported_models`（应在第 0 步前通过管理后台配好）

---

## 第 2 步：建 mock 子系统

### 2.1 复制骨架模板
```bash
cp -r demo/starclothing/templates/mock_subsystem mock/mock/systems/<sysname>/
```
（参考 `MOCK_SUBSYSTEM_TEMPLATE.md` 写法）

### 2.2 编写业务数据（data.py）
- 按 Starclothing 的 `mock/mock/systems/plm/data.py` 写法：dataclass + LazyTenantRegistry
- 每张业务表至少 5~20 条样本数据
- 多租户 key（如 `<sysname>-<org>-demo-key`）

### 2.3 编写端点（routes.py）
- 用 `Annotated[..., Depends(get_tenant)]` 注入 tenant
- 至少 1 个 `list*` 端点（query 参数）+ 1 个 `get*` 端点（path 参数）
- 业务逻辑端点（评分 / 比对 / 检测等）按场景需要写

### 2.4 注册到 mock 网关
在 `mock/mock/core/registry.py` 加：
```python
SystemDef(
    key="<sysname>", name="<sysname> ...", prefix="/<sysname>",
    api_key="<sysname>-<org>-demo-key", keys_to_tenants={"<sysname>-<org>-demo-key": "<org>"},
),
```

### 2.5 自检
```bash
docker restart ai_infra_mock
curl -s "http://localhost:8010/<sysname>/health" -H "X-API-Key: <sysname>-<org>-demo-key"
curl -s "http://localhost:8010/<sysname>/openapi.json" -H "X-API-Key: <sysname>-<org>-demo-key" | head
```

### 2.6 通过条件
- `/health` 返回 `{"status":"ok","system":"<sysname>"}`
- `/openapi.json` 含全部端点 path

### 2.7 失败回退
- `404 Not Found` → 检查 `registry.py` 是否注册 + `__init__.py` 是否导入
- `401 Unauthorized` → API key 不匹配，检查 `keys_to_tenants`

---

## 第 3 步：seed mock 连接器 + 技能 + 数据接口

### 3.1 复制 + 改名
```bash
cp demo/starclothing/scripts/seed_starclothing_mock_connectors.py \
   demo/<neworg>/scripts/seed_<neworg>_mock_connectors.py
```

### 3.2 替换变量
- `ORG_SLUG` → 新 slug
- `SKIP_SYSTEMS` → 按实际建的系统调整（Starclothing 跳过 HRM）
- `DEFAULT_BASE_URL` → 默认 `http://localhost:8010`

### 3.3 跑脚本
```bash
docker cp demo/<neworg>/scripts/seed_<neworg>_mock_connectors.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_<neworg>_mock_connectors.py
```

### 3.4 自检
```bash
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"<neworg>","username":"<user>","password":"<pwd>"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl -sS http://localhost:8000/api/v1/terminal/resources -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; r=json.load(sys.stdin); print([s['slug'] for s in r['skills']])"
```

### 3.5 通过条件
- skills 列表含 `<org>-<sysname>-query` 技能
- data_interfaces 含所有 mock 端点

### 3.6 失败回退
- 技能没注册 → mock openapi.json 取不到，检查 `MOCK_BASE_URL` 容器互联
- 数据接口空 → 检查 mock 端点是否在 `openapi.json` 里

---

## 第 4 步：seed 本体文件

### 4.1 复制 + 改名
```bash
cp demo/starclothing/scripts/seed_starclothing_ontology.py \
   demo/<neworg>/scripts/seed_<neworg>_ontology.py
```

### 4.2 写本体内容
参考 Starclothing 的 `app/seed_data/ontology/` 三文件夹结构：
- `<SysName>/README.md` — 子系统概述
- `<SysName>/object-types.md` — 对象类型（如款式 / 工单 / 供应商）
- `<SysName>/link-types.md` — 链接类型（如 style_uses_fabric）
- `<SysName>/action-types.md` — 动作类型（如 list / get / create / update）
- `Cross/README.md` + 三件套——跨系统概念

### 4.3 跑脚本 + 自检
```bash
docker cp demo/<neworg>/scripts/seed_<neworg>_ontology.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_<neworg>_ontology.py
# 自检：
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
  "SELECT folder_path, name FROM skill_files WHERE folder_path LIKE '%<neworg>%' OR name LIKE '%<neworg>%' LIMIT 30;"
```

### 4.4 通过条件
- 12 个本体文件（4 文件夹 × 3 文件，或按实际子系统数 × 3）全部入库
- sjp 登录后 trace `category=ontology` 应含 12 files

---

## 第 5 步：seed RAG 知识库（按需，非所有场景都要）

### 5.1 准备语料
- 业务知识沉淀（Starclothing 用 8 类缺陷案例 61 chunks）
- 按场景需要的 RAG：缺陷案例 / 规章制度 / SOP / 历史案例库

### 5.2 复制 + 改名
```bash
cp demo/starclothing/scripts/seed_starclothing_defect_rag.py \
   demo/<neworg>/scripts/seed_<neworg>_<ragname>.py
```

### 5.3 跑脚本 + 自检 embedding 完整性
```bash
docker cp demo/<neworg>/scripts/seed_<neworg>_<ragname>.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_<neworg>_<ragname>.py
docker exec ai_infra_backend python -c "
import asyncio
from app.database import async_session_factory
from sqlalchemy import select, func
from app.models.rag import RagCollection, RagChunk
async def main():
    async with async_session_factory() as db:
        r = await db.execute(select(RagCollection).where(RagCollection.name=='<ragname>'))
        c = r.scalar_one_or_none()
        if not c: print('collection not found'); return
        cnt = await db.execute(select(func.count(RagChunk.id)).where(RagChunk.collection_id==c.id))
        emb = await db.execute(select(func.count(RagChunk.id)).where(RagChunk.collection_id==c.id, RagChunk.embedding.isnot(None)))
        print(f'chunks: {cnt.scalar()} embedded: {emb.scalar()}')
asyncio.run(main())
"
```

### 5.4 通过条件
- chunks 总数 = embedded 总数（无 NULL embedding）
- 若 embedded < chunks → 跑 `reembed_<neworg>_<ragname>.py`（参考 `reembed_defect_rag.py` 写法）补齐

### 5.5 retrieve_rag trace 验证
- sjp 跑一个含 RAG 关键词的任务
- trace `category=rag` 应显示 `retriever=vector` + `hits ≥ 1`
- 若 `retriever=keyword_fallback` → 向量通道未通，参考 `pd1_terminal_task.md` §5.6 修复路径

---

## 第 6 步：seed Agent 配置

### 6.1 复制 + 改名
```bash
cp demo/starclothing/scripts/seed_starclothing_agents.py \
   demo/<neworg>/scripts/seed_<neworg>_agents.py
```

### 6.2 改 agent slug / name / system_prompt
- 每个 agent 一个场景，system_prompt 写法参考 PD-1/PD-2/PD-3 prompt（含「输出要求」段——见 `PROMPT_OUTPUT_PATTERN.md`）
- skill_slugs 绑定该场景所需 mock 技能
- rag_collection_name 绑定该场景所需 RAG（无 RAG 设 None）

### 6.3 跑脚本 + 自检
```bash
docker cp demo/<neworg>/scripts/seed_<neworg>_agents.py ai_infra_backend:/app/scripts/
docker exec ai_infra_backend python scripts/seed_<neworg>_agents.py
# 自检：
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
  "SELECT slug, name FROM agents WHERE slug LIKE '<org>-%';"
```

### 6.4 通过条件
- 所有场景 agent 入库
- 每个 agent 有对应的 skill_slugs / rag_collection_name

---

## 第 7 步：写场景 demo 文档

### 7.1 复制 + 改名 pd1_terminal_task.md 模板
```bash
cp demo/starclothing/pd1_terminal_task.md demo/<neworg>/<scenario>_terminal_task.md
```

### 7.2 按场景改 7 节内容
1. 演示身份
2. 前置条件
3. 操作步骤（含 prompt + 资源注入表）
4. 期望输出（含 SSE trace 表）
5. 故障排查（参考 Starclothing 三场景 §5 模板）
6. 手工调 API 复现

### 7.3 写 README.md 演示矩阵
参考 `demo/starclothing/README.md` §1 演示矩阵写法

---

## 第 8 步：端到端验证

### 8.1 跑 1 个场景任务
- 用业务用户登录终端 `http://localhost:8000/<org>/terminal/login`
- 新建任务、选模型（真实 id）、/-mention 选技能、贴 prompt
- 运行，观察 SSE 是否含 6 类 trace + 4 段分析上屏 + generate_docx

### 8.2 稳定性验证
- 同一 prompt 跑 2 次（参考 PD-3 v2+v3、PD-2 v4+v6、PD-1 v5+v6 模式）
- 两次都应 4 段分析上屏 + 6 trace 全触发
- 若第二次 text 字符数暴跌（参考 PD-1 v4：7179→356）→ 检查 prompt 是否含「输出要求」段

### 8.3 评估输出达标度
参考 `SCENARIO_AUTHORING_GUIDE.md` §7 12 项验收清单逐项打勾

---

## 第 9 步：commit + push

### 9.1 检查范围
```bash
cd /root/ai_infra
git status
git diff --stat
```

### 9.2 commit（按 Starclothing 提交风格）
```
feat(<neworg>): <场景概述> demo + mock <子系统> + 节点修复

## 主要内容
1. ... (参考 commit 6906d86 的 8 段式结构)
```

### 9.3 push
```bash
git push origin main
```

---

## 常见踩坑速查

| 症状 | 根因 | 修复参考 |
|---|---|---|
| `tool_call arguments={}` 全部失败 | `_build_tools` 占位 schema 覆盖 | `pd2_terminal_task.md` §5.11 |
| `getStyle` 返回 `style {style_code} not found` | path-param 占位符未替换 | `pd3_terminal_task.md` §5.13 |
| `trace rag retriever=keyword_fallback` | 向量通道未通 | `pd1_terminal_task.md` §5.6 |
| agent 跳过 text 直接生成 docx | prompt 缺「输出要求」段 | `PROMPT_OUTPUT_PATTERN.md` |
| `getLeadtimeDiff` 返回 `{}` | tz-aware/naive 比较失败 | `pd2_terminal_task.md` §5.10 |
| memory/extract 0 facts | extract 节点对中文长文本偏保守 | `pd1_terminal_task.md` §5.11 |
