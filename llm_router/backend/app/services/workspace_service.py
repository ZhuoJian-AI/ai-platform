"""Workspace service — CRUD for workspaces and their files."""

import base64
import hashlib
import io
import json
import mimetypes
import unicodedata
import zipfile
from datetime import UTC, datetime
from pathlib import PurePosixPath
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.config import settings
from app.models.department import Department
from app.models.organization import Organization
from app.models.team import Team
from app.models.user import User
from app.models.workspace import (
    OfficeEditRoom,
    Workspace,
    WorkspaceFile,
    WorkspaceFileEventOutbox,
    WorkspaceFileMutation,
    WorkspaceFileVersion,
    WorkspaceFolder,
)
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceFileCreate,
    WorkspaceFileListItem,
    WorkspaceFileUpdate,
    WorkspaceFolderCreate,
    WorkspaceUpdate,
)
from app.services import doc_parser, storage_gateway_service
from app.services.storage_lifecycle_service import mark_deleted, mark_workspace_deleted
from app.utils.workspace_presentation import clean_display_name, enrich_metadata, presentation_dict

MAX_WORKSPACE_FILE_BYTES = settings.workspace_max_file_bytes
MAX_LLM_FILE_CHARS = 100_000
MAX_TOOL_FILE_BYTES = 50 * 1024

_RAW_IMAGE_TOOL_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".pdf",
)
_RAW_ARCHIVE_TOOL_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz")
_RAW_AUDIO_TOOL_SUFFIXES = (".mp3", ".wav", ".m4a", ".webm", ".opus")
_WORD_BINARY_SUFFIXES = {
    ".doc", ".docx", ".docm", ".dot", ".dotx", ".dotm", ".wps", ".wpt",
    ".rtf", ".odt", ".ott",
}
_SPREADSHEET_BINARY_SUFFIXES = {
    ".xls", ".xlsx", ".xlsm", ".xlt", ".xltx", ".xltm", ".et",
    ".ods", ".ots",
}
_PRESENTATION_BINARY_SUFFIXES = {
    ".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".ppsm", ".potx", ".potm", ".dps",
    ".pot", ".dpt", ".odp", ".otp",
}
_KNOWN_BINARY_SUFFIXES = {
    *_WORD_BINARY_SUFFIXES,
    *_SPREADSHEET_BINARY_SUFFIXES,
    *_PRESENTATION_BINARY_SUFFIXES,
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".mp4", ".mov", ".avi",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".bin", ".epub",
}
_KNOWN_TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".css", ".scss", ".less", ".js", ".jsx", ".ts", ".tsx",
    ".py", ".java", ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".rb",
    ".sh", ".ps1", ".sql", ".toml", ".ini", ".cfg", ".conf", ".log",
}
_KNOWN_BINARY_MIME_PREFIXES = (
    "image/", "audio/", "video/",
    "application/vnd.ms-", "application/vnd.openxmlformats-",
    "application/vnd.oasis.opendocument", "application/vnd.apple.",
)
_KNOWN_BINARY_MIMES = {
    "application/pdf", "application/msword", "application/zip",
    "application/x-7z-compressed", "application/x-rar-compressed",
    "application/x-tar", "application/gzip", "application/octet-stream",
}
WEBOFFICE_EDITABLE_SUFFIXES = {
    ".doc", ".docx", ".dot", ".wps", ".wpt", ".dotx", ".docm", ".dotm",
    ".ppt", ".pptx", ".pptm", ".ppsx", ".ppsm", ".pps", ".potx", ".potm", ".dpt", ".dps",
    ".et", ".xls", ".xlt", ".xlsx", ".xlsm", ".xltx", ".xltm",
}


class WorkspaceFileUploadError(ValueError):
    """工作空间原文件上传校验失败。"""


class WorkspaceFileInvalidPath(ValueError):  # noqa: N818
    """The caller supplied an unsafe or otherwise invalid logical path."""


class WorkspaceFileUnsupportedTextUpdate(ValueError):  # noqa: N818
    """A plain-text mutation was attempted against a known binary artifact."""


class WorkspaceFileMetadataConflict(ValueError):  # noqa: N818
    """A generic update attempted to forge storage or file identity metadata."""


class WorkspaceFilePathConflict(ValueError):  # noqa: N818
    """A create/upload attempted to overwrite a live logical path."""

    def __init__(self, file: WorkspaceFile):
        super().__init__("目标路径已存在；请按 file_id 和 base_version_id 明确更新")
        self.file_id = str(file.id)
        self.current_version_id = str(file.current_version_id) if file.current_version_id else None


class WorkspaceFileVersionConflict(ValueError):  # noqa: N818
    """The caller edited a stale file version."""

    def __init__(self, message: str, *, current_version_id: str | UUID | None = None):
        super().__init__(message)
        self.current_version_id = str(current_version_id) if current_version_id else None


class WorkspaceFileIdempotencyConflict(ValueError):  # noqa: N818
    """An idempotency key was reused for a different mutation."""


class WorkspaceFileActiveEditConflict(ValueError):  # noqa: N818
    """A WebOffice room owns the mutable OSS object for this logical file."""

    def __init__(
        self,
        message: str,
        *,
        room_id: str | UUID,
        current_version_id: str | UUID | None,
    ):
        super().__init__(message)
        self.room_id = str(room_id)
        self.current_version_id = str(current_version_id) if current_version_id else None


class WorkspaceFileVersionNotFound(ValueError):  # noqa: N818
    """The requested immutable version does not belong to the logical file."""


def office_edit_enabled(file, *, can_update: bool) -> bool:
    """Return the effective server-owned WebOffice editing capability.

    The role capability is necessary but never sufficient: the Platform flag,
    authenticated Gateway configuration and callback verification secret must
    all be present, and the concrete file must be a current OSS-backed Office
    artifact within the configured size limit.
    """
    if not can_update or not settings.workspace_weboffice_edit_configured:
        return False
    metadata = getattr(file, "metadata_", None) or {}
    filename = str(metadata.get("name") or getattr(file, "path", ""))
    return bool(
        PurePosixPath(filename).suffix.casefold() in WEBOFFICE_EDITABLE_SUFFIXES
        and storage_gateway_service.is_object_ref(getattr(file, "content_ref", None))
        and getattr(file, "current_version_id", None)
        and 0 < int(getattr(file, "size", 0) or 0) <= settings.workspace_weboffice_max_bytes
    )


def raw_tool_file_kind(f: WorkspaceFile) -> str | None:
    """Return the platform tool that can consume an unparsed raw binary file.

    Images/scanned PDFs and archives do not need a text extraction result before
    they can be passed to the immutable Runner lane.  Keep this allow-list aligned
    with ``image_tool`` and ``archive_tool`` rather than accepting arbitrary binary
    uploads as chat-ready.
    """
    meta = f.metadata_ or {}
    name = str(meta.get("name") or PurePosixPath(f.path).name).strip().lower()
    if name.endswith(_RAW_IMAGE_TOOL_SUFFIXES):
        return "image_tool"
    if name.endswith(_RAW_ARCHIVE_TOOL_SUFFIXES):
        return "archive_tool"
    if name.endswith(_RAW_AUDIO_TOOL_SUFFIXES):
        return "understand_audio"
    return None


# ── Workspace ──────────────────────────────────────────────────────────

async def create_workspace(db: AsyncSession, org_id: UUID, data: WorkspaceCreate) -> Workspace:
    ws = Workspace(organization_id=org_id, **data.model_dump())
    db.add(ws)
    await db.flush()
    return ws


