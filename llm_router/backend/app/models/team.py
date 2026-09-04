"""Team ORM model."""

from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Team(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("department_id", "slug", name="uq_team_dept_slug"),)

    department_id: Mapped[str] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False
    )
    # 反规范化，加速查询
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # 团队级限制 (NULL = 依次继承部门→组织)
    rate_limit_rpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_tpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_cap_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # 预算上限（以 token 计）；NULL = 依次继承部门→组织
    budget_cap_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 每月平台 AI 操作准入次数；失败不退，NULL = 依次继承部门→组织
    budget_cap_credits: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 关系
    department = relationship("Department", back_populates="teams")
