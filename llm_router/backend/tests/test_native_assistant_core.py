"""Focused parity tests for the platform-owned Assistant Core loop."""

from __future__ import annotations

import json

import pytest

from app.agents.core import native
from app.agents.graph.nodes import _apply_artifact_completion_guard
from app.services.assistant_delivery_policy import explicit_output_formats

ORG_ID = "00000000-0000-0000-0000-000000000001"


def test_confirmation_tool_explains_runtime_card_without_weakening_schema():
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    specs = [
        {"name": "supplier_create", "description": "新增厂商", "input_schema": schema, "approval": "ask"},
        {"name": "supplier_query", "description": "查询厂商", "input_schema": schema},
    ]
    tools = native._platform_tools(specs)
    assert "用户确认前不会执行写入" in tools[0]["function"]["description"]
    assert tools[0]["function"]["parameters"] == schema
    assert tools[1]["function"]["description"] == "查询厂商"


@pytest.mark.parametrize(("request_text", "formats"), [
    ("生成一份MP3音频", {"mp3"}),
    ("请把原来的 XLSX 转成 CSV", {"csv"}),
    ("读取附件 voice.mp3 并分析", set()),
    ("生成一份报告", set()),
    ("生成一份介绍MP3的报告", set()),
    ("create a PDF", {"pdf"}),
])
def test_explicit_output_format_is_not_input_file_routing(request_text, formats):
    assert explicit_output_formats(request_text) == formats


@pytest.mark.parametrize(("mime", "expected"), [("text/plain", False), ("audio/mpeg", True)])
def test_final_guard_requires_requested_audio_format(mime, expected):
    state = {"request": "生成一份MP3音频"}
    artifact = {"fileId": "f1", "versionId": "v1", "mimeType": mime}
    assert _apply_artifact_completion_guard(state, [artifact]) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("corrected", [False, True])
async def test_native_loop_rejects_txt_substitute_for_mp3(monkeypatch, corrected):
    call = {"id": "c1", "name": "report_create", "arguments": '{"rows":[]}'}
    turns = [
        [("tool_calls", [call], None)],
        [("text", "已生成", None)],
    ]
    if corrected:
        turns.append([("tool_calls", [{**call, "id": "c2", "arguments": '{"rows":[{}]}'}], None)])
    turns.append([("text", "已生成", None)])
    monkeypatch.setattr(native.model_gateway, "stream_chat", _scripted_stream(turns))

    async def execute(_state, tool_call, _registry):
        mime = "audio/mpeg" if tool_call["id"] == "c2" else "text/plain"
        content = json.dumps({"artifacts": [{"fileId": tool_call["id"], "versionId": "v1", "mimeType": mime}]})
        return {"content": content}, content, True

    monkeypatch.setattr(native, "_execute_tool_call", execute)
    state = {**_state(), "request": "生成一份MP3音频"}
    events = [event async for event in native.stream_run(
        _request(require_file=True), state=state, prepared=_prepared(), deps={"db": object()},
    )]
    assert any(event.get("action") == "continuation" for event in events)
    assert any(event["type"] == "done" for event in events) is corrected
    if not corrected:
        assert events[-1]["code"] == "ARTIFACT_DELIVERY_FAILED"


@pytest.fixture(autouse=True)
def db_engine():
    """Native coordinator unit tests do not require PostgreSQL."""
    yield


def _request(*, require_file: bool = False, max_steps: int = 8) -> dict:
    return {
        "max_steps": max_steps,
        "tools": [
            {
                "name": "report_create",
                "description": "创建报告",
                "input_schema": {
                    "type": "object",
                    "properties": {"rows": {"type": "array", "items": {"type": "object"}}},
                    "required": ["rows"],
                    "additionalProperties": False,
                },
                "timeout_ms": 1000,
                "max_model_chars": 60_000,
            }
        ],
        "completion_policy": {
            "require_file_output": require_file,
            "file_output_tools": ["report_create"],
            "max_nudges": 1,
            "nudge_text": "请真实生成文件。",
        },
    }


def _state() -> dict:
    return {
        "org_id": ORG_ID,
        "run_id": 7,
        "model_alias": "default",
        "steps": [],
        "traces": [],
        "request": "生成报告",
    }


