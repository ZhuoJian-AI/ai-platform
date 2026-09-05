"""Authorized, replay-safe subsystem action execution and confirmation."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urljoin
from uuid import UUID, uuid4

import httpx
import jwt
from fastapi import HTTPException
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, best_match
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.user_auth import CurrentUser, current_user_for_user
from app.models.enterprise_application import (
    EnterpriseApplication,
    EnterpriseApplicationAction,
    EnterpriseApplicationActionRequest,
    EnterpriseApplicationIntegration,
    EnterpriseApplicationSsoCode,
)
from app.models.user import User
from app.services import enterprise_application_service
from app.services.subsystem_access_service import assert_application_available
from app.utils.crypto import decrypt_provider_api_key, encrypt_provider_api_key, hash_api_key
from app.utils.public_url import request_public_http, same_origin

OPERATION_PERMISSION = {
    "query": "ai_query",
    "create": "ai_create",
    "update": "ai_update",
    "delete": "ai_delete",
    "approve": "ai_approve",
    "export": "export",
}

FORCED_CONFIRMATION_OPERATIONS = {"delete", "approve"}


def action_requires_confirmation(action: EnterpriseApplicationAction) -> bool:
    """Keep the high-risk boundary independent of untrusted manifest flags."""

    return bool(action.requires_confirmation) or action.operation in FORCED_CONFIRMATION_OPERATIONS
CONFIRMATION_TTL = timedelta(minutes=5)
SSO_TICKET_TTL = timedelta(seconds=120)
SSO_CODE_RETENTION = timedelta(hours=1)
SSO_CODE_RATE_WINDOW = timedelta(minutes=1)
SSO_CODE_RATE_LIMIT = 30
SSO_CODE_OUTSTANDING_LIMIT = 10


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
    db: AsyncSession,
    application: EnterpriseApplication,
    user: CurrentUser,
    *,
    page_key: str | None = None,
    module_key: str | None = None,
) -> list[EnterpriseApplicationAction]:
    if not application.assistant_enabled:
        return []
    integration = await _integration_or_409(db, application.id)
    result: list[EnterpriseApplicationAction] = []
    for action in await list_actions(db, application.id, active_only=True):
        if module_key and action.module_key != module_key:
            continue
        page_actions = _manifest_page_action_keys(integration, action.module_key, page_key)
        if page_actions is not None and action.action_key not in page_actions:
            continue
        required = OPERATION_PERMISSION[action.operation]
        if action.ai_enabled and enterprise_application_service.action_allowed_for_user(
            application, user, action.module_key, page_key, action.action_key, required
        ):
            result.append(action)
    return result


def action_tool_name(application: EnterpriseApplication, action: EnterpriseApplicationAction) -> str:
    import re

    base = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{application.slug}__{action.action_key}")
    return (base[:55] + "_" + str(action.id).replace("-", "")[:8])[:64]


def _schema_error_message(error) -> str:
    """Return stable Chinese text instead of jsonschema's English validation detail."""

    messages = {
        "required": "缺少必填字段",
        "type": "数据类型不正确",
        "enum": "取值不在允许范围内",
        "additionalProperties": "包含未约定的字段",
        "pattern": "格式不正确",
        "minimum": "数值小于允许的最小值",
        "maximum": "数值超过允许的最大值",
        "minLength": "文本长度不足",
        "maxLength": "文本长度超出限制",
        "minItems": "列表项目数量不足",
        "maxItems": "列表项目数量超出限制",
    }
    return messages.get(str(error.validator), "内容不符合输入约定")


