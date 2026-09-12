import json
from types import SimpleNamespace

import pytest

from app.agents.core import runner


@pytest.mark.asyncio
@pytest.mark.parametrize("recovered", [False, True])
async def test_multi_write_completion_is_based_on_each_receipt(monkeypatch, recovered):
    results = [("one", "completed"), ("two", "failed")]
    if recovered:
        results.append(("two", "completed"))

    async def stream(*args, **kwargs):
        for index, (request_id, status) in enumerate(results):
            yield {"type": "tool_result", "id": str(index), "name": "update_owner", "ok": True,
                   "content": json.dumps({"status": status, "provenance": {"requestId": request_id}})}
        yield {"type": "done", "text": "全部操作已完成。"}

    monkeypatch.setattr(runner.native_core, "stream_run", stream)
    state = {"run_id": 1, "request": "执行两项操作", "messages": [], "steps": []}
    registry = {"update_owner": {"kind": "enterprise_action", "action": SimpleNamespace(operation="update")}}
    events = []
    await runner._consume_native(state, {"system_prompt": "", "tools": [], "registry": registry},
                                 "run-token", None, events, {})
    if recovered:
        assert not state.get("error")
        assert state["assistant_final"] == "全部操作已完成。"
    else:
        assert "一部分" in state["assistant_final"]
        assert state["error"] == "Some business operations remain incomplete"
    assert len(state["operation_outcomes"]) == 2