def _prepared() -> dict:
    return {
        "messages": [{"role": "user", "content": "生成报告"}],
        "system_prompt": "只使用获准工具。",
        "memory_context": "",
        "registry": {"report_create": {"kind": "code"}},
        "provider_override": None,
        "model_override": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("known", [True, False])
async def test_unloaded_batch_never_executes_and_correction_is_bounded(monkeypatch, known):
    request = _request()
    request["lazy_tools"] = [{**request["tools"][0], "name": "deferred"}] if known else []
    request["tools"].append({
        "name": "enterprise_capability_search",
        "input_schema": {"type": "object", "properties": {}},
    })
    calls = [
        {"id": "allowed", "name": "report_create", "arguments": '{"rows":[]}'},
        {"id": "deferred", "name": "deferred", "arguments": "{}"},
    ]
    monkeypatch.setattr(native.model_gateway, "stream_chat", _scripted_stream([
        [("tool_calls", calls, None)] for _ in range(4)
    ]))

    async def forbidden_execute(*args):
        pytest.fail("A rejected batch must not execute any tool")

    monkeypatch.setattr(native, "_execute_tool_call", forbidden_execute)
    events = []
    with pytest.raises(RuntimeError, match="已拒绝执行"):
        async for event in native.stream_run(
            request, state=_state(), prepared=_prepared(), deps={"db": object()},
        ):
            events.append(event)
    traces = [event for event in events if event.get("code") == "tool_not_loaded_or_allowed"]
    assert [event["retryable"] for event in traces] == ([True, True, True, False] if known else [False])


@pytest.mark.asyncio
async def test_discovery_correction_preserves_protocol_and_reasoning(monkeypatch):
    request = _request()
    request["lazy_tools"] = [{**request["tools"][0], "name": "deferred"}]
    request["tools"].append({
        "name": "enterprise_capability_search",
        "input_schema": {"type": "object", "properties": {}},
    })
    turn = 0

    async def model_turn(**kwargs):
        nonlocal turn
        turn += 1
        if turn == 1:
            return "", [{"id": "c1", "name": "deferred", "arguments": "{}"}], {}, "private-test"
        messages = kwargs["messages"]
        assert messages[-2]["reasoning_content"] == "private-test"
        assert messages[-2]["tool_calls"][0]["id"] == messages[-1]["tool_call_id"] == "c1"
        result = json.loads(messages[-1]["content"])
        assert result["status"] == "retryable_error"
        assert result["error"]["retryable"] is True
        assert result["error"]["code"] == "tool_discovery_required"
        assert "enterprise_capability_search" in result["data"]["correctionHint"]
        assert "deferred" not in [tool["function"]["name"] for tool in kwargs["tools"]]
        return "暂未执行。", [], {}, None

    monkeypatch.setattr(native, "_model_turn", model_turn)
    events = [event async for event in native.stream_run(
        request, state=_state(), prepared=_prepared(), deps={"db": object()},
    )]
    assert turn == 2
    assert "private-test" not in json.dumps(events)


def _scripted_stream(turns):
    cursor = {"value": 0}

    def stream_chat(*_args, **_kwargs):
        index = cursor["value"]
        cursor["value"] += 1

        async def events():
            for event in turns[index]:
                yield event

        return events()

    return stream_chat


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_changed_arguments_cannot_bypass_tool_retry_budget(monkeypatch, batch):
    calls = [
        {"id": f"c{i}", "name": "report_create", "arguments": json.dumps({"rows": [{"i": i}]})}
        for i in range(5 if batch else 4)
    ]
    turns = (
        [[("tool_calls", calls, None)]] if batch
        else [[("tool_calls", [call], None)] for call in calls]
    ) + [[("text", "当前工具失败，未生成文件。", None)]]
    scripted = _scripted_stream(turns)
    visible_tools = []
    provider_messages = []

    def stream(*args, **kwargs):
        visible_tools.append([item["function"]["name"] for item in kwargs.get("tools") or []])
        provider_messages.append([dict(item) for item in args[3]])
        return scripted(*args, **kwargs)

    executed = []

    async def execute(_state, call, _registry):
        executed.append(call["id"])
        payload = native._tool_error("upstream_failed", "依赖不可用", retryable=True)
        return {"content": payload}, payload, False

    monkeypatch.setattr(native.model_gateway, "stream_chat", stream)
    monkeypatch.setattr(native, "_execute_tool_call", execute)
    request = _request()
    request["tools"].append({"name": "other_query", "input_schema": {"type": "object"}})
    events = [event async for event in native.stream_run(
        request, state=_state(), prepared=_prepared(), deps={"db": object()},
    )]
    assert executed == ["c0", "c1", "c2", "c3"]
    assert visible_tools[-1] == ["other_query"]
    assert len([e for e in events if e.get("action") == "tool_retry_exhausted"]) == 1
    assert next(e for e in events if e["type"] == "done")["text"] == "当前工具失败，未生成文件。"
    if batch:
        results = [e for e in events if e["type"] == "tool_result"]
        assert len(results) == 5
        assert json.loads(results[-1]["content"])["error"]["code"] == "tool_retry_exhausted"
        replay = provider_messages[-1]
        tool_turn = next(i for i, message in enumerate(replay) if message.get("tool_calls"))
        assert [message["role"] for message in replay[tool_turn + 1:tool_turn + 6]] == ["tool"] * 5


@pytest.mark.asyncio
async def test_third_correction_can_complete_after_three_invalid_calls(monkeypatch):
    arguments = [{}, {"rows": "[]"}, {"rows": 7}, {"rows": []}]
    turns = [[("tool_calls", [{
        "id": f"c{i}", "name": "report_create", "arguments": json.dumps(value),
    }], None)] for i, value in enumerate(arguments)] + [[("text", "文件已交付。", None)]]
    scripted = _scripted_stream(turns)
    received = []

    def stream(*args, **kwargs):
        received.append([dict(message) for message in args[3]])
        return scripted(*args, **kwargs)

    executed = []

    async def execute(_state, call, _registry):
        executed.append(call["id"])
        payload = json.dumps({"file_id": "f1", "version_id": "v1"})
        return {"content": payload}, payload, True

    monkeypatch.setattr(native.model_gateway, "stream_chat", stream)
    monkeypatch.setattr(native, "_execute_tool_call", execute)
    events = [event async for event in native.stream_run(
        _request(require_file=True), state=_state(), prepared=_prepared(), deps={"db": object()},
    )]
    assert executed == ["c3"]
    assert [e["ok"] for e in events if e["type"] == "tool_result"] == [False, False, False, True]
    feedback = [json.loads(m["content"]) for m in received[3] if m["role"] == "tool"]
    assert len(feedback) == 3
    assert all(result["error"]["correctionFields"] for result in feedback)
    assert events[-1]["type"] == "done"
    assert not any(e["type"] == "error" for e in events)


@pytest.mark.asyncio
async def test_timed_out_write_is_not_resent_with_new_arguments(monkeypatch):
    calls = [{"id": f"c{i}", "name": "report_create",
              "arguments": json.dumps({"rows": [{"i": i}]})} for i in range(2)]
    monkeypatch.setattr(native.model_gateway, "stream_chat", _scripted_stream(
        [[("tool_calls", [call], None)] for call in calls]
        + [[("text", "写入结果待核实，未重复提交。", None)]],
    ))
    executed = []

    async def execute(_state, call, _registry):
        executed.append(call["id"])
        raise TimeoutError

    monkeypatch.setattr(native, "_execute_tool_call", execute)
    events = [event async for event in native.stream_run(
        _request(), state=_state(), prepared=_prepared(), deps={"db": object()},
    )]
    assert executed == ["c0"]
    results = [json.loads(e["content"]) for e in events if e["type"] == "tool_result"]
    assert all(r["error"]["code"] == "write_outcome_unknown" for r in results)
    assert all(r["error"]["retryable"] is False for r in results)
    assert all("c0" in r["data"]["correctionHint"] for r in results)


@pytest.mark.asyncio
async def test_success_resets_own_tool_retry_budget(monkeypatch):
    outcomes = [False, False, True, False, False, True]
    turns = [[("tool_calls", [{
        "id": f"c{i}", "name": "report_create",
        "arguments": json.dumps({"rows": [{"i": i}]}),
    }], None)] for i in range(len(outcomes))] + [[("text", "操作完成。", None)]]
    executed = []

    async def execute(_state, call, _registry):
        ok = outcomes[len(executed)]
        executed.append(call["id"])
        payload = json.dumps({"ok": ok})
        return {"content": payload}, payload, ok

    monkeypatch.setattr(native.model_gateway, "stream_chat", _scripted_stream(turns))
    monkeypatch.setattr(native, "_execute_tool_call", execute)
    events = [event async for event in native.stream_run(
        _request(), state=_state(), prepared=_prepared(), deps={"db": object()},
    )]
    assert len(executed) == 6
    assert not any(e.get("action") == "tool_retry_exhausted" for e in events)


@pytest.mark.asyncio
async def test_native_core_executes_authorized_tool_and_preserves_event_contract(monkeypatch):
    monkeypatch.setattr(
        native.model_gateway,
        "stream_chat",
        _scripted_stream(
            [
                [("tool_calls", [{"id": "c1", "name": "report_create", "arguments": '{"rows":[]}'}], None)],
                [("text", "文件已生成。", None), ("usage", None, {"input_tokens": 2, "output_tokens": 3})],
            ]
        ),
    )
    calls = []

    async def execute(state, call, registry):
        calls.append((state, call, registry))
        payload = json.dumps({"status": "success", "file_id": "f1"}, ensure_ascii=False)
        return {"role": "tool", "tool_call_id": call["id"], "content": payload}, payload, True

    monkeypatch.setattr(native, "_execute_tool_call", execute)
    events = [
        event
        async for event in native.stream_run(
            _request(), state=_state(), prepared=_prepared(), deps={"db": object()}
        )
    ]

    assert len(calls) == 1
    assert next(item for item in events if item["type"] == "tool_result")["ok"] is True
    assert next(item for item in events if item["type"] == "done")["text"] == "文件已生成。"
    assert sum(item.get("input_tokens", 0) for item in events if item["type"] == "usage") == 2


@pytest.mark.asyncio
async def test_native_core_passes_reasoning_content_back_with_tool_call(monkeypatch):
    """MiMo thinking-mode tool turns require verbatim reasoning pass-through."""

    provider_messages: list[list[dict]] = []
    turns = [
        [
            ("reasoning_content", "先定位并调用报表工具。", None),
            ("tool_calls", [{"id": "c1", "name": "report_create", "arguments": '{"rows":[]}'}], None),
        ],
        [("text", "文件已生成。", None)],
    ]
    cursor = {"value": 0}

    def stream_chat(*_args, **kwargs):
        messages = kwargs.get("messages") or (_args[3] if len(_args) > 3 else [])
        provider_messages.append([dict(item) for item in messages])
        index = cursor["value"]
        cursor["value"] += 1

        async def events():
            for event in turns[index]:
                yield event

        return events()

    async def execute(_state, call, _registry):
        payload = json.dumps({"status": "completed", "data": {"rows": []}}, ensure_ascii=False)
        return {"role": "tool", "tool_call_id": call["id"], "content": payload}, payload, True

    monkeypatch.setattr(native.model_gateway, "stream_chat", stream_chat)
    monkeypatch.setattr(native, "_execute_tool_call", execute)

    events = [
        event
        async for event in native.stream_run(
            _request(), state=_state(), prepared=_prepared(), deps={"db": object()}
        )
    ]

    assert len(provider_messages) == 2, events
    assistant_turn = provider_messages[1][-2]
    assert assistant_turn["role"] == "assistant"
    assert assistant_turn["reasoning_content"] == "先定位并调用报表工具。"
    assert assistant_turn["tool_calls"][0]["id"] == "c1"
    assert next(item for item in events if item["type"] == "done")["text"] == "文件已生成。"


def test_model_messages_preserves_reasoning_only_as_provider_metadata():
    messages = native._model_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "完整思考续传",
                "tool_calls": [],
                "platform_annotation": "不得发送",
            }
        ]
    )

    assert messages == [
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "完整思考续传",
            "tool_calls": [],
        }
    ]


