# 星途服装 · 7 场景 Demo 演示

`ai_infra` 平台 + AgileBuddy 通用智能体在服装企业的 7 个 AI 应用场景演示。
覆盖 **产品开发 3 场景 + 供应链 4 场景**。

> **演示方式说明**：7 个场景全部走**终端任务方式**——每个场景由其**归口部门**的业务用户登录终端（PD-1=开发部长 `dev-lead`、PD-2=面料开发员 `fabric-dev`、PD-3=品控部长 `qc-lead`、SC-1=供应链部长 `supply-lead`、SC-2=生产部长 `prod-lead`、SC-3=财务部长 `finance-lead`、SC-4=商品部长 `merch-lead`），新建任务、配置模型（claude-opus-4 / claude-sonnet-4，按场景 agent 模板默认）、写提示词、`/-mention` 选择技能后运行，详见 [`pd1_terminal_task.md`](./pd1_terminal_task.md) / [`pd2_terminal_task.md`](./pd2_terminal_task.md) / [`pd3_terminal_task.md`](./pd3_terminal_task.md) / [`sc1_terminal_task.md`](./sc1_terminal_task.md) / [`sc2_terminal_task.md`](./sc2_terminal_task.md) / [`sc3_terminal_task.md`](./sc3_terminal_task.md) / [`sc4_terminal_task.md`](./sc4_terminal_task.md)。旧 shell 脚本（`sc3_reconciliation.sh` / `sc4_price_ledger.sh`）保留作历史对照。

> **部门级 scope 拆分**：自 2026-07-11 起，星途服装组织的所有资源（本体 / 数据接口 / 技能 / RAG / 工作区 / 记忆）已按**部门级别**重新拆分。每个场景的归口用户只能看到本部门 scope 内的资源——既允许跨部门数据流转（通过在调用方部门下重新实现一份数据接口，按需开放端点），又确保每个部门的数据接口暴露面是显式授权的。详细 scope 模型见 [`SCENARIO_AUTHORING_GUIDE.md`](./SCENARIO_AUTHORING_GUIDE.md)。

> **新增场景请先读 [`SCENARIO_AUTHORING_GUIDE.md`](./SCENARIO_AUTHORING_GUIDE.md)**——7 步搭建法 + 9 类常见故障 + 验收清单，沉淀自 PD-1～SC-4 全过程踩过的坑。

---

## 1. 演示矩阵

| 场景 | Demo 方式 | 归口部门 | 归口用户 | Agent slug | 绑定技能 | RAG / 本体 |
|---|---|---|---|---|---|---|
| **PD-1** 逾期订单风险汇总与推送 | [`pd1_terminal_task.md`](./pd1_terminal_task.md) | 开发部 | `dev-lead` | — | PLM 查询（开发部级） | — |
| **PD-2** 关键面料成本交期产能测算与异动检测 | [`pd2_terminal_task.md`](./pd2_terminal_task.md) | 设计部 | `fabric-dev` | `starclothing-pd2-fabric-library` | SCM 查询（设计部级） | — |
| **PD-3** 新品缺陷风险预警与闭环待办 | [`pd3_terminal_task.md`](./pd3_terminal_task.md) | 品控部 | `qc-lead` | `starclothing-pd3-defect-closure` | PLM 查询（品控部 proxy） | 服装缺陷知识库（品控部级） |
| **SC-1** 来料批次物料校验与异常回写 | [`sc1_terminal_task.md`](./sc1_terminal_task.md) | 供应链部 | `supply-lead` | `starclothing-sc1-material-validation` | SCM + MES 查询（供应链部级） | — |
| **SC-2** 下周工单产线排程与风险提示 | [`sc2_terminal_task.md`](./sc2_terminal_task.md) | 生产部 | `prod-lead` | `starclothing-sc2-factory-scheduling` | MES + SCM 查询（生产部级） | — |
| **SC-3** 跨系统单据对账与差异闭环 | [`sc3_terminal_task.md`](./sc3_terminal_task.md) | 财务部 | `finance-lead` | `starclothing-sc3-reconciliation` | ERP + MES + CRM 查询（财务部级） | — |
| **SC-4** 采购报价比对与成本台账建议 | [`sc4_terminal_task.md`](./sc4_terminal_task.md) | 商品部 | `merch-lead` | `starclothing-sc4-price-comparison` | SCM + ERP 查询（商品部级） | — |

