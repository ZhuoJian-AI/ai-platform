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
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    budget_cap_usd: Decimal | None = None
    budget_cap_tokens: int | None = None
    expires_at: datetime | None = None


class ApiKeyUpdate(BaseModel):
    key_name: str | None = Field(None, max_length=255)
    allowed_models: list[str] | None = None
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    budget_cap_usd: Decimal | None = None
    budget_cap_tokens: int | None = None
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
    is_active: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyRead(BaseModel):
    """API Key 元数据 + 可解密的完整 Key。"""
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
    is_active: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None
    key_plain: str  # 解密后的完整明文，旧 Key 为空串

    model_config = {"from_attributes": True}


class ApiKeyCreateResponse(ApiKeyRead):
    """创建时返回完整密钥（向后兼容保留 key 字段）。"""
    key: str  # 等同于 key_plain，保留向后兼容
