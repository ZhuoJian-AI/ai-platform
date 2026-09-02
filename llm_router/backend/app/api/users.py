"""Users CRUD API — org-scoped end-user management."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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
from app.auth.user_auth import current_user_for_user
from app.database import get_db
from app.schemas.user import (
    UserCreate,
    UserLoginRequest,
    UserLoginResponse,
    UserPasswordReset,
    UserRead,
    UserSlugLoginRequest,
    UserUpdate,
)
from app.services import workspace_permission_service
from app.services.organization_service import get_organization, get_organization_by_slug
from app.services.user_service import (
    create_user,
    get_user,
    list_users,
    login_user,
    reset_password,
    soft_delete_user,
    update_user,
)

router = APIRouter()


@router.post("/users/login", response_model=UserLoginResponse)
async def login_user_endpoint(
    data: UserLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """组织用户登录（密码登录）。username 仅组织内唯一，故请求体需带 organization_id。"""
    result = await login_user(db, data.organization_id, data.username, data.password)
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid organization, username or password")
    return result


@router.post("/users/login-by-slug", response_model=UserLoginResponse)
async def login_user_by_slug_endpoint(
    data: UserSlugLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """终端用户按组织 slug 登录（多租户兼容，前端 ``/{slug}/users/login`` 调用）。"""
    org = await get_organization_by_slug(db, data.slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    result = await login_user(db, org.id, data.username, data.password)
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return result


@router.post("/organizations/{org_id}/users", response_model=UserRead, status_code=201)
async def create_user_endpoint(
    org_id: UUID,
    data: UserCreate,
    auth: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    org = await get_organization(db, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        return await create_user(db, org_id, data, created_by_admin_id=auth.id)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Username '{data.username}' already exists in this organization")


@router.get("/organizations/{org_id}/users", response_model=list[UserRead])
async def list_users_endpoint(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access),
    db: AsyncSession = Depends(get_db),
):
    return await list_users(db, org_id)


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user_endpoint(
    user_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    assert_org_access(auth, user.organization_id)
    return user


@router.get("/users/{user_id}/effective-access")
async def get_user_effective_access_endpoint(
    user_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Preview exactly the workspace permissions the selected employee receives."""
    user = await get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    assert_org_access(auth, user.organization_id)
    principal = await current_user_for_user(db, user)
    return await workspace_permission_service.effective_access(db, principal)


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user_endpoint(
    user_id: UUID,
    data: UserUpdate,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    assert_org_write_access(auth, user.organization_id)
    try:
        return await update_user(db, user, data, created_by_admin_id=auth.id)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists in this organization")


@router.post("/users/{user_id}/reset-password", response_model=UserRead)
async def reset_password_endpoint(
    user_id: UUID,
    data: UserPasswordReset,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """重置组织用户密码（重置后该用户下次登录强制改密）。
    权限：org_admin 可重置本组织用户、super_admin 全局可重置。
    """
    user = await get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    assert_org_write_access(auth, user.organization_id)
    return await reset_password(db, user, data.password)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user_endpoint(
    user_id: UUID,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    assert_org_write_access(auth, user.organization_id)
    await soft_delete_user(db, user)
