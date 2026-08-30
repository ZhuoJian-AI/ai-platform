"""Tenant business applications embedded in the terminal and their access grants."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    integration = relationship(
        "EnterpriseApplicationIntegration",
        back_populates="application",
        lazy="selectin",
        uselist=False,
    )
    event_routes = relationship(
        "EnterpriseApplicationEventRoute",
        back_populates="application",
        lazy="selectin",
        foreign_keys="EnterpriseApplicationEventRoute.application_id",
    )
    actions = relationship("EnterpriseApplicationAction", back_populates="application", lazy="selectin")
    action_requests = relationship(
        "EnterpriseApplicationActionRequest", back_populates="application", lazy="selectin"
    )


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
    # Empty means every module, preserving the behaviour of grants created before 0043.
    module_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Protocol v2: per-submodule role + permissions. Empty preserves v1 behaviour.
    module_access: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

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
            "operation IN ('query','create','update','delete','export','approve')",
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


class EnterpriseApplicationIntegration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Private connection state for one independently deployed subsystem."""

    __tablename__ = "enterprise_application_integrations"
    __table_args__ = (
        UniqueConstraint("application_id", name="uq_enterprise_application_integration_app"),
        CheckConstraint(
            "sync_status IN ('unconfigured','ready','syncing','healthy','error')",
            name="ck_enterprise_application_integration_status",
        ),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    manifest_url: Mapped[str] = mapped_column(Text, nullable=False)
    events_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    cursor_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sync_status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    last_manifest_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    application = relationship("EnterpriseApplication", back_populates="integration")


class EnterpriseApplicationAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Manifest-discovered command shared by page buttons and AI assistants."""

    __tablename__ = "enterprise_application_actions"
    __table_args__ = (
        UniqueConstraint("application_id", "action_key", name="uq_enterprise_application_action_key"),
        CheckConstraint(
            "operation IN ('query','create','update','delete','export','approve')",
            name="ck_enterprise_application_action_operation",
        ),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    action_key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    application = relationship("EnterpriseApplication", back_populates="actions")
    requests = relationship("EnterpriseApplicationActionRequest", back_populates="action", lazy="selectin")


class EnterpriseApplicationActionRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Replay-safe execution and optional human-confirmation record for one action."""

    __tablename__ = "enterprise_application_action_requests"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "user_id",
            "request_id",
            name="uq_enterprise_application_action_request",
        ),
        CheckConstraint(
            "status IN ('pending','executing','completed','rejected','expired','failed')",
            name="ck_enterprise_application_action_request_status",
        ),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_application_actions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    module_key: Mapped[str] = mapped_column(String(120), nullable=False)
    params_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    application = relationship("EnterpriseApplication", back_populates="action_requests")
    action = relationship("EnterpriseApplicationAction", back_populates="requests")


class EnterpriseApplicationEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable receipt used for replay-safe subsystem event ingestion."""

    __tablename__ = "enterprise_application_events"
    __table_args__ = (
        UniqueConstraint("application_id", "event_id", name="uq_enterprise_application_event_id"),
        UniqueConstraint("application_id", "source_sequence", name="uq_enterprise_application_event_sequence"),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    module_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    action: Mapped[str | None] = mapped_column(String(80), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class EnterpriseApplicationEventRoute(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Administrator-owned rule that turns a subsystem event into a scoped work item."""

    __tablename__ = "enterprise_application_event_routes"
    __table_args__ = (
        CheckConstraint(
            "target_scope_type IN ('organization','department','team','user')",
            name="ck_enterprise_application_event_route_scope_type",
        ),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    module_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_application_id: Mapped[str | None] = mapped_column(
        ForeignKey("enterprise_applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    target_module_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    application = relationship(
        "EnterpriseApplication", back_populates="event_routes", foreign_keys=[application_id]
    )
    target_application = relationship("EnterpriseApplication", foreign_keys=[target_application_id])


class EnterpriseApplicationEventDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Replay-safe outbound delivery from one subsystem event to another subsystem."""

    __tablename__ = "enterprise_application_event_deliveries"
    __table_args__ = (
        UniqueConstraint("route_id", "source_event_id", name="uq_enterprise_event_delivery_route_event"),
        CheckConstraint(
            "status IN ('pending','delivering','delivered','failed')",
            name="ck_enterprise_event_delivery_status",
        ),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    route_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_application_event_routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_event_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_application_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_application_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    delivery_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CrossDepartmentWorkItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Central, department-scoped notification produced from a subsystem event."""

    __tablename__ = "cross_department_work_items"
    __table_args__ = (
        UniqueConstraint("route_id", "source_event_id", name="uq_cross_department_work_item_route_event"),
        CheckConstraint("status IN ('open','done')", name="ck_cross_department_work_item_status"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_application_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    route_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_application_event_routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    target_scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    target_module_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
