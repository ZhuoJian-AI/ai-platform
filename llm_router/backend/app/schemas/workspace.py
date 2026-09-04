"""Workspace Pydantic schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

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
    base_version_id: UUID | None = None
    idempotency_key: str | None = Field(None, min_length=8, max_length=160)

    @model_validator(mode="after")
    def require_change(self):
        if self.content is None and self.metadata is None:
            raise ValueError("content or metadata is required")
        return self


class WorkspaceFilePresentation(BaseModel):
    """Stable user-facing metadata; storage identifiers remain unchanged."""

    display_name: str
    source_kind: str = "upload"
    source_task_id: str | None = None
    source_task_title: str | None = None
    skill_id: str | None = None
    skill_display_name: str | None = None
    skill_version: str | None = None
    created_at: str | None = None


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
    mutation_result_version_id: UUID | None = None
    previous_version_id: UUID | None = None
    resolved_version_id: UUID | None = None
    resolved_version_no: int | None = None
    is_historical: bool = False
    workspace_name: str | None = None
    workspace_slug: str | None = None
    canonical_path: str | None = None
    current_version_no: int | None = None
    capabilities: dict[str, bool] | None = None
    effective_capabilities: dict[str, bool] | None = None
    internal_url: str | None = None
    office_edit_enabled: bool = False
    presentation: WorkspaceFilePresentation | None = None

    @model_validator(mode="after")
    def derive_presentation(self):
        if self.canonical_path is None:
            self.canonical_path = self.path
        if self.presentation is None:
            from app.utils.workspace_presentation import presentation_dict

            self.presentation = WorkspaceFilePresentation(**presentation_dict(
                self.path, self.metadata, created_at=self.created_at,
            ))
        if self.effective_capabilities is None:
            self.effective_capabilities = self.capabilities
        if self.capabilities is None:
            self.capabilities = self.effective_capabilities
        return self


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
    current_version_id: UUID | None = None
    previous_version_id: UUID | None = None
    workspace_name: str | None = None
    workspace_slug: str | None = None
    canonical_path: str | None = None
    current_version_no: int | None = None
    capabilities: dict[str, bool] | None = None
    effective_capabilities: dict[str, bool] | None = None
    internal_url: str | None = None
    office_edit_enabled: bool = False
    parse_status: str = "unparsed"
    parse_kind: str | None = None
    parse_error: str | None = None
    created_at: datetime
    updated_at: datetime
    presentation: WorkspaceFilePresentation


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


class WorkspaceOriginalPreviewSourceRead(BaseModel):
    mode: str
    url: str | None = None
    fallback_url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    filename: str
    mime_type: str


class WorkspaceDownloadTicketRead(BaseModel):
    url: str
    fallback_url: str | None = None
    expires_at: datetime
    filename: str
    mime_type: str
    etag: str | None = None
    size: int
    headers: dict[str, str] = Field(default_factory=dict)


class WorkspacePreviewSessionRead(BaseModel):
    mode: str
    filename: str
    mime_type: str
    size: int
    url: str | None = None
    fallback_url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    weboffice_url: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    access_token_expired_time: str | None = None
    refresh_token_expired_time: str | None = None
    refresh_context: str | None = None
    reason: str | None = None
    strict_range: bool = False
    file_id: str | None = None
    source_version_id: str | None = None
    room_id: UUID | None = None
    save_status: str | None = None


class WorkspacePreviewSessionCreate(BaseModel):
    client_open_id: str = Field(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    preferred_mode: Literal["default", "fast_layout", "interactive_ppt"] = "default"
    version_id: UUID | None = None


class WorkspacePreviewSessionRefresh(BaseModel):
    access_token: str = Field(..., min_length=16, max_length=4096)
    refresh_token: str = Field(..., min_length=16, max_length=4096)
    refresh_context: str = Field(..., min_length=32, max_length=4096)
    room_id: UUID | None = None


class WorkspaceEditRoomStatusRead(BaseModel):
    room_id: UUID
    status: str
    save_status: str
    source_file_version_id: UUID | None = None
    final_file_version_id: UUID | None = None
    current_version_id: UUID | None = None
    error: str | None = None


class WorkspaceEditSessionCreate(BaseModel):
    client_open_id: str = Field(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class WorkspaceEditSessionClose(BaseModel):
    client_open_id: str = Field(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class WorkspaceFileRestoreRequest(BaseModel):
    """Explicit optimistic restore; the server never guesses a mutable base."""

    base_version_id: UUID
    idempotency_key: str = Field(..., min_length=8, max_length=160)


class WorkspaceFileDeleteRequest(BaseModel):
    """Explicit optimistic delete; the server never guesses a mutable base."""

    base_version_id: UUID
    idempotency_key: str = Field(..., min_length=8, max_length=160)


class WorkspaceFileMoveRequest(BaseModel):
    target_workspace_id: UUID | None = None
    target_path: str = Field(..., min_length=1, max_length=1024)
    base_version_id: UUID
    idempotency_key: str = Field(..., min_length=8, max_length=160)


class WorkspaceFileRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=512)
    base_version_id: UUID
    idempotency_key: str = Field(..., min_length=8, max_length=160)


class WorkspaceFileCopyRequest(BaseModel):
    target_workspace_id: UUID
    target_path: str | None = Field(None, min_length=1, max_length=1024)
    base_version_id: UUID
    idempotency_key: str = Field(..., min_length=8, max_length=160)


class WorkspaceFallbackPreviewRead(BaseModel):
    status: str
    attempt_count: int
    url: str | None = None
    fallback_url: str | None = None
    expires_at: datetime | None = None
    error: str | None = None


class WorkspaceSpreadsheetPreviewRead(BaseModel):
    status: str
    attempt_count: int
    sheets: list[dict] = Field(default_factory=list)
    error: str | None = None


class WorkspaceSpreadsheetPageRead(BaseModel):
    sheet: str
    page: int
    page_size: int
    total_rows: int
    truncated: bool = False
    rows: list[list[str | int | float | bool | None]] = Field(default_factory=list)


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
    weak_network: bool = False
    target_file_id: UUID | None = None
    base_version_id: UUID | None = None
    idempotency_key: str | None = Field(None, min_length=8, max_length=160)

    @model_validator(mode="after")
    def require_complete_version_replacement_identity(self):
        supplied = (
            self.target_file_id is not None,
            self.base_version_id is not None,
            bool(self.idempotency_key),
        )
        if any(supplied) and not all(supplied):
            raise ValueError(
                "target_file_id, base_version_id and idempotency_key must be supplied together"
            )
        return self


class WorkspaceUploadSessionRead(BaseModel):
    id: UUID
    method: str = "PUT"
    url: str | None = None
    fallback_url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    fields: dict[str, str] = Field(default_factory=dict)
    part_size: int | None = None
    expected_parts: int | None = None
    expires_at: datetime
    max_file_bytes: int


class WorkspaceUploadPartReceipt(BaseModel):
    part_number: int = Field(..., ge=1, le=10_000)
    etag: str = Field(..., min_length=1, max_length=256)


class WorkspaceUploadComplete(BaseModel):
    etag: str | None = Field(None, max_length=256)
    parts: list[WorkspaceUploadPartReceipt] = Field(default_factory=list, max_length=10_000)


class WorkspaceUploadPartSigned(BaseModel):
    part_number: int
    method: str = "PUT"
    url: str
    fallback_url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    expires_in: int


class WorkspaceUploadMultipartStatus(BaseModel):
    status: str
    part_size: int
    expected_parts: int
    uploaded_parts: list[dict] = Field(default_factory=list)
    expires_at: datetime


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
    internal_url: str | None = None

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
    actor_display_name: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
