# MFG-01 工单进度与产能报表 · 终端任务演示

> 生产制造部排产计划员 `mfg-planner` 登录终端，新建任务、配置 `glm-5.2` + `craft`、`/agileac-mfg-mes-erp-scm-query` 选技能、写提示词、运行，agent 自主多轮调 MES `listWorkOrders`/`listEquipmentStatus`/`getOee`/`listWip` + ERP `listInventory` + SCM `listFabricArrivalPlans`/`listReplenishmentSuggestions`，按"在制/逾期/卡顿"分组输出工单进度表 + 产能报表 + 卡顿催办清单 + 配件到货监管。
>
> **员工 vibe working 视角**：排产计划员原本要在 MES 翻工单、ERP 翻库存、SCM 翻到货，再手工拼排产报表与催办单——现在一句话拿到工单进度 + OEE 产能 + 缺料卡顿催办对象。AI 是排产计划员的副驾驶。
>
> 本场景验证 **痛点 B 生产报表 + E 卡顿催办**——11 场景中无 RAG 的纯数据接口驱动场景（排产规则由模板 system_prompt 承载，与 FIN-01 对账规则同范式；A2 排产规则库待补，非阻塞）。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 敏睿空调（slug = `agileac`） |
| 用户名 | `mfg-planner` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |
| 部门 | 生产制造部 · 排产计划组（team: `prod-planning`） |

> 技能为部门级 `agileac-mfg-mes-erp-scm-query`（MES 工单/产线/OEE + ERP 物料库存 + SCM 到货/补单只读）；**无 RAG**——排产优先级/缺料卡顿/产能预警阈值规则由模板 system_prompt 承载。

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）+ `ai_infra_postgres` 容器在跑。
2. **数据已 seed**（按 `README.md` §9 顺序执行）：
   - `seed_agileac_org.py`（含 `mfg-planner` 用户 + 生产制造部 + 排产计划组）
   - mock 6 系统 agileac tenant 数据已内置，含 MES 工单（在制/逾期/卡顿样本）+ 产线 OEE + ERP 物料库存 + SCM 到货计划（AGFAP-002 压缩机延误样本）；mock 容器重启即生效
   - `seed_agileac_mock_connectors.py`（含部门级技能 `agileac-mfg-mes-erp-scm-query`，MES 9 端点 + ERP 3 端点 + SCM 4 端点）
   - `seed_agileac_ontology.py`（组织级 MES/ERP/SCM 各域 `identifiers.md`——工单 AWO、生产订单 PO、设备 EQ-、物料 M-、到货计划 AGFAP、补单建议 AGRS、交期快照 AGLT 前缀与码空间映射）
   - `seed_agileac_agents.py`（含 `agileac-mfg-01-production-report` agent 模板配置，四层架构 system_prompt）
3. **glm-5.2 已可用**：自检 `GET /api/v1/terminal/models`（mfg-planner token）应含 `glm-5.2`。
4. **mfg-planner 账号已存在且 active**：
   ```bash
   docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
     "SELECT username, is_active FROM users WHERE username='mfg-planner';"
   ```
5. **MES/ERP/SCM mock 端点正常**：
   ```bash
   curl -s "http://localhost:8010/mes/work-orders" -H "X-API-Key: mes-agileac-demo-key" | head
   curl -s "http://localhost:8010/mes/equipment-status" -H "X-API-Key: mes-agileac-demo-key" | head
   curl -s "http://localhost:8010/mes/oee" -H "X-API-Key: mes-agileac-demo-key" | head
   curl -s "http://localhost:8010/erp/inventory" -H "X-API-Key: erp-agileac-demo-key" | head
   curl -s "http://localhost:8010/scm/fabric-arrival-plans" -H "X-API-Key: scm-agileac-demo-key" | head
   ```
   均应返回 JSON 列表。

