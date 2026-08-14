"""DLP Rules CRUD API."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import (
    CurrentAdmin,
    require_admin,
    require_org_access,
    require_org_access_write,
)
from app.database import get_db
from app.schemas.dlp_rule import (
    DlpRuleCreate,
    DlpRuleLibraryEntry,
    DlpRuleRead,
    DlpRuleTestRequest,
    DlpRuleTestResponse,
    DlpRuleUpdate,
)
from app.services.dlp_rule_service import (
    create_dlp_rule,
    get_dlp_rule,
    list_dlp_rules,
    list_rule_library,
    soft_delete_dlp_rule,
    test_dlp_rule,
    update_dlp_rule,
)

router = APIRouter()


@router.get("/dlp-rules/library", response_model=list[DlpRuleLibraryEntry])
async def get_rule_library(_: CurrentAdmin = Depends(require_admin)):
    """规则库（代码内置、只读）：全部预置 DLP 规则定义，供「添加规则」下拉选择。"""
    return list_rule_library()


def _assert_dlp_access(auth: CurrentAdmin, rule_org_id: UUID | None) -> None:
    """DLP 规则访问校验。

    平台级账号（organization_id 为 None）不受限；组织级账号仅可访问本组织规则。
    跨组织访问被拒。规则一律归属到某组织，rule_org_id 不应为 None。
    """
    if (
        auth.organization_id is not None
        and rule_org_id is not None
        and rule_org_id != auth.organization_id
    ):
        raise HTTPException(status_code=403, detail="No access to this organization's rules")


@router.post("/organizations/{org_id}/dlp-rules", response_model=DlpRuleRead, status_code=201)
async def create_rule(org_id: UUID, data: DlpRuleCreate, auth: CurrentAdmin = Depends(require_org_access_write), db: AsyncSession = Depends(get_db)):
    return await create_dlp_rule(db, org_id, data)


@router.get("/organizations/{org_id}/dlp-rules", response_model=list[DlpRuleRead])
async def list_rules(org_id: UUID, _: CurrentAdmin = Depends(require_org_access), db: AsyncSession = Depends(get_db)):
    return await list_dlp_rules(db, org_id)


@router.get("/dlp-rules/{rule_id}", response_model=DlpRuleRead)
async def get_rule(rule_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rule = await get_dlp_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="DLP rule not found")
    _assert_dlp_access(auth, rule.organization_id)
    return rule


@router.patch("/dlp-rules/{rule_id}", response_model=DlpRuleRead)
async def update_rule(rule_id: UUID, data: DlpRuleUpdate, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rule = await get_dlp_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="DLP rule not found")
    _assert_dlp_access(auth, rule.organization_id)
    # 组织级账号的作用域护栏（平台级账号不受限）：不得把规则挪到别的组织。
    # 不允许提升为全局——scope_type 正则已限制为 organization/department/team。
    if auth.organization_id is not None:
        changes = data.model_dump(exclude_unset=True)
        effective_org = changes.get("organization_id", rule.organization_id)
        if effective_org is not None and effective_org != auth.organization_id:
            raise HTTPException(
                status_code=403,
                detail="Cannot move rules to another organization",
            )
    return await update_dlp_rule(db, rule, data)


@router.delete("/dlp-rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: UUID, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rule = await get_dlp_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="DLP rule not found")
    _assert_dlp_access(auth, rule.organization_id)
    await soft_delete_dlp_rule(db, rule)


@router.post("/dlp-rules/{rule_id}/test", response_model=DlpRuleTestResponse)
async def test_rule(rule_id: UUID, data: DlpRuleTestRequest, auth: CurrentAdmin = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rule = await get_dlp_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="DLP rule not found")
    _assert_dlp_access(auth, rule.organization_id)
    result = await test_dlp_rule(rule, data.text, data.direction)
    return DlpRuleTestResponse(**result)
