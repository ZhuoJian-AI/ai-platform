"""RAG Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas._base import MetaReadModel, OrmModel


class RagCollectionCreate(BaseModel):
    name: str = Field(..., max_length=255)
    # slug 可省略：服务端在为空时自动生成唯一 slug（中文等名称无法 slugify）。
    slug: str | None = Field(None, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    embedding_model: str = "text-embedding-v4"
    embedding_dim: int | None = None
    chunk_size: int = 800
    chunk_overlap: int = 100
    metadata: dict = Field(default_factory=dict)
    scope_type: str = Field("organization", max_length=20)
    scope_id: str | None = None


class RagCollectionUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    metadata: dict | None = None
    scope_type: str | None = Field(None, max_length=20)
    scope_id: str | None = None


class RagCollectionRead(MetaReadModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str | None
    embedding_model: str
    embedding_dim: int | None
    chunk_size: int
    chunk_overlap: int
    scope_type: str
    scope_id: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class RagDocumentCreate(BaseModel):
    source: str = Field(..., max_length=512)
    title: str | None = Field(None, max_length=512)
    content: str
    metadata: dict = Field(default_factory=dict)
    folder_path: str = ""


class RagDocumentUpdate(BaseModel):
    """文档重命名 / 移动。"""
    source: str | None = Field(None, max_length=512)
    title: str | None = Field(None, max_length=512)
    folder_path: str | None = None


class RagDocumentRead(MetaReadModel):
    id: UUID
    collection_id: UUID
    source: str
    title: str | None = None
    content: str
    doc_hash: str | None = None
    folder_path: str = ""
    created_by: str | None = None
    # 解析入库状态：pending/parsing/chunking/embedding/ready/failed
    status: str = "ready"
    progress: int = 100
    parse_error: str | None = None
    created_at: datetime
    updated_at: datetime


class RagChunkRead(BaseModel):
    """文档分块（编辑视图）。"""
    id: UUID
    document_id: UUID | None
    content: str
    chunk_index: int = 0
    has_embedding: bool = False


class RagReingestRequest(BaseModel):
    """按分块重新入库：以编辑后的分块列表替换原分块并重新嵌入。

    ``chunks`` 为 ``None`` 时表示「从原文重切」——服务端用当前结构感知分块器对
    ``doc.content`` 重新切分（用于已入库文档在分块算法改进后无需重新上传即可刷新分块）。
    """
    chunks: list[str] | None = None
    source: str | None = Field(None, max_length=512)
    title: str | None = Field(None, max_length=512)
    folder_path: str | None = None


class RagFolderCreate(BaseModel):
    path: str = Field(..., max_length=1024)


class RagFolderUpdate(BaseModel):
    """文件夹重命名（移动）。"""
    path: str = Field(..., max_length=1024)


class RagFolderRead(OrmModel):
    id: UUID
    collection_id: UUID
    path: str
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class RagRetrieveRequest(BaseModel):
    query: str
    top_k: int = Field(5, ge=1, le=50)


class RagChunkHit(BaseModel):
    chunk_id: str
    document_id: str | None
    content: str
    score: float
    metadata: dict


class RagRetrieveResponse(BaseModel):
    query: str
    hits: list[RagChunkHit]


class RagDocumentStatusRead(BaseModel):
    """文档解析入库状态（前端轮询用）。"""

    id: UUID
    status: str
    progress: int
    parse_error: str | None = None
    chunk_count: int = 0


class RagIngestConfig(BaseModel):
    """组织级默认入库参数：新建知识库 / 文档入库表单的默认值。"""
    embedding_model: str = "text-embedding-v4"
    embedding_dim: int | None = None
    chunk_size: int = 800
    chunk_overlap: int = 100
    top_k: int = 5
