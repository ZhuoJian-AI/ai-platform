"""AgentMessage ORM model — persisted conversation memory per (agent, session)."""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AgentMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """单轮对话消息（user/assistant/tool），按 session_id 聚合为对话记忆。"""

    __tablename__ = "agent_messages"

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user / assistant / tool
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 工具调用相关元数据（tool_call_id / name 等），无则空
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
