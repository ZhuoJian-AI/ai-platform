"""JudgeTemplate CRUD API."""

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
from app.database import get_db
from app.schemas.judge import JudgeTemplateCreate, JudgeTemplateRead, JudgeTemplateUpdate
from app.services.judge_service import (
    create_judge,
    get_judge,
    list_judges,
    soft_delete_judge,
    update_judge,
)

router = APIRouter()


@router.post("/organizations/{org_id}/judges", response_model=JudgeTemplateRead, status_code=201)
async def create_judge_endpoint(
    org_id: UUID, data: JudgeTemplateCreate,
    _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db),
):
    try:
        return await create_judge(db, org_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists")


@router.get("/organizations/{org_id}/judges", response_model=list[JudgeTemplateRead])
async def list_judges_endpoint(
    org_id: UUID, _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db),
):
    return await list_judges(db, org_id)


@router.get("/judges/{judge_id}", response_model=JudgeTemplateRead)
async def get_judge_endpoint(
    judge_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    jt = await get_judge(db, judge_id)
    if not jt:
        raise HTTPException(status_code=404, detail="Judge template not found")
    assert_org_access(auth, jt.organization_id)
    return jt


@router.patch("/judges/{judge_id}", response_model=JudgeTemplateRead)
async def update_judge_endpoint(
    judge_id: UUID, data: JudgeTemplateUpdate,
    auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    jt = await get_judge(db, judge_id)
    if not jt:
        raise HTTPException(status_code=404, detail="Judge template not found")
    assert_org_write_access(auth, jt.organization_id)
    return await update_judge(db, jt, data)


@router.delete("/judges/{judge_id}", status_code=204)
async def delete_judge_endpoint(
    judge_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    jt = await get_judge(db, judge_id)
    if not jt:
        raise HTTPException(status_code=404, detail="Judge template not found")
    assert_org_write_access(auth, jt.organization_id)
    await soft_delete_judge(db, jt)
