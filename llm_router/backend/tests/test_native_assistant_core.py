"""Focused parity tests for the platform-owned Assistant Core loop."""

from __future__ import annotations

import json

import pytest

from app.agents.core import native
from app.agents.dsh import runner

ORG_ID = "00000000-0000-0000-0000-000000000001"


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
        payload = json.dumps({"status": "success", "file_id": "f1"}, ensure_ascii=False)
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
    assert "invalid_tool_arguments" in result["content"]
    assert "校验失败" in result["content"]


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
        payload = json.dumps({"status": "success", "file_id": "f2"}, ensure_ascii=False)
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


def test_engine_choice_is_server_owned_and_canary_scoped(monkeypatch):
    monkeypatch.setattr(runner.settings, "assistant_engine", "dsh")
    monkeypatch.setattr(runner.settings, "assistant_native_canary_user_ids", "u-1,u-2")
    assert runner._assistant_engine_for_run("u-1") == "native"
    assert runner._assistant_engine_for_run("u-3") == "dsh"
    monkeypatch.setattr(runner.settings, "assistant_engine", "native")
    assert runner._assistant_engine_for_run("any-user") == "native"
