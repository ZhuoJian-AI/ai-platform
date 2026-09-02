"""Organization ORM model."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "organizations"

    # name / slug 在平台内对未软删组织唯一；partial unique index 由迁移 0028 创建，
    # 软删组织不占用槽位。这里不再声明 unique=True（会生成非 partial 约束）。
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # 是否为平台默认组织（全平台至多一个，由超管在「组织管理」设定）；
    # 各管理页面优先展示该组织。部分唯一索引由迁移 0009 创建。
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 组织级限制
    rate_limit_rpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_tpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_cap_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # 预算上限（以 token 计）；NULL = 不限
    budget_cap_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 关系
    departments = relationship("Department", back_populates="organization", lazy="selectin")
    users = relationship("User", back_populates="organization", lazy="selectin")
    api_keys = relationship("ApiKey", back_populates="organization", lazy="selectin")
    providers = relationship("LlmProvider", back_populates="organization", lazy="selectin")
    dlp_rules = relationship("DlpRule", back_populates="organization", lazy="selectin")
    routing_policies = relationship("RoutingPolicy", back_populates="organization", lazy="selectin")
class OrganizationSlugAlias(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Historical organization slug kept as a permanent login alias."""

    __tablename__ = "organization_slug_aliases"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
