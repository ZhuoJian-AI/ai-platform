"""LLM Provider Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class LlmProviderCreate(BaseModel):
    name: str = Field(..., max_length=255)
    provider_type: str = Field(..., pattern=r"^(anthropic|openai|azure_openai|custom)$")
    base_url: str = Field(...)
    api_key: str = Field(...)  # 明文，加密存储
    priority: int = Field(default=0)
    weight: int = Field(default=1)
    timeout_seconds: int = Field(default=120)
    max_retries: int = Field(default=2)
    supported_models: list[str] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    # 层级范围：由创建端点决定（org/dept/team 端点分别校验），默认 organization
    scope_type: str = Field(default="organization", pattern=r"^(organization|department|team)$")


class LlmProviderUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    base_url: str | None = None
    api_key: str | None = None  # 仅更新时传入新 key
    is_active: bool | None = None
    priority: int | None = None
    weight: int | None = None
    timeout_seconds: int | None = None
    max_retries: int | None = None
    supported_models: list[str] | None = None
    config: dict | None = None
    # scope_type/department_id/team_id 不可改（绑定节点固定，同 API Key）


class LlmProviderRead(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    provider_type: str
    scope_type: str
    department_id: UUID | None = None
    team_id: UUID | None = None
    base_url: str
    api_key_encrypted: str  # 返回加密后的值（不可逆）
    api_key_version: int
    is_active: bool
    priority: int
    weight: int
    timeout_seconds: int
    max_retries: int
    supported_models: list[str]
    health_status: str
    config: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