def _validate_params(action: EnterpriseApplicationAction, params: dict) -> None:
    schema = action.input_schema or {}
    if schema.get("type") not in {None, "object"}:
        raise HTTPException(status_code=409, detail="子系统 Action 输入 Schema 的根类型必须是 object")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise HTTPException(status_code=409, detail="子系统 Action 输入 Schema 无效") from exc
    error = best_match(Draft202012Validator(schema).iter_errors(params))
    if error is None:
        return
    path = ".".join(str(part) for part in error.absolute_path)
    location = f"参数 {path}" if path else "Action 参数"
    raise HTTPException(status_code=422, detail=f"{location}不符合约定：{_schema_error_message(error)}")


async def _integration_or_409(db: AsyncSession, application_id: UUID | str) -> EnterpriseApplicationIntegration:
    row = (
        await db.execute(
            select(EnterpriseApplicationIntegration).where(
                EnterpriseApplicationIntegration.application_id == UUID(str(application_id))
            )
        )
    ).scalar_one_or_none()
    has_action_credential = bool(
        row
        and (
            row.action_signing_secret_encrypted
            or (row.credential_version < 2 and row.auth_token_encrypted)
        )
    )
    if row is None or not has_action_credential or row.protocol_version < 2:
        raise HTTPException(status_code=409, detail="Subsystem Action credential is not configured")
    if not row.sync_enabled:
        raise HTTPException(status_code=409, detail="Subsystem integration is disabled")
    application = await db.get(EnterpriseApplication, row.application_id)
    if application is None:
        raise HTTPException(status_code=409, detail="Subsystem application is unavailable")
    await assert_application_available(db, application)
    return row


def _action_signing_secret(integration: EnterpriseApplicationIntegration) -> str:
    """Use separated credentials for v2.5; preserve read-only migration support for v2.4."""
    encrypted = integration.action_signing_secret_encrypted
    if not encrypted and integration.credential_version < 2:
        encrypted = integration.auth_token_encrypted
    if not encrypted:
        raise HTTPException(status_code=409, detail="Subsystem Action credential is not configured")
    return decrypt_provider_api_key(encrypted)


def _manifest_page_action_keys(
    integration: EnterpriseApplicationIntegration, module_key: str, page_key: str | None
) -> set[str] | None:
    manifest = integration.manifest if isinstance(integration.manifest, dict) else {}
    revision = str(manifest.get("contractRevision") or "2.0")
    modules = manifest.get("modules") if isinstance(manifest.get("modules"), list) else []
    module = next((item for item in modules if isinstance(item, dict) and item.get("moduleKey") == module_key), None)
    if not isinstance(module, dict):
        return None if revision == "2.0" else set()
    if not page_key:
        return None if revision == "2.0" else set()
    pages = module.get("pages") if isinstance(module.get("pages"), list) else []
    page = next((item for item in pages if isinstance(item, dict) and item.get("pageKey") == page_key), None)
    if not isinstance(page, dict):
        return set()
    return {str(item) for item in (page.get("actionKeys") or []) if isinstance(item, str)}


def _request_payload(params: dict, page_key: str | None, expected_version: str | int | None) -> str:
    return json.dumps(
        {"params": params, "pageKey": page_key, "expectedVersion": expected_version},
        ensure_ascii=False,
    )


def _decode_request_payload(value: str) -> tuple[dict, str | None, str | int | None]:
    decoded = json.loads(value)
    if isinstance(decoded, dict) and isinstance(decoded.get("params"), dict):
        page_key = decoded.get("pageKey") if isinstance(decoded.get("pageKey"), str) else None
        return decoded["params"], page_key, decoded.get("expectedVersion")
    return (decoded if isinstance(decoded, dict) else {}), None, None


