# PD-3 新品缺陷风险预警与闭环待办 · 终端任务演示

> 与 PD-1 / PD-2 同走**终端任务方式**：业务用户 `qc-lead` 登录终端，新建任务、
> 配置 `glm-5.2`、`/starclothing-plm-query` 选技能，提示词中**显式触发 RAG 检索**，
> agent 自主多轮调用 PLM 端点 + RAG 服装缺陷知识库，对两款新品做缺陷风险
> 预警 + 评审必查项 + 闭环回路复核。

---

## 1. 演示身份

| 项 | 值 |
|---|---|
| 组织 | 星途服装（slug = `starclothing`） |
| 用户名 | `qc-lead` |
| 密码 | `12345678` |
| 角色 | member（业务用户，无管理后台权限） |

---

## 2. 前置条件

1. **平台已起**：`ai_infra_backend`（:8000）+ `ai_infra_mock`（:8010）容器在跑。
2. **数据已 seed**：`seed_starclothing_apparel.py` / `seed_starclothing_mock_connectors.py` /
   `seed_starclothing_ontology.py` / `seed_starclothing_agents.py` / **`seed_starclothing_defect_rag.py`**
   至少跑过一次（详见根 `README.md` §2.2）。
   - ⚠️ **PD-3 强依赖 RAG**：必须跑 `seed_starclothing_defect_rag.py` 把「服装缺陷知识库」
     集合的 61 个 chunk + 向量 embedding 灌入；否则 retrieve_rag 节点 hits=0，
     PD-3 的核心演示点（RAG 检索相似历史案例）就丢了。
3. **claude-opus-4 已可用**：Anthropic provider 的 `supported_models` 含 `claude-opus-4`。
   - 自检：`GET /api/v1/terminal/models`（用 qc-lead token）应在 `models` 里看到 `claude-opus-4`。
4. **qc-lead 账号已存在且 active**：自检 `SELECT username, is_active FROM users WHERE username='qc-lead'`。
5. **PLM mock 端点正常**：
   ```bash
   curl -s "http://localhost:8010/plm/defect-history?style_code=P-FW2026-002" \
     -H "X-API-Key: plm-starclothing-demo-key" | head
   ```
   应返回 DF20260012 / DF20260018 等历史案例。
6. **缺陷知识库向量通道正常**：
   ```bash
   docker exec ai_infra_backend python -c "
   from app.rag.service import RAGService
   s = RAGService(); c = s.get_collection_by_name('服装缺陷知识库')
   print('chunks:', c.chunk_count, 'embedded:', c.embedded_count)
   "
   ```
   应输出 `chunks: 61 embedded: 61`。若 `embedded < chunks`，参考 PD-1 §5.6
   跑 `reembed_defect_rag.py` 补齐。

> ⚠️ PD-3 关键依赖 3 件事：PLM 的 `getStyle` / `listDefectHistory` /
> `listFeasibilityLogs` 端点 + 缺陷知识库 RAG 向量通道 + `_build_tools`
> 修复（PD-2 §5.11，确保 `tool_call.arguments` 不为 `{}`）。

---

## 3. 操作步骤

### 3.1 登录终端

浏览器访问：

```
http://localhost:8000/starclothing/terminal/login
```

- 用户名：`qc-lead`
- 密码：`12345678`

登录后落到 `/starclothing/terminal`。

### 3.2 新建任务

点左栏「New Task / 新建任务」进入 HomeView composer。

### 3.3 配置任务（TaskConfigDrawer）

点 composer 右侧 ⚙️ 打开 TaskConfigDrawer：

| 字段 | 取值 | 说明 |
|---|---|---|
| Workspace | `qc-lead`（个人工作区） | 干净；记忆仍按四级自动载入 |
| Model | **`claude-opus-4`** | 真实模型 id（终端下拉直接列真实 id，无别名层） |
| Exec Mode | **`craft`**（自主多步执行） | agent 需多轮调 PLM 端点 + RAG 检索；`ask` 单轮不够 |

> 本体 / 数据接口按 qc-lead scope 自动注入：9 个本体文件（品控部 PLM 5 个含 README + 组织级 Cross 4 个）+ 1 个数据系统
> 个数据接口（含 PLM 全集）按权限自动可见，无需在 drawer 里配。

> **场景模板（template_agent_id）**：PD-3 已改为四层架构——persona / RAG 检索 cue /
> feasibility_log 闭环待办规则 / 输出骨架由 Agent 模板 `starclothing-pd3-defect-closure`
> 的 `system_prompt` 承载，用户 composer 只写「目标 + 对象 + 技能 chip」（见 §3.4）。
> 任务 config 必须绑 `template_agent_id = <该 slug 的 UUID>`，运行时 `load_config` 才会把
> 模板 persona 拼到 system prompt 最前（`trace template` / `template:true` 出现），技能与
> 模型留空即从模板继承（`starclothing-plm-query` + claude-opus-4）。**前端 drawer 暂未暴露
> 「场景模板」选择器**，用 §6 手工调 API 在 `config` 里显式带 `template_agent_id` 绑定。

### 3.4 在输入框写提示词 + /-mention 选择技能

在 `MentionInput` 输入框敲 `/` 触发技能菜单，输入 `plm` 过滤，选中
**`starclothing-plm-query`** 即把技能 chip 插入提示词。

