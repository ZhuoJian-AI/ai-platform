"""File execution policy tests; no database or external storage is contacted."""
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.graph import builtin_tools as tools


@pytest.fixture
def lane(monkeypatch):
    source = SimpleNamespace(id=uuid4(), workspace_id=uuid4(), current_version_id=uuid4(), path="原件.txt",
                             content="old", deleted_at=None, metadata_={})
    destination = SimpleNamespace(id=uuid4(), name="个人空间")
    user = SimpleNamespace(id=uuid4())
    db = SimpleNamespace(refresh=AsyncMock(), flush=AsyncMock(), delete=AsyncMock())
    output = SimpleNamespace(id=uuid4(), current_version_id=uuid4(), path="修改版.txt",
                             parse_status="ready", metadata_={})
    mutation = SimpleNamespace()
    monkeypatch.setattr(tools, "get_deps", lambda: {"db": db})
    monkeypatch.setattr(tools, "_authorized_file", AsyncMock(return_value=(source, destination, user)))
    monkeypatch.setattr(tools, "_resolve_tool_workspace", AsyncMock(return_value=(destination, user, None)))
    monkeypatch.setattr(tools, "_authorized_input_file", AsyncMock(return_value=(source, user)))
    monkeypatch.setattr(tools, "_runner_input", AsyncMock(return_value={"name": "原件.txt"}))
    monkeypatch.setattr(tools, "_task_source_fields", AsyncMock(return_value={}))
    monkeypatch.setattr(tools, "_workspace_file_identity", AsyncMock(
        side_effect=lambda _db, f, _ws, _user: {"file_id": str(f.id), "version_id": str(f.current_version_id)},
    ))
    monkeypatch.setattr(tools.workspace_service, "get_workspace", AsyncMock(return_value=destination))
    monkeypatch.setattr(tools.workspace_service, "ingest_uploaded_file", AsyncMock(return_value=output))
    monkeypatch.setattr(tools.workspace_service, "sync_current_version", AsyncMock())
    monkeypatch.setattr(tools.workspace_service, "begin_file_mutation", AsyncMock(return_value=(mutation, False)))
    monkeypatch.setattr(tools.workspace_service, "complete_file_mutation", AsyncMock())
    monkeypatch.setattr(tools.workspace_service, "replace_file_artifact",
                        AsyncMock(side_effect=AssertionError("overwrite")))
    monkeypatch.setattr(tools, "_authorized_create_replay", AsyncMock(return_value=(output, destination, user)))
    runner = AsyncMock(return_value=({"outputs": [{
        "name": "修改版.txt", "content_base64": base64.b64encode(b"new").decode(), "mime_type": "text/plain",
    }]}, 1))
    monkeypatch.setattr(tools.tool_executor_client, "execute_builtin", runner)
    params = {"content": "new", "format": "txt", "target_file_id": str(source.id),
              "base_version_id": str(source.current_version_id), "idempotency_key": "save-as-operation-1"}
    return SimpleNamespace(source=source, destination=destination, user=user, db=db, output=output,
                           runner=runner, params=params, mutation=mutation)


async def execute(lane):
    return json.loads(await tools._execute_platform_file_tool(
        {"exec_mode": "craft", "workspace_id": str(lane.destination.id)},
        "text_create", lane.params, lane.destination, lane.user,
    ))


@pytest.mark.asyncio
async def test_save_as_preserves_original_and_returns_new_identity(lane):
    version = lane.source.current_version_id
    result = await execute(lane)
    assert result["status"] == "success"
    assert result["outputs"][0]["file_id"] == str(lane.output.id)
    assert lane.source.content == "old" and lane.source.current_version_id == version
    assert lane.output.metadata_["derived_from_file_id"] == str(lane.source.id)
    assert all(call.kwargs["capability"] == "read" for call in tools._authorized_file.await_args_list)
    assert all(call.kwargs["capability"] == "create" for call in tools._resolve_tool_workspace.await_args_list)
    tools.workspace_service.replace_file_artifact.assert_not_called()


@pytest.mark.asyncio
async def test_replay_returns_existing_output_without_second_file(lane):
    await execute(lane)
    tools.workspace_service.begin_file_mutation.return_value = (lane.mutation, True)
    result = await execute(lane)
    assert result["outputs"][0]["file_id"] == str(lane.output.id)
    assert tools.workspace_service.ingest_uploaded_file.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["version", "source_permission", "destination_permission"])
async def test_changes_during_execution_block_commit(lane, change):
    if change == "version":
        async def refresh(*args, **kwargs):
            lane.source.current_version_id = uuid4()
        lane.db.refresh.side_effect = refresh
    elif change == "source_permission":
        tools._authorized_file.side_effect = [(lane.source, lane.destination, lane.user), (None, None, lane.user)]
    else:
        tools._resolve_tool_workspace.side_effect = [
            (lane.destination, lane.user, None), (None, lane.user, "无创建权限"),
        ]
    result = await execute(lane)
    assert result["status"] != "success"
    tools.workspace_service.ingest_uploaded_file.assert_not_called()
    tools.workspace_service.begin_file_mutation.assert_not_called()
    assert lane.source.content == "old"


@pytest.mark.asyncio
async def test_stale_source_is_rejected_before_executor(lane):
    lane.params["base_version_id"] = str(uuid4())
    assert (await execute(lane))["status"] == "conflict"
    lane.runner.assert_not_called()
