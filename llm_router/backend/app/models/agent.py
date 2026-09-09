"""Text-only reusable persona for the personal Assistant Core."""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """智能体只保存文本角色定义；能力与权限全部继承当前员工。"""

    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope_type", "scope_id", "slug", name="uq_agent_scope_slug"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # 作用范围：organization / department / user；scope_id 为对应 id（org 级为 None）。
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="organization")
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # 创建者（终端用户 id）；管理员或历史数据为 None，纯字符串无 FK。
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    runs = relationship("AgentRun", back_populates="agent", lazy="noload")