完整提示词如下（直接复制，约 100 字）：

```
新品开发评审会：款号 P-FW2026-002 压胶冲锋衣即将进入大货试产，款号 P-FW2026-001 双面呢大衣即将进入量产。请基于历史缺陷知识库做风险预警。

/starclothing-plm-query
```

> **v7d 起改为四层架构**（对齐 PD-2 `§3.4` / SC-1 `§3.4`）：user composer 只写
> **目标 + 对象 + 技能 chip**，persona / RAG 检索 cue（8 类缺陷关键词 + 品类 fallback）/
> feasibility_log 闭环待办规则（仅覆盖成本/交期/产能三维度，缺陷预防措施未留痕项标注
> 待办提示监管 Agent 跟进）/ 输出骨架（风险预警表 + 评审必查项 + 闭环验证建议 + 闭环待办
> 四段）由 Agent 模板 `starclothing-pd3-defect-closure` 的 `system_prompt` 承载（796 字符）。
> 任务 config 必须绑定 `template_agent_id = <starclothing-pd3-defect-closure 的 UUID>`，
> 运行时 `load_config` 才会注入模板（trace `template` 出现、`template:true`）。技能与模型
> 留空即从模板继承（`starclothing-plm-query` + claude-opus-4）。runtime 的
> `[输出协议]`+`[工具调用策略]` 兜底「先 text 后 docx / 不要臆造 / 最少端点集」，本体
> identifiers.md 兜底「标识符不猜」——故 composer 不再写执行步骤、输出要求、输出格式。
>
> 若前端 drawer 暂未暴露「场景模板」选择器，可用 §6 手工调 API 在 `config` 里显式带
> `template_agent_id` 复现（`SELECT id FROM agents WHERE slug='starclothing-pd3-defect-closure'`）。

> ⚠️ **关键 1**：`/starclothing-plm-query` 必须从 `/` 菜单选中 chip，不能手敲文本。agent 运行时解析 chip（正则 `(?<![\w/])/slug`）决定调用哪个技能的端点；API 直调时 message 里写 `/starclothing-plm-query` 也会被同款正则解析（见 §6）。
>
> ⚠️ **关键 2**：composer 须含「历史缺陷知识库」字样触发 `retrieve_rag`（按 query 语义
> 命中，不提 RAG 可能跳过检索）——本短 composer 的「请基于历史缺陷知识库做风险预警」
> 已满足。8 类缺陷关键词 + 品类 fallback 已固化在模板 `system_prompt`，不在 composer。
>
> ⚠️ **关键 3-5**：闭环回路（`listFeasibilityLogs` 复核 PD-2 可行性测算，串成 PD-2→PD-3
> 数据闭环）/ 历史缺陷品类 fallback（新款无 style_code 历史缺陷时按 category 查同类）/
> feasibility_log 闭环待办判断（gap = 缺陷预防措施未留痕，非 decision 字段）三项 policy
> 均已固化在模板 `system_prompt`，agent 据 policy 自主执行，composer 不写。

#### 资源注入机制（任务运行时自动完成，无需配置）

任务运行时，agent runtime 会按 qc-lead 的 scope 自动注入以下资源（**部门级 scope 拆分后**，qc-lead 看到品控部范围内的资源，含品控部 PLM proxy + 缺陷知识库）：

| 资源类型 | 注入方式 | 本次演示注入量 |
|---|---|---|
| **本体** | scope_filter 过滤后：品控部 PLM 5 个（含 README）+ 组织级 Cross 4 个 | 9 files |
| **数据接口目录** | `scope_service.list_data_interfaces_for_user` 按权限列出 qc-lead 可调用的接口 | 1 system（PLM）/ 24 interfaces |
| **RAG** | 品控部 scope 下的「服装缺陷知识库」collection 自动匹配；retrieve_rag 节点按 query 检索 top-k | 1 collection（61 chunks），预期 hits ≥ 5 |
| **长期记忆** | 4 级（组织+部门+团队+个人）按权限聚合 | 见 trace memory/load |
| **技能** | `template_agent_id` 继承 + /-mention chip 解析；config 留空 skill_ids 即从模板 `starclothing-pd3-defect-closure` 继承 | 1 skill（品控部级 starclothing-plm-query） |
| **记忆沉淀** | extract_memory 节点抽取本轮可沉淀事实写入个人级 Memory | 0~N facts |

> **跨部门数据访问**：PD-3 是品控部场景，本部门已 proxy 复制 PLM 本体 + 拥有缺陷知识库 RAG——所有数据资产都在品控部 scope 内闭环。如需调用其他部门（如开发部 PLM 原始数据）的接口，需在品控部下重新实现一份数据接口（绑定同一 `tool_connector`）。

### 3.5 提交运行

按回车或点发送按钮提交。前端会：
1. `POST /api/v1/terminal/tasks` 创建任务（把 composer 内容作为 `message` 存档）；
2. `POST /api/v1/terminal/tasks/{id}/run` body `{message: <同一段提示词>, stream: true}` —— **这才是真正发给 agent 的输入**。

> ⚠️ 实测：`/run` 的 `message` 才是 agent 看到的指令；任务创建时存的 `message`
> 不会被 agent 读到。前端做法是「同一段文本两次用」。手工调 API 记得 `/run` 也要带完整提示词。

