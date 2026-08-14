"""LLM Providers CRUD API."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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
from app.schemas.llm_provider import LlmProviderCreate, LlmProviderRead, LlmProviderUpdate
from app.services.llm_provider_service import (
    create_provider,
    get_provider,
    list_providers,
    soft_delete_provider,
    update_provider,
)
from app.services.organization_service import get_department, get_team

router = APIRouter()


@router.post("/organizations/{org_id}/providers", response_model=LlmProviderRead, status_code=201)
async def create_provider_endpoint(org_id: UUID, data: LlmProviderCreate, _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db)):
    if data.scope_type != "organization":
        raise HTTPException(status_code=400, detail="scope_type must be 'organization' for this endpoint")
    return await create_provider(db, org_id, data)


@router.post("/departments/{dept_id}/providers", response_model=LlmProviderRead, status_code=201)
async def create_dept_provider_endpoint(dept_id: UUID, data: LlmProviderCreate, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """创建部门级提供商：调用解析遵循 团队>部门>组织 优先级且继承。"""
    if data.scope_type != "department":
        raise HTTPException(status_code=400, detail="scope_type must be 'department' for this endpoint")
    dept = await get_department(db, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    assert_org_write_access(auth, dept.organization_id)
    return await create_provider(db, dept.organization_id, data, dept_id=dept_id)


@router.post("/teams/{team_id}/providers", response_model=LlmProviderRead, status_code=201)
async def create_team_provider_endpoint(team_id: UUID, data: LlmProviderCreate, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """创建团队级提供商：调用解析遵循 团队>部门>组织 优先级且继承。"""
    if data.scope_type != "team":
        raise HTTPException(status_code=400, detail="scope_type must be 'team' for this endpoint")
    team = await get_team(db, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    assert_org_write_access(auth, team.organization_id)
    return await create_provider(db, team.organization_id, data, team_id=team_id)


@router.get("/organizations/{org_id}/providers", response_model=list[LlmProviderRead])
async def list_providers_endpoint(org_id: UUID, _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db)):
    return await list_providers(db, org_id)


@router.get("/providers/{provider_id}", response_model=LlmProviderRead)
async def get_provider_endpoint(provider_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    provider = await get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    assert_org_access(auth, provider.organization_id)
    return provider


@router.patch("/providers/{provider_id}", response_model=LlmProviderRead)
async def update_provider_endpoint(provider_id: UUID, data: LlmProviderUpdate, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    provider = await get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    assert_org_write_access(auth, provider.organization_id)
    return await update_provider(db, provider, data)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider_endpoint(provider_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    provider = await get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    assert_org_write_access(auth, provider.organization_id)
    await soft_delete_provider(db, provider)
