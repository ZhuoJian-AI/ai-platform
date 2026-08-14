"""Data interface service — 系统 / 数据接口 CRUD（数据接口页独立数据结构）。

后端提供完整 CRUD（供脚本 / 种子 / 后续录入页使用）；管理端 UI 仅启用/禁用 + 搜索 + 查看样例。
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_interface import DataInterface, DataSystem
from app.schemas.data_interface import (
    DataInterfaceCreate,
    DataInterfaceUpdate,
    DataSystemCreate,
    DataSystemUpdate,
)


def _scope_clause(model, org_id: UUID, scope_type: str, scope_id: str | None):
    clauses = [
        model.organization_id == org_id,
        model.scope_type == scope_type,
        model.scope_id.is_(None) if scope_id is None else model.scope_id == scope_id,
    ]
    return clauses


# ── DataSystem ──────────────────────────────────────────────────────────

async def create_system(
    db: AsyncSession, org_id: UUID, data: DataSystemCreate,
) -> DataSystem:
    s = DataSystem(organization_id=org_id, **data.model_dump())
    db.add(s)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(s)
    return s


async def list_systems(
    db: AsyncSession, org_id: UUID, scope_type: str, scope_id: str | None,
) -> list[DataSystem]:
    result = await db.execute(
        select(DataSystem).where(
            *_scope_clause(DataSystem, org_id, scope_type, scope_id),
            DataSystem.deleted_at.is_(None),
        ).order_by(DataSystem.name)
    )
    return list(result.scalars().all())


async def get_system(db: AsyncSession, system_id: UUID) -> DataSystem | None:
    result = await db.execute(
        select(DataSystem).where(DataSystem.id == system_id, DataSystem.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_system(db: AsyncSession, s: DataSystem, data: DataSystemUpdate) -> DataSystem:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    await db.flush()
    await db.refresh(s)
    return s


async def soft_delete_system(db: AsyncSession, s: DataSystem) -> None:
    s.deleted_at = datetime.now(UTC)
    await db.flush()


# ── DataInterface ───────────────────────────────────────────────────────

async def create_interface(
    db: AsyncSession, system: DataSystem, data: DataInterfaceCreate,
) -> DataInterface:
    di = DataInterface(data_system_id=system.id, **data.model_dump())
    db.add(di)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(di)
    return di


async def list_interfaces(db: AsyncSession, system_id: UUID) -> list[DataInterface]:
    result = await db.execute(
        select(DataInterface).where(
            DataInterface.data_system_id == system_id, DataInterface.deleted_at.is_(None),
        ).order_by(DataInterface.name)
    )
    return list(result.scalars().all())


async def get_interface(db: AsyncSession, interface_id: UUID) -> DataInterface | None:
    result = await db.execute(
        select(DataInterface).where(DataInterface.id == interface_id, DataInterface.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_interface(db: AsyncSession, di: DataInterface, data: DataInterfaceUpdate) -> DataInterface:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(di, field, value)
    await db.flush()
    await db.refresh(di)
    return di


async def soft_delete_interface(db: AsyncSession, di: DataInterface) -> None:
    di.deleted_at = datetime.now(UTC)
    await db.flush()
