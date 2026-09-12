"""Read an original operation receipt; never dispatch a business mutation."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.models.enterprise_application import EnterpriseApplicationAction, EnterpriseApplicationActionRequest
from app.services import enterprise_application_service, subsystem_action_service
from app.utils.crypto import decrypt_provider_api_key


def recovery_tool_name(action_name: str) -> str:
    return "resume_action_" + hashlib.sha256(action_name.encode()).hexdigest()[:16]


def history_request_ids(state: dict, action_name: str) -> list[str]:
    names = {action_name, recovery_tool_name(action_name)}
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