### 3.6 观察 SSE 事件流

任务运行后，右侧 ChatView 渲染 SSE。事件类型与含义：

| 事件 | 含义 |
|---|---|
| `[step] load_config` | 装载任务配置（model / skill_ids / workspace / template_agent_id） |
| `[trace]` (template) | 场景模板 persona 注入（`template:true`——PD-3 模板 system_prompt 拼到 system prompt 最前，继承 skill_ids/model_alias） |
| `[trace]` (rag) | RAG 检索——PD-3 query 与缺陷知识库高度相关，预期 hits ≥ 5 |
| `[trace]` (memory/load) | 长期记忆载入（4 级 scope 聚合） |
| `[trace]` (ontology) | 部门级本体注入 system prompt |
| `[trace]` (data_interface) | 数据接口目录注入（按用户权限，品控部 PLM 24 端点） |
| `[trace]` (skill) | /-mention 解析引用了哪个技能 |
| `[trace]` (memory/extract) | 记忆沉淀抽取 |
| `[phase] llm #0/#1/#2` | 每个 LLM 调用轮次 |
| `[tool_call]` | agent 调用工具（PLM 端点 / generate_docx / workspace_list_files） |
| `[tool_result]` | 工具返回（ok / FAIL） |
| `[text]` | LLM 流式输出 token |
| `[done]` | agent_loop 收口（带 usage 统计） |
| `[final]` | 任务结束，附 latency_ms + session_id |

> 终端前端 ChatView 目前只渲染 `text` / `tool_call` / `tool_result`；`trace`
> 事件保存在 assistant 消息的 `metadata_.traces` 里，管理后台或
> `GET /terminal/tasks/{id}/messages` 可见。

典型 PD-3 运行约 4–5 分钟（3–5 轮 LLM + 10–12 次 tool 调用 + glm-5.2 推理，
含 RAG 向量检索 + PLM 端点调用 + .docx 附件生成）。

---

## 4. 期望输出

agent 会输出三段 + 1 个附件：

### 4.1 风险预警表

每款号 × 高风险缺陷类型 = 1 行，共约 4–6 行：

| 款号 | 高风险缺陷类型 | 历史案例编号 | 严重等级 | 发生部位 |
|---|---|---|---|---|
| P-FW2026-002 | 漏水 | DF20260012 | 严重 | 拉链位 / 压胶接缝 |
| P-FW2026-002 | 压胶脱落 | DF20260018 | 严重 | 全衣压胶条 |
| P-FW2026-001 | 整烫烫花 | DF20260009 | 严重 | 羊绒面正面 |
| P-FW2026-001 | 尺寸偏差 | DF20260016 | 一般 | 手缝吃势处 |

> 数据来源：PLM `listDefectHistory?style_code=P-FW2026-002` 应返回 DF20260012
> （漏水）+ DF20260018（压胶脱落）；`style_code=P-FW2026-001` 应返回
> DF20260009（整烫烫花）+ DF20260016（尺寸偏差）。
> RAG 检索应补全根因 / 纠正 / 预防措施（参考 PD-1 §3.4 关键 2 经验）。

### 4.2 评审必查项清单

按设计 / 工艺 / 物料 / 验证 4 阶段：

```
设计阶段
  - 压胶冲锋衣拉链位必做封胶检测（参考 DF20260012）  责任：设计部  验证：首件水浸测试
  - 双面呢大衣手缝工序标准化（参考 DF20260016）      责任：设计部  验证：首件签字

工艺阶段
  - 压胶机硅胶轮每 3 个月检查硬度（参考 DF20260018）  责任：工艺部  验证：设备点检表
  - 羊绒款熨烫温度 ≤150℃ 必垫烫布（参考 DF20260009） 责任：工艺部  验证：温控记录

物料阶段
  - 三层压胶面料进料必测透气膜耐水压                责任：品质部  验证：来料抽检 5%
  - 双面呢面料色牢度 ≥4 级                         责任：品质部  验证：来料全检

验证阶段
  - 试产首件：拉链位封胶测试 + 水浸 30min            责任：品保部  验证：首件报告
  - 量产抽测：每 200 件抽 5 件做水洗 + 整烫后复检      责任：品保部  验证：抽测台账
```

### 4.3 闭环验证建议

```
P-FW2026-002 压胶冲锋衣（试产阶段）
  试产首件检测项：
    1. 拉链位封胶完整性（目视 + 拉扯）
    2. 压胶条剥离强度（≥15N/cm）
    3. 整衣水浸 30min 漏水测试
  量产抽测项：每 200 件抽 5 件，复测水浸 + 压胶剥离
  复测标准：水浸 30min 内侧无水迹；压胶剥离 ≥15N/cm

P-FW2026-001 双面呢大衣（量产阶段）
  试产首件检测项：
    1. 手缝吃势均匀度（目视 + 尺寸抽检）
    2. 整烫后表面无烫花（目视）
    3. 尺寸符合样板（首件三检签字）
  量产抽测项：每 100 件抽 3 件，复测尺寸 + 整烫外观
  复测标准：尺寸偏差 ±0.5cm；整烫后无烫花、无极光
```

### 4.4 闭环待办

对 `listFeasibilityLogs` 返回的 feasibility_log，复核预防措施落实情况：

