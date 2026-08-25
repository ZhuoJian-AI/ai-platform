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
    PlatformExtensionCatalogEntry,
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
        "runtime_requirements": {"node": "22.19.0", "dsh": "0.1.0-rc.5"},
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
