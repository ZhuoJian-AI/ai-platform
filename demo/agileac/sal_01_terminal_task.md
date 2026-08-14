# SAL-01 销售订单回款与电商退换货 · 终端任务演示

> 销售部销售运营员 `sal-ops`（订单回款子任务）/ 电商运营员 `sal-ecom`（退换货子任务）登录终端，新建任务、配置 `glm-5.2` + `craft`、`/agileac-sal-crm-erp-query` 选技能、写提示词、运行，agent 自主多轮调 CRM `listSalesOrders`/`listReceivables`/`listComplaints`/`listCustomers` + ERP `listVouchers`/`listProductionCosts`，输出订单回款报表 + 应收催办清单（销售运营子任务），或退换货内部处理清单（电商退换货子任务）。
>
> **员工 vibe working 视角**：销售运营员原本要在 CRM 翻订单/应收、再手工拼回款报表与催办单；电商运营员翻客诉、安排退换货内部检测——现在一句话拿到回款报表/催办对象或退换货处理清单。AI 是销售员工的副驾驶，**不对终端客户直接交互**（B3 AI 语音客服不开放；应收催办通过待办机制推送 sal-ops/fin-receivable，退换货客诉转 svc-engineer 检测回流 SVC-01）。
>
> 本场景验证 **痛点 B 销售回款报表 + A4 退换货内部处理 + E 应收催办**。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 敏睿空调（slug = `agileac`） |
| 用户名 | `sal-ops`（销售运营子任务）/ `sal-ecom`（电商退换货子任务） |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |
| 部门 | 销售部 · 销售运营组 `sales-ops` / 电商组 `sales-ecom` |

> 两子任务同属销售部，技能同源（部门级 `agileac-sal-crm-erp-query`，CRM 客户/商机/订单/客诉/应收 + ERP 凭证/生产成本只读）；无 RAG。按子任务切归口员工验证组级 scope 隔离。

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）+ `ai_infra_postgres` 容器在跑。
2. **数据已 seed**（按 `README.md` §9 顺序执行）：
   - `seed_agileac_org.py`（含 `sal-ops` / `sal-ecom` 用户 + 销售部 + 销售运营组/电商组）
   - mock 6 系统 agileac tenant 数据已内置，含 CRM 销售订单 AGSO + 应收 AGINV（含逾期样本）+ 客诉 AGCP（含 type=return 退换货样本）+ 客户 C-AG-（RETAIL/ECOM/DEALER/PROJ 四渠道）；mock 容器重启即生效
   - `seed_agileac_mock_connectors.py`（含部门级技能 `agileac-sal-crm-erp-query`，CRM listCustomers/getCustomer/listOpportunities/listQuotations/listSalesOrders/listComplaints/listReceivables/listFollowUps + ERP listVouchers/listProductionCosts）
   - `seed_agileac_ontology.py`（组织级 CRM/ERP 各域 `identifiers.md`——销售订单 AGSO、客户 C-AG-、客诉 AGCP、应收 AGINV、凭证 BV-AG- 前缀与码空间映射）
   - `seed_agileac_agents.py`（含 `agileac-sal-01-sales-ecommerce` agent 模板配置，四层架构 system_prompt）
3. **glm-5.2 已可用**：自检 `GET /api/v1/terminal/models`（sal-ops token）应含 `glm-5.2`。
4. **sal-ops / sal-ecom 账号已存在且 active**：
   ```bash
   docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
     "SELECT username, is_active FROM users WHERE username IN ('sal-ops','sal-ecom');"
   ```
5. **CRM/ERP mock 端点正常**：
   ```bash
   curl -s "http://localhost:8010/crm/sales-orders" -H "X-API-Key: crm-agileac-demo-key" | head
   curl -s "http://localhost:8010/crm/receivables" -H "X-API-Key: crm-agileac-demo-key" | head
   curl -s "http://localhost:8010/crm/complaints?type=return" -H "X-API-Key: crm-agileac-demo-key" | head
   curl -s "http://localhost:8010/crm/customers" -H "X-API-Key: crm-agileac-demo-key" | head
   ```
   均应返回 JSON 列表。