```
闭环待办：
  P-FW2026-002 → FL20260002 → decision="通过"
    feasibility_log 覆盖维度：成本 / 交期 / 产能（已通过）
    未覆盖维度：缺陷预防措施（水压测试 / 胶条批次管理 / 硅胶轮维保 / 拉链位防水贴片）
    → 4 项闭环待办，提示 PD-1 监管 Agent 跟进

  P-FW2026-001 → FL20260001 → decision="通过"
    feasibility_log 覆盖维度：成本 / 交期 / 产能（已通过）
    未覆盖维度：缺陷预防措施（缩率测试 / 抗起球测试 / 整烫温度管控 / 手缝标准化）
    → 4 项闭环待办，提示 PD-1 监管 Agent 跟进
```

> 数据来源：PLM `listFeasibilityLogs?style_code=P-FW2026-002` 返回 FL20260002
> （decision="通过"，仅覆盖成本/交期/产能）；`style_code=P-FW2026-001` 返回
> FL20260001（decision="通过"，同上）。
> 闭环回路把 PD-2 沉淀的可行性测算结果与 PD-3 缺陷预警串成完整数据闭环——
> 但 feasibility_log 不含缺陷预防措施留痕字段，所以即使 decision="通过"，
> 缺陷预防措施仍未闭环，agent 应基于这一 gap 生成闭环待办项。

### 4.5 SSE trace 事件（演示时截图可证）

| trace | 含义 | 实测值 |
|---|---|---|
| `category=rag` | RAG 检索 | 1 collection / **5 hits（retriever=vector）**；query 与缺陷知识库高度相关，hits 内容直接进 system prompt |
| `category=memory, subtype=load` | 长期记忆载入 | 0 history + 6 facts |
| `category=ontology` | 部门级本体注入 | 8 files（品控部 PLM proxy 4 + 组织级 Cross 4） |
| `category=data_interface` | 数据接口目录注入 | 1 system（PLM）/ 24 interfaces |
| `category=skill` | /-mention 引用技能 | 1 skill（starclothing-plm-query） |
| `category=memory, subtype=extract` | 记忆沉淀抽取 | v7d5 起正常抽取（详见 §5.14） |

### 4.6 实测延迟与 token 用量

| 指标 | 首次跑（无「先 text 后 docx」要求） | 二次跑（v2 prompt） | 三次跑（v3 prompt 同 v2，稳定性验证） | v7（path-param 修复后回归） | **v7b（PLM 本体补标识符约定）** |
|---|---|---|---|---|---|
| latency_ms | 244884（~4 min） | 302438（~5 min） | 367094（~6.1 min） | 275467（~4.6 min） | 257974（~4.3 min） |
| input_tokens | 183518 | 97774 | 97835 | 90665 | 61863 |
| output_tokens | 8852 | 11507 | 13074 | 9128 | 9381 |
| tool_calls 总数 | 22（含 6 次失败） | 12（含 2 次失败） | 12（含 2 次失败） | 13（含 2 次失败） | **7（0 失败）** |
| text 事件字符数 | 806 | **7334** | **8457** | **6619** | **6216** |
| .docx markdown 字符数 | 7219 | 6401 | 7175 | — | — |
| 4 段分析是否上屏 | ✗ | ✓ | ✓ | ✓ | ✓ |
| 6 类 trace 是否全 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 4 个关键案例编号命中 | ✓ | ✓ | ✓ | ✓ | ✓ |
| listFeasibilityLogs 两款都调 | ✓ | ✓ | ✓ | ✓ | ✓ |
| `getStyle` path 端点 | ✗ 2 次失败（`{style_code}` 占位符） | ✗ 2 次失败 | ✗ 2 次失败 | ✓ 2 次调用 0 失败 | ✓ 2 次调用 0 失败 |
| `getFabric` path 端点 | ✗ 4 次失败 | — | ✗ 2 次失败 | ✗ 2 次失败（M- 当 F- 误用） | **✓ 未误调（0 次调用，0 失败）** |

> v2 prompt 加了「先 text 流式输出 4 段分析，再生成 docx 附件」要求后，连续
> 2 次（v2 + v3）跑都稳定达标——text 流式输出 7334 / 8457 字符（远超 806
> 基线），4 段分析全部出现在 ChatView 屏幕上。方差只在延迟（5 / 6.1 min）和
> 字符数（7.3K / 8.5K）上，**核心达标指标 0 失败**。
>
> v2/v3 都观察到 `getStyle` path-param bug 以同样方式失败 2 次 + agent 以同样
> 方式降级到 `listStyles`——降级路径稳定可复现，不影响演示闭环。
>
> **v7（path-param 修复后回归）**：`executor.py` 占位符替换 + Craft 分支注入
> `[工具调用策略]` 全局生效后回跑，`getStyle` 2 次调用 **0 失败**（v2/v3 的
> `{style_code}` 字面占位符失败全部消失），path 端点直接返回真实款式数据。
> 剩余 2 次失败发生在 `getFabric`，但错误信息是 `fabric M-SHELL-3L-150 not
> found` / `fabric M-WOOL-DBL-360 not found`——**占位符已被真实值替换**
> （不再是 `fabric {fabric_code} not found`），失败原因是 agent 把 BOM 里的
> 物料编码 `M-*`（material code）误当作面料主数据编码 `F-*`（fabric_code）
> 传入；这是 agent 标识符误用，**非 path-param bug**，agent 自主降级到
> `listFabrics` 后闭环仍完整。详见 §5.11 / §5.13。
>
> **v7b（PLM 本体补标识符约定）**：在 `PLM/identifiers.md` 本体里写死各实体主键
> 前缀与示例值（`P-`/`F-`/`M-`/`SMP`/`BLK`/`QC`/`DF`/`XCL`/`FL`）+ 跨码空间映射
> 规则（`Style.fabric_main` 是 `M-` 物料码、`Fabric.fabric_code` 是 `F-` 主数据
> 码、须按后缀映射，不可直接传 `M-`；款号 `P-` ≠ 工单号 `XWO`；新款缺陷按
> `category` fallback）。回跑：tool_calls **7 次 0 失败**（v7 的 2 次 `getFabric`
> M-vs-F 失败消失——agent 读本体后根本没误调 `getFabric`），input 90665→61863、
> tool_calls 13→7。本体「no-guessing 骨架」生效，详见 §5.11。

