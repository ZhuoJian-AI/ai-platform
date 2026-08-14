# 未修 known issue 清单

> Starclothing demo 已知但未根治的问题。**绕过 ≠ 修复**——这些问题在 PD-1/PD-2/PD-3
> 各场景的 §5.x 故障排查里都标了"非阻塞 / 修复（可选）"，新组织 demo 应该
> 知道哪些坑是"绕过"路径通过、哪些是真"修了"。

---

## Issue #1 · Path-param 占位符未替换（已修）

### 现象
agent 调 path 参数端点时返回：
```
{"detail":"style {style_code} not found"}
{"detail":"fabric {fabric_code} not found"}
{"detail":"bulk order {bulk_no} not found"}
{"detail":"sampling order {sampling_no} not found"}
```

`{style_code}` 等占位符**字面未被替换**为实际入参值。

### 影响端点（Starclothing 范围内）
- PLM：`getStyle` / `getFabric` / `getBulkOrder` / `getSamplingProgress` / `getCostLedger` 等 `/api/v1/xxx/{code}` 形式
- SCM：`getQuotation` / `getSupplier` / `getSupplierCapacity` 等
- 任何 OpenAPI path 含 `{占位符}` 的端点

### 根因
技能 wrapper 把 path 参数当作 query/body 参数透传，未替换到 OpenAPI path 占位符。LLM 看到 `style_code` 在 args schema 里，传了值，但 wrapper 调 mock 时把 `style_code=P-FW2026-001` 当 query string 透传，未替换 URL 里的 `{style_code}`。

### 修复状态
**已修**（executor.py `execute_endpoint`）：在拼装 URL 前遍历入参，凡 `{name}` 出现在 `endpoint.path` 中即用 `urllib.parse.quote` 替换进路径并从 query/body 参数移除，剩余参数再按 GET→query / 其余→body 放置。混合端点（如 `calcFabricCost` 的 path `fabric_code` + query `style_code`）也被正确处理。已对 `getStyle` / `getBulkOrder` / `getSamplingProgress` / `calcFabricCost` 用真实 mock 数据回归通过。

### 全场景回归验证（v7）
| 场景 | path 端点 | v7 调用 / 失败 | 结论 |
|---|---|---|---|
| PD-1（dev-lead, PLM） | `getStyle` / `getBulkOrder` / `getSamplingProgress` | 17 次 tool_call **0 失败** | 占位符全部替换，直接命中真实数据（`pd1 §4.5 v7`） |
| PD-2（fabric-dev, SCM） | 无（SCM 全 query 端点） | 0 path 端点 | 从未受影响（`pd2 §4.6`） |
| PD-3（qc-lead, PLM） | `getStyle` / `getFabric` | `getStyle` 2/0 ✓；`getFabric` 4/2（残留失败为 agent 把 `M-*` 物料码误当 `F-*` 面料码，**占位符已替换**） | path-param bug 根治（`pd3 §4.6 v7` / §5.13） |
| SC-1（supply-lead, MES+SCM） | `getWorkOrder` / `getSupplier` | `getSupplier` 7/0 ✓；`getWorkOrder` 16/6（残留失败为 agent 猜测缺 `X` 前缀的工单号，**占位符已替换**） | path-param bug 根治（`sc1 §4.6 v7` / §5.7） |

> 所有场景的 tool_result 失败信息中**不再出现 `{占位符}` 字面**——残留失败均为
> agent 标识符推断偏差（传了 mock 数据里不存在的码），agent 自主降级到 list 端点
> 后闭环仍完整。这与 Issue #1（占位符未替换）是不同类别的问题。

### 参考文档
- `pd3_terminal_task.md` §5.13
- `pd1_terminal_task.md` §5.10
- `sc1_terminal_task.md` §5.7

---

## Issue #2 · memory/extract 抽取 0~3 facts（已修）

### 现象
`trace memory/extract` 多数轮次 `facts: 0`，偶尔抽到 3 facts。

### 实测数据（修复前）
| 场景 | 轮次 | facts |
|---|---|---|
| PD-1 v5 | 1 次 | 3 |
| PD-1 v6 | 1 次 | 0 |
| PD-2 v6 | 1 次 | 0 |
| PD-3 v3 | 1 次 | 0 |

### 根因（两层，第二层才是真因）
1. **prompt 偏保守**：原 prompt「不要抽取一次性任务细节、不要抽取临时数据」把 PD-2
   的结论性事实（面料→首选供应商、面料→交期异动 Δ）也当任务细节跳过。
