"""Manifest discovery and replay-safe event ingestion for independently deployed subsystems."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import jwt
import structlog
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_auth import CurrentUser
from app.config import settings
from app.database import async_session_factory
from app.models.department import Department
from app.models.enterprise_application import (
    CrossDepartmentWorkItem,
    EnterpriseApplication,
    EnterpriseApplicationAction,
    EnterpriseApplicationEvent,
    EnterpriseApplicationEventDelivery,
    EnterpriseApplicationEventRoute,
    EnterpriseApplicationIntegration,
)
from app.schemas.enterprise_application import (
    EnterpriseApplicationEventRouteInput,
    EnterpriseApplicationIntegrationInput,
)
from app.services import scope_service, skill_scope_service
from app.utils.crypto import decrypt_provider_api_key, encrypt_provider_api_key
from app.utils.public_url import assert_public_http_url, same_origin

logger = structlog.get_logger()

STABLE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _validate_manifest_url(application: EnterpriseApplication, value: str) -> str:
    url = str(value)
    if not same_origin(application.entry_url, url):
        raise HTTPException(status_code=422, detail="Manifest URL must use the application entry URL origin")
    try:
        assert_public_http_url(url, require_https=settings.app_env != "development")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return url


def _headers(row: EnterpriseApplicationIntegration) -> dict[str, str]:
    headers = {"accept": "application/json", "user-agent": "ZhuoJian-Subsystem-Sync/1.0"}
    if row.auth_token_encrypted:
        headers["authorization"] = f"Bearer {decrypt_provider_api_key(row.auth_token_encrypted)}"
    return headers


def _validate_manifest_payload(
    payload: object,
    *,
    entry_url: str,
    manifest_url: str,
    expected_slug: str | None,
) -> tuple[dict, str, int]:
    if not isinstance(payload, dict) or payload.get("protocol") != "zhuojian-subsystem":
        raise ValueError("Manifest protocol must be 'zhuojian-subsystem'")
    version = payload.get("version")
    if version not in {1, 2}:
        raise ValueError("Subsystem protocol version must be 1 or 2")
    application_slug = str(payload.get("applicationSlug") or "").strip()
    if not application_slug:
        raise ValueError("Manifest applicationSlug is required")
    if expected_slug is not None and application_slug != expected_slug:
        raise ValueError("Manifest applicationSlug does not match the registered application")
    modules = payload.get("modules")
    if not isinstance(modules, list) or len(modules) > 500:
        raise ValueError("Manifest modules must be a list with at most 500 entries")
    module_keys: set[str] = set()
    action_keys: set[str] = set()
    page_keys: set[str] = set()
    normalized_modules: list[dict] = []
    contract_revision = str(payload.get("contractRevision") or "2.0") if version == 2 else "1.0"
    if version == 2:
        if contract_revision not in {"2.0", "2.1", "2.2", "2.3", "2.4"}:
            raise ValueError("Unsupported subsystem contractRevision")
        if not modules:
            raise ValueError("Manifest modules must not be empty for protocol v2")
        enterprise = payload.get("enterprise")
        if (
            not isinstance(enterprise, dict)
            or not str(enterprise.get("key") or "").strip()
            or not str(enterprise.get("name") or "").strip()
        ):
            raise ValueError("Manifest enterprise.key and enterprise.name are required")
        auth = payload.get("auth")
        if not isinstance(auth, dict):
            raise ValueError("Manifest auth is required for protocol v2")
        if auth.get("ssoPath") != "/api/integration/sso":
            raise ValueError("Manifest auth.ssoPath must be '/api/integration/sso'")
        if auth.get("algorithm") != "HS256":
            raise ValueError("Manifest auth.algorithm must be 'HS256'")
    for module in modules:
        if not isinstance(module, dict):
            raise ValueError("Manifest module entries must be objects")
        key = str(module.get("key") or module.get("moduleKey") or "").strip()
        if not key or len(key) > 120 or not STABLE_KEY_RE.fullmatch(key) or key in module_keys:
            raise ValueError("Manifest module keys must be unique and 1-120 characters")
        module_keys.add(key)
        route = str(module.get("route") or "/").strip()
        parsed_route = urlsplit(route)
        if not route.startswith("/") or route.startswith("//") or parsed_route.scheme or parsed_route.netloc:
            raise ValueError(f"Module '{key}' route must be a site-relative path")
        departments = module.get("departments") if isinstance(module.get("departments"), list) else []
        if version == 2:
            if any(not isinstance(item, dict) for item in departments):
                raise ValueError(f"Module '{key}' departments must contain objects")
            department_keys = [
                str(item.get("key") or "").strip()
                for item in departments
                if isinstance(item, dict)
            ]
            if not department_keys or any(not item for item in department_keys):
                raise ValueError(f"Module '{key}' must declare departments with stable keys")
            if any(len(item) > 120 or not STABLE_KEY_RE.fullmatch(item) for item in department_keys):
                raise ValueError(f"Module '{key}' department keys must use lowercase stable identifiers")
            if len(set(department_keys)) != len(department_keys):
                raise ValueError(f"Module '{key}' department keys must be unique")
            for department in departments:
                if not str(department.get("name") or "").strip() or not str(
                    department.get("role") or ""
                ).strip():
                    raise ValueError(f"Module '{key}' departments must declare name and role")
            owners = [item for item in departments if isinstance(item, dict) and item.get("role") == "owner"]
            if len(owners) != 1:
                raise ValueError(f"Module '{key}' must declare exactly one owner department")
        normalized_actions: list[dict] = []
        actions = module.get("actions") if isinstance(module.get("actions"), list) else []
        if version == 2 and not isinstance(module.get("actions"), list):
            raise ValueError(f"Module '{key}' actions must be a list")
        for action in actions:
            if not isinstance(action, dict):
                raise ValueError(f"Module '{key}' contains a non-object action")
            action_key = str(action.get("actionKey") or action.get("key") or "").strip()
            operation = str(action.get("operation") or "").strip()
            if version == 2:
                required_fields = {
                    "actionKey",
                    "name",
                    "operation",
                    "aiEnabled",
                    "requiresConfirmation",
                    "inputSchema",
                    "resultSchema",
                }
                if not required_fields.issubset(action):
                    raise ValueError(f"Action '{action_key or '<empty>'}' is missing protocol v2 fields")
                if not isinstance(action["aiEnabled"], bool) or not isinstance(
                    action["requiresConfirmation"], bool
                ):
                    raise ValueError(f"Action '{action_key}' AI and confirmation flags must be booleans")
                if not isinstance(action["inputSchema"], dict) or not isinstance(
                    action["resultSchema"], dict
                ):
                    raise ValueError(f"Action '{action_key}' input and result schemas must be objects")
            if (
                not action_key
                or len(action_key) > 160
                or not STABLE_KEY_RE.fullmatch(action_key)
                or action_key in action_keys
            ):
                raise ValueError("Manifest action keys must be unique and 1-160 characters")
            if operation not in {"query", "create", "update", "delete", "export", "approve"}:
                raise ValueError(f"Action '{action_key}' has an unsupported operation")
            action_keys.add(action_key)
            normalized_actions.append({
                **action,
                "actionKey": action_key,
                "name": str(action.get("name") or action_key)[:255],
                "operation": operation,
                "aiEnabled": bool(action.get("aiEnabled", False)),
                "requiresConfirmation": bool(action.get("requiresConfirmation", False)),
                "inputSchema": action.get("inputSchema") if isinstance(action.get("inputSchema"), dict) else {},
                "resultSchema": action.get("resultSchema") if isinstance(action.get("resultSchema"), dict) else {},
            })
        normalized_pages: list[dict] = []
        pages = module.get("pages") if isinstance(module.get("pages"), list) else []
        if contract_revision in {"2.1", "2.2", "2.3", "2.4"} and not pages:
            raise ValueError(f"Module '{key}' must declare pages for contractRevision {contract_revision}")
        module_action_keys = {item["actionKey"] for item in normalized_actions}
        for page in pages:
            if not isinstance(page, dict):
                raise ValueError(f"Module '{key}' contains a non-object page")
            page_key = str(page.get("pageKey") or "").strip()
            if (
                not page_key
                or len(page_key) > 160
                or not STABLE_KEY_RE.fullmatch(page_key)
                or page_key in page_keys
            ):
                raise ValueError("Manifest page keys must be unique and 1-160 characters")
            page_keys.add(page_key)
            route_pattern = str(page.get("routePattern") or "").strip()
            parsed_page_route = urlsplit(route_pattern)
            if (
                not route_pattern.startswith("/")
                or route_pattern.startswith("//")
                or parsed_page_route.scheme
                or parsed_page_route.netloc
            ):
                raise ValueError(f"Page '{page_key}' routePattern must be a site-relative path")
            page_action_keys = page.get("actionKeys")
            if not isinstance(page_action_keys, list) or any(
                not isinstance(item, str) or item not in module_action_keys for item in page_action_keys
            ):
                raise ValueError(f"Page '{page_key}' actionKeys must reference actions in module '{key}'")
            query_action_key = page.get("queryActionKey")
            if query_action_key is not None and query_action_key not in page_action_keys:
                raise ValueError(f"Page '{page_key}' queryActionKey must be included in actionKeys")
            context_schema = page.get("contextSchema")
            if not isinstance(context_schema, dict):
                raise ValueError(f"Page '{page_key}' contextSchema must be an object")
            normalized_pages.append({
                **page,
                "pageKey": page_key,
                "name": str(page.get("name") or page_key)[:255],
                "routePattern": route_pattern,
                "queryActionKey": query_action_key,
                "actionKeys": list(dict.fromkeys(page_action_keys)),
                "contextSchema": context_schema,
            })
        normalized_departments: list[dict] | list[object] = list(departments)
        if version == 2:
            normalized_departments = []
        for department in departments if version == 2 else []:
            department_action_keys = department.get("actionKeys")
            department_page_keys = department.get("pageKeys")
            if contract_revision in {"2.2", "2.3"} and (
                not isinstance(department_action_keys, list)
                or not isinstance(department_page_keys, list)
            ):
                raise ValueError(
                    f"Module '{key}' departments must declare actionKeys and pageKeys "
                    f"for contractRevision {contract_revision}"
                )
            if department_action_keys is None:
                department_action_keys = []
            if department_page_keys is None:
                department_page_keys = []
            if not isinstance(department_action_keys, list) or any(
                not isinstance(item, str) or item not in module_action_keys
                for item in department_action_keys
            ):
                raise ValueError(
                    f"Module '{key}' department actionKeys must reference actions in the same module"
                )
            module_page_keys = {item["pageKey"] for item in normalized_pages}
            if not isinstance(department_page_keys, list) or any(
                not isinstance(item, str) or item not in module_page_keys
                for item in department_page_keys
            ):
                raise ValueError(
                    f"Module '{key}' department pageKeys must reference pages in the same module"
                )
            normalized_department = dict(department)
            if contract_revision == "2.4":
                # v2.4 departments describe delivery/data responsibility only.
                # Access hints moved to accessRoles and must never leak back into
                # the platform as implicit department grants.
                normalized_department.pop("actionKeys", None)
                normalized_department.pop("pageKeys", None)
            else:
                normalized_department["actionKeys"] = list(dict.fromkeys(department_action_keys))
                normalized_department["pageKeys"] = list(dict.fromkeys(department_page_keys))
            normalized_departments.append(normalized_department)
        access_roles = module.get("accessRoles") if isinstance(module.get("accessRoles"), list) else []
        normalized_access_roles: list[dict] = []
        if contract_revision == "2.4" and not access_roles:
            raise ValueError(f"Module '{key}' must declare accessRoles for contractRevision 2.4")
        role_keys: set[str] = set()
        module_page_keys = {item["pageKey"] for item in normalized_pages}
        department_key_set = {
            str(item.get("key")) for item in normalized_departments if isinstance(item, dict)
        }
        for access_role in access_roles:
            if not isinstance(access_role, dict):
                raise ValueError(f"Module '{key}' accessRoles must contain objects")
            role_key = str(access_role.get("roleKey") or "").strip()
            if (
                not role_key or len(role_key) > 120
                or not STABLE_KEY_RE.fullmatch(role_key) or role_key in role_keys
            ):
                raise ValueError(f"Module '{key}' access role keys must be unique stable identifiers")
            role_keys.add(role_key)
            role_name = str(access_role.get("name") or "").strip()
            if not role_name:
                raise ValueError(f"Module '{key}' access role '{role_key}' must declare name")
            suggested_department_key = access_role.get("suggestedDepartmentKey")
            if suggested_department_key is not None and str(suggested_department_key) not in department_key_set:
                raise ValueError(
                    f"Module '{key}' access role '{role_key}' references an unknown department"
                )
            role_page_keys = access_role.get("pageKeys")
            role_action_keys = access_role.get("actionKeys")
            if not isinstance(role_page_keys, list) or any(
                not isinstance(item, str) or item not in module_page_keys for item in role_page_keys
            ):
                raise ValueError(
                    f"Module '{key}' access role '{role_key}' pageKeys must reference module pages"
                )
            if not isinstance(role_action_keys, list) or any(
                not isinstance(item, str) or item not in module_action_keys for item in role_action_keys
            ):
                raise ValueError(
                    f"Module '{key}' access role '{role_key}' actionKeys must reference module actions"
                )
            normalized_access_roles.append({
                **access_role,
                "roleKey": role_key,
                "name": role_name[:120],
                "suggestedDepartmentKey": suggested_department_key,
                "pageKeys": list(dict.fromkeys(role_page_keys)),
                "actionKeys": list(dict.fromkeys(role_action_keys)),
            })
        normalized_modules.append({
            **module,
            "moduleKey": key,
            "name": str(module.get("name") or module.get("moduleName") or key)[:255],
            "route": route,
            "departments": normalized_departments,
            "pages": normalized_pages,
            "actions": normalized_actions,
            "accessRoles": normalized_access_roles,
        })
    if version == 1:
        event_feed = payload.get("eventFeed")
        if not isinstance(event_feed, dict) or not event_feed.get("path"):
            raise ValueError("Manifest eventFeed.path is required")
        events_url = urljoin(manifest_url, str(event_feed["path"]))
    else:
        if not payload.get("eventsUrl"):
            raise ValueError("Manifest eventsUrl is required for protocol v2")
        events_url = urljoin(manifest_url, str(payload["eventsUrl"]))
        if contract_revision in {"2.1", "2.2", "2.3", "2.4"}:
            deliveries_path = payload.get("eventDeliveriesUrl")
            if deliveries_path != "/api/integration/event-deliveries":
                raise ValueError("Manifest eventDeliveriesUrl must be '/api/integration/event-deliveries'")
            deliveries_url = urljoin(manifest_url, deliveries_path)
            if not same_origin(entry_url, deliveries_url):
                raise ValueError("Event delivery endpoint must use the registered application origin")
    if not same_origin(entry_url, events_url):
        raise ValueError("Event feed must use the registered application origin")
    normalized = {
        **payload,
        "version": version,
        "contractRevision": contract_revision,
        "applicationSlug": application_slug,
        "modules": normalized_modules,
    }
    return normalized, events_url, version


def _validate_manifest(application: EnterpriseApplication, payload: object, manifest_url: str) -> tuple[dict, str, int]:
    return _validate_manifest_payload(
        payload,
        entry_url=application.entry_url,
        manifest_url=manifest_url,
        expected_slug=application.slug,
    )


async def _match_departments(db: AsyncSession, organization_id: UUID | str, manifest: dict) -> None:
    departments = list((await db.execute(
        select(Department).where(
            Department.organization_id == UUID(str(organization_id)),
            Department.deleted_at.is_(None),
        )
    )).scalars().all())
    by_slug = {item.slug: item for item in departments}
    for module in manifest.get("modules") or []:
        for department in module.get("departments") or []:
            if not isinstance(department, dict):
                continue
            match = by_slug.get(str(department.get("key") or ""))
            department["platformDepartmentId"] = str(match.id) if match else None
            department["matchStatus"] = "matched" if match else "unresolved"


async def _sync_actions(
    db: AsyncSession, application: EnterpriseApplication, manifest: dict
) -> None:
    existing = list((await db.execute(
        select(EnterpriseApplicationAction).where(EnterpriseApplicationAction.application_id == application.id)
    )).scalars().all())
    by_key = {item.action_key: item for item in existing}
    seen: set[str] = set()
    for module in manifest.get("modules") or []:
        module_key = module["moduleKey"]
        for action in module.get("actions") or []:
            key = action["actionKey"]
            seen.add(key)
            values = {
                "module_key": module_key,
                "name": action["name"],
                "description": str(action.get("description") or "")[:4000] or None,
                "operation": action["operation"],
                "ai_enabled": action["aiEnabled"],
                "requires_confirmation": action["requiresConfirmation"],
                "input_schema": action["inputSchema"],
                "result_schema": action["resultSchema"],
                "is_active": True,
            }
            row = by_key.get(key)
            if row is None:
                db.add(EnterpriseApplicationAction(
                    application_id=application.id,
                    organization_id=application.organization_id,
                    action_key=key,
                    **values,
                ))
            else:
                for field, value in values.items():
                    setattr(row, field, value)
    for row in existing:
        if row.action_key not in seen:
            row.is_active = False


async def get_integration(db: AsyncSession, application_id: UUID | str) -> EnterpriseApplicationIntegration | None:
    return (
        await db.execute(
            select(EnterpriseApplicationIntegration).where(
                EnterpriseApplicationIntegration.application_id == UUID(str(application_id))
            )
        )
    ).scalar_one_or_none()


async def configure_integration(
    db: AsyncSession,
    application: EnterpriseApplication,
    data: EnterpriseApplicationIntegrationInput,
) -> EnterpriseApplicationIntegration:
    manifest_url = _validate_manifest_url(application, str(data.manifest_url))
    row = await get_integration(db, application.id)
    if row is None:
        row = EnterpriseApplicationIntegration(
            application_id=application.id,
            organization_id=application.organization_id,
            manifest_url=manifest_url,
            sync_enabled=data.sync_enabled,
            sync_status="ready",
        )
        db.add(row)
    else:
        row.manifest_url = manifest_url
        row.sync_enabled = data.sync_enabled
        row.sync_status = "ready"
        row.last_error = None
    if data.clear_auth_token:
        row.auth_token_encrypted = None
    elif data.auth_token:
        row.auth_token_encrypted = encrypt_provider_api_key(data.auth_token)
    await db.flush()
    return row


async def discover_subsystem(
    db: AsyncSession, organization_id: UUID | str, base_url: str, auth_token: str | None = None
) -> dict:
    """Probe the fixed v2 endpoints without creating platform records."""
    entry_url = str(base_url).rstrip("/") + "/"
    try:
        assert_public_http_url(entry_url, require_https=settings.app_env != "development")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    health_url = urljoin(entry_url, "/health")
    manifest_url = urljoin(entry_url, "/api/integration/manifest")
    headers = {"accept": "application/json", "user-agent": "ZhuoJian-Subsystem-Discovery/2.0"}
    if auth_token:
        headers["authorization"] = f"Bearer {auth_token}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False
        ) as client:
            health_response = await client.get(health_url, headers=headers)
            if 300 <= health_response.status_code < 400:
                raise ValueError("Health endpoint must not redirect")
            health_response.raise_for_status()
            manifest_response = await client.get(manifest_url, headers=headers)
            if 300 <= manifest_response.status_code < 400:
                raise ValueError("Manifest endpoint must not redirect")
            manifest_response.raise_for_status()
            if len(manifest_response.content) > 512 * 1024:
                raise ValueError("Manifest exceeds 512KB")
            manifest, _, version = _validate_manifest_payload(
                manifest_response.json(),
                entry_url=entry_url,
                manifest_url=manifest_url,
                expected_slug=None,
            )
            await _match_departments(db, organization_id, manifest)
    except (httpx.HTTPError, ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"Subsystem discovery failed: {exc}") from exc
    return {
        "entry_url": entry_url,
        "manifest_url": manifest_url,
        "health_url": health_url,
        "health_status": "healthy",
        "protocol_version": version,
        "suggested_name": str(manifest.get("applicationName") or manifest["applicationSlug"])[:255],
        "suggested_slug": manifest["applicationSlug"],
        "manifest": manifest,
        "modules": manifest.get("modules") or [],
    }


def integration_read(row: EnterpriseApplicationIntegration) -> dict:
    manifest = row.manifest or {}
    return {
        "application_id": row.application_id,
        "manifest_url": row.manifest_url,
        "events_url": row.events_url,
        "protocol_version": row.protocol_version,
        "manifest": manifest,
        "modules": manifest.get("modules") if isinstance(manifest.get("modules"), list) else [],
        "cursor_sequence": row.cursor_sequence,
        "sync_enabled": row.sync_enabled,
        "sync_status": row.sync_status,
        "token_configured": bool(row.auth_token_encrypted),
        "last_manifest_sync_at": row.last_manifest_sync_at,
        "last_event_sync_at": row.last_event_sync_at,
        "last_error": row.last_error,
    }


def manifest_page(
    integration: EnterpriseApplicationIntegration,
    module_key: str,
    page_key: str,
) -> dict | None:
    manifest = integration.manifest if isinstance(integration.manifest, dict) else {}
    modules = manifest.get("modules") if isinstance(manifest.get("modules"), list) else []
    for module in modules:
        if not isinstance(module, dict) or module.get("moduleKey") != module_key:
            continue
        pages = module.get("pages") if isinstance(module.get("pages"), list) else []
        return next(
            (page for page in pages if isinstance(page, dict) and page.get("pageKey") == page_key),
            None,
        )
    return None


async def replace_routes(
    db: AsyncSession,
    application: EnterpriseApplication,
    items: list[EnterpriseApplicationEventRouteInput],
) -> list[EnterpriseApplicationEventRoute]:
    now = datetime.now(UTC)
    existing = list(
        (
            await db.execute(
                select(EnterpriseApplicationEventRoute).where(
                    EnterpriseApplicationEventRoute.application_id == application.id
                )
            )
        )
        .scalars()
        .all()
    )
    for row in existing:
        row.deleted_at = now
    created: list[EnterpriseApplicationEventRoute] = []
    for item in items:
        scope_id = await skill_scope_service.validate_scope_target(
            db, application.organization_id, item.target_scope_type, item.target_scope_id
        )
        target_application_id = None
        if item.target_application_id:
            target_application = await db.get(EnterpriseApplication, item.target_application_id)
            if (
                target_application is None
                or target_application.deleted_at is not None
                or str(target_application.organization_id) != str(application.organization_id)
            ):
                raise HTTPException(status_code=400, detail="Target application must belong to the same organization")
            target_application_id = target_application.id
        row = EnterpriseApplicationEventRoute(
            application_id=application.id,
            organization_id=application.organization_id,
            name=item.name,
            event_type=item.event_type,
            module_key=item.module_key,
            target_scope_type=item.target_scope_type,
            target_scope_id=scope_id,
            target_application_id=target_application_id,
            target_module_key=item.target_module_key,
            is_active=item.is_active,
        )
        db.add(row)
        created.append(row)
    await db.flush()
    return created


async def list_routes(db: AsyncSession, application_id: UUID | str) -> list[EnterpriseApplicationEventRoute]:
    return list(
        (
            await db.execute(
                select(EnterpriseApplicationEventRoute)
                .where(
                    EnterpriseApplicationEventRoute.application_id == UUID(str(application_id)),
                    EnterpriseApplicationEventRoute.deleted_at.is_(None),
                )
                .order_by(EnterpriseApplicationEventRoute.created_at)
            )
        )
        .scalars()
        .all()
    )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


async def _store_event(
    db: AsyncSession,
    integration: EnterpriseApplicationIntegration,
    event: dict,
) -> tuple[bool, int]:
    sequence = event.get("sequence")
    event_id = str(event.get("eventId") or "")
    event_type = str(event.get("eventType") or "")
    if not isinstance(sequence, int) or sequence <= 0 or not event_id or not event_type:
        raise ValueError("Event requires positive sequence, eventId and eventType")
    if len(event_id) > 200 or len(event_type) > 160:
        raise ValueError("Event identifier is too long")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    values = {
        "application_id": integration.application_id,
        "organization_id": integration.organization_id,
        "event_id": event_id,
        "source_sequence": sequence,
        "event_type": event_type,
        "module_key": str(event.get("moduleKey") or "")[:120] or None,
        "entity_type": str(event.get("entityType") or "")[:120] or None,
        "entity_id": str(event.get("entityId") or "")[:200] or None,
        "action": str(event.get("action") or "")[:80] or None,
        "occurred_at": _parse_datetime(event.get("occurredAt")),
        "payload": payload,
    }
    result = await db.execute(
        insert(EnterpriseApplicationEvent)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["application_id", "event_id"])
        .returning(EnterpriseApplicationEvent.id)
    )
    event_row_id = result.scalar_one_or_none()
    if event_row_id is None:
        return False, 0
    routes = list(
        (
            await db.execute(
                select(EnterpriseApplicationEventRoute).where(
                    EnterpriseApplicationEventRoute.application_id == integration.application_id,
                    EnterpriseApplicationEventRoute.deleted_at.is_(None),
                    EnterpriseApplicationEventRoute.is_active.is_(True),
                    EnterpriseApplicationEventRoute.event_type.in_([event_type, "*"]),
                    or_(
                        EnterpriseApplicationEventRoute.module_key.is_(None),
                        EnterpriseApplicationEventRoute.module_key == values["module_key"],
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    created = 0
    entity_label = values["entity_id"] or values["entity_type"] or "业务记录"
    for route in routes:
        if route.target_application_id:
            delivery_id = str(uuid5(NAMESPACE_URL, f"{route.id}:{event_row_id}"))
            await db.execute(
                insert(EnterpriseApplicationEventDelivery)
                .values(
                    organization_id=integration.organization_id,
                    route_id=route.id,
                    source_event_id=event_row_id,
                    target_application_id=route.target_application_id,
                    delivery_id=delivery_id,
                    status="pending",
                    attempts=0,
                    response={},
                )
                .on_conflict_do_nothing(index_elements=["route_id", "source_event_id"])
            )
        work_result = await db.execute(
            insert(CrossDepartmentWorkItem)
            .values(
                organization_id=integration.organization_id,
                source_application_id=integration.application_id,
                route_id=route.id,
                source_event_id=event_id,
                title=f"{route.name}：{entity_label}"[:300],
                target_scope_type=route.target_scope_type,
                target_scope_id=route.target_scope_id,
                target_module_key=route.target_module_key,
                source_context={
                    "event_type": event_type,
                    "module_key": values["module_key"],
                    "entity_type": values["entity_type"],
                    "entity_id": values["entity_id"],
                    "action": values["action"],
                    "payload": payload,
                },
            )
            .on_conflict_do_nothing(index_elements=["route_id", "source_event_id"])
            .returning(CrossDepartmentWorkItem.id)
        )
        created += int(work_result.scalar_one_or_none() is not None)
    return True, created


async def deliver_pending_events(
    db: AsyncSession,
    *,
    organization_id: UUID | str,
    limit: int = 100,
) -> int:
    deliveries = list((await db.execute(
        select(EnterpriseApplicationEventDelivery)
        .where(
            EnterpriseApplicationEventDelivery.organization_id == UUID(str(organization_id)),
            EnterpriseApplicationEventDelivery.status.in_(["pending", "failed"]),
            EnterpriseApplicationEventDelivery.attempts < 10,
        )
        .order_by(EnterpriseApplicationEventDelivery.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )).scalars().all())
    delivered = 0
    for delivery in deliveries:
        delivery.status = "delivering"
        delivery.attempts += 1
        await db.flush()
        event = await db.get(EnterpriseApplicationEvent, delivery.source_event_id)
        route = await db.get(EnterpriseApplicationEventRoute, delivery.route_id)
        target = await db.get(EnterpriseApplication, delivery.target_application_id)
        integration = await get_integration(db, delivery.target_application_id)
        if not event or not route or not target or not integration or not integration.auth_token_encrypted:
            delivery.status = "failed"
            delivery.last_error = "Target subsystem integration is unavailable"
            continue
        manifest = integration.manifest if isinstance(integration.manifest, dict) else {}
        delivery_path = manifest.get("eventDeliveriesUrl")
        if delivery_path != "/api/integration/event-deliveries":
            delivery.status = "failed"
            delivery.last_error = "Target subsystem does not declare eventDeliveriesUrl"
            continue
        url = urljoin(target.entry_url.rstrip("/") + "/", delivery_path.lstrip("/"))
        try:
            if not same_origin(target.entry_url, url):
                raise ValueError("Event delivery endpoint left the target application origin")
            assert_public_http_url(url, require_https=True)
            now = datetime.now(UTC)
            token = jwt.encode({
                "iss": "zhuojian-saas",
                "aud": target.slug,
                "typ": "zhuojian-event",
                "organizationId": str(delivery.organization_id),
                "deliveryId": delivery.delivery_id,
                "eventId": event.event_id,
                "eventType": event.event_type,
                "targetModuleKey": route.target_module_key,
                "iat": now,
                "exp": now + timedelta(seconds=60),
            }, decrypt_provider_api_key(integration.auth_token_encrypted), algorithm="HS256")
            source = await db.get(EnterpriseApplication, event.application_id)
            body = {
                "deliveryId": delivery.delivery_id,
                "sourceApplicationSlug": source.slug if source else "unknown",
                "event": {
                    "eventId": event.event_id,
                    "eventType": event.event_type,
                    "enterpriseKey": str(manifest.get("enterprise", {}).get("key") or "aifabei"),
                    "moduleKey": event.module_key,
                    "entityType": event.entity_type,
                    "entityId": event.entity_id,
                    "occurredAt": event.occurred_at.isoformat() if event.occurred_at else event.created_at.isoformat(),
                    "payload": event.payload or {},
                },
            }
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0), follow_redirects=False) as client:
                response = await client.post(url, json=body, headers={
                    "authorization": f"Bearer {token}",
                    "user-agent": "ZhuoJian-Subsystem-Event/2.1",
                })
            if 300 <= response.status_code < 400:
                raise RuntimeError("Subsystem event delivery endpoint must not redirect")
            response.raise_for_status()
            result = response.json()
            delivery.status = "delivered"
            delivery.delivered_at = datetime.now(UTC)
            delivery.response = result if isinstance(result, dict) else {"value": result}
            delivery.last_error = None
            delivered += 1
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            delivery.status = "failed"
            delivery.last_error = str(exc)[:1000]
        await db.flush()
    return delivered


async def sync_integration(
    db: AsyncSession,
    application: EnterpriseApplication,
    *,
    batch_limit: int = 200,
) -> dict:
    row = await get_integration(db, application.id)
    if row is None:
        raise HTTPException(status_code=409, detail="Subsystem integration is not configured")
    row.sync_status = "syncing"
    row.last_error = None
    await db.flush()
    received = 0
    work_items = 0
    delivered_events = 0
    try:
        timeout = httpx.Timeout(20.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            manifest_response = await client.get(row.manifest_url, headers=_headers(row))
            manifest_response.raise_for_status()
            if len(manifest_response.content) > 512 * 1024:
                raise ValueError("Manifest exceeds 512KB")
            manifest, events_url, version = _validate_manifest(
                application, manifest_response.json(), row.manifest_url
            )
            await _match_departments(db, application.organization_id, manifest)
            await _sync_actions(db, application, manifest)
            row.manifest = manifest
            row.events_url = events_url
            row.protocol_version = version
            row.last_manifest_sync_at = datetime.now(UTC)

            while received < batch_limit:
                response = await client.get(
                    events_url,
                    params={"after": row.cursor_sequence, "limit": min(100, batch_limit - received)},
                    headers=_headers(row),
                )
                response.raise_for_status()
                if len(response.content) > 2 * 1024 * 1024:
                    raise ValueError("Event feed response exceeds 2MB")
                feed = response.json()
                if not isinstance(feed, dict) or not isinstance(feed.get("items"), list):
                    raise ValueError("Event feed must return an items list")
                items = feed["items"]
                previous = row.cursor_sequence
                for event in items:
                    if not isinstance(event, dict):
                        raise ValueError("Event feed contains a non-object item")
                    sequence = event.get("sequence")
                    if not isinstance(sequence, int) or sequence <= previous:
                        raise ValueError("Event sequence must be strictly ascending")
                    stored, created = await _store_event(db, row, event)
                    received += int(stored)
                    work_items += created
                    previous = sequence
                    row.cursor_sequence = sequence
                if not items or not feed.get("hasMore") or received >= batch_limit:
                    break
            row.last_event_sync_at = datetime.now(UTC)
            delivered_events = await deliver_pending_events(
                db, organization_id=application.organization_id
            )
            row.sync_status = "healthy"
            row.last_error = None
            await db.flush()
        return {
            "status": "healthy",
            "manifest_updated": True,
            "received_events": received,
            "created_work_items": work_items,
            "delivered_events": delivered_events,
            "cursor_sequence": row.cursor_sequence,
            "detail": None,
        }
    except (httpx.HTTPError, ValueError, ValidationError) as exc:
        row.sync_status = "error"
        row.last_error = str(exc)[:1000]
        await db.flush()
        return {
            "status": "error",
            "manifest_updated": False,
            "received_events": received,
            "created_work_items": work_items,
            "delivered_events": delivered_events,
            "cursor_sequence": row.cursor_sequence,
            "detail": row.last_error,
        }


async def list_work_items_for_user(db: AsyncSession, user: CurrentUser) -> list[CrossDepartmentWorkItem]:
    scopes = set(scope_service.effective_scope_set(user))
    clauses = [
        (CrossDepartmentWorkItem.target_scope_type == scope_type)
        & (CrossDepartmentWorkItem.target_scope_id == scope_id)
        for scope_type, scope_id in scopes
    ]
    return list(
        (
            await db.execute(
                select(CrossDepartmentWorkItem)
                .where(
                    CrossDepartmentWorkItem.organization_id == user.organization_id,
                    or_(*clauses),
                )
                .order_by(CrossDepartmentWorkItem.status, CrossDepartmentWorkItem.created_at.desc())
                .limit(500)
            )
        )
        .scalars()
        .all()
    )


async def update_work_item_status(
    db: AsyncSession, user: CurrentUser, item_id: UUID, status: str
) -> CrossDepartmentWorkItem:
    rows = await list_work_items_for_user(db, user)
    item = next((row for row in rows if row.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Work item not found")
    item.status = status
    await db.flush()
    return item


async def run_subsystem_sync_scheduler() -> None:
    """Continuously poll enabled integrations; failures stay isolated per application."""
    while True:
        try:
            async with async_session_factory() as db:
                ids = list(
                    (
                        await db.execute(
                            select(EnterpriseApplicationIntegration.application_id)
                            .join(
                                EnterpriseApplication,
                                EnterpriseApplication.id == EnterpriseApplicationIntegration.application_id,
                            )
                            .where(
                                EnterpriseApplicationIntegration.sync_enabled.is_(True),
                                EnterpriseApplication.is_active.is_(True),
                                EnterpriseApplication.deleted_at.is_(None),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            for application_id in ids:
                try:
                    async with async_session_factory() as db:
                        application = (
                            await db.execute(
                                select(EnterpriseApplication).where(
                                    EnterpriseApplication.id == application_id,
                                    EnterpriseApplication.deleted_at.is_(None),
                                )
                            )
                        ).scalar_one_or_none()
                        if application is not None:
                            await sync_integration(db, application)
                            await db.commit()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - one subsystem must not stop the scheduler
                    logger.warning("subsystem_sync_failed", application_id=str(application_id), error=str(exc)[:500])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("subsystem_scheduler_failed", error=str(exc)[:500])
        await asyncio.sleep(max(15, settings.subsystem_sync_poll_seconds))
