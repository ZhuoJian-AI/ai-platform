"""Workspace ORM models — governed tenant file storage and immutable versions."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """智能体工作空间：限定 agent 文件读写的根作用域。"""

    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_workspace_org_slug"),)

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

    files = relationship("WorkspaceFile", back_populates="workspace", lazy="selectin")
    folders = relationship("WorkspaceFolder", back_populates="workspace", lazy="selectin")


class WorkspaceFile(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """工作空间内的文件元数据。content_ref 指向存储后端中的实际内容定位。"""

    __tablename__ = "workspace_files"
    __table_args__ = (UniqueConstraint("workspace_id", "path", name="uq_wsfile_path"),)

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

    workspace = relationship("Workspace", back_populates="folders")


class WorkspaceFileVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable snapshot pinned by tasks, shares and audit records."""

    __tablename__ = "workspace_file_versions"
    __table_args__ = (UniqueConstraint("workspace_file_id", "version_no", name="uq_wsfile_version"),)

    workspace_file_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
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
