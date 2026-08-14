"""Admin management API — login, CRUD, password change."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import CurrentAdmin, require_admin, require_super_admin
from app.database import get_db
from app.models.admin import Admin
from app.schemas.admin import (
    AdminCreate,
    AdminRead,
    AdminUpdate,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    OrgInfoResponse,
)
from app.services.admin_service import (
    admin_read_with_org,
    change_password,
    create_admin,
    delete_admin,
    ensure_super_admin,
    list_admins,
    login,
    update_admin,
)
from app.services.organization_service import get_org_public_by_slug

router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse)
async def login_endpoint(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """管理员登录。

    - 带 slug：组织门户登录（/{slug}/login），仅匹配该组织下的 org_admin。
    - 不带 slug：平台登录（/login），仅匹配未绑定组织的平台级账号。
    """
    result = await login(db, data.username, data.password, slug=data.slug)
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return result


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
    auth: CurrentAdmin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """修改当前管理员密码。"""
    ok = await change_password(db, auth.admin, data.old_password, data.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    return {"message": "Password changed"}


@router.post("/auth/ensure-super-admin", response_model=AdminRead)
async def ensure_super_admin_endpoint(db: AsyncSession = Depends(get_db)):
    """确保至少存在一个 super_admin 账号。首次部署时调用。
    如果已存在 super_admin 则返回 409（不会重复创建）。
    初始密码输出到服务端日志。
    """
    result = await db.execute(
        __import__("sqlalchemy").select(Admin).where(Admin.role == "super_admin")
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Super admin already exists")
    admin = await ensure_super_admin(db)
    return AdminRead.model_validate(admin)


@router.get("/admins", response_model=list[AdminRead])
async def list_admins_endpoint(
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """列出所有管理员（仅 super_admin 可用）。"""
    admins = await list_admins(db)
    return [await admin_read_with_org(db, a) for a in admins]


@router.post("/admins", response_model=AdminRead, status_code=201)
async def create_admin_endpoint(
    data: AdminCreate,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建管理员（仅 super_admin 可用）。

    用户名唯一性由 DB partial unique index 兜底：
    组织级账号在所属组织内唯一，平台级账号全局唯一。冲突返回 409。
    """
    try:
        admin = await create_admin(db, data, created_by_id=auth.id)
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists in this scope")
    return await admin_read_with_org(db, admin)


@router.get("/admins/{admin_id}", response_model=AdminRead)
async def get_admin_endpoint(
    admin_id: int,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取管理员详情。"""
    from app.services.admin_service import get_admin
    admin = await get_admin(db, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    return await admin_read_with_org(db, admin)


@router.patch("/admins/{admin_id}", response_model=AdminRead)
async def update_admin_endpoint(
    admin_id: int,
    data: AdminUpdate,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新管理员（仅 super_admin 可用）。不允许修改自己角色为非 super_admin。"""
    from app.services.admin_service import get_admin
    admin = await get_admin(db, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    # 防止 super_admin 降低自己的角色
    if admin_id == auth.id and data.role is not None and data.role != "super_admin":
        raise HTTPException(status_code=400, detail="Cannot demote yourself")

    updated = await update_admin(
        db, admin,
        display_name=data.display_name,
        role=data.role,
        is_active=data.is_active,
        password=data.password,
        organization_id=data.organization_id,
    )
    return await admin_read_with_org(db, updated)


@router.delete("/admins/{admin_id}", status_code=204)
async def delete_admin_endpoint(
    admin_id: int,
    auth: CurrentAdmin = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除管理员（仅 super_admin 可用）。不允许删除自己。"""
    if admin_id == auth.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    from app.services.admin_service import get_admin
    admin = await get_admin(db, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    await delete_admin(db, admin)
