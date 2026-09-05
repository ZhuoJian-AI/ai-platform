"""Platform extension import, review, immutable release and activation workflow."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import UUID

import structlog
from fastapi import HTTPException
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dsh import client as dsh_client
from app.database import async_session_factory
from app.models.platform_extension import (
    PlatformExtensionCatalogEntry,
    PlatformExtensionRelease,
    PlatformExtensionReleaseEvent,
    PlatformExtensionSource,
)
from app.services import extension_builder_client, storage_gateway_service
from app.services.platform_extension_catalog import DSH_VERSION, NODE_VERSION, baseline_manifest, catalog_items
from app.services.platform_extension_versioning import (
    BASELINE_RELEASE_NAME,
    BASELINE_VALIDATION_STATUS,
    ReleaseVersionHealPlan,
    ReleaseVersionHealRefusal,
    manifest_dsh_version,
    needs_dsh_version_heal,
    plan_release_version_heal,
    rewrite_manifest_dsh_version,
)
from app.services.platform_tool_registry import platform_managed_tool_names

logger = structlog.get_logger()

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


async def _active_release(db: AsyncSession) -> PlatformExtensionRelease | None:
    return (
        await db.execute(select(PlatformExtensionRelease).where(PlatformExtensionRelease.is_active.is_(True)))
    ).scalar_one_or_none()


async def ensure_baseline(db: AsyncSession, admin_id: int) -> PlatformExtensionRelease:
    active = await _active_release(db)
    if active:
        active, _ = await heal_active_release_version(db, active, actor_admin_id=admin_id)
        return active
    # The console loads overview, catalog and releases in parallel on first use.
    # Serialize baseline creation so those requests cannot create competing active rows.
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _RELEASE_SEQUENCE_LOCK})
    active = await _active_release(db)
    if active:
        active, _ = await heal_active_release_version(db, active, actor_admin_id=admin_id)
        return active
    manifest = baseline_manifest()
    release = PlatformExtensionRelease(
        version_no=1,
        name=BASELINE_RELEASE_NAME,
        manifest=manifest,
        checksum=manifest_checksum(manifest),
        status="active",
        is_active=True,
        created_by_admin_id=admin_id,
        published_by_admin_id=admin_id,
        activated_at=datetime.now(UTC),
        validation_report={"status": BASELINE_VALIDATION_STATUS, "migrated_without_behavior_change": True},
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


async def _heal_already_refused(db: AsyncSession, release_id: UUID, to_version: str) -> bool:
    """Only one ``release_version_heal_skipped`` event per release per target version."""
    existing = (
        await db.execute(
            select(PlatformExtensionReleaseEvent.id)
            .where(
                PlatformExtensionReleaseEvent.release_id == release_id,
                PlatformExtensionReleaseEvent.event_type == "release_version_heal_skipped",
                PlatformExtensionReleaseEvent.details["to_dsh_version"].astext == to_version,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return existing is not None


async def heal_active_release_version(
    db: AsyncSession,
    active: PlatformExtensionRelease,
    *,
    actor_admin_id: int | None,
) -> tuple[PlatformExtensionRelease, dict | None]:
    """Bring the active release to the DSH version this backend ships (``DSH_VERSION``).

    Release rows are immutable snapshots, so after a DSH upgrade the active manifest still
    names the previous version and ``verifyRelease`` in the runtime refuses to activate it.
    The decision lives in ``platform_extension_versioning.plan_release_version_heal``; this
    function persists it as a new active row (keeping the stale row as ``superseded`` history)
    and records a ``release_version_healed`` event.  A custom release whose items are not
    compatible with the current catalog is left untouched with a warning and one
    ``release_version_heal_skipped`` event.

    Returns the release to use from now on and the heal details (``None`` when nothing changed).
    Callers run inside a transaction; the caller commits.
    """
    if not needs_dsh_version_heal(active.manifest):
        return active, None
    # Same lock as baseline creation / version allocation: parallel console requests and the
    # startup sync must not race to supersede the same row.  Re-read after acquiring it.
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _RELEASE_SEQUENCE_LOCK})
    current = await _active_release(db)
    if current is None:
        return active, None
    active = current
    plan = plan_release_version_heal(
        name=active.name,
        validation_report=active.validation_report,
        manifest=active.manifest,
    )
    if plan is None:
        return active, None
    if isinstance(plan, ReleaseVersionHealRefusal):
        logger.warning(
            "platform_extension_release_version_incompatible",
            release_id=str(active.id),
            release_name=active.name,
            version_no=active.version_no,
            release_dsh_version=plan.from_dsh_version,
            platform_dsh_version=plan.to_dsh_version,
            reasons=plan.reasons,
            action="republish the release from the extension console; the runtime stays on its built-in baseline",
        )
        if not await _heal_already_refused(db, active.id, plan.to_dsh_version):
            await record_event(
                db,
                event_type="release_version_heal_skipped",
                actor_admin_id=actor_admin_id,
                release_id=active.id,
                status="incompatible",
                details={
                    "from_dsh_version": plan.from_dsh_version,
                    "to_dsh_version": plan.to_dsh_version,
                    "reasons": plan.reasons,
                },
            )
        return active, None
    assert isinstance(plan, ReleaseVersionHealPlan)
    previous_id = active.id
    previous_checksum = active.checksum
    # Deactivate first: ``uq_platform_extension_releases_one_active`` is checked per statement.
    active.is_active = False
    active.status = "superseded"
    await db.flush()
    release = PlatformExtensionRelease(
        version_no=await _next_release_version(db),
        name=plan.name,
        manifest=plan.manifest,
        checksum=manifest_checksum(plan.manifest),
        status="active",
        is_active=True,
        base_release_id=previous_id,
        created_by_admin_id=actor_admin_id or active.created_by_admin_id,
        published_by_admin_id=actor_admin_id or active.published_by_admin_id or active.created_by_admin_id,
        activated_at=datetime.now(UTC),
        validation_report={
            **plan.validation_report,
            "healed_from": {**plan.validation_report.get("healed_from", {}), "release_id": str(previous_id)},
        },
    )
    db.add(release)
    await db.flush()
    details = {
        "mode": plan.mode,
        "previous_release_id": str(previous_id),
        "previous_checksum": previous_checksum,
        "from_dsh_version": plan.from_dsh_version,
        "to_dsh_version": plan.to_dsh_version,
        "checksum": release.checksum,
    }
    await record_event(
        db,
        event_type="release_version_healed",
        actor_admin_id=actor_admin_id,
        release_id=release.id,
        details=details,
    )
    logger.info(
        "platform_extension_release_version_healed",
        release_id=str(release.id),
        version_no=release.version_no,
        previous_release_id=str(previous_id),
        mode=plan.mode,
        from_dsh_version=plan.from_dsh_version,
        to_dsh_version=plan.to_dsh_version,
    )
    return release, details


async def _next_release_version(db: AsyncSession) -> int:
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _RELEASE_SEQUENCE_LOCK})
    return int((await db.execute(select(func.max(PlatformExtensionRelease.version_no)))).scalar() or 0) + 1


def _core_catalog_row(row: dict) -> dict:
    layer = {
        "dsh-agent-loop": "coordinator",
        "dsh-llm-runtime": "model_adapter",
        "dsh-session": "runtime",
        "dsh-system-prompt": "runtime",
        "dsh-tools": "runtime",
        "dsh-agent": "runtime",
    }.get(row["slug"], "system_tool" if row["kind"] == "system_tool" else "runtime")
    warnings = row.get("compatibility_warnings") or []
    return {
        **row,
        "id": None,
        "source": "official",
        "layer": layer,
        "operation": "replace" if layer == "coordinator" else "add",
        "trust_level": "platform",
        "runtime_requirements": {"node": NODE_VERSION, "dsh": DSH_VERSION},
        "compatibility_status": "needs_adapter" if row["kind"] == "adapter_required" else "compatible",
        "compatibility_reasons": warnings,
        "repository": "https://github.com/deepseek-ai/deepseek-harness",
        "homepage": "https://deepseek.com/harness/",
        "package_name": f"@deepseek-ai/{row['slug']}" if row["slug"].startswith("dsh-") else None,
        "available_versions": [row["version"]] if row["version"] != "platform" else [],
        "category": "official",
        "metadata": {},
        "lifecycle_status": "available",
        "installed": False,
        "installed_version": None,
        "active_source_id": None,
        "latest_source_id": None,
    }


def catalog_entry_to_item(row: PlatformExtensionCatalogEntry) -> dict:
    return {
        "id": row.id,
        "slug": row.slug,
        "name": row.name,
        "version": row.version or "待选择",
        "description": row.description,
        "kind": row.kind,
        "source": row.provider,
        "status": row.compatibility_status,
        "removable": True,
        "capabilities": [],
        "compatibility_warnings": row.compatibility_reasons,
        "layer": row.layer,
        "operation": row.operation,
        "trust_level": row.trust_level,
        "runtime_requirements": row.runtime_requirements,
        "compatibility_status": row.compatibility_status,
        "compatibility_reasons": row.compatibility_reasons,
        "repository": row.repository,
        "homepage": row.homepage,
        "package_name": row.package_name,
        "available_versions": row.available_versions,
        "category": row.category,
        "metadata": row.metadata_payload,
        "lifecycle_status": "available",
        "installed": False,
        "installed_version": None,
        "active_source_id": None,
        "latest_source_id": None,
    }


def _manifest_source_map(manifest: dict) -> dict[str, dict]:
    return {
        str(item.get("source_id")): item
        for item in (manifest or {}).get("external_extensions") or []
        if item.get("source_id") and item.get("enabled", True)
    }


def _source_catalog_entry_id(source: PlatformExtensionSource) -> str | None:
    value = (source.build_report or {}).get("catalog_entry_id")
    return str(value) if value else None


def _source_item(source: PlatformExtensionSource) -> dict:
    manifest = source.manifest or {}
    return {
        "id": None,
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
        "layer": manifest.get("layer") or (
            "coordinator" if "coordinator" in (manifest.get("provides") or []) else
            "system_tool" if manifest.get("type") == "system_tool" else "runtime"
        ),
        "operation": manifest.get("operation") or (
            "replace" if "coordinator" in (manifest.get("provides") or []) else "add"
        ),
        "trust_level": "platform_reviewed" if source.review_status == "approved" else "external",
        "runtime_requirements": manifest.get("runtime_requirements") or {},
        "compatibility_status": "compatible" if source.status == "ready" else source.status,
        "compatibility_reasons": (source.compatibility or {}).get("warnings") or [],
        "repository": source.locator if source.source_type == "github" else None,
        "homepage": None,
        "package_name": source.locator if source.source_type == "npm" else None,
        "available_versions": [source.resolved_version] if source.resolved_version else [],
        "category": "imported",
        "metadata": {"source_id": str(source.id), "review_status": source.review_status},
        "lifecycle_status": "available",
        "installed": False,
        "installed_version": None,
        "active_source_id": None,
        "latest_source_id": source.id,
    }


def _source_lifecycle(
    source: PlatformExtensionSource | None,
    *,
    active_sources: dict[str, dict],
    candidate_source_ids: set[str],
) -> tuple[str, bool, str | None, UUID | None]:
    if source is None:
        return "not_imported", False, None, None
    source_id = str(source.id)
    active_item = active_sources.get(source_id)
    if active_item is not None:
        return (
            "installed",
            True,
            str(active_item.get("version") or source.resolved_version or source.requested_version or "unknown"),
            source.id,
        )
    if source_id in candidate_source_ids:
        return "candidate", False, None, None
    if source.status in {"importing", "building", "failed", "incompatible", "review_required"}:
        return source.status, False, None, None
    if source.status == "ready" and source.review_status == "approved":
        return "approved", False, None, None
    return source.status or "not_imported", False, None, None


async def _catalog_rows(db: AsyncSession, admin_id: int) -> list[dict]:
    active = await ensure_baseline(db, admin_id)
    rows = [_core_catalog_row(row) for row in catalog_items()]
    plugin_states = {
        str(item.get("slug")): item
        for item in (active.manifest or {}).get("plugins") or []
    }
    tool_states = {
        str(item.get("slug")): item
        for item in (active.manifest or {}).get("system_tools") or []
    }
    for row in rows:
        states = tool_states if row["kind"] == "system_tool" else plugin_states
        manifest_item = states.get(row["slug"])
        enabled = bool(manifest_item and manifest_item.get("enabled", True))
        row["status"] = "enabled" if enabled else "disabled"
        row["lifecycle_status"] = "installed" if enabled else "disabled"
        row["installed"] = enabled
        row["installed_version"] = row["version"] if enabled else None

    discovery = list((await db.execute(
        select(PlatformExtensionCatalogEntry)
        .where(
            PlatformExtensionCatalogEntry.is_active.is_(True),
            PlatformExtensionCatalogEntry.provider == "community",
        )
        .order_by(PlatformExtensionCatalogEntry.name)
    )).scalars().all())
    sources = list((await db.execute(
        select(PlatformExtensionSource).order_by(PlatformExtensionSource.created_at.desc())
    )).scalars().all())
    releases = list((await db.execute(
        select(PlatformExtensionRelease).where(PlatformExtensionRelease.is_active.is_(False))
    )).scalars().all())
    active_sources = _manifest_source_map(active.manifest or {})
    candidate_source_ids = {
        source_id
        for release in releases
        if release.status in {"draft", "validating", "ready", "publishing"}
        for source_id in _manifest_source_map(release.manifest or {})
    }

    linked_by_entry: dict[str, PlatformExtensionSource] = {}
    unlinked_sources: list[PlatformExtensionSource] = []
    entry_by_locator = {
        locator: str(entry.id)
        for entry in discovery
        for locator in (entry.package_name, entry.repository)
        if locator
    }
    for source in sources:
        entry_id = _source_catalog_entry_id(source) or entry_by_locator.get(source.locator)
        if entry_id and entry_id not in linked_by_entry:
            linked_by_entry[entry_id] = source
        elif not entry_id:
            unlinked_sources.append(source)

    for entry in discovery:
        item = catalog_entry_to_item(entry)
        source = linked_by_entry.get(str(entry.id))
        lifecycle, installed, installed_version, active_source_id = _source_lifecycle(
            source,
            active_sources=active_sources,
            candidate_source_ids=candidate_source_ids,
        )
        item.update({
            "status": source.status if source else item["status"],
            "lifecycle_status": lifecycle,
            "installed": installed,
            "installed_version": installed_version,
            "active_source_id": active_source_id,
            "latest_source_id": source.id if source else None,
            "metadata": {
                **(item.get("metadata") or {}),
                **({
                    "source_id": str(source.id),
                    "review_status": source.review_status,
                } if source else {}),
            },
        })
        rows.append(item)

    for source in unlinked_sources:
        item = _source_item(source)
        lifecycle, installed, installed_version, active_source_id = _source_lifecycle(
            source,
            active_sources=active_sources,
            candidate_source_ids=candidate_source_ids,
        )
        item.update({
            "lifecycle_status": lifecycle,
            "installed": installed,
            "installed_version": installed_version,
            "active_source_id": active_source_id,
        })
        rows.append(item)
    return rows


def _filter_catalog_rows(
    rows: list[dict],
    *,
    query: str | None,
    source_filter: str | None,
    layer: str | None,
) -> list[dict]:
    normalized_query = (query or "").strip().lower()
    return [
        row for row in rows
        if (not source_filter or row["source"] == source_filter)
        and (not layer or row["layer"] == layer)
        and (
            not normalized_query
            or normalized_query in " ".join(
                [row["name"], row["slug"], row.get("description") or "", row.get("package_name") or ""]
            ).lower()
        )
    ]


async def catalog_sync_summary(db: AsyncSession) -> dict:
    event = (await db.execute(
        select(PlatformExtensionReleaseEvent)
        .where(PlatformExtensionReleaseEvent.event_type == "catalog_synced")
        .order_by(PlatformExtensionReleaseEvent.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if event is None:
        return {"status": "never", "stale": True}
    return {**(event.details or {}), "status": event.status, "event_at": event.created_at.isoformat()}


async def catalog_page(
    db: AsyncSession,
    admin_id: int,
    *,
    query: str | None = None,
    source_filter: str | None = None,
    layer: str | None = None,
    state: str = "all",
    page: int = 1,
    page_size: int = 48,
) -> dict:
    filtered = _filter_catalog_rows(
        await _catalog_rows(db, admin_id),
        query=query,
        source_filter=source_filter,
        layer=layer,
    )
    counts = {
        "compatible": sum(row["compatibility_status"] == "compatible" for row in filtered),
        "adapter": sum(row["compatibility_status"] == "needs_adapter" for row in filtered),
        "all": len(filtered),
        "installed": sum(bool(row["installed"]) for row in filtered),
    }
    if state == "compatible":
        filtered = [row for row in filtered if row["compatibility_status"] == "compatible"]
    elif state == "adapter":
        filtered = [row for row in filtered if row["compatibility_status"] == "needs_adapter"]
    elif state == "installed":
        filtered = [row for row in filtered if row["installed"]]
    filtered.sort(key=lambda row: (not row["installed"], str(row["name"]).lower(), str(row["slug"])))
    page_size = max(1, min(page_size, 48))
    page = max(1, page)
    start = (page - 1) * page_size
    return {
        "items": filtered[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": len(filtered),
        "counts": counts,
        "sync": await catalog_sync_summary(db),
    }


async def list_catalog(
    db: AsyncSession,
    admin_id: int,
    *,
    query: str | None = None,
    source_filter: str | None = None,
    layer: str | None = None,
    compatibility: str | None = None,
    offset: int = 0,
    limit: int = 3000,
) -> list[dict]:
    rows = _filter_catalog_rows(
        await _catalog_rows(db, admin_id),
        query=query,
        source_filter=source_filter,
        layer=layer,
    )
    if compatibility:
        rows = [row for row in rows if row["compatibility_status"] == compatibility]
    return rows[max(0, offset):max(0, offset) + max(1, min(limit, 3000))]


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
            catalog_entry_id = (source.build_report or {}).get("catalog_entry_id")
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
            source.build_report = {
                **(result.get("report") or {}),
                **({"catalog_entry_id": catalog_entry_id} if catalog_entry_id else {}),
            }
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
    # A draft is a deep copy of the active snapshot, but ``dsh_version`` (and the core plugin
    # versions mirroring it) always come from the platform constant, never from the copy.
    manifest = rewrite_manifest_dsh_version(active.manifest)
    active_extensions_by_source = {
        str(item.get("source_id")): item
        for item in (active.manifest or {}).get("external_extensions") or []
        if item.get("source_id")
    }
    active_extensions_by_slug = {
        str(item.get("slug")): item
        for item in (active.manifest or {}).get("external_extensions") or []
        if item.get("slug")
    }
    # A candidate is a complete immutable snapshot. Rebuild external entries
    # from the explicit selection so removing a source really uninstalls it.
    manifest["external_extensions"] = []
    disabled = set(config.get("disabled_plugins") or [])
    disabled_tool_groups = set(config.get("disabled_tool_groups") or [])
    extension_configs = config.get("extension_configs") or {}
    extension_disabled_organizations = config.get("extension_disabled_organization_ids") or {}
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
            if kind == "runtime_plugin" and not (
                (source.manifest or {}).get("platform_adapted") is True
                and (source.build_report or {}).get("codex_adaptation")
            ):
                raise HTTPException(
                    status_code=409,
                    detail=f"Runtime source {source.id} requires a reviewed Codex platform adaptation",
                )
            active_extension = active_extensions_by_source.get(str(source.id)) or active_extensions_by_slug.get(
                str((source.manifest or {}).get("slug") or "")
            ) or {}
            source_config = extension_configs.get(str(source.id), extension_configs.get(str(
                (source.manifest or {}).get("slug") or ""
            ), active_extension.get("default_config", (source.manifest or {}).get("default_config") or {})))
            disabled_orgs = extension_disabled_organizations.get(
                str(source.id),
                extension_disabled_organizations.get(
                    str((source.manifest or {}).get("slug") or ""),
                    active_extension.get("disabled_organization_ids") or [],
                ),
            )
            manifest.setdefault("external_extensions", []).append(
                {
                    **source.manifest,
                    "source_id": str(source.id),
                    "artifact_ref": source.artifact_ref,
                    "artifact_sha256": source.artifact_sha256,
                    "enabled": True,
                    "capabilities": (source.manifest or {}).get("provides") or [],
                    "default_config": source_config,
                    "disabled_organization_ids": [str(value) for value in disabled_orgs],
                }
            )
    enabled_extensions = [item for item in manifest.get("external_extensions", []) if item.get("enabled", True)]
    replacement_slots: dict[str, str] = {}
    replaceable_layers = {"coordinator", "memory_context", "rag_strategy", "model_adapter"}
    for item in enabled_extensions:
        default_layer = "coordinator" if "coordinator" in (item.get("provides") or []) else "runtime"
        layer = str(item.get("layer") or default_layer)
        operation = str(item.get("operation") or ("replace" if layer == "coordinator" else "add"))
        if operation != "replace":
            continue
        if layer not in replaceable_layers:
            raise HTTPException(status_code=409, detail=f"Layer {layer} does not support replacement")
        if layer in replacement_slots:
            raise HTTPException(
                status_code=409,
                detail=f"A release cannot replace slot {layer} more than once",
            )
        replacement_slots[layer] = str(item.get("slug"))
    manifest["replacement_slots"] = replacement_slots
    if "coordinator" in replacement_slots:
        for plugin in manifest.get("plugins", []):
            if "coordinator" in (plugin.get("capabilities") or []):
                plugin["enabled"] = False
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
        await db.refresh(release)
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
        await db.refresh(release)
    return release


async def rollback_release(
    db: AsyncSession,
    target: PlatformExtensionRelease,
    *,
    admin_id: int,
) -> PlatformExtensionRelease:
    active = await ensure_baseline(db, admin_id)
    next_version = await _next_release_version(db)
    # History rows predating a DSH upgrade still name the old version; the rollback candidate
    # must name the version the runtime actually runs or validation fails before it starts.
    manifest = rewrite_manifest_dsh_version(target.manifest)
    target_dsh_version = manifest_dsh_version(target.manifest)
    copy = PlatformExtensionRelease(
        version_no=next_version,
        name=f"回滚至 v{target.version_no}",
        manifest=manifest,
        checksum=manifest_checksum(manifest),
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
        details={
            "target_release_id": str(target.id),
            **(
                {"dsh_version_rewritten": {"from": target_dsh_version, "to": DSH_VERSION}}
                if target_dsh_version != DSH_VERSION
                else {}
            ),
        },
    )
    return copy


def validate_extension_config(schema: dict, value: dict) -> list[str]:
    """Validate the useful, deterministic subset of JSON Schema used by tool settings.

    Full JSON Schema execution is intentionally not delegated to plugin code. The
    builder owns code checks; this validator protects the settings UI/API contract.
    """
    errors: list[str] = []
    if not schema:
        return errors
    if schema.get("type", "object") != "object":
        return ["config_schema root must be an object"]
    properties = schema.get("properties") or {}
    for name in schema.get("required") or []:
        if name not in value or value[name] is None or value[name] == "":
            errors.append(f"{name} is required")
    expected_types = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    for name, item in value.items():
        declaration = properties.get(name)
        if not declaration:
            if schema.get("additionalProperties") is False:
                errors.append(f"{name} is not allowed")
            continue
        declared_type = declaration.get("type")
        expected = expected_types.get(declared_type)
        type_matches = isinstance(item, expected) if expected else True
        # bool subclasses int in Python, but JSON Schema keeps them distinct.
        if declared_type in {"integer", "number"} and isinstance(item, bool):
            type_matches = False
        if not type_matches:
            errors.append(f"{name} must be {declaration.get('type')}")
    return errors


def _active_source_ids(active: PlatformExtensionRelease, *, excluding_slug: str | None = None) -> list[UUID]:
    values: list[UUID] = []
    for item in (active.manifest or {}).get("external_extensions") or []:
        if item.get("enabled", True) is False or item.get("slug") == excluding_slug:
            continue
        try:
            values.append(UUID(str(item["source_id"])))
        except (KeyError, TypeError, ValueError):
            continue
    return values


async def prepare_system_tool_release(
    db: AsyncSession,
    source: PlatformExtensionSource,
    *,
    admin_id: int,
    config: dict,
    disabled_organization_ids: list[UUID],
    publish: bool,
) -> PlatformExtensionRelease:
    """Validate or install one reviewed system tool as a complete snapshot.

    The previous active release remains untouched until candidate validation and
    Runtime activation both succeed.
    """
    manifest = source.manifest or {}
    if manifest.get("type") != "system_tool":
        raise HTTPException(status_code=409, detail="Only system_tool extensions support one-click installation")
    if source.status not in {"review_required", "ready"}:
        raise HTTPException(status_code=409, detail="The system tool must pass isolated build first")
    config_errors = validate_extension_config(manifest.get("config_schema") or {}, config)
    if config_errors:
        raise HTTPException(status_code=422, detail={"message": "Invalid system tool config", "errors": config_errors})
    # Super-admin one-click installation is the review decision for system tools.
    if source.review_status != "approved":
        await approve_source(db, source, admin_id=admin_id, approved=True, note="system tool one-click review")
    active = await ensure_baseline(db, admin_id)
    active_config = (active.manifest or {}).get("release_config") or {}
    existing_configs = active_config.get("extension_configs") or {}
    existing_disabled = active_config.get("extension_disabled_organization_ids") or {}
    slug = str(manifest.get("slug") or "")
    source_ids = [*_active_source_ids(active, excluding_slug=slug), source.id]
    release = await create_release(
        db,
        name=f"{'安装' if publish else '连接测试'}系统工具：{manifest.get('name') or slug}",
        source_ids=source_ids,
        config={
            **active_config,
            "extension_configs": {**existing_configs, str(source.id): config},
            "extension_disabled_organization_ids": {
                **existing_disabled,
                str(source.id): [str(value) for value in disabled_organization_ids],
            },
            "lifecycle_action": "install" if publish else "connection_test",
        },
        admin_id=admin_id,
    )
    release = await validate_release(db, release, admin_id)
    if release.status != "ready":
        await db.flush()
        return release
    if publish:
        release = await publish_release(db, release, admin_id)
    return release


async def disable_system_tool(
    db: AsyncSession,
    source: PlatformExtensionSource,
    *,
    admin_id: int,
) -> PlatformExtensionRelease:
    manifest = source.manifest or {}
    if manifest.get("type") != "system_tool":
        raise HTTPException(status_code=409, detail="Only system tools can be disabled here")
    active = await ensure_baseline(db, admin_id)
    slug = str(manifest.get("slug") or "")
    if not any(item.get("slug") == slug for item in (active.manifest or {}).get("external_extensions") or []):
        raise HTTPException(status_code=409, detail="System tool is not active")
    release = await create_release(
        db,
        name=f"停用系统工具：{manifest.get('name') or slug}",
        source_ids=_active_source_ids(active, excluding_slug=slug),
        config={**((active.manifest or {}).get("release_config") or {}), "lifecycle_action": "disable"},
        admin_id=admin_id,
    )
    release = await validate_release(db, release, admin_id)
    if release.status == "ready":
        release = await publish_release(db, release, admin_id)
    return release


async def rollback_system_tool(
    db: AsyncSession,
    source: PlatformExtensionSource,
    *,
    admin_id: int,
) -> PlatformExtensionRelease:
    slug = str((source.manifest or {}).get("slug") or "")
    releases = list((await db.execute(
        select(PlatformExtensionRelease).order_by(PlatformExtensionRelease.version_no.desc())
    )).scalars().all())
    target = next((row for row in releases if row.status == "superseded" and any(
        item.get("slug") == slug and item.get("enabled", True)
        for item in (row.manifest or {}).get("external_extensions") or []
    )), None)
    if target is None:
        raise HTTPException(status_code=404, detail="No previous immutable version exists for this system tool")
    release = await rollback_release(db, target, admin_id=admin_id)
    release = await validate_release(db, release, admin_id)
    if release.status == "ready":
        release = await publish_release(db, release, admin_id)
    return release


async def sync_active_release_to_runtime() -> None:
    """Re-activate the DB fact-source after a backend or DSH container (re)start.

    Runs from the FastAPI lifespan.  First the active release is healed to ``DSH_VERSION``
    (see ``heal_active_release_version``) so an upgraded runtime accepts it; then the manifest
    is pushed unless the runtime already reports this release id and checksum.  Every
    outcome is logged: after a DSH upgrade the deploy checklist looks for
    ``platform_extension_release_version_healed`` / ``platform_extension_runtime_activated``.
    """
    async with async_session_factory() as db:
        active = await _active_release(db)
        if not active:
            logger.info("platform_extension_runtime_sync_skipped", reason="no active release yet")
            return
        healed = None
        try:
            active, healed = await heal_active_release_version(db, active, actor_admin_id=None)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - keep the runtime sync going with the stored row
            await db.rollback()
            logger.warning("platform_extension_release_heal_failed", release_id=str(active.id), error=str(exc))
            active = await _active_release(db)
            if active is None:
                return
        release_id = str(active.id)
        checksum = active.checksum
        manifest = active.manifest
        dsh_version = manifest_dsh_version(manifest)
        version_no = active.version_no
    health = await dsh_client.runtime_health()
    if health.get("release_id") == release_id and health.get("release_checksum") == checksum:
        logger.info("platform_extension_runtime_in_sync", release_id=release_id, dsh_version=dsh_version)
        return
    try:
        result = await dsh_client.activate_release(release_id, await runtime_manifest(manifest), checksum)
    except Exception as exc:  # noqa: BLE001 - startup must not crash; the failure is logged for operators
        response = getattr(exc, "response", None)
        logger.warning(
            "platform_extension_runtime_activation_failed",
            release_id=release_id,
            version_no=version_no,
            dsh_version=dsh_version,
            runtime_dsh_version=health.get("dsh_version"),
            error=str(exc),
            runtime_response=(getattr(response, "text", None) or "")[:500],
        )
        return
    if not result.get("ok"):
        logger.warning(
            "platform_extension_runtime_activation_rejected",
            release_id=release_id,
            dsh_version=dsh_version,
            result=result,
        )
        return
    logger.info(
        "platform_extension_runtime_activated",
        release_id=release_id,
        version_no=version_no,
        dsh_version=dsh_version,
        healed=healed is not None,
    )


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
