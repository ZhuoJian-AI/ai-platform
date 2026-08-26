"""Tenant business applications embedded in the terminal and their access grants."""

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class EnterpriseApplication(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "enterprise_applications"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_enterprise_application_org_slug"),
        CheckConstraint("display_mode IN ('embedded','external')", name="ck_enterprise_application_display_mode"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_url: Mapped[str] = mapped_column(Text, nullable=False)
    display_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="embedded")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    assistant_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    assistant_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    assistant_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    health_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")

    grants = relationship("EnterpriseApplicationGrant", back_populates="application", lazy="selectin")
    tool_bindings = relationship("EnterpriseApplicationToolBinding", back_populates="application", lazy="selectin")


class EnterpriseApplicationGrant(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "enterprise_application_grants"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "scope_type",
            "scope_id",
            name="uq_enterprise_application_grant_scope",
        ),
        CheckConstraint(
            "scope_type IN ('organization','department','team','user')",
            name="ck_enterprise_application_grant_scope_type",
        ),
        Index(
            "uq_enterprise_application_grant_org_scope",
            "application_id",
            unique=True,
            postgresql_where=text("scope_type = 'organization' AND scope_id IS NULL AND deleted_at IS NULL"),
        ),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    permissions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    application = relationship("EnterpriseApplication", back_populates="grants")


class EnterpriseApplicationToolBinding(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "enterprise_application_tool_bindings"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "target_type",
            "target_id",
            "operation",
            name="uq_enterprise_application_tool_binding",
        ),
        CheckConstraint(
            "target_type IN ('tool_endpoint','data_interface','skill_folder')",
            name="ck_enterprise_application_tool_binding_target_type",
        ),
        CheckConstraint(
            "operation IN ('query','create','update','delete','export')",
            name="ck_enterprise_application_tool_binding_operation",
        ),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    application = relationship("EnterpriseApplication", back_populates="tool_bindings")
