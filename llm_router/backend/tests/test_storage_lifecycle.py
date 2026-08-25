"""Retention, OSS compensation and physical cleanup tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.admin import Admin
from app.models.ontology import Ontology, OntologyFile
from app.models.organization import Organization
from app.models.rag import RagChunk, RagCollection, RagDocument
from app.models.skill import SkillFile, SkillFolder, SkillVersion
from app.models.workspace import (
    Workspace,
    WorkspaceFile,
    WorkspaceFileVersion,
    WorkspaceFolder,
    WorkspaceShareLink,
    WorkspaceUploadSession,
)
from app.services import (
    storage_gateway_service,
    storage_lifecycle_service,
    workspace_governance_service,
)


async def _organization(db_session, slug: str = "lifecycle") -> Organization:
    organization = Organization(name=f"Lifecycle {slug}", slug=slug)
    db_session.add(organization)
    await db_session.flush()
    return organization


async def _workspace(db_session, organization: Organization, slug: str = "files") -> Workspace:
    workspace = Workspace(
        organization_id=organization.id,
        name=f"Workspace {slug}",
        slug=slug,
        storage_backend="s3",
        root_path="",
        scope_type="organization",
    )
    db_session.add(workspace)
    await db_session.flush()
    return workspace


@pytest.mark.asyncio
async def test_workspace_delete_and_restore_use_common_30_day_deadline(db_session):
    organization = await _organization(db_session)
    workspace = await _workspace(db_session, organization)
    file = WorkspaceFile(
        workspace_id=workspace.id,
        path="reports/a.xlsx",
        size=12,
        content_ref="oss://workspace/a.xlsx",
        metadata_={},
    )
    db_session.add(file)
    await db_session.flush()

    before = datetime.now(UTC)
    deadline = await storage_lifecycle_service.mark_workspace_deleted(db_session, workspace)
    assert workspace.deleted_at is not None
    assert file.deleted_at == workspace.deleted_at
    assert timedelta(days=29, hours=23) < deadline - before < timedelta(days=30, minutes=1)

    storage_lifecycle_service.restore(workspace, file)
    assert workspace.deleted_at is None and workspace.purge_after is None
    assert file.deleted_at is None and file.purge_after is None


@pytest.mark.asyncio
async def test_inline_skill_migration_clears_blob_only_after_verified_upload(
    db_session, monkeypatch,
):
    organization = await _organization(db_session, "skill-migration")
    folder = SkillFolder(
        organization_id=organization.id,
        scope_type="organization",
        name="Migration Skill",
        slug="migration-skill",
    )
    db_session.add(folder)
    await db_session.flush()
    raw = b"verified-skill-package"
    version = SkillVersion(
        skill_folder_id=folder.id,
        version_no=1,
        package_hash="a" * 64,
        manifest={},
        archive=raw,
        archive_size=len(raw),
        runtime="prompt",
        install_status="ready",
    )
    db_session.add(version)
    await db_session.flush()
    monkeypatch.setattr(settings, "workspace_object_storage_enabled", True)
    monkeypatch.setattr(settings, "storage_gateway_url", "http://gateway")
    monkeypatch.setattr(settings, "storage_project_token", "test-token")
    monkeypatch.setattr(
        storage_gateway_service,
        "upload_skill_archive",
        lambda *_args, **_kwargs: _async_value("oss://skill-packages/package.zip"),
    )
    monkeypatch.setattr(
        storage_gateway_service,
        "download_bytes",
        lambda *_args, **_kwargs: _async_value(raw),
    )

    result = await storage_lifecycle_service.migrate_inline_skill_packages(db_session)
    assert result == {"migrated": 1, "failed": 0}
    assert version.archive is None
    assert version.archive_ref == "oss://skill-packages/package.zip"
    assert version.storage_status == "stored"


@pytest.mark.asyncio
async def test_inline_skill_migration_keeps_blob_when_verification_fails(
    db_session, monkeypatch,
):
    organization = await _organization(db_session, "skill-migration-failed")
    folder = SkillFolder(
        organization_id=organization.id,
        scope_type="organization",
        name="Failed Skill",
        slug="failed-skill",
    )
    db_session.add(folder)
    await db_session.flush()
    raw = b"authoritative-inline-package"
    version = SkillVersion(
        skill_folder_id=folder.id,
        version_no=1,
        package_hash="b" * 64,
        manifest={},
        archive=raw,
        archive_size=len(raw),
        runtime="prompt",
        install_status="ready",
    )
    db_session.add(version)
    await db_session.flush()
    monkeypatch.setattr(settings, "workspace_object_storage_enabled", True)
    monkeypatch.setattr(settings, "storage_gateway_url", "http://gateway")
    monkeypatch.setattr(settings, "storage_project_token", "test-token")
    monkeypatch.setattr(
        storage_gateway_service,
        "upload_skill_archive",
        lambda *_args, **_kwargs: _async_value("oss://skill-packages/package.zip"),
    )
    monkeypatch.setattr(
        storage_gateway_service,
        "download_bytes",
        lambda *_args, **_kwargs: _async_value(b"corrupted"),
    )

    result = await storage_lifecycle_service.migrate_inline_skill_packages(db_session)
    assert result == {"migrated": 0, "failed": 1}
    assert bytes(version.archive or b"") == raw
    assert version.archive_ref is None
    assert version.storage_status == "failed"


@pytest.mark.asyncio
async def test_skill_purge_retries_oss_before_clearing_database(db_session, monkeypatch):
    organization = await _organization(db_session, "skill-purge")
    folder = SkillFolder(
        organization_id=organization.id,
        scope_type="organization",
        name="Purge Skill",
        slug="purge-skill",
    )
    db_session.add(folder)
    await db_session.flush()
    version = SkillVersion(
        skill_folder_id=folder.id,
        version_no=1,
        package_hash="c" * 64,
        manifest={},
        archive_ref="oss://skill-packages/purge.zip",
        archive_size=99,
        storage_status="purge_pending",
        purge_after=datetime.now(UTC) - timedelta(seconds=1),
        runtime="agent_skill",
        install_status="ready",
    )
    db_session.add(version)
    await db_session.flush()

    async def fail_delete(_ref):
        raise storage_gateway_service.StorageGatewayError("temporary outage")

    monkeypatch.setattr(storage_gateway_service, "delete_object", fail_delete)
    purged, failed = await storage_lifecycle_service._purge_skill_versions(
        db_session, datetime.now(UTC),
    )
    assert (purged, failed) == (0, 1)
    assert version.archive_ref == "oss://skill-packages/purge.zip"
    assert version.archive_purged_at is None

    monkeypatch.setattr(storage_gateway_service, "delete_object", lambda _ref: _async_value(None))
    purged, failed = await storage_lifecycle_service._purge_skill_versions(
        db_session, datetime.now(UTC),
    )
    assert (purged, failed) == (1, 0)
    assert version.archive_ref is None
    assert version.archive_purged_at is not None
    assert version.storage_status == "purged"


@pytest.mark.asyncio
async def test_workspace_purge_preserves_shared_objects_and_active_share_links(
    db_session, monkeypatch,
):
    organization = await _organization(db_session, "workspace-purge")
    workspace = await _workspace(db_session, organization, "workspace-purge")
    shared_ref = "oss://workspace/shared.bin"
    deleted = WorkspaceFile(
        workspace_id=workspace.id,
        path="deleted.bin",
        size=10,
        content_ref=shared_ref,
        metadata_={},
        deleted_at=datetime.now(UTC) - timedelta(days=31),
        purge_after=datetime.now(UTC) - timedelta(days=1),
    )
    survivor = WorkspaceFile(
        workspace_id=workspace.id,
        path="survivor.bin",
        size=10,
        content_ref=shared_ref,
        metadata_={},
    )
    db_session.add_all([deleted, survivor])
    await db_session.flush()
    version = WorkspaceFileVersion(
        workspace_file_id=deleted.id,
        version_no=1,
        size=10,
        content_ref=shared_ref,
        metadata_={},
    )
    db_session.add(version)
    await db_session.flush()
    deleted.current_version_id = version.id
    active_share = WorkspaceShareLink(
        workspace_file_id=deleted.id,
        version_id=version.id,
        token_hash="f" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(active_share)
    await db_session.flush()
    deleted_refs: list[str] = []
    monkeypatch.setattr(
        storage_gateway_service,
        "delete_object",
        lambda ref: _record_async(deleted_refs, ref),
    )

    assert await workspace_governance_service.purge_expired(db_session) == 0
    active_share.revoked_at = datetime.now(UTC)
    assert await workspace_governance_service.purge_expired(db_session) == 1
    assert deleted_refs == []
    assert await db_session.get(WorkspaceFile, survivor.id) is survivor


@pytest.mark.asyncio
async def test_expired_workspace_containers_wait_for_files_then_are_removed(
    db_session, monkeypatch,
):
    organization = await _organization(db_session, "workspace-container-purge")
    workspace = await _workspace(db_session, organization, "expired-workspace")
    deadline = datetime.now(UTC) - timedelta(seconds=1)
    workspace.deleted_at = datetime.now(UTC) - timedelta(days=31)
    workspace.purge_after = deadline
    folder = WorkspaceFolder(
        workspace_id=workspace.id,
        path="reports",
        deleted_at=workspace.deleted_at,
        purge_after=deadline,
    )
    file = WorkspaceFile(
        workspace_id=workspace.id,
        path="reports/final.xlsx",
        size=10,
        content_ref="oss://workspace/final.xlsx",
        metadata_={},
        deleted_at=workspace.deleted_at,
        purge_after=deadline,
    )
    db_session.add_all([folder, file])
    await db_session.flush()
    monkeypatch.setattr(
        storage_gateway_service, "delete_object", lambda _ref: _async_value(None),
    )

    blocked = await storage_lifecycle_service._purge_workspace_containers(db_session, datetime.now(UTC))
    assert blocked == {"workspace_folders": 0, "workspaces": 0}
    assert await workspace_governance_service.purge_expired(db_session) == 1
    removed = await storage_lifecycle_service._purge_workspace_containers(db_session, datetime.now(UTC))
    assert removed == {"workspace_folders": 1, "workspaces": 1}
    await db_session.flush()
    assert await db_session.get(Workspace, workspace.id) is None


@pytest.mark.asyncio
async def test_expired_skill_content_is_removed_after_package_purge(db_session):
    organization = await _organization(db_session, "skill-content-purge")
    deadline = datetime.now(UTC) - timedelta(seconds=1)
    folder = SkillFolder(
        organization_id=organization.id,
        scope_type="organization",
        name="Expired Skill",
        slug="expired-skill",
        is_active=False,
        deleted_at=datetime.now(UTC) - timedelta(days=31),
        purge_after=deadline,
    )
    db_session.add(folder)
    await db_session.flush()
    source = SkillFile(
        skill_folder_id=folder.id,
        path="scripts/process.py",
        size=17,
        content="print('private')",
        deleted_at=folder.deleted_at,
        purge_after=deadline,
    )
    version = SkillVersion(
        skill_folder_id=folder.id,
        version_no=1,
        package_hash="d" * 64,
        manifest={},
        archive=None,
        archive_ref=None,
        archive_size=0,
        archive_purged_at=datetime.now(UTC),
        storage_status="purged",
        purge_after=deadline,
        runtime="agent_skill",
        install_status="ready",
    )
    db_session.add_all([source, version])
    await db_session.flush()

    assert await storage_lifecycle_service._finalize_skill_folders(db_session, datetime.now(UTC)) == 1
    await db_session.flush()
    assert await db_session.get(SkillFile, source.id) is None
    assert folder.purge_after is None
    assert folder.deleted_at is not None


@pytest.mark.asyncio
async def test_rag_ontology_and_upload_session_are_physically_cleaned(
    db_session, monkeypatch,
):
    organization = await _organization(db_session, "content-purge")
    workspace = await _workspace(db_session, organization, "content-purge")
    admin = Admin(username="lifecycle-admin", password_hash="x", role="super_admin", is_active=True)
    collection = RagCollection(
        organization_id=organization.id,
        name="Expired RAG",
        slug="expired-rag",
        embedding_model="test",
        deleted_at=datetime.now(UTC) - timedelta(days=31),
        purge_after=datetime.now(UTC) - timedelta(days=1),
    )
    ontology = Ontology(
        organization_id=organization.id,
        name="Expired Ontology",
        slug="expired-ontology",
        entities=[{"secret": "remove"}],
        relations=[{"secret": "remove"}],
        deleted_at=datetime.now(UTC) - timedelta(days=31),
        purge_after=datetime.now(UTC) - timedelta(days=1),
    )
    ontology_file = OntologyFile(
        organization_id=organization.id,
        scope_type="organization",
        path="private.md",
        content="remove me",
        size=9,
        deleted_at=datetime.now(UTC) - timedelta(days=31),
        purge_after=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add_all([admin, collection, ontology, ontology_file])
    await db_session.flush()
    document = RagDocument(
        collection_id=collection.id,
        source="secret.txt",
        content="remove me",
        status="ready",
        deleted_at=datetime.now(UTC) - timedelta(days=31),
        purge_after=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(document)
    await db_session.flush()
    chunk = RagChunk(collection_id=collection.id, document_id=document.id, content="remove me")
    session = WorkspaceUploadSession(
        organization_id=organization.id,
        workspace_id=workspace.id,
        admin_id=admin.id,
        path="expired.bin",
        original_filename="expired.bin",
        content_type="application/octet-stream",
        expected_size=10,
        content_ref="oss://temporary/expired.bin",
        status="pending",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add_all([chunk, session])
    await db_session.flush()
    deleted_refs: list[str] = []
    monkeypatch.setattr(
        storage_gateway_service,
        "delete_object",
        lambda ref: _record_async(deleted_refs, ref),
    )

    assert await storage_lifecycle_service._purge_rag(db_session, datetime.now(UTC)) == 1
    assert await storage_lifecycle_service._purge_ontology(db_session, datetime.now(UTC)) == 2
    assert await storage_lifecycle_service.expire_upload_sessions(db_session) == {"expired": 1, "failed": 0}
    assert document.content == "" and document.status == "purged"
    assert (await db_session.execute(select(RagChunk))).scalars().all() == []
    assert ontology.entities == [] and ontology.relations == []
    assert ontology_file.content is None and ontology_file.size == 0
    assert session.status == "expired" and session.content_ref is None
    assert deleted_refs == ["oss://temporary/expired.bin"]


@pytest.mark.asyncio
async def test_orphan_scan_deletes_only_unreferenced_old_objects(db_session, monkeypatch):
    organization = await _organization(db_session, "orphan-scan")
    workspace = await _workspace(db_session, organization, "orphan-scan")
    db_session.add(WorkspaceFile(
        workspace_id=workspace.id,
        path="kept.bin",
        size=1,
        content_ref="oss://workspace/kept.bin",
        metadata_={},
    ))
    await db_session.flush()
    monkeypatch.setattr(
        storage_gateway_service,
        "list_project_objects",
        lambda **_kwargs: _async_value({
            "items": [
                {"object_key": "workspace/kept.bin", "size": 1, "created_at": ""},
                {"object_key": "workspace/orphan.bin", "size": 2, "created_at": ""},
            ],
            "next_cursor": None,
        }),
    )
    deleted_refs: list[str] = []
    monkeypatch.setattr(
        storage_gateway_service,
        "delete_object",
        lambda ref: _record_async(deleted_refs, ref),
    )

    result = await storage_lifecycle_service.reconcile_orphan_objects(db_session)
    assert result == {
        "orphan_scan_supported": 1,
        "orphans_scanned": 2,
        "orphans_deleted": 1,
        "orphan_failures": 0,
    }
    assert deleted_refs == ["oss://workspace/orphan.bin"]


async def _async_value(value):
    return value


async def _record_async(target: list[str], value: str):
    target.append(value)
