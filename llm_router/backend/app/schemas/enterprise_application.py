"""Schemas for tenant business applications and scoped permissions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from app.schemas._base import OrmModel

ApplicationPermission = Literal["view", "ai_query", "ai_create", "ai_update", "ai_delete", "export"]
ApplicationScope = Literal["organization", "department", "team", "user"]
ApplicationTarget = Literal["tool_endpoint", "data_interface", "skill_folder"]
ApplicationOperation = Literal["query", "create", "update", "delete", "export"]


class EnterpriseApplicationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    icon_url: AnyHttpUrl | None = None
    entry_url: AnyHttpUrl
    display_mode: Literal["embedded", "external"] = "embedded"
    sort_order: int = Field(0, ge=-10000, le=10000)
    is_active: bool = True
    assistant_enabled: bool = True
    assistant_prompt: str | None = None
    assistant_config: dict = Field(default_factory=dict)


class EnterpriseApplicationUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    icon_url: AnyHttpUrl | None = None
    entry_url: AnyHttpUrl | None = None
    display_mode: Literal["embedded", "external"] | None = None
    sort_order: int | None = Field(None, ge=-10000, le=10000)
    is_active: bool | None = None
    assistant_enabled: bool | None = None
    assistant_prompt: str | None = None
    assistant_config: dict | None = None


class EnterpriseApplicationGrantInput(BaseModel):
    scope_type: ApplicationScope
    scope_id: UUID | None = None
    permissions: list[ApplicationPermission] = Field(default_factory=list)

    @field_validator("permissions")
    @classmethod
    def unique_permissions(cls, value: list[ApplicationPermission]) -> list[ApplicationPermission]:
        return list(dict.fromkeys(value))


class EnterpriseApplicationGrantsReplace(BaseModel):
    grants: list[EnterpriseApplicationGrantInput] = Field(default_factory=list, max_length=2000)


class EnterpriseApplicationToolBindingInput(BaseModel):
    target_type: ApplicationTarget
    target_id: UUID
    operation: ApplicationOperation
    is_active: bool = True


class EnterpriseApplicationToolBindingsReplace(BaseModel):
    bindings: list[EnterpriseApplicationToolBindingInput] = Field(default_factory=list, max_length=1000)


class EnterpriseApplicationGrantRead(OrmModel):
    id: UUID
    application_id: UUID
    organization_id: UUID
    scope_type: str
    scope_id: str | None
    permissions: list[str]
    created_at: datetime
    updated_at: datetime


class EnterpriseApplicationToolBindingRead(OrmModel):
    id: UUID
    application_id: UUID
    organization_id: UUID
    target_type: str
    target_id: str
    operation: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EnterpriseApplicationRead(OrmModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str | None
    icon_url: str | None
    entry_url: str
    display_mode: str
    sort_order: int
    is_active: bool
    assistant_enabled: bool
    assistant_prompt: str | None
    assistant_config: dict
    health_status: str
    grants: list[EnterpriseApplicationGrantRead] = Field(default_factory=list)
    tool_bindings: list[EnterpriseApplicationToolBindingRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TerminalEnterpriseApplicationRead(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    icon_url: str | None
    display_mode: str
    sort_order: int
    assistant_enabled: bool
    permissions: list[str]


class EnterpriseApplicationLaunchRead(BaseModel):
    application_id: UUID
    url: str
    display_mode: str
    permissions: list[str]


class EnterpriseApplicationHealthRead(BaseModel):
    status: Literal["healthy", "unhealthy"]
    status_code: int | None = None
    detail: str | None = None
