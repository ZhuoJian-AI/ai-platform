"""Workspace service — CRUD for workspaces and their files."""

import base64
import hashlib
import mimetypes
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.config import settings
from app.models.department import Department
from app.models.organization import Organization
from app.models.team import Team
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceFile, WorkspaceFolder
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceFileCreate,
    WorkspaceFileListItem,
    WorkspaceFileUpdate,
    WorkspaceFolderCreate,
    WorkspaceUpdate,
)
from app.services import doc_parser, storage_gateway_service

MAX_WORKSPACE_FILE_BYTES = 5 * 1024 * 1024
MAX_LLM_FILE_CHARS = 100_000
MAX_TOOL_FILE_BYTES = 50 * 1024

_RAW_IMAGE_TOOL_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".pdf",
)
_RAW_ARCHIVE_TOOL_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz")


class WorkspaceFileUploadError(ValueError):
    """工作空间原文件上传校验失败。"""


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
    ws.deleted_at = datetime.now(UTC)
    await db.flush()


# ── WorkspaceFile ──────────────────────────────────────────────────────

def _normalize_path(path: str) -> str:
    """规范化相对路径，防止越权（剥离前导 / 与 .. 段）。"""
    parts: list[str] = []
    for seg in path.replace("\\", "/").split("/"):
        if seg in ("", ".",):
            continue
        if seg == "..":
            # 不允许上跳
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def _sanitize_content(content: str) -> str:
    """剥离 PostgreSQL TEXT 列不允许的 NUL 字节（\\x00）。

    上传的二进制文件经 readAsText 后可能携带 U+0000，直接落库会触发
    ``CharacterNotInRepertoireError``。工作空间为智能体文本沙箱，二进制内容本就不适用，
    此处做防御性清洗避免 500。
    """
    return content.replace("\x00", "")


async def upsert_file(
    db: AsyncSession,
    ws: Workspace,
    data: WorkspaceFileCreate,
    *,
    content_ref: str | None = None,
    raw_size: int | None = None,
    raw_content_hash: str | None = None,
) -> WorkspaceFile:
    path = _normalize_path(data.path)
    content = _sanitize_content(data.content)
    meta = dict(data.metadata or {})
    # 二进制文件：前端以 base64 编码写入 content，并以 metadata.binary 标记。
    # size / content_hash 按解码后的原始字节计算，content 列存 base64 文本（PG TEXT 不允许 NUL）。
    if meta.get("binary") and raw_size is not None and raw_content_hash is not None:
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
    # 注意：此处**不**按 ``deleted_at IS NULL`` 过滤。唯一约束 ``uq_wsfile_path`` 是
    # ``(workspace_id, path)`` 且**不含** deleted_at——同一路径即便旧记录已被软删，仍占用
    # 该 (workspace_id, path) 槽位。若按 deleted_at 过滤会漏掉软删记录 → 走 INSERT 分支
    # → 命中唯一约束冲突（UniqueViolation）。这里取同路径记录（无论软删与否）：存在则
    # 复活并覆盖，不存在才 INSERT。
    result = await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == ws.id,
            WorkspaceFile.path == path,
        )
    )
    f = result.scalar_one_or_none()
    if f is None:
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
        )
        db.add(f)
    else:
        f.content = content
        if content_ref is not None:
            f.content_ref = content_ref
        f.size = size
        f.content_hash = content_hash
        f.extracted_text = None
        f.parse_status = parse_status
        f.parse_kind = parse_kind
        f.parse_error = None
        # 复活被软删的同路径记录：upsert 语义是「该路径现在应是这份内容」，
        # 旧记录的软删状态不应阻挡新写入（否则唯一约束会让 INSERT 失败）。
        f.deleted_at = None
        # 合并而非覆盖：保留既有元数据（如 task_id 归属标记），仅用新值更新同名字段。
        f.metadata_ = {**(f.metadata_ or {}), **meta}
        if not meta.get("binary"):
            f.metadata_.pop("binary", None)
            f.metadata_.pop("mime", None)
    await db.flush()
    await db.refresh(f)
    return f


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
            WorkspaceFile.metadata_,
        )).where(
            WorkspaceFile.workspace_id == ws_id, WorkspaceFile.deleted_at.is_(None)
        ).order_by(WorkspaceFile.path)
    )
    return list(result.scalars().all())


def _file_list_item(f: WorkspaceFile) -> WorkspaceFileListItem:
    meta = f.metadata_ or {}
    original_filename = str(meta.get("name") or PurePosixPath(f.path).name)
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
        parse_status=f.parse_status,
        parse_kind=f.parse_kind,
        parse_error=f.parse_error,
        created_at=f.created_at,
        updated_at=f.updated_at,
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