def _params_hash(params: dict) -> str:
    canonical = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _identity_claims(
    application: EnterpriseApplication,
    action: EnterpriseApplicationAction,
    user: CurrentUser,
    request_id: str,
    permissions: set[str],
    page_key: str | None,
    params: dict,
    *,
    confirmation_id: str | None = None,
) -> dict:
    now = datetime.now(UTC)
    claims = {
        "iss": "zhuojian-saas",
        "aud": application.slug,
        "typ": "zhuojian-action",
        "sub": user.id,
        "organizationId": str(user.organization_id),
        "departmentId": user.department_id,
        "departmentIds": list(user.department_ids),
        "roleIds": list(user.role_ids),
        "effectiveDataScope": enterprise_application_service.effective_data_scope(
            application,
            user,
            action.module_key,
            page_key,
            action.action_key,
            OPERATION_PERMISSION[action.operation],
        ),
        "teamId": user.team_id,
        "moduleKey": action.module_key,
        "pageKey": page_key,
        "actionKey": action.action_key,
        "operation": action.operation,
        "permissions": sorted(permissions),
        "requestId": request_id,
        "jti": uuid4().hex,
        "iat": now,
        "exp": now + timedelta(seconds=60),
    }
    if confirmation_id:
        claims.update({
            "confirmed": True,
            "confirmationId": confirmation_id,
            "confirmedBy": user.id,
            "confirmedAt": now.isoformat(),
            "paramsHash": _params_hash(params),
        })
    return claims


