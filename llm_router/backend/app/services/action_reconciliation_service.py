"""Evidence-based administrative reconciliation; never dispatch a business call."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import raiseload, selectinload

from app.auth.admin_auth import assert_org_access, assert_org_write_access
from app.models.audit_log import AuditLog
from app.models.enterprise_application import EnterpriseApplicationActionRequest as ActionRequest


def serialize(row):
    return {
        "id": str(row.id), "request_id": row.request_id,
        "module_key": row.module_key, "action_name": row.action.name,
        "user_id": str(row.user_id), "status": row.status,
        "created_at": row.created_at, "resolved_at": row.resolved_at,
        "reconciliation": (row.result or {}).get("reconciliation"),
    }


async def list_requests(db, application, auth):
    assert_org_access(auth, application.organization_id)
    rows = (await db.execute(
        select(ActionRequest).options(raiseload("*"), selectinload(ActionRequest.action)).where(
            ActionRequest.application_id == application.id,
            ActionRequest.organization_id == application.organization_id,
            or_(
                ActionRequest.result["executionOutcome"].astext == "unknown",
                ActionRequest.result["reconciliation"].is_not(None),
            ),
        ).order_by(ActionRequest.created_at.desc()).limit(100)
    )).scalars().all()
    return [serialize(row) for row in rows]


def apply_resolution(row, *, decision, evidence, admin_id):
    """Called under a row lock. In-flight requests cannot be overwritten."""
    if decision not in {"executed", "not_executed"} or not evidence.strip():
        raise HTTPException(422, "请选择核实结论并填写业务回执或核查证据")
    previous = (row.result or {}).get("reconciliation")
    if previous:
        if (previous.get("decision"), previous.get("evidence"), previous.get("admin_id")) == (
            decision, evidence.strip(), admin_id,
        ):
            return False
        raise HTTPException(409, "该操作已经核实，请刷新查看；不能覆盖原结论")
    if row.status != "failed" or (row.result or {}).get("executionOutcome") != "unknown":
        raise HTTPException(409, "仅可核实已结束且结果未知的请求；执行中的请求不能人工覆盖")
    now = datetime.now(UTC)
    row.result = {
        **(row.result or {}),
        "executionOutcome": decision,
        "reconciliation": {
            "decision": decision, "evidence": evidence.strip(),
            "admin_id": admin_id, "verified_at": now.isoformat(),
            "source": "administrator_evidence",
        },
    }
    # Retain the encrypted binding as a duplicate barrier for verified writes.
    # No remote payload or Artifact is fabricated by a human determination.
    row.status = "completed" if decision == "executed" else "rejected"
    row.error = None if decision == "executed" else "管理员已核实未执行；如需重试，必须重新确认"
    row.resolved_at = row.updated_at = now
    return True


async def reconcile(db, application, auth, request_id: UUID, *, decision, evidence):
    assert_org_write_access(auth, application.organization_id)
    row = (await db.execute(
        select(ActionRequest).options(raiseload("*"), selectinload(ActionRequest.action)).where(
            ActionRequest.id == request_id,
            ActionRequest.application_id == application.id,
            ActionRequest.organization_id == application.organization_id,
        ).with_for_update().execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "未找到本应用的待核实操作")
    if apply_resolution(row, decision=decision, evidence=evidence, admin_id=auth.id):
        db.add(AuditLog(
            request_id=str(row.id), organization_id=str(application.organization_id),
            event_type="action_reconciliation", status_code=200,
            metadata_={"application_id": str(application.id), **row.result["reconciliation"]},
        ))
        await db.flush()
    return serialize(row)
