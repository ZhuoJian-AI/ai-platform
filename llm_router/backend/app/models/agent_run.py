"""AgentRun ORM model — execution records for agent test playground & monitoring."""

import uuid

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class AgentRun(TimestampMixin, Base):
    """单次智能体执行记录（测试广场 / 监控共用）。append-only，不软删。"""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # 管理端 playground：agent_id 非空；终端通用智能体：agent_id 为空、task_id 非空
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 执行模式：craft（自主执行）/ ask（只读问答）/ plan（出方案不执行）。
    # general 运行取自 task.config；agent 运行（测试广场）恒为 craft。监控台据此拆分通用三类。
    exec_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="craft")
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    request: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 完整消息序列（含 user/assistant/tool），便于回放
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # 逐步执行轨迹（节点名、耗时、工具调用、RAG 命中等）
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # queued / running / success / error / cancelled / timeout / busy
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # judge 评分结果（若启用判官节点）
    judge_score: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    agent = relationship("Agent", back_populates="runs")


class AgentRunEvent(Base, TimestampMixin):
    """单次 run 的 SSE 事件流（按 seq 顺序回放）。

    后台 runner 边产边落库每条 step/trace/phase/tool_call/tool_result/text/done/final/error
    事件，使「客户端断连 → resume 端点回放 + 续接 live」成为可能（runner.py detach 执行）。
    append-only，不软删。run_id 可空（首事件 load_config 之前不可能有，但保留容错）。
    """

    __tablename__ = "agent_run_events"
    __table_args__ = (
        Index("ix_agent_run_events_run_seq", "run_id", "seq"),
        Index("ix_agent_run_events_task_seq", "task_id", "seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
