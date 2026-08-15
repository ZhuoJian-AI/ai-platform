"""Workspace ORM models — agent file read/write sandbox per organization."""

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text, UniqueConstraint
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
    # local 后端：相对 workspace root 的文件路径；小文本亦可内联存 content 字段。
    content_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 内联文本内容（小文件直接落库，便于在线编辑与 agent 即时读取）。
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Office/PDF 等二进制文件的结构化文本解析结果；原文件仍保存在 content(base64)。
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unparsed")
    parse_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    workspace = relationship("Workspace", back_populates="files")


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
