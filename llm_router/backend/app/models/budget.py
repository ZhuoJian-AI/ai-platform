"""Budget Usage ORM model — tracks spend per scope per billing period."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BudgetUsage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "budget_usage"
    __table_args__ = (UniqueConstraint("scope_type", "scope_id", "period_start", name="uq_budget_scope_period"),)

    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)  # organization, department, team, api_key
    scope_id: Mapped[str] = mapped_column(nullable=False)

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AiQuotaEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only fact ledger for AI admission and final token settlement.

    Redis remains the atomic admission boundary.  This table is the durable,
    auditable source used to rebuild Redis counters and report usage even after
    an API key is revoked. One credit means one admitted platform AI operation;
    it remains consumed after failure, while internal retry/failover keeps the
    same reservation. Database triggers created by migration 0066 reject UPDATE
    and DELETE so history cannot be rewritten in place.
    """

    __tablename__ = "ai_quota_events"
    __table_args__ = (
        UniqueConstraint(
            "reservation_id",
            "scope_type",
            "scope_id",
            "event_type",
            name="uq_ai_quota_event_phase",
        ),
        Index("ix_ai_quota_events_org_created", "organization_id", "created_at"),
        Index("ix_ai_quota_events_scope_created", "scope_type", "scope_id", "created_at"),
        Index(
            "ix_ai_quota_events_created_at_brin",
            "created_at",
            postgresql_using="brin",
        ),
    )

    reservation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    department_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    team_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    api_key_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    operation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    reserved_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    actual_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
