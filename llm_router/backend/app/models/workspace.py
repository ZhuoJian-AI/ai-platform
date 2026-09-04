"""Workspace ORM models — governed tenant file storage and immutable versions."""

from datetime import UTC, datetime

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


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """智能体工作空间：限定 agent 文件读写的根作用域。"""

    __tablename__ = "workspaces"
    __table_args__ = (
        Index(
            "uq_workspace_org_slug_active",
            "organization_id",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 存储后端：local（本地文件系统）/ s3（后续扩展）。运行时按 backend 解析 content_ref。
    storage_backend: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    # 本地后端下的根目录（相对平台 workspace 根的子路径）；s3 后端为 bucket 前缀。
    root_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 作用范围：organization/department/team/user
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="organization")
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    files = relationship("WorkspaceFile", back_populates="workspace", lazy="selectin")
    folders = relationship("WorkspaceFolder", back_populates="workspace", lazy="selectin")


class WorkspaceFile(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """工作空间内的文件元数据。content_ref 指向存储后端中的实际内容定位。"""

    __tablename__ = "workspace_files"
    # Only a live path is unique.  A deleted file keeps its stable identity and
    # immutable versions for historical task references, while a later upload
    # to the same path receives a brand-new file id.
    __table_args__ = (
        Index(
            "uq_wsfile_path_active",
            "workspace_id",
            "path",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)  # 相对 workspace root 的 POSIX 路径
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # legacy local 为相对路径；对象存储为 oss://<project-scoped-object-key>。
    content_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 内联文本内容（小文件直接落库，便于在线编辑与 agent 即时读取）。
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Office/PDF 等二进制文件的结构化文本解析结果；原文件由 content_ref 定位。
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unparsed")
    parse_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "workspace_file_versions.id",
            name="fk_wsfile_current_version",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    deleted_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deleted_by_admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    parse_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parse_locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    workspace = relationship("Workspace", back_populates="files")
    versions = relationship(
        "WorkspaceFileVersion", foreign_keys="WorkspaceFileVersion.workspace_file_id",
        back_populates="file", cascade="all, delete-orphan", lazy="selectin",
    )


class WorkspaceFolder(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """工作空间内的文件夹元数据。path 为相对 workspace root 的 POSIX 路径，
    嵌套靠路径段表达（与文件一致）；可独立存在以支持空文件夹。"""

    __tablename__ = "workspace_folders"
    __table_args__ = (UniqueConstraint("workspace_id", "path", name="uq_wsfolder_path"),)

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)  # 相对 workspace root 的 POSIX 路径
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    workspace = relationship("Workspace", back_populates="folders")


class WorkspaceFileVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable snapshot pinned by tasks, shares and audit records."""

    __tablename__ = "workspace_file_versions"
    __table_args__ = (
        UniqueConstraint("workspace_file_id", "version_no", name="uq_wsfile_version"),
        UniqueConstraint(
            "workspace_file_id",
            "mutation_idempotency_key",
            name="uq_wsfile_version_mutation_key",
        ),
    )

    workspace_file_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # Optional client mutation identity.  It is scoped to one stable file id so
    # retried edits cannot create duplicate versions.
    mutation_idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    mutation_request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # OSS object versions are independent from IMM's numeric save counter and
    # from this table's version_no.  Historical downloads must pin this exact
    # opaque VersionId when multiple logical versions share one object key.
    storage_version_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    storage_etag: Mapped[str | None] = mapped_column(String(256), nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unparsed")
    parse_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)

    file = relationship("WorkspaceFile", foreign_keys=[workspace_file_id], back_populates="versions")


class WorkspaceFileMutation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable replay record for one logical file write.

    The payload contains identifiers and state only.  File bodies, signed URLs
    and credentials are deliberately excluded so retries can be answered
    without duplicating writes or persisting sensitive material.
    """

    __tablename__ = "file_mutations"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "actor_type", "actor_id", "idempotency_key",
            name="uq_file_mutation_actor_key",
        ),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    base_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_file_versions.id", ondelete="SET NULL"), nullable=True
    )
    result_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="SET NULL"), nullable=True
    )
    result_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_file_versions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class OfficeEditRoom(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One explicit human WebOffice editing session; credentials are never stored."""

    __tablename__ = "office_edit_rooms"
    __table_args__ = (
        UniqueConstraint(
            "workspace_file_id", "actor_type", "actor_id", "client_open_id",
            name="uq_office_edit_room_client_open",
        ),
    )

    workspace_file_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_file_version_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_file_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_content_ref: Mapped[str] = mapped_column(Text, nullable=False)
    source_storage_version_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_etag: Mapped[str | None] = mapped_column(String(256), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    client_open_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_file_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_file_versions.id", ondelete="SET NULL"), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class OfficeSaveEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable, idempotent platform receipt for one IMM SaveVersion event."""

    __tablename__ = "office_save_events"

    gateway_event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    workspace_file_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    office_edit_room_id: Mapped[str | None] = mapped_column(
        ForeignKey("office_edit_rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    repository_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    notified_storage_version_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    notified_etag: Mapped[str] = mapped_column(String(256), nullable=False)
    notified_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notified_content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    notified_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    notified_integrity_algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    notified_integrity_value: Mapped[str] = mapped_column(String(128), nullable=False)
    imm_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_time: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_storage_version_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    resolved_file_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_file_versions.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkspaceFileEventOutbox(TimestampMixin, Base):
    """Small fan-out event; never contains file bodies, tokens, or signed URLs."""

    __tablename__ = "workspace_file_event_outbox"
    __table_args__ = (Index("ix_workspace_file_event_outbox_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_file_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_file_versions.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)


class WorkspacePreviewJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Crash-recoverable, version-pinned Office fallback conversion."""

    __tablename__ = "workspace_preview_jobs"
    __table_args__ = (
        UniqueConstraint(
            "file_version_id", "conversion_type", name="uq_workspace_preview_version_type"
        ),
    )

    workspace_file_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_version_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_file_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversion_type: Mapped[str] = mapped_column(String(32), nullable=False, default="pdf")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    output_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkspaceUploadSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_upload_sessions"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL) <> (admin_id IS NOT NULL)",
            name="ck_workspace_upload_session_one_actor",
        ),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"), nullable=True, index=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    upload_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    upload_headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    workspace_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="SET NULL"), nullable=True
    )


class WorkspaceAuditEvent(TimestampMixin, Base):
    __tablename__ = "workspace_audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    workspace_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="SET NULL"), nullable=True, index=True
    )
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_file_versions.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class WorkspaceShareLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_share_links"

    workspace_file_id: Mapped[str] = mapped_column(ForeignKey("workspace_files.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("workspace_file_versions.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
