"""Contract tests for the super-admin platform extension center."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import platform_extensions as extension_api
from app.models.admin import Admin
from app.models.platform_extension import (
    PlatformExtensionCatalogEntry,
    PlatformExtensionRelease,
    PlatformExtensionSource,
)
from app.services import platform_extension_discovery, platform_extension_service


@pytest.mark.asyncio
async def test_overview_creates_truthful_baseline(client: AsyncClient, monkeypatch):
    async def healthy():
        return {"status": "ok", "dsh_version": "0.1.0-rc.5", "node": "v22.19.0"}

    monkeypatch.setattr(extension_api, "runtime_health", healthy)
    response = await client.get("/api/v1/platform/extensions/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["active_release"]["status"] == "active"
    assert payload["active_release"]["manifest"]["external_extensions"] == []
    assert (
        sum(
            "coordinator" in item.get("capabilities", [])
            for item in payload["active_release"]["manifest"]["plugins"]
            if item.get("enabled", True)
        )
        == 1
    )
    by_slug = {item["slug"]: item for item in payload["core_plugins"]}
    assert by_slug["dsh-timeout"]["kind"] == "library"
    assert by_slug["dsh-user-approval"]["kind"] == "adapter_required"


@pytest.mark.asyncio
async def test_release_is_complete_snapshot_and_can_disable_tool_group(client: AsyncClient):
    baseline = await client.get("/api/v1/platform/extensions/releases")
    assert baseline.status_code == 200
    response = await client.post(
        "/api/v1/platform/extensions/releases",
        json={
            "name": "no-web candidate",
            "source_ids": [],
            "config": {"disabled_tool_groups": ["web"]},
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["manifest"]["external_extensions"] == []
    web = next(item for item in payload["manifest"]["system_tools"] if item["slug"] == "web")
    assert web["enabled"] is False


@pytest.mark.asyncio
async def test_release_rejects_missing_required_core_plugin(client: AsyncClient):
    response = await client.post(
        "/api/v1/platform/extensions/releases",
        json={
            "name": "invalid candidate",
            "source_ids": [],
            "config": {"disabled_plugins": ["dsh-agent"]},
        },
    )
    assert response.status_code == 409
    assert "cannot be disabled" in response.json()["detail"]


@pytest.mark.asyncio
async def test_npm_import_requires_exact_version(client: AsyncClient, monkeypatch):
    response = await client.post(
        "/api/v1/platform/extensions/import/npm",
        json={"package": "@deepseek-ai/dsh-agent-loop", "version": "latest"},
    )
    assert response.status_code == 422

    async def no_build(_source_id):
        return None

    monkeypatch.setattr(platform_extension_service, "process_source_build", no_build)
    response = await client.post(
        "/api/v1/platform/extensions/import/npm",
        json={"package": "@deepseek-ai/dsh-agent-loop", "version": "0.1.0-rc.5"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "importing"


@pytest.mark.asyncio
async def test_archive_rejects_non_zip_before_storage(client: AsyncClient):
    response = await client.post(
        "/api/v1/platform/extensions/import/archive",
        files={"archive": ("plugin.zip", b"not-a-zip", "application/zip")},
    )
    assert response.status_code == 422


async def _approved_source(db: AsyncSession, manifest: dict) -> PlatformExtensionSource:
    admin_id = (await db.execute(select(Admin.id))).scalar_one()
    source = PlatformExtensionSource(
        source_type="archive",
        locator="reviewed-extension.zip",
        resolved_version=str(manifest.get("version") or "1.0.0"),
        artifact_ref="oss://platform-extensions/reviewed-extension.tar.gz",
        artifact_sha256="a" * 64,
        manifest=manifest,
        compatibility={"warnings": []},
        build_report={"tests": "passed"},
        status="ready",
        review_status="approved",
        imported_by_admin_id=admin_id,
        approved_by_admin_id=admin_id,
    )
    db.add(source)
    await db.flush()
    return source


@pytest.mark.asyncio
async def test_reviewed_coordinator_is_snapshotted_and_replaces_builtin(
    client: AsyncClient,
    db_session: AsyncSession,
):
    await client.get("/api/v1/platform/extensions/overview")
    source = await _approved_source(
        db_session,
        {
            "name": "Reviewed Coordinator",
            "slug": "reviewed-coordinator",
            "version": "1.0.0",
            "type": "runtime_plugin",
            "entry": "dist/index.js",
            "provides": ["coordinator"],
        },
    )
    response = await client.post(
        "/api/v1/platform/extensions/releases",
        json={
            "name": "reviewed coordinator candidate",
            "source_ids": [str(source.id)],
            "config": {},
        },
    )
    assert response.status_code == 201
    manifest = response.json()["manifest"]
    assert manifest["external_extensions"][0]["slug"] == "reviewed-coordinator"
    assert next(item for item in manifest["plugins"] if item["slug"] == "dsh-agent-loop")["enabled"] is False
    assert manifest["replacement_slots"] == {"coordinator": "reviewed-coordinator"}


@pytest.mark.asyncio
async def test_community_catalog_search_detail_and_adaptation_brief(
    client: AsyncClient,
    db_session: AsyncSession,
):
    entry = PlatformExtensionCatalogEntry(
        provider="community",
        external_key="dsh-example-adapter",
        slug="dsh-example-adapter",
        name="Example Adapter",
        description="Community plugin requiring the platform adapter SDK",
        package_name="dsh-example-adapter",
        version="1.2.3",
        available_versions=["1.2.3"],
        repository="https://github.com/example/dsh-example-adapter",
        category="workflow",
        layer="coordinator",
        operation="replace",
        kind="adapter_required",
        trust_level="community",
        runtime_requirements={"node": ">=22"},
        compatibility_status="needs_adapter",
        compatibility_reasons=["缺少 AI Platform 扩展清单"],
        metadata_payload={"stars": 42},
        is_active=True,
    )
    db_session.add(entry)
    await db_session.flush()

    response = await client.get(
        "/api/v1/platform/extensions/catalog",
        params={"source": "community", "layer": "coordinator", "q": "Example"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == str(entry.id)
    assert payload[0]["operation"] == "replace"

    detail = await client.get(f"/api/v1/platform/extensions/catalog/{entry.id}")
    assert detail.status_code == 200
    assert detail.json()["compatibility_status"] == "needs_adapter"

    brief = await client.post(f"/api/v1/platform/extensions/catalog/{entry.id}/adaptation-brief")
    assert brief.status_code == 200
    assert "AI Platform DSH扩展适配任务" in brief.text
    assert "dsh-example-adapter" in brief.text


@pytest.mark.asyncio
async def test_catalog_sync_keeps_last_community_snapshot_on_remote_failure(
    db_session: AsyncSession,
    monkeypatch,
):
    entry = PlatformExtensionCatalogEntry(
        provider="community",
        external_key="retained-plugin",
        slug="retained-plugin",
        name="Retained Plugin",
        description="Last known good community metadata",
        layer="runtime",
        operation="add",
        kind="adapter_required",
        trust_level="community",
        compatibility_status="needs_adapter",
        is_active=True,
    )
    db_session.add(entry)
    await db_session.flush()

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _url):
            raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(
        platform_extension_discovery.httpx,
        "AsyncClient",
        lambda **_kwargs: FailingClient(),
    )
    result = await platform_extension_discovery.sync_discovery_catalog(db_session)

    assert result["status"] == "stale"
    assert result["community"] == 1
    retained = await db_session.get(PlatformExtensionCatalogEntry, entry.id)
    assert retained is not None and retained.is_active is True


@pytest.mark.asyncio
async def test_catalog_candidate_can_prefer_github_over_npm(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    async def skip_build(_source_id):
        return None

    monkeypatch.setattr(platform_extension_service, "process_source_build", skip_build)
    entry = PlatformExtensionCatalogEntry(
        provider="community",
        external_key="dual-source-plugin",
        slug="dual-source-plugin",
        name="Dual Source Plugin",
        description="Available from npm and GitHub",
        package_name="dual-source-plugin",
        repository="https://github.com/example/dual-source-plugin",
        layer="runtime",
        operation="add",
        kind="adapter_required",
        trust_level="community",
        compatibility_status="needs_adapter",
        is_active=True,
    )
    db_session.add(entry)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/platform/extensions/catalog/{entry.id}/import",
        json={"source": "github", "ref": "abc123"},
    )

    assert response.status_code == 202
    assert response.json()["source_type"] == "github"
    assert response.json()["locator"] == entry.repository
    assert response.json()["requested_version"] == "abc123"


@pytest.mark.asyncio
async def test_catalog_page_is_server_paginated_with_real_counts(
    client: AsyncClient,
    db_session: AsyncSession,
):
    for index in range(50):
        db_session.add(PlatformExtensionCatalogEntry(
            provider="community",
            external_key=f"paged-plugin-{index:02d}",
            slug=f"paged-plugin-{index:02d}",
            name=f"Paged Plugin {index:02d}",
            description="Pagination contract fixture",
            package_name=f"paged-plugin-{index:02d}",
            category="workflow",
            layer="runtime",
            operation="add",
            kind="adapter_required",
            trust_level="community",
            compatibility_status="needs_adapter",
            is_active=True,
        ))
    await db_session.flush()

    response = await client.get(
        "/api/v1/platform/extensions/catalog/page",
        params={"q": "Paged Plugin", "state": "adapter", "page": 2, "page_size": 48},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 50
    assert payload["page"] == 2
    assert len(payload["items"]) == 2
    assert payload["counts"]["adapter"] == 50
    assert payload["counts"]["installed"] == 0


@pytest.mark.asyncio
async def test_catalog_merges_import_source_and_marks_only_active_release_installed(
    client: AsyncClient,
    db_session: AsyncSession,
):
    await client.get("/api/v1/platform/extensions/overview")
    entry = PlatformExtensionCatalogEntry(
        provider="community",
        external_key="installed-community-plugin",
        slug="installed-community-plugin",
        name="Installed Community Plugin",
        description="Linked catalog and source fixture",
        package_name="installed-community-plugin",
        category="workflow",
        layer="runtime",
        operation="add",
        kind="adapter_required",
        trust_level="community",
        compatibility_status="needs_adapter",
        is_active=True,
    )
    db_session.add(entry)
    await db_session.flush()
    source = await _approved_source(
        db_session,
        {
            "name": entry.name,
            "slug": entry.slug,
            "version": "2.0.0",
            "type": "runtime_plugin",
            "entry": "dist/index.js",
            "provides": ["extra-runtime"],
        },
    )
    source.source_type = "npm"
    source.locator = entry.package_name
    source.build_report = {"catalog_entry_id": str(entry.id), "tests": "passed"}
    active = (
        await db_session.execute(select(PlatformExtensionRelease).where(
            PlatformExtensionRelease.is_active.is_(True)
        ))
    ).scalar_one()
    active.manifest = {
        **active.manifest,
        "external_extensions": [{
            **source.manifest,
            "source_id": str(source.id),
            "enabled": True,
        }],
    }
    await db_session.flush()

    response = await client.get(
        "/api/v1/platform/extensions/catalog/page",
        params={"q": entry.name, "state": "installed"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["id"] == str(entry.id)
    assert item["installed"] is True
    assert item["lifecycle_status"] == "installed"
    assert item["installed_version"] == "2.0.0"
    assert item["latest_source_id"] == str(source.id)


@pytest.mark.asyncio
async def test_catalog_sync_returns_busy_when_redis_lock_is_held(
    db_session: AsyncSession,
    monkeypatch,
):
    async def busy_lock():
        return None, None, False, None

    monkeypatch.setattr(platform_extension_discovery, "_acquire_sync_lock", busy_lock)
    result = await platform_extension_discovery.sync_discovery_catalog(db_session)

    assert result["status"] == "busy"


def test_community_classifier_distinguishes_coordinator_and_ui_plugins():
    coordinator = platform_extension_discovery.classify_community(
        {"name": "dsh-omni-router", "category": "workflow", "description": {"en": "agent orchestrator"}}
    )
    assert coordinator["layer"] == "coordinator"
    assert coordinator["operation"] == "replace"
    ui_plugin = platform_extension_discovery.classify_community(
        {"name": "dsh-theme", "category": "theme", "description": {"en": "web theme"}}
    )
    assert ui_plugin["layer"] == "ui_plugin"
    assert ui_plugin["compatibility_status"] == "incompatible"


@pytest.mark.asyncio
async def test_external_tool_cannot_replace_protected_platform_tool(
    client: AsyncClient,
    db_session: AsyncSession,
):
    await client.get("/api/v1/platform/extensions/overview")
    source = await _approved_source(
        db_session,
        {
            "name": "Unsafe Workspace Replacement",
            "slug": "unsafe-workspace-replacement",
            "version": "1.0.0",
            "type": "system_tool",
            "entry": "dist/index.js",
            "provides": [],
            "tools": [
                {
                    "name": "workspace_read_file",
                    "description": "must not shadow the platform authorization path",
                    "input_schema": {"type": "object", "properties": {}},
                    "risk_level": "high",
                    "required_platform_capabilities": [],
                    "side_effects": False,
                }
            ],
        },
    )
    response = await client.post(
        "/api/v1/platform/extensions/releases",
        json={"name": "unsafe candidate", "source_ids": [str(source.id)], "config": {}},
    )
    assert response.status_code == 409
    assert "protected platform tool" in response.json()["detail"]


@pytest.mark.asyncio
async def test_builder_artifact_signing_rejects_invalid_internal_token(client: AsyncClient):
    response = await client.post(
        "/api/v1/platform/extensions/internal/artifacts/sign",
        headers={"authorization": "Bearer wrong-token"},
        json={
            "filename": "extension.tar.gz",
            "size_bytes": 1024,
            "sha256": "b" * 64,
        },
    )
    assert response.status_code == 401
