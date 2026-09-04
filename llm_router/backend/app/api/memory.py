"""Memory admin API — 维护组织/部门/团队级长期记忆（超管端 + 组织管理端）。

个人级（scope_type='user'）每用户仅一条，由系统端 + 终端智能体自动合并沉淀；管理端不允许
新建个人记忆（避免破坏「每用户一份」），但可编辑其内容/分类/元数据（人工修订）。所有级别
记忆均不允许删除（只合并/编辑，不删除）。
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.schemas.memory import MemoryCreate, MemoryRead, MemoryUpdate
from app.services import memory_service
from app.services.organization_service import list_organizations

router = APIRouter()


def _assert_admin_scope_writable(scope_type: str) -> None:
    """管理端仅可新建 organization/department/team 级；user 级由系统+智能体自动合并。"""
    if scope_type == "user":
        raise HTTPException(status_code=403, detail="Personal memory is auto-managed; edit instead of create")


def _strip_scope_fields(data: MemoryUpdate) -> MemoryUpdate:
    """去掉 scope_type/scope_id（含「显式传了 None」的情况），且不把它们标成已设置。"""
    return MemoryUpdate(**{
        key: value for key, value in data.model_dump(exclude_unset=True).items()
        if key not in {"scope_type", "scope_id"}
    })


# ── Memory Tree（随组织架构逐级嵌套）──

@router.get("/memory/tree")
async def memory_tree_endpoint(
    organization_id: UUID | None = None,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    """长期记忆树：组织 → 部门 → 团队 → 用户，每节点携带其绑定记忆。

    - 指定 ``organization_id`` 时仅返回该组织子树（须有访问权）；
    - 组织级管理员未指定时返回其组织子树；
    - 平台级账号（超管）未指定时返回全部组织。
    - 缺失记忆惰性补建/刷新（GET 亦会写入，与工作空间树一致）。
    """
    if organization_id is not None:
        assert_org_access(auth, organization_id)
        org_ids = [organization_id]
    elif auth.organization_id is not None:
        org_ids = [auth.organization_id]
    else:
        org_ids = [o.id for o in await list_organizations(db)]
    return await memory_service.build_memory_tree(db, org_ids)


@router.get("/organizations/{org_id}/memory", response_model=list[MemoryRead])
async def list_memory_endpoint(
    org_id: UUID,
    scope_type: str | None = Query(default=None),
    scope_id: str | None = Query(default=None),
    _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    return await memory_service.list_memory(db, org_id, scope_type=scope_type, scope_id=scope_id)


@router.post("/organizations/{org_id}/memory", response_model=MemoryRead, status_code=201)
async def create_memory_endpoint(
    org_id: UUID, data: MemoryCreate,
    auth: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    _assert_admin_scope_writable(data.scope_type)
    mem = await memory_service.create_memory(db, org_id, data)
    await db.commit()
    await db.refresh(mem)
    return mem


@router.patch("/memory/{mem_id}", response_model=MemoryRead)
async def update_memory_endpoint(
    mem_id: UUID, data: MemoryUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    mem = await memory_service.get_memory(db, mem_id)
    if mem is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    assert_org_write_access(auth, mem.organization_id)
    if mem.scope_type == "user":
        # 个人记忆：仅可改内容/分类/元数据，禁止改 scope 归属（保持「每用户一份」）。
        # 注意不能用 model_copy(update={...: None})——那会把 scope_type/scope_id 记进 fields_set，
        # update_memory 的 model_dump(exclude_unset=True) 就会把 NULL 写进 NOT NULL 列 → 500。
        # 这里重建一个不含这两个字段的 MemoryUpdate（其余字段保持「显式传了什么就更新什么」）。
        data = _strip_scope_fields(data)
    elif data.scope_type is not None:
        _assert_admin_scope_writable(data.scope_type)
    updated = await memory_service.update_memory(db, mem, data)
    await db.commit()
    return updated
