"""Schemas for tenant business applications and scoped permissions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from app.schemas._base import OrmModel

ApplicationPermission = Literal[
    "view", "ai_query", "ai_create", "ai_update", "ai_delete", "ai_approve", "export"
]
ApplicationScope = Literal["organization", "department", "team", "user"]
ApplicationTarget = Literal["tool_endpoint", "data_interface", "skill_folder"]
ApplicationOperation = Literal["query", "create", "update", "delete", "export", "approve"]


class EnterpriseApplicationPageAccess(BaseModel):
    permissions: list[ApplicationPermission] = Field(default_factory=list)
    action_keys: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("permissions")
    @classmethod
    def unique_permissions(cls, value: list[ApplicationPermission]) -> list[ApplicationPermission]:
        return list(dict.fromkeys(value))

    @field_validator("action_keys")
    @classmethod
    def valid_action_keys(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if any(len(item) > 160 for item in cleaned):
            raise ValueError("action key must be 160 characters or fewer")
        return list(dict.fromkeys(cleaned))


class EnterpriseApplicationModuleAccess(BaseModel):
    role: str = Field("member", min_length=1, max_length=80)
    permissions: list[ApplicationPermission] = Field(default_factory=list)
    action_keys: list[str] = Field(default_factory=list, max_length=500)
    page_access: dict[str, EnterpriseApplicationPageAccess] = Field(default_factory=dict)

    @field_validator("permissions")
    @classmethod
    def unique_permissions(cls, value: list[ApplicationPermission]) -> list[ApplicationPermission]:
        return list(dict.fromkeys(value))

    @field_validator("action_keys")
    @classmethod
    def valid_action_keys(cls, value: list[str]) -> list[str]:
        return EnterpriseApplicationPageAccess.valid_action_keys(value)

    @field_validator("page_access")
    @classmethod
    def valid_page_access(
        cls, value: dict[str, EnterpriseApplicationPageAccess]
    ) -> dict[str, EnterpriseApplicationPageAccess]:
        if len(value) > 500:
            raise ValueError("page access must contain at most 500 pages")
        cleaned: dict[str, EnterpriseApplicationPageAccess] = {}
        for key, access in value.items():
            page_key = key.strip()
            if not page_key or len(page_key) > 160:
                raise ValueError("page key must be 1-160 characters")
            cleaned[page_key] = access
        return cleaned


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
    module_keys: list[str] = Field(default_factory=list, max_length=200)
    module_access: dict[str, EnterpriseApplicationModuleAccess] = Field(default_factory=dict)

    @field_validator("permissions")
    @classmethod
    def unique_permissions(cls, value: list[ApplicationPermission]) -> list[ApplicationPermission]:
        return list(dict.fromkeys(value))

    @field_validator("module_keys")
    @classmethod
    def valid_module_keys(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if any(len(item) > 120 for item in cleaned):
            raise ValueError("module key must be 120 characters or fewer")
        return list(dict.fromkeys(cleaned))

    @field_validator("module_access")
    @classmethod
    def valid_module_access(
        cls, value: dict[str, EnterpriseApplicationModuleAccess]
    ) -> dict[str, EnterpriseApplicationModuleAccess]:
        if len(value) > 200:
            raise ValueError("module access must contain at most 200 modules")
        cleaned: dict[str, EnterpriseApplicationModuleAccess] = {}
        for key, access in value.items():
            module_key = key.strip()
            if not module_key or len(module_key) > 120:
                raise ValueError("module key must be 1-120 characters")
            cleaned[module_key] = access
        return cleaned


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
    module_keys: list[str]
    module_access: dict[str, EnterpriseApplicationModuleAccess] = Field(default_factory=dict)
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
    module_keys: list[str] = Field(default_factory=list)


class EnterpriseApplicationLaunchModuleRead(BaseModel):
    module_key: str
    name: str


class EnterpriseApplicationLaunchRead(BaseModel):
    application_id: UUID
    url: str
    display_mode: str
    permissions: list[str]
    module_keys: list[str] = Field(default_factory=list)
    module_key: str | None = None
    modules: list[EnterpriseApplicationLaunchModuleRead] = Field(default_factory=list)


class EnterpriseApplicationIntegrationInput(BaseModel):
    manifest_url: AnyHttpUrl
    auth_token: str | None = Field(None, min_length=16, max_length=4096)
    clear_auth_token: bool = False
    sync_enabled: bool = True


class EnterpriseApplicationIntegrationRead(BaseModel):
    application_id: UUID
    manifest_url: str
    events_url: str | None
    protocol_version: int
    manifest: dict = Field(default_factory=dict)
    modules: list[dict] = Field(default_factory=list)
    cursor_sequence: int
    sync_enabled: bool
    sync_status: str
    token_configured: bool
    last_manifest_sync_at: datetime | None
    last_event_sync_at: datetime | None
    last_error: str | None


class EnterpriseApplicationActionRead(OrmModel):
    id: UUID
    application_id: UUID
    module_key: str
    action_key: str
    name: str
    description: str | None
    operation: ApplicationOperation
    ai_enabled: bool
    requires_confirmation: bool
    input_schema: dict = Field(default_factory=dict)
    result_schema: dict = Field(default_factory=dict)
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EnterpriseApplicationDiscoveryInput(BaseModel):
    base_url: AnyHttpUrl
    auth_token: str | None = Field(None, min_length=16, max_length=4096)


class EnterpriseApplicationDiscoveryRead(BaseModel):
    entry_url: str
    manifest_url: str
    health_url: str
    health_status: Literal["healthy", "unhealthy"]
    protocol_version: int
    suggested_name: str
    suggested_slug: str
    manifest: dict
    modules: list[dict] = Field(default_factory=list)


class EnterpriseApplicationActionInvoke(BaseModel):
    module_key: str = Field(..., min_length=1, max_length=120)
    page_key: str | None = Field(None, min_length=1, max_length=160)
    operation: ApplicationOperation | None = None
    expected_version: str | int | None = None
    params: dict = Field(default_factory=dict)
    request_id: str | None = Field(None, min_length=1, max_length=200)


class EnterpriseApplicationActionResultRead(BaseModel):
    request_id: str
    status: Literal["pending", "executing", "completed", "rejected", "expired", "failed"]
    confirmation_id: UUID | None = None
    result: dict = Field(default_factory=dict)
    error: str | None = None
    provenance: dict = Field(default_factory=dict)


class EnterpriseApplicationActionRequestRead(OrmModel):
    id: UUID
    application_id: UUID
    action_id: UUID
    request_id: str
    module_key: str
    page_key: str | None = None
    status: str
    params: dict = Field(default_factory=dict)
    expires_at: datetime
    resolved_at: datetime | None
    result: dict = Field(default_factory=dict)
    error: str | None
    action: EnterpriseApplicationActionRead
    created_at: datetime
    updated_at: datetime


class EnterpriseApplicationSyncRead(BaseModel):
    status: Literal["healthy", "error"]
    manifest_updated: bool = False
    received_events: int = 0
    created_work_items: int = 0
    delivered_events: int = 0
    cursor_sequence: int = 0
    detail: str | None = None


class EnterpriseApplicationEventRouteInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    event_type: str = Field(..., min_length=1, max_length=160)
    module_key: str | None = Field(None, max_length=120)
    target_scope_type: ApplicationScope
    target_scope_id: UUID | None = None
    target_application_id: UUID | None = None
    target_module_key: str | None = Field(None, max_length=120)
    is_active: bool = True


class EnterpriseApplicationEventRoutesReplace(BaseModel):
    routes: list[EnterpriseApplicationEventRouteInput] = Field(default_factory=list, max_length=500)


class EnterpriseApplicationEventRouteRead(OrmModel):
    id: UUID
    application_id: UUID
    name: str
    event_type: str
    module_key: str | None
    target_scope_type: str
    target_scope_id: str | None
    target_application_id: UUID | None
    target_module_key: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CrossDepartmentWorkItemRead(OrmModel):
    id: UUID
    source_application_id: UUID
    source_event_id: str
    title: str
    status: str
    target_scope_type: str
    target_scope_id: str | None
    target_module_key: str | None
    source_context: dict
    created_at: datetime
    updated_at: datetime


class CrossDepartmentWorkItemUpdate(BaseModel):
    status: Literal["open", "done"]


class EnterpriseApplicationHealthRead(BaseModel):
    status: Literal["healthy", "unhealthy"]
    status_code: int | None = None
    detail: str | None = None


class EnterpriseApplicationCapabilityRead(BaseModel):
    binding_id: UUID
    target_type: ApplicationTarget
    target_id: UUID
    operation: ApplicationOperation
    name: str
    source_name: str
    description: str | None = None
    method: str | None = None
    path: str | None = None
    binding_active: bool
    target_active: bool
    health_status: str | None = None


class EnterpriseApplicationRecentCallRead(BaseModel):
    id: int
    capability_name: str
    method: str | None = None
    path: str | None = None
    status: Literal["success", "failed"]
    status_code: int | None = None
    latency_ms: int | None = None
    error: str | None = None
    created_at: datetime


class EnterpriseApplicationOverviewRead(BaseModel):
    application_id: UUID
    operation_counts: dict[str, int]
    active_capability_count: int
    direct_capability_count: int
    skill_binding_count: int
    capabilities: list[EnterpriseApplicationCapabilityRead] = Field(default_factory=list)
    recent_calls: list[EnterpriseApplicationRecentCallRead] = Field(default_factory=list)
