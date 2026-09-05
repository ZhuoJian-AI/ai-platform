"""Unit contracts for the private Python ↔ DSH bridge."""

import asyncio
from contextvars import Context
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.agents.dsh import client as dsh_client
from app.agents.dsh import runner
from app.agents.graph.nodes import _skill_catalog_prompt
from app.api import dsh_internal
from app.api.dsh_internal import (
    ModelBridgeRequest,
    _to_platform_messages,
    _to_platform_tools,
)
from app.config import settings
from app.services.model_gateway import GatewayError


@pytest.fixture(autouse=True)
def db_engine():
    """These bridge tests are pure and do not require the PostgreSQL fixture."""
    yield


def test_dsh_messages_preserve_tool_protocol_and_current_images():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "分析图片"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "先读取"},
                {"type": "tool-call", "id": "c1", "name": "image_tool", "arguments": "{}"},
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool-result", "toolCallId": "c1",
                    "content": [{"type": "text", "text": "完成"}],
                },
            ],
        },
    ]

    converted = _to_platform_messages(
        messages,
        [{"data_url": "data:image/png;base64,AA==", "detail": "high"}],
    )

    assert converted[0]["content"][0] == {"type": "text", "text": "分析图片"}
    assert converted[0]["content"][1]["image_url"]["url"].startswith("data:image/png")
    assert converted[1]["tool_calls"][0]["function"]["name"] == "image_tool"
    assert converted[2] == {"role": "tool", "tool_call_id": "c1", "content": "完成"}


@pytest.mark.asyncio
async def test_model_bridge_returns_verification_error_before_stream_headers(monkeypatch):
    async def unavailable_model(*_args, **_kwargs):
        raise GatewayError("deployment_not_verified")
        yield  # pragma: no cover - keeps this an async generator

    context = SimpleNamespace(
        db=object(),
        deps={},
        state={"org_id": str(uuid4()), "model_alias": "mimo-v2.5"},
        image_inputs=[],
        provider_override=None,
        model_override=None,
    )
    monkeypatch.setattr(dsh_internal.run_registry, "get", lambda _token: context)
    monkeypatch.setattr(dsh_internal.llm_client, "stream_chat", unavailable_model)

    with pytest.raises(HTTPException) as raised:
        await dsh_internal.model_stream(
            ModelBridgeRequest(run_token="run-token"),
            authorization=f"Bearer {settings.dsh_runtime_token}",
        )

    assert raised.value.status_code == 409
    assert "尚未完成全部能力验证" in raised.value.detail


@pytest.mark.asyncio
async def test_model_bridge_prefetch_keeps_the_first_stream_event(monkeypatch):
    async def available_model(*_args, **_kwargs):
        yield "text", "OK", None
        yield "usage", None, {"input_tokens": 2, "output_tokens": 1}

    context = SimpleNamespace(
        db=object(),
        deps={},
        state={"org_id": str(uuid4()), "model_alias": "compatible-model"},
        image_inputs=[],
        provider_override=None,
        model_override=None,
    )
    monkeypatch.setattr(dsh_internal.run_registry, "get", lambda _token: context)
    monkeypatch.setattr(dsh_internal.llm_client, "stream_chat", available_model)

    response = await dsh_internal.model_stream(
        ModelBridgeRequest(run_token="run-token"),
        authorization=f"Bearer {settings.dsh_runtime_token}",
    )
    chunks = [chunk async for chunk in response.body_iterator]
    body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)

    assert '"type": "block-start"' in body
    assert '"text": "OK"' in body
    assert '"type": "finish"' in body


