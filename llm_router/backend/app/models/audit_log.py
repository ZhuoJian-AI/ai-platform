"""Audit Log ORM model — append-only, never update or delete."""

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(nullable=False, index=True)
    api_key_id: Mapped[str | None] = mapped_column(ForeignKey("api_keys.id"), nullable=True)

    # 作用范围
    organization_id: Mapped[str] = mapped_column(nullable=False, index=True)
    department_id: Mapped[str | None] = mapped_column(nullable=True)
    team_id: Mapped[str | None] = mapped_column(nullable=True)
    provider_id: Mapped[str | None] = mapped_column(nullable=True)

    # 事件详情
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    direction: Mapped[str | None] = mapped_column(String(20), nullable=True)  # inbound, outbound

    # 模型信息
    model_requested: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_served: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 用量
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # DLP 违规
    dlp_violations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # 响应状态
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 扩展元数据
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