> ⚠️ SAL-01 关键依赖：CRM `listSalesOrders`/`listReceivables`（订单回款）+ CRM `listComplaints`(type=return)（退换货）+ CRM `listCustomers`/`getCustomer`（客户画像）+ ERP `listVouchers`（凭证核对）。**应收走 CRM `listReceivables`**（ERP 无 listReceivables 端点，AGINV 发票号与 ERP 共享码空间）；**退换货客诉转 svc-engineer 检测**闭环回流 SVC-01，不在本场景直调售后 agent。无 RAG。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问 `http://localhost:8000/agileac/terminal/login`：
- 销售运营子任务：用户名 `sal-ops`
- 电商退换货子任务：用户名 `sal-ecom`

密码 `12345678`。左上角应显示「销售部」。

### 3.2 新建任务

点左栏「New Task / 新建任务」进入任务编辑器。

### 3.3 配置任务（TaskConfigDrawer）

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `sal-ops` 或 `sal-ecom`（个人工作区） | 干净；记忆按四级自动载入 |
| Model | **`glm-5.2`** | 真实模型 id |
| Exec Mode | **`craft`** | agent 需多轮 CRM/ERP + generate_docx |
| 场景模板 | `agileac-sal-01-sales-ecommerce` | **必绑**——子任务切分/催办规则/输出骨架由模板承载 |

> 若 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id`。
>
> **本体 / 记忆不在 drawer 配置**——按用户 scope 自动注入；SAL-01 无 RAG。

### 3.4 在输入框写提示词 + /-mention 选择技能

敲 `/` 弹技能菜单，输入 `sal` 过滤，选中 **`agileac-sal-crm-erp-query`**。

**销售运营子任务**提示词（`sal-ops` 登录，直接复制，约 40 字——**纯业务请求，不带编排/端点指令**）：

```
对敏睿空调逾期应收做催办，输出订单回款报表与催办清单、推送对象。

/agileac-sal-crm-erp-query
```

**电商退换货子任务**提示词（`sal-ecom` 登录，直接复制，约 35 字）：

```
处理敏睿空调电商退换货客诉，输出内部处理清单，客诉转 svc-engineer 检测。

/agileac-sal-crm-erp-query
```

> **四层架构**：user composer 只写**业务目标 + 技能 chip**。子任务切分（订单回款 vs 退换货）、应收催办推送对象、退换货客诉转 svc-engineer 闭环回流 SVC-01、不对客户直接交互——**全部由 Agent 模板 `agileac-sal-01-sales-ecommerce` 的 `system_prompt` 承载**。任务 config 必须绑定 `template_agent_id`。
>
> ⚠️ **关键 1**：`/agileac-sal-crm-erp-query` 必须从 `/` 菜单选 chip。
> ⚠️ **关键 2**：提示词只写业务目标，不写"调 CRM 订单再查应收"这类编排——子任务切分与催办规则全由模板驱动。
> ⚠️ **关键 3**：本体 identifiers.md 已写明销售订单 AGSO、客户 C-AG-、客诉 AGCP、应收 AGINV（与 ERP 共享码空间），跨系统按 invoice_no 关联勿直传异构编码。

#### 资源注入机制（任务运行时自动完成）

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | 按 scope 注入（组织级 CRM/ERP identifiers） | 若干 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` | CRM/ERP 2 systems / ~11 interfaces |
| **RAG** | 无（SAL-01 不绑 RAG；org 级员工综合库 auto-load 仍触发） | — |
| **长期记忆** | 4 级聚合 | 若干 history + facts |
| **技能** | /-mention 解析 + 模板继承 | 1 skill（agileac-sal-crm-erp-query） |
| **记忆沉淀** | extract_memory 抽取 | 0~3 facts |

### 3.5 提交运行

按回车提交。前端创建任务后 `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}`。

### 3.6 观察 SSE 事件流

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载配置（`template:true`） |
| `[trace]` (template) | 场景模板 `agileac-sal-01-sales-ecommerce` 注入 |
| `[trace]` (memory/load) | 长期记忆载入 |
| `[trace]` (ontology) | 组织本体注入（含 CRM/ERP identifiers） |
| `[trace]` (rag) | org 级员工综合库 auto-load（SAL 无部门级 RAG） |
| `[trace]` (data_interface) | 数据接口目录（CRM/ERP） |
| `[trace]` (skill) | /-mention 引用 `agileac-sal-crm-erp-query` |
| `[trace]` (memory/extract) | 记忆沉淀 |
| `[tool_call]` | agent 调 CRM `listSalesOrders`/`listReceivables`（销售运营子任务）；或 CRM `listComplaints`(type=return)/`listCustomers`（电商子任务） |
| `[text]` | LLM 流式输出回款表/催办清单或退换货清单 |
| `[done]` / `[final]` | 收口 + usage + latency |

