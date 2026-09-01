"""User Pydantic schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.role import EffectiveDataScopeRead, RoleSummary


class ManagerScopeGrant(BaseModel):
    scope_type: Literal["department", "team"]
    scope_id: UUID


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=320)
    display_name: str | None = Field(None, max_length=255)
    role: Literal["admin", "member"] = "member"
    # 兼容旧客户端字段，但组织归属始终只能有一个部门。
    department_ids: list[UUID] = Field(default_factory=list, max_length=1)
    department_id: UUID | None = None
    team_id: UUID | None = None
    is_active: bool = True
    password: str = Field(..., min_length=8, max_length=128)
    manager_scopes: list[ManagerScopeGrant] = Field(default_factory=list)
    role_ids: list[UUID] | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def validate_single_department(self) -> "UserCreate":
        legacy_department_id = self.department_ids[0] if self.department_ids else None
        if self.department_id and legacy_department_id and self.department_id != legacy_department_id:
            raise ValueError("department_id and department_ids must identify the same department")
        selected = self.department_id or legacy_department_id
        self.department_id = selected
        self.department_ids = [selected] if selected else []
        return self


class UserUpdate(BaseModel):
    username: str | None = Field(None, min_length=1, max_length=320)
    display_name: str | None = Field(None, max_length=255)
    role: Literal["admin", "member"] | None = None
    department_ids: list[UUID] | None = Field(None, max_length=1)
    department_id: UUID | None = None
    team_id: UUID | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8, max_length=128)
    manager_scopes: list[ManagerScopeGrant] | None = None
    role_ids: list[UUID] | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def validate_single_department(self) -> "UserUpdate":
        if "department_ids" not in self.model_fields_set or "department_id" not in self.model_fields_set:
            return self
        legacy_department_id = self.department_ids[0] if self.department_ids else None
        if self.department_id != legacy_department_id:
            raise ValueError("department_id and department_ids must identify the same department")
        return self


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
    department_ids: list[UUID] = Field(default_factory=list)
    department_id: UUID | None = None
    team_id: UUID | None = None
    is_active: bool
    must_change_password: bool = False
    manager_scopes: list[ManagerScopeGrant] = Field(default_factory=list)
    role_ids: list[UUID] = Field(default_factory=list)
    roles: list[RoleSummary] = Field(default_factory=list)
    permission_codes: list[str] = Field(default_factory=list)
    effective_data_scopes: EffectiveDataScopeRead | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False
    user: UserRead
