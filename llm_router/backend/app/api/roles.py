"""Organization role and assignment management APIs."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import (
    CurrentAdmin,
    assert_org_write_access,
    require_admin,
    require_org_access,
    require_org_access_write,
)
from app.database import get_db
from app.schemas.role import (
    RoleCreate,
    RoleDataScopeReplace,
    RolePermissionsReplace,
    RoleRead,
    RoleUpdate,
    UserRolesReplace,
)
from app.schemas.user import UserRead
from app.services.role_service import (
    create_role,
    delete_role,
    get_role,
    list_roles,
    replace_data_scope,
    replace_permissions,
    replace_user_roles,
    update_role,
)
from app.services.user_service import get_user

router = APIRouter()


def _role_org(auth: CurrentAdmin, organization_id: UUID | None) -> UUID:
    if auth.organization_id is not None:
        if organization_id is not None and organization_id != auth.organization_id:
            raise HTTPException(status_code=403, detail="No access to this organization")
        return auth.organization_id
    if organization_id is None:
        raise HTTPException(status_code=422, detail="organization_id is required for platform administrators")
    return organization_id


@router.get("/roles", response_model=list[RoleRead])
async def list_roles_public_contract(
    organization_id: UUID | None = None,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await list_roles(db, _role_org(auth, organization_id))


@router.post("/roles", response_model=RoleRead, status_code=201)
async def create_role_public_contract(
    data: RoleCreate,
    organization_id: UUID | None = None,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    org_id = _role_org(auth, organization_id)
    assert_org_write_access(auth, org_id)
    try:
        return await create_role(db, org_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Role code '{data.code}' already exists")


@router.get("/organizations/{org_id}/roles", response_model=list[RoleRead])
async def list_roles_endpoint(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access),
    db: AsyncSession = Depends(get_db),
):
    return await list_roles(db, org_id)


@router.post("/organizations/{org_id}/roles", response_model=RoleRead, status_code=201)
async def create_role_endpoint(
    org_id: UUID,
    data: RoleCreate,
    _: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await create_role(db, org_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Role code '{data.code}' already exists")


async def _owned_role(db: AsyncSession, role_id: UUID, auth: CurrentAdmin):
    role = await get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    assert_org_write_access(auth, role.organization_id)
    return role


@router.get("/roles/{role_id}", response_model=RoleRead)
async def get_role_endpoint(
    role_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _owned_role(db, role_id, auth)


@router.patch("/roles/{role_id}", response_model=RoleRead)
async def update_role_endpoint(
    role_id: UUID,
    data: RoleUpdate,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await update_role(db, await _owned_role(db, role_id, auth), data)


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role_endpoint(
    role_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await delete_role(db, await _owned_role(db, role_id, auth))


@router.put("/roles/{role_id}/permissions", response_model=RoleRead)
async def replace_role_permissions_endpoint(
    role_id: UUID,
    data: RolePermissionsReplace,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await replace_permissions(db, await _owned_role(db, role_id, auth), data.permission_codes)


@router.put("/roles/{role_id}/data-scope", response_model=RoleRead)
async def replace_role_data_scope_endpoint(
    role_id: UUID,
    data: RoleDataScopeReplace,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await replace_data_scope(db, await _owned_role(db, role_id, auth), data)


@router.put("/users/{user_id}/roles", response_model=UserRead)
async def replace_user_roles_endpoint(
    user_id: UUID,
    data: UserRolesReplace,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    assert_org_write_access(auth, user.organization_id)
    await replace_user_roles(db, user, data.role_ids)
    return user
