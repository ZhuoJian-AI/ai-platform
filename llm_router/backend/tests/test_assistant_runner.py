"""Pure coordinator contracts that must survive the DSH retirement."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents import runtime_support
from app.agents.core import runner
from app.agents.graph import run_registry


@pytest.fixture(autouse=True)
def db_engine():
    """These coordinator tests do not require PostgreSQL."""

    yield


@pytest.mark.parametrize("status", ["completed", "needs_confirmation", "unknown", "unverified"])
def test_global_history_retains_recovery_references_without_page_authority(status):
    context = {
        "toolResultRefs": [{"requestId": "original-request", "recoveryState": status}],
        "artifactRefs": [{"fileId": "file", "versionId": "version"}],
        "pageKey": "old-page",
        "roleIds": ["old-role"],
        "filtersSummary": {"private": "unrelated"},
    }
    state = {"messages": [{"role": "assistant", "content": "结果", "business_context": context}]}
    content = runner._history(state)[0]["content"]
    references = json.loads(content.split("\n")[-1])
    assert references == {key: context[key] for key in ("toolResultRefs", "artifactRefs")}
    assert "当前权限校验" in content
    assert "old-role" not in content and "old-page" not in content and "unrelated" not in content
    assert state["messages"][0]["business_context"] == context


def test_global_history_bounds_references_and_preserves_request_deduplication():
    rows = runner._history({
        "request": "继续",
        "messages": [
            {"role": "assistant", "content": "结果", "business_context": {
                "toolResultRefs": [{"requestId": str(i)} for i in range(30)] + [None],
                "artifactRefs": "invalid",
            }},
            {"role": "user", "content": "继续", "business_context": {"pageKey": "old"}},
        ],
    })
    assert len(rows) == 1
    refs = json.loads(rows[0]["content"].split("\n")[-1])
    assert refs == {"toolResultRefs": [{"requestId": str(i)} for i in range(10, 30)]}


def test_page_history_keeps_existing_business_context():
    context = {"pageKey": "page", "entityRefs": [{"entityId": "order"}]}
    rows = runner._history({"application_id": "app", "messages": [
        {"role": "assistant", "content": "结果", "business_context": context},
    ]})
    assert json.loads(rows[0]["content"].split("\n")[-1]) == context


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_non_stream_run_persists_tool_and_terminal_events(monkeypatch, fails):
    state = {"session_id": "session", "run_id": 123, "messages": []}
    monkeypatch.setattr(runner, "general_initial_state", lambda **kw: state)
    monkeypatch.setattr(runner, "general_context", lambda *args: {})
    monkeypatch.setattr(runner, "user_message_metadata", lambda s: {})

    async def prepare(s, deps, writer, **kw):
        writer(json.dumps({"type": "phase", "phase": "prepare"}))
        return {}, ""

    async def admitted(s, deps, prepared, token, handle, staged, user_id):
        staged.append({"type": "tool_result", "name": "image_tool", "ok": not fails})
        if fails:
            raise ValueError("test failure")

    async def finish(s, deps, writer):
        s["assistant_final"] = "完成"
        writer(json.dumps({"type": "assistant_message", "content": "完成"}))

    async def failed(s, deps, exc, writer):
        s["error"] = "test failure"
        s["assistant_final"] = "失败"
        writer(json.dumps({"type": "assistant_message", "content": "失败"}))

    persist = AsyncMock()
    monkeypatch.setattr(runner, "_prepare", prepare)
    monkeypatch.setattr(runner, "_admitted_run", admitted)
    monkeypatch.setattr(runner, "_finish", finish)
    monkeypatch.setattr(runner, "_finish_failed_run", failed)
    monkeypatch.setattr(runner, "persist_run_events", persist)
    db = SimpleNamespace(add=lambda obj: None, commit=AsyncMock())
    result = await runner.run_general_agent(
        org_id="org", user=SimpleNamespace(id="user"), task=SimpleNamespace(id="task"),
        message="识图", config={}, session_id=None, db=db, request=None,
    )
    persist.assert_awaited_once()
    run_id, task_id, events, final = persist.call_args.args
    assert (run_id, task_id) == (123, "task")
    assert [event["type"] for event in events] == ["phase", "tool_result", "assistant_message", "done"]
    assert json.loads(final)["status"] == ("failed" if fails else "completed")
    assert json.loads(final)["content"] == result["assistant"]


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
async def test_successful_auxiliary_query_does_not_hide_a_failed_mutation(monkeypatch):
    state = {
        "run_id": 2,
        "request": "先查询订单再修改负责人",
        "application_id": "app-1",
        "messages": [],
        "steps": [],
        "business_turn_intent": {"intent": "mutate", "operation": "update"},
        "_assistant_tool_registry": {
            "find_order": {"kind": "enterprise_action", "operation": "query"},
            "update_owner": {"kind": "enterprise_action", "operation": "update"},
        },
    }
    await _consume(monkeypatch, [
        {"type": "tool_result", "id": "query", "name": "find_order", "ok": True,
         "content": json.dumps({"status": "completed", "data": {"id": "order-1"}})},
        {"type": "tool_result", "id": "write", "name": "update_owner", "ok": False,
         "content": json.dumps({"status": "failed", "error": {"messageZh": "写入失败"},
                                "result": {"executionOutcome": "unknown"},
                                "provenance": {"requestId": "original-write"}})},
        {"type": "done", "text": "查询和修改都已完成。"},
    ], state)

    assert state["error"] == "Requested business mutation was not completed"
    assert state["assistant_final"].startswith("辅助查询已经成功，但本轮未获得业务操作的成功回执")
    assert "查询和修改都已完成" not in state["assistant_final"]
    execution = state["business_tool_executions"][-1]
    assert execution["requestId"] == "original-write"
    assert execution["executionOutcome"] == "unknown"


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
@pytest.mark.parametrize("specialist_ok", [True, False])
async def test_specialist_analysis_is_not_rejected_for_missing_database_query(monkeypatch, specialist_ok):
    state = {
        "run_id": 14, "request": "识别上传的报告", "application_id": "app-1",
        "messages": [], "steps": [],
        "business_turn_intent": {"intent": "query", "requiresLiveData": True},
        "_assistant_tool_registry": {"specialist": {"kind": "subsystem_specialist"}},
    }
    await _consume(monkeypatch, [
        {"type": "tool_result", "id": "c1", "name": "specialist", "ok": specialist_ok,
         "content": json.dumps({"status": "completed" if specialist_ok else "failed",
                                "data": {"draft": {"style": "204A231"}}})},
        {"type": "done", "text": "上传报告的款号是 204A231。"},
    ], state)
    if specialist_ok:
        assert state.get("error") is None
        assert "204A231" in state["assistant_final"]
    else:
        assert state.get("error")
        assert "204A231" not in state["assistant_final"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["enterprise_action", "enterprise_export_file"])
@pytest.mark.parametrize("status", [
    "error", "pending", "retryable_error", "needs_input", "needs_confirmation", "queued", "running", "cancelled",
])
@pytest.mark.parametrize("recovers", [False, True])
async def test_transport_success_is_not_business_completion(monkeypatch, kind, status, recovers):
    state = {
        "run_id": 15, "request": "查询当前记录", "application_id": "app-1",
        "messages": [], "steps": [],
        "_assistant_tool_registry": {"query": {"kind": kind, "operation": "query"}},
    }
    events = [{"type": "tool_result", "id": "first", "name": "query", "ok": True,
               "content": json.dumps({"status": status})}]
    if recovers:
        events.append({"type": "tool_result", "id": "corrected", "name": "query", "ok": True,
                       "content": json.dumps({"status": "completed", "count": 12})})
    events.append({"type": "done", "text": "当前共有 12 条记录。"})
    await _consume(monkeypatch, events, state)
    if recovers:
        assert state.get("error") is None
        assert "12" in state["assistant_final"]
    else:
        assert state.get("error")
        assert "12" not in state["assistant_final"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [
    "failed", "error", "pending", "retryable_error", "needs_input", "needs_confirmation",
    "queued", "running", "cancelled", "executing", "expired", "rejected", "unknown", "", "success",
])
@pytest.mark.parametrize("recovers", [False, True])
async def test_write_requires_completed_receipt_and_allows_recovery(monkeypatch, status, recovers):
    state = {
        "run_id": 16, "request": "修改订单负责人", "application_id": "app-1",
        "messages": [], "steps": [],
        "_assistant_tool_registry": {"update_order": {"kind": "enterprise_action", "operation": "update"}},
    }
    events = [{"type": "tool_result", "id": "first", "name": "update_order", "ok": True,
               "content": json.dumps({"status": status})}]
    if recovers:
        events.append({"type": "tool_result", "id": "verified", "name": "update_order", "ok": True,
                       "content": json.dumps({"status": "completed"})})
    events.append({"type": "done", "text": "已修改订单负责人。"})
    staged = await _consume(monkeypatch, events, state)
    receipts = [event for event in staged if event.get("type") == "tool_result"]
    assert receipts[0]["business_mutation_committed"] is False
    if recovers:
        assert receipts[1]["business_mutation_committed"] is True
        assert state.get("error") is None
        assert state["assistant_final"] == "已修改订单负责人。"
    else:
        assert "已修改订单负责人" not in state["assistant_final"]
        if status in {"pending", "needs_confirmation"}:
            assert "等待你确认" in state["assistant_final"]
        else:
            assert state.get("error")
            assert "业务数据未被修改" not in state["assistant_final"]


@pytest.mark.asyncio
@pytest.mark.parametrize("specialist_ok,query_ok", [(False, True), (True, False), (True, True), (False, False)])
@pytest.mark.parametrize("fallback", ["none", "same_file", "other_file", "empty"])
async def test_file_analysis_evidence_is_separate_from_auxiliary_query(monkeypatch, specialist_ok, query_ok, fallback):
    state = {
        "run_id": 17, "request": "识别上传报告的款号和数量", "application_id": "app-1",
        "messages": [], "steps": [],
        "business_turn_intent": {"intent": "query", "requiresLiveData": True},
        "_assistant_tool_registry": {
            "specialist": {"kind": "subsystem_specialist"},
            "query": {"kind": "enterprise_action", "operation": "query"},
        },
    }
    events = [
        {"type": "tool_call", "id": "s", "name": "specialist", "arguments": '{"input_file_ids":["source"]}'},
        {"type": "tool_result", "id": "s", "name": "specialist", "ok": specialist_ok,
         "content": json.dumps({"status": "completed" if specialist_ok else "failed",
                                "data": {"draft": {"style": "204A231"}} if specialist_ok else {}})},
        {"type": "tool_result", "id": "q", "name": "query", "ok": query_ok,
         "content": json.dumps({"status": "completed" if query_ok else "failed", "count": 1})},
    ]
    if fallback != "none":
        file_id = "other" if fallback == "other_file" else "source"
        events.extend([
            {"type": "tool_call", "id": "v", "name": "image_tool",
             "arguments": json.dumps({"action": "understand", "input_file_ids": [file_id]})},
            {"type": "tool_result", "id": "v", "name": "image_tool", "ok": True,
             "content": json.dumps({"status": "completed", "data": {
                 "answer": "204A231，100件" if fallback != "empty" else "",
                 "inputFiles": [{"fileId": file_id}],
             }})},
        ])
    events.append({"type": "done", "text": "报告款号为204A231。"})
    await _consume(monkeypatch, events, state)
    if specialist_ok or fallback == "same_file":
        assert state.get("error") is None
        assert "204A231" in state["assistant_final"]
    else:
        assert state.get("error") == "File analysis was not verified by an input-bound tool result"
        assert "204A231" not in state["assistant_final"]


@pytest.mark.asyncio
async def test_empty_success_is_not_misreported_as_max_steps(monkeypatch):
    state = {"run_id": 2, "request": "你好", "messages": [], "steps": []}
    await _consume(monkeypatch, [{"type": "done", "text": ""}], state)

    assert state["error"] == "Assistant Core completed without a final response"
    assert state["assistant_final"] == "模型未返回最终回答，请重试。"


@pytest.mark.asyncio
@pytest.mark.parametrize("intent_name", ["clarify", "navigate"])
async def test_business_routing_hint_never_short_circuits_the_main_llm(monkeypatch, intent_name):
    captured_requests = []

    async def stream_run(request, **_kwargs):
        captured_requests.append(request)
        yield {"type": "done", "text": "主脑已结合当前页面理解并完成回答。"}

    monkeypatch.setattr(runner.native_core, "stream_run", stream_run)
    state = {
        "run_id": 21,
        "request": "调用204A231款资料",
        "application_id": "app-1",
        "business_turn_intent": {
            "intent": intent_name,
            "clarificationQuestion": "分类器认为需要补充信息",
        },
        "messages": [],
        "steps": [],
    }

    await runner._consume_native(
        state,
        {"system_prompt": "结合页面理解用户自然表达", "tools": []},
        "run-token",
        None,
        [],
        {},
    )

    assert len(captured_requests) == 1
    assert captured_requests[0]["message"] == "调用204A231款资料"
    assert state["assistant_final"] == "主脑已结合当前页面理解并完成回答。"
    assert not any(
        step.get("step") in {"awaiting_clarification", "navigation_required"}
        for step in state["steps"]
    )


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
