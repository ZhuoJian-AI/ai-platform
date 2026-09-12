"""Read an original operation receipt; never dispatch a business mutation."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.models.enterprise_application import EnterpriseApplicationAction, EnterpriseApplicationActionRequest
from app.models.task import Task, TaskMessage
from app.services import enterprise_application_service, subsystem_action_service
from app.utils.crypto import decrypt_provider_api_key


def recovery_tool_name(action_name: str) -> str:
    return "resume_action_" + hashlib.sha256(action_name.encode()).hexdigest()[:16]


def repeat_tool_name(action_name: str) -> str:
    return "repeat_action_" + hashlib.sha256(action_name.encode()).hexdigest()[:16]


def retain_completed_provenance(state: dict, result: dict) -> None:
    """Carry verified execution evidence into later artifact creation.

    A replay keeps the original timestamp and request reference. Pending,
    unknown and failed results are not evidence of a successful business step.
    """
    if result.get("status") != "completed" or not isinstance(result.get("provenance"), dict):
        return
    payload = result.get("result") if isinstance(result.get("result"), dict) else {}
    provenance = {
        **result["provenance"],
        "snapshot_id": payload.get("snapshotId"),
        "snapshot_at": payload.get("snapshotAt"),
    }
    if result.get("replayed"):
        provenance["replayed"] = True
    rows = state.setdefault("business_action_provenance", [])
    if not rows or rows[-1] != provenance:
        rows.append(provenance)


def history_request_ids(state: dict, action_name: str) -> list[str]:
    names = {action_name, recovery_tool_name(action_name), repeat_tool_name(action_name)}
    references = []
    for message in state.get("messages") or []:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        context = message.get("business_context")
        rows = context.get("toolResultRefs") if isinstance(context, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows[-20:]:
            if not isinstance(row, dict) or row.get("name") not in names:
                continue
            request_id = row.get("requestId")
            if isinstance(request_id, str) and 0 < len(request_id) <= 160:
                references.append(request_id)
    return list(dict.fromkeys(references))[-20:]


async def recover_action_result(db, application, action, user, request_id, allowed_ids, page_key):
    if request_id not in allowed_ids:
        raise HTTPException(status_code=403, detail="只能恢复当前对话中该业务操作的原始引用")
    current = await enterprise_application_service.get_application(db, application.id)
    if current is None or str(current.organization_id) != str(user.organization_id):
        raise HTTPException(status_code=404, detail="业务应用不存在")
    action = (await db.execute(select(EnterpriseApplicationAction).where(
        EnterpriseApplicationAction.id == action.id,
        EnterpriseApplicationAction.application_id == current.id,
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if action is None or not current.assistant_enabled or not action.is_active or not action.ai_enabled:
        raise HTTPException(status_code=403, detail="该业务操作当前不可用")
    required = subsystem_action_service.OPERATION_PERMISSION[action.operation]
    await enterprise_application_service.assert_page_permission(db, current.id, user, action.module_key,
                                                               page_key, required)
    integration = await subsystem_action_service._integration_or_409(db, current.id)
    page_actions = subsystem_action_service._manifest_page_action_keys(integration, action.module_key, page_key)
    if (page_actions is not None and action.action_key not in page_actions) or not (
        enterprise_application_service.action_allowed_for_user(
            current, user, action.module_key, page_key, action.action_key, required,
        )
    ):
        raise HTTPException(status_code=403, detail="当前角色无权恢复该页面的业务操作")
    row = (await db.execute(select(EnterpriseApplicationActionRequest).where(
        EnterpriseApplicationActionRequest.application_id == current.id,
        EnterpriseApplicationActionRequest.organization_id == current.organization_id,
        EnterpriseApplicationActionRequest.user_id == UUID(str(user.id)),
        EnterpriseApplicationActionRequest.action_id == action.id,
        EnterpriseApplicationActionRequest.module_key == action.module_key,
        EnterpriseApplicationActionRequest.request_id == request_id,
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="原操作记录不存在，未重新提交")
    if not row.params_encrypted:
        raise HTTPException(status_code=409, detail="旧记录缺少页面绑定，无法安全恢复；请核实原操作结果")
    _, original_page, _ = subsystem_action_service._decode_request_payload(
        decrypt_provider_api_key(row.params_encrypted),
    )
    if original_page != page_key:
        raise HTTPException(status_code=409, detail="请先定位到原操作页面再恢复")
    result = subsystem_action_service.action_result(row, current, action, page_key=page_key)
    if row.status == "pending" and row.expires_at <= datetime.now(UTC):
        result.update(status="expired", confirmation_id=None, error="原确认卡片已过期，请重新提出并确认操作")
    result["replayed"] = True
    result["provenance"]["executedAt"] = row.resolved_at.isoformat() if row.resolved_at else None
    return result


async def pending_request_id(db, application, action, user, allowed_ids, params, page_key, expected_version,
                             *, task_id=None):
    """Match previous proposals and executions within server-loaded Task history.

    The caller must still invoke the normal service with this ID: it rechecks
    current authorization and the stored parameter/page/version binding.
    """
    if (not allowed_ids and not task_id) or action.operation not in {"create", "update", "delete", "approve"}:
        return None
    history_filter = EnterpriseApplicationActionRequest.request_id.in_(allowed_ids[-20:])
    if task_id:
        # Search durable references separately from the LLM's short context window.
        # A client cannot nominate another Task or inject assistant-role metadata.
        owned_reference = select(TaskMessage.id).join(Task, Task.id == TaskMessage.task_id).where(
            Task.id == UUID(str(task_id)), Task.user_id == UUID(str(user.id)),
            Task.organization_id == user.organization_id, Task.deleted_at.is_(None),
            TaskMessage.role == "assistant",
            TaskMessage.metadata_["tool_executions"].op("@>")(
                func.jsonb_build_array(func.jsonb_build_object(
                    "requestId", EnterpriseApplicationActionRequest.request_id,
                )),
            ),
        ).exists()
        history_filter = or_(history_filter, owned_reference)
    rows = (await db.execute(select(EnterpriseApplicationActionRequest).where(
        EnterpriseApplicationActionRequest.application_id == application.id,
        EnterpriseApplicationActionRequest.organization_id == user.organization_id,
        EnterpriseApplicationActionRequest.user_id == UUID(str(user.id)),
        EnterpriseApplicationActionRequest.action_id == action.id,
        EnterpriseApplicationActionRequest.module_key == action.module_key,
        history_filter,
        EnterpriseApplicationActionRequest.status.in_(["pending", "completed", "executing", "failed"]),
    ).order_by(EnterpriseApplicationActionRequest.created_at.desc()))).scalars().all()
    for row in rows:
        if row.status == "pending" and row.expires_at <= datetime.now(UTC):
            continue
        if row.status == "failed" and (
            not isinstance(row.result, dict) or row.result.get("executionOutcome") != "unknown"
        ):
            continue
        if not row.params_encrypted:
            raise HTTPException(409, "历史操作缺少参数绑定，不能安全判断是否已执行。请先核实原记录，勿直接重试。")
        raw = decrypt_provider_api_key(row.params_encrypted)
        binding = json.loads(raw)
        if not isinstance(binding, dict):
            raise HTTPException(409, "历史操作参数绑定无效，请先核实原记录")
        original, original_page, original_version = subsystem_action_service._decode_request_payload(
            raw,
        )
        digest = (binding.get("paramsDigest") if binding.get("_bindingOnly") == 1
                  else subsystem_action_service._params_hash(original))
        if (original_page == page_key and original_version == expected_version
                and digest == subsystem_action_service._params_hash(params)):
            return row.request_id
    return None
