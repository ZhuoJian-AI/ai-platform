"""Coolify targets and deployment state for independently hosted enterprise modules."""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ModuleDeploymentProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Non-secret Coolify target selected by a platform or enterprise administrator."""

    __tablename__ = "module_deployment_profiles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "runtime_key", name="uq_module_deployment_profile_org_runtime"
        ),
        Index(
            "uq_module_deployment_profile_org_default",
            "organization_id",
            unique=True,
            postgresql_where=text("is_default = true"),
        ),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    runtime_key: Mapped[str] = mapped_column(String(80), nullable=False)
    server_uuid: Mapped[str] = mapped_column(String(120), nullable=False)
    project_uuid: Mapped[str] = mapped_column(String(120), nullable=False)
    environment_name: Mapped[str] = mapped_column(String(120), nullable=False, default="production")
    environment_uuid: Mapped[str | None] = mapped_column(String(120), nullable=True)
    destination_uuid: Mapped[str | None] = mapped_column(String(120), nullable=True)
    github_app_uuid: Mapped[str] = mapped_column(String(120), nullable=False)
    domain_suffix: Mapped[str] = mapped_column(String(255), nullable=False)
    use_build_server: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ModuleDeployment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One reusable Coolify application and its latest release state."""

    __tablename__ = "module_deployments"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "module_slug", name="uq_module_deployment_org_slug"
        ),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    deployment_profile_id: Mapped[str] = mapped_column(
        ForeignKey("module_deployment_profiles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("enterprise_applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    module_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    module_name: Mapped[str] = mapped_column(String(255), nullable=False)
    repository_name: Mapped[str] = mapped_column(String(255), nullable=False)
    coolify_application_uuid: Mapped[str] = mapped_column(String(120), nullable=False)
    entry_url: Mapped[str] = mapped_column(Text, nullable=False)
    integration_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    session_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    requested_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    last_success_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deployment_uuid: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rollback_deployment_uuid: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    failure_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(nullable=True)
