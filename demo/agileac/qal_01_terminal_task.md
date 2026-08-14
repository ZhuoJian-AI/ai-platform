# QAL-01 质量数据报表与缺陷闭环 · 终端任务演示

> 质量部质量工程师 `qal-engineer` 登录终端，新建任务、配置 `glm-5.2` + `craft`、`/agileac-qal-mes-plm-query` 选技能、写提示词、运行，agent 自主多轮调 MES `listDefects`/`getDefectRootCause` + PLM `listDefectHistory`/`getStyle` + 检索「质量缺陷案例库」找相似根因 + 质检 SOP，输出来料/制程/出货三段质量报表 + 缺陷闭环待办（催办生产/研发/采购）。
>
> **员工 vibe working 视角**：质量工程师原本要在 MES 翻缺陷、PLM 翻历史故障案例、再手工拼质量报表与 8D 待办——现在一句话拿到三段质量报表 + 5W2H 根因 + 跨部门闭环待办。AI 是质量工程师的副驾驶。
>
> 本场景验证 **痛点 B 质量报表 + C 质检报告 + 缺陷闭环**——与 SVC-01 共用故障案例库方法论但归口部门不同（QAL 质量部来料/制程/出货，SVC 售后部客户报修后诊断）。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 敏睿空调（slug = `agileac`） |
| 用户名 | `qal-engineer` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |
| 部门 | 质量部 · 质量工程组（team: `qal-engineering`） |

> 技能为部门级 `agileac-qal-mes-plm-query`（MES 缺陷/工单 + PLM 历史故障案例/产品款式只读）；RAG 为部门级「质量缺陷案例库」（dept: quality，8 类缺陷 5W2H + 质检 SOP + 8D 闭环）。

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）+ `ai_infra_postgres` 容器在跑。
2. **数据已 seed**（按 `README.md` §9 顺序执行）：
   - `seed_agileac_org.py`（含 `qal-engineer` 用户 + 质量部 + 质量工程组）
   - mock 6 系统 agileac tenant 数据已内置，含 MES 缺陷样本（不制冷/噪音/漏水等 8 类，含 5W2H 根因）+ PLM 历史故障案例 DF-AG-；mock 容器重启即生效
   - `seed_agileac_mock_connectors.py`（含部门级技能 `agileac-qal-mes-plm-query`，MES listDefects/getDefectRootCause/listWorkOrders/getWorkOrder/listProductionOrders + PLM listDefectHistory/listStyles/getStyle）
   - `seed_agileac_ontology.py`（组织级 MES/PLM 各域 `identifiers.md`——**MES 缺陷号 `DF` ≠ PLM 故障案例号 `DF-AG-`，跨系统按 product_code/defect_type 关联勿直传 DF**）
   - `seed_agileac_rag.py`（含部门级「质量缺陷案例库」：8 类缺陷 5W2H + 质检 SOP IQC/IPQC/OQC + 8D 闭环 D1-D8）
   - `seed_agileac_agents.py`（含 `agileac-qal-01-quality-report` agent 模板配置，四层架构 system_prompt）
3. **glm-5.2 已可用**：自检 `GET /api/v1/terminal/models`（qal-engineer token）应含 `glm-5.2`。
4. **qal-engineer 账号已存在且 active**：
   ```bash
   docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
     "SELECT username, is_active FROM users WHERE username='qal-engineer';"
   ```
5. **MES/PLM mock 端点正常**：
   ```bash
   curl -s "http://localhost:8010/mes/defects" -H "X-API-Key: mes-agileac-demo-key" | head
   curl -s "http://localhost:8010/mes/defects/DF20260101/root-cause" -H "X-API-Key: mes-agileac-demo-key" | head
   curl -s "http://localhost:8010/plm/defect-history" -H "X-API-Key: plm-agileac-demo-key" | head
   ```
   均应返回 JSON。

