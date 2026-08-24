"""Platform extension import, review, immutable release and activation workflow."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dsh import client as dsh_client
from app.database import async_session_factory
from app.models.platform_extension import (
    PlatformExtensionRelease,
    PlatformExtensionReleaseEvent,
    PlatformExtensionSource,
)
from app.services import extension_builder_client, storage_gateway_service
from app.services.platform_extension_catalog import baseline_manifest, catalog_items
from app.services.platform_tool_registry import platform_managed_tool_names

_RELEASE_SEQUENCE_LOCK = 6_238_716_421


def _canonical_value(value):
    """Normalize JSON values so Python and the Node runtime hash identical data."""
    if isinstance(value, dict):
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def manifest_checksum(manifest: dict) -> str:
    raw = json.dumps(
        _canonical_value(manifest),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


async def record_event(
    db: AsyncSession,
    *,
    event_type: str,
    actor_admin_id: int | None,
    source_id: UUID | None = None,
    release_id: UUID | None = None,
    status: str = "ok",
    details: dict | None = None,
) -> PlatformExtensionReleaseEvent:
    event = PlatformExtensionReleaseEvent(
        source_id=source_id,
        release_id=release_id,
        actor_admin_id=actor_admin_id,
        event_type=event_type,
        status=status,
        details=details or {},
    )
    db.add(event)
    await db.flush()
    return event


async def ensure_baseline(db: AsyncSession, admin_id: int) -> PlatformExtensionRelease:
    active = (
        await db.execute(select(PlatformExtensionRelease).where(PlatformExtensionRelease.is_active.is_(True)))
    ).scalar_one_or_none()
    if active:
        return active
    # The console loads overview, catalog and releases in parallel on first use.
    # Serialize baseline creation so those requests cannot create competing active rows.
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _RELEASE_SEQUENCE_LOCK})
    active = (
        await db.execute(select(PlatformExtensionRelease).where(PlatformExtensionRelease.is_active.is_(True)))
    ).scalar_one_or_none()
    if active:
        return active
    manifest = baseline_manifest()
    release = PlatformExtensionRelease(
        version_no=1,
        name="平台基线",
        manifest=manifest,
        checksum=manifest_checksum(manifest),
        status="active",
        is_active=True,
        created_by_admin_id=admin_id,
        published_by_admin_id=admin_id,
        activated_at=datetime.now(UTC),
        validation_report={"status": "baseline", "migrated_without_behavior_change": True},
    )
    db.add(release)
    await db.flush()
    await record_event(
        db,
        event_type="baseline_created",
        actor_admin_id=admin_id,
        release_id=release.id,
        details={"checksum": release.checksum},
    )
    return release


async def _next_release_version(db: AsyncSession) -> int:
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _RELEASE_SEQUENCE_LOCK})
    return int((await db.execute(select(func.max(PlatformExtensionRelease.version_no)))).scalar() or 0) + 1


async def list_catalog(db: AsyncSession, admin_id: int) -> list[dict]:
    active = await ensure_baseline(db, admin_id)
    rows = catalog_items()
    plugin_states = {
        str(item.get("slug")): item.get("enabled", True)
        for item in (active.manifest or {}).get("plugins") or []
    }
    tool_states = {
        str(item.get("slug")): item.get("enabled", True)
        for item in (active.manifest or {}).get("system_tools") or []
    }
    for row in rows:
        states = tool_states if row["kind"] == "system_tool" else plugin_states
        if row["slug"] in states:
            row["status"] = "enabled" if states[row["slug"]] else "disabled"
    sources = list(
        (await db.execute(select(PlatformExtensionSource).order_by(PlatformExtensionSource.created_at.desc())))
        .scalars()
        .all()
    )
    for source in sources:
        manifest = source.manifest or {}
        rows.append(
            {
                "slug": manifest.get("slug") or f"source-{source.id}",
                "name": manifest.get("name") or source.locator,
                "version": manifest.get("version") or source.resolved_version or source.requested_version or "unknown",
                "description": manifest.get("description") or "外部导入候选",
                "kind": manifest.get("type") or "adapter_required",
                "source": "reviewed" if source.review_status == "approved" else "external",
                "status": source.status,
                "removable": True,
                "capabilities": manifest.get("provides") or [],
                "compatibility_warnings": (source.compatibility or {}).get("warnings") or [],
            }
        )
    return rows


async def create_source(
    db: AsyncSession,
    *,
    source_type: str,
    locator: str,
    requested_version: str | None,
    admin_id: int,
    input_ref: str | None = None,
) -> PlatformExtensionSource:
    source = PlatformExtensionSource(
        source_type=source_type,
        locator=locator,
        requested_version=requested_version,
        imported_by_admin_id=admin_id,
        status="importing",
        review_status="pending",
        build_report={"input_ref": input_ref} if input_ref else {},
    )
    db.add(source)
    await db.flush()
    await record_event(
        db,
        event_type="import_created",
        actor_admin_id=admin_id,
        source_id=source.id,
        details={"source_type": source_type, "locator": locator},
    )
    return source


async def process_source_build(source_id: UUID) -> None:
    async with async_session_factory() as db:
        source = (
            await db.execute(
                select(PlatformExtensionSource)
                .where(PlatformExtensionSource.id == source_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not source or source.status != "importing":
            return
        source.status = "building"
        source.error = None
        await record_event(
            db, event_type="build_started", actor_admin_id=source.imported_by_admin_id, source_id=source.id
        )
        await db.commit()
        try:
            payload = {
                "source_type": source.source_type,
                "locator": source.locator,
                "version": source.requested_version,
            }
            input_ref = (source.build_report or {}).get("input_ref")
            if input_ref:
                signed = await storage_gateway_service.get_signed_download(input_ref)
                payload["archive_url"] = signed["url"]
                payload["archive_headers"] = signed.get("headers") or {}
            result = await extension_builder_client.build(payload)
            artifact_ref = str(result.get("artifact_ref") or "")
            artifact_sha256 = str(result.get("sha256") or "")
            if (
                not storage_gateway_service.is_object_ref(artifact_ref)
                or re.fullmatch(r"[a-f0-9]{64}", artifact_sha256) is None
            ):
                raise RuntimeError("Builder did not return a verified OSS artifact")
            source.artifact_ref = artifact_ref
            source.artifact_sha256 = artifact_sha256
            source.resolved_version = result.get("resolved_version")
            source.commit_sha = result.get("commit_sha")
            source.manifest = result.get("manifest") or {}
            source.compatibility = result.get("compatibility") or {}
            source.build_report = result.get("report") or {}
            publishable = bool(result.get("publishable"))
            source.status = "review_required" if publishable else "incompatible"
            source.error = None if publishable else result.get("error") or "需要平台适配器，不能发布"
            await record_event(
                db,
                event_type="build_completed",
                actor_admin_id=source.imported_by_admin_id,
                source_id=source.id,
                status="ok" if publishable else "incompatible",
                details={"sha256": source.artifact_sha256, "publishable": publishable},
            )
        except Exception as exc:
            source.status = "failed"
            source.error = str(exc)[:2000]
            await record_event(
                db,
                event_type="build_failed",
                actor_admin_id=source.imported_by_admin_id,
                source_id=source.id,
                status="failed",
                details={"error": source.error},
            )
        await db.commit()


async def approve_source(
    db: AsyncSession,
    source: PlatformExtensionSource,
    *,
    admin_id: int,
    approved: bool,
    note: str | None,
) -> PlatformExtensionSource:
    if source.status not in {"review_required", "ready"}:
        raise HTTPException(status_code=409, detail="Only a compatible reviewed build can be approved")
    source.review_status = "approved" if approved else "rejected"
    source.status = "ready" if approved else "review_required"
    source.approved_by_admin_id = admin_id if approved else None
    source.approved_at = datetime.now(UTC) if approved else None
    await record_event(
        db,
        event_type="source_approved" if approved else "source_rejected",
        actor_admin_id=admin_id,
        source_id=source.id,
        details={"note": note},
    )
    await db.flush()
    return source


def _enabled_coordinators(manifest: dict) -> list[str]:
    found = []
    for item in [*(manifest.get("plugins") or []), *(manifest.get("external_extensions") or [])]:
        if item.get("enabled", True) and "coordinator" in (item.get("capabilities") or item.get("provides") or []):
            found.append(str(item.get("slug")))
    return found


async def create_release(
    db: AsyncSession,
    *,
    name: str,
    source_ids: list[UUID],
    config: dict,
    admin_id: int,
) -> PlatformExtensionRelease:
    active = await ensure_baseline(db, admin_id)
    manifest = json.loads(json.dumps(active.manifest))
    # A candidate is a complete immutable snapshot. Rebuild external entries
    # from the explicit selection so removing a source really uninstalls it.
    manifest["external_extensions"] = []
    disabled = set(config.get("disabled_plugins") or [])
    disabled_tool_groups = set(config.get("disabled_tool_groups") or [])
    for plugin in manifest.get("plugins", []):
        if plugin.get("slug") in disabled:
            if plugin.get("required") and "coordinator" not in (plugin.get("capabilities") or []):
                raise HTTPException(status_code=409, detail=f"Core plugin {plugin['slug']} cannot be disabled")
            plugin["enabled"] = False
    for group in manifest.get("system_tools", []):
        group["enabled"] = group.get("slug") not in disabled_tool_groups
    if source_ids:
        sources = list(
            (await db.execute(select(PlatformExtensionSource).where(PlatformExtensionSource.id.in_(source_ids))))
            .scalars()
            .all()
        )
        if len(sources) != len(set(source_ids)):
            raise HTTPException(status_code=404, detail="Extension source not found")
        for source in sources:
            if source.status != "ready" or source.review_status != "approved":
                raise HTTPException(status_code=409, detail=f"Source {source.id} is not approved and ready")
            kind = (source.manifest or {}).get("type")
            if kind not in {"runtime_plugin", "system_tool"}:
                raise HTTPException(status_code=409, detail=f"Source {source.id} needs an adapter")
            if not source.artifact_ref or not source.artifact_sha256:
                raise HTTPException(status_code=409, detail=f"Source {source.id} has no verified build artifact")
            manifest.setdefault("external_extensions", []).append(
                {
                    **source.manifest,
                    "source_id": str(source.id),
                    "artifact_ref": source.artifact_ref,
                    "artifact_sha256": source.artifact_sha256,
                    "enabled": True,
                    "capabilities": (source.manifest or {}).get("provides") or [],
                }
            )
    enabled_extensions = [item for item in manifest.get("external_extensions", []) if item.get("enabled", True)]
    slugs = [str(item.get("slug")) for item in enabled_extensions]
    if len(slugs) != len(set(slugs)):
        raise HTTPException(status_code=409, detail="A release cannot contain duplicate extension slugs")
    external_tool_names: list[str] = [
        str(tool.get("name"))
        for item in enabled_extensions
        if item.get("type") == "system_tool"
        for tool in (item.get("tools") or [])
    ]
    if len(external_tool_names) != len(set(external_tool_names)):
        raise HTTPException(status_code=409, detail="External system tools must have unique names")
    collisions = sorted(set(external_tool_names) & platform_managed_tool_names())
    if collisions:
        raise HTTPException(
            status_code=409,
            detail=f"External tools cannot replace protected platform tool names: {collisions}",
        )
    providers = {
        capability
        for item in [*(manifest.get("plugins") or []), *enabled_extensions]
        if item.get("enabled", True)
        for capability in (item.get("capabilities") or item.get("provides") or [])
    }
    enabled_tool_groups = [
        group for group in manifest.get("system_tools") or [] if group.get("enabled", True)
    ]
    platform_capabilities = providers | {
        str(value)
        for group in enabled_tool_groups
        for value in [group.get("slug"), *(group.get("tools") or [])]
        if value
    }
    for item in enabled_extensions:
        missing = sorted(set(item.get("requires") or []) - providers)
        conflicts = sorted(set(item.get("conflicts") or []) & providers)
        if missing:
            raise HTTPException(status_code=409, detail=f"Extension {item.get('slug')} requires {missing}")
        if conflicts:
            raise HTTPException(status_code=409, detail=f"Extension {item.get('slug')} conflicts with {conflicts}")
        for tool in item.get("tools") or []:
            missing_tool_capabilities = sorted(
                set(tool.get("required_platform_capabilities") or []) - platform_capabilities
            )
            if missing_tool_capabilities:
                raise HTTPException(
                    status_code=409,
                    detail=f"Tool {tool.get('name')} requires platform capabilities {missing_tool_capabilities}",
                )
    manifest["release_config"] = config
    coordinators = _enabled_coordinators(manifest)
    if len(coordinators) != 1:
        raise HTTPException(
            status_code=409,
            detail=f"A release must contain exactly one coordinator; found {coordinators}",
        )
    next_version = await _next_release_version(db)
    release = PlatformExtensionRelease(
        version_no=next_version,
        name=name,
        manifest=manifest,
        checksum=manifest_checksum(manifest),
        status="draft",
        is_active=False,
        base_release_id=active.id,
        created_by_admin_id=admin_id,
    )
    db.add(release)
    await db.flush()
    await record_event(
        db,
        event_type="release_created",
        actor_admin_id=admin_id,
        release_id=release.id,
        details={"source_ids": [str(v) for v in source_ids]},
    )
    return release


async def validate_release(
    db: AsyncSession, release: PlatformExtensionRelease, admin_id: int
) -> PlatformExtensionRelease:
    release.status = "validating"
    release.error = None
    await db.flush()
    try:
        report = await dsh_client.validate_release(
            str(release.id),
            await runtime_manifest(release.manifest),
            release.checksum,
        )
        release.validation_report = report
        release.status = "ready" if report.get("ok") else "failed"
        release.error = None if report.get("ok") else str(report.get("error") or "Candidate validation failed")
    except Exception as exc:  # noqa: BLE001 - candidate failures are persisted for review
        release.status = "failed"
        release.error = str(exc)[:2000]
        release.validation_report = {"ok": False, "error": release.error}
    await record_event(
        db,
        event_type="release_validated",
        actor_admin_id=admin_id,
        release_id=release.id,
        status=release.status,
        details=release.validation_report,
    )
    await db.flush()
    return release


async def publish_release(
    db: AsyncSession, release: PlatformExtensionRelease, admin_id: int
) -> PlatformExtensionRelease:
    if release.status != "ready":
        raise HTTPException(status_code=409, detail="Release must pass candidate validation before publishing")
    release_id = release.id
    release.status = "publishing"
    await db.flush()
    await record_event(db, event_type="publish_started", actor_admin_id=admin_id, release_id=release.id)
    previous = (
        await db.execute(
            select(PlatformExtensionRelease).where(
                PlatformExtensionRelease.is_active.is_(True),
                PlatformExtensionRelease.id != release.id,
            )
        )
    ).scalar_one_or_none()
    previous_snapshot = (
        (str(previous.id), json.loads(json.dumps(previous.manifest)), previous.checksum)
        if previous is not None
        else None
    )
    # Persist the append-only start event before making the external runtime call.
    # Otherwise a failed activation would roll back the only evidence that a publish was attempted.
    await db.commit()
    runtime_switched = False
    try:
        result = await dsh_client.activate_release(
            str(release.id),
            await runtime_manifest(release.manifest),
            release.checksum,
        )
        if not result.get("ok"):
            raise RuntimeError(str(result.get("error") or "Runtime health confirmation failed"))
        runtime_switched = True
        await db.execute(
            update(PlatformExtensionRelease)
            .where(PlatformExtensionRelease.is_active.is_(True), PlatformExtensionRelease.id != release.id)
            .values(is_active=False, status="superseded")
        )
        release.status = "active"
        release.is_active = True
        release.published_by_admin_id = admin_id
        release.activated_at = datetime.now(UTC)
        release.validation_report = {**(release.validation_report or {}), "activation": result}
        await record_event(
            db, event_type="publish_completed", actor_admin_id=admin_id, release_id=release.id, details=result
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        release = await db.get(PlatformExtensionRelease, release_id)
        if release is None:
            raise
        runtime_restored = False
        if runtime_switched and previous_snapshot is not None:
            try:
                await dsh_client.activate_release(
                    previous_snapshot[0],
                    await runtime_manifest(previous_snapshot[1]),
                    previous_snapshot[2],
                )
                runtime_restored = True
            except Exception:
                pass
        release.status = "failed"
        release.error = str(exc)[:2000]
        await record_event(
            db,
            event_type="publish_failed",
            actor_admin_id=admin_id,
            release_id=release.id,
            status="failed",
            details={"error": release.error, "runtime_restored": runtime_restored},
        )
        if runtime_restored:
            await record_event(
                db,
                event_type="automatic_runtime_rollback",
                actor_admin_id=admin_id,
                release_id=release.id,
                details={"restored_release_id": previous_snapshot[0]},
            )
        await db.commit()
    return release


async def rollback_release(
    db: AsyncSession,
    target: PlatformExtensionRelease,
    *,
    admin_id: int,
) -> PlatformExtensionRelease:
    active = await ensure_baseline(db, admin_id)
    next_version = await _next_release_version(db)
    copy = PlatformExtensionRelease(
        version_no=next_version,
        name=f"回滚至 v{target.version_no}",
        manifest=json.loads(json.dumps(target.manifest)),
        checksum=target.checksum,
        status="draft",
        is_active=False,
        base_release_id=active.id,
        created_by_admin_id=admin_id,
    )
    db.add(copy)
    await db.flush()
    await record_event(
        db,
        event_type="rollback_created",
        actor_admin_id=admin_id,
        release_id=copy.id,
        details={"target_release_id": str(target.id)},
    )
    return copy


async def sync_active_release_to_runtime() -> None:
    """Re-activate the DB fact-source after a DSH container restart."""
    async with async_session_factory() as db:
        active = (
            await db.execute(select(PlatformExtensionRelease).where(PlatformExtensionRelease.is_active.is_(True)))
        ).scalar_one_or_none()
        if not active:
            return
        health = await dsh_client.runtime_health()
        if health.get("release_id") == str(active.id) and health.get("release_checksum") == active.checksum:
            return
        try:
            await dsh_client.activate_release(
                str(active.id),
                await runtime_manifest(active.manifest),
                active.checksum,
            )
        except Exception:
            return


async def runtime_manifest(manifest: dict) -> dict:
    """Attach ephemeral artifact URLs without changing the immutable checksum source."""
    value = json.loads(json.dumps(manifest))
    for item in value.get("external_extensions") or []:
        ref = item.get("artifact_ref")
        if ref:
            signed = await storage_gateway_service.get_signed_download(ref)
            item["artifact_url"] = signed["url"]
            item["artifact_headers"] = signed.get("headers") or {}
    return value