2. **（真因）JSON 解析失败**：glm-5.2 非流式返回常把 JSON 包在 ``` ```json ``` ```
   markdown 围栏里（大输入时尤甚），`json.loads("```json\n{...}")` 首字符是反引号 →
   抛 `Expecting value: line 1 column 1 (char 0)`，被 `except` 吞掉 → facts 静默归零。
   后端日志连发 `extract_memory_failed error='Expecting value: line 1 column 1 (char 0)'`。

### 修复状态（已修，v7d5）
- **prompt 改为显式三元组抽取**（`nodes.py` `extract_memory`）：要求「实体 → 属性 → 值」
  短句，区分「可复用结论事实」vs「过程性数据」，给具体示例，限 8 条宁缺毋滥。
- **`_parse_json_lenient` 容错解析**（`nodes.py` 新增）：先剥 ``` ```json ``` ``` 围栏；
  仍失败则取首个 `{` 到末个 `}` 子串再试；全失败返回 `{}`（不抛异常、不静默归零）。
  堵住推理模型非流式 markdown-fence 包裹导致的 `char 0` 解析失败。

### 验证（PD-2 v7d5，task 2d8e4f23）
- `trace memory/extract` **facts: 0 → 8** ✓
- 后端 `extract_memory_failed` 日志：本轮 **0 条**（修复前每轮 1 条 char 0）✓
- 个人记忆行 `updated_at` 刷新，含 8 条结构化三元组（如「M-FLEECE-280 → 首选供应商
  → XS-FAB-001（36元/m，Δ=0）」「XS-FAB-003 → 产能状态 → 91%满载+异动+15天」）✓
- 27 tool_call / 27 tool_result，0 失败；generate_docx 闭环；template:true ✓

### 影响范围
此修复在 `extract_memory` 节点（general 模式所有终端任务共用），PD-1 / PD-3 / SC-1
同款 glm-5.2 + 同款 fence 解析坑一并受益——三场景的记忆沉淀通道从「基本归零」变为
「正常抽取」。跨任务复用（下次跑同场景可命中上轮 facts）正式生效。

### 参考文档
- `pd1_terminal_task.md` §5.11
- `pd2_terminal_task.md` §5.13
- `pd3_terminal_task.md` §5.14

---

## Issue #3 · 跨 agent 任务交接机制缺失（未修，文字承诺）

### 现象
PD-3 prompt 要求"未落实项标注闭环待办并提示 PD-1 监管 Agent 跟进"，但 PD-3 是单次任务执行，**没有真正的跨 agent 调用 / 队列交接机制**。agent 只是在 .docx 里写了一句"需 PD-1 监管 Agent 跟进"——文字层面的承诺，没有实际触发 PD-1 agent 任务。

### 根因
当前 agent 框架不支持跨 agent 任务交接：
- agent A 完成任务后不能调用 agent B 生成新任务
- 没有 pending_followup 队列让 agent B 启动时拉取
- 没有任务状态机让"闭环待办 → 已跟进 → 已闭环"流转

### 影响
- spec 履行度问题，不是 bug
- 闭环待办只是文字承诺，需要人工把待办转给 PD-1 agent owner 跟进
- 多 agent 协作场景（如 PD-3 + PD-1）退化成单 agent

### 推荐修复（未实施，设计文档已写）
参考 `CROSS_AGENT_HANDOFF_DESIGN.md` 的设计：pending_followup 队列 + 拉取模式 + 状态机。本期未实施，新组织若需要跨 agent 协作建议先实施该机制。

### 参考文档
- `pd3_terminal_task.md` §5.15
- `CROSS_AGENT_HANDOFF_DESIGN.md`

---

## Issue #4 · `getStyle` 多端点重复失败浪费 tool_call 预算（已随 #1 修复）

### 现象
PD-1 v6 实测 23 次 tool_call 里 11 次失败（46%），全部是 Issue #1 的 path-param bug 触发。agent 会针对每个款号 / 工单号 / 打样单号都试一次 path 端点，每次都失败，然后才降级到 list 端点。

