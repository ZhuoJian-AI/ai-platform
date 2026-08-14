"""Routing Policies CRUD API."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
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
from app.models.routing_policy import RoutingPolicy
from app.schemas.routing_policy import RoutingPolicyCreate, RoutingPolicyRead, RoutingPolicyUpdate

router = APIRouter()


@router.post("/organizations/{org_id}/routing-policies", response_model=RoutingPolicyRead, status_code=201)
async def create_policy(org_id: UUID, data: RoutingPolicyCreate, _: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db)):
    policy = RoutingPolicy(organization_id=org_id, **data.model_dump())
    db.add(policy)
    await db.flush()
    return policy


@router.get("/organizations/{org_id}/routing-policies", response_model=list[RoutingPolicyRead])
async def list_policies(org_id: UUID, _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RoutingPolicy).where(
            RoutingPolicy.organization_id == org_id, RoutingPolicy.deleted_at.is_(None)
        )
    )
    return list(result.scalars().all())


@router.get("/routing-policies/{policy_id}", response_model=RoutingPolicyRead)
async def get_policy(policy_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RoutingPolicy).where(RoutingPolicy.id == policy_id, RoutingPolicy.deleted_at.is_(None))
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Routing policy not found")
    assert_org_access(auth, policy.organization_id)
    return policy


@router.patch("/routing-policies/{policy_id}", response_model=RoutingPolicyRead)
async def update_policy(policy_id: UUID, data: RoutingPolicyUpdate, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RoutingPolicy).where(RoutingPolicy.id == policy_id, RoutingPolicy.deleted_at.is_(None))
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Routing policy not found")
    assert_org_write_access(auth, policy.organization_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)
    await db.flush()
    return policy


@router.delete("/routing-policies/{policy_id}", status_code=204)
async def delete_policy(policy_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RoutingPolicy).where(RoutingPolicy.id == policy_id, RoutingPolicy.deleted_at.is_(None))
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Routing policy not found")
    assert_org_write_access(auth, policy.organization_id)
    policy.deleted_at = datetime.now(UTC)
    await db.flush()