async def list_workspaces(db: AsyncSession, org_id: UUID) -> list[Workspace]:
    result = await db.execute(
        select(Workspace).where(Workspace.organization_id == org_id, Workspace.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_workspace(db: AsyncSession, ws_id: UUID) -> Workspace | None:
    result = await db.execute(
        select(Workspace).where(Workspace.id == ws_id, Workspace.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_workspace(db: AsyncSession, ws: Workspace, data: WorkspaceUpdate) -> Workspace:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ws, field, value)
    await db.flush()
    await db.refresh(ws)
    return ws


async def soft_delete_workspace(db: AsyncSession, ws: Workspace) -> None:
    await mark_workspace_deleted(db, ws)


# ── WorkspaceFile ──────────────────────────────────────────────────────

def _normalize_path(path: str) -> str:
    """Normalize one logical relative path and reject traversal spellings."""
    if not isinstance(path, str):
        raise WorkspaceFileInvalidPath("路径必须是字符串")
    path = unicodedata.normalize("NFC", path)
    if "\x00" in path or any(ord(char) < 32 for char in path):
        raise WorkspaceFileInvalidPath("路径包含非法控制字符")
    parts: list[str] = []
    for seg in path.replace("\\", "/").split("/"):
        if seg in ("", ".",):
            continue
        if seg == "..":
            raise WorkspaceFileInvalidPath("路径不允许包含 ..")
        parts.append(seg)
    normalized = "/".join(parts)
    if not normalized:
        raise WorkspaceFileInvalidPath("路径不能为空")
    if len(normalized) > 1024:
        raise WorkspaceFileInvalidPath("路径过长")
    return normalized


def _sanitize_content(content: str) -> str:
    """剥离 PostgreSQL TEXT 列不允许的 NUL 字节（\\x00）。

    上传的二进制文件经 readAsText 后可能携带 U+0000，直接落库会触发
    ``CharacterNotInRepertoireError``。工作空间为智能体文本沙箱，二进制内容本就不适用，
    此处做防御性清洗避免 500。
    """
    return content.replace("\x00", "")


_RESERVED_FILE_METADATA_KEYS = {
    "binary", "mime", "name", "original_filename", "storage_backend",
    "storage_version_id", "etag", "integrity_algorithm", "integrity_value",
    "artifact_format_verified", "detected_artifact_format",
    "content_hash", "size", "task_id", "generated_by", "source_kind",
    "source_task_id", "source_task_title", "skill_id", "skill_display_name",
    "skill_version", "source_created_at",
}


def _merge_update_metadata(file: WorkspaceFile, patch: dict | None) -> dict:
    """Apply user metadata as a patch while preserving server-owned identity."""
    persisted = dict(file.metadata_ or {})
    if patch is None:
        return persisted
    for key, value in patch.items():
        reserved = key in _RESERVED_FILE_METADATA_KEYS or key.startswith(("storage_", "source_"))
        if reserved and value != persisted.get(key):
            raise WorkspaceFileMetadataConflict(
                f"metadata.{key} 由服务器维护，不能通过通用文件更新修改"
            )
    return {**persisted, **patch}


def _assert_plain_text_update_supported(file: WorkspaceFile) -> None:
    """Allow persisted text uploads without permitting binary corruption.

    ``metadata.binary`` records how an uploaded file is stored (raw bytes in
    OSS/PostgreSQL), not whether its logical format is editable text.  CSV,
    TXT, Markdown and JSON uploads therefore legitimately keep that marker.
    A known binary suffix, MIME type, or verified byte format always wins over
    a conflicting text hint so Office/PDF files cannot be overwritten through
    the generic text editor.
    """
    metadata = dict(file.metadata_ or {})
    path_suffix = PurePosixPath(str(file.path)).suffix.lower()
    name_suffix = PurePosixPath(str(metadata.get("name") or "")).suffix.lower()
    suffixes = {path_suffix, name_suffix} - {""}
    mime = str(metadata.get("mime") or "").split(";", 1)[0].strip().lower()
    verified_format = None
    if metadata.get("artifact_format_verified") is True:
        verified_format = _normalize_detected_artifact_format(
            str(metadata.get("detected_artifact_format") or "")
        )
    if (
        any(suffix in _KNOWN_BINARY_SUFFIXES for suffix in suffixes)
        or mime in (_KNOWN_BINARY_MIMES - {"application/octet-stream"})
        or mime.startswith(_KNOWN_BINARY_MIME_PREFIXES)
        or (verified_format is not None and verified_format != "text")
    ):
        raise WorkspaceFileUnsupportedTextUpdate(
            "该文件是二进制格式，不能用纯文本更新；请使用对应文件工具生成并替换原文件版本"
        )
    if any(suffix in _KNOWN_TEXT_SUFFIXES for suffix in suffixes) or mime.startswith("text/"):
        return
    if mime in {"application/json", "application/xml", "application/javascript"}:
        return
    if bool(metadata.get("binary")):
        raise WorkspaceFileUnsupportedTextUpdate(
            "无法确认该文件是安全文本格式，请使用文件制品更新接口"
        )
    if file.content is not None or str(file.parse_kind or "") in {"text", "csv", "json", "markdown"}:
        return
    if mime == "application/octet-stream":
        raise WorkspaceFileUnsupportedTextUpdate(
            "无法确认该文件是安全文本格式，请使用文件制品更新接口"
        )


def _assert_plain_text_create_supported(path: str, metadata: dict) -> None:
    """Reject a text body whose persisted identity denotes binary bytes."""
    probe = SimpleNamespace(
        path=path,
        metadata_=dict(metadata),
        content="",
        parse_kind="text",
    )
    _assert_plain_text_update_supported(probe)


def _artifact_family_from_suffix(suffix: str) -> str | None:
    if suffix in _WORD_BINARY_SUFFIXES:
        return "word"
    if suffix in _SPREADSHEET_BINARY_SUFFIXES:
        return "spreadsheet"
    if suffix in _PRESENTATION_BINARY_SUFFIXES:
        return "presentation"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}:
        return "image"
    if suffix in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}:
        return "audio"
    if suffix in {".mp4", ".mov", ".avi"}:
        return "video"
    if suffix in {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".epub"}:
        return "archive"
    if suffix in _KNOWN_TEXT_SUFFIXES:
        return "text"
    return None


def _artifact_family_from_mime(mime: str) -> str | None:
    value = str(mime or "").split(";", 1)[0].strip().lower()
    if value.startswith("image/"):
        return "image"
    if value.startswith("audio/"):
        return "audio"
    if value.startswith("video/"):
        return "video"
    if value.startswith("text/") or value in {
        "application/json", "application/xml", "application/javascript",
    }:
        return "text"
    if value == "application/pdf":
        return "pdf"
    if any(token in value for token in (
        "wordprocessingml", "msword", "opendocument.text",
    )):
        return "word"
    if any(token in value for token in (
        "spreadsheetml", "ms-excel", "opendocument.spreadsheet",
    )):
        return "spreadsheet"
    if any(token in value for token in (
        "presentationml", "ms-powerpoint", "opendocument.presentation",
    )):
        return "presentation"
    if value in {
        "application/zip", "application/x-7z-compressed",
        "application/x-rar-compressed", "application/x-tar", "application/gzip",
        "application/epub+zip",
    }:
        return "archive"
    return None


def _artifact_format_from_suffix(suffix: str) -> str | None:
    value = suffix.casefold().lstrip(".")
    if value == "jpg":
        return "jpeg"
    if value in {
        *(item.lstrip(".") for item in _WORD_BINARY_SUFFIXES),
        *(item.lstrip(".") for item in _SPREADSHEET_BINARY_SUFFIXES),
        *(item.lstrip(".") for item in _PRESENTATION_BINARY_SUFFIXES),
        "pdf", "png", "jpeg", "gif", "webp", "bmp", "tif", "tiff",
        "mp3", "wav", "m4a", "aac", "flac", "ogg", "opus",
        "mp4", "mov", "avi", "zip", "rar", "7z", "tar", "gz",
        "tgz", "bz2", "xz", "epub",
    }:
        return value
    if f".{value}" in _KNOWN_TEXT_SUFFIXES:
        return "text"
    return None


def _artifact_format_from_mime(mime: str) -> str | None:
    value = str(mime or "").split(";", 1)[0].strip().casefold()
    exact = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.ms-word.document.macroenabled.12": "docm",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template": "dotx",
        "application/vnd.ms-word.template.macroenabled.12": "dotm",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.ms-excel.sheet.macroenabled.12": "xlsm",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.template": "xltx",
        "application/vnd.ms-excel.template.macroenabled.12": "xltm",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
        "application/vnd.ms-powerpoint.presentation.macroenabled.12": "pptm",
        "application/vnd.openxmlformats-officedocument.presentationml.slideshow": "ppsx",
        "application/vnd.ms-powerpoint.slideshow.macroenabled.12": "ppsm",
        "application/vnd.openxmlformats-officedocument.presentationml.template": "potx",
        "application/vnd.ms-powerpoint.template.macroenabled.12": "potm",
        "application/vnd.oasis.opendocument.text": "odt",
        "application/vnd.oasis.opendocument.text-template": "ott",
        "application/vnd.oasis.opendocument.spreadsheet": "ods",
        "application/vnd.oasis.opendocument.spreadsheet-template": "ots",
        "application/vnd.oasis.opendocument.presentation": "odp",
        "application/vnd.oasis.opendocument.presentation-template": "otp",
        "image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif",
        "image/webp": "webp", "image/bmp": "bmp", "image/tiff": "tiff",
        "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
        "audio/flac": "flac", "audio/ogg": "ogg", "video/mp4": "mp4",
        "application/zip": "zip", "application/epub+zip": "epub",
    }
    if value in exact:
        return exact[value]
    if value.startswith("text/") or value in {
        "application/json", "application/xml", "application/javascript",
    }:
        return "text"
    return None


def _assert_artifact_replacement_compatible(
    file: WorkspaceFile,
    metadata: dict,
    *,
    content: str | None,
    content_ref: str | None,
) -> None:
    """Keep a stable path's format compatible with verified replacement bytes."""
    persisted = dict(file.metadata_ or {})
    target_name = str(persisted.get("name") or file.path)
    path_suffix = PurePosixPath(str(file.path)).suffix.lower()
    name_suffix = PurePosixPath(target_name).suffix.lower()
    suffix = (
        path_suffix
        if _artifact_family_from_suffix(path_suffix) is not None
        else name_suffix
    )
    persisted_mime = str(persisted.get("mime") or "")
    # Once a file is known binary, its server-owned MIME remains authoritative
    # even if a human renamed the path to a misleading extension.
    target_family = (
        _artifact_family_from_mime(persisted_mime)
        or _artifact_family_from_suffix(suffix)
        if persisted.get("binary")
        else _artifact_family_from_suffix(suffix) or _artifact_family_from_mime(persisted_mime)
    )
    if target_family is None:
        return
    target_format = (
        _artifact_format_from_mime(persisted_mime)
        or _artifact_format_from_suffix(suffix)
        if persisted.get("binary")
        else _artifact_format_from_suffix(suffix) or _artifact_format_from_mime(persisted_mime)
    )
    incoming_format: str | None = None
    if content is not None:
        try:
            raw = base64.b64decode(content, validate=True)
        except (TypeError, ValueError):
            raw = b""
        incoming_format = _detect_artifact_format(raw)
    elif content_ref is not None and metadata.get("artifact_format_verified") is True:
        incoming_format = _normalize_detected_artifact_format(
            str(metadata.get("detected_artifact_format") or "")
        )
    # A generic OLE/CFB signature does not distinguish Word, Excel and
    # PowerPoint.  Until the trusted storage inspector identifies the concrete
    # stream type, accepting it here could replace (for example) an .xls with
    # a .doc while preserving the old stable path.  Fail closed instead.
    if incoming_format == "legacy_office":
        incoming_format = None
    # Text is a representation rather than a container extension; UTF-8
    # source formats may safely retain their existing .md/.csv/etc identity.
    compatible = (
        incoming_format == "text" and target_family == "text"
    ) or (
        target_format is not None and incoming_format == target_format
    )
    if not compatible:
        raise WorkspaceFileUnsupportedTextUpdate(
            "无法从真实字节验证替换制品与原文件格式兼容；请另建文件或使用匹配格式的文件工具"
        )


def _normalize_detected_artifact_format(value: str) -> str | None:
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "ole": "legacy_office", "ole_compound": "legacy_office",
        "legacy_office": "legacy_office", "cfb": "legacy_office",
        "jpg": "jpeg", "tif": "tiff",
        "odf_text": "odt", "odf_spreadsheet": "ods", "odf_presentation": "odp",
    }
    if normalized in aliases:
        return aliases[normalized]
    exact = {
        "doc", "docx", "docm", "dot", "dotx", "dotm", "wps", "wpt", "rtf",
        "odt", "ott", "xls", "xlsx", "xlsm", "xlt", "xltx", "xltm", "et",
        "ods", "ots", "ppt", "pptx", "pptm", "pps", "ppsx", "ppsm", "pot",
        "potx", "potm", "dps", "dpt", "odp", "otp", "pdf", "png", "jpeg",
        "gif", "webp", "bmp", "tiff", "mp3", "wav", "m4a", "aac", "flac",
        "ogg", "opus", "mp4", "mov", "avi", "zip", "rar", "7z", "tar",
        "gz", "tgz", "bz2", "xz", "epub", "text",
    }
    return normalized if normalized in exact else None