### 实测数据
| 场景 | tool_calls | 失败 | 失败率 |
|---|---|---|---|
| PD-1 v4 | 28 | 13 | 46% |
| PD-1 v5 | 19 | 7 | 37% |
| PD-1 v6 | 23 | 11 | 48% |
| PD-3 v3 | 12 | 2 | 17% |
| PD-2 v6 | 23 | 0 | 0%（SCM 全用 query 端点）|
| SC-1 v1/v2 | 20/28 | 13/13 | 65% / 46%（6× getWorkOrder + 7× getSupplier，全部 path-param bug）|

PD-2 失败率 0% 因为 SCM 端点全部用 query 参数（`material_code=...` / `supplier_code=...`），没有 path 参数；PD-1/PD-3 用 PLM 端点，PLM 有 `getStyle(style_code)` 等 path 参数端点。

### v7 修复后回归
| 场景 | path 端点失败（修复前） | path 端点失败（v7 后） |
|---|---|---|
| PD-1 | getStyle/getBulkOrder/getSamplingProgress 11 次 | **0 次** |
| PD-3 | getStyle 2 次 + getFabric 4 次 | getStyle **0 次**；getFabric 2 次（残留为标识符误用，非占位符） |
| SC-1 | getWorkOrder 6 次 + getSupplier 7 次 | getSupplier **0 次**；getWorkOrder 6 次（残留为标识符推断偏差，非占位符） |

### 影响
- 演示屏幕红色 ✗ 多，不专业
- 浪费 LLM 推理预算（每次失败后 agent 要重新决策降级路径）
- 延迟增加（失败 → 重试 → 降级，多 1~2 轮 LLM 调用）

### 修复状态
**已随 Issue #1 修复**（path-param 替换让 getStyle/getBulkOrder/getSamplingProgress 等端点直接命中真实数据，不再失败降级）。另外在 `agent_loop` 的 Craft 分支注入了 `[工具调用策略]` 指令，要求 agent 结合本体与数据接口目录先分析「最少且最直接可达的端点集合」、按参数清单准备入参、对详情/列表端点按需选择、失败后据返回信息修正而非无差别重试——从策略层杜绝「把所有端点都试一遍」。v7 已在 PD-1 / PD-3 / SC-1 三场景回归通过（PD-2 无 path 端点，不受影响）。

### 参考文档
- `pd1_terminal_task.md` §5.10
- `pd3_terminal_task.md` §5.13
- `sc1_terminal_task.md` §5.7

---

## Issue #5 · sjp 个人 workspace 记忆不跨任务复用（已解决：场景拆归口用户 + 清空 sjp）

### 现象
PD-1 跑完后 sjp 的个人 workspace 留有 `面料综合测算与异动预警报告_*.docx` 等附件，但跑 PD-2 时 agent 不会自动读取 PD-1 的输出。

### 根因
当前设计是 workspace 按任务隔离，agent 不跨任务读取前序任务输出（除非显式 prompt 让它读）。memory/extract 抽取的 facts 也不一定能在下次任务里被 retrieve_memory 命中。

### 影响
- 多场景串联（PD-1 → PD-2 → PD-3）需要人工 prompt 中转
- 不影响单场景演示

### 解决状态
**已解决**（2026-07-13）。场景 demo 已从单一演示账号 `sjp` 拆分给各场景归口用户（PD-1→dev-lead、PD-2→fabric-dev、PD-3→qc-lead、SC-1→supply-lead、SC-2→prod-lead），sjp 不再使用。原 sjp 个人 workspace 残留的 12 个 .docx 报告附件与 1 条 memory 记录（5 条 PD-1 域沉淀 fact）已硬删除；sjp 账号本身保留（`is_active=t`），各归口用户的 memory / workspace 零改动。此后每个场景的记忆沉淀自然落到对应归口用户的个人记忆桶，不再混在 sjp 单一桶里，跨任务复用问题不再以"sjp 单账号串联"的形态出现。

### 备注（新组织若需多场景串联演示）
若仍要 PD-1 → PD-2 → PD-3 串联，建议：
1. PD-1 输出保存为 workspace 文件
2. PD-2 prompt 显式说"读取 workspace 中的 PD-1 报告"
3. 或在 prompt 里硬编码前序结论（如"4 款面料首选供应商都是 XS-FAB-002"）

---

## Issue #6 · `.env.deploy` 含真密钥进仓库（按惯例，非 bug）

### 现象
`.env.deploy` 含 `SECRET_KEY` / `MASTER_ENCRYPTION_KEY` 真密钥，按 commit `e79cd2a` 的 gitignore 改动纳入仓库。