async def update_file(db: AsyncSession, f: WorkspaceFile, data: WorkspaceFileUpdate) -> WorkspaceFile:
    if data.content is not None:
        content = _sanitize_content(data.content)
        f.content = content
        f.size = len(content.encode("utf-8"))
        f.content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        f.extracted_text = None
        f.parse_status = "ready"
        f.parse_kind = "text"
        f.parse_error = None
    if data.metadata is not None:
        f.metadata_ = data.metadata
    await db.flush()
    await db.refresh(f)
    return f


async def soft_delete_file(db: AsyncSession, f: WorkspaceFile) -> None:
    f.deleted_at = datetime.now(UTC)
    await db.flush()


async def ingest_uploaded_file(
    db: AsyncSession,
    ws: Workspace,
    *,
    path: str,
    filename: str,
    content_type: str | None,
    raw: bytes,
) -> WorkspaceFile:
    """保存工作空间原文件并同步提取可预览、可供 LLM 使用的结构化文本。"""
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
    await _parse_binary_file(db, f, filename=filename, content_type=mime, raw=raw)
    return f


async def load_file_bytes(f: WorkspaceFile) -> bytes:
    """Load original file bytes from OSS or the legacy PostgreSQL payload."""
    if storage_gateway_service.is_object_ref(f.content_ref):
        try:
            raw = await storage_gateway_service.download_bytes(str(f.content_ref))
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
    try:
        raw = await load_file_bytes(f)
    except (WorkspaceFileUploadError, storage_gateway_service.StorageGatewayError) as exc:
        f.parse_status = "failed"
        f.parse_error = str(exc)[:1000]
        await db.flush()
        await db.refresh(f)
        return f
    meta = f.metadata_ or {}
    await _parse_binary_file(
        db,
        f,
        filename=str(meta.get("name") or f.path.rsplit("/", 1)[-1]),
        content_type=str(meta.get("mime") or "application/octet-stream"),
        raw=raw,
    )
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
        "original_filename": str((f.metadata_ or {}).get("name") or PurePosixPath(f.path).name),
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


async def soft_delete_folder(db: AsyncSession, folder: WorkspaceFolder) -> None:
    """软删文件夹 + 其下所有子文件夹 + 该前缀下所有文件（级联）。

    嵌套靠路径段，故以 ``folder.path + "/"`` 前缀匹配后代与文件。
    """
    now = datetime.now(UTC)
    prefix = f"{folder.path}/"

    # 子文件夹
    sub_folders = (await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.workspace_id == folder.workspace_id,
            WorkspaceFolder.path.startswith(prefix),
            WorkspaceFolder.deleted_at.is_(None),
        )
    )).scalars().all()
    for sf in sub_folders:
        sf.deleted_at = now

    # 前缀下文件
    sub_files = (await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == folder.workspace_id,
            WorkspaceFile.path.startswith(prefix),
            WorkspaceFile.deleted_at.is_(None),
        )
    )).scalars().all()
    for sf in sub_files:
        sf.deleted_at = now

    folder.deleted_at = now
    await db.flush()


async def soft_delete_folder_path(db: AsyncSession, ws_id: UUID, path: str) -> dict[str, int]:
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

    folder_rows = (await db.execute(
        select(WorkspaceFolder).where(
            WorkspaceFolder.workspace_id == ws_id,
            WorkspaceFolder.deleted_at.is_(None),
        )
    )).scalars().all()
    matched_folders = [
        item for item in folder_rows
        if item.path == normalized or item.path.startswith(prefix)
    ]
    for item in matched_folders:
        item.deleted_at = now

    file_rows = (await db.execute(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == ws_id,
            WorkspaceFile.path.startswith(prefix),
            WorkspaceFile.deleted_at.is_(None),
        )
    )).scalars().all()
    for item in file_rows:
        item.deleted_at = now

    await db.flush()
    return {"folders": len(matched_folders), "files": len(file_rows)}


async def bulk_soft_delete_items(
    db: AsyncSession,
    ws_id: UUID,
    *,
    file_ids: list[UUID],
    folder_paths: list[str],
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

    selected_files: list[WorkspaceFile] = []
    if unique_file_ids:
        selected_files = list((await db.execute(
            select(WorkspaceFile).where(
                WorkspaceFile.id.in_(unique_file_ids),
                WorkspaceFile.deleted_at.is_(None),
            )
        )).scalars().all())
        if len(selected_files) != len(unique_file_ids):
            raise ValueError("部分文件不存在或已删除")
        if any(item.workspace_id != ws_id for item in selected_files):
            raise ValueError("文件不属于当前工作空间")

    deleted_files = 0
    deleted_folders = 0
    for path in reduced_paths:
        result = await soft_delete_folder_path(db, ws_id, path)
        deleted_files += result["files"]
        deleted_folders += result["folders"]

    now = datetime.now(UTC)
    for item in selected_files:
        if item.deleted_at is None:
            item.deleted_at = now
            deleted_files += 1
    await db.flush()
    return {"deleted_files": deleted_files, "deleted_folders": deleted_folders}


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
        depts_sorted = sorted(depts, key=lambda d: d.name)
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
