"""Pure coordinator contracts that must survive the DSH retirement."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.agents import runtime_support
from app.agents.core import runner
from app.agents.graph import run_registry


@pytest.fixture(autouse=True)
def db_engine():
    """These coordinator tests do not require PostgreSQL."""

    yield


async def _consume(monkeypatch, events, state):
    async def stream_run(_request, **_kwargs):
        for event in events:
            yield event

    monkeypatch.setattr(runner.native_core, "stream_run", stream_run)
    staged: list[dict] = []
    await runner._consume_native(
        state,
        {"system_prompt": "", "tools": []},
        "run-token",
        None,
        staged,
        {},
    )
    return staged


@pytest.mark.asyncio
async def test_failed_tool_without_final_text_is_reported_as_the_tool_failure(monkeypatch):
    state = {"run_id": 1, "request": "处理文件", "messages": [], "steps": []}
    await _consume(
        monkeypatch,
        [
            {"type": "tool_call", "id": "call-1", "name": "unknown_tool", "arguments": "{}"},
            {
                "type": "tool_result",
                "id": "call-1",
                "name": "unknown_tool",
                "content": 'unknown tool "unknown_tool"',
                "ok": False,
            },
            {"type": "done", "text": ""},
        ],
        state,
    )

    assert "Tool 'unknown_tool' failed" in state["error"]
    assert "工具执行失败（unknown_tool）" in state["assistant_final"]
    assert "最大步数" not in state["assistant_final"]


@pytest.mark.asyncio
async def test_current_business_data_fails_closed_when_page_action_fails(monkeypatch):
    state = {
        "run_id": 11,
        "request": "查询当前页面共有多少条记录",
        "application_id": "app-1",
        "messages": [],
        "steps": [],
        "_assistant_tool_registry": {"current_page_query": {"kind": "enterprise_action"}},
    }
    staged = await _consume(
        monkeypatch,
        [
            {"type": "tool_call", "id": "call-1", "name": "current_page_query", "arguments": "{}"},
            {
                "type": "tool_result",
                "id": "call-1",
                "name": "current_page_query",
                "content": "Bad Gateway",
                "ok": False,
            },
            {"type": "done", "text": "根据历史记录，当前共有 74 条。"},
        ],
        state,
    )

    assert state["assistant_final"] == "本轮实时业务查询没有成功返回，因此暂时无法确认当前数据。请稍后重试。"
    assert "74" not in state["assistant_final"]
    assert state["error"] == "Current business data was not verified by a successful enterprise Action"
    assert any(event.get("type") == "text_retract" for event in staged)


@pytest.mark.asyncio
async def test_current_business_data_accepts_a_successful_page_action(monkeypatch):
    state = {
        "run_id": 12,
        "request": "查询当前页面共有多少条记录",
        "application_id": "app-1",
        "messages": [],
        "steps": [],
        "_assistant_tool_registry": {"current_page_query": {"kind": "enterprise_action"}},
    }
    await _consume(
        monkeypatch,
        [
            {"type": "tool_call", "id": "call-1", "name": "current_page_query", "arguments": "{}"},
            {
                "type": "tool_result",
                "id": "call-1",
                "name": "current_page_query",
                "content": '{"count":12}',
                "ok": True,
            },
            {"type": "done", "text": "当前共有 12 条记录。"},
        ],
        state,
    )

    assert state["assistant_final"] == "当前共有 12 条记录。"
    assert state.get("error") is None


@pytest.mark.asyncio
async def test_current_business_export_accepts_a_successful_composite_file_tool(monkeypatch):
    state = {
        "run_id": 13,
        "request": "根据当前业务数据生成一份 Excel，保存到个人空间",
        "application_id": "app-1",
        "messages": [],
        "steps": [],
        "_assistant_tool_registry": {
            "current_page_export_file": {"kind": "enterprise_export_file", "operation": "export"},
        },
    }
    await _consume(
        monkeypatch,
        [
            {
                "type": "tool_call",
                "id": "call-1",
                "name": "current_page_export_file",
                "arguments": '{"target_format":"xlsx"}',
            },
            {
                "type": "tool_result",
                "id": "call-1",
                "name": "current_page_export_file",
                "content": '{"status":"success","outputs":[{"file_id":"file-1"}]}',
                "ok": True,
            },
            {"type": "done", "text": "已生成当前业务数据 Excel。"},
        ],
        state,
    )

    assert state["assistant_final"] == "已生成当前业务数据 Excel。"
    assert state.get("error") is None


@pytest.mark.asyncio
async def test_empty_success_is_not_misreported_as_max_steps(monkeypatch):
    state = {"run_id": 2, "request": "你好", "messages": [], "steps": []}
    await _consume(monkeypatch, [{"type": "done", "text": ""}], state)

    assert state["error"] == "Assistant Core completed without a final response"
    assert state["assistant_final"] == "模型未返回最终回答，请重试。"


@pytest.mark.asyncio
async def test_max_steps_uses_the_structured_error_code(monkeypatch):
    async def stream_run(_request, **_kwargs):
        yield {"type": "error", "message": "MAX_STEPS_EXCEEDED", "code": "MAX_STEPS_EXCEEDED"}

    monkeypatch.setattr(runner.native_core, "stream_run", stream_run)
    state = {"run_id": 3, "request": "循环任务", "messages": [], "steps": []}
    with pytest.raises(runner.AssistantRunError) as raised:
        await runner._consume_native(
            state,
            {"system_prompt": "", "tools": []},
            "run-token",
            None,
            [],
            {},
        )

    assert raised.value.code == "MAX_STEPS_EXCEEDED"
    assert runner._public_failure_message(raised.value) == "达到最大步数，未产生最终回答。"


def test_publish_failure_reply_retracts_partial_text_before_persisted_done():
    handle = run_registry.RunHandle(task_id="task-failure")
    staged = [{"type": "text", "delta": "我先"}, {"type": "text", "delta": "读取文件"}]
    runner._publish_failure_reply(handle, staged, {}, RuntimeError("boom"))

    assert staged[2] == {"type": "text_retract", "chars": 6}
    assert staged[3] == {"type": "text", "delta": runner._public_failure_message(RuntimeError("boom"))}
    assert len(handle.buffer) == 2


@pytest.mark.asyncio
async def test_finalize_bg_error_publishes_error_before_done(monkeypatch):
    class FakeDb:
        async def get(self, *_args):
            return None

        def add(self, _row):
            return None

        async def commit(self):
            return None

    @asynccontextmanager
    async def fake_session_factory():
        yield FakeDb()

    monkeypatch.setattr(runtime_support, "async_session_factory", fake_session_factory)
    handle = run_registry.RunHandle(task_id="task-finalize")
    await runtime_support.finalize_bg_error(
        handle,
        SimpleNamespace(id="task-finalize"),
        42,
        "boom",
        "RuntimeError: boom",
        "sess",
        0.0,
    )

    import json

    payloads = [json.loads(item) for item in handle.buffer]
    assert payloads[0] == {"type": "error", "message": "boom"}
    assert payloads[1]["type"] == "final"
    assert handle.done is True


@pytest.mark.asyncio
async def test_early_prepare_failure_persists_a_public_assistant_message(monkeypatch):
    added = []

    class FakeDb:
        def add(self, row):
            added.append(row)

        async def commit(self):
            return None

    @asynccontextmanager
    async def fake_session_factory():
        yield FakeDb()

    monkeypatch.setattr(runner, "async_session_factory", fake_session_factory)
    state = {"messages": [], "steps": [], "page_context": {"page_key": "progress_dashboard.main"}}
    message_id = await runner._persist_early_failure_reply(
        state,
        SimpleNamespace(id="f5fdbb35-b6b9-4223-932a-5f88cc0239fb"),
        RuntimeError("upstream secret detail"),
    )

    assert message_id
    assert len(added) == 1
    assert added[0].content == "智能体暂时无法完成本次请求，请稍后重试。"
    assert "upstream secret detail" not in added[0].content


def test_unverified_model_error_has_an_actionable_public_message():
    error = runner.AssistantRunError(
        "当前模型尚未完成全部能力验证，请管理员在“模型提供商”中完成该模型声明的全部能力测试。",
    )
    assert "完成该模型声明的全部能力测试" in runner._public_failure_message(error)
