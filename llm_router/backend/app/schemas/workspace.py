"""Workspace Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas._base import MetaReadModel, OrmModel


class WorkspaceCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    storage_backend: str = Field("local", max_length=20)
    root_path: str = Field("", max_length=512)
    config: dict = Field(default_factory=dict)
    scope_type: str = Field("organization", max_length=20)
    scope_id: str | None = None
    is_active: bool = True


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    config: dict | None = None
    scope_type: str | None = Field(None, max_length=20)
    scope_id: str | None = None
    is_active: bool | None = None


class WorkspaceRead(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str | None
    storage_backend: str
    root_path: str
    config: dict
    scope_type: str
    scope_id: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    capabilities: dict[str, bool] | None = None

    model_config = {"from_attributes": True}


class WorkspaceFileCreate(BaseModel):
    path: str = Field(..., max_length=1024)
    content: str = ""
    metadata: dict = Field(default_factory=dict)


class WorkspaceFileUpdate(BaseModel):
    content: str | None = None
    metadata: dict | None = None


class WorkspaceFileRead(MetaReadModel):
    id: UUID
    workspace_id: UUID
    path: str
    size: int
    content_hash: str | None = None
    content: str | None = None
    extracted_text: str | None = None
    parse_status: str = "unparsed"
    parse_kind: str | None = None
    parse_error: str | None = None
    created_at: datetime
    updated_at: datetime
    current_version_id: UUID | None = None


class WorkspaceFileListItem(BaseModel):
    """Lightweight file metadata returned by workspace list endpoints.

    Deliberately excludes ``content`` and ``extracted_text`` so listing a
    workspace never transfers the stored Base64 payload or parsed document.
    """

    id: UUID
    workspace_id: UUID
    path: str
    original_filename: str
    size: int
    mime_type: str | None = None
    is_binary: bool = False
    content_hash: str | None = None
    parse_status: str = "unparsed"
    parse_kind: str | None = None
    parse_error: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkspaceFilePage(BaseModel):
    items: list[WorkspaceFileListItem]
    total: int
    page: int
    page_size: int


class WorkspaceFilePreviewRead(BaseModel):
    id: UUID
    path: str
    parse_status: str
    parse_kind: str | None = None
    parse_error: str | None = None
    extracted_text: str | None = None


class WorkspaceFolderCreate(BaseModel):
    path: str = Field(..., max_length=1024)


class WorkspaceFolderRead(OrmModel):
    id: UUID
    workspace_id: UUID
    path: str
    created_at: datetime
    updated_at: datetime


class WorkspaceBulkDeleteRequest(BaseModel):
    file_ids: list[UUID] = Field(default_factory=list, max_length=200)
    folder_paths: list[str] = Field(default_factory=list, max_length=100)


class WorkspaceBulkDeleteResult(BaseModel):
    deleted_files: int
    deleted_folders: int


class WorkspaceUploadInitiate(BaseModel):
    path: str = Field(..., max_length=1024)
    filename: str = Field(..., max_length=512)
    content_type: str = Field("application/octet-stream", max_length=255)
    size: int = Field(..., gt=0)


class WorkspaceUploadSessionRead(BaseModel):
    id: UUID
    method: str = "PUT"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime
    max_file_bytes: int


class WorkspaceUploadComplete(BaseModel):
    etag: str | None = Field(None, max_length=256)


class WorkspaceFileVersionRead(BaseModel):
    id: UUID
    workspace_file_id: UUID
    version_no: int
    size: int
    content_hash: str | None = None
    parse_status: str
    parse_kind: str | None = None
    parse_error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkspacePublishRequest(BaseModel):
    target_workspace_id: UUID
    target_path: str | None = Field(None, max_length=1024)


class WorkspaceShareCreate(BaseModel):
    expires_in_seconds: int = Field(7 * 24 * 3600, ge=60, le=30 * 24 * 3600)


class WorkspaceShareRead(BaseModel):
    url: str
    expires_at: datetime


class WorkspaceAuditEventRead(MetaReadModel):
    id: int
    workspace_id: UUID
    workspace_file_id: UUID | None = None
    version_id: UUID | None = None
    action: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