@pytest.mark.asyncio
async def test_native_core_reuses_duplicate_side_effect_in_one_model_turn(monkeypatch):
    monkeypatch.setattr(
        native.model_gateway,
        "stream_chat",
        _scripted_stream(
            [
                [
                    (
                        "tool_calls",
                        [
                            {"id": "c1", "name": "report_create", "arguments": '{"rows":[]}'},
                            {"id": "c2", "name": "report_create", "arguments": '{"rows":[]}'},
                        ],
                        None,
                    )
                ],
                [("text", "文件已生成。", None)],
            ]
        ),
    )
    calls = []

    async def execute(_state, call, _registry):
        calls.append(call["id"])
        payload = json.dumps(
            {"status": "success", "file_id": "f1", "version_id": "v1"},
            ensure_ascii=False,
        )
        return {"role": "tool", "tool_call_id": call["id"], "content": payload}, payload, True

    monkeypatch.setattr(native, "_execute_tool_call", execute)
    events = [
        event
        async for event in native.stream_run(
            _request(require_file=True), state=_state(), prepared=_prepared(), deps={"db": object()}
        )
    ]

    assert calls == ["c1"]
    results = [item for item in events if item["type"] == "tool_result"]
    assert [item["id"] for item in results] == ["c1", "c2"]
    assert results[0]["content"] == results[1]["content"]
    assert any(item.get("action") == "duplicate_side_effect_reused" for item in events)
    assert next(item for item in events if item["type"] == "done")["text"] == "文件已生成。"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status": "completed", "artifacts": [{"fileId": "f1", "versionId": "v1"}]}, True),
        ({"status": "success", "outputs": [{"file_id": "f1", "version_id": "v1"}]}, True),
        ({"status": "success", "file_id": "f1", "version_id": "v1"}, True),
        ({"status": "success", "path": "/tmp/report.xlsx"}, False),
        ({"status": "success", "url": "https://example.invalid/report.xlsx"}, False),
        ({"status": "success", "file_id": "f1"}, False),
        ("文件已生成", False),
    ],
)
def test_file_delivery_requires_a_stable_workspace_artifact_identity(payload, expected):
    content = payload if isinstance(payload, str) else json.dumps(payload)
    assert native._tool_result_has_trusted_artifact(content) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("max_nudges", [0, 1, 2])