> ⚠️ MFG-01 关键依赖：MES `listWorkOrders`/`listEquipmentStatus`/`getOee`/`listWip`（工单进度 + 产能）+ ERP `listInventory`（物料现货 + 安全库存）+ SCM `listFabricArrivalPlans`/`listReplenishmentSuggestions`（到货监管 + 补单）。无 RAG——排产规则由模板 system_prompt 承载。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问 `http://localhost:8000/agileac/terminal/login`，用户名 `mfg-planner`，密码 `12345678`。左上角应显示「生产制造部」。

### 3.2 新建任务

点左栏「New Task / 新建任务」进入任务编辑器。

### 3.3 配置任务（TaskConfigDrawer）

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `mfg-planner`（个人工作区） | 干净；记忆按四级自动载入 |
| Model | **`glm-5.2`** | 真实模型 id |
| Exec Mode | **`craft`** | agent 需多轮跨 MES/ERP/SCM + generate_docx |
| 场景模板 | `agileac-mfg-01-production-report` | **必绑**——排产规则/卡顿催办/输出骨架由模板承载 |

> 若 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id`。
>
> **本体 / 记忆不在 drawer 配置**——按用户 scope 自动注入；MFG-01 无 RAG（排产规则由模板 system_prompt 承载）。

### 3.4 在输入框写提示词 + /-mention 选择技能

敲 `/` 弹技能菜单，输入 `mfg` 过滤，选中 **`agileac-mfg-mes-erp-scm-query`**。

**提示词**（直接复制，约 45 字——**纯业务请求，不带编排/端点指令**）：

```
扫敏睿空调当前在制/逾期工单与产线产能，标出卡顿节点与缺料预警，输出催办清单。

/agileac-mfg-mes-erp-scm-query
```

> **四层架构**：user composer 只写**业务目标 + 技能 chip**。排产优先级（旺季家用优先）、缺料卡顿优先级（压缩机 M-COMP-GT-24K 单源长交期最高）、产能预警阈值（OEE<70% 标 ⚠️）、卡顿催办对象——**全部由 Agent 模板 `agileac-mfg-01-production-report` 的 `system_prompt` 承载**。任务 config 必须绑定 `template_agent_id`。
>
> ⚠️ **关键 1**：`/agileac-mfg-mes-erp-scm-query` 必须从 `/` 菜单选 chip。
> ⚠️ **关键 2**：提示词只写业务目标，不写"调 MES 工单再调 ERP 库存"这类编排——跨系统路径与排产规则全由模板驱动。
> ⚠️ **关键 3**：本体 identifiers.md 已写明工单 AWO、设备 EQ-RC-/EQ-CC-/EQ-TST-、物料 M-、到货 AGFAP，跨系统按 work_order_no / material_code 关联勿直传异构编码。

#### 资源注入机制（任务运行时自动完成）

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | 按 scope 注入（组织级 MES/ERP/SCM identifiers） | 若干 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` | MES/ERP/SCM 3 systems / ~16 interfaces |
| **RAG** | 无（MFG-01 不绑 RAG；org 级员工综合库 auto-load 仍触发） | — |
| **长期记忆** | 4 级聚合 | 若干 history + facts |
| **技能** | /-mention 解析 + 模板继承 | 1 skill（跨 3 系统） |
| **记忆沉淀** | extract_memory 抽取 | 0~3 facts |

### 3.5 提交运行

按回车提交。前端创建任务后 `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}`。

### 3.6 观察 SSE 事件流

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载配置（`template:true`） |
| `[trace]` (template) | 场景模板 `agileac-mfg-01-production-report` 注入 |
| `[trace]` (memory/load) | 长期记忆载入 |
| `[trace]` (ontology) | 组织本体注入（含 MES/ERP/SCM identifiers） |
| `[trace]` (rag) | org 级员工综合库 auto-load（MFG 无部门级 RAG） |
| `[trace]` (data_interface) | 数据接口目录（MES/ERP/SCM） |
| `[trace]` (skill) | /-mention 引用 `agileac-mfg-mes-erp-scm-query` |
| `[trace]` (memory/extract) | 记忆沉淀 |
| `[tool_call]` | agent 调 MES `listWorkOrders`/`listEquipmentStatus`/`getOee` + ERP `listInventory` + SCM `listFabricArrivalPlans` |
| `[text]` | LLM 流式输出工单表/产能表/催办清单 |
| `[done]` / `[final]` | 收口 + usage + latency |

