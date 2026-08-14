"""API Keys CRUD API."""

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
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyRead, ApiKeyUpdate, _ApiKeyReadInner
from app.services.api_key_service import (
    create_api_key,
    get_api_key,
    get_decrypted_key,
    list_api_keys,
    revoke_api_key,
    update_api_key,
)
from app.services.organization_service import get_department, get_team

router = APIRouter()


def _build_read(api_key, include_key: bool = False) -> dict:
    """构造 ApiKeyRead 的 dict，注入解密后的完整 Key。"""
    decrypted = get_decrypted_key(api_key)
    # 先用不含 key_plain 的临时 schema 序列化 ORM 对象
    data = _ApiKeyReadInner.model_validate(api_key).model_dump()
    data["key_plain"] = decrypted
    if include_key:
        data["key"] = decrypted
    return data


@router.post("/organizations/{org_id}/api-keys", response_model=ApiKeyCreateResponse, status_code=201)
async def create_org_key(org_id: UUID, data: ApiKeyCreate, _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db)):
    if data.scope_type != "organization":
        raise HTTPException(status_code=400, detail="scope_type must be 'organization' for this endpoint")
    api_key, _full_key = await create_api_key(db, org_id, data)
    return ApiKeyCreateResponse(**_build_read(api_key, include_key=True))


@router.post("/departments/{dept_id}/api-keys", response_model=ApiKeyCreateResponse, status_code=201)
async def create_dept_key(dept_id: UUID, data: ApiKeyCreate, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if data.scope_type != "department":
        raise HTTPException(status_code=400, detail="scope_type must be 'department' for this endpoint")
    dept = await get_department(db, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    assert_org_write_access(auth, dept.organization_id)
    api_key, _full_key = await create_api_key(db, dept_id=dept_id, org_id=dept.organization_id, data=data)
    return ApiKeyCreateResponse(**_build_read(api_key, include_key=True))


@router.post("/teams/{team_id}/api-keys", response_model=ApiKeyCreateResponse, status_code=201)
async def create_team_key(team_id: UUID, data: ApiKeyCreate, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if data.scope_type != "team":
        raise HTTPException(status_code=400, detail="scope_type must be 'team' for this endpoint")
    team = await get_team(db, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    assert_org_write_access(auth, team.organization_id)
    api_key, _full_key = await create_api_key(db, team_id=team_id, org_id=team.organization_id, data=data)
    return ApiKeyCreateResponse(**_build_read(api_key, include_key=True))


@router.get("/organizations/{org_id}/api-keys", response_model=list[ApiKeyRead])
async def list_keys(org_id: UUID, _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db)):
    keys = await list_api_keys(db, org_id)
    return [_build_read(k) for k in keys]


@router.get("/api-keys/{key_id}", response_model=ApiKeyRead)
async def get_key(key_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    key = await get_api_key(db, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    assert_org_access(auth, key.organization_id)
    return _build_read(key)


@router.patch("/api-keys/{key_id}", response_model=ApiKeyRead)
async def update_key(key_id: UUID, data: ApiKeyUpdate, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    key = await get_api_key(db, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    assert_org_write_access(auth, key.organization_id)
    updated = await update_api_key(db, key, data)
    return _build_read(updated)


@router.post("/api-keys/{key_id}/revoke", response_model=ApiKeyRead)
async def revoke_key(key_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    key = await get_api_key(db, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    assert_org_write_access(auth, key.organization_id)
    revoked = await revoke_api_key(db, key)
    return _build_read(revoked)