def _detect_artifact_format(raw: bytes) -> str | None:
    """Detect common persisted formats from bytes, never from names or MIME."""
    if not raw:
        return None
    if raw.startswith(b"%PDF-"):
        return "pdf"
    if raw.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return "legacy_office"
    if raw.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = {name.replace("\\", "/").lstrip("/") for name in archive.namelist()}
                if "[Content_Types].xml" in names:
                    content_types = archive.read("[Content_Types].xml").lower()
                    if any(name.startswith("word/") for name in names):
                        if b"macroenabled" in content_types:
                            return "dotm" if b"template" in content_types else "docm"
                        return "dotx" if b"template.main+xml" in content_types else "docx"
                    if any(name.startswith("xl/") for name in names):
                        if b"macroenabled" in content_types:
                            return "xltm" if b"template" in content_types else "xlsm"
                        return "xltx" if b"template.main+xml" in content_types else "xlsx"
                    if any(name.startswith("ppt/") for name in names):
                        macro = b"macroenabled" in content_types
                        if b"slideshow" in content_types:
                            return "ppsm" if macro else "ppsx"
                        if b"template" in content_types:
                            return "potm" if macro else "potx"
                        return "pptm" if macro else "pptx"
                if "mimetype" in names:
                    mime = archive.read("mimetype")[:256].decode("ascii", errors="ignore")
                    if mime == "application/vnd.oasis.opendocument.text":
                        return "odt"
                    if mime == "application/vnd.oasis.opendocument.text-template":
                        return "ott"
                    if mime == "application/vnd.oasis.opendocument.spreadsheet":
                        return "ods"
                    if mime == "application/vnd.oasis.opendocument.spreadsheet-template":
                        return "ots"
                    if mime == "application/vnd.oasis.opendocument.presentation":
                        return "odp"
                    if mime == "application/vnd.oasis.opendocument.presentation-template":
                        return "otp"
                    if mime == "application/epub+zip":
                        return "epub"
        except (KeyError, OSError, zipfile.BadZipFile):
            return None
        return "zip"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "webp"
    if raw.startswith(b"BM"):
        return "bmp"
    if raw.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WAVE":
        return "wav"
    if raw.startswith(b"ID3"):
        return "mp3"
    if raw.startswith(b"OggS"):
        return "ogg"
    if raw.startswith(b"fLaC"):
        return "flac"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "text"


async def file_snapshot_at_version(
    db: AsyncSession,
    file: WorkspaceFile,
    version_id: UUID | None,
):
    """Return a file-shaped immutable snapshot without changing its stable ID.

    The storage VersionId is retained in both the version row and metadata so
    every historical preview/download path can pin the exact OSS object
    generation instead of silently reading the current object.
    """
    if version_id is None:
        return file, None
    version = await db.get(WorkspaceFileVersion, version_id)
    if version is None or str(version.workspace_file_id) != str(file.id):
        raise WorkspaceFileVersionNotFound("文件版本不存在")
    metadata = dict(version.metadata_ or {})
    if version.storage_version_id:
        metadata["storage_version_id"] = str(version.storage_version_id)
    if version.storage_etag:
        metadata["etag"] = str(version.storage_etag)
    return SimpleNamespace(
        id=file.id,
        workspace_id=file.workspace_id,
        path=file.path,
        size=version.size,
        content_hash=version.content_hash,
        content_ref=version.content_ref,
        content=version.content,
        extracted_text=version.extracted_text,
        parse_status=version.parse_status,
        parse_kind=version.parse_kind,
        parse_error=version.parse_error,
        metadata_=metadata,
        current_version_id=version.id,
        created_at=file.created_at,
        updated_at=version.created_at,
        is_historical=str(version.id) != str(file.current_version_id),
    ), version


def storage_version_id(
    file,
    version: WorkspaceFileVersion | None = None,
) -> str | None:
    """Resolve the exact OSS VersionId represented by a file/snapshot."""
    if version is not None and version.storage_version_id:
        return str(version.storage_version_id)
    return str((file.metadata_ or {}).get("storage_version_id") or "") or None


async def _active_office_room(
    db: AsyncSession,
    file_id: UUID | str,
) -> OfficeEditRoom | None:
    now = datetime.now(UTC)
    return (await db.execute(select(OfficeEditRoom).where(
        OfficeEditRoom.workspace_file_id == file_id,
        OfficeEditRoom.status.in_(("open", "closing")),
        OfficeEditRoom.expires_at > now,
    ).order_by(OfficeEditRoom.created_at.desc()).limit(1))).scalar_one_or_none()


async def assert_no_active_office_room(
    db: AsyncSession,
    file: WorkspaceFile,
) -> None:
    """Protect an active collaborative OSS object from out-of-band writes."""
    room = await _active_office_room(db, file.id)
    if room is not None:
        raise WorkspaceFileActiveEditConflict(
            "文件正在 WebOffice 协同编辑，不能静默覆盖",
            room_id=room.id,
            current_version_id=file.current_version_id,
        )


async def enqueue_file_event(
    db: AsyncSession,
    file: WorkspaceFile,
    *,
    event_type: str,
    version_id: UUID | str | None = None,
) -> None:
    """Append an ID-only event in the same transaction as the mutation."""
    organization_id = await db.scalar(select(Workspace.organization_id).where(
        Workspace.id == file.workspace_id,
    ))
    if organization_id is None:
        return
    db.add(WorkspaceFileEventOutbox(
        organization_id=organization_id,
        workspace_id=file.workspace_id,
        workspace_file_id=file.id,
        version_id=version_id,
        event_type=event_type,
    ))


def _stable_request_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")).hexdigest()


async def begin_file_mutation(
    db: AsyncSession,
    *,
    workspace: Workspace,
    file: WorkspaceFile | None,
    actor_type: str,
    actor_id: str,
    operation: str,
    idempotency_key: str,
    payload: dict,
    base_version_id: UUID | str | None = None,
) -> tuple[WorkspaceFileMutation, bool]:
    """Claim a durable actor-scoped mutation key in the caller transaction."""
    request_hash = _stable_request_hash({"operation": operation, **payload})
    lookup = select(WorkspaceFileMutation).where(
        WorkspaceFileMutation.organization_id == workspace.organization_id,
        WorkspaceFileMutation.actor_type == actor_type,
        WorkspaceFileMutation.actor_id == str(actor_id),
        WorkspaceFileMutation.idempotency_key == idempotency_key,
    ).with_for_update()
    existing = (await db.execute(lookup)).scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != request_hash or existing.operation != operation:
            raise WorkspaceFileIdempotencyConflict("幂等键已用于不同的文件修改")
        if existing.status != "completed":
            raise WorkspaceFileIdempotencyConflict("相同幂等操作仍在处理中，请稍后重试")
        return existing, True
    try:
        # The unique actor/key index is the final arbiter.  A savepoint keeps a
        # concurrent insert race from invalidating the caller's transaction so
        # we can safely read and replay the winner instead of returning 500.
        async with db.begin_nested():
            mutation = WorkspaceFileMutation(
                organization_id=workspace.organization_id,
                workspace_id=workspace.id,
                workspace_file_id=file.id if file is not None else None,
                actor_type=actor_type,
                actor_id=str(actor_id),
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                base_version_id=base_version_id,
                status="pending",
                result={},
            )
            db.add(mutation)
            await db.flush()
    except IntegrityError:
        existing = (await db.execute(lookup)).scalar_one_or_none()
        if existing is None:
            raise WorkspaceFileIdempotencyConflict("幂等操作竞争，请重试") from None
        if existing.request_hash != request_hash or existing.operation != operation:
            raise WorkspaceFileIdempotencyConflict("幂等键已用于不同的文件修改") from None
        if existing.status != "completed":
            raise WorkspaceFileIdempotencyConflict("相同幂等操作仍在处理中，请稍后重试") from None
        return existing, True
    return mutation, False


async def complete_file_mutation(
    db: AsyncSession,
    mutation: WorkspaceFileMutation,
    *,
    result_file: WorkspaceFile | None,
    result: dict | None = None,
) -> None:
    mutation.status = "completed"
    mutation.result_file_id = result_file.id if result_file is not None else None
    mutation.result_version_id = (
        result_file.current_version_id if result_file is not None else None
    )
    mutation.result = dict(result or {})
    await db.flush()


async def upsert_file(
    db: AsyncSession,
    ws: Workspace,
    data: WorkspaceFileCreate,
    *,
    content_ref: str | None = None,
    raw_size: int | None = None,
    raw_content_hash: str | None = None,
    created_by_user_id: str | UUID | None = None,
    created_by_admin_id: int | None = None,
) -> WorkspaceFile:
    path = _normalize_path(data.path)
    content = _sanitize_content(data.content)
    meta = enrich_metadata(path, dict(data.metadata or {}), created_at=datetime.now(UTC))
    if raw_size is None and content_ref is None:
        _assert_plain_text_create_supported(path, meta)
    # 二进制文件：前端以 base64 编码写入 content，并以 metadata.binary 标记。
    # size / content_hash 按解码后的原始字节计算，content 列存 base64 文本（PG TEXT 不允许 NUL）。
    if meta.get("binary") and raw_size is not None:
        size = raw_size
        content_hash = raw_content_hash
    elif meta.get("binary"):
        try:
            raw = base64.b64decode(content, validate=False)
        except ValueError:  # binascii.Error 是 ValueError 子类
            raw = b""
        size = len(raw)
        content_hash = hashlib.sha256(raw).hexdigest()
    else:
        content_bytes = content.encode("utf-8")
        size = len(content_bytes)
        content_hash = hashlib.sha256(content_bytes).hexdigest()
    parse_status = "unparsed" if meta.get("binary") else "ready"
    parse_kind = None if meta.get("binary") else "text"
    # A deleted generation is deliberately excluded.  Historical task refs
    # remain bound to its old UUID and must never start pointing at a later
    # upload that merely reuses the same human path.
    result = await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == ws.id,
            WorkspaceFile.path == path,
            WorkspaceFile.deleted_at.is_(None),
        ).with_for_update()
    )
    f = result.scalar_one_or_none()
    if f is not None:
        raise WorkspaceFilePathConflict(f)
    f = WorkspaceFile(
        workspace_id=ws.id,
        path=path,
        size=size,
        content_hash=content_hash,
        content=content,
        content_ref=content_ref or path,
        parse_status=parse_status,
        parse_kind=parse_kind,
        metadata_=meta,
        created_by_user_id=created_by_user_id,
    )
    try:
        # The preflight lookup gives a useful conflict immediately, while the
        # partial unique index remains authoritative for two concurrent
        # creators.  Isolate a losing insert in a SAVEPOINT so callers can
        # still resolve the winning logical file and return a clean 409.
        async with db.begin_nested():
            db.add(f)
            await db.flush()
    except IntegrityError:
        collision = (await db.execute(select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == ws.id,
            WorkspaceFile.path == path,
            WorkspaceFile.deleted_at.is_(None),
        ))).scalar_one_or_none()
        if collision is not None:
            raise WorkspaceFilePathConflict(collision) from None
        raise
    await create_file_version(
        db, f, created_by_user_id=created_by_user_id, created_by_admin_id=created_by_admin_id,
    )
    await db.refresh(f)
    return f


