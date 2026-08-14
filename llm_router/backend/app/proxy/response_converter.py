"""API protocol converter — convert between Anthropic and OpenAI response formats.

This allows, for example, an OpenAI-format request to be routed to an Anthropic
provider, and vice versa.
"""

from __future__ import annotations

import time
from typing import Any


def anthropic_to_openai_response(anthropic_resp: dict[str, Any], model: str) -> dict[str, Any]:
    """将 Anthropic /v1/messages 响应转换为 OpenAI /v1/chat/completions 格式。"""
    content_text = ""
    for block in anthropic_resp.get("content", []):
        if block.get("type") == "text":
            content_text += block.get("text", "")

    usage = anthropic_resp.get("usage", {})
    return {
        "id": f"chatcmpl-{anthropic_resp.get('id', '')}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content_text, "tool_calls": None},
                "finish_reason": _map_stop_reason(anthropic_resp.get("stop_reason")),
            }
        ],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        },
    }


def openai_to_anthropic_response(openai_resp: dict[str, Any]) -> dict[str, Any]:
    """将 OpenAI /v1/chat/completions 响应转换为 Anthropic /v1/messages 格式。"""
    choices = openai_resp.get("choices", [])
    content_text = ""
    finish_reason = "end_turn"
    if choices:
        message = choices[0].get("message", {})
        content_text = message.get("content", "")
        finish_reason = _map_finish_reason(choices[0].get("finish_reason"))

    usage = openai_resp.get("usage", {})
    return {
        "id": f"msg-{openai_resp.get('id', '').replace('chatcmpl-', '')}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content_text}],
        "model": openai_resp.get("model", ""),
        "stop_reason": finish_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def _map_stop_reason(reason: str | None) -> str:
    """Anthropic stop_reason → OpenAI finish_reason。"""
    mapping = {
        "end_turn": "stop",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
    }
    return mapping.get(reason or "", "stop")


def _map_finish_reason(reason: str | None) -> str:
    """OpenAI finish_reason → Anthropic stop_reason。"""
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
    }
    return mapping.get(reason or "", "end_turn")
