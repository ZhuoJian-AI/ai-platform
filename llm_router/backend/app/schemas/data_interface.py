"""Data interface Pydantic schemas — 数据接口页独立数据结构。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas._base import OrmModel


class DataSystemCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = None
    scope_type: str = Field("organization", max_length=20)
    scope_id: str | None = None
    is_active: bool = True


class DataSystemUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    is_active: bool | None = None


class DataSystemRead(OrmModel):
    id: UUID
    organization_id: UUID
    scope_type: str
    scope_id: str | None = None
    name: str
    description: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DataInterfaceCreate(BaseModel):
    name: str = Field(..., max_length=255)
    method: str | None = Field(None, max_length=20)
    path: str | None = Field(None, max_length=1024)
    description: str | None = None
    params_schema: dict = Field(default_factory=dict)
    response_schema: dict = Field(default_factory=dict)
    is_active: bool = True


class DataInterfaceUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    method: str | None = Field(None, max_length=20)
    path: str | None = Field(None, max_length=1024)
    description: str | None = None
    params_schema: dict | None = None
    response_schema: dict | None = None
    is_active: bool | None = None


class DataInterfaceRead(OrmModel):
    id: UUID
    data_system_id: UUID
    name: str
    method: str | None = None
    path: str | None = None
    description: str | None = None
    params_schema: dict
    response_schema: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime
