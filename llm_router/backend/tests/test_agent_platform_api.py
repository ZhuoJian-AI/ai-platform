"""Tests for agent platform CRUD (workspace / agent / judge / rag)."""

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

    # 写文件（路径规范化：剥离前导 / 与 ..）
    f = await client.post(
        f"/api/v1/workspaces/{ws_id}/files",
        json={"path": "/../secret/../../notes.md", "content": "hello"},
    )
    assert f.status_code == 201
    # 路径规范化：剥离前导 / 与所有 .. 段，确保沙箱内
    assert f.json()["path"] == "notes.md"
    assert f.json()["content"] == "hello"

    listed = await client.get(f"/api/v1/workspaces/{ws_id}/files")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


# ── Agent ──

@pytest.mark.asyncio
async def test_agent_crud(client: AsyncClient):
    org_id = await _make_org(client, "ag-org")
    r = await client.post(
        f"/api/v1/organizations/{org_id}/agents",
        json={"name": "客服", "slug": "support", "system_prompt": "你是客服", "model_alias": "default"},
    )
    assert r.status_code == 201
    aid = r.json()["id"]
    assert r.json()["system_prompt"] == "你是客服"

    upd = await client.patch(f"/api/v1/agents/{aid}", json={"description": "在线客服"})
    assert upd.status_code == 200
    assert upd.json()["description"] == "在线客服"
    assert upd.json()["version"] == 2  # 更新自增版本

    listed = await client.get(f"/api/v1/organizations/{org_id}/agents")
    assert any(a["id"] == aid for a in listed.json())

    dele = await client.delete(f"/api/v1/agents/{aid}")
    assert dele.status_code == 204


# ── Judge ──

@pytest.mark.asyncio
async def test_judge_crud(client: AsyncClient):
    org_id = await _make_org(client, "jg-org")
    r = await client.post(
        f"/api/v1/organizations/{org_id}/judges",
        json={"name": "准确性判官", "slug": "accuracy",
              "criteria": [{"dimension": "准确性", "weight": 1.0}]},
    )
    assert r.status_code == 201
    jid = r.json()["id"]
    assert r.json()["criteria"][0]["dimension"] == "准确性"

    g = await client.get(f"/api/v1/judges/{jid}")
    assert g.status_code == 200


# ── RAG collection + ingest（embedding 无 provider 时明确失败）──

@pytest.mark.asyncio
async def test_rag_collection_and_ingest(client: AsyncClient):
    org_id = await _make_org(client, "rag-org")
    coll = await client.post(
        f"/api/v1/organizations/{org_id}/rag",
        json={"name": "知识库", "slug": "kb", "chunk_size": 50, "chunk_overlap": 10},
    )
    assert coll.status_code == 201
    coll_id = coll.json()["id"]

    # 无 embedding provider：不得伪装成入库成功；保留 failed 文档供前端排查。
    doc = await client.post(
        f"/api/v1/rag/{coll_id}/documents",
        json={"source": "manual.txt", "content": "a" * 120, "title": "手动文档"},
    )
    assert doc.status_code == 502
    assert "embedding 不可用" in doc.json()["detail"]

    docs = await client.get(f"/api/v1/rag/{coll_id}/documents")
    assert len(docs.json()) == 1
    assert docs.json()[0]["source"] == "manual.txt"
    assert docs.json()[0]["status"] == "failed"
