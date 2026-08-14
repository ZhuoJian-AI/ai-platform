"""Routing Policy Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RoutingPolicyCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = None
    model_pattern: str = Field(..., max_length=255)  # glob 模式
    strategy: str = Field(..., pattern=r"^(priority|round_robin|weighted|least_latency|failover)$")
    provider_ids: list[UUID] = Field(...)
    is_default: bool = False


class RoutingPolicyUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    model_pattern: str | None = None
    strategy: str | None = None
    provider_ids: list[UUID] | None = None
    is_default: bool | None = None


class RoutingPolicyRead(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    model_pattern: str
    strategy: str
    provider_ids: list
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
