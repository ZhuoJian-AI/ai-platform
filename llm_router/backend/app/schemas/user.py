"""User Pydantic schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=320)
    display_name: str | None = Field(None, max_length=255)
    role: Literal["admin", "member"] = "member"
    department_id: UUID | None = None
    team_id: UUID | None = None
    is_active: bool = True
    password: str = Field(..., min_length=8, max_length=128)


class UserUpdate(BaseModel):
    username: str | None = Field(None, min_length=1, max_length=320)
    display_name: str | None = Field(None, max_length=255)
    role: Literal["admin", "member"] | None = None
    department_id: UUID | None = None
    team_id: UUID | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8, max_length=128)


class UserPasswordReset(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


class UserLoginRequest(BaseModel):
    """组织用户登录请求。username 仅组织内唯一，故必须带 organization_id。"""
    organization_id: UUID
    username: str
    password: str = Field(..., min_length=1, max_length=128)


class UserSlugLoginRequest(BaseModel):
    """终端用户按组织 slug 登录请求（多租户兼容）。"""
    slug: str
    username: str
    password: str = Field(..., min_length=1, max_length=128)


class UserRead(BaseModel):
    id: UUID
    organization_id: UUID
    username: str
    display_name: str | None
    role: str
    department_id: UUID | None = None
    team_id: UUID | None = None
    is_active: bool
    must_change_password: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False
    user: UserRead
