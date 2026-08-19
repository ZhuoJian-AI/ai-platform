"""Tool connector & endpoint Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas._base import OrmModel


class ToolConnectorCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    type: str = Field("other", max_length=20)  # erp/crm/hrm/other
    base_url: str
    auth_type: str = Field("none", max_length=20)  # none/basic/bearer/apikey/oauth
    # 明文鉴权配置（加密落库，读回时不返回）
    auth_config: dict = Field(default_factory=dict)
    spec: dict = Field(default_factory=dict)
    is_active: bool = True


class ToolConnectorUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    type: str | None = None
    base_url: str | None = None
    auth_type: str | None = None
    auth_config: dict | None = None
    spec: dict | None = None
    is_active: bool | None = None


class ToolConnectorRead(OrmModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str | None
    type: str
    base_url: str
    auth_type: str
    spec: dict
    is_active: bool
    health_status: str
    created_at: datetime
    updated_at: datetime


class ToolEndpointCreate(BaseModel):
    name: str = Field(..., max_length=255)
    method: str = Field("GET", max_length=10)
    path: str = Field(..., max_length=1024)
    description: str | None = None
    params_schema: dict = Field(default_factory=dict)
    response_schema: dict = Field(default_factory=dict)
    is_active: bool = True


class ToolEndpointUpdate(BaseModel):
    name: str | None = None
    method: str | None = None
    path: str | None = None
    description: str | None = None
    params_schema: dict | None = None
    response_schema: dict | None = None
    is_active: bool | None = None


class ToolEndpointRead(OrmModel):
    id: UUID
    connector_id: UUID
    name: str
    method: str
    path: str
    description: str | None = None
    params_schema: dict
    response_schema: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EndpointTestRequest(BaseModel):
    params: dict = Field(default_factory=dict)


class ConnectorSkillPublishRequest(BaseModel):
    """Publish selected connector endpoints as an organization-scoped Skill."""

    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    endpoint_ids: list[UUID] = Field(..., min_length=1)
