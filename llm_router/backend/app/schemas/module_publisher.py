"""Schemas for tenant-scoped module repository publishing."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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


class ModuleDeploymentProfileInput(BaseModel):
    runtime_key: str = Field("default", min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    server_uuid: str = Field(..., min_length=1, max_length=120)
    project_uuid: str = Field(..., min_length=1, max_length=120)
    environment_name: str = Field("production", min_length=1, max_length=120)
    environment_uuid: str | None = Field(None, max_length=120)
    destination_uuid: str | None = Field(None, max_length=120)
    github_app_uuid: str = Field(..., min_length=1, max_length=120)
    domain_suffix: str = Field(..., min_length=3, max_length=255)
    use_build_server: bool = False
    is_default: bool = False
    is_active: bool = True

    @field_validator("domain_suffix")
    @classmethod
    def normalize_domain_suffix(cls, value: str) -> str:
        cleaned = value.strip().lower().strip(".")
        labels = cleaned.split(".")
        if len(labels) < 2 or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in label)
            for label in labels
        ):
            raise ValueError("domain_suffix must be a valid DNS suffix without '*.'")
        return cleaned


class ModuleDeploymentProfileRead(ModuleDeploymentProfileInput):
    id: UUID
    organization_id: UUID
    deployer_configured: bool


class ModuleDeploymentRequest(BaseModel):
    module_slug: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    module_name: str = Field(..., min_length=1, max_length=255)
    repository_name: str = Field(..., min_length=3, max_length=255, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    source_commit: str = Field(..., min_length=7, max_length=40, pattern=r"^[0-9a-fA-F]+$")
    runtime_key: str | None = Field(None, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ModuleDeploymentRead(BaseModel):
    id: UUID
    module_slug: str
    module_name: str
    repository_name: str
    entry_url: str
    coolify_application_uuid: str
    deployment_uuid: str | None
    requested_commit: str
    last_success_commit: str | None
    status: Literal[
        "queued", "deploying", "verifying", "healthy", "failed",
        "rollback_queued", "rolling_back", "rolled_back", "rollback_failed",
    ]
    failure_stage: str | None = None
    detail: str | None = None
    log_excerpt: str | None = None
    application_id: UUID | None = None
    retryable: bool = False
    next_action: str | None = None