---

## 2. 前置条件

### 2.1 平台已部署
- Docker Compose 起来后端（`ai_infra_backend`，端口 8000）+ mock（`ai_infra_mock`，端口 8010）。
- 后端容器内可访问 mock：`http://ai_infra_mock:8010`（容器互联）。
- 主机端可访问后端：`http://localhost:8000`。

### 2.2 数据已 seed（按顺序执行）
```bash
# 所有 seed 脚本统一放在 demo/starclothing/scripts/ 下，每次执行都需 docker cp 到 backend 容器内：
SCRIPTS=(
  seed_starclothing_apparel.py            # 组织/部门/用户/路由策略/组织级 APIKey
  seed_starclothing_mock_connectors.py    # 5 个 mock 系统连接器 + 技能 + 数据接口
  seed_starclothing_ontology.py           # PLM/SCM/Cross 三文件夹本体
  seed_starclothing_defect_rag.py         # 服装缺陷知识库（8 类缺陷案例）
  seed_starclothing_agents.py             # 7 个业务 Agent 配置
)
for s in "${SCRIPTS[@]}"; do
  docker cp /root/ai_infra/demo/starclothing/scripts/$s ai_infra_backend:/app/scripts/$s
  docker exec ai_infra_backend python scripts/$s
done
```

### 2.3 LLM Provider 已配置
- 在管理端「星途服装」组织 → LLM Provider 页配置至少一个可用 Provider（如 Anthropic Claude / 阿里云通义 / DeepSeek），并确保路由策略（`model_pattern` 如 `claude-*`/`gpt-*`/`deepseek-*`）指向真实可用 provider——终端下拉直接列真实模型 id，无别名层。
- 若 Provider 未配置或 API Key 失效，SSE 会显示 `[step] load_config → [phase] llm #0 → [final]` 但无 `[text]` 事件（LLM 调用 403/超时）。

### 2.4 超管账号
- 演示脚本默认使用 `root / Sjp19831209`（super admin）登录。
- 生产环境请改为最小权限的 `org_admin`（在「星途服装」组织下创建组织级管理员）。

---

## 3. 运行演示

### 3.1 PD-1 / PD-2 / PD-3 / SC-1 / SC-2 终端任务方式（推荐）

按 [`pd1_terminal_task.md`](./pd1_terminal_task.md) / [`pd2_terminal_task.md`](./pd2_terminal_task.md) / [`pd3_terminal_task.md`](./pd3_terminal_task.md) / [`sc1_terminal_task.md`](./sc1_terminal_task.md) / [`sc2_terminal_task.md`](./sc2_terminal_task.md) 走 UI 流程：浏览器访问 `http://localhost:8000/starclothing/terminal/login`，用**场景归口用户**登录（PD-1=`dev-lead` / PD-2=`fabric-dev` / PD-3=`qc-lead` / SC-1=`supply-lead` / SC-2=`prod-lead`，统一密码 `12345678`），新建任务、选 `claude-opus-4` / `claude-sonnet-4` 等真实模型 id、写提示词、`/starclothing-{plm,scm,mes}-query` 选技能、运行。**每个归口用户只能看到本部门 scope 内的资源**——这是部门级 scope 拆分后的安全模型。

### 3.2 其余 2 场景：shell 脚本方式

```bash
cd /root/ai_infra/demo/starclothing

# 任选一个场景执行（脚本会自动登录 → 找 agent → SSE 流式打印）：
./sc3_reconciliation.sh      # 跨系统单据对账与差异闭环
./sc4_price_ledger.sh        # 采购报价比对与成本台账建议

# SC-1 / SC-2 旧 shell 脚本保留以备对照（推荐改用 terminal_task.md 终端方式）：
./sc1_material_validation.sh # 来料批次物料校验与异常回写（旧版）
./sc2_factory_scheduling.sh  # 下周工单产线排程与风险提示（旧版）

# 自定义后端地址 / 凭据：
BACKEND_HOST=192.168.1.10 BACKEND_PORT=8000 \
ADMIN_USER=orgadmin ADMIN_PASS=xxxx \
./sc3_reconciliation.sh
```