def _provenance(
    application: EnterpriseApplication,
    action: EnterpriseApplicationAction,
    request_id: str,
    page_key: str | None = None,
) -> dict:
    return {
        "applicationId": str(application.id),
        "applicationSlug": application.slug,
        "moduleKey": action.module_key,
        "pageKey": page_key,
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
    *,
    confirmed: bool = False,
) -> dict:
    integration = await _integration_or_409(db, application.id)
    params, page_key, expected_version = _decode_request_payload(
        decrypt_provider_api_key(request_row.params_encrypted or "")
    )
    required = OPERATION_PERMISSION[action.operation]
    permissions = enterprise_application_service.effective_page_permissions(
        application, user, action.module_key, page_key
    )
    if (
        not action.is_active
        or not action.ai_enabled
        or (
            (page_actions := _manifest_page_action_keys(integration, action.module_key, page_key)) is not None
            and action.action_key not in page_actions
        )
        or not enterprise_application_service.action_allowed_for_user(
            application, user, action.module_key, page_key, action.action_key, required
        )
    ):
        raise HTTPException(status_code=403, detail="Action is no longer authorized")
    secret = _action_signing_secret(integration)
    token = jwt.encode(
        _identity_claims(
            application,
            action,
            user,
            request_row.request_id,
            permissions,
            page_key,
            params,
            confirmation_id=str(request_row.id) if confirmed and action_requires_confirmation(action) else None,
        ),
        secret,
        algorithm="HS256",
    )
    url = urljoin(
        application.entry_url.rstrip("/") + "/",
        f"api/integration/actions/{quote(action.action_key, safe='')}",
    )
    if not same_origin(application.entry_url, url):
        raise HTTPException(status_code=409, detail="Action endpoint left the registered application origin")
    request_row.status = "executing"
    await db.flush()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=8.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await request_public_http(
                client,
                "POST",
                url,
                require_https=True,
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                    "user-agent": "ZhuoJian-Subsystem-Action/2.0",
                },
                json={
                    "moduleKey": action.module_key,
                    "pageKey": page_key,
                    "operation": action.operation,
                    "expectedVersion": expected_version,
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
    return action_result(request_row, application, action, page_key=page_key)


def action_result(
    request_row: EnterpriseApplicationActionRequest,
    application: EnterpriseApplication,
    action: EnterpriseApplicationAction,
    *,
    page_key: str | None = None,
) -> dict:
    return {
        "request_id": request_row.request_id,
        "status": request_row.status,
        "confirmation_id": request_row.id if action_requires_confirmation(action) else None,
        "result": request_row.result or {},
        "error": request_row.error,
        "provenance": _provenance(application, action, request_row.request_id, page_key),
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
    page_key: str | None = None,
    operation: str | None = None,
    expected_version: str | int | None = None,
) -> dict:
    application = await enterprise_application_service.get_application(db, application_id)
    if application is None or str(application.organization_id) != str(user.organization_id):
        raise HTTPException(status_code=404, detail="Application not found")
    if not application.assistant_enabled:
        raise HTTPException(status_code=403, detail="The administrator disabled AI for this application")
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
    if operation is not None and operation != action.operation:
        raise HTTPException(status_code=409, detail="Action operation does not match the manifest")
    required = OPERATION_PERMISSION[action.operation]
    await enterprise_application_service.assert_page_permission(
        db, application.id, user, module_key, page_key, required
    )
    if not action.ai_enabled:
        raise HTTPException(status_code=403, detail="Action is not enabled for AI")
    _validate_params(action, params)
    integration = await _integration_or_409(db, application.id)
    page_actions = _manifest_page_action_keys(integration, module_key, page_key)
    if page_actions is not None and action.action_key not in page_actions:
        raise HTTPException(status_code=403, detail="Action is not available on the current page")
    if not enterprise_application_service.action_allowed_for_user(
        application, user, module_key, page_key, action.action_key, required
    ):
        raise HTTPException(status_code=403, detail="Action is not authorized for this user and page")
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
        if existing.params_encrypted:
            _, existing_page_key, existing_version = _decode_request_payload(
                decrypt_provider_api_key(existing.params_encrypted)
            )
            if existing_page_key != page_key or existing_version != expected_version:
                raise HTTPException(status_code=409, detail="requestId is bound to another page or version")
        return action_result(existing, application, action, page_key=page_key)
    now = datetime.now(UTC)
    request_row = EnterpriseApplicationActionRequest(
        application_id=application.id,
        organization_id=application.organization_id,
        action_id=action.id,
        user_id=UUID(user.id),
        request_id=rid,
        module_key=module_key,
        params_encrypted=encrypt_provider_api_key(_request_payload(params, page_key, expected_version)),
        status="pending",
        expires_at=now + CONFIRMATION_TTL,
    )
    db.add(request_row)
    await db.flush()
    if action_requires_confirmation(action):
        return action_result(request_row, application, action, page_key=page_key)
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
        page_key: str | None = None
        if row.status == "pending" and row.params_encrypted:
            try:
                params, page_key, _ = _decode_request_payload(
                    decrypt_provider_api_key(row.params_encrypted)
                )
            except (ValueError, TypeError):
                params = {}
        result.append(
            {
                "id": row.id,
                "application_id": row.application_id,
                "action_id": row.action_id,
                "request_id": row.request_id,
                "module_key": row.module_key,
                "page_key": page_key,
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
    page_key: str | None = None
    if request_row.params_encrypted:
        try:
            _, page_key, _ = _decode_request_payload(
                decrypt_provider_api_key(request_row.params_encrypted)
            )
        except (ValueError, TypeError):
            page_key = None
    if request_row.status != "pending":
        return action_result(request_row, application, action, page_key=page_key)
    now = datetime.now(UTC)
    if request_row.expires_at <= now:
        request_row.status = "expired"
        request_row.params_encrypted = None
        request_row.resolved_at = now
        await db.flush()
        return action_result(request_row, application, action, page_key=page_key)
    if not approve:
        request_row.status = "rejected"
        request_row.params_encrypted = None
        request_row.resolved_at = now
        await db.flush()
        return action_result(request_row, application, action, page_key=page_key)
    return await _execute_request(db, request_row, application, action, user, confirmed=True)


def _launch_claims(
    integration: EnterpriseApplicationIntegration,
    application: EnterpriseApplication,
    user: CurrentUser,
    module_key: str,
    permissions: set[str],
    module_claims: dict | None = None,
    *,
    launch_nonce: str,
    session_binding_hash: str,
) -> dict:
    if not integration.sso_exchange_credential_hash or integration.protocol_version < 2:
        raise HTTPException(status_code=409, detail="Subsystem SSO exchange credential is not configured")
    action_keys = module_claims.get("action_keys") if isinstance(module_claims, dict) else None
    page_access = module_claims.get("page_access") if isinstance(module_claims, dict) else None
    if not isinstance(action_keys, list) or not isinstance(page_access, dict) or not page_access:
        raise HTTPException(
            status_code=403,
            detail="请联系企业管理员配置该子模块的具体页面和操作权限",
        )
    now = datetime.now(UTC)
    claims = {
        "iss": "zhuojian-saas",
        "aud": application.slug,
        "typ": "zhuojian-sso-code",
        "sub": user.id,
        "organizationId": str(user.organization_id),
        "departmentId": user.department_id,
        "departmentIds": list(user.department_ids),
        "roleIds": list(user.role_ids),
        "effectiveDataScope": enterprise_application_service.effective_data_scope(
            application, user, module_key
        ),
        "teamId": user.team_id,
        "moduleKey": module_key,
        "permissions": sorted(permissions),
        "jti": uuid4().hex,
        "launchNonce": launch_nonce,
        "sessionBindingHash": session_binding_hash,
        "authEpoch": user.user.auth_epoch,
        "iat": now.isoformat(),
        "exp": (now + SSO_TICKET_TTL).isoformat(),
    }
    claims["actionKeys"] = action_keys
    claims["pageAccess"] = {
        page_key: {
            "permissions": page.get("permissions") or [],
            "actionKeys": page.get("action_keys") or [],
            "dataScopes": page.get("data_scopes") or {},
            "actionDataScopes": page.get("action_data_scopes") or {},
        }
        for page_key, page in page_access.items()
        if isinstance(page_key, str) and isinstance(page, dict)
    }
    claims["pageKeys"] = sorted(claims["pageAccess"])
    return claims


def issue_legacy_launch_ticket(
    integration: EnterpriseApplicationIntegration,
    application: EnterpriseApplication,
    user: CurrentUser,
    module_key: str,
    permissions: set[str],
    module_claims: dict,
) -> str:
    """Keep already-deployed v2.0-v2.4 systems usable while they migrate to v2.5."""
    if integration.credential_version >= 2 or not integration.auth_token_encrypted:
        raise HTTPException(status_code=409, detail="Legacy subsystem credential is not configured")
    action_keys = module_claims.get("action_keys")
    page_access = module_claims.get("page_access")
    if not isinstance(action_keys, list) or not isinstance(page_access, dict) or not page_access:
        raise HTTPException(status_code=403, detail="请联系企业管理员配置该子模块的具体页面和操作权限")
    now = datetime.now(UTC)
    claims = {
        "iss": "zhuojian-saas",
        "aud": application.slug,
        "typ": "zhuojian-sso",
        "sub": user.id,
        "organizationId": str(user.organization_id),
        "departmentId": user.department_id,
        "departmentIds": list(user.department_ids),
        "roleIds": list(user.role_ids),
        "effectiveDataScope": enterprise_application_service.effective_data_scope(
            application, user, module_key
        ),
        "teamId": user.team_id,
        "moduleKey": module_key,
        "permissions": sorted(permissions),
        "actionKeys": action_keys,
        "pageAccess": {
            page_key: {
                "permissions": page.get("permissions") or [],
                "actionKeys": page.get("action_keys") or [],
                "dataScopes": page.get("data_scopes") or {},
                "actionDataScopes": page.get("action_data_scopes") or {},
            }
            for page_key, page in page_access.items()
            if isinstance(page_key, str) and isinstance(page, dict)
        },
        "jti": uuid4().hex,
        "authEpoch": user.user.auth_epoch,
        "iat": now,
        "exp": now + SSO_TICKET_TTL,
    }
    claims["pageKeys"] = sorted(claims["pageAccess"])
    return jwt.encode(
        claims,
        decrypt_provider_api_key(integration.auth_token_encrypted),
        algorithm="HS256",
    )


async def issue_launch_code(
    db: AsyncSession,
    integration: EnterpriseApplicationIntegration,
    application: EnterpriseApplication,
    user: CurrentUser,
    module_key: str,
    permissions: set[str],
    module_claims: dict,
    *,
    redirect_path: str,
    session_binding_hash: str,
    launch_nonce: str | None = None,
) -> tuple[str, str]:
    """Persist only a hash of the browser-visible code and encrypted claims."""

    await assert_application_available(db, application)
    if not integration.sync_enabled:
        raise HTTPException(status_code=409, detail="Subsystem integration is disabled")
    if not integration.sso_exchange_credential_hash or integration.credential_version < 2:
        raise HTTPException(status_code=409, detail="Subsystem SSO exchange credential is not configured")
    if not redirect_path.startswith("/") or redirect_path.startswith("//"):
        raise HTTPException(status_code=409, detail="Subsystem redirect path is invalid")
    if len(session_binding_hash) != 64:
        raise HTTPException(status_code=409, detail="User session binding is invalid")

    now = datetime.now(UTC)
    # Serialize per-user issuance so concurrent launch requests cannot bypass
    # the rate/outstanding limits.
    await db.execute(select(User.id).where(User.id == UUID(user.id)).with_for_update())
    stale_ids = (
        select(EnterpriseApplicationSsoCode.id)
        .where(
            or_(
                EnterpriseApplicationSsoCode.expires_at < now - SSO_CODE_RETENTION,
                EnterpriseApplicationSsoCode.consumed_at < now - SSO_CODE_RETENTION,
            )
        )
        .limit(500)
    )
    await db.execute(delete(EnterpriseApplicationSsoCode).where(EnterpriseApplicationSsoCode.id.in_(stale_ids)))
    outstanding = int(
        (
            await db.execute(
                select(func.count())
                .select_from(EnterpriseApplicationSsoCode)
                .where(
                    EnterpriseApplicationSsoCode.application_id == application.id,
                    EnterpriseApplicationSsoCode.user_id == UUID(user.id),
                    EnterpriseApplicationSsoCode.consumed_at.is_(None),
                    EnterpriseApplicationSsoCode.expires_at > now,
                )
            )
        ).scalar_one()
    )
    recent = int(
        (
            await db.execute(
                select(func.count())
                .select_from(EnterpriseApplicationSsoCode)
                .where(
                    EnterpriseApplicationSsoCode.application_id == application.id,
                    EnterpriseApplicationSsoCode.user_id == UUID(user.id),
                    EnterpriseApplicationSsoCode.created_at >= now - SSO_CODE_RATE_WINDOW,
                )
            )
        ).scalar_one()
    )
    if outstanding >= SSO_CODE_OUTSTANDING_LIMIT or recent >= SSO_CODE_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many subsystem launch requests")

    nonce = launch_nonce or secrets.token_urlsafe(24)
    code = f"zjsc_{secrets.token_urlsafe(48)}"
    claims = _launch_claims(
        integration,
        application,
        user,
        module_key,
        permissions,
        module_claims,
        launch_nonce=nonce,
        session_binding_hash=session_binding_hash,
    )
    db.add(
        EnterpriseApplicationSsoCode(
            application_id=application.id,
            organization_id=application.organization_id,
            user_id=UUID(user.id),
            code_hash=hash_api_key(code),
            module_key=module_key,
            redirect_path=redirect_path,
            session_binding_hash=session_binding_hash,
            launch_nonce=nonce,
            claims_encrypted=encrypt_provider_api_key(
                json.dumps(claims, ensure_ascii=False, separators=(",", ":"), default=str)
            ),
            expires_at=now + SSO_TICKET_TTL,
        )
    )
    await db.flush()
    return code, nonce


async def redeem_launch_code(
    db: AsyncSession,
    integration: EnterpriseApplicationIntegration,
    *,
    code: str,
    redirect_path: str,
    launch_nonce: str,
) -> dict:
    """Atomically consume a code bound to this app, redirect and launch nonce."""

    application = await db.get(EnterpriseApplication, integration.application_id)
    if application is None:
        raise HTTPException(status_code=401, detail="Invalid or expired subsystem SSO code")
    await assert_application_available(db, application)
    now = datetime.now(UTC)
    row = (
        await db.execute(
            update(EnterpriseApplicationSsoCode)
            .where(
                EnterpriseApplicationSsoCode.application_id == application.id,
                EnterpriseApplicationSsoCode.organization_id == application.organization_id,
                EnterpriseApplicationSsoCode.code_hash == hash_api_key(code),
                EnterpriseApplicationSsoCode.redirect_path == redirect_path,
                EnterpriseApplicationSsoCode.launch_nonce == launch_nonce,
                EnterpriseApplicationSsoCode.consumed_at.is_(None),
                EnterpriseApplicationSsoCode.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(EnterpriseApplicationSsoCode)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid or expired subsystem SSO code")
    user = await db.get(User, row.user_id)
    if user is None or user.deleted_at is not None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired subsystem SSO code")
    try:
        claims = json.loads(decrypt_provider_api_key(row.claims_encrypted))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired subsystem SSO code")
    if (
        not isinstance(claims, dict)
        or claims.get("sub") != str(user.id)
        or claims.get("organizationId") != str(application.organization_id)
        or claims.get("aud") != application.slug
        or claims.get("moduleKey") != row.module_key
        or claims.get("launchNonce") != launch_nonce
        or claims.get("sessionBindingHash") != row.session_binding_hash
        or claims.get("authEpoch") != user.auth_epoch
    ):
        raise HTTPException(status_code=401, detail="Invalid or expired subsystem SSO code")
    return {
        "application_id": application.id,
        "application_slug": application.slug,
        "organization_id": application.organization_id,
        "module_key": row.module_key,
        "redirect": row.redirect_path,
        "launch_nonce": row.launch_nonce,
        "claims": claims,
    }


async def validate_live_subsystem_session(
    db: AsyncSession,
    integration: EnterpriseApplicationIntegration,
    *,
    user_id: UUID,
    auth_epoch: int,
    module_key: str,
    page_key: str,
    action_key: str | None,
) -> dict:
    """Re-check an iframe session against current SaaS grants and revocations."""

    application = await enterprise_application_service.get_application(
        db, integration.application_id
    )
    if application is None:
        raise HTTPException(status_code=401, detail="Subsystem session is no longer valid")
    await assert_application_available(db, application)
    user = await db.get(User, user_id)
    if (
        user is None
        or user.deleted_at is not None
        or not user.is_active
        or user.must_change_password
        or str(user.organization_id) != str(application.organization_id)
        or user.auth_epoch != auth_epoch
    ):
        raise HTTPException(status_code=401, detail="Subsystem session is no longer valid")
    current_user = await current_user_for_user(db, user)
    module_claims = enterprise_application_service.effective_module_claims(
        application,
        current_user,
        module_key,
    )
    page = (module_claims.get("page_access") or {}).get(page_key)
    if not isinstance(page, dict) or "view" not in (page.get("permissions") or []):
        raise HTTPException(status_code=403, detail="Subsystem page access has been revoked")
    if action_key is None:
        data_scope = (page.get("data_scopes") or {}).get("view")
    else:
        if action_key not in (page.get("action_keys") or []):
            raise HTTPException(status_code=403, detail="Subsystem Action access has been revoked")
        data_scope = (page.get("action_data_scopes") or {}).get(action_key)
    if not isinstance(data_scope, dict):
        raise HTTPException(status_code=403, detail="Subsystem data scope is unavailable")
    return {
        "valid": True,
        "auth_epoch": user.auth_epoch,
        "effective_data_scope": data_scope,
    }
