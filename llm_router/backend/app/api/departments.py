"""Departments CRUD API."""

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
from app.schemas.organization import DepartmentCreate, DepartmentRead, DepartmentUpdate
from app.services.organization_service import (
    create_department,
    get_department,
    get_organization,
    list_departments,
    soft_delete_department,
    update_department,
)

router = APIRouter()


@router.post("/organizations/{org_id}/departments", response_model=DepartmentRead, status_code=201)
async def create_dept(org_id: UUID, data: DepartmentCreate, _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db)):
    org = await get_organization(db, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        return await create_department(db, org_id, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists in this organization")


@router.get("/organizations/{org_id}/departments", response_model=list[DepartmentRead])
async def list_depts(org_id: UUID, _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db)):
    return await list_departments(db, org_id)


@router.get("/departments/{dept_id}", response_model=DepartmentRead)
async def get_dept(dept_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    dept = await get_department(db, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    assert_org_access(auth, dept.organization_id)
    return dept


@router.patch("/departments/{dept_id}", response_model=DepartmentRead)
async def update_dept(dept_id: UUID, data: DepartmentUpdate, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    dept = await get_department(db, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    assert_org_write_access(auth, dept.organization_id)
    try:
        return await update_department(db, dept, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Slug '{data.slug}' already exists in this organization")


@router.delete("/departments/{dept_id}", status_code=204)
async def delete_dept(dept_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    dept = await get_department(db, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    assert_org_write_access(auth, dept.organization_id)
    await soft_delete_department(db, dept)