async def create_file_version(
    db: AsyncSession,
    f: WorkspaceFile,
    *,
    created_by_user_id: str | UUID | None = None,
    created_by_admin_id: int | None = None,
    mutation_idempotency_key: str | None = None,
    mutation_request_hash: str | None = None,
) -> WorkspaceFileVersion:
    latest = int((await db.execute(select(func.coalesce(func.max(WorkspaceFileVersion.version_no), 0)).where(
        WorkspaceFileVersion.workspace_file_id == f.id,
    ))).scalar_one())
    version = WorkspaceFileVersion(
        workspace_file_id=f.id,
        version_no=latest + 1,
        mutation_idempotency_key=mutation_idempotency_key,
        mutation_request_hash=mutation_request_hash,
        storage_version_id=str((f.metadata_ or {}).get("storage_version_id") or "") or None,
        storage_etag=str((f.metadata_ or {}).get("etag") or "") or None,
        size=f.size,
        content_hash=f.content_hash,
        content_ref=f.content_ref,
        content=f.content,
        extracted_text=f.extracted_text,
        parse_status=f.parse_status,
        parse_kind=f.parse_kind,
        parse_error=f.parse_error,
        metadata_=dict(f.metadata_ or {}),
        created_by_user_id=created_by_user_id,
        created_by_admin_id=created_by_admin_id,
    )
    db.add(version)
    await db.flush()
    f.current_version_id = version.id
    # Non-persistent response metadata: distinguishes this mutation's exact
    # result from a newer current version when an old idempotency key replays.
    setattr(f, "mutation_result_version_id", version.id)
    await enqueue_file_event(
        db,
        f,
        event_type="version_created",
        version_id=version.id,
    )
    await db.flush()
    return version


async def sync_current_version(db: AsyncSession, f: WorkspaceFile) -> None:
    if not f.current_version_id:
        return
    version = await db.get(WorkspaceFileVersion, f.current_version_id)
    if version is None:
        return
    version.extracted_text = f.extracted_text
    version.parse_status = f.parse_status
    version.parse_kind = f.parse_kind
    version.parse_error = f.parse_error
    version.metadata_ = dict(f.metadata_ or {})
    await db.flush()


async def list_files(db: AsyncSession, ws_id: UUID) -> list[WorkspaceFile]:
    """List lightweight ORM rows for internal callers.

    The Base64 payload and parsed text are intentionally deferred.  Internal
    callers need identifiers/paths and may inspect the lightweight metadata
    (for example ``is_binary`` in the terminal-wide file picker).
    """
    result = await db.execute(
        select(WorkspaceFile).options(load_only(
            WorkspaceFile.id,
            WorkspaceFile.workspace_id,
            WorkspaceFile.path,
            WorkspaceFile.size,
            WorkspaceFile.content_hash,
            WorkspaceFile.content_ref,
            WorkspaceFile.metadata_,
            WorkspaceFile.parse_status,
            WorkspaceFile.parse_kind,
            WorkspaceFile.parse_error,
            WorkspaceFile.created_at,
            WorkspaceFile.updated_at,
            WorkspaceFile.current_version_id,
        )).where(
            WorkspaceFile.workspace_id == ws_id, WorkspaceFile.deleted_at.is_(None)
        ).order_by(WorkspaceFile.path)
    )
    return list(result.scalars().all())


def _file_list_item(f: WorkspaceFile) -> WorkspaceFileListItem:
    meta = f.metadata_ or {}
    original_filename = clean_display_name(f.path, meta)
    mime_type = str(meta.get("mime") or mimetypes.guess_type(original_filename)[0] or "") or None
    return WorkspaceFileListItem(
        id=f.id,
        workspace_id=f.workspace_id,
        path=f.path,
        original_filename=original_filename,
        size=f.size,
        mime_type=mime_type,
        is_binary=bool(meta.get("binary")),
        content_hash=f.content_hash,
        current_version_id=f.current_version_id,
        office_edit_enabled=office_edit_enabled(f, can_update=True),
        parse_status=f.parse_status,
        parse_kind=f.parse_kind,
        parse_error=f.parse_error,
        created_at=f.created_at,
        updated_at=f.updated_at,
        presentation=presentation_dict(f.path, meta, created_at=f.created_at),
    )


async def list_files_page(
    db: AsyncSession,
    ws_id: UUID,
    *,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[WorkspaceFileListItem], int]:
    """Return a page of file summaries without loading content columns."""
    filters = (WorkspaceFile.workspace_id == ws_id, WorkspaceFile.deleted_at.is_(None))
    total = int((await db.execute(
        select(func.count(WorkspaceFile.id)).where(*filters)
    )).scalar_one())
    result = await db.execute(
        select(WorkspaceFile)
        .options(load_only(
            WorkspaceFile.id,
            WorkspaceFile.workspace_id,
            WorkspaceFile.path,
            WorkspaceFile.size,
            WorkspaceFile.content_hash,
            WorkspaceFile.current_version_id,
            WorkspaceFile.content_ref,
            WorkspaceFile.parse_status,
            WorkspaceFile.parse_kind,
            WorkspaceFile.parse_error,
            WorkspaceFile.metadata_,
            WorkspaceFile.created_at,
            WorkspaceFile.updated_at,
        ))
        .where(*filters)
        .order_by(WorkspaceFile.path)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [_file_list_item(f) for f in result.scalars().all()], total


async def search_files(
    db: AsyncSession,
    workspace_ids: list[UUID] | tuple[UUID, ...],
    *,
    query: str = "",
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[WorkspaceFile], bool]:
    """Search a live authorized workspace set without materialising every file."""
    if not workspace_ids:
        return [], False
    filters = [
        WorkspaceFile.workspace_id.in_(workspace_ids),
        WorkspaceFile.deleted_at.is_(None),
    ]
    needle = unicodedata.normalize("NFC", query).strip()
    if needle:
        escaped_needle = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_needle}%"
        filters.append(or_(
            WorkspaceFile.path.ilike(pattern, escape="\\"),
            WorkspaceFile.metadata_["name"].as_string().ilike(pattern, escape="\\"),
        ))
    page_size = min(500, max(1, int(limit)))
    page_offset = max(0, int(offset))
    result = await db.execute(
        select(WorkspaceFile)
        .options(load_only(
            WorkspaceFile.id,
            WorkspaceFile.workspace_id,
            WorkspaceFile.path,
            WorkspaceFile.size,
            WorkspaceFile.content_hash,
            WorkspaceFile.current_version_id,
            WorkspaceFile.content_ref,
            WorkspaceFile.metadata_,
            WorkspaceFile.parse_status,
            WorkspaceFile.parse_kind,
            WorkspaceFile.parse_error,
            WorkspaceFile.created_at,
            WorkspaceFile.updated_at,
        ))
        .where(*filters)
        .order_by(WorkspaceFile.workspace_id, WorkspaceFile.path, WorkspaceFile.id)
        .offset(page_offset)
        .limit(page_size + 1)
    )
    rows = list(result.scalars().all())
    return rows[:page_size], len(rows) > page_size