@pytest.mark.asyncio
async def test_model_bridge_prefetch_can_continue_in_streaming_response_context(monkeypatch):
    async def available_model(*_args, **_kwargs):
        yield "text", "OK", None
        yield "usage", None, {"input_tokens": 2, "output_tokens": 1}

    context = SimpleNamespace(
        db=object(),
        deps={},
        state={"org_id": str(uuid4()), "model_alias": "compatible-model"},
        image_inputs=[],
        provider_override=None,
        model_override=None,
    )
    monkeypatch.setattr(dsh_internal.run_registry, "get", lambda _token: context)
    monkeypatch.setattr(dsh_internal.llm_client, "stream_chat", available_model)

    response = await dsh_internal.model_stream(
        ModelBridgeRequest(run_token="run-token"),
        authorization=f"Bearer {settings.dsh_runtime_token}",
    )

    async def consume_body():
        return [chunk async for chunk in response.body_iterator]

    # Starlette may consume the StreamingResponse body in a fresh task/context
    # after the bridge prefetches its first event in the request task.
    chunks = await asyncio.create_task(consume_body(), context=Context())
    body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)

    assert '"text": "OK"' in body
    assert '"type": "finish"' in body


def test_dsh_tools_convert_to_existing_gateway_schema():
    tools = _to_platform_tools([
        {
            "name": "rag_search", "description": "检索知识库",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
        },
    ])
    assert tools == [{
        "type": "function",
        "function": {
            "name": "rag_search", "description": "检索知识库",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
        },
    }]


def test_dsh_tool_bridge_no_longer_owns_the_identical_failure_guard():
    """A1：相同工具+参数的重复失败拦截已移入 DSH 工具管线，Python 桥不再持有该状态。"""
    for name in ("_identical_failure_blocked", "_record_tool_outcome", "_tool_call_fingerprint"):
        assert not hasattr(dsh_internal, name)


def test_skill_catalog_never_advertises_an_unavailable_load_tool():
    state = {
        "skill_catalog": [
            {
                "id": "skill-1",
                "slug": "bank-process",
                "name": "银行流水处理",
                "scope_type": "user",
                "is_executable": True,
                "description": "处理银行流水",
            }
        ],
    }

    disabled = _skill_catalog_prompt(state, load_skill_available=False)
    enabled = _skill_catalog_prompt(state, load_skill_available=True)

    assert "不得调用或声称已经调用 load_skill" in disabled
    assert "需要说明时调用 load_skill" not in disabled
    assert "需要说明时调用 load_skill" in enabled


