"""Tests for the retained workspace and text-persona agent CRUD."""

import pytest
from httpx import AsyncClient


async def _make_org(client: AsyncClient, slug: str = "agent-org") -> str:
    r = await client.post("/api/v1/organizations", json={"name": f"公司-{slug}", "slug": slug})
    assert r.status_code == 201
    return r.json()["id"]


# ── Workspace ──

@pytest.mark.asyncio
async def test_workspace_and_files(client: AsyncClient):
    org_id = await _make_org(client, "ws-org")
    ws = await client.post(
        f"/api/v1/organizations/{org_id}/workspaces",
        json={"name": "默认空间", "slug": "default"},
    )
    assert ws.status_code == 201
    ws_id = ws.json()["id"]

    # 路径穿越必须被安全拒绝，不能归一化成沙箱内的另一个文件。
    rejected = await client.post(
        f"/api/v1/workspaces/{ws_id}/files",
        json={"path": "/../secret/../../notes.md", "content": "hello"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "workspace_file_invalid_path"

    # 拒绝坏请求后，正常的相对路径仍可写入。
    f = await client.post(
        f"/api/v1/workspaces/{ws_id}/files",
        json={"path": "/notes.md", "content": "hello"},
    )
    assert f.status_code == 201
    assert f.json()["path"] == "notes.md"
    assert f.json()["content"] == "hello"

    listed = await client.get(f"/api/v1/workspaces/{ws_id}/files")
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["path"] == "notes.md"
    assert "content" not in body["items"][0]


# ── Agent ──

@pytest.mark.asyncio
async def test_agent_crud(client: AsyncClient):
    org_id = await _make_org(client, "ag-org")
    r = await client.post(
        f"/api/v1/organizations/{org_id}/agents",
        json={"name": "客服", "description": "在线支持", "system_prompt": "你是客服"},
    )
    assert r.status_code == 201
    aid = r.json()["id"]
    assert r.json()["system_prompt"] == "你是客服"
    assert r.json()["slug"]

    upd = await client.patch(f"/api/v1/agents/{aid}", json={"description": "在线客服"})
    assert upd.status_code == 200
    assert upd.json()["description"] == "在线客服"
    assert upd.json()["version"] == 2  # 更新自增版本

    listed = await client.get(f"/api/v1/organizations/{org_id}/agents")
    assert any(a["id"] == aid for a in listed.json())

    dele = await client.delete(f"/api/v1/agents/{aid}")
    assert dele.status_code == 204


@pytest.mark.asyncio
async def test_agent_rejects_retired_binding_fields(client: AsyncClient):
    org_id = await _make_org(client, "ag-strict-org")
    response = await client.post(
        f"/api/v1/organizations/{org_id}/agents",
        json={
            "name": "不应创建",
            "system_prompt": "文本角色",
            "model_alias": "default",
            "skill_ids": [],
            "rag_collection_ids": [],
        },
    )
    assert response.status_code == 422