> 典型 MFG-01 运行约 3–5 分钟（跨 3 系统 tool 调用 + LLM 推理 + 记忆节点）。无部门级 RAG，但 org 级员工综合库 auto-load 仍触发 `trace rag`。

---

## 4. 期望输出

### 4.1 工单进度汇总表

| 工单号 | 产品 | 工厂/产线 | 状态 | 计划完工 | 实际完工 | 剩余天数 | 风险等级 |
|---|---|---|---|---|---|---|---|
| AWO20260101 | P-RC-WALL-15 | 总装1线 | 在制 | 2026-07-05 | - | 2 | 中 |
| AWO20260105 | P-RC-CAB-30 | 总装2线 | 逾期 | 2026-06-30 | - | -5 | 高 |

### 4.2 产能报表

| 产线 | 今日 OEE | 可用率 | 性能 | 质量 | 停机时长 | 备注 |
|---|---|---|---|---|---|---|
| 总装1线 | 82% | 90% | 92% | 98% | 45min | 设备正常 |
| 总装2线 | 65% | 70% | 90% | 99% | 240min | ⚠️ OEE<70% 换线停机 |

### 4.3 卡顿催办清单 + 配件到货监管

| 工单号 | 卡顿节点 | 责任部门 | 催办对象 | 关键提示 |
|---|---|---|---|---|
| AWO20260105 | 缺压缩机 M-COMP-GT-24K | 供应链部 | supply-procurement | 旺季延迟 7 天，需提前 60 天下单 |

> 配件到货监管：AGFAP-002 压缩机 M-COMP-GT-24K 延误 7 天 → 影响 AWO20260105。催办通过待办机制推送 supply-procurement，不直接调用其他部门 agent。

### 4.4 .docx 报告附件

agent 调 `generate_docx` 把三段打包成 `敏睿空调_工单进度与产能报表_YYYYMMDD.docx`（约 30 KB）。

### 4.5 SSE trace 事件

| trace | 含义 | 期望实测值 |
|---|---|---|
| `category=template` | 场景模板注入（必出） | slug=agileac-mfg-01-production-report + chars |
| `category=ontology` | 组织本体注入 | 含 MES/ERP/SCM identifiers |
| `category=data_interface` | 数据接口目录 | MES/ERP/SCM 3 systems |
| `category=skill` | /-mention 引用技能 | 1 skill（跨 3 系统） |
| `category=memory, subtype=load/extract` | 记忆载入/沉淀 | 若干 facts |

> MFG-01 不绑部门级 RAG，但 org 级员工综合库 auto-load 仍触发 `trace rag`（命中含"工单/排产/库存"关键词 chunk，非阻塞）。6 类 trace 全出。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `glm-5.2`
- 智谱 AI provider 未配。修复：管理端配智谱 AI provider + 路由策略 `model_pattern=glm-*`，重跑 `seed_agileac_org.py`。

### 5.2 提示词里 `/agileac-mfg-mes-erp-scm-query` 没被识别
- 必须从 `/` 弹窗选 chip，不能手敲。

### 5.3 `[tool_result FAIL]` 跨系统接口调用失败
- mock 网关未起或 API key 不匹配。自检 MES/ERP/SCM 端点（见 §2.5）均应返回 JSON。注意每个系统用各自 agileac demo key（mes/erp/scm-agileac-demo-key）。

### 5.4 agent 只调了 MES 没跨系统
- 现象：只调 `listWorkOrders`，没调 ERP `listInventory` / SCM `listFabricArrivalPlans`，缺料卡顿与到货监管缺失。
- 根因：模板 system_prompt 的 `## 职责` 跨系统路径未引导，或 `load_config template:false`（模板未注入）。
- 修复：确认 `template:true` + 模板 system_prompt 含"调 ERP 库存 → 调 SCM 到货"跨系统路径。

