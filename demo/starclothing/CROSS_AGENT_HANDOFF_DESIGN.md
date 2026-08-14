# 跨 Agent 任务交接机制设计

> 解决 `pd3_terminal_task.md` §5.15 标注的「闭环待办只是文字承诺，没有真正跨 agent
> 交接」问题。本期未实施，本设计供新组织 / 后续迭代时落地参考。

---

## 问题背景

PD-3 闭环场景 spec 要求："未落实项标注闭环待办并提示 PD-1 监管 Agent 跟进"。
当前实现：
- PD-3 agent 在 `.docx` 报告里**写一句**"需 PD-1 监管 Agent 跟进"
- 但 PD-1 agent **不会自动被触发**新任务
- 闭环待办只是文字承诺，需要人工把待办转给 PD-1 agent owner

agent 框架当前局限：
1. agent A 完成任务后不能调用 agent B 生成新任务
2. 没有 `pending_followup` 队列让 agent B 启动时拉取
3. 没有任务状态机让"闭环待办 → 已跟进 → 已闭环"流转

---

## 设计目标

1. **PD-3 完成时写入待办**：闭环分析里发现"预防措施未在 feasibility_log 中落实"
   的款号，按一条 `pending_followup` 记录入库
2. **PD-1 启动时拉取待办**：PD-1 agent 启动时自动查询指向自己的 pending 待办，
   作为本轮任务上下文输入
3. **状态机流转**：`pending → in_progress → resolved`，PD-1 处理完写回 resolved
4. **可追溯**：每个 followup 关联 source_task（PD-3 任务）+ target_agent（PD-1 agent）
   + created_at + resolved_at，便于审计

---

## 数据模型

新增 `agent_followups` 表（SQLAlchemy ORM 模型，仿 `Task` 风格）：

```python
# app/models/agent_followup.py
"""跨 agent 任务交接队列。"""

from datetime import datetime
from sqlalchemy import ForeignKey, String, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AgentFollowup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """闭环待办 / 跨 agent 交接记录。"""

    __tablename__ = "agent_followups"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    # 来源：哪个 task / agent 产生的待办
    source_task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # 目标：交给哪个 agent 处理
    target_agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    # 状态机：pending / in_progress / resolved / skipped
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
    )
    # 待办类型：闭环验证 / 缺陷跟进 / 交期预警 / 自定义
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    # 待办标题 + 详细描述（给 target agent 的 prompt 上下文）
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 结构化上下文（款号 / 工单号 / 缺陷类型 / 责任人 等）
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 处理结果（target agent 处理完后回填）
    resolution: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolved_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )
```

Alembic migration（参考 `alembic/versions/0028_*` 风格新建 `0029_agent_followups.py`）：
```python
def upgrade():
    op.create_table(
        "agent_followups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_task_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_agent_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_agent_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("category", sa.String(50), nullable=False, server_default="general"),
        sa.Column("title", sa.String(500), nullable=False, server_default=""),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("context", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("resolution", sa.Text(), nullable=False, server_default=""),
        sa.Column("resolved_task_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_followups_org_target_status", "agent_followups",
                    ["organization_id", "target_agent_id", "status"])
```

---

## 写入端：PD-3 agent 输出闭环待办

### 方案 A：内置工具 `create_followup`（推荐）

在 `_builtin_tool_defs()`（`app/agents/graph/nodes.py`）新增一个内置工具，让 agent
在分析过程中**显式调用**写入待办，而不是只写在 docx 里：

```python
def _builtin_tool_defs() -> list[dict]:
    return [
        # ... 现有 generate_docx / web_search 等
        {
            "type": "function",
            "name": "create_followup",
            "description": "登记一条跨 agent 闭环待办。用于把当前任务的未落实项"
                           "交给另一 agent 后续跟进。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_agent_slug": {"type": "string", "description": "目标 agent 的 slug"},
                    "category": {"type": "string", "description": "闭环验证 / 缺陷跟进 / 交期预警"},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "context": {"type": "object", "description": "结构化上下文：款号/工单号/缺陷类型"},
                },
                "required": ["target_agent_slug", "title"],
            },
        },
    ]

async def _execute_builtin_tool(state: AgentState, name: str, params: dict) -> str:
    if name == "create_followup":
        # 1. 反查 target_agent_id by slug（同组织内）
        # 2. 写入 agent_followups 表，status=pending
        # 3. 返回成功消息，让 agent 在 text 流里说"已登记闭环待办 #F-xxxx 给 PD-1"
        ...
```

### 方案 B：extract_memory 节点扩展（轻量）

