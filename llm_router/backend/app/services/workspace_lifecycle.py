"""Workspace lifecycle — keep each org/dept/team/user node paired with one same-name workspace.

严格按节点自动生成：每个组织 / 部门 / 团队 / 用户节点恰好对应一个同名工作空间，
绑定键为 ``(organization_id, scope_type, scope_id)``。本服务在节点增删改时同步工作空间，
并在管理端构建工作空间树时惰性补建缺失的工作空间。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate
from app.services.storage_lifecycle_service import mark_workspace_deleted, restore
from app.services.workspace_service import create_workspace


async def get_bound_workspace(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None,
) -> Workspace | None:
    """按绑定键取节点对应的未软删工作空间；无则返回 None。"""
    stmt = select(Workspace).where(
        Workspace.organization_id == org_id,
        Workspace.scope_type == scope_type,
        Workspace.deleted_at.is_(None),
    )
    if scope_id is None:
        stmt = stmt.where(Workspace.scope_id.is_(None))
    else:
        stmt = stmt.where(Workspace.scope_id == scope_id)
    # 用 .first() 而非 scalar_one_or_none：兼容历史手动创建可能残留的同 scope 重复行，
    # 严格模式下每节点至多一个绑定工作空间。
    return (await db.execute(stmt)).scalars().first()


async def _get_bound_workspace_any(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None,
) -> Workspace | None:
    """按绑定键取节点对应的工作空间（含已软删）；供 ``ensure_node_workspace`` 复活用。"""
    stmt = select(Workspace).where(
        Workspace.organization_id == org_id,
        Workspace.scope_type == scope_type,
    )
    if scope_id is None:
        stmt = stmt.where(Workspace.scope_id.is_(None))
    else:
        stmt = stmt.where(Workspace.scope_id == scope_id)
    return (await db.execute(stmt)).scalars().first()


async def ensure_node_workspace(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None,
    name: str, slug: str,
) -> Workspace:
    """确保节点存在同名绑定工作空间；存在则同步 name，不存在则创建，已软删则复活。幂等。

    同一节点恢复时优先复活原工作空间，保留其历史文件。新节点即使复用了已删除
    节点的 slug，也必须创建独立工作空间，避免将旧部门文件泄露给新部门。数据库仅对
    ``deleted_at IS NULL`` 的工作空间限制 ``(organization_id, slug)`` 唯一。
    """
    ws = await get_bound_workspace(db, org_id, scope_type, scope_id)
    if ws is not None:
        if ws.name != name:
            ws.name = name
            await db.flush()
        return ws

    ws = await _get_bound_workspace_any(db, org_id, scope_type, scope_id)
    if ws is not None:
        restore(ws)
        ws.name = name
        # slug 仅对组织 / 部门节点有意义（取节点 slug）；团队 / 用户工作空间 slug 为节点 id，不可变。
        if scope_type in ("organization", "department") and slug and ws.slug != slug:
            ws.slug = slug
        await db.flush()
        return ws

    return await create_workspace(
        db, org_id,
        WorkspaceCreate(name=name, slug=slug, scope_type=scope_type, scope_id=scope_id),
    )


async def sync_node_workspace(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None,
    name: str, slug: str | None = None,
) -> None:
    """节点重命名时同步工作空间 name/slug；找不到绑定工作空间则不操作（下次建树会补建）。

    slug 仅对组织 / 部门节点有意义（其工作空间 slug 取节点 slug）；团队 / 用户工作空间
    slug 为节点 id，不可变，故不传。
    """
    ws = await get_bound_workspace(db, org_id, scope_type, scope_id)
    if ws is None:
        return
    changed = False
    if ws.name != name:
        ws.name = name
        changed = True
    if slug is not None and ws.slug != slug:
        ws.slug = slug
        changed = True
    if changed:
        await db.flush()


async def soft_delete_node_workspace(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None,
) -> None:
    """节点删除时软删其绑定工作空间；文件随 workspace_id 自然失达，无需单独处理。"""
    ws = await get_bound_workspace(db, org_id, scope_type, scope_id)
    if ws is not None:
        await mark_workspace_deleted(db, ws)
