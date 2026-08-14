"""Memory ORM model — hierarchical long-term memory (org / dept / team / user).

区别于 ``AgentMessage``（按 session 的对话消息）：Memory 是智能体跨会话沉淀的长期事实/偏好，
按 scope_type + scope_id 分级。组织/部门/团队级由管理端维护；个人级（scope_type='user'）
由终端智能体经 ``extract_memory`` 节点自行沉淀。运行时 ``load_memory`` 按 4 级聚合注入。
"""

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Memory(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """分级长期记忆条目。"""

    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memory_scope", "organization_id", "scope_type", "scope_id"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # organization / department / team / user
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # org 级为 None；其余为对应 dept/team/user id
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="general")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # manual（管理端维护）/ auto（智能体沉淀，仅 user 级）
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    # 维度无关向量列（语义召回；v1 按 recency 载入，向量留作扩展）
    embedding: Mapped[list | None] = mapped_column(Vector(None), nullable=True)