### 3.1 SSE 事件类型
脚本会把后端的 SSE 流解析为可读输出：

```
[step]    load_config / save_memory / extract_memory / judge / write_run_log
[phase]  llm #0  /  llm #1   每个 LLM 调用轮次
[text]    直接流式打印 LLM 输出 token（无前缀）
[tool_call]     工具调用名 + 参数
[tool_result]   工具返回内容（成功 ✓ / 失败 ✗）
[final]   latency=...ms session=...
[error]  执行错误信息
```

---

## 4. 数据来源（mock 多租户）

星途服装的数据全部来自 mock 系统（`mock/` 目录），与「敏睿制造」共用同一套 mock，通过 **X-API-Key 区分租户**：

| Mock 系统 | 端口 | 星途服装 API Key | 用途 |
|---|---|---|---|
| PLM | 8010 `/plm` | `plm-starclothing-demo-key` | 款式 / 面料 / BOM / 打样 / 大货 / QC / 缺陷案例 / 成本台账 / 可行性 |
| SCM | 8010 `/scm` | `scm-starclothing-demo-key` | 供应商 / 报价 / 产能日历 / 面料到货 / 补货 / 交期快照 / 物料校验 |
| ERP | 8010 `/erp` | `erp-starclothing-demo-key` | 物料档案 / 采购订单 / 库存 / 生产成本 / 应付应收 / 收款 |
| MES | 8010 `/mes` | `mes-starclothing-demo-key` | 工单 / 产品 / 产线 / 缺陷 / 库存 |
| CRM | 8010 `/crm` | `crm-starclothing-demo-key` | 客户 / 销售订单 / 投诉 |

### 4.1 服装真实款号（mock 内置）
- 双面呢大衣：`P-FW2026-001`（羊毛/羊绒，工单 `XWO20260789`）
- 压胶冲锋衣：`P-FW2026-002`（工单 `XWO20260788`、`XWO20260800`、`XWO20260811`）
- 纯棉 T 恤：`P-SS2026-010`（工单 `XWO20260801`、`XWO20260803`）
- 牛仔裤：`P-SS2026-020`（工单 `XWO20260808`）
- 风衣：`P-AP2026-030`（工单 `XWO20260810`）
- 衬衫：`P-AP2026-031` / 卫衣：`P-AP2026-032` / 摇粒绒开衫：`P-SS2026-011`

### 4.2 跨系统数据闭环
- ERP `production_costs.work_order_no` → MES `work_orders.work_order_no`
- CRM `complaints.work_order_no` → MES `work_orders.work_order_no`
- PLM `defect_history.work_order_no` → MES `work_orders.work_order_no`
- SCM `quotations.material_code` → ERP `materials.code` → PLM `bom.fabric_code`

---

## 5. 7 个场景的 AI 价值

| 场景 | 替代人工 | AI 增值 |
|---|---|---|
| **PD-1** 逾期订单风险汇总与推送 | 跟单员手工巡单 Excel | 7×24 自动扫描 + 逾期推送 + 风险分级 + 补救建议 |
| **PD-2** 关键面料成本交期产能测算与异动检测 | 面料开发员查 SCM/问供应商 | 实时交期（cached:false 永不缓存）+ 异动检测 + 多供应商评分 |
| **PD-3** 新品缺陷风险预警与闭环待办 | 品质部经验复盘 | 8 类历史缺陷 RAG 检索 + 评审必查项 + 试产/量产验证标准 |
| **SC-1** 来料批次物料校验与异常回写 | 仓管员逐批对 BOM | BOM 一致性 + 资质有效期 + 让步规则 + 工单锁定闭环 |
| **SC-2** 下周工单产线排程与风险提示 | 计划员手排产线 | 工单 + 产线 + 产能 + 到货 + 补货四源联动 + 瓶颈识别 |
| **SC-3** 跨系统单据对账与差异闭环 | 财务逐单核对 | CRM↔MES↔ERP 三系统跨表对账 + 差异率 + 异常清单 |
| **SC-4** 采购报价比对与成本台账建议 | 采购员询价比价 | 多供应商评分（价格40%+交期30%+账期30%）+ 异动检测 + 成本台账建议 |

