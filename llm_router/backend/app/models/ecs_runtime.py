"""Direct ECS runtimes and module release state for tenant-owned infrastructure."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EcsRuntime(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One administrator-initialized ECS that may publish modules for one tenant."""

    __tablename__ = "ecs_runtimes"
    __table_args__ = (
        UniqueConstraint("organization_id", "runtime_key", name="uq_ecs_runtime_org_key"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    runtime_key: Mapped[str] = mapped_column(String(80), nullable=False)
    enterprise_key: Mapped[str] = mapped_column(String(80), nullable=False)
    environment: Mapped[str] = mapped_column(String(40), nullable=False, default="staging")
    domain_suffix: Mapped[str] = mapped_column(String(255), nullable=False)
    public_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credential_prefix: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    credential_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    credential_rotated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EcsModuleRelease(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Latest direct-ECS release registered for an enterprise application."""

    __tablename__ = "ecs_module_releases"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "application_slug", name="uq_ecs_module_release_org_slug"
        ),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    runtime_id: Mapped[str] = mapped_column(
        ForeignKey("ecs_runtimes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("enterprise_applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    application_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    application_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    requested_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    last_success_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_revision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    manifest_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="verifying")
    release_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
