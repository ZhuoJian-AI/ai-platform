"""Admin management API — login, CRUD, password change."""

import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import CurrentAdmin, require_admin
from app.auth.login_throttle import (
    assert_login_allowed,
    clear_login_failures,
    record_login_failure,
)
from app.auth.mfa import (
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    matching_totp_counter,
    provisioning_uri,
)
from app.auth.session_cookies import (
    admin_csrf_cookie_name,
    admin_session_cookie_name,
    clear_cookie,
    set_admin_csrf_cookie,
    set_session_cookie,
)
from app.database import get_db
from app.models.admin import Admin
from app.schemas.admin import (
    AdminCreate,
    AdminRead,
    AdminUpdate,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    MfaCodeRequest,
    OrgInfoResponse,
)
from app.services.admin_service import (
    admin_read_with_org,
    assert_can_manage_admin,
    change_password,
    create_access_token,
    create_admin,
    delete_admin,
    get_admin,
    list_admins,
    login,
    update_admin,
)
from app.services.organization_service import get_org_public_by_slug
from app.utils.crypto import decrypt_provider_api_key, encrypt_provider_api_key
from app.utils.request_source import client_source

router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse)
async def login_endpoint(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """管理员登录。

    - 带 slug：组织门户登录，仅匹配该组织的 enterprise_admin。
    - 不带 slug：平台登录，仅匹配 platform_super_admin。
    """
    identity = f"{data.slug or 'platform'}:{data.username}"
    source = client_source(request)
    await assert_login_allowed("admin", identity, source)
    try:
        result = await login(db, data.username, data.password, slug=data.slug, mfa_code=data.mfa_code)
    except HTTPException as exc:
        # A correct password entering the second MFA step is not a failed
        # login. Invalid MFA codes still consume the shared throttle budget.
        if exc.detail != "MFA_REQUIRED":
            await record_login_failure("admin", identity, source)
        raise
    if result is None:
        await record_login_failure("admin", identity, source)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    await clear_login_failures("admin", identity, source)
    set_session_cookie(
        response,
        admin_session_cookie_name(),
        result.access_token,
        max_age=24 * 60 * 60,
    )
    result.csrf_token = set_admin_csrf_cookie(response)
    return result


@router.post("/auth/mfa/setup")
async def setup_mfa_endpoint(
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a pending TOTP seed; confirmation is required before enabling."""
    admin = (
        await db.execute(select(Admin).where(Admin.id == auth.admin.id).with_for_update())
    ).scalar_one()
    if admin.mfa_enabled:
        raise HTTPException(status_code=409, detail="MFA is already enabled")
    secret = (
        decrypt_provider_api_key(admin.mfa_secret_encrypted)
        if admin.mfa_secret_encrypted
        else generate_totp_secret()
    )
    admin.mfa_secret_encrypted = encrypt_provider_api_key(secret)
    admin.mfa_recovery_code_hashes = []
    admin.mfa_last_totp_counter = None
    await db.flush()
    return {
        "secret": secret,
        "provisioning_uri": provisioning_uri(secret, auth.admin.username),
    }


@router.post("/auth/mfa/confirm")
async def confirm_mfa_endpoint(
    data: MfaCodeRequest,
    response: Response,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Verify enrollment and return one-time recovery codes plus a full session."""
    admin = (
        await db.execute(select(Admin).where(Admin.id == auth.admin.id).with_for_update())
    ).scalar_one()
    if admin.mfa_enabled:
        raise HTTPException(status_code=409, detail="MFA is already enabled")
    encrypted = admin.mfa_secret_encrypted
    if not encrypted:
        raise HTTPException(status_code=409, detail="Start MFA setup first")
    secret = decrypt_provider_api_key(encrypted)
    counter = matching_totp_counter(secret, data.code)
    if counter is None:
        raise HTTPException(status_code=400, detail="Invalid verification code")
    recovery_codes = generate_recovery_codes()
    admin.mfa_recovery_code_hashes = [hash_recovery_code(code) for code in recovery_codes]
    admin.mfa_enabled = True
    admin.mfa_last_totp_counter = counter
    admin.mfa_verified_at = datetime.now(UTC)
    admin.auth_epoch += 1
    await db.flush()
    token = create_access_token(admin, mfa_verified=True)
    set_session_cookie(response, admin_session_cookie_name(), token, max_age=24 * 60 * 60)
    csrf_token = set_admin_csrf_cookie(response)
    return {
        "recovery_codes": recovery_codes,
        "access_token": token,
        "token_type": "bearer",
        "csrf_token": csrf_token,
        "admin": (await admin_read_with_org(db, admin)).model_dump(mode="json"),
    }


@router.get("/auth/csrf")
async def csrf_endpoint(
    response: Response,
    _: CurrentAdmin = Depends(require_admin),
):
    """Rotate the readable double-submit token for a valid admin session."""
    return {"csrf_token": set_admin_csrf_cookie(response)}


@router.post("/auth/logout", status_code=204)
async def logout_endpoint(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Clear browser credentials and revoke valid administrator sessions."""
    cookie_csrf = request.cookies.get(admin_csrf_cookie_name(), "")
    header_csrf = request.headers.get("x-csrf-token", "")
    if cookie_csrf and not hmac.compare_digest(cookie_csrf, header_csrf):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token")
    try:
        current = await require_admin(request, db)
    except HTTPException:
        current = None
    if current is not None:
        # JWTs are stateless, so logout advances the account epoch. This logs
        # out other administrator sessions too instead of leaving a copied
        # 24-hour bearer usable after the browser says it logged out.
        current.admin.auth_epoch += 1
        await db.flush()
    clear_cookie(response, admin_session_cookie_name())
    clear_cookie(response, admin_csrf_cookie_name(), httponly=False)
    return response


@router.get("/auth/org-info/{slug}", response_model=OrgInfoResponse)
async def org_info_endpoint(slug: str, db: AsyncSession = Depends(get_db)):
    """公开端点：按 slug 查询组织名，供组织门户登录页展示。组织不存在返回 404。"""
    info = await get_org_public_by_slug(db, slug)
    if info is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    name, real_slug = info
    return OrgInfoResponse(name=name, slug=real_slug)


@router.get("/auth/me", response_model=AdminRead)
async def get_current_admin(auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """获取当前登录管理员信息。"""
    return await admin_read_with_org(db, auth.admin)


@router.post("/auth/change-password")
async def change_password_endpoint(
    data: ChangePasswordRequest,
    response: Response,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """修改当前管理员密码。"""
    ok = await change_password(db, auth.admin, data.old_password, data.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    clear_cookie(response, admin_session_cookie_name())
    clear_cookie(response, admin_csrf_cookie_name(), httponly=False)
    return {"message": "Password changed"}


@router.get("/admins", response_model=list[AdminRead])
async def list_admins_endpoint(
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """平台超管查看全部；企业管理员只查看本企业的企业管理员。"""
    admins = await list_admins(db, actor=auth.admin)
    return [await admin_read_with_org(db, a) for a in admins]


@router.post("/admins", response_model=AdminRead, status_code=201)
async def create_admin_endpoint(
    data: AdminCreate,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建管理员。企业管理员只能在本企业创建同级管理员。

    用户名唯一性由 DB partial unique index 兜底：
    组织级账号在所属组织内唯一，平台级账号全局唯一。冲突返回 409。
    """
    try:
        admin = await create_admin(db, data, actor=auth.admin)
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists in this scope")
    return await admin_read_with_org(db, admin)


@router.get("/admins/{admin_id}", response_model=AdminRead)
async def get_admin_endpoint(
    admin_id: int,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取管理员详情。"""
    admin = await get_admin(db, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    assert_can_manage_admin(auth.admin, admin)
    return await admin_read_with_org(db, admin)


@router.patch("/admins/{admin_id}", response_model=AdminRead)
async def update_admin_endpoint(
    admin_id: int,
    data: AdminUpdate,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新管理员；角色和企业绑定不可变，且禁止自停用或停用最后一名企业管理员。"""
    admin = await get_admin(db, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    updated = await update_admin(db, admin, data, actor=auth.admin)
    return await admin_read_with_org(db, updated)


@router.delete("/admins/{admin_id}", status_code=204)
async def delete_admin_endpoint(
    admin_id: int,
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """停用并撤销管理员会话；不物理删除审计主体。"""
    admin = await get_admin(db, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    await delete_admin(db, admin, actor=auth.admin)
