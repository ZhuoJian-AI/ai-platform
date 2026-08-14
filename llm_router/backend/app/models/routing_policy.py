"""Routing Policy ORM model — maps model pattern to provider list."""

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class RoutingPolicy(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "routing_policies"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 匹配规则
    model_pattern: Mapped[str] = mapped_column(String(255), nullable=False)  # glob 模式，如 "claude-opus-*"
    strategy: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # priority, round_robin, weighted, least_latency, failover

    # 有序的 provider UUID 列表
    provider_ids: Mapped[list] = mapped_column(JSONB, nullable=False)

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 关系
    organization = relationship("Organization", back_populates="routing_policies")
