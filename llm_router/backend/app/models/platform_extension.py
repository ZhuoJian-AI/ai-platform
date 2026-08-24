"""Platform-wide reviewed extension sources and immutable runtime releases."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PlatformExtensionSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An imported extension candidate. Importing never activates code."""

    __tablename__ = "platform_extension_sources"

    source_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    requested_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    build_report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    compatibility: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="importing", index=True)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_by_admin_id: Mapped[int] = mapped_column(
        ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    approved_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformExtensionRelease(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable full snapshot of the platform runtime/tool extension set."""

    __tablename__ = "platform_extension_releases"
    __table_args__ = (
        Index(
            "uq_platform_extension_releases_one_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    version_no: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    base_release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_extension_releases.id", ondelete="SET NULL"), nullable=True
    )
    created_by_admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False)
    published_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL"), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PlatformExtensionReleaseEvent(TimestampMixin, Base):
    """Append-only audit trail for import, validation, publish and rollback."""

    __tablename__ = "platform_extension_release_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_extension_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_extension_releases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ok")
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
