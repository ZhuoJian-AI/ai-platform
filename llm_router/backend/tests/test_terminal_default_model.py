from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import terminal


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [None, "", "default", "allowed", "forbidden"])
async def test_default_model_reaches_router_but_explicit_model_remains_checked(monkeypatch, selected):
    org_id, task_id, ws_id = uuid4(), uuid4(), uuid4()
    task = SimpleNamespace(id=task_id, organization_id=org_id, session_id="e2e",
                           config={"model_alias": selected})
    user = SimpleNamespace(id=str(uuid4()), organization_id=org_id)
    workspace = SimpleNamespace(id=ws_id, organization_id=org_id)
    monkeypatch.setattr(terminal, "_get_owned_task", AsyncMock(return_value=task))
    monkeypatch.setattr(terminal, "assert_user_write", lambda _: None)
    monkeypatch.setattr(terminal, "_user_defaults", AsyncMock(return_value={"workspace_id": str(ws_id)}))
    monkeypatch.setattr(terminal.workspace_service, "get_workspace", AsyncMock(return_value=workspace))
    monkeypatch.setattr(terminal.workspace_permission_service, "assert_can_create", AsyncMock())
    monkeypatch.setattr(terminal, "_resolve_task_attachments", AsyncMock(return_value=[]))
    monkeypatch.setattr(terminal, "_resolve_task_file_refs", AsyncMock(return_value=[]))
    monkeypatch.setattr(terminal.task_service, "list_persistent_file_refs", AsyncMock(return_value=[]))
    monkeypatch.setattr(terminal.task_service, "upsert_task_file_refs", AsyncMock())
    monkeypatch.setattr(terminal.scope_service, "list_available_models_for_user", AsyncMock(return_value=["allowed"]))
    monkeypatch.setattr(terminal, "_assert_client_request_not_completed", AsyncMock())
    dispatch = AsyncMock(return_value={"started": True})
    monkeypatch.setattr(terminal, "stream_general_agent", dispatch)
    db = SimpleNamespace(flush=AsyncMock())
    data = terminal.TaskRunRequest(message="帮我生成语音", stream=True)
    if selected == "forbidden":
        with pytest.raises(HTTPException) as failure:
            await terminal.run_task_endpoint(task_id, data, object(), cu=user, db=db)
        assert failure.value.status_code == 400
        dispatch.assert_not_awaited()
    else:
        assert await terminal.run_task_endpoint(task_id, data, object(), cu=user, db=db) == {"started": True}
        assert dispatch.call_args.kwargs["config"]["model_alias"] == (selected or "default")
