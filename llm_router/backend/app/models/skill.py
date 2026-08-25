"""Skill ORM model — agent-callable function bound to tool endpoints.

注：``Skill``（definition JSONB）为旧模型，保留 dormant；技能已文件夹化为
``SkillFolder`` + ``SkillFile``，agent ``_build_tools`` 改读 skill.md manifest。
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Skill(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """技能：OpenAI function-tool schema 定义 + 绑定的 ToolEndpoint 列表。

    agent 的 execute_tools 节点按 LLM 返回的 tool_call.name 匹配 Skill，
    再经 Skill.bound_endpoint_ids → ToolEndpoint → executor 调用外部 API。
    """

    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_skill_org_slug"),)

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # OpenAI function-tool definition: {"name","description","parameters":<json-schema>}
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 绑定的 ToolEndpoint.id 列表（按顺序尝试）
    bound_endpoint_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # 参数映射：endpoint 入参如何从 LLM arguments 提取（可选）
    param_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # 作用范围：organization（全组织）/ department / team / user；scope_id 为对应 dept/team/user id（org 级为 None）
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="organization")
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SkillFolder(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """技能文件夹：一行 = 一个技能，按 (organization_id, scope_type, scope_id) 节点作用域化。

    文件夹内 ``skill.md`` 定义 function-tool（manifest），``skill_files`` 存放文件夹内文件。
    """

    __tablename__ = "skill_folders"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope_type", "scope_id", "slug", name="uq_skill_folder_scope_slug"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="organization")
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    # 创建者（终端用户 id）：admin / 历史数据为 None；终端「仅可操作自己创建的技能」据此判定
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    active_version_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "skill_versions.id", name="fk_skill_folder_active_version",
            ondelete="SET NULL", use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    files = relationship("SkillFile", back_populates="folder", lazy="selectin")

    @property
    def is_installed(self) -> bool:
        """Active package or a compatible legacy skill.md is available."""
        return self.is_active and (bool(self.active_version_id) or any(
            item.deleted_at is None and item.path.lower() == "skill.md" for item in (self.files or [])
        ))


class SkillFile(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """技能文件夹内文件：content 为文本（skill.md 的 manifest + 文档，或其他资源文件）。"""

    __tablename__ = "skill_files"
    __table_args__ = (UniqueConstraint("skill_folder_id", "path", name="uq_skill_file_path"),)

    skill_folder_id: Mapped[str] = mapped_column(
        ForeignKey("skill_folders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    folder = relationship("SkillFolder", back_populates="files")


class SkillVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable snapshot of an imported Skill package."""

    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_folder_id", "version_no", name="uq_skill_version_number"),
        UniqueConstraint("skill_folder_id", "package_hash", name="uq_skill_version_hash"),
    )

    skill_folder_id: Mapped[str] = mapped_column(
        ForeignKey("skill_folders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    package_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Legacy inline package. New packages live in private OSS and keep only an
    # opaque project-scoped reference here; the column remains during the
    # rolling migration so old versions continue to execute.
    archive: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    archive_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    archive_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_status: Mapped[str] = mapped_column(String(20), nullable=False, default="inline", index=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    archive_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runtime: Mapped[str] = mapped_column(String(20), nullable=False, default="prompt")
    entrypoint: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_executable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    install_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    install_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScopeManagerAssignment(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Department/team management grant; deliberately separate from User.role."""

    __tablename__ = "scope_manager_assignments"
    __table_args__ = (
        CheckConstraint("scope_type IN ('department','team')", name="ck_scope_manager_type"),
        UniqueConstraint("user_id", "scope_type", "scope_id", name="uq_scope_manager_assignment"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL"), nullable=True
    )


class SkillExecution(TimestampMixin, Base):
    """Append-only audit trail for executable Skill runs."""

    __tablename__ = "skill_executions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    skill_folder_id: Mapped[str] = mapped_column(
        ForeignKey("skill_folders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    skill_version_id: Mapped[str] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    input_file_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    output_file_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
