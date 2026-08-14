# PRD-01 产品参数核对与卖点提炼 · 终端任务演示

> 产品部产品专员 `pm-product` 登录终端，新建任务、配置 `glm-5.2` + `craft`、`/agileac-prd-plm-crm-query` 选技能、写提示词、运行，agent 自主多轮调 PLM `getStyle`/`listBoms` 核对 2 款产品参数 + 调 CRM `listCustomers`/`listOpportunities` 取客户画像 + 检索「产品参数与卖点库」取 5 段式方法论，输出参数核对表 + 卖点提炼清单 + 内部款/竞品差异表。
>
> **员工 vibe working 视角**：产品专员原本要在 PLM 翻参数表、CRM 翻客户反馈、再手工拼卖点文档交付市场部——现在一句话拿到核对一致的参数表 + 5 段式卖点 + 竞品差异，直接喂给 MKT-01 做内容生成。AI 是产品专员的副驾驶，**不对终端客户**。
>
> 本场景验证 **痛点 A2 产品卖点提取 + C 参数核对**——产品部交付市场部（MKT-01 接力）的衔接场景。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 敏睿空调（slug = `agileac`） |
| 用户名 | `pm-product` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |
| 部门 | 产品部（不分团队） |

> 产品部无下属团队，技能为部门级 `agileac-prd-plm-crm-query`（PLM 款式/BOM + CRM 客户/商机只读）；RAG 为部门级「产品参数与卖点库」（dept: product）。

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）+ `ai_infra_postgres` 容器在跑。
2. **数据已 seed**（按 `README.md` §9 顺序执行）：
   - `seed_agileac_org.py`（含 `pm-product` 用户 + 产品部）
   - mock 6 系统 agileac tenant 数据已内置（`mock/mock/systems/*/data.py` 的 `_build_agileac`），含 PLM 2 款主打产品 P-RC-WALL-15 / P-CC-VRV-360 的参数 + BOM；CRM 客户/商机；mock 容器重启即生效
   - `seed_agileac_mock_connectors.py`（含部门级技能 `agileac-prd-plm-crm-query`，PLM listStyles/getStyle/listBoms + CRM listCustomers/getCustomer/listOpportunities/listFollowUps）
   - `seed_agileac_ontology.py`（组织级 PLM/CRM 各域 `identifiers.md`——产品款号 P-RC-/P-CC-、物料 M-、客户 C-AG- 前缀与码空间映射）
   - `seed_agileac_rag.py`（含部门级「产品参数与卖点库」：6 款产品参数表 + 5 段式卖点方法论 + 内部款/竞品差异对照）
   - `seed_agileac_agents.py`（含 `agileac-prd-01-product-params` agent 模板配置，四层架构 system_prompt）
3. **glm-5.2 已可用**：组织已配智谱 AI provider，`supported_models` 含 `glm-5.2`。
   - 自检：`GET /api/v1/terminal/models`（用 pm-product token）应在 `models` 里看到 `glm-5.2`。
4. **pm-product 账号已存在且 active**：
   ```bash
   docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
     "SELECT username, is_active FROM users WHERE username='pm-product';"
   ```
5. **PLM/CRM mock 端点正常**：
   ```bash
   curl -s "http://localhost:8010/plm/styles?style_code=P-RC-WALL-15" -H "X-API-Key: plm-agileac-demo-key" | head
   curl -s "http://localhost:8010/plm/boms?style_code=P-RC-WALL-15" -H "X-API-Key: plm-agileac-demo-key" | head
   curl -s "http://localhost:8010/crm/customers" -H "X-API-Key: crm-agileac-demo-key" | head
   curl -s "http://localhost:8010/crm/opportunities" -H "X-API-Key: crm-agileac-demo-key" | head
   ```
   均应返回 JSON 列表。