> ⚠️ QAL-01 关键依赖：MES `listDefects`/`getDefectRootCause`（缺陷 + 5W2H 根因）+ PLM `listDefectHistory`（历史故障案例 8 类）+ RAG「质量缺陷案例库」（相似根因 + 质检 SOP + 8D 闭环）。**注意跨码空间**：MES 缺陷号 `DF` 不能直传给 PLM 查历史（PLM 用 `DF-AG-`），须按 `product_code` / `defect_type` 关联。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问 `http://localhost:8000/agileac/terminal/login`，用户名 `qal-engineer`，密码 `12345678`。左上角应显示「质量部」。

### 3.2 新建任务

点左栏「New Task / 新建任务」进入任务编辑器。

### 3.3 配置任务（TaskConfigDrawer）

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `qal-engineer`（个人工作区） | 干净；记忆按四级自动载入 |
| Model | **`glm-5.2`** | 真实模型 id |
| Exec Mode | **`craft`** | agent 需多轮 MES/PLM + RAG + generate_docx |
| 场景模板 | `agileac-qal-01-quality-report` | **必绑**——质检 SOP/8D 闭环规则/输出骨架由模板承载 |

> 若 drawer 暂未暴露「场景模板」选择器，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id`。

### 3.4 在输入框写提示词 + /-mention 选择技能

敲 `/` 弹技能菜单，输入 `qal` 过滤，选中 **`agileac-qal-mes-plm-query`**。

**提示词**（直接复制，约 50 字——**纯业务请求，不带编排/端点指令**）：

```
对敏睿空调本期来料/制程/出货质量做报表，对未闭环缺陷做根因分析与 8D 闭环待办（催办生产/研发/采购）。

/agileac-qal-mes-plm-query
```

> **四层架构**：user composer 只写**业务目标 + 技能 chip**。三段质量报表（IQC/IPQC/OQC）、5W2H 根因、8D 闭环待办分组（生产/研发/采购）、跨码空间关联规则——**全部由 Agent 模板 `agileac-qal-01-quality-report` 的 `system_prompt` 承载**。任务 config 必须绑定 `template_agent_id`。
>
> ⚠️ **关键 1**：`/agileac-qal-mes-plm-query` 必须从 `/` 菜单选 chip。
> ⚠️ **关键 2**：提示词只写业务目标，不写"调 MES 缺陷再查 PLM 历史"这类编排——核对路径与闭环规则全由模板驱动。
> ⚠️ **关键 3**：本体 identifiers.md 已写明 MES 缺陷号 `DF` ≠ PLM 故障案例号 `DF-AG-`，跨系统按 `product_code` / `defect_type` 关联勿直传 DF，否则 404。

#### 资源注入机制（任务运行时自动完成）

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | 按 scope 注入（组织级 MES/PLM identifiers） | 若干 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` | MES/PLM 2 systems / ~8 interfaces |
| **RAG** | agent 绑定部门级「质量缺陷案例库」 | 1 collection / 多 chunks |
| **长期记忆** | 4 级聚合 | 若干 history + facts |
| **技能** | /-mention 解析 + 模板继承 | 1 skill（agileac-qal-mes-plm-query） |
| **记忆沉淀** | extract_memory 抽取 | 0~3 facts |

### 3.5 提交运行

按回车提交。前端创建任务后 `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}`。

### 3.6 观察 SSE 事件流

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载配置（`template:true`） |
| `[trace]` (template) | 场景模板 `agileac-qal-01-quality-report` 注入 |
| `[trace]` (memory/load) | 长期记忆载入 |
| `[trace]` (ontology) | 组织本体注入（含 MES/PLM identifiers + 跨码空间映射） |
| `[trace]` (rag) | 「质量缺陷案例库」检索命中（相似根因 + SOP） |
| `[trace]` (data_interface) | 数据接口目录（MES/PLM） |
| `[trace]` (skill) | /-mention 引用 `agileac-qal-mes-plm-query` |
| `[trace]` (memory/extract) | 记忆沉淀 |
| `[tool_call]` | agent 调 MES `listDefects`/`getDefectRootCause` + PLM `listDefectHistory` |
| `[text]` | LLM 流式输出三段报表/闭环待办 |
| `[done]` / `[final]` | 收口 + usage + latency |

