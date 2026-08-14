"""Workspace Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas._base import MetaReadModel, OrmModel


class WorkspaceCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    storage_backend: str = Field("local", max_length=20)
    root_path: str = Field("", max_length=512)
    config: dict = Field(default_factory=dict)
    scope_type: str = Field("organization", max_length=20)
    scope_id: str | None = None
    is_active: bool = True


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    config: dict | None = None
    scope_type: str | None = Field(None, max_length=20)
    scope_id: str | None = None
    is_active: bool | None = None


class WorkspaceRead(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str | None
    storage_backend: str
    root_path: str
    config: dict
    scope_type: str
    scope_id: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceFileCreate(BaseModel):
    path: str = Field(..., max_length=1024)
    content: str = ""
    metadata: dict = Field(default_factory=dict)


class WorkspaceFileUpdate(BaseModel):
    content: str | None = None
    metadata: dict | None = None


class WorkspaceFileRead(MetaReadModel):
    id: UUID
    workspace_id: UUID
    path: str
    size: int
    content_hash: str | None = None
    content: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkspaceFolderCreate(BaseModel):
    path: str = Field(..., max_length=1024)


class WorkspaceFolderRead(OrmModel):
    id: UUID
    workspace_id: UUID
    path: str
    created_at: datetime
    updated_at: datetime
