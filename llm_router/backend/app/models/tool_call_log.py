"""ToolCallLog ORM model — append-only record of tool invocations (for monitoring)."""

from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ToolCallLog(TimestampMixin, Base):
    """单次工具端点调用记录（监控/测试广场共用）。append-only。"""

    __tablename__ = "tool_call_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    connector_id: Mapped[str | None] = mapped_column(
        ForeignKey("tool_connectors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    endpoint_id: Mapped[str | None] = mapped_column(
        ForeignKey("tool_endpoints.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Runtime records SkillFolder ids. Migration 0025 intentionally removed the
    # legacy FK to the dormant ``skills`` table, but the physical column remains
    # PostgreSQL UUID.  Keep it as a loose UUID reference without an FK.
    skill_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)

    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
