"""Budget Usage ORM model — tracks spend per scope per billing period."""

from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Date, Integer, Numeric, String, UniqueConstraint
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
