"""Hybrid RBAC request and response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

DataScope = Literal["all", "custom_departments", "department", "department_and_children", "self"]


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    code: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.:-]*$")
    description: str | None = Field(None, max_length=500)
    data_scope: DataScope = "self"
    is_active: bool = True


class RoleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class RolePermissionsReplace(BaseModel):
    permission_codes: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("permission_codes")
    @classmethod
    def normalize_codes(cls, value: list[str]) -> list[str]:
        codes = [code.strip() for code in value if code.strip()]
        if any(len(code) > 160 for code in codes):
            raise ValueError("permission code must be 160 characters or fewer")
        return list(dict.fromkeys(codes))


class RoleDataScopeReplace(BaseModel):
    data_scope: DataScope
    department_ids: list[UUID] = Field(default_factory=list, max_length=1000)


class UserRolesReplace(BaseModel):
    role_ids: list[UUID] = Field(default_factory=list, max_length=100)


class RoleSummary(BaseModel):
    id: UUID
    name: str
    code: str
    data_scope: str
    is_builtin: bool = False


class RoleRead(RoleSummary):
    organization_id: UUID
    description: str | None
    is_active: bool
    permission_codes: list[str] = Field(default_factory=list)
    department_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EffectiveDataScopeRead(BaseModel):
    unrestricted: bool = False
    include_self: bool = False
    own_only: bool = False
    department_ids: list[UUID] = Field(default_factory=list)
