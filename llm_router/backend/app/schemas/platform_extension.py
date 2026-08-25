"""Public schemas for the super-admin platform extension center."""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.schemas._base import OrmModel

ExtensionKind = Literal["runtime_plugin", "system_tool", "library", "adapter_required", "incompatible"]


class ExtensionCatalogItem(BaseModel):
    id: UUID | None = None
    slug: str
    name: str
    version: str
    description: str
    kind: ExtensionKind
    source: Literal["core", "official", "community", "reviewed", "external"]
    status: str
    removable: bool = True
    capabilities: list[str] = Field(default_factory=list)
    compatibility_warnings: list[str] = Field(default_factory=list)
    layer: str = "unknown"
    operation: Literal["add", "replace"] = "add"
    trust_level: str = "platform"
    runtime_requirements: dict = Field(default_factory=dict)
    compatibility_status: str = "compatible"
    compatibility_reasons: list[str] = Field(default_factory=list)
    repository: str | None = None
    homepage: str | None = None
    package_name: str | None = None
    available_versions: list[str] = Field(default_factory=list)
    category: str = "unknown"
    metadata: dict = Field(default_factory=dict)
    lifecycle_status: str = "available"
    installed: bool = False
    installed_version: str | None = None
    active_source_id: UUID | None = None
    latest_source_id: UUID | None = None


class ExtensionCatalogPage(BaseModel):
    items: list[ExtensionCatalogItem] = Field(default_factory=list)
    page: int = 1
    page_size: int = 48
    total: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    sync: dict = Field(default_factory=dict)


class ExtensionCatalogImportRequest(BaseModel):
    source: Literal["npm", "github"] | None = None
    version: str | None = Field(None, max_length=100)
    ref: str | None = Field(None, max_length=255)


class ExtensionImportNpm(BaseModel):
    package: str = Field(..., min_length=1, max_length=255, pattern=r"^(?:@[-a-zA-Z0-9_.]+/)?[-a-zA-Z0-9_.]+$")
    version: str = Field(..., min_length=1, max_length=100)

    @field_validator("version")
    @classmethod
    def exact_version_only(cls, value: str) -> str:
        if not re.fullmatch(r"v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", value):
            raise ValueError("npm imports require an exact semantic version, not latest or a range")
        return value


class ExtensionImportGithub(BaseModel):
    repository: HttpUrl
    ref: str = Field(..., min_length=1, max_length=255)


class ExtensionArtifactSign(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    size_bytes: int = Field(..., gt=0)
    sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")


class ExtensionSourceRead(OrmModel):
    id: UUID
    source_type: str
    locator: str
    requested_version: str | None = None
    resolved_version: str | None = None
    commit_sha: str | None = None
    artifact_ref: str | None = None
    artifact_sha256: str | None = None
    manifest: dict
    build_report: dict
    compatibility: dict
    status: str
    review_status: str
    error: str | None = None
    imported_by_admin_id: int
    approved_by_admin_id: int | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExtensionApproveRequest(BaseModel):
    approved: bool = True
    note: str | None = Field(None, max_length=1000)


class ExtensionReleaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    source_ids: list[UUID] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)


class ExtensionReleaseRead(OrmModel):
    id: UUID
    version_no: int
    name: str
    manifest: dict
    checksum: str
    status: str
    is_active: bool
    base_release_id: UUID | None = None
    created_by_admin_id: int
    published_by_admin_id: int | None = None
    activated_at: datetime | None = None
    validation_report: dict
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ExtensionReleaseEventRead(OrmModel):
    id: int
    source_id: UUID | None = None
    release_id: UUID | None = None
    actor_admin_id: int | None = None
    event_type: str
    status: str
    details: dict
    created_at: datetime


class ExtensionOverview(BaseModel):
    active_release: ExtensionReleaseRead | None = None
    runtime_health: dict = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)
    release_counts: dict[str, int] = Field(default_factory=dict)
    core_plugins: list[ExtensionCatalogItem] = Field(default_factory=list)
    system_tools: list[ExtensionCatalogItem] = Field(default_factory=list)
