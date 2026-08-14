"""Skill Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas._base import MetaReadModel, OrmModel


class SkillCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    definition: dict = Field(default_factory=dict)
    bound_endpoint_ids: list[str] = Field(default_factory=list)
    param_mapping: dict = Field(default_factory=dict)
    scope_type: str = Field("organization", max_length=20)
    scope_id: str | None = None
    is_active: bool = True


class SkillUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    definition: dict | None = None
    bound_endpoint_ids: list[str] | None = None
    param_mapping: dict | None = None
    scope_type: str | None = Field(None, max_length=20)
    scope_id: str | None = None
    is_active: bool | None = None


class SkillRead(OrmModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str | None = None
    definition: dict
    bound_endpoint_ids: list[str]
    param_mapping: dict
    scope_type: str
    scope_id: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SkillTestRequest(BaseModel):
    params: dict = Field(default_factory=dict)


# ── 技能文件夹化（SkillFolder + SkillFile）──────────────────────────────

class SkillFolderCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    scope_type: str = Field("organization", max_length=20)
    scope_id: str | None = None


class SkillFolderUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    slug: str | None = Field(None, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillFolderRead(OrmModel):
    id: UUID
    organization_id: UUID
    scope_type: str
    scope_id: str | None = None
    name: str
    slug: str
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class SkillFileCreate(BaseModel):
    path: str = Field(..., max_length=1024)
    content: str = ""
    metadata: dict = Field(default_factory=dict)


class SkillFileUpdate(BaseModel):
    path: str | None = Field(None, max_length=1024)
    content: str | None = None
    metadata: dict | None = None


class SkillFileReadMeta(MetaReadModel):
    """文件列表/摘要：不含 content（避免大字段）。"""
    id: UUID
    skill_folder_id: UUID
    path: str
    size: int
    content_hash: str | None = None
    created_at: datetime
    updated_at: datetime


class SkillFileRead(SkillFileReadMeta):
    """单文件详情：含 content。"""
    content: str | None = None
