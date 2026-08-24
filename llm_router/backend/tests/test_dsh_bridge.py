"""Unit contracts for the private Python ↔ DSH bridge."""

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