async def get_file(db: AsyncSession, file_id: UUID) -> WorkspaceFile | None:
    result = await db.execute(
        select(WorkspaceFile).where(WorkspaceFile.id == file_id, WorkspaceFile.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_file_by_path(db: AsyncSession, ws_id: UUID, path: str) -> WorkspaceFile | None:
    """按 (workspace_id, path) 取文件（path 经规范化）。供智能体内置文件工具使用。"""
    normalized = _normalize_path(path)
    result = await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == ws_id,
            WorkspaceFile.path == normalized,
            WorkspaceFile.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_file_including_deleted(db: AsyncSession, file_id: UUID) -> WorkspaceFile | None:
    return await db.get(WorkspaceFile, file_id)


async def current_version_numbers(
    db: AsyncSession, file_ids: list[UUID] | tuple[UUID, ...],
) -> dict[str, int]:
    """Return current version numbers without loading immutable payload columns."""
    if not file_ids:
        return {}
    rows = await db.execute(
        select(WorkspaceFile.id, WorkspaceFileVersion.version_no)
        .join(WorkspaceFileVersion, WorkspaceFile.current_version_id == WorkspaceFileVersion.id)
        .where(WorkspaceFile.id.in_(file_ids))
    )
    return {str(file_id): int(version_no) for file_id, version_no in rows.all()}


async def version_lineage(
    db: AsyncSession,
    file: WorkspaceFile,
) -> tuple[WorkspaceFileVersion | None, UUID | str | None]:
    """Return the current immutable row and its immediate predecessor ID."""
    if not file.current_version_id:
        return None, None
    current = await db.get(WorkspaceFileVersion, file.current_version_id)
    if current is None:
        return None, None
    previous_id = await db.scalar(
        select(WorkspaceFileVersion.id).where(
            WorkspaceFileVersion.workspace_file_id == file.id,
            WorkspaceFileVersion.version_no < current.version_no,
        ).order_by(WorkspaceFileVersion.version_no.desc()).limit(1)
    )
    return current, previous_id


def _mutation_request_hash(data: WorkspaceFileUpdate) -> str:
    payload = data.model_dump(mode="json", exclude={"idempotency_key"}, exclude_unset=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text_parse_kind(path: str) -> str:
    """Return the lightweight parser kind for user-edited UTF-8 text."""
    suffix = PurePosixPath(path).suffix.casefold()
    return {
        ".csv": "csv",
        ".tsv": "csv",
        ".md": "md",
        ".markdown": "md",
        ".json": "json",
    }.get(suffix, "txt")


async def _upload_verified_text_revision(
    file: WorkspaceFile,
    content: str,
    metadata: dict,
) -> tuple[str, int, str, dict]:
    """Persist one edited text revision as a new verified OSS object.

    Uploaded CSV/TXT files keep their original bytes in OSS.  Reusing the old
    ``content_ref`` after an inline edit makes the database version look new
    while previews and downloads still resolve the old object.  Always create
    a fresh object first and return metadata for the atomic database switch.
    """
    raw = content.encode("utf-8")
    filename = clean_display_name(file.path, metadata) or PurePosixPath(file.path).name
    content_type = str(
        metadata.get("mime")
        or mimetypes.guess_type(filename)[0]
        or "text/plain"
    )
    content_ref: str | None = None
    expected_hash = hashlib.sha256(raw).hexdigest()
    try:
        content_ref = await storage_gateway_service.upload_bytes(
            raw,
            filename=filename,
            content_type=content_type,
        )
        inspected = await storage_gateway_service.inspect_object(content_ref)
        if int(inspected.get("size") or -1) != len(raw):
            raise storage_gateway_service.StorageGatewayError(
                "OSS edited object size verification failed"
            )
        remote_hash = str(inspected.get("content_hash") or "").casefold()
        if remote_hash != expected_hash:
            raise storage_gateway_service.StorageGatewayError(
                "OSS edited object hash verification failed"
            )
    except Exception:
        # The database has not been changed yet.  Best-effort removal avoids
        # leaving a verified-but-unreferenced object when inspection fails.
        if content_ref is not None:
            try:
                await storage_gateway_service.delete_object(content_ref)
            except storage_gateway_service.StorageGatewayError:
                pass
        raise

    updated_metadata = dict(metadata)
    updated_metadata.update({
        "binary": True,
        "mime": content_type,
        "name": filename,
        "storage_backend": "oss_gateway",
    })
    version_id = str(inspected.get("version_id") or "")
    etag = str(inspected.get("etag") or "").strip('"')
    if version_id:
        updated_metadata["storage_version_id"] = version_id
    else:
        updated_metadata.pop("storage_version_id", None)
    if etag:
        updated_metadata["etag"] = etag
    else:
        updated_metadata.pop("etag", None)
    return content_ref, len(raw), expected_hash, updated_metadata


async def update_file(
    db: AsyncSession,
    f: WorkspaceFile,
    data: WorkspaceFileUpdate,
    *,
    created_by_user_id: str | UUID | None = None,
    created_by_admin_id: int | None = None,
) -> WorkspaceFile:
    # Serialize edits to a stable file id.  The lock closes the gap between the
    # base-version check and version creation, preventing two editors from both
    # successfully updating the same base revision.
    locked = (await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.id == f.id,
            WorkspaceFile.deleted_at.is_(None),
        ).with_for_update()
    )).scalar_one_or_none()
    if locked is None:
        raise WorkspaceFileVersionConflict("文件已删除或不可更新")

    request_hash = _mutation_request_hash(data)
    if data.idempotency_key:
        replay = (await db.execute(select(WorkspaceFileVersion).where(
            WorkspaceFileVersion.workspace_file_id == locked.id,
            WorkspaceFileVersion.mutation_idempotency_key == data.idempotency_key,
        ))).scalar_one_or_none()
        if replay is not None:
            if replay.mutation_request_hash != request_hash:
                raise WorkspaceFileIdempotencyConflict("幂等键已用于不同的文件修改")
            # The original mutation already committed. Return the stable file
            # without creating another immutable version.
            setattr(locked, "mutation_result_version_id", replay.id)
            return locked

    await assert_no_active_office_room(db, locked)

    if data.base_version_id is not None and str(locked.current_version_id or "") != str(data.base_version_id):
        raise WorkspaceFileVersionConflict(
            "文件已被其他人更新，请刷新后重试",
            current_version_id=locked.current_version_id,
        )

    metadata = _merge_update_metadata(locked, data.metadata)
    if data.content is not None:
        _assert_plain_text_update_supported(locked)
        content = _sanitize_content(data.content)
        stores_original_in_oss = storage_gateway_service.is_object_ref(locked.content_ref)
        is_legacy_binary_text = bool(metadata.get("binary"))
        if stores_original_in_oss or (
            is_legacy_binary_text
            and settings.workspace_object_storage_enabled
            and settings.workspace_object_storage_configured
        ):
            try:
                content_ref, size, content_hash, metadata = await _upload_verified_text_revision(
                    locked,
                    content,
                    metadata,
                )
            except storage_gateway_service.StorageGatewayError as exc:
                raise WorkspaceFileUploadError(str(exc)) from exc
            locked.content_ref = content_ref
            locked.content = None
            locked.size = size
            locked.content_hash = content_hash
            # Keep a bounded, directly readable representation for the Agent;
            # the authoritative downloadable bytes remain the new OSS object.
            locked.extracted_text = content
            locked.parse_kind = _text_parse_kind(locked.path)
        else:
            raw = content.encode("utf-8")
            locked.content_ref = None
            locked.content = content
            locked.size = len(raw)
            locked.content_hash = hashlib.sha256(raw).hexdigest()
            locked.extracted_text = None
            locked.parse_kind = _text_parse_kind(locked.path)
            # Plain inline text must never retain the legacy Base64 marker or
            # it will be decoded as binary on the next preview/download.
            metadata.pop("binary", None)
            metadata.pop("storage_backend", None)
            metadata.pop("storage_version_id", None)
            metadata.pop("etag", None)
        locked.parse_status = "ready"
        locked.parse_error = None
    locked.metadata_ = metadata
    await db.flush()
    await create_file_version(
        db,
        locked,
        created_by_user_id=created_by_user_id,
        created_by_admin_id=created_by_admin_id,
        mutation_idempotency_key=data.idempotency_key,
        mutation_request_hash=request_hash if data.idempotency_key else None,
    )
    await db.refresh(locked)
    return locked


async def replace_file_artifact(
    db: AsyncSession,
    f: WorkspaceFile,
    *,
    content: str | None,
    content_ref: str | None,
    size: int,
    content_hash: str | None,
    metadata: dict,
    parse_status: str,
    parse_kind: str | None,
    base_version_id: UUID,
    idempotency_key: str,
    expected_workspace_id: UUID | str | None = None,
    expected_path: str | None = None,
    created_by_user_id: str | UUID | None = None,
    created_by_admin_id: int | None = None,
) -> WorkspaceFile:
    """Atomically replace one stable file with a Runner-verified artifact."""
    locked = (await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.id == f.id,
            WorkspaceFile.deleted_at.is_(None),
        ).with_for_update()
    )).scalar_one_or_none()
    if locked is None:
        raise WorkspaceFileVersionConflict("文件已删除或不可更新")
    if expected_workspace_id is not None and str(locked.workspace_id) != str(expected_workspace_id):
        raise WorkspaceFileVersionConflict(
            "文件已被移动，请刷新后重试", current_version_id=locked.current_version_id,
        )
    if expected_path is not None and locked.path != _normalize_path(expected_path):
        raise WorkspaceFileVersionConflict(
            "文件路径已变化，请刷新后重试", current_version_id=locked.current_version_id,
        )
    request_hash = hashlib.sha256(json.dumps({
        "operation": "replace_artifact",
        "base_version_id": str(base_version_id),
        "content_ref": content_ref,
        "size": int(size),
        "content_hash": content_hash,
        "inline_hash": hashlib.sha256((content or "").encode("utf-8")).hexdigest(),
        "metadata": metadata,
        "parse_status": parse_status,
        "parse_kind": parse_kind,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    replay = (await db.execute(select(WorkspaceFileVersion).where(
        WorkspaceFileVersion.workspace_file_id == locked.id,
        WorkspaceFileVersion.mutation_idempotency_key == idempotency_key,
    ))).scalar_one_or_none()
    if replay is not None:
        if replay.mutation_request_hash != request_hash:
            raise WorkspaceFileIdempotencyConflict("幂等键已用于不同的文件修改")
        setattr(locked, "mutation_result_version_id", replay.id)
        return locked
    _assert_artifact_replacement_compatible(
        locked, metadata, content=content, content_ref=content_ref,
    )
    await assert_no_active_office_room(db, locked)
    if str(locked.current_version_id or "") != str(base_version_id):
        raise WorkspaceFileVersionConflict(
            "文件已被其他人更新，请刷新后重试",
            current_version_id=locked.current_version_id,
        )

    locked.content = _sanitize_content(content) if content is not None else None
    locked.content_ref = content_ref
    locked.size = int(size)
    locked.content_hash = content_hash
    locked.extracted_text = None
    locked.parse_status = parse_status
    locked.parse_kind = parse_kind
    locked.parse_error = None
    locked.metadata_ = dict(metadata)
    await db.flush()
    await create_file_version(
        db,
        locked,
        created_by_user_id=created_by_user_id,
        created_by_admin_id=created_by_admin_id,
        mutation_idempotency_key=idempotency_key,
        mutation_request_hash=request_hash,
    )
    await db.refresh(locked)
    return locked


async def move_file(
    db: AsyncSession,
    f: WorkspaceFile,
    target_path: str,
    *,
    base_version_id: UUID,
    idempotency_key: str,
    target_workspace: Workspace | None = None,
    rename_to: str | None = None,
    created_by_user_id: str | UUID | None = None,
    created_by_admin_id: int | None = None,
) -> WorkspaceFile:
    """Move one logical file, optionally across workspaces, preserving UUID/history."""
    rename_name: str | None = None
    if rename_to is not None:
        rename_name = PurePosixPath(str(rename_to)).name
        if not rename_name or rename_name in {".", ".."}:
            raise ValueError("文件名无效")
    else:
        path = _normalize_path(target_path)
        if not path:
            raise ValueError("目标路径不能为空")
    locked = (await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.id == f.id,
            WorkspaceFile.deleted_at.is_(None),
        ).with_for_update()
    )).scalar_one_or_none()
    if locked is None:
        raise WorkspaceFileVersionConflict("文件已删除或不可更新")
    destination = target_workspace or await db.get(Workspace, locked.workspace_id)
    if destination is None or destination.deleted_at is not None:
        raise ValueError("目标工作空间不存在")
    source_workspace = await db.get(Workspace, locked.workspace_id)
    if source_workspace is None or source_workspace.organization_id != destination.organization_id:
        raise ValueError("不能跨企业移动文件")
    if rename_name is not None:
        if str(destination.id) != str(locked.workspace_id):
            raise ValueError("重命名不能同时跨工作空间移动")
        # Derive the directory only after locking the current row.  More
        # importantly, the request identity below is the semantic new name,
        # not a path derived by the API from mutable live state.  Retrying a
        # successful rename after a later move therefore replays cleanly.
        path = str(PurePosixPath(locked.path).with_name(rename_name))
    request_hash = hashlib.sha256(json.dumps({
        "operation": "rename" if rename_name is not None else "move",
        **(
            {"new_name": rename_name}
            if rename_name is not None
            else {
                "target_workspace_id": str(destination.id),
                "target_path": path,
            }
        ),
        "base_version_id": str(base_version_id),
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    replay = (await db.execute(select(WorkspaceFileVersion).where(
        WorkspaceFileVersion.workspace_file_id == locked.id,
        WorkspaceFileVersion.mutation_idempotency_key == idempotency_key,
    ))).scalar_one_or_none()
    if replay is not None:
        if replay.mutation_request_hash != request_hash:
            raise WorkspaceFileIdempotencyConflict("幂等键已用于不同的文件修改")
        setattr(locked, "mutation_result_version_id", replay.id)
        return locked
    await assert_no_active_office_room(db, locked)
    if str(locked.current_version_id or "") != str(base_version_id):
        raise WorkspaceFileVersionConflict(
            "文件已被其他人更新，请刷新后重试",
            current_version_id=locked.current_version_id,
        )
    collision = (await db.execute(select(WorkspaceFile.id).where(
        WorkspaceFile.workspace_id == destination.id,
        WorkspaceFile.path == path,
        WorkspaceFile.id != locked.id,
        WorkspaceFile.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if collision is not None:
        raise ValueError("目标路径已存在文件")
    try:
        async with db.begin_nested():
            if str(locked.workspace_id) != str(destination.id):
                # Emit the departure while the row still points at the source.
                await enqueue_file_event(
                    db, locked, event_type="file_moved_out",
                    version_id=locked.current_version_id,
                )
                locked.workspace_id = destination.id
            locked.path = path
            metadata = dict(locked.metadata_ or {})
            if metadata.get("name"):
                metadata["name"] = PurePosixPath(path).name
            locked.metadata_ = metadata
            await db.flush()
    except IntegrityError:
        await db.refresh(locked)
        collision = await get_file_by_path(db, destination.id, path)
        if collision is not None and str(collision.id) != str(locked.id):
            raise WorkspaceFilePathConflict(collision) from None
        raise ValueError("目标路径并发冲突，请刷新后重试") from None
    await create_file_version(
        db,
        locked,
        created_by_user_id=created_by_user_id,
        created_by_admin_id=created_by_admin_id,
        mutation_idempotency_key=idempotency_key,
        mutation_request_hash=request_hash,
    )
    await db.refresh(locked)
    return locked


async def copy_file(
    db: AsyncSession,
    source: WorkspaceFile,
    target_workspace: Workspace,
    target_path: str,
    *,
    base_version_id: UUID,
    idempotency_key: str,
    actor_type: str,
    actor_id: str | UUID | int,
    created_by_user_id: str | UUID | None = None,
    created_by_admin_id: int | None = None,
) -> WorkspaceFile:
    """Copy the persisted source revision to a new stable logical file."""
    path = _normalize_path(target_path)
    locked = (await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.id == source.id,
        WorkspaceFile.deleted_at.is_(None),
    ).with_for_update())).scalar_one_or_none()
    if locked is None:
        raise WorkspaceFileVersionConflict("源文件已删除或不可复制")
    mutation, replayed = await begin_file_mutation(
        db,
        workspace=target_workspace,
        file=locked,
        actor_type=actor_type,
        actor_id=str(actor_id),
        operation="copy",
        idempotency_key=idempotency_key,
        base_version_id=base_version_id,
        payload={
            "source_file_id": str(locked.id),
            "target_workspace_id": str(target_workspace.id),
            "target_path": path,
            "base_version_id": str(base_version_id),
        },
    )
    if replayed:
        live_result = await get_file(db, mutation.result_file_id) if mutation.result_file_id else None
        result_version = (
            await db.get(WorkspaceFileVersion, mutation.result_version_id)
            if mutation.result_version_id else None
        )
        original_workspace = await get_workspace(db, UUID(str(mutation.workspace_id)))
        if (
            live_result is None
            or result_version is None
            or original_workspace is None
            or str(result_version.workspace_file_id) != str(live_result.id)
        ):
            raise WorkspaceFileVersionConflict("幂等复制结果已不可用")
        result, _ = await file_snapshot_at_version(db, live_result, result_version.id)
        result.workspace_id = original_workspace.id
        result.path = str((mutation.result or {}).get("target_path") or path)
        result.metadata_ = dict(result.metadata_ or {})
        result.metadata_["name"] = PurePosixPath(result.path).name
        result.current_version_id = result_version.id
        result.is_mutation_replay = True
        result.mutation_result_version_id = result_version.id
        # Authorize a replay against the result's real current workspace, but
        # never serialize that later location as the original copy result.
        result.mutation_result_live_workspace_id = live_result.workspace_id
        return result
    if str(locked.current_version_id or "") != str(base_version_id):
        # Expected conflicts are returned as structured Agent results.  Remove
        # the just-created claim before raising so the surrounding tool
        # transaction cannot accidentally commit a permanently pending key.
        await db.delete(mutation)
        await db.flush()
        raise WorkspaceFileVersionConflict(
            "源文件已被更新，请刷新后重试",
            current_version_id=locked.current_version_id,
        )
    if await get_file_by_path(db, target_workspace.id, path) is not None:
        await db.delete(mutation)
        await db.flush()
        raise ValueError("目标路径已存在文件")
    try:
        copied = await upsert_file(
            db,
            target_workspace,
            WorkspaceFileCreate(
                path=path,
                content=locked.content or "",
                metadata={
                    **dict(locked.metadata_ or {}),
                    "name": PurePosixPath(path).name,
                },
            ),
            content_ref=locked.content_ref,
            raw_size=locked.size,
            raw_content_hash=locked.content_hash,
            created_by_user_id=created_by_user_id,
            created_by_admin_id=created_by_admin_id,
        )
    except (WorkspaceFilePathConflict, IntegrityError):
        await db.delete(mutation)
        await db.flush()
        raise
    copied.extracted_text = locked.extracted_text
    copied.parse_status = locked.parse_status
    copied.parse_kind = locked.parse_kind
    copied.parse_error = locked.parse_error
    await sync_current_version(db, copied)
    await complete_file_mutation(
        db,
        mutation,
        result_file=copied,
        result={
            "source_file_id": str(locked.id),
            "target_file_id": str(copied.id),
            "target_workspace_id": str(target_workspace.id),
            "target_path": path,
        },
    )
    await db.refresh(copied)
    return copied


async def restore_file_version(
    db: AsyncSession,
    f: WorkspaceFile,
    version: WorkspaceFileVersion,
    *,
    base_version_id: UUID,
    idempotency_key: str,
    created_by_user_id: str | UUID | None = None,
    created_by_admin_id: int | None = None,
) -> WorkspaceFile:
    """Restore an immutable version with optimistic concurrency and replay safety."""
    locked = (await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.id == f.id,
            WorkspaceFile.deleted_at.is_(None),
        ).with_for_update()
    )).scalar_one_or_none()
    if locked is None or str(version.workspace_file_id) != str(f.id):
        raise WorkspaceFileVersionConflict("文件版本不存在或文件已删除")
    request_hash = hashlib.sha256(json.dumps({
        "operation": "restore",
        "version_id": str(version.id),
        "base_version_id": str(base_version_id),
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    replay = (await db.execute(select(WorkspaceFileVersion).where(
        WorkspaceFileVersion.workspace_file_id == locked.id,
        WorkspaceFileVersion.mutation_idempotency_key == idempotency_key,
    ))).scalar_one_or_none()
    if replay is not None:
        if replay.mutation_request_hash != request_hash:
            raise WorkspaceFileIdempotencyConflict("幂等键已用于不同的文件修改")
        setattr(locked, "mutation_result_version_id", replay.id)
        return locked
    await assert_no_active_office_room(db, locked)
    if str(locked.current_version_id or "") != str(base_version_id):
        raise WorkspaceFileVersionConflict(
            "文件已被其他人更新，请刷新后重试",
            current_version_id=locked.current_version_id,
        )
    for field in (
        "size", "content_hash", "content_ref", "content", "extracted_text",
        "parse_status", "parse_kind", "parse_error", "metadata_",
    ):
        setattr(locked, field, getattr(version, field))
    await db.flush()
    await create_file_version(
        db,
        locked,
        created_by_user_id=created_by_user_id,
        created_by_admin_id=created_by_admin_id,
        mutation_idempotency_key=idempotency_key,
        mutation_request_hash=request_hash,
    )
    await db.refresh(locked)
    return locked


async def _mark_files_deleted_locked(
    db: AsyncSession,
    files: list[WorkspaceFile],
    *,
    user_id: str | UUID | None = None,
    admin_id: int | None = None,
    now: datetime | None = None,
) -> None:
    """Delete already row-locked files without bypassing active edit rooms.

    Every bulk/folder/task cleanup path uses this helper.  Callers acquire all
    logical-file row locks before this check; WebOffice room creation takes the
    same file lock, so it cannot slip between the active-room check and the
    tombstone write.
    """
    if not files:
        return
    for file in files:
        await assert_no_active_office_room(db, file)
    deleted_at = now or datetime.now(UTC)
    for file in files:
        mark_deleted(file, now=deleted_at)
        file.deleted_by_user_id = user_id
        file.deleted_by_admin_id = admin_id
        await enqueue_file_event(
            db,
            file,
            event_type="file_deleted",
            version_id=file.current_version_id,
        )


async def soft_delete_file_generations(
    db: AsyncSession,
    generations: dict[UUID, UUID],
) -> list[WorkspaceFile]:
    """Safely delete only task-owned file generations that are still current."""
    if not generations:
        return []
    rows = list((await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.id.in_(tuple(generations)),
        WorkspaceFile.deleted_at.is_(None),
    ).order_by(WorkspaceFile.id).with_for_update())).scalars().all())
    eligible = [
        file for file in rows
        if str(file.current_version_id or "") == str(generations.get(UUID(str(file.id))) or "")
    ]
    await _mark_files_deleted_locked(db, eligible)
    if eligible:
        await db.flush()
    return eligible


async def soft_delete_file(
    db: AsyncSession,
    f: WorkspaceFile,
    *,
    user_id: str | UUID | None = None,
    admin_id: int | None = None,
    base_version_id: UUID | None = None,
    idempotency_key: str | None = None,
    mutation_actor_type: str | None = None,
    mutation_actor_id: str | None = None,
) -> None:
    locked = (await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.id == f.id,
    ).with_for_update())).scalar_one_or_none()
    if locked is None:
        return
    mutation = None
    if idempotency_key:
        actor_type = mutation_actor_type or ("user" if user_id is not None else "admin")
        actor_id = mutation_actor_id or (user_id if user_id is not None else admin_id)
        if actor_id is None:
            raise ValueError("幂等删除缺少操作者")
        workspace = await get_workspace(db, locked.workspace_id)
        if workspace is None:
            raise WorkspaceFileVersionConflict("工作空间已删除")
        mutation, replayed = await begin_file_mutation(
            db,
            workspace=workspace,
            file=locked,
            actor_type=actor_type,
            actor_id=str(actor_id),
            operation="delete",
            idempotency_key=idempotency_key,
            base_version_id=base_version_id,
            payload={
                "file_id": str(locked.id),
                "base_version_id": str(base_version_id or ""),
            },
        )
        if replayed:
            return
    if locked.deleted_at is not None:
        if mutation is not None:
            await db.delete(mutation)
            await db.flush()
        raise WorkspaceFileVersionConflict("文件已删除")
    if base_version_id is not None and str(locked.current_version_id or "") != str(base_version_id):
        if mutation is not None:
            await db.delete(mutation)
            await db.flush()
        raise WorkspaceFileVersionConflict(
            "文件已被其他人更新，请刷新后重试",
            current_version_id=locked.current_version_id,
        )
    try:
        await assert_no_active_office_room(db, locked)
    except WorkspaceFileActiveEditConflict:
        if mutation is not None:
            await db.delete(mutation)
            await db.flush()
        raise
    mark_deleted(locked)
    locked.deleted_by_user_id = user_id
    locked.deleted_by_admin_id = admin_id
    await enqueue_file_event(
        db,
        locked,
        event_type="file_deleted",
        version_id=locked.current_version_id,
    )
    if mutation is not None:
        await complete_file_mutation(
            db,
            mutation,
            result_file=locked,
            result={"file_id": str(locked.id), "deleted": True},
        )
    await db.flush()


async def ingest_uploaded_file(
    db: AsyncSession,
    ws: Workspace,
    *,
    path: str,
    filename: str,
    content_type: str | None,
    raw: bytes,
    created_by_user_id: str | UUID | None = None,
    created_by_admin_id: int | None = None,
) -> WorkspaceFile:
    """Store an original file and queue binary parsing outside the request."""
    if not raw:
        raise WorkspaceFileUploadError("文件为空")
    if len(raw) > MAX_WORKSPACE_FILE_BYTES:
        raise WorkspaceFileUploadError(
            f"文件过大（{len(raw)} 字节），上限 {MAX_WORKSPACE_FILE_BYTES // (1024 * 1024)}MB"
        )
    mime = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    digest = hashlib.sha256(raw).hexdigest()
    content_ref: str | None = None
    metadata = {"binary": True, "mime": mime, "name": filename}
    if settings.workspace_object_storage_enabled:
        if not settings.workspace_object_storage_configured:
            raise WorkspaceFileUploadError("对象存储已启用，但存储网关配置不完整")
        try:
            content_ref = await storage_gateway_service.upload_bytes(
                raw, filename=filename, content_type=mime,
            )
        except storage_gateway_service.StorageGatewayError as exc:
            raise WorkspaceFileUploadError(str(exc)) from exc
        encoded = ""
        metadata["storage_backend"] = "oss_gateway"
    else:
        encoded = base64.b64encode(raw).decode("ascii")
        metadata["storage_backend"] = "postgres_base64"
    try:
        f = await upsert_file(
            db,
            ws,
            WorkspaceFileCreate(path=path, content=encoded, metadata=metadata),
            content_ref=content_ref,
            raw_size=len(raw),
            raw_content_hash=digest,
            created_by_user_id=created_by_user_id,
            created_by_admin_id=created_by_admin_id,
        )
        if content_ref is not None:
            f.content = None
            await db.flush()
    except Exception:
        if content_ref is not None:
            try:
                await storage_gateway_service.delete_object(content_ref)
            except storage_gateway_service.StorageGatewayError:
                pass
        raise
    # Small uploads preserve the original immediate-availability behaviour.
    # Only direct/large OSS uploads are handed to workspace-parser so a large
    # Office document never occupies a backend request worker for minutes.
    if len(raw) <= settings.workspace_proxy_upload_max_bytes:
        await _parse_binary_file(
            db,
            f,
            filename=filename,
            content_type=content_type,
            raw=raw,
        )
    else:
        f.parse_status = "queued"
        f.parse_kind = None
        f.parse_error = None
        await sync_current_version(db, f)
        await db.flush()
    return f


async def load_file_bytes(f: WorkspaceFile) -> bytes:
    """Load original file bytes from OSS or the legacy PostgreSQL payload."""
    if storage_gateway_service.is_object_ref(f.content_ref):
        try:
            raw = await storage_gateway_service.download_bytes(
                str(f.content_ref),
                version_id=storage_version_id(f),
            )
        except storage_gateway_service.StorageGatewayError as exc:
            raise WorkspaceFileUploadError(str(exc)) from exc
    elif (f.metadata_ or {}).get("binary"):
        try:
            raw = base64.b64decode(f.content or "", validate=False)
        except ValueError as exc:
            raise WorkspaceFileUploadError(f"原文件 Base64 损坏：{exc}") from exc
    else:
        raw = (f.content or "").encode("utf-8")
    if not raw:
        raise WorkspaceFileUploadError("原文件为空")
    if f.content_hash and hashlib.sha256(raw).hexdigest() != f.content_hash:
        raise WorkspaceFileUploadError("原文件完整性校验失败")
    return raw


async def reparse_file(db: AsyncSession, f: WorkspaceFile) -> WorkspaceFile:
    """重新解析历史二进制工作空间文件；原始内容不变。"""
    if not (f.metadata_ or {}).get("binary"):
        f.parse_status = "ready"
        f.parse_kind = "text"
        f.parse_error = None
        f.extracted_text = None
        await db.flush()
        await db.refresh(f)
        return f
    f.parse_status = "queued"
    f.parse_kind = None
    f.parse_error = None
    f.parse_locked_at = None
    f.parse_locked_by = None
    await sync_current_version(db, f)
    await db.flush()
    await db.refresh(f)
    return f


async def _parse_binary_file(
    db: AsyncSession,
    f: WorkspaceFile,
    *,
    filename: str,
    content_type: str | None,
    raw: bytes,
) -> None:
    try:
        text, kind = doc_parser.extract_text(filename, content_type, raw)
        if not text.strip():
            raise doc_parser.UnsupportedFileTypeError("文件解析后内容为空")
        f.extracted_text = text
        f.parse_status = "ready"
        f.parse_kind = kind
        f.parse_error = None
    except doc_parser.UnsupportedFileTypeError as exc:
        f.extracted_text = None
        message = str(exc)
        f.parse_status = "unsupported" if message.startswith("不支持的文件类型") else "failed"
        f.parse_kind = None
        f.parse_error = message[:1000]
    await db.flush()
    await sync_current_version(db, f)
    await db.refresh(f)


def _readable_file_text(f: WorkspaceFile) -> tuple[str | None, str | None]:
    """Return readable text and an optional error without ever exposing Base64."""
    if not (f.metadata_ or {}).get("binary"):
        return f.content or "", None
    if f.parse_status != "ready" or not (f.extracted_text or "").strip():
        return None, f.parse_error or "尚未解析"
    return f.extracted_text or "", None


def resolve_file_content(
    f: WorkspaceFile,
    *,
    max_chars: int | None = MAX_LLM_FILE_CHARS,
) -> str:
    """给智能体读取文件：文本返回原文，二进制返回解析结果，绝不返回 Base64。"""
    text, error = _readable_file_text(f)
    if error is not None:
        return f"[文件 {f.path} 无法读取正文：{error}]"
    text = text or ""
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n[内容已截断：原文 {len(text)} 字符，本轮最多注入 {max_chars} 字符]"


def paginate_file_content(
    f: WorkspaceFile,
    *,
    offset: int = 1,
    limit: int = 200,
    max_bytes: int = MAX_TOOL_FILE_BYTES,
) -> dict:
    """Return one explicit, model-safe line window from a workspace file."""
    if offset < 1:
        return {"status": "error", "error": "offset must be >= 1"}
    if limit < 1 or limit > 1000:
        return {"status": "error", "error": "limit must be between 1 and 1000"}

    text, error = _readable_file_text(f)
    base = {
        "file_id": str(f.id),
        "path": f.path,
        "original_filename": clean_display_name(f.path, f.metadata_ or {}),
    }
    if error is not None:
        return {**base, "status": "unavailable", "error": error}

    lines = (text or "").splitlines()
    total_lines = len(lines)
    if total_lines == 0:
        return {
            **base,
            "status": "ready",
            "offset": 1,
            "end_line": 0,
            "total_lines": 0,
            "has_more": False,
            "next_offset": None,
            "truncated_reason": None,
            "content": "",
        }
    if offset > total_lines:
        return {
            **base,
            "status": "error",
            "error": f"offset {offset} is out of range ({total_lines} lines)",
            "total_lines": total_lines,
        }

    selected: list[str] = []
    used_bytes = 0
    truncated_reason: str | None = None
    for line in lines[offset - 1: offset - 1 + limit]:
        encoded = line.encode("utf-8")
        separator_bytes = 1 if selected else 0
        if used_bytes + separator_bytes + len(encoded) > max_bytes:
            if not selected:
                # Keep UTF-8 valid and make the exceptional single-line loss explicit.
                clipped = encoded[:max_bytes].decode("utf-8", errors="ignore")
                selected.append(clipped)
                used_bytes = len(clipped.encode("utf-8"))
                truncated_reason = "line_exceeds_byte_limit"
            else:
                truncated_reason = "byte_limit"
            break
        selected.append(line)
        used_bytes += separator_bytes + len(encoded)

    end_line = offset + len(selected) - 1
    has_more = end_line < total_lines
    if truncated_reason == "line_exceeds_byte_limit":
        # Advancing by line would hide the unread remainder, so do not advertise
        # a false continuation point.
        has_more = False
        next_offset = None
    else:
        next_offset = end_line + 1 if has_more else None
    return {
        **base,
        "status": "ready",
        "offset": offset,
        "end_line": end_line,
        "total_lines": total_lines,
        "has_more": has_more,
        "next_offset": next_offset,
        "truncated_reason": truncated_reason,
        "content": "\n".join(selected),
    }


# ── WorkspaceFolder ────────────────────────────────────────────────────

async def create_folder(db: AsyncSession, ws: Workspace, data: WorkspaceFolderCreate) -> WorkspaceFolder:
    """新建文件夹（幂等）：path 经规范化后按 (workspace_id, path) 去重，已存在则原样返回。"""
    path = _normalize_path(data.path)
    result = await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.workspace_id == ws.id,
            WorkspaceFolder.path == path,
            WorkspaceFolder.deleted_at.is_(None),
        )
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        folder = WorkspaceFolder(workspace_id=ws.id, path=path)
        db.add(folder)
        await db.flush()
        await db.refresh(folder)
    return folder


async def list_folders(db: AsyncSession, ws_id: UUID) -> list[WorkspaceFolder]:
    result = await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.workspace_id == ws_id, WorkspaceFolder.deleted_at.is_(None)
        ).order_by(WorkspaceFolder.path)
    )
    return list(result.scalars().all())


