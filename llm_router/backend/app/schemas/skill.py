"""Skill Pydantic schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from app.schemas._base import MetaReadModel, OrmModel


class SkillCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    definition: dict = Field(default_factory=dict)
    bound_endpoint_ids: list[str] = Field(default_factory=list)
    param_mapping: dict = Field(default_factory=dict)
    scope_type: str = Field("organization", max_length=20)
    scope_id: str | None = None
    is_active: bool = True


class SkillUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    definition: dict | None = None
    bound_endpoint_ids: list[str] | None = None
    param_mapping: dict | None = None
    scope_type: str | None = Field(None, max_length=20)
    scope_id: str | None = None
    is_active: bool | None = None


class SkillRead(OrmModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str | None = None
    definition: dict
    bound_endpoint_ids: list[str]
    param_mapping: dict
    scope_type: str
    scope_id: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SkillTestRequest(BaseModel):
    params: dict = Field(default_factory=dict)


# ── 技能文件夹化（SkillFolder + SkillFile）──────────────────────────────

class SkillFolderCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    scope_type: str = Field("organization", max_length=20)
    scope_id: str | None = None


class SkillFolderUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    slug: str | None = Field(None, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    is_active: bool | None = None


class SkillFolderRead(OrmModel):
    id: UUID
    organization_id: UUID
    scope_type: str
    scope_id: str | None = None
    name: str
    slug: str
    created_by: str | None = None
    active_version_id: UUID | None = None
    is_active: bool = True
    is_installed: bool = False
    created_at: datetime
    updated_at: datetime


class SkillFileCreate(BaseModel):
    path: str = Field(..., max_length=1024)
    content: str = ""
    metadata: dict = Field(default_factory=dict)


class SkillFileUpdate(BaseModel):
    path: str | None = Field(None, max_length=1024)
    content: str | None = None
    metadata: dict | None = None


class SkillFileReadMeta(MetaReadModel):
    """文件列表/摘要：不含 content（避免大字段）。"""
    id: UUID
    skill_folder_id: UUID
    path: str
    size: int
    content_hash: str | None = None
    created_at: datetime
    updated_at: datetime


class SkillFileRead(SkillFileReadMeta):
    """单文件详情：含 content。"""
    content: str | None = None


class SkillVersionRead(OrmModel):
    id: UUID
    skill_folder_id: UUID
    version_no: int
    package_hash: str
    manifest: dict
    runtime: str
    entrypoint: str | None = None
    is_executable: bool
    install_status: Literal["pending", "installing", "ready", "failed"]
    install_error: str | None = None
    archive_ref: str | None = None
    archive_size: int = 0
    storage_status: Literal["inline", "stored", "purge_pending", "purged", "failed"] = "inline"
    purge_after: datetime | None = None
    archive_purged_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def package_format(self) -> str:
        platform = self.manifest.get("_platform") if isinstance(self.manifest, dict) else None
        return str(platform.get("package_format")) if isinstance(platform, dict) else "legacy"

    @computed_field
    @property
    def script_languages(self) -> list[str]:
        platform = self.manifest.get("_platform") if isinstance(self.manifest, dict) else None
        values = platform.get("script_languages") if isinstance(platform, dict) else []
        return [str(value) for value in values] if isinstance(values, list) else []

    @computed_field
    @property
    def compatibility_warnings(self) -> list[str]:
        platform = self.manifest.get("_platform") if isinstance(self.manifest, dict) else None
        values = platform.get("compatibility_warnings") if isinstance(platform, dict) else []
        return [str(value) for value in values] if isinstance(values, list) else []

    @computed_field
    @property
    def python_version(self) -> str | None:
        platform = self.manifest.get("_platform") if isinstance(self.manifest, dict) else None
        value = platform.get("python_version") if isinstance(platform, dict) else None
        return str(value) if value else None

    @computed_field
    @property
    def node_version(self) -> str | None:
        platform = self.manifest.get("_platform") if isinstance(self.manifest, dict) else None
        value = platform.get("node_version") if isinstance(platform, dict) else None
        return str(value) if value else None

    @computed_field
    @property
    def builtin_dependencies(self) -> dict:
        platform = self.manifest.get("_platform") if isinstance(self.manifest, dict) else None
        value = platform.get("builtin_dependencies") if isinstance(platform, dict) else None
        return value if isinstance(value, dict) else {}

    @computed_field
    @property
    def installed_dependencies(self) -> dict:
        platform = self.manifest.get("_platform") if isinstance(self.manifest, dict) else None
        value = platform.get("installed_dependencies") if isinstance(platform, dict) else None
        return value if isinstance(value, dict) else {}


class SkillImportRead(BaseModel):
    folder: SkillFolderRead
    version: SkillVersionRead


class SkillScopeNode(BaseModel):
    scope_type: Literal["organization", "department", "team", "user"]
    scope_id: str | None
    name: str
    can_import: bool = False
    can_manage: bool = False


class SkillExecutionRead(OrmModel):
    id: int
    organization_id: UUID
    user_id: UUID | None = None
    task_id: UUID | None = None
    agent_id: UUID | None = None
    skill_folder_id: UUID
    skill_version_id: UUID
    input_file_ids: list[str]
    output_file_ids: list[str]
    params: dict
    status: str
    latency_ms: int | None = None
    error: str | None = None
    created_at: datetime