### 根因
项目策略：`# 密钥（.env）、数据备份（backups/）、源码、文档等全部纳入仓库。`（来自 `.gitignore` 注释）

### 影响
- 仓库泄露 = 密钥泄露
- 适合内部演示仓库，不适合公开仓库

### 推荐修复
若仓库转公开，需要：
1. `.gitignore` 加回 `.env*` / `backups/`
2. 历史 commit 里的密钥需要 BFG / git filter-repo 清理
3. 真密钥从 vault / 环境变量读取

非本期演示范围。

---

## Issue #7 · mock 容器无 volume mount，改源码要 docker cp（设计如此）

### 现象
改了 `mock/mock/systems/plm/data.py` 后，`docker restart ai_infra_mock` 不会生效——必须先 `docker cp` 进容器再 restart。

### 根因
`docker-compose.yml` 里 `ai_infra_mock` 服务没有挂载源码 volume（不像 `ai_infra_backend` 有 `volumes: - ./llm_router/backend:/app`）。

### 影响
- 改 mock 源码工作流繁琐：编辑 → docker cp → restart
- 容易忘 cp 直接 restart 导致改动不生效，调试浪费时间

### 推荐修复
在 `docker-compose.yml` 给 `ai_infra_mock` 加 volume：
```yaml
ai_infra_mock:
  volumes:
    - ./mock:/app/mock
```

但加 volume 后重启会触发 mock package 重新加载，可能有副作用（如 LazyTenantRegistry 状态丢失）。本期未修。

### 参考文档
- `SCENARIO_AUTHORING_GUIDE.md` §6.3
- `pd2_terminal_task.md` §5.3（隐式提到 mock 改完要 restart）

---

## Issue #8 · list 端点 keyword 过滤性能问题（未修，可绕过）

### 现象
PLM `listStyles(keyword=...)` 实现是 `if keyword: rows = [r for r in rows if keyword in r.get("name","")]` —— 全表扫描，数据量大时慢。

### 根因
mock 是演示用，数据量小（PLM ~10 条 styles），O(N) 全扫描可接受。生产环境会换 DB 索引。

### 影响
- 演示场景无影响
- 数据量 >1000 时会有可见延迟

### 推荐修复
非演示范围问题，生产部署时换真实 DB 索引即可。

---

## Issue #9 · 时区处理不一致（已修）

### 现象
SCM `getLeadtimeDiff(since=2026-06-21T00:00:00Z)` 返回 `TypeError: can't compare offset-naive and offset-aware datetimes`。

### 根因
mock 的 `snapshot_at` 字段是 offset-naive（如 `2026-06-10T09:00:00`），`since` 参数带 `Z` 后缀变 offset-aware，两者比较失败。

### 修复状态
**已修**（commit 6906d86）。在 `mock/mock/systems/scm/routes.py` 的 `get_leadtime_diff` 加：
```python
if since_dt.tzinfo is not None:
    since_dt = since_dt.replace(tzinfo=None)
```

### 参考文档
- `pd2_terminal_task.md` §5.10

---

## Issue #10 · payment_score 评分方向反转（已修）

### 现象
SCM `compareQuotations` 里 `payment_score` 原代码 `(1 - days/pay_max) * 30`——账期越短分越高。但**采购方偏好账期长**（资金占用少 = 高分），方向反了。

### 实测影响
XS-FAB-002（账期 30 天）得 10 分，XS-FAB-001/004（账期 45 天）得 0 分。business logic 完全反了。

### 修复状态
**已修**（commit 6906d86）。改成 `((days - pay_min) / (pay_max - pay_min) * 30) if pay_max > pay_min else 15.0`——账期越长分越高，符合采购方偏好。

### 参考文档
- `pd2_terminal_task.md` §5.x 故障排查（隐式提到评分方向）

---

## Issue #11 · starclothing slug 重复 org（已软删空壳）

### 现象
`organizations` 表里 `slug='starclothing'` 有两份：`54f5f892-cf08-4a75-88b2-b649fea392a4`（真实，19 users / 10 depts / 7 agents）与 `fac4022f-07f6-4d73-a0d1-2011bc99d3ad`（空壳，0 users/depts/agents，仅 1 个建 org 时自动生成的 workspace + 1 条 memory）。

### 影响
任何按 `slug='starclothing'` 或 `name='星途服装'` 取 org 的脚本/逻辑（如 `seed_starclothing_agents.py` 的 `_get_org` 用 `scalar_one_or_none()`）会抛 `MultipleResultsFound` 或命中错的那份，导致 seed 跑崩、prompt 写不到真实 org、supply-lead 看不到新 prompt。