---

## 6. 故障排查

### 6.1 登录失败
```
[err] 登录失败：{"detail":"Invalid username or password"}
```
→ 检查 `ADMIN_USER` / `ADMIN_PASS` 环境变量；或后端未 seed super admin（运行 `POST /api/v1/auth/ensure-super-admin`）。

### 6.2 找不到组织 / Agent
```
[err] 未找到组织 slug=starclothing
[err] 未找到 agent slug=starclothing-pd1-product-monitor
```
→ 未完成 seed。按 §2.2 顺序执行 5 个 seed 脚本。

### 6.3 SSE 无 text 输出
```
[step] load_config ...
[phase] llm #0
[final] latency=...ms session=...
```
→ LLM Provider 未配置或 API Key 失效。在管理端「星途服装」组织 → LLM Provider 页配置 Provider，并确保 `claude-*` 等真实模型 id 在 provider 的 `supported_models` 里且路由策略指向可用 provider。

### 6.4 工具调用失败
```
[tool_result FAIL] tool error: ...
```
→ mock 系统未启动或 API Key 不匹配：
```bash
docker ps | grep ai_infra_mock
curl -s http://localhost:8010/plm/styles -H "X-API-Key: plm-starclothing-demo-key" | head
```

---

## 7. 文件清单

```
demo/starclothing/
├── README.md                       # 本文档
├── SCENARIO_AUTHORING_GUIDE.md     # 场景搭建方法论 + 故障排查（新增场景先读此）
├── pd1_terminal_task.md            # PD-1 终端任务演示（dev-lead 业务用户身份）
├── pd2_terminal_task.md            # PD-2 终端任务演示（fabric-dev，关键面料成本交期产能测算与异动检测）
├── pd3_terminal_task.md            # PD-3 终端任务演示（qc-lead，新品缺陷风险预警与闭环待办 + RAG 检索）
├── sc1_terminal_task.md            # SC-1 终端任务演示（supply-lead，来料批次物料校验与异常回写，SCM + MES）
├── sc2_terminal_task.md            # SC-2 终端任务演示（prod-lead，下周工单产线排程与风险提示，MES + SCM）
├── _common.sh                       # 通用函数：登录 / 解析 org_id / 解析 agent_id / SSE 解析
├── pd1_overdue_push.sh              # PD-1 旧脚本方式（保留以备对照，推荐改用 pd1_terminal_task.md）
├── pd2_fabric_leadtime.sh           # PD-2 旧脚本方式（保留以备对照，推荐改用 pd2_terminal_task.md）
├── pd3_defect_warning.sh            # PD-3 旧脚本方式（保留以备对照，推荐改用 pd3_terminal_task.md）
├── sc1_material_validation.sh       # SC-1 旧脚本方式（保留以备对照，推荐改用 sc1_terminal_task.md）
├── sc2_factory_scheduling.sh        # SC-2 旧脚本方式（保留以备对照，推荐改用 sc2_terminal_task.md）
├── sc3_reconciliation.sh            # SC-3 跨系统单据对账与差异闭环
└── sc4_price_ledger.sh              # SC-4 采购报价比对与成本台账建议
```

对应的 seed 脚本在 `demo/starclothing/scripts/`：
```
seed_starclothing_apparel.py            # 组织/部门/用户/路由/APIKey
seed_starclothing_mock_connectors.py    # 5 个 mock 连接器 + 技能 + 数据接口
seed_starclothing_ontology.py            # PLM/SCM/Cross 三文件夹本体
seed_starclothing_defect_rag.py          # 服装缺陷知识库 RAG
seed_starclothing_agents.py              # 7 个业务 Agent 配置
reembed_defect_rag.py             # NULL embedding 回填（embedding 失败时用）
```