async def get_folder(db: AsyncSession, folder_id: UUID) -> WorkspaceFolder | None:
    result = await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.id == folder_id, WorkspaceFolder.deleted_at.is_(None)
        )
    )
    return result.scalar_one_or_none()


async def soft_delete_folder(
    db: AsyncSession,
    folder: WorkspaceFolder,
    *,
    user_id: str | UUID | None = None,
    admin_id: int | None = None,
) -> None:
    """软删文件夹 + 其下所有子文件夹 + 该前缀下所有文件（级联）。

    嵌套靠路径段，故以 ``folder.path + "/"`` 前缀匹配后代与文件。
    """
    now = datetime.now(UTC)
    prefix = f"{folder.path}/"

    # Lock files first, in a stable order shared by every recursive deletion
    # path.  This serializes against file updates and WebOffice room creation.
    sub_files = list((await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == folder.workspace_id,
            WorkspaceFile.path.startswith(prefix),
            WorkspaceFile.deleted_at.is_(None),
        ).order_by(WorkspaceFile.id).with_for_update()
    )).scalars().all())
    await _mark_files_deleted_locked(
        db, sub_files, user_id=user_id, admin_id=admin_id, now=now,
    )

    # Lock the complete folder subtree before changing any folder tombstone.
    sub_folders = (await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.workspace_id == folder.workspace_id,
            or_(
                WorkspaceFolder.id == folder.id,
                WorkspaceFolder.path.startswith(prefix),
            ),
            WorkspaceFolder.deleted_at.is_(None),
        ).order_by(WorkspaceFolder.id).with_for_update()
    )).scalars().all()
    for sf in sub_folders:
        mark_deleted(sf, now=now)
    await db.flush()


