"""Organizations CRUD API."""

import base64
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.auth.admin_auth import (
    CurrentAdmin,
    is_org_scoped,
    require_admin,
    require_admin_role,
    require_org_access,
    require_org_access_write,
)
from app.database import get_db
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)
from app.services.organization_service import (
    create_organization,
    get_default_organization,
    get_organization,
    get_organization_by_slug,
    list_organizations,
    set_default_organization,
    soft_delete_organization,
    update_organization,
)

router = APIRouter()
logger = structlog.get_logger()


@router.post("/organizations", response_model=OrganizationRead, status_code=201)
async def create_org(data: OrganizationCreate, _: CurrentAdmin = Depends(require_admin_role), db: AsyncSession = Depends(get_db)):
    try:
        return await create_organization(db, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists")


@router.get("/organizations", response_model=list[OrganizationRead])
async def list_orgs(auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """列出组织。组织级账号仅返回自己被指派的组织；平台级账号返回全部。"""
    orgs = await list_organizations(db)
    if is_org_scoped(auth):
        return [o for o in orgs if o.id == auth.organization_id]
    return orgs


@router.get("/organizations/default", response_model=OrganizationRead)
async def get_default_org(auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """返回默认组织。组织级账号返回自己被指派的组织（忽略平台默认设定）。"""
    if is_org_scoped(auth):
        org = await get_organization(db, auth.organization_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        return org
    org = await get_default_organization(db)
    if not org:
        raise HTTPException(status_code=404, detail="No default organization set")
    return org


@router.get("/organizations/{org_id}", response_model=OrganizationRead)
async def get_org(org_id: UUID, _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db)):
    org = await get_organization(db, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.post("/organizations/{org_id}/default", response_model=OrganizationRead)
async def set_default_org(org_id: UUID, _: CurrentAdmin = Depends(require_admin_role), db: AsyncSession = Depends(get_db)):
    """将指定组织设为平台默认组织（仅平台级账号）。"""
    org = await get_organization(db, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return await set_default_organization(db, org)


@router.patch("/organizations/{org_id}", response_model=OrganizationRead)
async def update_org(org_id: UUID, data: OrganizationUpdate, _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db)):
    org = await get_organization(db, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        return await update_organization(db, org, data)
    except IntegrityError as exc:
        await db.rollback()
        # 记录真实冲突信息（原 detail 只硬编码 slug，掩盖 workspaces/memories 等表的真实约束冲突）
        logger.error("org_update_integrity_error",
                     org_id=str(org_id), slug=data.slug, name=data.name,
                     orig=str(getattr(exc, "orig", None) or exc))
        raise HTTPException(
            status_code=409,
            detail=f"Slug '{data.slug}' already exists (orig: {getattr(exc, 'orig', None) or exc})",
        )


@router.delete("/organizations/{org_id}", status_code=204)
async def delete_org(org_id: UUID, _: CurrentAdmin = Depends(require_admin_role), db: AsyncSession = Depends(get_db)):
    """删除组织（仅平台级账号；组织级账号不可删除自己组织）。"""
    org = await get_organization(db, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    await soft_delete_organization(db, org)


# ── 联系方式图片（组织管理员上传，登录页免登录读取） ────────────────────

CONTACT_IMAGE_MAX_BYTES = 2 * 1024 * 1024  # 2MB，避免 JSONB 爆炸


@router.post("/organizations/{org_id}/contact-image", status_code=204)
async def upload_contact_image(
    org_id: UUID,
    file: UploadFile = File(...),
    _: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    """上传/更新组织联系二维码图片。

    存入 ``organization.settings.contact_image = {"data": base64, "mime": ...}``。
    组织级账号仅能给自己组织上传；平台级账号可给任意组织上传。
    """
    org = await get_organization(db, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    mime = (file.content_type or "image/png").lower()
    if not mime.startswith("image/"):
        raise HTTPException(status_code=400, detail="仅支持图片格式")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(raw) > CONTACT_IMAGE_MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"图片过大（>{CONTACT_IMAGE_MAX_BYTES // 1024}KB）")
    settings = dict(org.settings or {})
    settings["contact_image"] = {
        "data": base64.b64encode(raw).decode(),
        "mime": mime,
    }
    org.settings = settings
    await db.flush()


@router.delete("/organizations/{org_id}/contact-image", status_code=204)
async def delete_contact_image(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access_write),
    db: AsyncSession = Depends(get_db),
):
    """删除组织联系二维码图片。"""
    org = await get_organization(db, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    settings = dict(org.settings or {})
    if "contact_image" in settings:
        settings.pop("contact_image")
        org.settings = settings
        await db.flush()


@router.get("/public/orgs/{slug}/contact-image")
async def get_public_contact_image(slug: str, db: AsyncSession = Depends(get_db)):
    """免登录访问：组织管理端 / 终端登录页「联系我们」弹出的二维码图片。

    未配置时返回 404，前端据此不弹框。无组织 slug 时登录页直接不渲染「联系我们」入口。
    """
    org = await get_organization_by_slug(db, slug)
    if not org:
        raise HTTPException(status_code=404, detail="Not configured")
    ci = (org.settings or {}).get("contact_image")
    if not isinstance(ci, dict) or not ci.get("data"):
        raise HTTPException(status_code=404, detail="Not configured")
    mime = (ci.get("mime") or "image/png").lower()
    try:
        raw = base64.b64decode(ci.get("data") or "")
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid image data")
    return Response(content=raw, media_type=mime)
