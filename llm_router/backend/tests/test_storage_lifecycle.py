"""Workspace retention, OSS compensation and physical cleanup tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.admin import Admin
from app.models.organization import Organization
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
        storage_gateway_service,
        "delete_object",
        lambda _ref: _async_value(None),
    )

    blocked = await storage_lifecycle_service._purge_workspace_containers(
        db_session,
        datetime.now(UTC),
    )
    assert blocked == {"workspace_folders": 0, "workspaces": 0}
    assert await workspace_governance_service.purge_expired(db_session) == 1
    removed = await storage_lifecycle_service._purge_workspace_containers(
        db_session,
        datetime.now(UTC),
    )
    assert removed == {"workspace_folders": 1, "workspaces": 1}
    await db_session.flush()
    assert await db_session.get(Workspace, workspace.id) is None


@pytest.mark.asyncio
async def test_expired_upload_session_is_physically_cleaned(db_session, monkeypatch):
    organization = await _organization(db_session, "upload-session-purge")
    workspace = await _workspace(db_session, organization, "upload-session-purge")
    admin = Admin(
        username="lifecycle-admin",
        password_hash="x",
        role="platform_super_admin",
        is_active=True,
    )
    db_session.add(admin)
    await db_session.flush()
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
    db_session.add(session)
    await db_session.flush()
    deleted_refs: list[str] = []
    monkeypatch.setattr(
        storage_gateway_service,
        "delete_object",
        lambda ref: _record_async(deleted_refs, ref),
    )

    assert await storage_lifecycle_service.expire_upload_sessions(db_session) == {
        "expired": 1,
        "failed": 0,
    }
    assert session.status == "expired" and session.content_ref is None
    assert deleted_refs == ["oss://temporary/expired.bin"]


@pytest.mark.asyncio
async def test_orphan_scan_deletes_only_unreferenced_old_objects(db_session, monkeypatch):
    organization = await _organization(db_session, "orphan-scan")
    workspace = await _workspace(db_session, organization, "orphan-scan")
    db_session.add(
        WorkspaceFile(
            workspace_id=workspace.id,
            path="kept.bin",
            size=1,
            content_ref="oss://workspace/kept.bin",
            metadata_={},
        )
    )
    await db_session.flush()
    monkeypatch.setattr(
        storage_gateway_service,
        "list_project_objects",
        lambda **_kwargs: _async_value(
            {
                "items": [
                    {"object_key": "workspace/kept.bin", "size": 1, "created_at": ""},
                    {"object_key": "workspace/orphan.bin", "size": 2, "created_at": ""},
                ],
                "next_cursor": None,
            }
        ),
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
