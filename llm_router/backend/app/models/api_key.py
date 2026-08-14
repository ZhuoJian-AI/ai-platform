"""API Key ORM model — hierarchical key system."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"

    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    key_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")  # AES-256-GCM 加密存储
    key_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # 层级范围
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)  # organization, department, team

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    department_id: Mapped[str | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # 权限配置
    allowed_models: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # 空=全部
    rate_limit_rpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_tpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_cap_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # 预算上限（以 token 计）；NULL = 继承上层
    budget_cap_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关系
    organization = relationship("Organization", back_populates="api_keys")