> ⚠️ PRD-01 关键依赖：PLM `getStyle`/`listBoms`（产品参数 + BOM 核对）+ CRM `listCustomers`/`listOpportunities`（客户画像做场景化卖点）+ RAG「产品参数与卖点库」（标称参数基准 + 5 段式方法论 + 竞品对照）。**卖点不走 `getProductSellingPoints` 端点（未实现/未绑定）**——卖点段来自 RAG，参数来自 PLM，客户画像来自 CRM。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问 `http://localhost:8000/agileac/terminal/login`，用户名 `pm-product`，密码 `12345678`。登录后落到 `/agileac/terminal`，左上角应显示「产品部」。

> 终端使用 user-type JWT。`pm-product` 的 scope 包含：组织级资源（PLM/CRM identifiers）+ 产品部部门级资源（技能 + RAG）+ 个人工作区。

### 3.2 新建任务

点左栏「New Task / 新建任务」进入任务编辑器。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧 ⚙️ 设置按钮，配置 4 项：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `pm-product`（个人工作区） | 干净；记忆仍按四级自动载入 |
| Model | **`glm-5.2`** | 真实模型 id，无别名层 |
| Exec Mode | **`craft`** | agent 需多轮 PLM/CRM + RAG + generate_docx |
| 场景模板 | `agileac-prd-01-product-params` | **必绑**——5 段式卖点规则/竞品覆盖/输出骨架由模板 system_prompt 承载 |

> 若 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id`。

### 3.4 在输入框写提示词 + /-mention 选择技能

敲 `/` 弹出技能菜单，输入 `prd` 过滤，选中 **`agileac-prd-plm-crm-query`** 即把技能 chip 插入提示词。

**提示词**（直接复制，约 50 字——**纯业务请求，不带任何编排/端点指令**）：

```
对敏睿空调 2 款主打产品做参数核对与卖点提炼：P-RC-WALL-15（1.5 匹壁挂家用）、P-CC-VRV-360（360 型多联机商用）。

/agileac-prd-plm-crm-query
```

> **四层架构**：user composer 只写**产品款号 + 业务目标 + 技能 chip**。5 段式卖点方法论、竞品覆盖 5 大品牌、参数核对路径、输出三段——**全部由 Agent 模板 `agileac-prd-01-product-params` 的 `system_prompt` 承载**。任务 config 必须绑定 `template_agent_id = <agileac-prd-01-product-params 的 UUID>`，运行时 `load_config` 才会注入模板（trace `template` 出现、`template:true`）。
>
> ⚠️ **关键 1**：`/agileac-prd-plm-crm-query` 必须从 `/` 菜单选 chip，不能手敲。
> ⚠️ **关键 2**：提示词只写产品款号 + 业务目标，不写"调 PLM getStyle 再查 BOM"这类编排——核对路径与卖点规则全由模板驱动。
> ⚠️ **关键 3**：composer 写明 2 款具体产品款号——让 agent 有明确核对锚点。本体 identifiers.md 已写明款号前缀 P-RC- 家用 / P-CC- 商用，agent 调端点前读此表杜绝 404。

#### 资源注入机制（任务运行时自动完成）

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | 按 scope 注入（组织级 PLM/CRM identifiers） | 若干 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` | PLM/CRM 2 systems / ~8 interfaces |
| **RAG** | agent 绑定部门级「产品参数与卖点库」 | 1 collection / 多 chunks |
| **长期记忆** | 4 级聚合；load_memory 节点载入 | 若干 history + facts |
| **技能** | /-mention 解析 + 模板继承 | 1 skill（agileac-prd-plm-crm-query） |
| **记忆沉淀** | extract_memory 抽取本轮可沉淀事实 | 0~3 facts |

### 3.5 提交运行

按回车提交。前端 `POST /api/v1/terminal/tasks` 创建任务，再 `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}`。

