"""Skill store service — 技能文件夹 + 文件 CRUD（镜像 workspace_service）。

一个技能 = 一个 SkillFolder（节点作用域化）；文件夹内 skill.md 定义 function-tool manifest。
路径规范化 / 内容清洗复用 workspace_service。
"""

import hashlib
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import SkillFile, SkillFolder
from app.schemas.skill import SkillFileCreate, SkillFileUpdate, SkillFolderCreate, SkillFolderUpdate
from app.services.storage_lifecycle_service import mark_deleted, mark_skill_deleted
from app.services.workspace_service import _normalize_path, _sanitize_content

SKILL_MANIFEST_PATH = "skill.md"


def _scope_clause(model, org_id: UUID, scope_type: str, scope_id: str | None):
    return [
        model.organization_id == org_id,
        model.scope_type == scope_type,
        model.scope_id.is_(None) if scope_id is None else model.scope_id == scope_id,
    ]


# ── SkillFolder ─────────────────────────────────────────────────────────

async def create_folder(
    db: AsyncSession, org_id: UUID, data: SkillFolderCreate, created_by: str | None = None,
) -> SkillFolder:
    f = SkillFolder(organization_id=org_id, created_by=created_by, **data.model_dump())
    db.add(f)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(f)
    return f


async def list_folders(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None,
) -> list[SkillFolder]:
    result = await db.execute(
        select(SkillFolder).where(
            *_scope_clause(SkillFolder, org_id, scope_type, scope_id),
            SkillFolder.deleted_at.is_(None),
        ).order_by(SkillFolder.name)
    )
    return list(result.scalars().all())


async def get_folder(db: AsyncSession, folder_id: UUID) -> SkillFolder | None:
    result = await db.execute(
        select(SkillFolder).where(SkillFolder.id == folder_id, SkillFolder.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_folder(db: AsyncSession, f: SkillFolder, data: SkillFolderUpdate) -> SkillFolder:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(f, field, value)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(f)
    return f


async def soft_delete_folder(db: AsyncSession, f: SkillFolder) -> None:
    """软删技能文件夹（FK CASCADE 会级联 skill_files；此处显式软删）。"""
    await mark_skill_deleted(db, f)


# ── SkillFile ───────────────────────────────────────────────────────────

async def upsert_file(
    db: AsyncSession, folder: SkillFolder, data: SkillFileCreate,
) -> SkillFile:
    path = _normalize_path(data.path)
    content = _sanitize_content(data.content)
    meta = dict(data.metadata or {})
    size = len(content.encode("utf-8"))
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    result = await db.execute(
        select(SkillFile).where(
            SkillFile.skill_folder_id == folder.id,
            SkillFile.path == path,
            SkillFile.deleted_at.is_(None),
        )
    )
    f = result.scalar_one_or_none()
    if f is None:
        f = SkillFile(
            skill_folder_id=folder.id, path=path, size=size,
            content_hash=content_hash, content=content, metadata_=meta,
        )
        db.add(f)
    else:
        f.content = content
        f.size = size
        f.content_hash = content_hash
        f.metadata_ = {**(f.metadata_ or {}), **meta}
    await db.flush()
    await db.refresh(f)
    return f


async def list_files(db: AsyncSession, folder_id: UUID) -> list[SkillFile]:
    result = await db.execute(
        select(SkillFile).where(
            SkillFile.skill_folder_id == folder_id, SkillFile.deleted_at.is_(None),
        ).order_by(SkillFile.path)
    )
    return list(result.scalars().all())


async def get_file(db: AsyncSession, file_id: UUID) -> SkillFile | None:
    result = await db.execute(
        select(SkillFile).where(SkillFile.id == file_id, SkillFile.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_file_by_path(db: AsyncSession, folder_id: UUID, path: str) -> SkillFile | None:
    """按 (folder_id, path) 取文件；供 agent 读取 skill.md manifest。"""
    normalized = _normalize_path(path)
    result = await db.execute(
        select(SkillFile).where(
            SkillFile.skill_folder_id == folder_id,
            SkillFile.path == normalized,
            SkillFile.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def update_file(db: AsyncSession, f: SkillFile, data: SkillFileUpdate) -> SkillFile:
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


async def soft_delete_file(db: AsyncSession, f: SkillFile) -> None:
    mark_deleted(f)
    await db.flush()
