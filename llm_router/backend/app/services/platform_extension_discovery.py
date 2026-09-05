"""Read-only discovery catalog for official and community DSH extensions."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory
from app.models.platform_extension import PlatformExtensionCatalogEntry
from app.services.platform_extension_catalog import catalog_items

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SLUG = re.compile(r"[^a-z0-9._-]+")
_SYNC_LOCK_KEY = "platform-extensions:catalog-sync-lock"

_CATEGORY_LAYER = {
    "model": "model_adapter",
    "session": "runtime",
    "memory": "memory_context",
    "tools": "system_tool",
    "browser": "system_tool",
    "vision": "system_tool",
    "voice": "system_tool",
    "docs": "system_tool",
    "git": "system_tool",
    "workflow": "runtime",
    "security": "hook_guard",
    "usage": "runtime",
    "notify": "runtime",
    "remote": "runtime",
    "identity": "runtime",
    "dev": "library",
    "skill": "skill_mcp",
    "ui": "ui_plugin",
    "theme": "ui_plugin",
    "market": "ui_plugin",
    "fun": "ui_plugin",
}


def _text(value: object, limit: int) -> str:
    return _CONTROL.sub("", str(value or "")).strip()[:limit]


def _url(value: object) -> str | None:
    raw = _text(value, 2000)
    if not raw:
        return None
    parsed = urlparse(raw)
    return raw if parsed.scheme == "https" and parsed.netloc else None


def _slug(value: object) -> str:
    clean = _SLUG.sub("-", _text(value, 255).lower()).strip("-.")
    return clean[:255] or "unnamed-extension"


def _integer(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def classify_community(item: dict) -> dict:
    category = _text(item.get("category"), 100).lower() or "unknown"
    haystack = " ".join(
        [
            _text(item.get("name"), 255),
            _text((item.get("description") or {}).get("en") if isinstance(item.get("description"), dict) else "", 2000),
            _text((item.get("description") or {}).get("zh") if isinstance(item.get("description"), dict) else "", 2000),
        ]
    ).lower()
    layer = _CATEGORY_LAYER.get(category, "unknown")
    operation = "add"
    if category == "workflow" and re.search(r"agent[-_ ]?loop|coordinator|orchestrat|omni[-_ ]?router", haystack):
        layer = "coordinator"
        operation = "replace"
    elif re.search(r"\brag\b|retriev|rerank|vector|weknora", haystack):
        layer = "rag_strategy"
        operation = "replace"
    elif layer == "memory_context":
        operation = "replace"

    if layer == "ui_plugin":
        return {
            "layer": layer,
            "operation": "add",
            "kind": "incompatible",
            "compatibility_status": "incompatible",
            "compatibility_reasons": ["该插件面向DSH本地Web/UI，不能直接装入云端SaaS Runtime"],
        }
    if layer == "skill_mcp":
        reasons = ["该条目属于Skill/MCP生态，不能冒充平台Runtime插件"]
    elif layer == "library":
        reasons = ["普通运行库不能作为独立平台插件发布"]
    else:
        reasons = ["社区目录只提供发现信息，发布前必须补充AI Platform扩展清单并通过隔离构建"]
    return {
        "layer": layer,
        "operation": operation,
        "kind": "adapter_required",
        "compatibility_status": "needs_adapter",
        "compatibility_reasons": reasons,
    }


def _official_rows() -> list[dict]:
    rows = []
    for item in catalog_items():
        layer = {
            "dsh-agent-loop": "coordinator",
            "dsh-llm-runtime": "model_adapter",
            "dsh-session": "runtime",
            "dsh-system-prompt": "runtime",
            "dsh-tools": "runtime",
            "dsh-agent": "runtime",
        }.get(item["slug"], "system_tool" if item["kind"] == "system_tool" else "runtime")
        status = "compatible" if item["kind"] not in {"adapter_required", "incompatible"} else "needs_adapter"
        rows.append(
            {
                "provider": "official",
                "external_key": item["slug"],
                "slug": item["slug"],
                "name": item["name"],
                "description": item["description"],
                "package_name": f"@deepseek-ai/{item['slug']}" if item["slug"].startswith("dsh-") else None,
                "version": item["version"] if item["version"] != "platform" else None,
                "available_versions": [item["version"]] if item["version"] != "platform" else [],
                "repository": "https://github.com/deepseek-ai/deepseek-harness",
                "homepage": "https://deepseek.com/harness/",
                "category": "official",
                "layer": layer,
                "operation": "replace" if layer == "coordinator" else "add",
                "kind": item["kind"],
                "trust_level": "official",
                "runtime_requirements": {"node": "22.19.0", "dsh": "0.1.0-rc.8"},
                "compatibility_status": status,
                "compatibility_reasons": item.get("compatibility_warnings") or [],
                "metadata_payload": {"capabilities": item.get("capabilities") or []},
            }
        )
    return rows


def _community_rows_with_stats(payload: dict) -> tuple[list[dict], dict[str, int]]:
    rows = []
    raw_plugins = payload.get("plugins") or []
    skipped = 0
    for raw in raw_plugins:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        name = _text(raw.get("name"), 255)
        repository = _url(raw.get("url"))
        package_name = _text(raw.get("npm"), 255) or None
        if not name or not (repository or package_name):
            skipped += 1
            continue
        description = raw.get("description") or {}
        description_text = (
            _text(description.get("zh"), 5000) or _text(description.get("en"), 5000)
            if isinstance(description, dict)
            else _text(description, 5000)
        )
        classification = classify_community(raw)
        external_key = package_name or repository or name
        rows.append(
            {
                "provider": "community",
                "external_key": _text(external_key, 512),
                "slug": _slug(package_name or name),
                "name": name,
                "description": description_text,
                "package_name": package_name,
                "version": None,
                "available_versions": [],
                "repository": repository,
                "homepage": _url(raw.get("page")),
                "category": _text(raw.get("category"), 100) or "unknown",
                "trust_level": "community",
                "runtime_requirements": {"node": "unknown", "dsh": "unknown"},
                "metadata_payload": {
                    "owner": _text(raw.get("owner"), 255),
                    "stars": _integer(raw.get("stars")),
                    "downloads": _integer(raw.get("downloads")),
                    "install": _text(raw.get("install"), 1000),
                    "added": _text(raw.get("added"), 40),
                    "catalog_updated": _text(payload.get("updated"), 40),
                },
                **classification,
            }
        )
    # Community lists can contain the same npm package in more than one category.
    # Keep one deterministic row so the database uniqueness constraint is never the deduper.
    deduplicated = list({row["external_key"]: row for row in rows}.values())
    return deduplicated, {
        "upstream_count": len(raw_plugins),
        "usable_count": len(deduplicated),
        "skipped_count": skipped,
        "deduplicated_count": len(rows) - len(deduplicated),
    }


def _community_rows(payload: dict) -> list[dict]:
    return _community_rows_with_stats(payload)[0]


async def _acquire_sync_lock() -> tuple[Redis | None, str | None, bool, str | None]:
    """Acquire the cross-process catalog lock; fail open only when Redis is unavailable."""

    token = uuid4().hex
    client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        acquired = bool(await client.set(
            _SYNC_LOCK_KEY,
            token,
            nx=True,
            ex=max(120, settings.extension_catalog_sync_timeout_seconds + 60),
        ))
        return client, token, acquired, None
    except Exception as exc:  # noqa: BLE001 - metadata sync must keep the last database snapshot
        await client.aclose()
        return None, None, True, _text(exc, 500)


async def _release_sync_lock(client: Redis | None, token: str | None) -> None:
    if client is None or token is None:
        return
    try:
        await client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            _SYNC_LOCK_KEY,
            token,
        )
    finally:
        await client.aclose()


async def _upsert_rows(db: AsyncSession, provider: str, rows: list[dict], synced_at: datetime) -> int:
    existing = list(
        (await db.execute(select(PlatformExtensionCatalogEntry).where(
            PlatformExtensionCatalogEntry.provider == provider
        ))).scalars().all()
    )
    by_key = {row.external_key: row for row in existing}
    seen: set[str] = set()
    for values in rows:
        key = values["external_key"]
        seen.add(key)
        record = by_key.get(key)
        if record is None:
            record = PlatformExtensionCatalogEntry(
                **values, last_synced_at=synced_at, is_active=True,
            )
            db.add(record)
        else:
            for field, value in values.items():
                setattr(record, field, value)
            record.last_synced_at = synced_at
            record.is_active = True
    for record in existing:
        if record.external_key not in seen:
            record.is_active = False
    await db.flush()
    return len(rows)


async def sync_discovery_catalog(db: AsyncSession) -> dict:
    """Refresh discovery metadata. A remote failure retains the last successful snapshot."""

    lock_client, lock_token, acquired, lock_warning = await _acquire_sync_lock()
    if not acquired:
        return {
            "status": "busy",
            "official": 0,
            "community": 0,
            "synced_at": datetime.now(UTC).isoformat(),
            "stale": False,
            "message": "另一个目录同步任务正在运行",
        }
    synced_at = datetime.now(UTC)
    try:
        official_count = await _upsert_rows(db, "official", _official_rows(), synced_at)
        try:
            async with httpx.AsyncClient(
                timeout=settings.extension_catalog_sync_timeout_seconds,
                follow_redirects=True,
            ) as client:
                response = await client.get(settings.extension_catalog_community_url)
                response.raise_for_status()
                if len(response.content) > 10 * 1024 * 1024:
                    raise ValueError("Community catalog exceeds the 10MB metadata limit")
                payload = response.json()
            community_rows, stats = _community_rows_with_stats(payload if isinstance(payload, dict) else {})
            if not community_rows:
                raise ValueError("Community catalog returned no usable plugin records")
            community_count = await _upsert_rows(db, "community", community_rows, synced_at)
            return {
                "status": "ok", "official": official_count, "community": community_count,
                "synced_at": synced_at.isoformat(), "stale": False,
                "lock_warning": lock_warning,
                **stats,
            }
        except Exception as exc:  # noqa: BLE001 - stale snapshot is an intentional fallback
            retained = len((await db.execute(select(PlatformExtensionCatalogEntry).where(
                PlatformExtensionCatalogEntry.provider == "community",
                PlatformExtensionCatalogEntry.is_active.is_(True),
            ))).scalars().all())
            return {
                "status": "stale" if retained else "failed",
                "official": official_count,
                "community": retained,
                "synced_at": synced_at.isoformat(),
                "stale": True,
                "error": _text(exc, 1000),
                "lock_warning": lock_warning,
                "upstream_count": 0,
                "usable_count": retained,
                "skipped_count": 0,
                "deduplicated_count": 0,
            }
    finally:
        await _release_sync_lock(lock_client, lock_token)


async def run_catalog_sync_scheduler() -> None:
    """Refresh the metadata catalog daily while retaining the last successful snapshot."""

    from app.services.platform_extension_service import record_event

    while True:
        try:
            async with async_session_factory() as db:
                last_synced = (
                    await db.execute(select(func.max(PlatformExtensionCatalogEntry.last_synced_at)).where(
                        PlatformExtensionCatalogEntry.provider == "community",
                        PlatformExtensionCatalogEntry.is_active.is_(True),
                    ))
                ).scalar_one_or_none()
                due = last_synced is None or last_synced <= datetime.now(UTC) - timedelta(
                    seconds=max(60, settings.extension_catalog_sync_interval_seconds)
                )
                if due:
                    result = await sync_discovery_catalog(db)
                    await record_event(
                        db,
                        event_type="catalog_synced",
                        actor_admin_id=None,
                        status="ok" if result["status"] == "ok" else result["status"],
                        details={**result, "trigger": "scheduled"},
                    )
                    await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Discovery metadata must never prevent the main API from serving the last snapshot.
            pass
        await asyncio.sleep(max(60, settings.extension_catalog_sync_poll_seconds))
