"""Memory lifecycle — keep each org/dept/team node paired with one long-term memory.

镜像 ``workspace_lifecycle``：每个组织 / 部门 / 团队节点恰好对应一条长期记忆，绑定键为
``(organization_id, scope_type, scope_id)``。节点增删改时同步——创建 / 重命名时写入并刷新
``## 档案`` 分节（组织写组织名；部门写组织 + 部门名；团队写组织 / 部门 / 团队名，均 markdown），
删除时软删。管理端记忆树构建时惰性补建缺失记忆。个人级（scope_type='user'）由
``memory_service.upsert_user_profile_memory`` 维护，不在此处。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory

# 组织 / 部门 / 团队记忆的档案分节标题
ARCHIVE_SECTION = "档案"


def _build_archive_section(
    org_name: str | None, dept_name: str | None, team_name: str | None,
) -> str:
    """构建「## 档案」分节：按层级写入所属名称（组织/部门/团队），无任何名称时返回空串。"""
    lines: list[str] = []
    if org_name:
        lines.append(f"- 所属组织：{org_name}")
    if dept_name:
        lines.append(f"- 所属部门：{dept_name}")
    if team_name:
        lines.append(f"- 所属团队：{team_name}")
    if not lines:
        return ""
    return f"## {ARCHIVE_SECTION}\n" + "\n".join(lines)


async def get_bound_memory(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None,
) -> Memory | None:
    """按绑定键取节点对应的未软删记忆；无则返回 None。用 ``.first()`` 兼容存量重复行。"""
    stmt = select(Memory).where(
        Memory.organization_id == org_id,
        Memory.scope_type == scope_type,
        Memory.deleted_at.is_(None),
    )
    if scope_id is None:
        stmt = stmt.where(Memory.scope_id.is_(None))
    else:
        stmt = stmt.where(Memory.scope_id == scope_id)
    return (await db.execute(stmt)).scalars().first()


async def _get_bound_memory_any(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None,
) -> Memory | None:
    """按绑定键取节点对应记忆（含已软删）；供 ``ensure_node_memory`` 复活用。"""
    stmt = select(Memory).where(
        Memory.organization_id == org_id,
        Memory.scope_type == scope_type,
    )
    if scope_id is None:
        stmt = stmt.where(Memory.scope_id.is_(None))
    else:
        stmt = stmt.where(Memory.scope_id == scope_id)
    return (await db.execute(stmt)).scalars().first()


async def ensure_node_memory(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None, *,
    org_name: str | None, dept_name: str | None = None, team_name: str | None = None,
) -> Memory:
    """确保 org/dept/team 节点存在一条绑定记忆，并刷新其 ``## 档案`` 分节为当前名称。

    存在则用 ``_replace_section`` 覆写档案分节（保留管理员在其它分节的自定义内容）；
    已软删则复活并重置为档案分节；确无则新建。幂等。
    """
    from app.services.memory_service import _replace_section

    section = _build_archive_section(org_name, dept_name, team_name)
    fallback = f"## {ARCHIVE_SECTION}\n（暂无信息）"

    mem = await get_bound_memory(db, org_id, scope_type, scope_id)
    if mem is not None:
        if section:
            mem.content = _replace_section(mem.content or "", ARCHIVE_SECTION, section)
        await db.flush()
        return mem

    any_mem = await _get_bound_memory_any(db, org_id, scope_type, scope_id)
    if any_mem is not None:
        any_mem.deleted_at = None
        any_mem.content = section or fallback
        any_mem.category = "archive"
        any_mem.source = "manual"
        await db.flush()
        return any_mem

    mem = Memory(
        organization_id=org_id, scope_type=scope_type, scope_id=scope_id,
        category="archive", content=section or fallback, source="manual", metadata_={},
    )
    db.add(mem)
    await db.flush()
    return mem


async def soft_delete_node_memory(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None,
) -> None:
    """节点删除时软删其绑定记忆。"""
    mem = await get_bound_memory(db, org_id, scope_type, scope_id)
    if mem is not None:
        mem.deleted_at = datetime.now(UTC)
        await db.flush()