> **v7c（瘦提示词 + 本体 + runtime 输出协议）**：把「先 text 后 docx」「不要
> 臆造数据」上提到 `nodes.py` Craft 分支 `OUTPUT_PROTOCOL_PROMPT`（场景无关
> runtime 注入），§3.4 提示词从 2796 字符删到 584（21%），只留角色 + 目标 +
> 两款款号 + 一条 feasibility_log gap 业务规则 + 技能 chip，**执行步骤 / 输出
> 格式 / 不要臆造 整段删除**。回跑：tool_calls 24 **0 失败**、text 8151（4 段
> 上屏）、`getFabric` **2 次调用 0 失败**（agent 自主用对 `F-` 码——
> `getFabric(fabric_code='F-SHELL-3L-150')` / `F-WOOL-DBL-360`，从 getStyle 返回
> 的 `fabric_main`（M- 码）按本体映射规则自主转 F-，瘦提示词没提一个字）。
> 证明**执行步骤可删、闭环不塌方**。代价：tool_calls 7→24、token 62k→158k、
> 延迟 4.3→6 min——删手把手步骤后 agent 多探了一圈（listQcReports×5 /
> getBulkOrder×4 等原版未要求的端点）。要压回高效靠端点 description 补准 +
> 本体实体关系写清（让 agent 不必既调 getBulkOrder 又调 listQcReports 查同一
> 件事），而非恢复手把手步骤。**真实边界**：瘦提示词未显式写「检索 RAG」字样，
> `trace rag` **未触发**（retrieve_rag 节点靠 query 语义命中，「历史缺陷知识库」
> 措辞语义匹配度不够）——RAG 检索意图目前还需在提示词点一句明示，或落到
> retrieve_rag 节点配置，不能完全靠语义。详见 §5.16。

> **v7d（template 层 + 真用户提示词，验证态）**：建最小 agent-template 层——
> `TaskConfig.template_agent_id`（引用一个 Agent 行）+ `AgentState.template_agent_id` +
> `_load_config_general` 把 Agent.system_prompt 作 persona/policy 前缀拼到
> `GENERAL_SYSTEM_PROMPT` 前（+ 继承 skill_ids/model_alias fallback）。PD-3 的
> `starclothing-pd3-defect-closure` Agent system_prompt 重写为**精简模板**：
> persona + RAG 检索 cue + feasibility_log 闭环待办 policy + 4 段输出骨架
> （796 字符，删了老胖 playbook 的检索策略/端点编排）。用户 composer 收缩到
> **216 字符**（原版 2796 的 7.8%）：只留「新品评审会：款号 P-FW2026-002/
> P-FW2026-001…基于历史缺陷知识库做风险预警」+ 技能 chip——**persona、feasibility
> policy、输出格式、RAG cue 全在 template，用户不写**。回跑（v7d2，修了
> AgentState 漏声明 template_agent_id 导致首轮没加载的 bug 后）：tool_calls 11
> **0 失败**、text 5834（4 段全上屏）、RAG vector 5 hits、`getFabric` 2 次 0 失败
> （F- 码）、text 含 `feasibility`/`监管 Agent`/`水压`（template 的闭环待办规则
> 驱动 agent 标注）。四层架构全绿：① runtime `[输出协议]`+`[工具调用策略]` 兜底
> 「先 text 后 docx / 不要臆造 / 最少端点集」；② 本体 identifiers.md 兜底「标识符
> 不猜」；③ template 承载 persona+policy+RAG cue+输出骨架；④ 用户 composer 只剩
> 目标+对象+chip。详见 §5.17。

> 与 PD-2 不同，PD-3 的 `trace rag` 预期 hits ≥ 5（query 语义与缺陷知识库
> 高度相关）；若 hits=0 或 `retriever=keyword_fallback`，参考 §5.5 修复。

---

## 5. 故障排查

### 5.1 模型选择器里没有 `claude-opus-4`
- Anthropic provider 未配或 `supported_models` 不含 `claude-opus-4`。
- 自检：`GET /api/v1/terminal/models` 的 `models` 应含 `claude-opus-4`。
- 修复：`docker cp` + `docker exec ai_infra_backend python /app/scripts/seed_starclothing_apparel.py`。

