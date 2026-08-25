"""Ontology store service — Markdown 文件 + 文件夹 CRUD（镜像 workspace_service）。

作用域由 (organization_id, scope_type, scope_id) 直接表达（organization 级 scope_id 为 None）。
path 为相对作用域根的 POSIX 路径，嵌套靠路径段表达；路径规范化 / 内容清洗复用 workspace_service。
旧 ``Ontology``（JSONB）模型 dormant，agent 运行时改读 ``OntologyFile.content``。
"""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ontology import OntologyFile, OntologyFolder
from app.schemas.ontology import OntologyFileCreate, OntologyFileUpdate
from app.services.storage_lifecycle_service import mark_deleted
from app.services.workspace_service import _normalize_path, _sanitize_content


def _scope_clause(model, org_id: UUID, scope_type: str, scope_id: str | None):
    """构造 (organization_id, scope_type, scope_id) 作用域 WHERE 条件。

    organization 级 scope_id 为 None，须用 ``is_(None)`` 匹配，避免 NULL 不等。
    """
    clauses = [
        model.organization_id == org_id,
        model.scope_type == scope_type,
        model.scope_id.is_(None) if scope_id is None else model.scope_id == scope_id,
    ]
    return clauses


# ── OntologyFile ────────────────────────────────────────────────────────

async def upsert_file(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None, data: OntologyFileCreate,
    created_by: str | None = None,
) -> OntologyFile:
    path = _normalize_path(data.path)
    content = _sanitize_content(data.content)
    meta = dict(data.metadata or {})
    size = len(content.encode("utf-8"))
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    result = await db.execute(
        select(OntologyFile).where(
            *_scope_clause(OntologyFile, org_id, scope_type, scope_id),
            OntologyFile.path == path,
            OntologyFile.deleted_at.is_(None),
        )
    )
    f = result.scalar_one_or_none()
    if f is None:
        f = OntologyFile(
            organization_id=org_id, scope_type=scope_type, scope_id=scope_id,
            path=path, size=size, content_hash=content_hash, content=content, metadata_=meta,
            created_by=created_by,
        )
        db.add(f)
    else:
        # 已存在：覆盖内容但保留原始创建者（与 RAG upsert 行为一致）
        f.content = content
        f.size = size
        f.content_hash = content_hash
        f.metadata_ = {**(f.metadata_ or {}), **meta}
    await db.flush()
    await db.refresh(f)
    return f


async def list_files(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None,
) -> list[OntologyFile]:
    result = await db.execute(
        select(OntologyFile).where(
            *_scope_clause(OntologyFile, org_id, scope_type, scope_id),
            OntologyFile.deleted_at.is_(None),
        ).order_by(OntologyFile.path)
    )
    return list(result.scalars().all())


async def get_file(db: AsyncSession, file_id: UUID) -> OntologyFile | None:
    result = await db.execute(
        select(OntologyFile).where(OntologyFile.id == file_id, OntologyFile.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_file(db: AsyncSession, f: OntologyFile, data: OntologyFileUpdate) -> OntologyFile:
    if data.path is not None:
        f.path = _normalize_path(data.path)
    if data.content is not None:
        content = _sanitize_content(data.content)
        f.content = content
        f.size = len(content.encode("utf-8"))
        f.content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if data.metadata is not None:
        f.metadata_ = data.metadata
    await db.flush()
    await db.refresh(f)
    return f


async def soft_delete_file(db: AsyncSession, f: OntologyFile) -> None:
    mark_deleted(f)
    await db.flush()


# ── OntologyFolder ──────────────────────────────────────────────────────

async def create_folder(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None, path: str,
    created_by: str | None = None,
) -> OntologyFolder:
    """新建文件夹（幂等）：已存在则原样返回（不改动 created_by）。"""
    normalized = _normalize_path(path)
    result = await db.execute(
        select(OntologyFolder).where(
            *_scope_clause(OntologyFolder, org_id, scope_type, scope_id),
            OntologyFolder.path == normalized,
            OntologyFolder.deleted_at.is_(None),
        )
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        folder = OntologyFolder(
            organization_id=org_id, scope_type=scope_type, scope_id=scope_id, path=normalized,
            created_by=created_by,
        )
        db.add(folder)
        await db.flush()
        await db.refresh(folder)
    return folder


async def list_folders(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None,
) -> list[OntologyFolder]:
    result = await db.execute(
        select(OntologyFolder).where(
            *_scope_clause(OntologyFolder, org_id, scope_type, scope_id),
            OntologyFolder.deleted_at.is_(None),
        ).order_by(OntologyFolder.path)
    )
    return list(result.scalars().all())


async def get_folder(db: AsyncSession, folder_id: UUID) -> OntologyFolder | None:
    result = await db.execute(
        select(OntologyFolder).where(OntologyFolder.id == folder_id, OntologyFolder.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def rename_folder(db: AsyncSession, folder: OntologyFolder, new_path: str) -> OntologyFolder:
    """重命名文件夹：更新自身 path，并前缀替换所有子文件夹与文件的 path。"""
    old_path = folder.path
    new_path = _normalize_path(new_path)
    if old_path == new_path:
        return folder
    old_prefix = f"{old_path}/"
    new_prefix = f"{new_path}/"

    # 子文件夹
    sub_folders = (await db.execute(
        select(OntologyFolder).where(
            *_scope_clause(OntologyFolder, folder.organization_id, folder.scope_type, folder.scope_id),
            OntologyFolder.path.startswith(old_prefix),
            OntologyFolder.deleted_at.is_(None),
        )
    )).scalars().all()
    for sf in sub_folders:
        sf.path = new_prefix + sf.path[len(old_prefix):]

    # 前缀下文件（含文件夹自身路径下的文件）
    sub_files = (await db.execute(
        select(OntologyFile).where(
            *_scope_clause(OntologyFile, folder.organization_id, folder.scope_type, folder.scope_id),
            OntologyFile.path.startswith(old_prefix),
            OntologyFile.deleted_at.is_(None),
        )
    )).scalars().all()
    for sf in sub_files:
        sf.path = new_prefix + sf.path[len(old_prefix):]

    folder.path = new_path
    await db.flush()
    await db.refresh(folder)
    return folder


async def soft_delete_folder(db: AsyncSession, folder: OntologyFolder) -> None:
    """软删文件夹 + 其下所有子文件夹 + 该前缀下所有文件（级联）。"""
    now = datetime.now(UTC)
    prefix = f"{folder.path}/"

    sub_folders = (await db.execute(
        select(OntologyFolder).where(
            *_scope_clause(OntologyFolder, folder.organization_id, folder.scope_type, folder.scope_id),
            OntologyFolder.path.startswith(prefix),
            OntologyFolder.deleted_at.is_(None),
        )
    )).scalars().all()
    for sf in sub_folders:
        mark_deleted(sf, now=now)

    sub_files = (await db.execute(
        select(OntologyFile).where(
            *_scope_clause(OntologyFile, folder.organization_id, folder.scope_type, folder.scope_id),
            OntologyFile.path.startswith(prefix),
            OntologyFile.deleted_at.is_(None),
        )
    )).scalars().all()
    for sf in sub_files:
        mark_deleted(sf, now=now)

    mark_deleted(folder, now=now)
    await db.flush()