### 3.6 观察 SSE 事件流

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载配置（`template:true` 表示模板已注入） |
| `[trace]` (template) | 场景模板 `agileac-prd-01-product-params` 注入 |
| `[trace]` (memory/load) | 长期记忆载入 |
| `[trace]` (ontology) | 组织本体注入（含 PLM/CRM identifiers） |
| `[trace]` (rag) | 「产品参数与卖点库」检索命中 |
| `[trace]` (data_interface) | 数据接口目录注入（PLM/CRM） |
| `[trace]` (skill) | /-mention 引用 `agileac-prd-plm-crm-query` |
| `[trace]` (memory/extract) | 记忆沉淀抽取 |
| `[tool_call]` | agent 调 PLM `getStyle`×2 + `listBoms` + CRM `listCustomers`/`listOpportunities` |
| `[text]` | LLM 流式输出参数表/卖点清单/差异表 |
| `[done]` / `[final]` | 收口 + usage + latency |

> 典型 PRD-01 运行约 2–4 分钟（多轮 PLM/CRM + RAG + LLM 推理 + 记忆节点）。

---

## 4. 期望输出

### 4.1 参数核对表（2 款产品）

| 参数 | 标称值 | PLM 实际 | 一致性 | 备注 |
|---|---|---|---|---|
| 制冷量 | 3.5 kW | 3.5 kW | ✓ | P-RC-WALL-15 |
| 能效等级 | 1 级 | 1 级 | ✓ | APF 5.20 |
| 噪音（低档） | 22 dB | 22 dB | ✓ | - |
| ... | ... | ... | ... | ... |

> PLM 实际与标称不符项标 ⚠️ 并在备注列写差异（如某参数 RAG 标称 vs PLM 实际偏差）。

### 4.2 卖点提炼清单（5 段式，产品部 → 市场部）

1. 节能省电：1 级能效 APF 5.20，全年省 30%
2. 静音舒适：低档 22 dB，等同图书馆
3. 快速响应：30 秒速冷，开机即享
4. 智能健康：紫外杀菌 99.9%
5. 场景适配：50—80㎡ 主卧/儿童房/老人房

### 4.3 内部款/竞品差异表

| 维度 | 本款 | 对比款 | 差异 |
|---|---|---|---|
| 能效 | APF 5.20 | ... | ... |
| 噪音 | 22 dB | ... | ... |

> 竞品覆盖格力/美的/海尔/大金/三菱 5 大品牌，参数来自 RAG 竞品对照 chunk 不杜撰。

### 4.4 .docx 报告附件

agent 调 `generate_docx` 把三段打包成 `敏睿空调_产品参数核对与卖点提炼_YYYYMMDD.docx`（约 30 KB），交付市场部（MKT-01 接力）。

### 4.5 SSE trace 事件

| trace | 含义 | 期望实测值 |
|---|---|---|
| `category=template` | 场景模板注入（必出） | slug=agileac-prd-01-product-params + chars |
| `category=rag` | 卖点库/竞品对照检索 | 命中产品参数 + 5 段式方法论 chunk |
| `category=ontology` | 组织本体注入 | 含 PLM/CRM identifiers |
| `category=data_interface` | 数据接口目录 | PLM/CRM 2 systems |
| `category=skill` | /-mention 引用技能 | 1 skill |
| `category=memory, subtype=load/extract` | 记忆载入/沉淀 | 若干 facts |

> 6 类 trace 全出（rag + memory.load + ontology + data_interface + skill + memory.extract）。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `glm-5.2`
- 智谱 AI provider 未配或 `supported_models` 不含 `glm-5.2`。修复：管理端配智谱 AI provider + 路由策略 `model_pattern=glm-*`，重跑 `seed_agileac_org.py`。

### 5.2 提示词里 `/agileac-prd-plm-crm-query` 没被识别
- 必须从 `/` 弹窗选 chip，不能手敲。自检：task.message 里这段应是结构化 chip 标记。

### 5.3 `[tool_result FAIL]` PLM/CRM 接口调用失败
- mock 网关未起或 API key 不匹配。自检 PLM/CRM 端点（见 §2.5）均应返回 JSON。注意每个系统用各自的 agileac demo key（plm-agileac-demo-key / crm-agileac-demo-key）。

### 5.4 agent 输出「我没有收到任务」
- 检查 `/run` 请求体里 `message` 是否为空——必须把完整提示词作为 `message` 发送。