### 解决状态
**已规避**（2026-07-13）。软删空壳 org `fac4022f-...`（`deleted_at=now()`）。脚本里 `select(Organization).where(Organization.deleted_at.is_(None) ...)` 据此只命中真实 org `54f5f892-...`。空壳那份的 1 个 workspace + 1 条 memory 成孤儿（软删 org 后不再被 active 查询命中，无害）。

### 推荐根治（未实施）
两份同 slug org 是历史残留（疑似重复 seed）。彻底根治需核对 `fac4022f-...` 确无引用后硬删（含其孤儿 workspace/memory），并排查 seed 脚本为何会建出第二份同 slug org（`slug` 上是否有唯一约束）。本次仅软删规避，未硬删。

### 参考文档
- `pd2_terminal_task.md` / 各 `*_terminal_task.md` 的登录用 `slug=starclothing`（前端 `/starclothing/terminal/login`）

---

## Issue #12 · seed_starclothing_agents.py skill 解析 stale（未修，可绕过）

### 现象
`demo/starclothing/scripts/seed_starclothing_agents.py` 的 `_resolve_skill_ids`（约 line 332-348）按 `SkillFolder.scope_type == "organization" AND scope_id IS NULL` 查技能 slug。但 `reorg_starclothing_scope.py`（commit 3aad6c6）已把 5 个 mock 技能（plm/scm/mes/erp/crm）拆到部门级 scope，org 级已无这些 SkillFolder。

### 影响
直接跑 `seed_starclothing_agents.py` → `skill_folders_missing`（5 个 slug 全缺）→ `sys.exit(1)`，**agent prompt 一条都没落库**。这阻塞了「改 seed 脚本里的 system_prompt → 跑脚本落库」这条标准工作流。

### 当前绕过路径
改完 seed 脚本里的 `system_prompt` 后，不要跑全量脚本，而是在 `ai_infra_backend` 容器里 import seed 模块取 `AGENTS` 列表（脚本有 `if __name__ == "__main__"` guard，可安全 import），按 `slug + organization_id` 直接 `UPDATE Agent.system_prompt`，skill_ids 不动（SC-1 改造即用此路径，详见 `starclothing-seed-script-skill-scope-stale` 记忆）。

### 推荐修复（未实施）
把 `_resolve_skill_ids` 的查询从 `scope_type == "organization"` 改成跨 scope（去掉 scope_type/scope_id 过滤，或按部门 scope 解析），让脚本在全量 re-seed 时也能正确解析部门级技能。非本期演示范围，新组织若要全量 re-seed 建议先修。

### 参考文档
- `demo/starclothing/scripts/seed_starclothing_agents.py` line 332-348
- `demo/starclothing/scripts/reorg_starclothing_scope.py`（技能拆部门级）

---

## 已修 vs 未修一览

| Issue | 状态 | 修复 commit |
|---|---|---|
| #1 path-param 占位符未替换 | **已修** | executor.py `execute_endpoint` |
| #2 memory/extract 0 facts | **已修**（prompt 三元组 + `_parse_json_lenient` 容错解析） | nodes.py `extract_memory` / `_parse_json_lenient` |
| #3 跨 agent 交接机制缺失 | 未修（文字承诺） | — |
| #4 path 端点重复失败浪费预算 | **已随 #1 修复**（+ 注入工具调用策略 prompt） | executor.py / nodes.py |
| #5 workspace 跨任务不复用 | **已解决**（场景拆归口用户 + 清空 sjp） | 2026-07-13 |
| #6 .env.deploy 含密钥 | 按惯例 | e79cd2a |
| #7 mock 容器无 volume | 设计如此 | — |
| #8 list keyword 全表扫描 | 未修（演示无影响） | — |
| #9 时区比较 TypeError | **已修** | 6906d86 |
| #10 payment_score 方向反转 | **已修** | 6906d86 |
| #11 starclothing slug 重复 org | **已规避**（软删空壳） | 2026-07-13 |
| #12 seed 脚本 skill 解析 stale | 未修（可手术式绕过） | — |

新组织 demo 时优先关注 #3 / #12——这两个影响 spec 履行度 / re-seed 工作流（#1 / #2 / #5 / #11 已解决）。其余按场景需要取舍。
