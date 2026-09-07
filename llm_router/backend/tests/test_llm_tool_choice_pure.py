from types import SimpleNamespace

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