async def test_file_request_never_finishes_successfully_without_delivery(monkeypatch, max_nudges):
    monkeypatch.setattr(
        native.model_gateway, "stream_chat",
        _scripted_stream([[("text", "文件已生成。", None)]] * (max_nudges + 1)),
    )
    request = _request(require_file=True)
    request["completion_policy"]["max_nudges"] = max_nudges
    events = [event async for event in native.stream_run(
        request, state=_state(), prepared=_prepared(), deps={"db": object()},
    )]
    assert sum(event.get("action") == "continuation" for event in events) == max_nudges
    assert not any(event["type"] == "done" for event in events)
    assert events[-1]["code"] == "ARTIFACT_DELIVERY_FAILED"


@pytest.mark.asyncio
async def test_native_core_nudges_when_file_tool_returns_only_a_server_path(monkeypatch):
    monkeypatch.setattr(
        native.model_gateway,
        "stream_chat",
        _scripted_stream(
            [
                [("tool_calls", [{"id": "c1", "name": "report_create", "arguments": '{"rows":[]}'}], None)],
                [("text", "文件已经生成。", None)],
                [("text", "文件生成失败，未交付到工作空间。", None)],
            ]
        ),
    )

    async def execute(_state, call, _registry):
        payload = json.dumps({"status": "success", "path": "/tmp/report.xlsx"})
        return {"role": "tool", "tool_call_id": call["id"], "content": payload}, payload, True

    monkeypatch.setattr(native, "_execute_tool_call", execute)
    events = [
        event
        async for event in native.stream_run(
            _request(require_file=True), state=_state(), prepared=_prepared(), deps={"db": object()}
        )
    ]

    assert any(item.get("action") == "continuation" for item in events)
    assert not any(item["type"] == "done" for item in events)
    assert next(item for item in events if item["type"] == "error")["code"] == "ARTIFACT_DELIVERY_FAILED"


