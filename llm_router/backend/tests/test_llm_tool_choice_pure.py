import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.agents import llm_client


@pytest.fixture(autouse=True)
def db_engine():
    """This protocol-shaping test is pure and must not require PostgreSQL."""

    yield None


def test_chat_body_forces_one_named_tool_for_openai_and_anthropic():
    tool = {
        "type": "function",
        "function": {
            "name": "classify_business_turn",
            "description": "classify",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    openai_provider = SimpleNamespace(provider_type="openai", vendor="custom", config={})
    openai_body = llm_client._build_chat_body(
        openai_provider,
        "model",
        [{"role": "user", "content": "test"}],
        "",
        0,
        100,
        [tool],
        False,
        "classify_business_turn",
    )
    assert openai_body["tool_choice"] == {
        "type": "function",
        "function": {"name": "classify_business_turn"},
    }

    anthropic_provider = SimpleNamespace(provider_type="anthropic", vendor="anthropic", config={})
    anthropic_body = llm_client._build_chat_body(
        anthropic_provider,
        "model",
        [{"role": "user", "content": "test"}],
        "",
        0,
        100,
        [tool],
        False,
        "classify_business_turn",
    )
    assert anthropic_body["tool_choice"] == {
        "type": "tool",
        "name": "classify_business_turn",
    }

    with pytest.raises(ValueError, match="available tool"):
        llm_client._build_chat_body(
            openai_provider,
            "model",
            [{"role": "user", "content": "test"}],
            "",
            0,
            100,
            [tool],
            False,
            "missing_tool",
        )


@pytest.mark.asyncio
async def test_chat_retries_without_forced_tool_choice_when_reasoning_mode_rejects_it(monkeypatch):
    tool = {
        "type": "function",
        "function": {
            "name": "classify_business_turn",
            "description": "classify",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    provider = SimpleNamespace(
        id=uuid4(),
        provider_type="openai",
        vendor="deepseek",
        config={},
        base_url="https://api.deepseek.test/v1",
        timeout_seconds=30,
    )
    request_bodies: list[dict] = []

    async def fake_key(_provider):
        return "secret"

    async def handler(request: httpx.Request) -> httpx.Response:
        request_bodies.append(json.loads(request.content))
        if len(request_bodies) == 1:
            return httpx.Response(
                400,
                json={"error": {"message": "Thinking mode does not support this tool_choice"}},
            )
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "content": "",
                        "tool_calls": [{
                            "id": "call-1",
                            "function": {"name": "classify_business_turn", "arguments": "{}"},
                        }],
                    },
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(llm_client, "get_decrypted_api_key", fake_key)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", fake_client)

    result = await llm_client.chat(
        None,
        uuid4(),
        "deepseek-v4-flash",
        [{"role": "user", "content": "classify"}],
        tools=[tool],
        tool_choice="classify_business_turn",
        provider_override=provider,
        model_override="deepseek-v4-flash",
    )

    assert len(request_bodies) == 2
    assert request_bodies[0]["tool_choice"]["function"]["name"] == "classify_business_turn"
    assert "tool_choice" not in request_bodies[1]
    assert result.tool_calls[0]["name"] == "classify_business_turn"