> 典型 SAL-01 运行约 2–4 分钟。无部门级 RAG，但 org 级员工综合库 auto-load 仍触发 `trace rag`。

---

## 4. 期望输出

### 4.1 销售运营子任务：订单回款报表 + 应收催办清单

**订单回款报表**（销售单号 | 客户 | 订单日期 | 金额 | 状态 | 应收余额 | 逾期天数）：

| 销售单号 | 客户 | 订单日期 | 金额 | 状态 | 应收余额 | 逾期天数 |
|---|---|---|---|---|---|---|
| AGSO20260002 | C-AG-RETAIL-01 | 2026-05-15 | 520,000 | 已发货 | 0 | - |
| AGSO20260005 | C-AG-PROJ-01 | 2026-04-20 | 380,000 | 已对账 | 100,000 | 35 |

**应收催办清单 + 推送对象汇总**：

| 发票号 | 客户 | 应收余额 | 逾期天数 | 催办对象 | 关键提示 |
|---|---|---|---|---|---|
| AGINV202605005 | C-AG-PROJ-01 | ¥100,000 | 35 | sal-ops | 客户已确认下周付款 |

> 推送对象汇总：sal-ops 3 单合计 ¥280,000 / fin-receivable 2 单合计 ¥150,000；催办方式电话+邮件+OA 待办，通过待办机制推送，不直接调用其他部门 agent。

### 4.2 电商退换货子任务：退换货内部处理清单

| 客诉单号 | 客户 | 类型 | 产品 | 原因 | 处理状态 | 催办对象 |
|---|---|---|---|---|---|---|
| AGCP-0003 | C-AG-ECOM-01 | return | P-RC-WALL-15 | 不制冷 | 待检测 | svc-engineer |

> 退换货库存影响：按客诉产品 + 退货数量定性说明（提示质检复检后返销）。客诉转 svc-engineer 检测闭环回流 SVC-01。

### 4.3 .docx 报告附件

agent 调 `generate_docx` 把报表/清单打包成 `敏睿空调_订单回款与电商退换货_YYYYMMDD.docx`（约 30 KB）。

### 4.4 SSE trace 事件

| trace | 含义 | 期望实测值 |
|---|---|---|
| `category=template` | 场景模板注入（必出） | slug=agileac-sal-01-sales-ecommerce + chars |
| `category=ontology` | 组织本体注入 | 含 CRM/ERP identifiers |
| `category=data_interface` | 数据接口目录 | CRM/ERP 2 systems |
| `category=skill` | /-mention 引用技能 | 1 skill |
| `category=memory, subtype=load/extract` | 记忆载入/沉淀 | 若干 facts |

> SAL-01 不绑部门级 RAG，但 org 级员工综合库 auto-load 仍触发 `trace rag`。6 类 trace 全出。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `glm-5.2`
- 智谱 AI provider 未配。修复：管理端配智谱 AI provider + 路由策略 `model_pattern=glm-*`，重跑 `seed_agileac_org.py`。

### 5.2 提示词里 `/agileac-sal-crm-erp-query` 没被识别
- 必须从 `/` 弹窗选 chip，不能手敲。

### 5.3 `[tool_result FAIL]` CRM/ERP 接口调用失败
- mock 网关未起或 API key 不匹配。自检 CRM/ERP 端点（见 §2.5）均应返回 JSON。注意 CRM 用 `crm-agileac-demo-key`、ERP 用 `erp-agileac-demo-key`。

### 5.4 agent 应收走了 ERP `listReceivables`（不存在端点）致 404
- 现象：agent 调 ERP `listReceivables` 返回 not found。
- 根因：ERP 无 listReceivables 端点，**应收走 CRM `listReceivables`**（AGINV 发票号与 ERP 共享码空间）。
- 修复：本体 identifiers.md 已写明 AGINV 跨系统共享；确认 `template:true` + 模板 `## 职责` 段引导走 CRM 应收。

