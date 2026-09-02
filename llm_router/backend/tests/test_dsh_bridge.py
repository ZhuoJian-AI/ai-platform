"""Unit contracts for the private Python ↔ DSH bridge."""

import pytest

from app.agents.dsh import runner
from app.agents.graph.nodes import _skill_catalog_prompt
from app.api.dsh_internal import _to_platform_messages, _to_platform_tools


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