> 典型 QAL-01 运行约 3–5 分钟（多轮 MES/PLM + RAG + LLM 推理 + 记忆节点）。

---

## 4. 期望输出

### 4.1 质量数据报表三段

**来料 IQC**（物料 | 批次 | 抽样数 | 不良数 | 不良率 | AQL 标准 | 结论）：

| 物料 | 批次 | 抽样数 | 不良数 | 不良率 | AQL 标准 | 结论 |
|---|---|---|---|---|---|---|
| M-COMP-GT-24K | BC2026001 | 100 | 0 | 0% | 0.65% | ✓ 合格 |
| M-COND-FIN-30 | BC2026002 | 50 | 1 | 2.0% | 0.65% | ✗ 整批退货 |

**制程 IPQC**（工序 | 巡检数 | 异常数 | 异常率 | 备注）+ **出货 OQC**（产品 | 抽样数 | 不良数 | 不良率 | 结论）同结构。

### 4.2 缺陷闭环待办清单（按生产/研发/采购三部门分组）

| 缺陷 ID | 类型 | 严重度 | 根因 | 永久措施 | 责任部门 | 催办对象 | 时限 |
|---|---|---|---|---|---|---|---|
| DF20260101 | 不制冷 | 高 | 焊接不良致冷媒泄漏 | 100% 充氮保护焊 + 焊缝 X 光抽检 | 生产部 | prod-assembly | 30 天 |
| DF20260105 | 噪音 | 中 | 减振胶垫老化 | 换邵氏 40° 胶垫，寿命 ≥8 年 | 研发部 | rnd-mechanical | 60 天 |

> 永久措施参考 RAG 检索的相似历史案例，标注来源案例号 DF-AG-。跨部门待办通过待办机制推送 prod-assembly / rnd-mechanical / supply-procurement，不直接调用其他部门 agent。

### 4.3 .docx 报告附件

agent 调 `generate_docx` 把两段打包成 `敏睿空调_质量数据报表与缺陷闭环_YYYYMMDD.docx`（约 35 KB）。

### 4.4 SSE trace 事件

| trace | 含义 | 期望实测值 |
|---|---|---|
| `category=template` | 场景模板注入（必出） | slug=agileac-qal-01-quality-report + chars |
| `category=rag` | 相似根因 + SOP 检索 | 命中缺陷类型 5W2H + 质检 SOP chunk |
| `category=ontology` | 组织本体注入 | 含 MES/PLM identifiers + 跨码空间映射 |
| `category=data_interface` | 数据接口目录 | MES/PLM 2 systems |
| `category=skill` | /-mention 引用技能 | 1 skill |
| `category=memory, subtype=load/extract` | 记忆载入/沉淀 | 若干 facts |

> 6 类 trace 全出。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `glm-5.2`
- 智谱 AI provider 未配。修复：管理端配智谱 AI provider + 路由策略 `model_pattern=glm-*`，重跑 `seed_agileac_org.py`。

### 5.2 提示词里 `/agileac-qal-mes-plm-query` 没被识别
- 必须从 `/` 弹窗选 chip，不能手敲。

### 5.3 `[tool_result FAIL]` MES/PLM 接口调用失败
- mock 网关未起或 API key 不匹配。自检 MES/PLM 端点（见 §2.5）均应返回 JSON。

### 5.4 agent 把 MES 缺陷号 `DF` 直传给 PLM 致 404
- 现象：agent 调 `listDefectHistory(defect_id="DF20260101")` 返回 not found。
- 根因：MES 缺陷号 `DF` ≠ PLM 故障案例号 `DF-AG-`，跨系统应按 `product_code` / `defect_type` 关联。
- 修复：本体 identifiers.md 已写明跨码空间映射；确认 `load_config template:true` + 模板 system_prompt 含"跨系统按 product_code 关联勿直传 DF"cue。

