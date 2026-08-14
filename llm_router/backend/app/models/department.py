"""Department ORM model."""

from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Department(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_dept_org_slug"),)

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # 部门级限制 (NULL = 继承组织)
    rate_limit_rpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_tpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_cap_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # 预算上限（以 token 计）；NULL = 继承组织
    budget_cap_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 关系
    organization = relationship("Organization", back_populates="departments")
    teams = relationship("Team", back_populates="department", lazy="selectin")
