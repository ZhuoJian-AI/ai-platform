"""Schemas for direct-ECS runtime registration and module publishing."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _dns_suffix(value: str) -> str:
    cleaned = value.strip().lower().removeprefix("*.").strip(".")
    labels = cleaned.split(".")
    if len(labels) < 2 or any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in label)
        for label in labels
    ):
        raise ValueError("domain_suffix must be a valid DNS suffix")
    return cleaned


class EcsRuntimeCreate(BaseModel):
    runtime_key: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    enterprise_key: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    environment: Literal["development", "staging", "production"] = "staging"
    domain_suffix: str = Field(..., min_length=3, max_length=255)
    public_address: str | None = Field(None, max_length=255)

    @field_validator("domain_suffix")
    @classmethod
    def normalize_domain_suffix(cls, value: str) -> str:
        return _dns_suffix(value)


class EcsRuntimeRead(BaseModel):
    id: UUID
    organization_id: UUID
    runtime_key: str
    enterprise_key: str
    environment: str
    domain_suffix: str
    public_address: str | None
    credential_prefix: str
    is_active: bool
    credential_rotated_at: datetime
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EcsRuntimeCredentialRead(BaseModel):
    runtime: EcsRuntimeRead
    credential: str
    runtime_profile: dict


class EcsRuntimeStateInput(BaseModel):
    is_active: bool


class EcsModulePublishInput(BaseModel):
    application_slug: str = Field(
        ..., min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    application_name: str = Field(..., min_length=1, max_length=255)
    base_url: str = Field(..., min_length=10, max_length=2048)
    integration_secret: str = Field(..., min_length=32, max_length=512)
    source_commit: str = Field(..., min_length=7, max_length=64, pattern=r"^[0-9a-fA-F]+$")
    image_ref: str | None = Field(None, max_length=2048)
    deployed_at: datetime | None = None
    release_metadata: dict = Field(default_factory=dict)


class EcsModuleReleaseRead(BaseModel):
    id: UUID
    runtime_id: UUID
    organization_id: UUID
    application_id: UUID | None
    application_slug: str
    application_name: str
    base_url: str
    requested_commit: str
    last_success_commit: str | None
    image_ref: str | None
    contract_revision: str | None
    manifest_digest: str | None
    status: Literal["verifying", "healthy", "failed"]
    release_metadata: dict
    last_error: str | None
    deployed_at: datetime | None
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
