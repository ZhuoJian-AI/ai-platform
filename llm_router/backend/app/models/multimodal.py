"""Durable audio jobs and tenant-isolated voice governance records."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class MultimodalJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "multimodal_jobs"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "idempotency_key", name="uq_multimodal_job_idempotency"),
        CheckConstraint(
            "status IN ('queued','processing','succeeded','failed','cancelled')",
            name="ck_multimodal_job_status",
        ),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    capability: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    deployment_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_deployments.id", ondelete="SET NULL"), nullable=True,
    )
    input_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="SET NULL"), nullable=True,
    )
    output_file_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "voice_profiles.id",
            name="multimodal_jobs_voice_profile_id_fkey",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audio_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class VoiceProfile(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "voice_profiles"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_voice_profile_org_name"),
        CheckConstraint("voice_type IN ('builtin','designed','cloned')", name="ck_voice_profile_type"),
        CheckConstraint("status IN ('active','disabled','pending_cleanup')", name="ck_voice_profile_status"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    created_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    voice_type: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_voice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    design_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="SET NULL"), nullable=True,
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    grants = relationship(
        "VoiceProfileGrant",
        primaryjoin=(
            "and_(VoiceProfile.id == VoiceProfileGrant.voice_profile_id, "
            "VoiceProfileGrant.deleted_at.is_(None))"
        ),
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    authorization = relationship("VoiceAuthorizationRecord", lazy="selectin", uselist=False)


class VoiceProfileGrant(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "voice_profile_grants"
    __table_args__ = (
        UniqueConstraint("voice_profile_id", "scope_type", "scope_id", name="uq_voice_profile_grant_scope"),
        CheckConstraint(
            "scope_type IN ('organization','role','department','user')",
            name="ck_voice_profile_grant_scope",
        ),
    )

    voice_profile_id: Mapped[str] = mapped_column(ForeignKey("voice_profiles.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class VoiceAuthorizationRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "voice_authorization_records"

    voice_profile_id: Mapped[str] = mapped_column(ForeignKey("voice_profiles.id", ondelete="CASCADE"), unique=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    rights_holder: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_file_id: Mapped[str] = mapped_column(ForeignKey("workspace_files.id", ondelete="RESTRICT"))
    confirmed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    confirmed_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL"), nullable=True,
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
