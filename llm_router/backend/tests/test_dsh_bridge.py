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
    _identical_failure_blocked,
    _record_tool_outcome,
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


def test_dsh_identical_tool_failure_guard_allows_one_retry_then_blocks():
    state: dict = {}
    arguments = {"input_file_ids": ["file-1"], "action": "inspect"}

    assert _identical_failure_blocked(state, "spreadsheet_tool", arguments) is False
    _record_tool_outcome(state, "spreadsheet_tool", arguments, ok=False)
    assert _identical_failure_blocked(state, "spreadsheet_tool", arguments) is False
    _record_tool_outcome(
        state,
        "spreadsheet_tool",
        {"action": "inspect", "input_file_ids": ["file-1"]},
        ok=False,
    )
    assert _identical_failure_blocked(state, "spreadsheet_tool", arguments) is True

    _record_tool_outcome(state, "spreadsheet_tool", arguments, ok=True)
    assert _identical_failure_blocked(state, "spreadsheet_tool", arguments) is False


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
async def test_skill_file_delivery_continues_after_load_only_completion(monkeypatch):
    requests: list[dict] = []

    async def stream_run(request):
        requests.append(request)
        if len(requests) == 1:
            yield {"type": "tool_call", "id": "load-1", "name": "load_skill", "arguments": "{}"}
            yield {
                "type": "tool_result", "id": "load-1", "name": "load_skill",
                "content": "loaded", "ok": True,
            }
            yield {"type": "done", "text": "我先加载技能。", "steps": 1, "tool_calls": 1}
            return
        yield {
            "type": "tool_call", "id": "sheet-1", "name": "spreadsheet_tool",
            "arguments": {"action": "create", "output_name": "output.xlsx"},
        }
        yield {
            "type": "tool_result", "id": "sheet-1", "name": "spreadsheet_tool",
            "content": "output.xlsx", "ok": True,
        }
        yield {"type": "done", "text": "处理完成，文件已生成。", "steps": 1, "tool_calls": 1}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    state = {
        "run_id": 4, "request": "请使用技能处理附件并保存结果", "messages": [], "steps": [],
        "exec_mode": "craft", "attachment_files": [{"file_id": "file-1"}],
        "invoked_skill_ids": ["skill-1"], "_dsh_tool_registry": {},
    }
    staged: list[dict] = []

    await runner._consume_dsh(
        state,
        {"system_prompt": "", "tools": []},
        "run-token",
        None,
        staged,
    )

    assert len(requests) == 2
    assert requests[1]["run_id"] == "4-continuation"
    assert state.get("error") is None
    assert state["assistant_final"] == "处理完成，文件已生成。"
    assert {step["step"] for step in state["steps"]} >= {
        "skill_file_delivery_continuation", "llm_final",
    }
    assert any(event.get("type") == "text_retract" for event in staged)


@pytest.mark.asyncio
async def test_skill_file_delivery_without_output_is_an_error_after_one_continuation(monkeypatch):
    requests: list[dict] = []

    async def stream_run(request):
        requests.append(request)
        yield {"type": "tool_call", "id": f"load-{len(requests)}", "name": "load_skill", "arguments": "{}"}
        yield {
            "type": "tool_result", "id": f"load-{len(requests)}", "name": "load_skill",
            "content": "loaded", "ok": True,
        }
        yield {"type": "done", "text": "技能已加载。", "steps": 1, "tool_calls": 1}

    monkeypatch.setattr(runner.client, "stream_run", stream_run)
    state = {
        "run_id": 5, "request": "请使用技能处理附件并保存结果", "messages": [], "steps": [],
        "exec_mode": "craft", "attachment_files": [{"file_id": "file-1"}],
        "invoked_skill_ids": ["skill-1"], "_dsh_tool_registry": {},
    }

    await runner._consume_dsh(
        state,
        {"system_prompt": "", "tools": []},
        "run-token",
        None,
        [],
    )

    assert len(requests) == 2
    assert state["error"] == "Skill execution completed without producing the requested file"
    assert "未生成用户要求的文件" in state["assistant_final"]


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


def test_unverified_model_error_has_an_actionable_public_message():
    error = runner.DshRunError(
        "当前模型尚未完成全部能力验证，请管理员在“模型提供商”中完成该模型声明的全部能力测试。"
    )

    assert "完成该模型声明的全部能力测试" in runner._public_failure_message(error)
