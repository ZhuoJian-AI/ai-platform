"""Workspace governance, direct OSS upload and immutable version coverage."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.auth.user_auth import CurrentUser
from app.config import settings
from app.models.department import Department
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceFileCreate, WorkspaceFileRead, WorkspaceUploadInitiate
from app.services import (
    workspace_governance_service,
    workspace_permission_service,
    workspace_service,
)


def test_direct_upload_accepts_file_below_proxy_threshold(monkeypatch):
    """Client/server routing-threshold drift must not reject an OSS upload."""
    monkeypatch.setattr(settings, "workspace_proxy_upload_max_bytes", 10 * 1024 * 1024)
    workspace_governance_service._validate_direct_upload_size(2 * 1024 * 1024)


def test_direct_upload_still_rejects_file_over_workspace_limit(monkeypatch):
    monkeypatch.setattr(settings, "workspace_max_file_bytes", 100 * 1024 * 1024)
    with pytest.raises(HTTPException) as exc:
        workspace_governance_service._validate_direct_upload_size(100 * 1024 * 1024 + 1)
    assert exc.value.status_code == 413


async def _tenant(db_session):
    org = Organization(name="Workspace Org", slug=f"workspace-{uuid4().hex[:8]}")
    foreign_org = Organization(name="Foreign Org", slug=f"foreign-{uuid4().hex[:8]}")
    db_session.add_all([org, foreign_org])
    await db_session.flush()
    department = Department(
        organization_id=org.id, name="Finance", slug=f"finance-{uuid4().hex[:8]}",
    )
    db_session.add(department)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        username=f"member-{uuid4().hex[:8]}",
        role="member",
        department_id=department.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    personal = Workspace(
        organization_id=org.id,
        name="Personal",
        slug=f"personal-{uuid4().hex[:8]}",
        scope_type="user",
        scope_id=str(user.id),
    )
    department_ws = Workspace(
        organization_id=org.id,
        name="Finance",
        slug=f"department-{uuid4().hex[:8]}",
        scope_type="department",
        scope_id=str(department.id),
    )
    organization_ws = Workspace(
        organization_id=org.id,
        name="Organization",
        slug=f"organization-{uuid4().hex[:8]}",
        scope_type="organization",
    )
    foreign_ws = Workspace(
        organization_id=foreign_org.id,
        name="Foreign",
        slug=f"foreign-ws-{uuid4().hex[:8]}",
        scope_type="organization",
    )
    db_session.add_all([personal, department_ws, organization_ws, foreign_ws])
    await db_session.flush()
    cu = CurrentUser(
        user=user,
        id=str(user.id),
        email=user.username,
        role=user.role,
        organization_id=org.id,
        department_id=str(department.id),
    )
    return cu, personal, department_ws, organization_ws, foreign_ws


@pytest.mark.asyncio
async def test_member_capabilities_and_cross_tenant_are_consistent(db_session):
    cu, personal, department_ws, organization_ws, foreign_ws = await _tenant(db_session)

    assert await workspace_permission_service.capabilities(db_session, personal, cu) == {
        "read": True, "create": True, "update": True, "delete": True,
        "manage": True, "publish": False,
    }
    assert await workspace_permission_service.capabilities(db_session, department_ws, cu) == {
        "read": True, "create": False, "update": False, "delete": False,
        "manage": False, "publish": False,
    }
    assert await workspace_permission_service.capabilities(db_session, organization_ws, cu) == {
        "read": True, "create": False, "update": False, "delete": False,
        "manage": False, "publish": False,
    }
    assert not (await workspace_permission_service.capabilities(db_session, foreign_ws, cu))["read"]
    with pytest.raises(HTTPException) as exc:
        await workspace_permission_service.assert_can_read(db_session, foreign_ws, cu)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_role_codes_grant_cross_department_read_and_upload(db_session):
    cu, _, _, _, _ = await _tenant(db_session)
    department = Department(
        organization_id=cu.organization_id,
        name="Quality",
        slug=f"quality-{uuid4().hex[:8]}",
    )
    db_session.add(department)
    await db_session.flush()
    workspace = Workspace(
        organization_id=cu.organization_id,
        name="Quality",
        slug=f"department-{uuid4().hex[:8]}",
        scope_type="department",
        scope_id=str(department.id),
    )
    db_session.add(workspace)
    await db_session.flush()

    assert await workspace_permission_service.capabilities(db_session, workspace, cu) == {
        "read": False, "create": False, "update": False, "delete": False,
        "manage": False, "publish": False,
    }
    cu.permission_codes = (
        f"{workspace_permission_service.DEPARTMENT_READ_PREFIX}{department.id}",
    )
    assert await workspace_permission_service.capabilities(db_session, workspace, cu) == {
        "read": True, "create": False, "update": False, "delete": False,
        "manage": False, "publish": False,
    }
    cu.permission_codes = (
        f"{workspace_permission_service.DEPARTMENT_UPLOAD_PREFIX}{department.id}",
    )
    assert await workspace_permission_service.capabilities(db_session, workspace, cu) == {
        "read": True, "create": True, "update": True, "delete": False,
        "manage": True, "publish": False,
    }
    with pytest.raises(HTTPException) as exc:
        await workspace_permission_service.assert_can_delete(db_session, workspace, cu)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_terminal_cannot_publish_into_shared_workspace(db_session):
    cu, personal, department_ws, _, _ = await _tenant(db_session)
    source = await workspace_service.upsert_file(
        db_session,
        personal,
        WorkspaceFileCreate(path="report.txt", content="personal-v1"),
        created_by_user_id=cu.id,
    )
    with pytest.raises(HTTPException) as exc:
        await workspace_governance_service.publish_file(
            db_session, personal, source, department_ws, cu, None,
        )
    assert exc.value.status_code == 403
    assert source.workspace_id == personal.id
    assert source.deleted_at is None


@pytest.mark.asyncio
async def test_direct_upload_verifies_oss_and_can_restore_from_trash(db_session, monkeypatch):
    cu, personal, _, _, _ = await _tenant(db_session)
    expected_size = 11 * 1024 * 1024

    async def fake_sign(**_kwargs):
        return {
            "url": "https://oss.example.test/signed-put",
            "headers": {"Content-Type": "application/pdf"},
            "object_key": "projects/test/workspace/file.pdf",
        }

    async def fake_inspect(_content_ref):
        return {"size": expected_size, "etag": "etag-1", "content_type": "application/pdf"}

    monkeypatch.setattr(settings, "workspace_object_storage_enabled", True)
    monkeypatch.setattr(settings, "storage_gateway_url", "https://storage.example.test")
    monkeypatch.setattr(settings, "storage_project_token", "test-token")
    monkeypatch.setattr(
        workspace_governance_service.storage_gateway_service,
        "sign_browser_upload",
        fake_sign,
    )
    monkeypatch.setattr(
        workspace_governance_service.storage_gateway_service,
        "inspect_object",
        fake_inspect,
    )

    session = await workspace_governance_service.initiate_direct_upload(
        db_session,
        personal,
        cu,
        WorkspaceUploadInitiate(
            path="invoices/file.pdf",
            filename="file.pdf",
            content_type="application/pdf",
            size=expected_size,
        ),
    )
    saved = await workspace_governance_service.complete_direct_upload(
        db_session, session, cu, client_etag='"etag-1"',
    )
    assert saved.content_ref == "oss://projects/test/workspace/file.pdf"
    assert saved.size == expected_size
    assert saved.parse_status == "queued"
    assert saved.current_version_id is not None
    # Direct-upload completion is returned through ``WorkspaceFileRead``.
    # Validate the exact response shape so server-generated timestamps cannot
    # be left expired after the final ORM flush.
    assert WorkspaceFileRead.model_validate(saved).updated_at is not None

    await workspace_service.soft_delete_file(db_session, saved, user_id=cu.id)
    restored = await workspace_governance_service.restore_from_trash(
        db_session, personal, saved.id, cu,
    )
    assert restored.deleted_at is None
    assert restored.purge_after is None
    assert WorkspaceFileRead.model_validate(restored).updated_at is not None


@pytest.mark.asyncio
async def test_direct_upload_rejects_authoritative_size_mismatch(db_session, monkeypatch):
    cu, personal, _, _, _ = await _tenant(db_session)
    expected_size = 11 * 1024 * 1024

    async def fake_sign(**_kwargs):
        return {"url": "https://oss.example.test/put", "headers": {}, "object_key": "x/file.bin"}

    async def fake_inspect(_content_ref):
        return {"size": expected_size - 1, "etag": "etag", "content_type": "application/octet-stream"}

    monkeypatch.setattr(settings, "workspace_object_storage_enabled", True)
    monkeypatch.setattr(settings, "storage_gateway_url", "https://storage.example.test")
    monkeypatch.setattr(settings, "storage_project_token", "test-token")
    monkeypatch.setattr(
        workspace_governance_service.storage_gateway_service, "sign_browser_upload", fake_sign,
    )
    monkeypatch.setattr(
        workspace_governance_service.storage_gateway_service, "inspect_object", fake_inspect,
    )
    session = await workspace_governance_service.initiate_direct_upload(
        db_session,
        personal,
        cu,
        WorkspaceUploadInitiate(
            path="file.bin", filename="file.bin",
            content_type="application/octet-stream", size=expected_size,
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await workspace_governance_service.complete_direct_upload(db_session, session, cu)
    assert exc.value.status_code == 409
    assert session.status == "failed"
