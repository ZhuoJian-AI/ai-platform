"""API Key Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    key_name: str = Field(..., max_length=255)
    scope_type: str = Field(..., pattern=r"^(organization|department|team)$")
    organization_id: UUID | None = None  # 用于 dept/team 级别的 key 创建
    allowed_models: list[str] = Field(default_factory=list)  # 空=全部
    rate_limit_rpm: int | None = Field(None, ge=0)
    rate_limit_tpm: int | None = Field(None, ge=0)
    # USD caps are retained only for legacy reporting until versioned provider
    # prices exist; new keys must use token and/or credit budgets.
    budget_cap_usd: None = None
    budget_cap_tokens: int | None = Field(None, ge=0)
    budget_cap_credits: int | None = Field(None, ge=0)
    expires_at: datetime | None = None


class ApiKeyUpdate(BaseModel):
    key_name: str | None = Field(None, max_length=255)
    allowed_models: list[str] | None = None
    rate_limit_rpm: int | None = Field(None, ge=0)
    rate_limit_tpm: int | None = Field(None, ge=0)
    budget_cap_usd: None = None
    budget_cap_tokens: int | None = Field(None, ge=0)
    budget_cap_credits: int | None = Field(None, ge=0)
    is_active: bool | None = None
    expires_at: datetime | None = None


class _ApiKeyReadInner(BaseModel):
    """内部 schema：不含 key_plain，仅用于从 ORM 对象序列化。"""
    id: UUID
    key_prefix: str
    key_name: str
    scope_type: str
    organization_id: UUID
    department_id: UUID | None
    team_id: UUID | None
    allowed_models: list[str]
    rate_limit_rpm: int | None
    rate_limit_tpm: int | None
    budget_cap_usd: Decimal | None
    budget_cap_tokens: int | None
    budget_cap_credits: int | None
    is_active: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyRead(BaseModel):
    """API Key metadata.  Bearer plaintext is never returned after creation."""
    id: UUID
    key_prefix: str
    key_name: str
    scope_type: str
    organization_id: UUID
    department_id: UUID | None
    team_id: UUID | None
    allowed_models: list[str]
    rate_limit_rpm: int | None
    rate_limit_tpm: int | None
    budget_cap_usd: Decimal | None
    budget_cap_tokens: int | None
    budget_cap_credits: int | None
    is_active: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None
    model_config = {"from_attributes": True}


class ApiKeyCreateResponse(ApiKeyRead):
    """Creation-only response containing the one-time bearer plaintext."""
    key: str