### 5.5 agent 退换货直调售后 agent
- 现象：agent 试图调用 svc-engineer 的 agent（跨 agent 直调）。
- 根因：模板未约束"转 svc-engineer 检测通过待办机制，不直接调用其他部门 agent"。
- 修复：确认 `template:true` + 模板 `## 规则` 段含该约束。

### 5.6 path 参数端点返回 404
- 现象：`getCustomer(code=...)` 返回 `{code} not found`——path 占位符未替换。
- 影响：**不阻塞闭环**。agent 自主降级到 `listCustomers`（query 端点）。
- 修复（可选）：技能 wrapper 按 OpenAPI path 占位符替换。非阻塞性。

### 5.7 `tool_call` args 全 `{}`
- 根因：`_build_tools`（`app/agents/graph/nodes.py`）manifest 占位 schema 覆盖问题。只要有一条 args 非 `{}`（如 `listComplaints(type=...)` 或 `listReceivables(status=...)`）即正常。

### 5.8 trace 里没有 `rag` 事件
- 正常——SAL-01 不绑部门级 RAG，但 org 级员工综合库 auto-load 仍触发 `trace rag`。6 类 trace 全出。

---

## 6. 附：手工调 API 复现

```bash
# 1) 登录拿 user token（销售运营子任务用 sal-ops，电商子任务换 sal-ecom）
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agileac","username":"sal-ops","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 SAL Agent 模板 id
TPL_ID=$(docker exec ai_infra_backend python3 -c "
import asyncio, asyncpg
async def m():
    c=await asyncpg.connect('postgresql://ai_infra:ai_infra@postgres:5432/ai_infra')
    r=await c.fetchrow(\"SELECT id FROM agents WHERE slug='agileac-sal-01-sales-ecommerce'\")
    print(r['id']); await c.close()
asyncio.run(m())")

# 3) 创建任务（绑定模板；skill_ids 留空从模板继承，model=glm-5.2）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"SAL-01 订单回款\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（销售运营子任务短 composer，含 /agileac-sal-crm-erp-query chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"对敏睿空调逾期应收做催办，输出订单回款报表与催办清单、推送对象。\\n\\n/agileac-sal-crm-erp-query\",\"stream\":true}"
```

电商退换货子任务换 `sal-ecom` 登录 + §3.4 电商退换货子任务提示词。短 composer 提示词文本见 §3.4。

---

## 7. 验收要点（演示前自检）

- [ ] `sal-ops` / `sal-ecom` 能登录 `/agileac/terminal/login`，左上角显示「销售部」
- [ ] `GET /api/v1/terminal/resources`（sal-ops token）的 `skills` 含 `agileac-sal-crm-erp-query`（dept: sales）
- [ ] `rag_collections` 不含任何部门级 RAG（SAL-01 无 RAG）
- [ ] `data_interfaces` 含 CRM `listSalesOrders`/`listReceivables`/`listComplaints` + ERP `listVouchers`
- [ ] `load_config` 事件显示 **`template:true`**
- [ ] `trace category=template` 出现（slug=`agileac-sal-01-sales-ecommerce` + chars）
- [ ] SSE 6 类 trace 出现（rag + memory.load + ontology + data_interface + skill + memory.extract）
- [ ] 销售运营子任务 `tool_call` 覆盖 CRM `listSalesOrders` + `listReceivables`；电商子任务覆盖 CRM `listComplaints`(type=return)
- [ ] `tool_call` args 不全 `{}`（至少 `listComplaints(type=...)` 或 `listReceivables(status=...)` 要带参）
- [ ] no-guessing：应收走 CRM `listReceivables`（ERP 无该端点）；AGINV 发票号跨 CRM/ERP 共享；销售订单 AGSO、客户 C-AG-、客诉 AGCP 用对前缀
- [ ] 销售运营子任务输出含订单回款报表 + 应收催办清单 + 推送对象汇总；电商子任务输出含退换货内部处理清单
- [ ] 应收催办通过待办机制推送 sal-ops / fin-receivable；退换货客诉转 svc-engineer 检测回流 SVC-01（不直接调用其他部门 agent，不对客户直接交互）