在 `extract_memory` 节点抽取 facts 后，**额外识别 `pending_followup` 类型的
事实**，自动写入 `agent_followups` 表。改动小但精度低——extract 当前对中文长文本
抽 0~3 facts（见 `KNOWN_ISSUES.md` #2），用同一通道做闭环待办抽取可靠性差。

**推荐方案 A**：让 agent 显式调 `create_followup`，把闭环待办从「docx 文字」
升级为「结构化记录」。

### PD-3 prompt 调整

在 prompt 第 5 步末尾加：
```
未落实项不要只写在 docx 里，必须用 `create_followup` 工具登记闭环待办，
target_agent_slug 填 `pd1-supervision`，让 PD-1 监管 Agent 启动时自动拉取。
```

---

## 拉取端：PD-1 agent 启动时读 pending 待办

### `load_memory` 节点扩展

在 `_load_memory_general`（`app/agents/graph/nodes.py:419`）后追加一个
`load_pending_followups` 子步骤：

```python
async def load_pending_followups(state: AgentState, deps, db) -> dict:
    """target_agent = 当前 agent 的 pending followups 拉取进上下文。"""
    agent_id = state.get("agent_id")
    org_id = state.get("organization_id")
    if not agent_id:
        return {"steps": [*state.get("steps", []), {"step": "load_pending_followups", "count": 0}]}

    result = await db.execute(
        select(AgentFollowup)
        .where(
            AgentFollowup.target_agent_id == agent_id,
            AgentFollowup.organization_id == org_id,
            AgentFollowup.status == "pending",
            AgentFollowup.deleted_at.is_(None),
        )
        .order_by(AgentFollowup.created_at.desc())
        .limit(10)
    )
    rows = result.scalars().all()
    if not rows:
        return {"steps": [*state.get("steps", []), {"step": "load_pending_followups", "count": 0}]}

    # 把待办拼成文本注入 messages context（system 提示部分追加）
    followup_text = "\n\n".join([
        f"【待办 #{f.id[:8]}】[{f.category}] {f.title}\n详情: {f.detail}\n上下文: {f.context}"
        for f in rows
    ])
    # 同步把 status 改为 in_progress（claim）
    for f in rows:
        f.status = "in_progress"
    await db.commit()

    return {
        "messages": [*state.get("messages", []),
                     {"role": "system",
                      "content": f"以下是来自其他 agent 的闭环待办，请在本轮任务中处理：\n\n{followup_text}"}],
        "loaded_followup_ids": [str(f.id) for f in rows],
        "steps": [*state.get("steps", []), {"step": "load_pending_followups", "count": len(rows)}],
    }
```

Graph 拓扑更新（`builder.py`）：
```
START → load_config → retrieve_rag → load_memory → load_pending_followups
      → agent_loop → save_memory → extract_memory → judge → write_run_log → END
```

### PD-1 prompt 调整

PD-1 prompt 第 1 步「拉取本任务相关的监管线索」改为：
```
1. 本任务会自动注入来自其他 agent（如 PD-3）的闭环待办——若有，请在分析
   "全流程进度汇总表" 时把待办项作为已识别风险纳入。处理完后调用
   `resolve_followup` 工具标记为已闭环。
```

---

## 状态机

```
   create_followup              load_pending_followups              resolve_followup
        │                              │                                  │
        ▼                              ▼                                  ▼
   ┌─────────┐  ───────────────►  ┌──────────────┐  ──────────────►  ┌──────────┐
   │ pending │  (PD-1 agent 启动) │ in_progress  │  (PD-1 处理完)   │ resolved │
   └─────────┘                    └──────────────┘                   └──────────┘
        │                                │                                  │
        │            超时未处理           │  跳过（不适用）                │
        └────────────────────────────►┌──────────┐                          │
                                       │ skipped  │ ◄──────────────────────┘
                                       └──────────┘
```

状态字段值：`pending` / `in_progress` / `resolved` / `skipped`

`skipped`：PD-1 agent 判断待办不适用（如款号已下线、缺陷已通过验收），调
`resolve_followup(status="skipped", resolution="...")` 标记跳过。

---

## 内置工具集

新增 2 个内置工具：

| 工具 | 调用方 | 用途 |
|---|---|---|
| `create_followup` | PD-3 agent | 写入一条 pending 待办 |
| `resolve_followup` | PD-1 agent | 标记 in_progress → resolved / skipped |

`resolve_followup` 签名：
```python
{
    "name": "resolve_followup",
    "description": "标记一条闭环待办为已处理。处理完后调用。",
    "parameters": {
        "type": "object",
        "properties": {
            "followup_id": {"type": "string", "description": "待办 ID（前 8 位即可）"},
            "status": {"type": "string", "enum": ["resolved", "skipped"]},
            "resolution": {"type": "string", "description": "处理结果说明"},
        },
        "required": ["followup_id", "status"],
    },
}
```

