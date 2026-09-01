"""Organization Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class OrganizationCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    settings: dict = Field(default_factory=dict)
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    budget_cap_usd: Decimal | None = None
    budget_cap_tokens: int | None = None


class OrganizationUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    slug: str | None = Field(None, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    settings: dict | None = None
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    budget_cap_usd: Decimal | None = None
    budget_cap_tokens: int | None = None


class OrganizationRead(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    settings: dict
    rate_limit_rpm: int | None
    rate_limit_tpm: int | None
    budget_cap_usd: Decimal | None
    budget_cap_tokens: int | None
    is_default: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DepartmentCreate(BaseModel):
    parent_id: UUID | None = None
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    settings: dict = Field(default_factory=dict)
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    budget_cap_usd: Decimal | None = None
    budget_cap_tokens: int | None = None


class DepartmentUpdate(BaseModel):
    parent_id: UUID | None = None
    name: str | None = Field(None, max_length=255)
    slug: str | None = Field(None, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    settings: dict | None = None
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    budget_cap_usd: Decimal | None = None
    budget_cap_tokens: int | None = None


class DepartmentRead(BaseModel):
    id: UUID
    organization_id: UUID
    parent_id: UUID | None = None
    name: str
    slug: str
    description: str | None
    settings: dict
    rate_limit_rpm: int | None
    rate_limit_tpm: int | None
    budget_cap_usd: Decimal | None
    budget_cap_tokens: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TeamCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    settings: dict = Field(default_factory=dict)
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    budget_cap_usd: Decimal | None = None
    budget_cap_tokens: int | None = None


class TeamUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    slug: str | None = Field(None, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    settings: dict | None = None
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    budget_cap_usd: Decimal | None = None
    budget_cap_tokens: int | None = None


class TeamRead(BaseModel):
    id: UUID
    department_id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str | None
    settings: dict
    rate_limit_rpm: int | None
    rate_limit_tpm: int | None
    budget_cap_usd: Decimal | None
    budget_cap_tokens: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
