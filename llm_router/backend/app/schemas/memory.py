"""Memory Pydantic schemas — hierarchical long-term memory CRUD."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas._base import MetaReadModel


class MemoryCreate(BaseModel):
    scope_type: str = Field("organization", max_length=20)  # organization/department/team/user
    scope_id: str | None = None  # org 级 None；其余为 dept/team/user id
    category: str = Field("general", max_length=100)
    content: str
    source: str = Field("manual", max_length=20)
    metadata: dict = Field(default_factory=dict)


class MemoryUpdate(BaseModel):
    scope_type: str | None = Field(None, max_length=20)
    scope_id: str | None = None
    category: str | None = Field(None, max_length=100)
    content: str | None = None
    metadata: dict | None = None


class MemoryRead(MetaReadModel):
    id: UUID
    organization_id: UUID
    scope_type: str
    scope_id: str | None = None
    category: str
    content: str
    source: str
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