---

## 与现有 agent 框架的集成点

| 现有节点 | 改动 |
|---|---|
| `_builtin_tool_defs()` | 新增 `create_followup` / `resolve_followup` 两个工具定义 |
| `_execute_builtin_tool()` | 新增两个工具的执行分支（写 / 改 `agent_followups` 表） |
| `load_memory` 节点 | 后追加 `load_pending_followups` 子步骤（仅 general 模式） |
| `builder.py` 图拓扑 | `load_memory → load_pending_followups → agent_loop` |
| `judge` 节点 | 判定通过条件追加"loaded_followup_ids 全部 resolved"，否则本轮 fail |
| `write_run_log` | run_log metadata 增 `followups_created` / `followups_resolved` 字段 |

---

## 演示场景串联效果

实施后 PD-3 → PD-1 跨场景串联流程：

```
PD-3 任务执行
  ├─ 分析 4 段输出 + 生成 docx
  ├─ 识别未落实项（如"P-AP2026-030 异动预警未在 feasibility_log 落实"）
  └─ 调 create_followup(target_agent_slug="pd1-supervision", ...)
       → 写入 agent_followups(status=pending)

（用户切到 PD-1 agent 启动新任务）

PD-1 任务启动
  ├─ load_config → retrieve_rag → load_memory
  ├─ load_pending_followups
  │    → 拉取 PD-3 写入的 pending 待办
  │    → 注入到 messages 上下文
  │    → status 置为 in_progress
  ├─ agent_loop
  │    → 在"全流程进度汇总表"里把 PD-3 待办作为已识别风险纳入
  │    → 处理完调 resolve_followup(followup_id, status="resolved", resolution="...")
  └─ judge → write_run_log（run_log 含 followups_resolved 字段）
```

闭环待办不再只是 PD-3 docx 里的一句话，而是有状态、可追溯、自动拉取的真正跨 agent
协作机制。

---

## 验证清单

实施后用以下方式验证：

1. **写入侧**：PD-3 跑完后查
   ```sql
   SELECT id, title, status, target_agent_id FROM agent_followups
   WHERE source_task_id = '<pd3_task_id>';
   ```
   应有 ≥1 条 pending。

2. **拉取侧**：PD-1 启动后 trace 应有 `load_pending_followups` 步骤，count ≥1；
   消息上下文应含"以下是来自其他 agent 的闭环待办"。

3. **状态流转**：PD-1 处理完后 followup status = resolved，resolution 非空，
   resolved_task_id 指向 PD-1 任务。

4. **judge 判定**：若 `loaded_followup_ids` 非空但未全部 resolved，judge 应判 fail
   并在 run_log 注明。

---

## 风险与限制

1. **claim 竞态**：若 PD-1 agent 多实例并行启动，可能同时 claim 同一 followup
   为 in_progress。建议在 `load_pending_followups` 用
   `SELECT ... FOR UPDATE SKIP LOCKED` 加锁。
2. **死循环**：PD-1 处理不完会导致 followup 长期 in_progress。建议加超时回退
   机制（如 24h 未 resolved 自动回 pending）——本期设计不含。
3. **agent slug 解析**：`create_followup` 需要在同组织内按 slug 反查 agent_id，
   要求每个 agent 的 slug 唯一（已有约束）。
4. **prompt 兼容**：现有 PD-3 v3 prompt 不含 `create_followup` 调用指令，
   需在 prompt 第 5 步追加（参考 PD-3 §3.4 修订说明）。

---

## 实施工作量估算

| 模块 | 工作量 |
|---|---|
| `agent_followups` 表 + Alembic migration | 0.5 day |
| 2 个内置工具 + 执行分支 | 1 day |
| `load_pending_followups` 节点 + 图拓扑改 | 0.5 day |
| PD-3 / PD-1 prompt 调整 + 验证 | 1 day |
| 端到端测试（PD-3 → PD-1 串联） | 1 day |
| **合计** | **4 day** |

非本期演示范围。新组织若需要跨 agent 协作演示（如供应链预警 → 采购跟进 →
财务对账的 3-agent 串联），建议先实施本设计。

---

## 参考文档

- `pd3_terminal_task.md` §3.4 prompt / §5.15 现状描述
- `pd1_terminal_task.md` §3.4 prompt（拉取闭环待办后需调整）
- `KNOWN_ISSUES.md` #3 跨 agent 交接机制缺失
- `app/agents/graph/nodes.py` `_builtin_tool_defs` / `load_memory` / `extract_memory`
- `app/agents/graph/builder.py` 图拓扑
- `app/models/task.py` Task 模型参考
