"""本体 ORM model — JSONB entity/relation graph for an organization.

注：``Ontology``（JSONB 图结构）为旧模型，保留 dormant；本体已文件化为
``OntologyFolder`` / ``OntologyFile``（Markdown 文件 + 文件夹），agent 运行时改读后者。
"""

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Ontology(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """组织本体：实体与关系的 JSONB 图结构，供智能体推理/工具编排引用。

    entities: [{"id","name","attributes":[...]}]
    relations: [{"src","dst","type","props":{...}}]
    """

    __tablename__ = "ontologies"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_ontology_org_slug"),)

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    entities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    relations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # 作用范围：organization/department/team/user
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="organization")
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class OntologyFolder(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """本体文件夹：path 为相对作用域根的 POSIX 路径，嵌套靠路径段表达。

    作用域由 (organization_id, scope_type, scope_id) 直接表达（organization 级 scope_id 为 None）。
    """

    __tablename__ = "ontology_folders"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope_type", "scope_id", "path", name="uq_ontology_folder_path"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="organization")
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    # 创建者（终端用户 id）；admin / 历史数据为 None，终端用户仅可删改自己创建的
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class OntologyFile(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """本体 Markdown 文件：content 为 Markdown 文本，agent 运行时直接注入 prompt。

    path 为相对作用域根的 POSIX 路径（含文件夹段）；作用域同 ``OntologyFolder``。
    """

    __tablename__ = "ontology_files"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope_type", "scope_id", "path", name="uq_ontology_file_path"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="organization")
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    # 创建者（终端用户 id）；admin / 历史数据为 None，终端用户仅可删改自己创建的
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
