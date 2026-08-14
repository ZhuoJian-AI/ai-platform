"""JudgeTemplate Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class JudgeTemplateCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    criteria: list = Field(default_factory=list)
    scoring_rubric: str | None = None
    is_active: bool = True


class JudgeTemplateUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    criteria: list | None = None
    scoring_rubric: str | None = None
    is_active: bool | None = None


class JudgeTemplateRead(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str | None
    criteria: list
    scoring_rubric: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