### 5.2 提示词里 `/starclothing-plm-query` 没被识别
- 必须从 `/` 弹窗里选中 chip，不能手敲纯文本。
- 自检：保存的 task.message 里这段应该是结构化 chip 标记。

### 5.3 `[tool_result FAIL]` PLM 接口调用失败
- mock 网关未起或 API key 不匹配。
- 自检：`curl -s "http://localhost:8010/plm/defect-history?style_code=P-FW2026-002" -H "X-API-Key: plm-starclothing-demo-key" | head` 应返回 JSON 列表（含 DF20260012/DF20260018）。
- 检查 `seed_starclothing_mock_connectors.py` 是否跑过最新版（含 PLM 连接器）。

### 5.4 agent 没调 RAG 检索（trace 缺 `category=rag`）
- 提示词里漏写了「检索服装缺陷知识库 RAG」字样或 8 类缺陷关键词。
- retrieve_rag 节点根据 query 语义触发，提示词不提 RAG 就可能跳过检索节点。
- 修复：在提示词步骤 3 显式写「检索服装缺陷知识库 RAG」+ 列出 8 类缺陷关键词。

### 5.5 trace `rag` 显示 `retriever=keyword_fallback` 或 hits=0
- PD-3 query 与缺陷知识库语义高度相关，hits=0 或 fallback 意味着向量通道未通。
- 自检：
  ```bash
  docker exec ai_infra_backend python -c "
  from app.rag.service import RAGService
  s = RAGService(); c = s.get_collection_by_name('服装缺陷知识库')
  print('chunks:', c.chunk_count, 'embedded:', c.embedded_count)
  "
  ```
- 若 `embedded < chunks`：跑 `reembed_defect_rag.py`（COLLECTION_ID / ORG_ID
  写死在脚本里，BATCH=8）补齐 NULL embedding 的 chunks。
- 根因排查参考 PD-1 §5.6（embedding provider 缺失 / `_EMBED_BATCH` 配置）。

### 5.6 agent 没调 `listFeasibilityLogs`（闭环回路断链）
- 提示词里漏写了步骤 5「闭环回路」。
- `listFeasibilityLogs` 是 PD-3 的核心差异化演示点——把 PD-2 沉淀的可行性
  测算结果与 PD-3 缺陷预警串成完整数据闭环。
- 修复：提示词步骤 5 显式写「调用 `listFeasibilityLogs`（style_code 入参）
  复核预防措施落实情况」。

### 5.7 工具调用全部 `args={}`（agent 不传参）
- 现象：所有 `tool_call` 的 `arguments` 是 `{}`，`getStyle` / `listDefectHistory`
  / `listFeasibilityLogs` 全部 FAIL 500。
- 根因：`_build_tools`（`app/agents/graph/nodes.py`）原代码用
  `manifest.parameters or ep.params_schema`，但 seed 脚本生成的
  `manifest.parameters = {"type":"object","properties":{}}` 是占位空 schema（非 None），
  truthy 判定让它覆盖了 `ep.params_schema`，LLM 看不到参数 schema 就不传参。
- 修复：已 fix（改为检测 `manifest.parameters.properties` 是否真有字段，否则用
  `ep.params_schema`）。若重现，检查 `nodes.py` `_build_tools` 的 params 选择逻辑。

### 5.8 agent 没做 `listDefectHistory` 的 fallback
- 现象：`listDefectHistory?style_code=P-FW2026-002` 返回非空但缺某些缺陷类型
  （如 P-FW2026-002 只有漏水/压胶脱落，无起球/掉色），agent 直接放弃这些类型。
- 修复：提示词步骤 2 写「若无历史案例则按 category（如压胶冲锋衣）调
  listDefectHistory 拿同类款历史缺陷」，让 agent 自主 fallback。

### 5.9 运行很久没动 / latency > 5 分钟
- glm-5.2 单轮推理慢，多轮 tool 调用累计 3–4 分钟正常。超过 8 分钟大概率卡住，
  看后端日志 `docker logs ai_infra_backend --tail 100`。

### 5.10 trace 事件没在 SSE 里显示
- 终端前端目前只渲染 `text` / `tool_call` / `tool_result`，`trace` 事件落在
  `TaskMessage.metadata_.traces` 里。
- 查看方式：管理后台 → 终端任务详情页 → 消息 traces 标签；或
  `GET /api/v1/terminal/tasks/{id}/messages` 看元数据。

### 5.11 `getStyle` / `getFabric` 返回 `style {style_code} not found`（v7 已修，仅余标识符误用）
- 现象（修复前）：agent 调 `getStyle(style_code="P-FW2026-002")` 返回
  `{"detail":"style {style_code} not found"}`——路径参数 `{style_code}` 字面未被替换。
- 根因：技能 wrapper 把 `style_code` 当作 query/body 参数透传，未替换到
  OpenAPI path 占位符 `/api/v1/styles/{style_code}`。
- 修复状态（v7 已根治）：`executor.py` `execute_endpoint` 在拼装 URL 前按
  `{name}` 占位符替换路径参数（`urllib.parse.quote` 编码）并从 query/body
  移除，全局生效。v7 回跑实测 `getStyle` 2 次调用 **0 失败**。
