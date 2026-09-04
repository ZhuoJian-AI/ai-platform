"""Admin Pydantic schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

AdminRole = Literal["platform_super_admin", "enterprise_admin"]


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)  # 登录用户名（非邮箱），支持 root 这类
    password: str = Field(..., min_length=1)
    # 带 slug = 组织门户登录（/{slug}/login），仅匹配该组织下的 enterprise_admin；
    # 不带 slug = 平台登录（/login），仅匹配未绑定组织的平台级账号。
    slug: str | None = None
    mfa_code: str | None = Field(None, min_length=6, max_length=32)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False
    admin: "AdminRead"
    # Double-submit value for browser clients.  The session JWT itself is only
    # stored in an HttpOnly cookie; legacy bearer clients may ignore this.
    csrf_token: str | None = None
    mfa_enrollment_required: bool = False


class OrgInfoResponse(BaseModel):
    """组织门户登录页公开信息（仅暴露 name + slug，用于登录框展示组织名）。"""

    name: str
    slug: str


class AdminCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=320)
    password: str = Field(..., min_length=12, max_length=128)
    display_name: str | None = Field(None, max_length=255)
    role: AdminRole
    organization_id: UUID | None = None

    @model_validator(mode="after")
    def validate_role_organization(self) -> "AdminCreate":
        if self.role == "platform_super_admin" and self.organization_id is not None:
            raise ValueError("platform_super_admin cannot be bound to an organization")
        if self.role == "enterprise_admin" and self.organization_id is None:
            raise ValueError("organization_id is required for enterprise_admin")
        return self


class AdminUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=255)
    # Role and organization are accepted only so old clients receive an explicit
    # immutable-field error. They may be repeated unchanged but never reassigned.
    role: AdminRole | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=12, max_length=128)
    organization_id: UUID | None = None


class AdminRead(BaseModel):
    id: int
    username: str
    display_name: str | None
    role: AdminRole
    is_active: bool
    must_change_password: bool = False
    auth_epoch: int = 0
    mfa_enabled: bool = False
    organization_id: UUID | None = None
    organization_name: str | None = None
    organization_slug: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=12, max_length=128)


class MfaCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=32)
