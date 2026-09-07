"""Memory Pydantic schemas — hierarchical long-term memory CRUD."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas._base import MetaReadModel


class MemoryCreate(BaseModel):
    scope_type: Literal["organization", "department", "user", "role"] = "organization"
    scope_id: str | None = None  # org 级 None；其余为 department/user/role id
    category: str = Field("general", max_length=100)
    content: str
    source: str = Field("manual", max_length=20)
    metadata: dict = Field(default_factory=dict)


class MemoryUpdate(BaseModel):
    scope_type: Literal["organization", "department", "user", "role"] | None = None
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
