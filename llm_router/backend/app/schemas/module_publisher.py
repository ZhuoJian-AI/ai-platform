"""Schemas for tenant-scoped module repository publishing."""

from datetime import datetime

from pydantic import BaseModel, Field


class ModuleRepositoryProvisionInput(BaseModel):
    module_slug: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    module_name: str = Field(..., min_length=1, max_length=255)


class ModuleRepositoryProvisionRead(BaseModel):
    owner: str
    repository_name: str
    clone_url: str
    access_token: str
    expires_at: datetime
    created: bool
