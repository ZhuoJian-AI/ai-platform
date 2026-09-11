import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.agents.graph import builtin_tools as tools
from app.agents.graph.context import bind_runtime


@pytest.fixture(autouse=True)
def db_engine():
    yield


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke_at", [0, 2, 3])
async def test_image_receipt_and_upload_revocation(monkeypatch, revoke_at):
    @asynccontextmanager
    async def savepoint():
        yield

    db = SimpleNamespace(begin_nested=savepoint, add=Mock(), flush=AsyncMock())
    ws = SimpleNamespace(id=uuid4())
    user = SimpleNamespace(id=uuid4())
    saved = SimpleNamespace(id=uuid4(), current_version_id=uuid4(), path="image.png", metadata_={},
                            content_hash="abc", content_ref="oss://test", parse_status="unsupported")
    monkeypatch.setattr(tools.workspace_service, "get_workspace", AsyncMock(return_value=ws))
    calls = 0

    async def resolve(*args, **kwargs):
        nonlocal calls
        calls += 1
        return (None, user, "权限已撤销") if calls == revoke_at else (ws, user, None)

    monkeypatch.setattr(tools, "_resolve_tool_workspace", resolve)
    monkeypatch.setattr(tools.multimodal_service, "resolve_image_generation", AsyncMock(
        return_value=SimpleNamespace(provider=SimpleNamespace(config={}), model="test")))
    monkeypatch.setattr(tools, "scan_request", AsyncMock(
        return_value=SimpleNamespace(blocked=False, redacted_text=None)))
    monkeypatch.setattr(tools.llm_client, "generate_image", AsyncMock(return_value=SimpleNamespace(
        raw=b"png", provider_id=str(uuid4()), model_served="test", revised_prompt=None)))
    monkeypatch.setattr(tools.multimodal_service, "normalize_generated_png", lambda _: (b"png", 8, 8))
    ingest = AsyncMock(return_value=saved)
    monkeypatch.setattr(tools.workspace_service, "ingest_uploaded_file", ingest)
    monkeypatch.setattr(tools.workspace_service, "sync_current_version", AsyncMock())
    monkeypatch.setattr(tools, "_task_source_fields", AsyncMock(return_value={}))
    monkeypatch.setattr(tools, "enrich_metadata", lambda *args, **kwargs: {})
    cleanup = AsyncMock()
    monkeypatch.setattr(tools.storage_gateway_service, "delete_object", cleanup)
    state = {"org_id": str(uuid4()), "workspace_id": str(ws.id), "exec_mode": "craft"}
    with bind_runtime({"db": db, "user": user}):
        result = json.loads(await tools._execute_builtin_tool(state, "image_generation_tool", {"prompt": "shirt"}))
    if revoke_at:
        assert result["status"] != "success"
        assert result["retryable"] is False
        assert "outputs" not in result
        assert ingest.await_count == (1 if revoke_at == 3 else 0)
        assert cleanup.await_count == (1 if revoke_at == 3 else 0)
    else:
        output = result["outputs"][0]
        assert output["version_id"] == str(saved.current_version_id)
        assert output["file_id"] == str(saved.id)
        assert output["mime_type"] == "image/png"
        assert output["workspace_id"] == str(ws.id)