async def soft_delete_folder_path(
    db: AsyncSession,
    ws_id: UUID,
    path: str,
    *,
    user_id: str | UUID | None = None,
    admin_id: int | None = None,
) -> dict[str, int]:
    """Delete an explicit or path-inferred folder and everything below it.

    Generated tool/attachment directories often exist only as path prefixes and
    therefore have no ``WorkspaceFolder`` row.  Treat the path tree as the source
    of truth so users can clean those directories without deleting every file.
    The workspace root is intentionally not deletable through this operation.
    """
    normalized = _normalize_path(path)
    if not normalized:
        raise ValueError("不能删除工作空间根目录")
    prefix = f"{normalized}/"
    now = datetime.now(UTC)

    file_rows = list((await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == ws_id,
            WorkspaceFile.path.startswith(prefix),
            WorkspaceFile.deleted_at.is_(None),
        ).order_by(WorkspaceFile.id).with_for_update()
    )).scalars().all())
    await _mark_files_deleted_locked(
        db, file_rows, user_id=user_id, admin_id=admin_id, now=now,
    )

    matched_folders = list((await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.workspace_id == ws_id,
            WorkspaceFolder.deleted_at.is_(None),
            or_(
                WorkspaceFolder.path == normalized,
                WorkspaceFolder.path.startswith(prefix),
            ),
        ).order_by(WorkspaceFolder.id).with_for_update()
    )).scalars().all())
    for item in matched_folders:
        mark_deleted(item, now=now)

    await db.flush()
    return {"folders": len(matched_folders), "files": len(file_rows)}


