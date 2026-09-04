"""Task & TaskMessage ORM models — 终端用户的通用智能体任务线程。

一个 Task = 用户在终端创建的一次任务/对话线程，携带按任务装配的资源配置（workspace /
skills / ontology / rag）。TaskMessage 为线程内逐轮消息（user/assistant/tool），
供 ``load_memory`` 载入本任务对话历史、前端渲染对话流。每次执行同时落一条 ``AgentRun``
（agent_id 为空、task_id 非空）供监控台复用。
"""

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Task(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """终端任务线程 + 资源配置。"""

    __tablename__ = "tasks"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    department_id: Mapped[str | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 任务装配配置：{workspace_id, skill_ids[], ontology_ids[], rag_collection_ids[],
    #   model_alias}；空数组 = 该维度按用户权限自动匹配全集。
    #   长期记忆不在此配置：运行时按用户权限自动载入 4 级记忆全集。
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active / archived

    messages = relationship("TaskMessage", back_populates="task", lazy="selectin",
                            order_by="TaskMessage.created_at")


class TaskMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """任务线程内单轮消息。"""

    __tablename__ = "task_messages"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user / assistant / tool
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 工具调用元数据（tool_calls / tool_call_id / name 等）
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    task = relationship("Task", back_populates="messages")


class TaskFileRef(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable task context index; never an authorization credential."""

    __tablename__ = "task_file_refs"
    __table_args__ = (
        UniqueConstraint("task_id", "workspace_file_id", name="uq_task_file_ref"),
    )

    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_file_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_file_versions.id", ondelete="SET NULL"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="turn", index=True)
    follow_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="message")
    workspace_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_path: Mapped[str | None] = mapped_column(String(1400), nullable=True)
