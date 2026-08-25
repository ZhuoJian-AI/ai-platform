"""Read-only discovery catalog for official and community DSH extensions."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.platform_extension import PlatformExtensionCatalogEntry
from app.services.platform_extension_catalog import catalog_items

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SLUG = re.compile(r"[^a-z0-9._-]+")

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
                "runtime_requirements": {"node": "22.19.0", "dsh": "0.1.0-rc.5"},
                "compatibility_status": status,
                "compatibility_reasons": item.get("compatibility_warnings") or [],
                "metadata_payload": {"capabilities": item.get("capabilities") or []},
            }
        )
    return rows


def _community_rows(payload: dict) -> list[dict]:
    rows = []
    for raw in payload.get("plugins") or []:
        if not isinstance(raw, dict):
            continue
        name = _text(raw.get("name"), 255)
        repository = _url(raw.get("url"))
        package_name = _text(raw.get("npm"), 255) or None
        if not name or not (repository or package_name):
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
    return list({row["external_key"]: row for row in rows}.values())


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

    synced_at = datetime.now(UTC)
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
        community_rows = _community_rows(payload if isinstance(payload, dict) else {})
        if not community_rows:
            raise ValueError("Community catalog returned no usable plugin records")
        community_count = await _upsert_rows(db, "community", community_rows, synced_at)
        return {
            "status": "ok", "official": official_count, "community": community_count,
            "synced_at": synced_at.isoformat(), "stale": False,
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
        }
