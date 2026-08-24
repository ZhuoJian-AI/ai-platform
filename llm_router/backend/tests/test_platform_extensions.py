"""Contract tests for the super-admin platform extension center."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import platform_extensions as extension_api
from app.models.admin import Admin
from app.models.platform_extension import PlatformExtensionSource
from app.services import platform_extension_service


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
            "config": {"disabled_plugins": ["dsh-agent-loop"]},
        },
    )
    assert response.status_code == 201
    manifest = response.json()["manifest"]
    assert manifest["external_extensions"][0]["slug"] == "reviewed-coordinator"
    assert next(item for item in manifest["plugins"] if item["slug"] == "dsh-agent-loop")["enabled"] is False


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