@pytest.mark.asyncio
async def test_native_core_rejects_json_string_for_array_field_before_execution(monkeypatch):
    monkeypatch.setattr(
        native.model_gateway,
        "stream_chat",
        _scripted_stream(
            [
                [("tool_calls", [{"id": "c1", "name": "report_create", "arguments": '{"rows":"[]"}'}], None)],
                [("text", "参数错误，未生成文件。", None)],
            ]
        ),
    )

    async def must_not_execute(*_args, **_kwargs):
        raise AssertionError("invalid arguments reached the executor")

    monkeypatch.setattr(native, "_execute_tool_call", must_not_execute)
    events = [
        event
        async for event in native.stream_run(
            _request(), state=_state(), prepared=_prepared(), deps={"db": object()}
        )
    ]
    result = next(item for item in events if item["type"] == "tool_result")
    assert result["ok"] is False
    envelope = json.loads(result["content"])
    assert envelope["status"] == "retryable_error"
    assert envelope["error"]["code"] == "invalid_tool_arguments"
    assert "校验失败" in envelope["error"]["messageZh"]
    assert envelope["error"]["correctionFields"][0]["field"] == "rows"


@pytest.mark.asyncio
@pytest.mark.parametrize("premature_calls", [0, 1, 2])
async def test_native_core_discovers_then_loads_and_calls_a_lazy_tool(monkeypatch, premature_calls):
    provider_tools: list[list[str]] = []
    turns = [
        [
            (
                "tool_calls",
                [
                    {
                        "id": "search-1",
                        "name": "enterprise_capability_search",
                        "arguments": '{"query":"根据订单数据生成 Excel"}',
                    }
                ],
                None,
            )
        ],
        [
            (
                "tool_calls",
                [
                    {
                        "id": "file-1",
                        "name": "report_create",
                        "arguments": '{"rows":[]}',
                    }
                ],
                None,
            )
        ],
        [("text", "文件已经保存到工作空间。", None)],
    ]
    turns[:0] = [
        [("tool_calls", [{"id": f"early-{i}", "name": "report_create", "arguments": '{"rows":[]}'}], None)]
        for i in range(premature_calls)
    ]
    cursor = {"value": 0}

    def stream_chat(*_args, **kwargs):
        provider_tools.append(
            [
                item["function"]["name"]
                for item in (kwargs.get("tools") or [])
            ]
        )
        index = cursor["value"]
        cursor["value"] += 1

        async def events():
            for event in turns[index]:
                yield event

        return events()

    monkeypatch.setattr(native.model_gateway, "stream_chat", stream_chat)
    executed: list[str] = []

    async def execute(_state, call, _registry):
        executed.append(call["name"])
        payload = json.dumps(
            {"status": "completed", "artifacts": [{"fileId": "f1", "versionId": "v1"}]},
            ensure_ascii=False,
        )
        return {"role": "tool", "tool_call_id": call["id"], "content": payload}, payload, True

    monkeypatch.setattr(native, "_execute_tool_call", execute)
    request = _request(require_file=True)
    report_spec = request["tools"][0]
    request["tools"] = [
        {
            "name": "enterprise_capability_search",
            "description": "搜索当前角色可用能力",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 12},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        }
    ]
    request["lazy_tools"] = [
        {
            **report_spec,
            "description": "根据订单数据生成 Excel 工作簿并保存到工作空间",
            "search_terms": ["订单", "Excel", "表格"],
        }
    ]
    prepared = _prepared()
    prepared["registry"]["enterprise_capability_search"] = {
        "kind": "assistant_capability_search"
    }

    events = [
        event
        async for event in native.stream_run(
            request,
            state=_state(),
            prepared=prepared,
            deps={"db": object()},
        )
    ]

    assert executed == ["report_create"]
    assert provider_tools[0] == ["enterprise_capability_search"]
    assert all("report_create" not in tools for tools in provider_tools[:premature_calls + 1])
    assert "report_create" in provider_tools[premature_calls + 1]
    activation = next(item for item in events if item.get("action") == "tool_catalog_loaded")
    assert activation["activatedTools"] == ["report_create"]
    assert activation["visibleTools"] == sorted(provider_tools[premature_calls + 1])
    search_result = next(
        item
        for item in events
        if item["type"] == "tool_result" and item["name"] == "enterprise_capability_search"
    )
    assert json.loads(search_result["content"])["data"]["activatedTools"] == ["report_create"]
    assert next(item for item in events if item["type"] == "done")["text"] == "文件已经保存到工作空间。"


@pytest.mark.asyncio
async def test_native_core_nudges_until_a_real_file_tool_succeeds(monkeypatch):
    monkeypatch.setattr(
        native.model_gateway,
        "stream_chat",
        _scripted_stream(
            [
                [("text", "我已经整理好了。", None)],
                [("tool_calls", [{"id": "c2", "name": "report_create", "arguments": '{"rows":[]}'}], None)],
                [("text", "文件已保存到个人空间。", None)],
            ]
        ),
    )

    async def execute(_state, call, _registry):
        payload = json.dumps({"status": "success", "file_id": "f2", "version_id": "v2"}, ensure_ascii=False)
        return {"role": "tool", "tool_call_id": call["id"], "content": payload}, payload, True

    monkeypatch.setattr(native, "_execute_tool_call", execute)
    events = [
        event
        async for event in native.stream_run(
            _request(require_file=True), state=_state(), prepared=_prepared(), deps={"db": object()}
        )
    ]
    assert any(item.get("action") == "continuation" for item in events)
    assert next(item for item in events if item["type"] == "done")["text"] == "文件已保存到个人空间。"