### 5.5 trace 里没有 `rag` 事件
- 正常——MFG-01 不绑部门级 RAG（排产规则由模板 system_prompt 承载），但 org 级员工综合库 auto-load 仍触发 `trace rag`。6 类 trace 全出。

### 5.6 path 参数端点（`getWorkOrder`/`getOee`）返回 404
- 现象：agent 调 `getWorkOrder(won="AWO20260101")` 返回 `{won} not found`——path 占位符未替换。
- 影响：**不阻塞闭环**。agent 自主降级到 `listWorkOrders`/`listEquipmentStatus`（query 参数端点）仍能拿到完整信息。
- 修复（可选）：技能 wrapper 按 OpenAPI path 占位符替换。非阻塞性。

### 5.7 `tool_call` args 全 `{}`
- 根因：`_build_tools`（`app/agents/graph/nodes.py`）manifest 占位 schema 覆盖问题。只要有一条 args 非 `{}`（如 `getOee(line=...)`）即正常；全 `{}` 立即查 `nodes.py`。

### 5.8 排产规则杜撰（不来自模板）
- 现象：催办对象/优先级与模板 system_prompt 规则不符。
- 修复：确认 `template:true` + 模板 `## 排产与卡顿规则` 段已注入（trace template chars）。

---

## 6. 附：手工调 API 复现

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agileac","username":"mfg-planner","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 MFG Agent 模板 id
TPL_ID=$(docker exec ai_infra_backend python3 -c "
import asyncio, asyncpg
async def m():
    c=await asyncpg.connect('postgresql://ai_infra:ai_infra@postgres:5432/ai_infra')
    r=await c.fetchrow(\"SELECT id FROM agents WHERE slug='agileac-mfg-01-production-report'\")
    print(r['id']); await c.close()
asyncio.run(m())")

# 3) 创建任务（绑定模板；skill_ids 留空从模板继承，model=glm-5.2）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"MFG-01 工单产能\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer，含 /agileac-mfg-mes-erp-scm-query chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"扫敏睿空调当前在制/逾期工单与产线产能，标出卡顿节点与缺料预警，输出催办清单。\\n\\n/agileac-mfg-mes-erp-scm-query\",\"stream\":true}"
```

---

## 7. 验收要点（演示前自检）

- [ ] `mfg-planner` 能登录 `/agileac/terminal/login`，左上角显示「生产制造部」
- [ ] `GET /api/v1/terminal/resources`（mfg-planner token）的 `skills` 含 `agileac-mfg-mes-erp-scm-query`（dept: production）
- [ ] `rag_collections` 不含任何部门级 RAG（MFG-01 无 RAG，排产规则由模板承载）
- [ ] `data_interfaces` 含 MES/ERP/SCM 3 系统端点
- [ ] `load_config` 事件显示 **`template:true`**
- [ ] `trace category=template` 出现（slug=`agileac-mfg-01-production-report` + chars）
- [ ] SSE 6 类 trace 出现（rag + memory.load + ontology + data_interface + skill + memory.extract）
- [ ] `tool_call` 跨 3 系统（MES `listWorkOrders`/`listEquipmentStatus`/`getOee` + ERP `listInventory` + SCM `listFabricArrivalPlans`）
- [ ] `tool_call` args 不全 `{}`（至少 `getOee(line=...)` 或 `listWorkOrders(won=...)` 要带参）
- [ ] no-guessing：agent 用对工单 AWO、设备 EQ-、物料 M-、到货 AGFAP 前缀；跨系统按 work_order_no / material_code 关联
- [ ] 输出含工单进度表 + 产能报表（OEE<70% 标 ⚠️）+ 卡顿催办清单 + 配件到货监管 + generate_docx 附件
- [ ] 卡顿催办通过待办机制推送 supply-procurement（不直接调用其他部门 agent）
