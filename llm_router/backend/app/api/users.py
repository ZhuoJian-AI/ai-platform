"""Users CRUD API — org-scoped end-user management."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
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
from app.auth.login_throttle import (
    assert_login_allowed,
    clear_login_failures,
    record_login_failure,
)
from app.auth.session_cookies import clear_cookie, set_session_cookie, user_session_cookie_name
from app.auth.user_auth import CurrentUser, current_user_for_user, require_user
from app.database import get_db
from app.models.user import User
from app.schemas.user import (
    UserCreate,
    UserLoginRequest,
    UserLoginResponse,
    UserPasswordChange,
    UserPasswordReset,
    UserRead,
    UserSlugLoginRequest,
    UserUpdate,
)
from app.services import workspace_permission_service
from app.services.oauth_service import revoke_user_refresh_tokens
from app.services.organization_service import get_organization, get_organization_by_slug
from app.services.user_service import (
    change_own_password,
    create_user,
    get_user,
    list_users,
    login_user,
    reset_password,
    soft_delete_user,
    update_user,
)
from app.utils.request_source import client_source

router = APIRouter()


@router.post("/users/login", response_model=UserLoginResponse)
async def login_user_endpoint(
    data: UserLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """组织用户登录（密码登录）。username 仅组织内唯一，故请求体需带 organization_id。"""
    identity = f"{data.organization_id}:{data.username}"
    source = client_source(request)
    await assert_login_allowed("employee", identity, source)
    result = await login_user(db, data.organization_id, data.username, data.password)
    if result is None:
        await record_login_failure("employee", identity, source)
        raise HTTPException(status_code=401, detail="Invalid organization, username or password")
    await clear_login_failures("employee", identity, source)
    set_session_cookie(response, user_session_cookie_name(), result.access_token, max_age=24 * 60 * 60)
    return result


@router.post("/users/login-by-slug", response_model=UserLoginResponse)
async def login_user_by_slug_endpoint(
    data: UserSlugLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """终端用户按组织 slug 登录（多租户兼容，前端 ``/{slug}/users/login`` 调用）。"""
    org = await get_organization_by_slug(db, data.slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    identity = f"{org.id}:{data.username}"
    source = client_source(request)
    await assert_login_allowed("employee", identity, source)
    result = await login_user(db, org.id, data.username, data.password)
    if result is None:
        await record_login_failure("employee", identity, source)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    await clear_login_failures("employee", identity, source)
    set_session_cookie(response, user_session_cookie_name(), result.access_token, max_age=24 * 60 * 60)
    return result


@router.post("/users/change-password", response_model=UserLoginResponse)
async def change_own_password_endpoint(
    data: UserPasswordChange,
    response: Response,
    current: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Let an employee replace an initial/reset password before using OAuth."""
    try:
        result = await change_own_password(
            db,
            current.user,
            data.old_password,
            data.new_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    set_session_cookie(response, user_session_cookie_name(), result.access_token, max_age=24 * 60 * 60)
    return result


@router.post("/users/logout", status_code=204)
async def logout_user_endpoint(
    response: Response,
    current: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke this employee's sessions and clear the browser session cookie."""

    result = await db.execute(select(User).where(User.id == current.user.id).with_for_update())
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    user.auth_epoch += 1
    await revoke_user_refresh_tokens(db, user.id)
    await db.flush()
    clear_cookie(response, user_session_cookie_name())


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
    权限：enterprise_admin 可重置本组织用户、platform_super_admin 全局可重置。
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
