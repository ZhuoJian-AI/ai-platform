"""Schemas for direct-ECS runtime registration and module publishing."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


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


class EcsModuleReleaseIntentInput(BaseModel):
    target_commit: str = Field(..., min_length=40, max_length=40, pattern=r"^[0-9a-fA-F]{40}$")


class EcsModuleCredentialsInput(BaseModel):
    """Four non-interchangeable credentials generated once by the ECS Runtime."""

    manifest_access_token: str = Field(..., min_length=40, max_length=512)
    sso_exchange_token: str = Field(..., min_length=40, max_length=512)
    action_signing_secret: str = Field(..., min_length=40, max_length=512)
    event_signing_secret: str = Field(..., min_length=40, max_length=512)

    @model_validator(mode="after")
    def validate_types_and_separation(self):
        expected = {
            "manifest_access_token": "zjmf_",
            "sso_exchange_token": "zjss_",
            "action_signing_secret": "zjac_",
            "event_signing_secret": "zjev_",
        }
        values: list[str] = []
        for field_name, prefix in expected.items():
            value = getattr(self, field_name)
            if not value.startswith(prefix):
                raise ValueError(f"{field_name} must use the {prefix} credential type")
            values.append(value)
        if len(values) != len(set(values)):
            raise ValueError("Subsystem credentials must be distinct for every purpose")
        return self


class EcsModulePublishInput(BaseModel):
    application_slug: str = Field(
        ..., min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    application_name: str = Field(..., min_length=1, max_length=255)
    base_url: str = Field(..., min_length=10, max_length=2048)
    # Compatibility input for v2.4 Runtime clients.  It authenticates manifest
    # and event-feed pulls only and can never sign SSO, Action or Event tokens.
    integration_secret: str | None = Field(None, min_length=32, max_length=512)
    credentials: EcsModuleCredentialsInput | None = None
    source_commit: str = Field(..., min_length=40, max_length=40, pattern=r"^[0-9a-fA-F]{40}$")
    image_ref: str = Field(..., min_length=1, max_length=2048)
    deployed_at: datetime | None = None
    release_metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_registration_credentials(self):
        if self.integration_secret and self.credentials:
            raise ValueError("Use credentials instead of the legacy integration_secret")
        if not self.integration_secret and self.credentials is None:
            raise ValueError("Subsystem registration credentials are required")
        return self


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
    status: Literal["verifying", "pending_review", "healthy", "failed"]
    release_metadata: dict
    last_error: str | None
    deployed_at: datetime | None
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