### 5.5 agent 卖点杜撰（不来自 RAG/PLM）
- 现象：卖点数值与 PLM 参数 / RAG 卖点库不符。
- 根因：agent 没真调 PLM `getStyle` 核对、没检索 RAG 卖点库，靠模型先验杜撰。
- 修复：确认 `load_config template:true` + 模板 system_prompt 含"参数来自 PLM + 卖点来自 RAG"约束；看 `tool_call` 是否覆盖 PLM `getStyle` + RAG 检索。

### 5.6 path 参数端点（`getStyle`）返回 404
- 现象：agent 调 `getStyle(style_code="P-RC-WALL-15")` 返回 `{style_code} not found`——path 占位符未替换。
- 影响：**不阻塞闭环**。agent 自主降级到 `listStyles`（query 参数端点）仍能拿到产品参数做核对。
- 修复（可选）：技能 wrapper 按 OpenAPI path 占位符替换。非阻塞性，本期按「agent 自主降级」通过。

### 5.7 `tool_call` args 全 `{}`
- 现象：所有 `tool_call.arguments={}`，需要参数的端点返回 500。
- 根因：`_build_tools`（`app/agents/graph/nodes.py`）manifest 占位 schema 覆盖问题。
- 修复：只要有一条 `tool_call` args 非 `{}`（如 `getStyle(style_code=...)`）就说明 `_build_tools` 正常；全 `{}` 立即查 `nodes.py` `_build_tools`。

### 5.8 memory/extract 抽取 0~3 facts
- 非阻塞；长期记忆跨任务复用弱。

---

## 6. 附：手工调 API 复现

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agileac","username":"pm-product","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 PRD Agent 模板 id
TPL_ID=$(docker exec ai_infra_backend python3 -c "
import asyncio, asyncpg
async def m():
    c=await asyncpg.connect('postgresql://ai_infra:ai_infra@postgres:5432/ai_infra')
    r=await c.fetchrow(\"SELECT id FROM agents WHERE slug='agileac-prd-01-product-params'\")
    print(r['id']); await c.close()
asyncio.run(m())")

# 3) 创建任务（绑定模板；skill_ids 留空从模板继承，model=glm-5.2）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"PRD-01 参数核对与卖点\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer，含 /agileac-prd-plm-crm-query chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"对敏睿空调 2 款主打产品做参数核对与卖点提炼：P-RC-WALL-15（1.5 匹壁挂家用）、P-CC-VRV-360（360 型多联机商用）。\\n\\n/agileac-prd-plm-crm-query\",\"stream\":true}"
```

---

## 7. 验收要点（演示前自检）

- [ ] `pm-product` 能登录 `/agileac/terminal/login`，左上角显示「产品部」
- [ ] `GET /api/v1/terminal/resources`（pm-product token）的 `skills` 含 `agileac-prd-plm-crm-query`（dept: product）
- [ ] `rag_collections` 含「产品参数与卖点库」（dept: product）
- [ ] `data_interfaces` 含 PLM `getStyle`/`listBoms` + CRM `listCustomers`/`listOpportunities`
- [ ] `load_config` 事件显示 **`template:true`**
- [ ] `trace category=template` 出现（slug=`agileac-prd-01-product-params` + chars）
- [ ] SSE 6 类 trace 出现（rag + memory.load + ontology + data_interface + skill + memory.extract）
- [ ] `tool_call` 覆盖 PLM `getStyle`×2（2 款产品）+ `listBoms` + CRM `listCustomers`/`listOpportunities`
- [ ] `tool_call` args 不全 `{}`（至少 `getStyle(style_code=...)` 要带参）
- [ ] no-guessing：agent 用对款号前缀 P-RC- 家用 / P-CC- 商用；竞品参数来自 RAG 不杜撰
- [ ] 输出含参数核对表 + 5 段式卖点清单 + 内部款/竞品差异表 + generate_docx 附件，交付市场部（MKT-01 接力）