### 5.5 path 参数端点（`getDefectRootCause`）返回 404
- 现象：agent 调 `getDefectRootCause(defect_id="DF20260101")` 返回 `{defect_id} not found`——path 占位符未替换。
- 影响：**不阻塞闭环**。agent 自主降级到 `listDefects`（query 端点）仍能拿到缺陷与根因。
- 修复（可选）：技能 wrapper 按 OpenAPI path 占位符替换。非阻塞性。

### 5.6 缺陷根因杜撰（不来自接口/RAG）
- 现象：根因与不良率与 MES 接口返回不符。
- 修复：确认 `template:true` + 模板 `## 闭环规则` 段含"5W2H 严格按接口返回不杜撰"；看 `tool_call` 是否覆盖 MES `getDefectRootCause` + RAG 检索。

### 5.7 `tool_call` args 全 `{}`
- 根因：`_build_tools`（`app/agents/graph/nodes.py`）manifest 占位 schema 覆盖问题。只要有一条 args 非 `{}`（如 `getDefectRootCause(defect_id=...)`）即正常。

### 5.8 memory/extract 抽取 0~3 facts
- 非阻塞；长期记忆跨任务复用弱。

---

## 6. 附：手工调 API 复现

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agileac","username":"qal-engineer","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 QAL Agent 模板 id
TPL_ID=$(docker exec ai_infra_backend python3 -c "
import asyncio, asyncpg
async def m():
    c=await asyncpg.connect('postgresql://ai_infra:ai_infra@postgres:5432/ai_infra')
    r=await c.fetchrow(\"SELECT id FROM agents WHERE slug='agileac-qal-01-quality-report'\")
    print(r['id']); await c.close()
asyncio.run(m())")

# 3) 创建任务（绑定模板；skill_ids 留空从模板继承，model=glm-5.2）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"QAL-01 质量缺陷闭环\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"glm-5.2\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer，含 /agileac-qal-mes-plm-query chip）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"对敏睿空调本期来料/制程/出货质量做报表，对未闭环缺陷做根因分析与 8D 闭环待办（催办生产/研发/采购）。\\n\\n/agileac-qal-mes-plm-query\",\"stream\":true}"
```

---

## 7. 验收要点（演示前自检）

- [ ] `qal-engineer` 能登录 `/agileac/terminal/login`，左上角显示「质量部」
- [ ] `GET /api/v1/terminal/resources`（qal-engineer token）的 `skills` 含 `agileac-qal-mes-plm-query`（dept: quality）
- [ ] `rag_collections` 含「质量缺陷案例库」（dept: quality）
- [ ] `data_interfaces` 含 MES `listDefects`/`getDefectRootCause` + PLM `listDefectHistory`
- [ ] `load_config` 事件显示 **`template:true`**
- [ ] `trace category=template` 出现（slug=`agileac-qal-01-quality-report` + chars）
- [ ] SSE 6 类 trace 出现（rag + memory.load + ontology + data_interface + skill + memory.extract）
- [ ] `tool_call` 覆盖 MES `listDefects`/`getDefectRootCause` + PLM `listDefectHistory`
- [ ] `tool_call` args 不全 `{}`（至少 `getDefectRootCause(defect_id=...)` 要带参）
- [ ] no-guessing：MES 缺陷号 `DF` 不直传给 PLM（PLM 用 `DF-AG-`），跨系统按 product_code/defect_type 关联
- [ ] 输出含三段质量报表（IQC/IPQC/OQC）+ 缺陷闭环待办清单（按生产/研发/采购分组）+ generate_docx 附件
- [ ] 跨部门待办通过待办机制推送 prod-assembly / rnd-mechanical / supply-procurement（不直接调用其他部门 agent）
