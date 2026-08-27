"""Workspace list endpoints return paged metadata without document payloads."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_auth import CurrentUser, require_user
from app.main import app
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceFileCreate
from app.services import workspace_service


@pytest.mark.asyncio
async def test_admin_file_list_is_paged_and_excludes_payloads(
    client: AsyncClient,
    db_session: AsyncSession,
):
    suffix = uuid4().hex[:8]
    org = Organization(name=f"列表测试-{suffix}", slug=f"list-{suffix}")
    db_session.add(org)
    await db_session.flush()
    ws = Workspace(
        organization_id=org.id,
        name="列表空间",
        slug=f"list-ws-{suffix}",
        scope_type="organization",
    )
    db_session.add(ws)
    await db_session.flush()
    first = await workspace_service.upsert_file(
        db_session, ws,
        WorkspaceFileCreate(path="a.txt", content="A" * 100_000),
    )
    first.extracted_text = "不得出现在列表" * 1000
    await workspace_service.upsert_file(
        db_session, ws,
        WorkspaceFileCreate(path="b.txt", content="B" * 100_000),
    )
    await db_session.flush()

    response = await client.get(
        f"/api/v1/workspaces/{ws.id}/files?page=1&page_size=1",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["path"] == "a.txt"
    assert item["original_filename"] == "a.txt"
    assert item["presentation"]["display_name"] == "a.txt"
    assert item["presentation"]["source_kind"] == "upload"
    assert "content" not in item
    assert "extracted_text" not in item
    assert "不得出现在列表" not in response.text

    second = await client.get(
        f"/api/v1/workspaces/{ws.id}/files?page=2&page_size=1",
    )
    assert second.status_code == 200
    assert second.json()["items"][0]["path"] == "b.txt"


@pytest.mark.asyncio
async def test_file_list_page_size_is_bounded(client: AsyncClient, db_session: AsyncSession):
    suffix = uuid4().hex[:8]
    org = Organization(name=f"分页校验-{suffix}", slug=f"bound-{suffix}")
    db_session.add(org)
    await db_session.flush()
    ws = Workspace(
        organization_id=org.id,
        name="分页空间",
        slug=f"bound-ws-{suffix}",
        scope_type="organization",
    )
    db_session.add(ws)
    await db_session.flush()

    response = await client.get(
        f"/api/v1/workspaces/{ws.id}/files?page=1&page_size=201",
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_terminal_global_file_summary_can_read_projected_metadata(
    client: AsyncClient,
    db_session: AsyncSession,
):
    suffix = uuid4().hex[:8]
    org = Organization(name=f"终端列表-{suffix}", slug=f"terminal-list-{suffix}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        username=f"terminal-{suffix}",
        role="member",
        is_active=True,
    )
    ws = Workspace(
        organization_id=org.id,
        name="组织空间",
        slug=f"terminal-ws-{suffix}",
        scope_type="organization",
    )
    db_session.add_all([user, ws])
    await db_session.flush()
    file = await workspace_service.upsert_file(
        db_session,
        ws,
        WorkspaceFileCreate(
            path="二进制报告.pdf",
            content="JVBERi0xLjQ=",
            metadata={"binary": True, "name": "二进制报告.pdf"},
        ),
    )
    current_user = CurrentUser(
        user=user,
        id=str(user.id),
        email=user.username,
        role=user.role,
        organization_id=org.id,
    )
    app.dependency_overrides[require_user] = lambda: current_user

    response = await client.get("/api/v1/terminal/workspace-files")

    assert response.status_code == 200
    assert response.json() == [{
        "id": str(file.id),
        "workspace_id": str(ws.id),
        "workspace_name": ws.name,
        "path": file.path,
        "original_filename": "二进制报告.pdf",
        "presentation": {
            "display_name": "二进制报告.pdf",
            "source_kind": "upload",
            "source_task_id": None,
            "source_task_title": None,
            "skill_id": None,
            "skill_display_name": None,
            "skill_version": None,
            "created_at": file.created_at.isoformat(),
        },
        "scope_type": "organization",
        "is_binary": True,
    }]
