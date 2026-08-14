"""本体 Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas._base import MetaReadModel, OrmModel


class OntologyCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    entities: list = Field(default_factory=list)
    relations: list = Field(default_factory=list)
    scope_type: str = Field("organization", max_length=20)
    scope_id: str | None = None
    is_active: bool = True


class OntologyUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    entities: list | None = None
    relations: list | None = None
    scope_type: str | None = Field(None, max_length=20)
    scope_id: str | None = None
    is_active: bool | None = None


class OntologyRead(OrmModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str | None = None
    entities: list
    relations: list
    scope_type: str
    scope_id: str | None = None
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OntologyValidateResponse(BaseModel):
    ok: bool
    errors: list[str]


# ── 本体文件化（Markdown 文件 + 文件夹）──────────────────────────────────

class OntologyScopeQuery(BaseModel):
    """作用域查询参数：organization 级 scope_id 为 None。"""
    scope_type: str = Field("organization", max_length=20)
    scope_id: str | None = None


class OntologyFolderCreate(BaseModel):
    path: str = Field(..., max_length=1024)
    scope_type: str = Field("organization", max_length=20)
    scope_id: str | None = None


class OntologyFolderRename(BaseModel):
    path: str = Field(..., max_length=1024)


class OntologyFolderRead(OrmModel):
    id: UUID
    organization_id: UUID
    scope_type: str
    scope_id: str | None = None
    path: str
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class OntologyFileCreate(BaseModel):
    path: str = Field(..., max_length=1024)
    content: str = ""
    metadata: dict = Field(default_factory=dict)
    scope_type: str = Field("organization", max_length=20)
    scope_id: str | None = None


class OntologyFileUpdate(BaseModel):
    path: str | None = Field(None, max_length=1024)
    content: str | None = None
    metadata: dict | None = None


class OntologyFileRead(MetaReadModel):
    id: UUID
    organization_id: UUID
    scope_type: str
    scope_id: str | None = None
    path: str
    size: int
    content_hash: str | None = None
    content: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
