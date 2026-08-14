"""Audit Logs query API."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import CurrentAdmin, require_org_access
from app.database import get_db
from app.models.audit_log import AuditLog

router = APIRouter()


@router.get("/organizations/{org_id}/audit-logs")
async def list_audit_logs(
    org_id: UUID,
    _: CurrentAdmin = Depends(require_org_access),
    db: AsyncSession = Depends(get_db),
    event_type: str | None = Query(None),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """查询审计日志（分页）。"""
    query = select(AuditLog).where(AuditLog.organization_id == str(org_id))

    if event_type:
        query = query.where(AuditLog.event_type == event_type)
    if start_time:
        query = query.where(AuditLog.created_at >= start_time)
    if end_time:
        query = query.where(AuditLog.created_at <= end_time)

    query = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    logs = list(result.scalars().all())

    # 计数
    count_query = select(func.count()).select_from(AuditLog).where(AuditLog.organization_id == str(org_id))
    if event_type:
        count_query = count_query.where(AuditLog.event_type == event_type)
    if start_time:
        count_query = count_query.where(AuditLog.created_at >= start_time)
    if end_time:
        count_query = count_query.where(AuditLog.created_at <= end_time)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    return {"total": total, "offset": offset, "limit": limit, "data": logs}