- 残留（v7b 已消除）：v7 时 `getFabric` 仍有 2 次失败，错误信息为
  `fabric M-SHELL-3L-150 not found` / `fabric M-WOOL-DBL-360 not found`——
  占位符已替换为真实值，失败原因是 agent 把 BOM 物料编码（`M-*`，material
  code）误当作面料主数据编码（`F-*`，fabric_code）传入。v7b 在 `PLM/identifiers.md`
  本体写死「`Style.fabric_main` 是 `M-` 物料码、`Fabric.fabric_code` 是 `F-`
  主数据码、不同码空间、须按后缀映射」后回跑——`getFabric` **0 次误调、0 失败**
  （agent 读本体后不再用 `M-` 码调面料详情端点）。no-guessing 骨架生效，
  详见 §4.6 v7b 列。

### 5.12 输出大量走 `generate_docx`，前端 `text` 输出较短
- 现象：SSE 的 `text` 事件累计仅 ~800 字符，但 `.docx` 报告 ~42KB / 7 段。
- 根因：agent 末轮选择 `generate_docx` 工具把完整分析打包成附件，前端
  ChatView 只渲染 `text` 事件，所以屏幕上看到的摘要比附件内容短。
- 实测（首次跑）：附件覆盖 (1) 风险预警表 (2) 评审必查项清单 (3) 闭环验证建议
  (4) 闭环待办 全部 4 段，PD-3 spec 完整对齐，但屏幕体验差。
- 修复：提示词已加「先在 text 里流式输出完整分析，再生成 docx 附件」要求
  （§3.4 输出要求段）。二次跑后 text 事件字符数 806 → 7334（9×），4 段分析
  全部出现在屏幕上，演示体验达标。代价是延迟 +60s，可接受。

### 5.13 `getStyle` / `getFabric` 路径参数未替换（v7 已修，详见 §5.11）
- 现象（修复前）：agent 调 `getStyle(style_code="P-FW2026-002")` 返回
  `{"detail":"style {style_code} not found"}`——`{style_code}` 占位符未被
  替换为实际值；`getFabric(fabric_code=...)` 同样问题。
- 根因：技能 wrapper 把 path 参数当作 query/body 参数透传，未替换到
  OpenAPI path 占位符 `/api/v1/styles/{style_code}`。
- 修复状态（v7 已根治）：随 `executor.py` `execute_endpoint` 占位符替换 +
  Craft 分支注入 `[工具调用策略]` 全局修复（见 `pd1_terminal_task.md` §5.10）。
  v7 回跑实测：13 次 tool_call 中 2 次失败，**全部为 `getFabric` 且占位符
  已替换**（`fabric M-WOOL-DBL-360 not found`，非 `fabric {fabric_code}
  not found`），属 agent 标识符误用而非 path-param bug；`getStyle` 2 次调用
  0 失败。详见 §5.11。
- 历史（修复前）：22 次 tool_call 中 6 次失败（2 次 getStyle + 4 次
  getFabric），失败率 27%——演示时屏幕会看到红色 ✗ 标记，但 agent 自行
  降级后闭环仍完整。

### 5.14 memory/extract 抽取 0 facts（已修，v7d5）
- 现象（修复前）：`trace memory/extract` 显示 `facts: 0`——本轮缺陷案例 / 评审必查项
  本是可沉淀事实，但 extract 节点未抽取。
- 根因：与 PD-1 / PD-2 同款——extract_memory prompt 偏保守 +（真因）glm-5.2 非流式
  把 JSON 包在 ``` ```json ``` ``` 围栏里，`json.loads` 抛 `char 0` 被吞 → facts 静默归零。
- 修复（已实施，见 KNOWN_ISSUES Issue #2 / `pd2_terminal_task.md` §5.13）：`nodes.py`
  `extract_memory` prompt 改三元组抽取 + 新增 `_parse_json_lenient` 容错解析。PD-3 同款
  受益，跨任务记忆复用正式生效。

### 5.15 "提示 PD-1 监管 Agent 跟进" 仅文字承诺，无实际交接
- 现象：prompt 步骤 5 要求"提示 PD-1 监管 Agent 跟进"，agent 在 .docx 里
  写了这句，但**没有实际触发 PD-1 agent 任务**。
- 根因：当前 agent 框架不支持跨 agent 任务交接（PD-3 不能调用 PD-1 agent
  生成新任务）。
- 影响：spec 履行度问题，不是 bug。闭环待办只是文字承诺，需要人工把待办
  转给 PD-1 agent owner 跟进。
- 修复（可选）：在 agent 框架里加跨 agent 任务交接机制（如 PD-3 写入
  "pending_followup" 队列，PD-1 agent 启动时拉取），非本期演示范围。

### 5.16 瘦提示词后 RAG 未触发 + 探索开销上升（v7c 揭示的真实边界）
- 现象（v7c）：§3.4 提示词瘦身后（删执行步骤/输出格式/不要臆造，只留角色+
  目标+两款款号+feasibility gap 规则+技能 chip），`trace rag` **未触发**——
  retrieve_rag 节点靠 user message 语义命中，「基于历史缺陷知识库做风险预警」
  措辞匹配度不够，没进检索。同时 tool_calls 24（v7b 为 7）、input 158k（v7b 为 62k）。
