"""DLP Rule ORM model."""


from sqlalchemy import Boolean, ForeignKey, Integer, String, Text

# 使用 UUID 而非 str 作为 scope_id 类型，因为可能关联不同表
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class DlpRule(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "dlp_rules"

    # 规则一律归属到某组织（无全局规则概念）；保留 nullable 仅为历史迁移兼容
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 规则类型与动作
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False)  # regex, keyword, ner, custom
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # low, medium, high, critical
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # block, redact, warn, log
    direction: Mapped[str] = mapped_column(String(20), nullable=False)  # request, response, both

    # 规则内容：正则表达式、关键词列表(JSON)、实体类型列表、自定义代码
    pattern: Mapped[str] = mapped_column(Text, nullable=False)

    # 作用范围
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)  # organization, department, team
    scope_id: Mapped[str | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 越高越先评估
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # 关系
    organization = relationship("Organization", back_populates="dlp_rules")
