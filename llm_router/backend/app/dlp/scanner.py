"""DLP Scanner — scans request/response content through the DLP engine."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dlp.engine import DLPEngine, DLPResult
from app.models.dlp_rule import DlpRule


async def collect_applicable_rules(
    db: AsyncSession,
    org_id: str,
    dept_id: str | None = None,
    team_id: str | None = None,
    direction: str = "both",
) -> list[DlpRule]:
    """收集适用于当前请求的所有 DLP 规则。

    规则来源（取并集，安全规则只增不减）:
    1. 组织规则 (scope_type='organization', organization_id=org_id)
    2. 部门规则 (scope_type='department', scope_id=dept_id)
    3. 团队规则 (scope_type='team', scope_id=team_id)
    """
    result = await db.execute(
        select(DlpRule).where(
            DlpRule.is_active.is_(True),
            DlpRule.deleted_at.is_(None),
            (DlpRule.direction == direction) | (DlpRule.direction == "both"),
            (
                ((DlpRule.scope_type == "organization") & (DlpRule.organization_id == org_id))
                | ((DlpRule.scope_type == "department") & (DlpRule.scope_id == dept_id) if dept_id else False)
                | ((DlpRule.scope_type == "team") & (DlpRule.scope_id == team_id) if team_id else False)
            ),
        ).order_by(DlpRule.priority.desc())
    )
    return list(result.scalars().all())


async def scan_request(
    db: AsyncSession,
    text: str,
    org_id: str,
    dept_id: str | None = None,
    team_id: str | None = None,
) -> DLPResult:
    """扫描请求内容。"""
    rules = await collect_applicable_rules(db, org_id, dept_id, team_id, direction="request")
    if not rules:
        return DLPResult()
    engine = DLPEngine(rules=rules)
    return await engine.scan(text, direction="request")


async def scan_response(
    db: AsyncSession,
    text: str,
    org_id: str,
    dept_id: str | None = None,
    team_id: str | None = None,
) -> DLPResult:
    """扫描响应内容。"""
    rules = await collect_applicable_rules(db, org_id, dept_id, team_id, direction="response")
    if not rules:
        return DLPResult()
    engine = DLPEngine(rules=rules)
    return await engine.scan(text, direction="response")
