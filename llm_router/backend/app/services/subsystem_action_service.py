"""Authorized, replay-safe subsystem action execution and confirmation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urljoin
from uuid import UUID, uuid4

import httpx
import jwt
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.user_auth import CurrentUser
from app.models.enterprise_application import (
    EnterpriseApplication,
    EnterpriseApplicationAction,
    EnterpriseApplicationActionRequest,
    EnterpriseApplicationIntegration,
)
from app.services import enterprise_application_service
from app.utils.crypto import decrypt_provider_api_key, encrypt_provider_api_key
from app.utils.public_url import assert_public_http_url, same_origin

OPERATION_PERMISSION = {
    "query": "ai_query",
    "create": "ai_create",
    "update": "ai_update",
    "delete": "ai_delete",
    "export": "export",
}
CONFIRMATION_TTL = timedelta(minutes=5)


async def list_actions(
    db: AsyncSession, application_id: UUID | str, *, active_only: bool = False
) -> list[EnterpriseApplicationAction]:
    statement = select(EnterpriseApplicationAction).where(
        EnterpriseApplicationAction.application_id == UUID(str(application_id))
    )
    if active_only:
        statement = statement.where(EnterpriseApplicationAction.is_active.is_(True))
    return list(
        (
            await db.execute(
                statement.order_by(EnterpriseApplicationAction.module_key, EnterpriseApplicationAction.action_key)
            )
        )
        .scalars()
        .all()
    )


async def list_actions_for_user(
    db: AsyncSession, application: EnterpriseApplication, user: CurrentUser
) -> list[EnterpriseApplicationAction]:
    result: list[EnterpriseApplicationAction] = []
    for action in await list_actions(db, application.id, active_only=True):
        required = OPERATION_PERMISSION[action.operation]
        permissions = enterprise_application_service.effective_module_permissions(application, user, action.module_key)
        if action.ai_enabled and "view" in permissions and required in permissions:
            result.append(action)
    return result


def action_tool_name(application: EnterpriseApplication, action: EnterpriseApplicationAction) -> str:
    import re

    base = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{application.slug}__{action.action_key}")
    return (base[:55] + "_" + str(action.id).replace("-", "")[:8])[:64]


def _validate_params(action: EnterpriseApplicationAction, params: dict) -> None:
    schema = action.input_schema or {}
    if schema.get("type") not in {None, "object"}:
        raise HTTPException(status_code=422, detail="Subsystem action input schema must describe an object")
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    missing = [str(key) for key in required if key not in params]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing action parameters: {', '.join(missing)}")


async def _integration_or_409(db: AsyncSession, application_id: UUID | str) -> EnterpriseApplicationIntegration:
    row = (
        await db.execute(
            select(EnterpriseApplicationIntegration).where(
                EnterpriseApplicationIntegration.application_id == UUID(str(application_id))
            )
        )
    ).scalar_one_or_none()
    if row is None or not row.auth_token_encrypted or row.protocol_version < 2:
        raise HTTPException(status_code=409, detail="Protocol v2 integration secret is not configured")
    if not row.sync_enabled:
        raise HTTPException(status_code=409, detail="Subsystem integration is disabled")
    return row


def _identity_claims(
    application: EnterpriseApplication,
    action: EnterpriseApplicationAction,
    user: CurrentUser,
    request_id: str,
    permissions: set[str],
) -> dict:
    now = datetime.now(UTC)
    return {
        "iss": "zhuojian-saas",
        "aud": application.slug,
        "typ": "zhuojian-action",
        "sub": user.id,
        "organizationId": str(user.organization_id),
        "departmentId": user.department_id,
        "teamId": user.team_id,
        "moduleKey": action.module_key,
        "actionKey": action.action_key,
        "operation": action.operation,
        "permissions": sorted(permissions),
        "requestId": request_id,
        "jti": uuid4().hex,
        "iat": now,
        "exp": now + timedelta(seconds=60),
    }


def _provenance(application: EnterpriseApplication, action: EnterpriseApplicationAction, request_id: str) -> dict:
    return {
        "applicationId": str(application.id),
        "applicationSlug": application.slug,
        "moduleKey": action.module_key,
        "actionKey": action.action_key,
        "operation": action.operation,
        "requestId": request_id,
        "executedAt": datetime.now(UTC).isoformat(),
    }


async def _execute_request(
    db: AsyncSession,
    request_row: EnterpriseApplicationActionRequest,
    application: EnterpriseApplication,
    action: EnterpriseApplicationAction,
    user: CurrentUser,
) -> dict:
    integration = await _integration_or_409(db, application.id)
    permissions = enterprise_application_service.effective_module_permissions(application, user, action.module_key)
    required = OPERATION_PERMISSION[action.operation]
    if "view" not in permissions or required not in permissions or not action.is_active or not action.ai_enabled:
        raise HTTPException(status_code=403, detail="Action is no longer authorized")
    params = json.loads(decrypt_provider_api_key(request_row.params_encrypted or ""))
    secret = decrypt_provider_api_key(integration.auth_token_encrypted or "")
    token = jwt.encode(
        _identity_claims(application, action, user, request_row.request_id, permissions),
        secret,
        algorithm="HS256",
    )
    url = urljoin(
        application.entry_url.rstrip("/") + "/",
        f"api/integration/actions/{quote(action.action_key, safe='')}",
    )
    if not same_origin(application.entry_url, url):
        raise HTTPException(status_code=409, detail="Action endpoint left the registered application origin")
    try:
        assert_public_http_url(url, require_https=True)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    request_row.status = "executing"
    await db.flush()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=8.0), follow_redirects=False) as client:
            response = await client.post(
                url,
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                    "user-agent": "ZhuoJian-Subsystem-Action/2.0",
                },
                json={
                    "moduleKey": action.module_key,
                    "params": params,
                    "requestId": request_row.request_id,
                },
            )
        if 300 <= response.status_code < 400:
            raise RuntimeError("Subsystem action endpoint must not redirect")
        response.raise_for_status()
        if len(response.content) > 2 * 1024 * 1024:
            raise ValueError("Subsystem action response exceeds 2MB")
        body = response.json()
        result = body if isinstance(body, dict) else {"value": body}
        request_row.status = "completed"
        request_row.result = result
        request_row.error = None
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        request_row.status = "failed"
        request_row.result = {}
        request_row.error = str(exc)[:1000]
    request_row.params_encrypted = None
    request_row.resolved_at = datetime.now(UTC)
    await db.flush()
    return action_result(request_row, application, action)


def action_result(
    request_row: EnterpriseApplicationActionRequest,
    application: EnterpriseApplication,
    action: EnterpriseApplicationAction,
) -> dict:
    return {
        "request_id": request_row.request_id,
        "status": request_row.status,
        "confirmation_id": request_row.id if action.requires_confirmation else None,
        "result": request_row.result or {},
        "error": request_row.error,
        "provenance": _provenance(application, action, request_row.request_id),
    }


async def invoke_action(
    db: AsyncSession,
    application_id: UUID | str,
    action_key: str,
    module_key: str,
    params: dict,
    user: CurrentUser,
    *,
    request_id: str | None = None,
) -> dict:
    application = await enterprise_application_service.get_application(db, application_id)
    if application is None or str(application.organization_id) != str(user.organization_id):
        raise HTTPException(status_code=404, detail="Application not found")
    action = (
        await db.execute(
            select(EnterpriseApplicationAction).where(
                EnterpriseApplicationAction.application_id == application.id,
                EnterpriseApplicationAction.action_key == action_key,
                EnterpriseApplicationAction.module_key == module_key,
                EnterpriseApplicationAction.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if action is None:
        raise HTTPException(status_code=404, detail="Subsystem action not found")
    required = OPERATION_PERMISSION[action.operation]
    await enterprise_application_service.assert_module_permission(db, application.id, user, module_key, required)
    if not action.ai_enabled:
        raise HTTPException(status_code=403, detail="Action is not enabled for AI")
    _validate_params(action, params)
    await _integration_or_409(db, application.id)
    rid = request_id or uuid4().hex
    existing = (
        await db.execute(
            select(EnterpriseApplicationActionRequest).where(
                EnterpriseApplicationActionRequest.application_id == application.id,
                EnterpriseApplicationActionRequest.user_id == UUID(user.id),
                EnterpriseApplicationActionRequest.request_id == rid,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if str(existing.action_id) != str(action.id) or existing.module_key != module_key:
            raise HTTPException(
                status_code=409,
                detail="requestId is already bound to a different user, module, or action",
            )
        return action_result(existing, application, action)
    now = datetime.now(UTC)
    request_row = EnterpriseApplicationActionRequest(
        application_id=application.id,
        organization_id=application.organization_id,
        action_id=action.id,
        user_id=UUID(user.id),
        request_id=rid,
        module_key=module_key,
        params_encrypted=encrypt_provider_api_key(json.dumps(params, ensure_ascii=False)),
        status="pending",
        expires_at=now + CONFIRMATION_TTL,
    )
    db.add(request_row)
    await db.flush()
    if action.requires_confirmation:
        return action_result(request_row, application, action)
    return await _execute_request(db, request_row, application, action, user)


async def list_confirmation_requests(db: AsyncSession, user: CurrentUser) -> list[dict]:
    now = datetime.now(UTC)
    rows = list(
        (
            await db.execute(
                select(EnterpriseApplicationActionRequest)
                .options(selectinload(EnterpriseApplicationActionRequest.action))
                .where(
                    EnterpriseApplicationActionRequest.organization_id == user.organization_id,
                    EnterpriseApplicationActionRequest.user_id == UUID(user.id),
                )
                .order_by(EnterpriseApplicationActionRequest.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        if row.status == "pending" and row.expires_at <= now:
            row.status = "expired"
            row.params_encrypted = None
            row.resolved_at = now
    await db.flush()
    result: list[dict] = []
    for row in rows:
        params: dict = {}
        if row.status == "pending" and row.params_encrypted:
            try:
                value = json.loads(decrypt_provider_api_key(row.params_encrypted))
                params = value if isinstance(value, dict) else {}
            except (ValueError, TypeError):
                params = {}
        result.append(
            {
                "id": row.id,
                "application_id": row.application_id,
                "action_id": row.action_id,
                "request_id": row.request_id,
                "module_key": row.module_key,
                "status": row.status,
                "params": params,
                "expires_at": row.expires_at,
                "resolved_at": row.resolved_at,
                "result": row.result or {},
                "error": row.error,
                "action": row.action,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
    return result


async def resolve_confirmation(db: AsyncSession, confirmation_id: UUID, user: CurrentUser, *, approve: bool) -> dict:
    request_row = (
        await db.execute(
            select(EnterpriseApplicationActionRequest)
            .options(selectinload(EnterpriseApplicationActionRequest.action))
            .where(EnterpriseApplicationActionRequest.id == confirmation_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if request_row is None or str(request_row.user_id) != user.id:
        raise HTTPException(status_code=404, detail="Confirmation request not found")
    application = await enterprise_application_service.get_application(db, request_row.application_id)
    if application is None or str(application.organization_id) != str(user.organization_id):
        raise HTTPException(status_code=404, detail="Application not found")
    action = request_row.action
    if request_row.status != "pending":
        return action_result(request_row, application, action)
    now = datetime.now(UTC)
    if request_row.expires_at <= now:
        request_row.status = "expired"
        request_row.params_encrypted = None
        request_row.resolved_at = now
        await db.flush()
        return action_result(request_row, application, action)
    if not approve:
        request_row.status = "rejected"
        request_row.params_encrypted = None
        request_row.resolved_at = now
        await db.flush()
        return action_result(request_row, application, action)
    return await _execute_request(db, request_row, application, action, user)


def issue_launch_ticket(
    integration: EnterpriseApplicationIntegration,
    application: EnterpriseApplication,
    user: CurrentUser,
    module_key: str,
    permissions: set[str],
) -> str:
    if not integration.auth_token_encrypted or integration.protocol_version < 2:
        raise HTTPException(status_code=409, detail="Protocol v2 integration secret is not configured")
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "zhuojian-saas",
            "aud": application.slug,
            "typ": "zhuojian-sso",
            "sub": user.id,
            "organizationId": str(user.organization_id),
            "departmentId": user.department_id,
            "teamId": user.team_id,
            "moduleKey": module_key,
            "permissions": sorted(permissions),
            "jti": uuid4().hex,
            "iat": now,
            "exp": now + timedelta(seconds=60),
        },
        decrypt_provider_api_key(integration.auth_token_encrypted),
        algorithm="HS256",
    )
