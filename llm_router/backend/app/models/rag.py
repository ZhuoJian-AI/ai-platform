"""RAG ORM models — collection / document / chunk with pgvector embedding."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class RagCollection(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """RAG 知识集合：绑定一个 embedding 模型与分块策略。"""

    __tablename__ = "rag_collections"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_ragcoll_org_slug"),)

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # embedding 模型名（经模型路由器解析，或直连 provider embeddings 端点）
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False, default="text-embedding-v4")
    # 维度信息（仅元数据；embedding 列为维度无关 Vector，支持不同维度的 collection 共存）
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=800)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # 作用范围：organization/department/team/user
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="organization")
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # 创建者（终端用户 id）；admin 创建或历史数据为 None。终端据此判定「仅可操作自己创建的」。
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    documents = relationship("RagDocument", back_populates="collection", lazy="selectin")
    folders = relationship("RagFolder", back_populates="collection", lazy="selectin")


class RagDocument(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """RAG 源文档（完整内容 + 元数据），分块后产生 RagChunk。"""

    __tablename__ = "rag_documents"

    collection_id: Mapped[str] = mapped_column(
        ForeignKey("rag_collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(512), nullable=False)  # 文件名 / URL / 标识
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    doc_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    # 所属文件夹（相对集合根的 POSIX 路径，"" 表示根目录）
    folder_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="", server_default="")
    # 创建者（终端用户 id）；admin / 历史数据为 None
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # 解析入库状态：pending/parsing/chunking/embedding/ready/failed
    # 上传文件入库走后台异步分块嵌入，状态/进度供前端轮询；同步入库（文本粘贴、
    # 终端 JSON 入库）直接 ready/100。历史数据 server_default=ready/100。
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready", server_default="ready")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    collection = relationship("RagCollection", back_populates="documents")
    chunks = relationship("RagChunk", back_populates="document", lazy="noload")


class RagFolder(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """RAG 集合内的文件夹元数据。path 为相对集合根的 POSIX 路径，
    嵌套靠路径段表达（与文档一致）；可独立存在以支持空文件夹。"""

    __tablename__ = "rag_folders"
    __table_args__ = (UniqueConstraint("collection_id", "path", name="uq_ragfolder_path"),)

    collection_id: Mapped[str] = mapped_column(
        ForeignKey("rag_collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)  # 相对集合根的 POSIX 路径
    # 创建者（终端用户 id）；admin / 历史数据为 None
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    collection = relationship("RagCollection", back_populates="folders")


class RagChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """RAG 文本块 + 向量。embedding 为维度无关 Vector，按 collection_id 检索。"""

    __tablename__ = "rag_chunks"

    collection_id: Mapped[str] = mapped_column(
        ForeignKey("rag_collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 维度无关向量列：不同 collection 可用不同 embedding 维度；查询时使用同维 query 向量。
    embedding: Mapped[list | None] = mapped_column(Vector(None), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    document = relationship("RagDocument", back_populates="chunks")