async def bulk_soft_delete_items(
    db: AsyncSession,
    ws_id: UUID,
    *,
    file_ids: list[UUID],
    folder_paths: list[str],
    user_id: str | UUID | None = None,
    admin_id: int | None = None,
) -> dict[str, int]:
    """Atomically validate and soft-delete selected files and folder subtrees."""
    unique_file_ids = list(dict.fromkeys(file_ids))
    normalized_paths: list[str] = []
    for raw_path in folder_paths:
        segments = raw_path.replace("\\", "/").split("/")
        if any(segment == ".." for segment in segments):
            raise ValueError("文件夹路径不能包含 ..")
        normalized = _normalize_path(raw_path)
        if not normalized:
            raise ValueError("不能删除工作空间根目录")
        normalized_paths.append(normalized)

    # Keep only the shallowest selected ancestor; deleting it already covers descendants.
    reduced_paths: list[str] = []
    for path in sorted(set(normalized_paths), key=lambda item: (item.count("/"), item)):
        if not any(path == parent or path.startswith(f"{parent}/") for parent in reduced_paths):
            reduced_paths.append(path)

    if not unique_file_ids and not reduced_paths:
        raise ValueError("请至少选择一个文件或文件夹")

    file_predicates = []
    if unique_file_ids:
        file_predicates.append(WorkspaceFile.id.in_(unique_file_ids))
    file_predicates.extend(
        WorkspaceFile.path.startswith(f"{path}/") for path in reduced_paths
    )
    selected_files = list((await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.workspace_id == ws_id,
        WorkspaceFile.deleted_at.is_(None),
        or_(*file_predicates),
    ).order_by(WorkspaceFile.id).with_for_update())).scalars().all())
    selected_ids = {str(item.id) for item in selected_files}
    if any(str(file_id) not in selected_ids for file_id in unique_file_ids):
        raise ValueError("部分文件不存在、已删除或不属于当前工作空间")

    folder_predicates = [
        or_(
            WorkspaceFolder.path == path,
            WorkspaceFolder.path.startswith(f"{path}/"),
        )
        for path in reduced_paths
    ]
    selected_folders: list[WorkspaceFolder] = []
    if folder_predicates:
        selected_folders = list((await db.execute(select(WorkspaceFolder).where(
            WorkspaceFolder.workspace_id == ws_id,
            WorkspaceFolder.deleted_at.is_(None),
            or_(*folder_predicates),
        ).order_by(WorkspaceFolder.id).with_for_update())).scalars().all())

    now = datetime.now(UTC)
    await _mark_files_deleted_locked(
        db, selected_files, user_id=user_id, admin_id=admin_id, now=now,
    )
    for item in selected_folders:
        mark_deleted(item, now=now)
    await db.flush()
    return {
        "deleted_files": len(selected_files),
        "deleted_folders": len(selected_folders),
    }


# ── Workspace Tree（随组织架构逐级嵌套）──────────────────────────────────

def _ws_info(ws: Workspace | None) -> dict | None:
    if ws is None:
        return None
    return {
        "id": str(ws.id),
        "name": ws.name,
        "slug": ws.slug,
        "scope_type": ws.scope_type,
        "scope_id": str(ws.scope_id) if ws.scope_id else None,
        "is_active": ws.is_active,
    }


def _node(node_type: str, node_id, name: str, ws: Workspace | None, children: list[dict]) -> dict:
    return {
        "node_type": node_type,
        "node_id": str(node_id),
        "name": name,
        "workspace": _ws_info(ws),
        "children": children,
    }


async def build_workspace_tree(db: AsyncSession, org_ids: list[UUID]) -> list[dict]:
    """构建工作空间文件夹树：组织 → 部门 → 团队 → 用户，每节点携带其绑定工作空间。

    缺失工作空间惰性补建（``ensure_node_workspace``）；用户挂载到所属团队 / 部门 / 组织。
    """
    # 延迟导入以规避与 workspace_lifecycle 的循环依赖。
    from app.services.workspace_lifecycle import ensure_node_workspace

    if not org_ids:
        return []

    rows = (await db.execute(
        select(Organization).where(
            Organization.id.in_(org_ids), Organization.deleted_at.is_(None)
        )
    )).scalars().all()
    orgs = sorted(rows, key=lambda o: o.name)

    tree: list[dict] = []
    for org in orgs:
        org_ws = await ensure_node_workspace(db, org.id, "organization", None, org.name, org.slug)

        depts = list((await db.execute(
            select(Department).where(
                Department.organization_id == org.id, Department.deleted_at.is_(None)
            )
        )).scalars().all())
        dept_map: dict[UUID, Department] = {d.id: d for d in depts}

        all_teams = list((await db.execute(
            select(Team).where(
                Team.organization_id == org.id, Team.deleted_at.is_(None)
            )
        )).scalars().all())
        team_map: dict[UUID, Team] = {t.id: t for t in all_teams}

        users = list((await db.execute(
            select(User).where(
                User.organization_id == org.id, User.deleted_at.is_(None)
            )
        )).scalars().all())

        # 先按 team / dept / org 分桶用户节点
        users_by_team: dict[UUID, list[dict]] = {}
        users_by_dept: dict[UUID, list[dict]] = {}
        org_direct_users: list[dict] = []
        for u in users:
            uname = u.display_name or u.username
            # 组织管理员（role='admin'）非终端用户，不持有工作空间：
            # 节点照常展示（前端标「无工作空间」），但不创建/复活其工作空间。
            if u.role == "admin":
                uws = None
            else:
                uws = await ensure_node_workspace(db, org.id, "user", str(u.id), uname, str(u.id))
            unode = _node("user", u.id, uname, uws, [])
            if u.team_id and u.team_id in team_map:
                users_by_team.setdefault(u.team_id, []).append(unode)
            elif u.department_id and u.department_id in dept_map:
                users_by_dept.setdefault(u.department_id, []).append(unode)
            else:
                org_direct_users.append(unode)

        # 按部门组装（团队归其部门）
        depts_sorted = sorted(depts, key=lambda d: (d.sort_order, d.created_at, str(d.id)))
        dept_nodes: list[dict] = []
        for dept in depts_sorted:
            dept_ws = await ensure_node_workspace(db, org.id, "department", str(dept.id), dept.name, dept.slug)
            dept_teams = [t for t in team_map.values() if t.department_id == dept.id]
            dept_teams = sorted(dept_teams, key=lambda t: t.name)
            team_nodes: list[dict] = []
            for team in dept_teams:
                team_ws = await ensure_node_workspace(db, org.id, "team", str(team.id), team.name, str(team.id))
                team_nodes.append(_node("team", team.id, team.name, team_ws, users_by_team.get(team.id, [])))
            dept_children = team_nodes + users_by_dept.get(dept.id, [])
            dept_nodes.append(_node("department", dept.id, dept.name, dept_ws, dept_children))

        tree.append(_node("organization", org.id, org.name, org_ws, dept_nodes + org_direct_users))

    return tree
