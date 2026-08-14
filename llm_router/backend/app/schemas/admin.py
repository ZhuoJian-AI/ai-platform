"""Admin Pydantic schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)  # 登录用户名（非邮箱），支持 root 这类
    password: str = Field(..., min_length=1)
    # 带 slug = 组织门户登录（/{slug}/login），仅匹配该组织下的 org_admin；
    # 不带 slug = 平台登录（/login），仅匹配未绑定组织的平台级账号。
    slug: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False
    admin: "AdminRead"


class OrgInfoResponse(BaseModel):
    """组织门户登录页公开信息（仅暴露 name + slug，用于登录框展示组织名）。"""
    name: str
    slug: str


class AdminCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)
    display_name: str | None = Field(None, max_length=255)
    role: Literal["super_admin", "admin", "org_admin"] = "admin"
    # org_admin 必填；其余角色应为 None（平台级账号）
    organization_id: UUID | None = None


class AdminUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=255)
    role: Literal["super_admin", "admin", "org_admin"] | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=1, max_length=128)
    organization_id: UUID | None = None


class AdminRead(BaseModel):
    id: int
    username: str
    display_name: str | None
    role: str
    is_active: bool
    must_change_password: bool = False
    organization_id: UUID | None = None
    organization_name: str | None = None
    organization_slug: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1, max_length=128)
