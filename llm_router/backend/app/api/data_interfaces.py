"""Data interface API — 数据接口页独立数据结构（系统 + 接口）。

后端提供完整 CRUD；管理端 UI 仅启用/禁用 + 搜索 + 查看输入输出样例。
与连接器（connectors/endpoints）解耦，连接器另有他用（技能绑定 / agent 调用）。
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import (
    CurrentAdmin,
    assert_org_access,
    assert_org_write_access,
    require_admin,
    require_org_access,
    require_org_access_write,
)
from app.database import get_db
from app.schemas.data_interface import (
    DataInterfaceCreate,
    DataInterfaceRead,
    DataInterfaceUpdate,
    DataSystemCreate,
    DataSystemRead,
    DataSystemUpdate,
)
from app.services.data_interface_service import (
    create_interface,
    create_system,
    get_interface,
    get_system,
    list_interfaces,
    list_systems,
    soft_delete_interface,
    soft_delete_system,
    update_interface,
    update_system,
)

router = APIRouter()


def _scope_params(scope_type: str, scope_id: str | None) -> tuple[str, str | None]:
    """从 query 解析作用域：organization 级 scope_id 为 None。"""
    return scope_type, scope_id or None


# ── DataSystem ──

@router.get("/organizations/{org_id}/data-systems", response_model=list[DataSystemRead])
async def list_systems_endpoint(
    org_id: UUID,
    scope_type: str = Query("organization"),
    scope_id: str | None = Query(None),
    _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    st, sid = _scope_params(scope_type, scope_id)
    return await list_systems(db, org_id, st, sid)


@router.post("/organizations/{org_id}/data-systems", response_model=DataSystemRead, status_code=201)
async def create_system_endpoint(
    org_id: UUID, data: DataSystemCreate,
    _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    try:
        return await create_system(db, org_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"System '{data.name}' already exists in this scope")


@router.get("/data-systems/{system_id}", response_model=DataSystemRead)
async def get_system_endpoint(
    system_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    s = await get_system(db, system_id)
    if not s:
        raise HTTPException(status_code=404, detail="Data system not found")
    assert_org_access(auth, s.organization_id)
    return s


@router.patch("/data-systems/{system_id}", response_model=DataSystemRead)
async def update_system_endpoint(
    system_id: UUID, data: DataSystemUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    s = await get_system(db, system_id)
    if not s:
        raise HTTPException(status_code=404, detail="Data system not found")
    assert_org_write_access(auth, s.organization_id)
    return await update_system(db, s, data)


@router.delete("/data-systems/{system_id}", status_code=204)
async def delete_system_endpoint(
    system_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    s = await get_system(db, system_id)
    if not s:
        raise HTTPException(status_code=404, detail="Data system not found")
    assert_org_write_access(auth, s.organization_id)
    await soft_delete_system(db, s)


# ── DataInterface ──

@router.get("/data-systems/{system_id}/data-interfaces", response_model=list[DataInterfaceRead])
async def list_interfaces_endpoint(
    system_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    s = await get_system(db, system_id)
    if not s:
        raise HTTPException(status_code=404, detail="Data system not found")
    assert_org_access(auth, s.organization_id)
    return await list_interfaces(db, s.id)


@router.post("/data-systems/{system_id}/data-interfaces", response_model=DataInterfaceRead, status_code=201)
async def create_interface_endpoint(
    system_id: UUID, data: DataInterfaceCreate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    s = await get_system(db, system_id)
    if not s:
        raise HTTPException(status_code=404, detail="Data system not found")
    assert_org_write_access(auth, s.organization_id)
    try:
        return await create_interface(db, s, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Interface '{data.name}' already exists in this system")


@router.get("/data-interfaces/{interface_id}", response_model=DataInterfaceRead)
async def get_interface_endpoint(
    interface_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    di = await get_interface(db, interface_id)
    if not di:
        raise HTTPException(status_code=404, detail="Data interface not found")
    s = await get_system(db, di.data_system_id)
    if not s:
        raise HTTPException(status_code=404, detail="Data system not found")
    assert_org_access(auth, s.organization_id)
    return di


@router.patch("/data-interfaces/{interface_id}", response_model=DataInterfaceRead)
async def update_interface_endpoint(
    interface_id: UUID, data: DataInterfaceUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    di = await get_interface(db, interface_id)
    if not di:
        raise HTTPException(status_code=404, detail="Data interface not found")
    s = await get_system(db, di.data_system_id)
    if not s:
        raise HTTPException(status_code=404, detail="Data system not found")
    assert_org_write_access(auth, s.organization_id)
    return await update_interface(db, di, data)


@router.delete("/data-interfaces/{interface_id}", status_code=204)
async def delete_interface_endpoint(
    interface_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    di = await get_interface(db, interface_id)
    if not di:
        raise HTTPException(status_code=404, detail="Data interface not found")
    s = await get_system(db, di.data_system_id)
    if not s:
        raise HTTPException(status_code=404, detail="Data system not found")
    assert_org_write_access(auth, s.organization_id)
    await soft_delete_interface(db, di)