@pytest.mark.asyncio
async def test_dsh_client_stops_at_protocol_terminal_event(monkeypatch):
    stream_closed = False
    read_past_terminal = False

    class FakeResponse:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            nonlocal read_past_terminal
            yield '{"type":"done","text":"完成"}'
            read_past_terminal = True
            yield '{"type":"status","status":"late-cleanup"}'

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *_args):
            nonlocal stream_closed
            stream_closed = True

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return FakeStream()

    monkeypatch.setattr(dsh_client.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    events = [event async for event in dsh_client.stream_run({"run_id": "run-1"})]

    assert events == [{"type": "done", "text": "完成"}]
    assert stream_closed is True
    assert read_past_terminal is False


@pytest.mark.asyncio
async def test_failed_tool_without_final_text_is_an_error(monkeypatch):
    async def stream_run(_request):
        yield {"type": "tool_call", "id": "call-1", "name": "load_skill", "arguments": "{}"}
        yield {
            "type": "tool_result",
            "id": "call-1",
            "name": "load_skill",
            "content": 'unknown tool "load_skill"',
            "ok": False,
        }
        yield {"type": "done", "text": "", "steps": 1, "tool_calls": 1}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    state = {"run_id": 1, "request": "处理文件", "messages": [], "steps": []}
    staged: list[dict] = []

    await runner._consume_dsh(
        state,
        {"system_prompt": "", "tools": []},
        "run-token",
        None,
        staged,
    )

    assert "Tool 'load_skill' failed" in state["error"]
    assert "工具执行失败（load_skill）" in state["assistant_final"]
    assert "最大步数" not in state["assistant_final"]


@pytest.mark.asyncio
async def test_skill_file_delivery_runs_once_with_a_runtime_completion_policy(monkeypatch):
    """A1：Python 不再以 ``-continuation`` 重跑；续执行交给 RunRequest.completion_policy 的运行时。"""
    requests: list[dict] = []

    async def stream_run(request):
        requests.append(request)
        yield {"type": "tool_call", "id": "load-1", "name": "load_skill", "arguments": "{}"}
        yield {
            "type": "tool_result", "id": "load-1", "name": "load_skill",
            "content": "loaded", "ok": True,
        }
        yield {"type": "done", "text": "技能已加载。", "steps": 1, "tool_calls": 1}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    state = {
        "run_id": 4, "request": "请使用技能处理附件并生成一份 Excel 表格", "messages": [], "steps": [],
        "exec_mode": "craft", "attachment_files": [{"file_id": "file-1"}],
        "invoked_skill_ids": ["skill-1"], "_dsh_tool_registry": {"bank_flow": {"kind": "code"}},
    }
    staged: list[dict] = []

    await runner._consume_dsh(
        state,
        {"system_prompt": "", "tools": []},
        "run-token",
        None,
        staged,
    )

    assert len(requests) == 1
    assert requests[0]["run_id"] == "4"
    policy = requests[0]["completion_policy"]
    assert set(policy) == {"require_file_output", "file_output_tools", "max_nudges", "nudge_text"}
    assert policy["require_file_output"] is True
    assert policy["max_nudges"] == 1
    assert {"spreadsheet_tool", "run_skill_script", "workspace_write_file", "bank_flow"} <= set(
        policy["file_output_tools"]
    )
    assert "load_skill" not in policy["file_output_tools"]
    # Python no longer judges delivery itself: the runtime's final answer stands as-is.
    assert state.get("error") is None
    assert state["assistant_final"] == "技能已加载。"
    assert not any(step["step"] == "skill_file_delivery_continuation" for step in state["steps"])
    assert not any(event.get("type") == "text_retract" for event in staged)


@pytest.mark.asyncio
async def test_empty_success_without_tools_is_not_reported_as_max_steps(monkeypatch):
    async def stream_run(_request):
        yield {"type": "done", "text": "", "steps": 1, "tool_calls": 0}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    state = {"run_id": 2, "request": "你好", "messages": [], "steps": []}

    await runner._consume_dsh(
        state,
        {"system_prompt": "", "tools": []},
        "run-token",
        None,
        [],
    )

    assert state["error"] == "DSH runtime completed without a final response"
    assert state["assistant_final"] == "模型未返回最终回答，请重试。"


@pytest.mark.asyncio
async def test_max_steps_requires_the_runtime_error_code(monkeypatch):
    async def stream_run(_request):
        yield {
            "type": "error",
            "message": "MAX_STEPS_EXCEEDED",
            "code": "MAX_STEPS_EXCEEDED",
        }

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    state = {"run_id": 3, "request": "循环任务", "messages": [], "steps": []}

    with pytest.raises(runner.DshRunError) as raised:
        await runner._consume_dsh(
            state,
            {"system_prompt": "", "tools": []},
            "run-token",
            None,
            [],
        )

    assert raised.value.code == "MAX_STEPS_EXCEEDED"
    assert runner._public_failure_message(raised.value) == "达到最大步数，未产生最终回答。"


# ── 审计修复（2026-09-03）──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_tool_returns_full_content_not_truncated_preview(monkeypatch):
    """H2：喂给模型的 tool result 必须是完整内容，不能是 4000 字预览。"""
    from contextlib import nullcontext
    from types import SimpleNamespace

    from app.api import dsh_internal
    from app.config import settings

    full = "x" * 12_000
    preview = full[:4000] + "\n[工具结果预览已截断，模型已收到完整分页结果]"

    async def fake_execute(_state, _call, _registry):
        return ({"role": "tool", "tool_call_id": "dsh-list_files", "content": full}, preview, True)

    context = SimpleNamespace(state={}, deps={}, tool_registry={})
    monkeypatch.setattr(dsh_internal.run_registry, "get", lambda _token: context)
    monkeypatch.setattr(dsh_internal, "bind_runtime", lambda _deps: nullcontext())
    monkeypatch.setattr(dsh_internal, "_execute_tool_call", fake_execute)

    result = await dsh_internal.execute_tool(
        dsh_internal.ToolBridgeRequest(run_token="t", name="list_files", arguments={}),
        authorization=f"Bearer {settings.dsh_runtime_token}",
    )

    assert result["ok"] is True
    assert result["content"] == full
    assert result["value"]["content"] == full
    assert len(result["content"]) == 12_000
    assert "已截断" not in result["content"]
    assert result["preview"] == preview


@pytest.mark.asyncio
async def test_model_stream_ends_with_error_finish_when_upstream_raises(monkeypatch):
    """H11：上游 stream_chat 中途抛错，NDJSON 必须以 finish(kind=error) 收口而不是断流。"""
    import json
    from contextlib import nullcontext
    from types import SimpleNamespace
    from uuid import uuid4

    from app.api import dsh_internal
    from app.config import settings

    async def broken_stream_chat(*_args, **_kwargs):
        yield ("text", "前半", None)
        raise RuntimeError("provider exploded")

    context = SimpleNamespace(
        state={"org_id": str(uuid4()), "model_alias": "default"}, deps={}, db=None,
        image_inputs=[], provider_override=None, model_override=None,
    )
    monkeypatch.setattr(dsh_internal.run_registry, "get", lambda _token: context)
    monkeypatch.setattr(dsh_internal, "bind_runtime", lambda _deps: nullcontext())
    monkeypatch.setattr(dsh_internal.llm_client, "stream_chat", broken_stream_chat)

    response = await dsh_internal.model_stream(
        dsh_internal.ModelBridgeRequest(run_token="t", messages=[]),
        authorization=f"Bearer {settings.dsh_runtime_token}",
    )
    lines = []
    async for chunk in response.body_iterator:
        lines.extend(line for line in str(chunk).splitlines() if line.strip())
    events = [json.loads(line) for line in lines]

    assert events[0]["type"] == "block-start"
    assert events[1] == {"type": "text-delta", "index": 0, "text": "前半"}
    last = events[-1]
    assert last["type"] == "finish"
    assert last["reason"]["kind"] == "error"
    assert last["reason"]["failure"]["message"]
    assert last["reason"]["failure"]["code"]
    assert last["reason"]["error"]["message"] == last["reason"]["failure"]["message"]


def test_publish_failure_reply_retracts_partial_text_and_ends_stream():
    """H7：后台流失败时，撤回半截文本、推公开错误文案 + done。"""
    from app.agents.graph import run_registry

    handle = run_registry.RunHandle(task_id="task-h7")
    staged: list[dict] = [
        {"type": "text", "delta": "我先"},
        {"type": "text", "delta": "读取文件"},
    ]
    runner._publish_failure_reply(handle, staged, {"usage": {"input_tokens": 1}}, RuntimeError("boom"))

    assert staged[2] == {"type": "text_retract", "chars": 6}
    assert staged[3] == {"type": "text", "delta": runner._public_failure_message(RuntimeError("boom"))}
    assert staged[4] == {"type": "done", "usage": {"input_tokens": 1}}
    assert len(handle.buffer) == 3  # 三条新事件都进了 live 缓冲


@pytest.mark.asyncio
async def test_finalize_bg_error_publishes_error_event_before_done(monkeypatch):
    """H7：finalize_bg_error 必须把 error 事件投到 live SSE，而不只是写库。"""
    import json
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from app.agents import runtime_support
    from app.agents.graph import run_registry

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
    handle = run_registry.RunHandle(task_id="task-h7-final")

    await runtime_support.finalize_bg_error(
        handle, SimpleNamespace(id="task-h7-final"), 42, "boom", "RuntimeError: boom", "sess", 0.0,
    )

    payloads = [json.loads(item) for item in handle.buffer]
    assert payloads[0] == {"type": "error", "message": "boom"}
    assert payloads[1]["type"] == "final"
    assert handle.done is True
    assert handle.error == "RuntimeError: boom"


def test_unverified_model_error_has_an_actionable_public_message():
    error = runner.DshRunError(
        "当前模型尚未完成全部能力验证，请管理员在“模型提供商”中完成该模型声明的全部能力测试。"
    )

    assert "完成该模型声明的全部能力测试" in runner._public_failure_message(error)