- 根因：
  1. RAG 触发靠语义——原版提示词 §3.4 关键2 即指出「必须显式写检索服装缺陷
     知识库 RAG 字样，否则可能跳过检索节点」。瘦版把这行也删了，故未触发。
  2. 探索开销上升——删手把手步骤后 agent 自主从 [数据接口]目录+本体选端点，
     多探了 listQcReports×5 / getBulkOrder×4 / listBulkOrders×2 / listSamplingOrders×2
     等原版未要求的端点（agent 在「找缺陷来源」时把 QC/大货/打样都查了一遍）。
- 影响：**闭环不塌方**（0 失败、4 段上屏、getFabric 自主调对 F- 码），但有
  资源浪费与 RAG 缺失。
- 处置：
  1. RAG 意图不靠删——瘦提示词仍需点一句「检索服装缺陷知识库」，或把检索
     触发条件从「query 语义」改为 retrieve_rag 节点配置（按技能/场景强制检索）。
  2. 探索开销靠**端点 description 补准 + 本体实体关系写清**压回——让 agent
     知道「缺陷来自 QcReport，不必既调 getBulkOrder 又调 listQcReports 查同一
     件事」，而非恢复手把手步骤。这是 plan 第 2 步（端点 description）的价值。
- 详见 §4.6 v7c 说明。

### 5.17 agent-template 层把 persona/policy 搬出用户提示词（v7d 验证态）
- 背景：v7c 把「执行步骤/输出格式/不要臆造」搬出用户提示词后，还剩 persona + feasibility
  gap policy 这两段业务用户写不出的内容赖在提示词里（见 §5.16 上方讨论）。要彻底搬出，
  需要一个「场景模板」承载 persona + 不可由本体/目录推导的业务规则 + 输出骨架。
- 实现（最小切法，不复活完整 Agent 实体、不开 workflow/judge）：
  1. `TaskConfig.template_agent_id`（可选，引用一个 Agent 行）+ `AgentState.template_agent_id`
     （**必须声明在 TypedDict，否则 langgraph 丢弃该 key，load_config 读到 None**——
     v7d1 即此 bug，template:false）。
  2. `_load_config_general` 若 template_agent_id 存在，`db.get(Agent, …)`，把
     `agent.system_prompt` 拼到 `GENERAL_SYSTEM_PROMPT` 前作 persona/policy 前缀；task
     config 未显式设 skill_ids/model_alias 时继承模板绑定。发 `trace category=template`。
  3. PD-3 的 `starclothing-pd3-defect-closure` Agent system_prompt 重写为精简模板
     （persona + RAG cue + feasibility policy + 4 段骨架，796 字符），seed 脚本同步更新
     （注：seed_starclothing_agents.py 因 reorg 把技能文件夹搬到部门 scope，按 org scope
     解析 skill_slugs 失败，需直接 upsert system_prompt 或修 seed 的 scope 解析）。
- 验证（v7d2）：用户 composer 216 字符（目标+款号+chip），tool_calls 11、0 失败、
  4 段全上屏、RAG 5 hits、getFabric F- 码 0 失败、feasibility policy 生效（text 含
  监管 Agent/水压）。**四层架构全绿**：runtime 输出协议 + 本体 identifiers.md + template
  + 用户 216 字符目标。
- 注意：RAG 触发仍由 retrieve_rag 节点按 user message 语义命中（template 的 RAG cue 在
  system_prompt，主要让 agent 知道要用 RAG 结果，不直接触发检索节点）。v7c RAG 未触发、
  v7d2 触发，差异主要在 user message 的 embedding（216 字符「基于历史缺陷知识库…」比
  v7c 的 584 字符含 feasibility 段更贴近缺陷 chunk）。RAG 触发稳定性仍是待解边界（§5.16）。
- 详见 §4.6 v7d 说明。

---

## 6. 附：手工调 API 复现

```bash
# 1) 登录拿 user token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"starclothing","username":"qc-lead","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) 解析 PD-3 Agent 模板 id（v7d 起任务 config 必须绑 template_agent_id；
#    skill_ids 留空从模板继承，model 留空继承 claude-opus-4）
TPL_ID=$(docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -tAc \
  "SELECT id FROM agents WHERE slug='starclothing-pd3-defect-closure' AND deleted_at IS NULL AND organization_id='54f5f892-cf08-4a75-88b2-b649fea392a4'")
echo "template_agent_id=$TPL_ID"

# 3) 创建任务（绑模板；skill_ids 留空从模板继承，model_alias 留空继承 claude-opus-4）
TASK_ID=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"title\":\"PD-3 新品缺陷风险预警与闭环待办\",\"message\":\"\",\"config\":{\"template_agent_id\":\"$TPL_ID\",\"skill_ids\":[],\"model_alias\":\"claude-opus-4\",\"exec_mode\":\"craft\"}}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 4) 运行（短 composer 作为 message，见 §3.4；含技能 chip + RAG 触发字样）
curl -sN -X POST "http://localhost:8000/api/v1/terminal/tasks/${TASK_ID}/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"message\":\"新品开发评审会：款号 P-FW2026-002 压胶冲锋衣即将进入大货试产，款号 P-FW2026-001 双面呢大衣即将进入量产。请基于历史缺陷知识库做风险预警。\\n\\n/starclothing-plm-query\",\"stream\":true}"
```

短 composer 提示词文本见 §3.4（persona / RAG cue / feasibility_log 闭环待办规则 / 输出格式
由 PD-3 Agent 模板 `system_prompt` 承载，不在 composer 里）。
