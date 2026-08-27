"""Manifest discovery and replay-safe event ingestion for independently deployed subsystems."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import httpx
import structlog
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_auth import CurrentUser
from app.config import settings
from app.database import async_session_factory
from app.models.enterprise_application import (
    CrossDepartmentWorkItem,
    EnterpriseApplication,
    EnterpriseApplicationEvent,
    EnterpriseApplicationEventRoute,
    EnterpriseApplicationIntegration,
)
from app.schemas.enterprise_application import (
    EnterpriseApplicationEventRouteInput,
    EnterpriseApplicationIntegrationInput,
)
from app.services import scope_service, skill_scope_service
from app.utils.crypto import decrypt_provider_api_key, encrypt_provider_api_key

logger = structlog.get_logger()


def _same_origin(entry_url: str, candidate: str) -> bool:
    entry = urlsplit(entry_url)
    target = urlsplit(candidate)
    return (
        target.scheme in {"http", "https"}
        and target.username is None
        and target.password is None
        and (entry.scheme, entry.hostname, entry.port) == (target.scheme, target.hostname, target.port)
    )


def _validate_manifest_url(application: EnterpriseApplication, value: str) -> str:
    url = str(value)
    if not _same_origin(application.entry_url, url):
        raise HTTPException(status_code=422, detail="Manifest URL must use the application entry URL origin")
    parsed = urlsplit(url)
    if settings.app_env != "development" and parsed.scheme != "https":
        raise HTTPException(status_code=422, detail="Production subsystem integration requires HTTPS")
    return url


def _headers(row: EnterpriseApplicationIntegration) -> dict[str, str]:
    headers = {"accept": "application/json", "user-agent": "ZhuoJian-Subsystem-Sync/1.0"}
    if row.auth_token_encrypted:
        headers["authorization"] = f"Bearer {decrypt_provider_api_key(row.auth_token_encrypted)}"
    return headers


def _validate_manifest(application: EnterpriseApplication, payload: object, manifest_url: str) -> tuple[dict, str]:
    if not isinstance(payload, dict) or payload.get("protocol") != "zhuojian-subsystem":
        raise ValueError("Manifest protocol must be 'zhuojian-subsystem'")
    if payload.get("version") != 1:
        raise ValueError("Only subsystem protocol version 1 is supported")
    if payload.get("applicationSlug") != application.slug:
        raise ValueError("Manifest applicationSlug does not match the registered application")
    modules = payload.get("modules")
    if not isinstance(modules, list) or len(modules) > 500:
        raise ValueError("Manifest modules must be a list with at most 500 entries")
    module_keys: set[str] = set()
    for module in modules:
        if not isinstance(module, dict):
            raise ValueError("Manifest module entries must be objects")
        key = str(module.get("key") or module.get("moduleKey") or "").strip()
        if not key or len(key) > 120 or key in module_keys:
            raise ValueError("Manifest module keys must be unique and 1-120 characters")
        module_keys.add(key)
    event_feed = payload.get("eventFeed")
    if not isinstance(event_feed, dict) or not event_feed.get("path"):
        raise ValueError("Manifest eventFeed.path is required")
    events_url = urljoin(manifest_url, str(event_feed["path"]))
    if not _same_origin(application.entry_url, events_url):
        raise ValueError("Event feed must use the registered application origin")
    return payload, events_url


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
        row = EnterpriseApplicationEventRoute(
            application_id=application.id,
            organization_id=application.organization_id,
            name=item.name,
            event_type=item.event_type,
            module_key=item.module_key,
            target_scope_type=item.target_scope_type,
            target_scope_id=scope_id,
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
    inserted = result.scalar_one_or_none() is not None
    if not inserted:
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
    try:
        timeout = httpx.Timeout(20.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            manifest_response = await client.get(row.manifest_url, headers=_headers(row))
            manifest_response.raise_for_status()
            if len(manifest_response.content) > 512 * 1024:
                raise ValueError("Manifest exceeds 512KB")
            manifest, events_url = _validate_manifest(application, manifest_response.json(), row.manifest_url)
            row.manifest = manifest
            row.events_url = events_url
            row.protocol_version = 1
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
            row.sync_status = "healthy"
            row.last_error = None
            await db.flush()
        return {
            "status": "healthy",
            "manifest_updated": True,
            "received_events": received,
            "created_work_items": work_items,
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
