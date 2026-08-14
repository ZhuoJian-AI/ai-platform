"""Skill ORM model — agent-callable function bound to tool endpoints.

注：``Skill``（definition JSONB）为旧模型，保留 dormant；技能已文件夹化为
``SkillFolder`` + ``SkillFile``，agent ``_build_tools`` 改读 skill.md manifest。
"""

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text, UniqueConstraint
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

    files = relationship("SkillFile", back_populates="folder", lazy="selectin")


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

    folder = relationship("SkillFolder", back_populates="files")
