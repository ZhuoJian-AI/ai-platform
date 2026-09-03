"""Private callbacks consumed only by the internal DSH Runtime container."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from app.agents.dsh import registry as run_registry
from app.agents.graph.context import bind_runtime
from app.agents.graph.nodes import _execute_tool_call
from app.config import settings
from app.services import model_gateway as llm_client

router = APIRouter(prefix="/internal/dsh")


class ModelBridgeRequest(BaseModel):
    run_token: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    system_prompt: str | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    temperature: float | None = None
    max_tokens: int | None = None


class ToolBridgeRequest(BaseModel):
    run_token: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


_IDENTICAL_TOOL_FAILURE_LIMIT = 2


def _tool_call_fingerprint(name: str, arguments: dict[str, Any]) -> str:
    normalized = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{name}\0{normalized}".encode()).hexdigest()


def _identical_failure_blocked(state: dict[str, Any], name: str, arguments: dict[str, Any]) -> bool:
    fingerprint = _tool_call_fingerprint(name, arguments)
    return (
        state.get("_dsh_last_failed_tool_fingerprint") == fingerprint
        and int(state.get("_dsh_consecutive_tool_failures") or 0) >= _IDENTICAL_TOOL_FAILURE_LIMIT
    )


def _record_tool_outcome(
    state: dict[str, Any], name: str, arguments: dict[str, Any], *, ok: bool,
) -> None:
    if ok:
        state.pop("_dsh_last_failed_tool_fingerprint", None)
        state.pop("_dsh_consecutive_tool_failures", None)
        return
    fingerprint = _tool_call_fingerprint(name, arguments)
    previous = int(state.get("_dsh_consecutive_tool_failures") or 0)
    state["_dsh_consecutive_tool_failures"] = (
        previous + 1 if state.get("_dsh_last_failed_tool_fingerprint") == fingerprint else 1
    )
    state["_dsh_last_failed_tool_fingerprint"] = fingerprint


def _require_service(authorization: str | None) -> None:
    expected = f"Bearer {settings.dsh_runtime_token}"
    if not authorization or authorization != expected:
        raise HTTPException(status_code=401, detail="invalid DSH service token")


def _text(blocks: list[dict[str, Any]]) -> str:
    return "".join(str(block.get("text") or "") for block in blocks if block.get("type") == "text")


def _to_platform_messages(
    messages: list[dict[str, Any]], image_inputs: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        blocks = message.get("content") if isinstance(message.get("content"), list) else []
        if role == "assistant":
            tool_calls = []
            reasoning_content = ""
            for block in blocks:
                if block.get("type") == "reasoning":
                    reasoning_content += str(block.get("text") or "")
                if block.get("type") == "tool-call":
                    tool_calls.append({
                        "id": str(block.get("id") or ""), "type": "function",
                        "function": {
                            "name": str(block.get("name") or ""),
                            "arguments": str(block.get("arguments") or "{}"),
                        },
                    })
            row: dict[str, Any] = {"role": "assistant", "content": _text(blocks)}
            if tool_calls:
                row["tool_calls"] = tool_calls
            if reasoning_content:
                row["reasoning_content"] = reasoning_content
            converted.append(row)
            continue
        result_blocks = [block for block in blocks if block.get("type") == "tool-result"]
        if result_blocks:
            for block in result_blocks:
                nested = block.get("content") if isinstance(block.get("content"), list) else []
                converted.append({
                    "role": "tool", "tool_call_id": str(block.get("toolCallId") or ""),
                    "content": _text(nested),
                })
        elif role == "user":
            converted.append({"role": "user", "content": _text(blocks)})
    images = list(image_inputs or [])
    if images:
        for message in reversed(converted):
            if message.get("role") != "user":
                continue
            original = message.get("content", "")
            message["content"] = [
                {"type": "text", "text": original if isinstance(original, str) else ""},
                *[
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image.get("data_url", ""),
                            "detail": image.get("detail", "auto"),
                        },
                    }
                    for image in images if image.get("data_url")
                ],
            ]
            break
    return converted


def _to_platform_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "type": "function",
        "function": {
            "name": str(tool.get("name") or ""),
            "description": str(tool.get("description") or ""),
            "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
        },
    } for tool in tools]


@router.post("/model/stream")
async def model_stream(
    body: ModelBridgeRequest, authorization: str | None = Header(default=None),
) -> StreamingResponse:
    _require_service(authorization)
    context = run_registry.get(body.run_token)
    if context is None:
        raise HTTPException(status_code=401, detail="expired run token")

    async def events():
        messages = _to_platform_messages(body.messages, context.image_inputs)
        tools = _to_platform_tools(body.tools)
        text = ""
        text_started = False
        next_index = 0
        usage = {"input_tokens": 0, "output_tokens": 0}
        tool_calls: list[dict[str, Any]] = []
        reasoning_content = ""
        with bind_runtime(context.deps):
            async for kind, payload, extra in llm_client.stream_chat(
                context.db, UUID(context.state["org_id"]),
                context.state.get("model_alias", "default"), messages,
                system_prompt=body.system_prompt or "",
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                tools=tools or None,
                dept_id=context.state.get("department_id"),
                team_id=context.state.get("team_id"),
                provider_override=context.provider_override,
                model_override=context.model_override,
            ):
                if kind == "text":
                    if not text_started:
                        text_started = True
                        yield json.dumps({"type": "block-start", "index": next_index, "blockType": "text"}) + "\n"
                    text += str(payload)
                    yield json.dumps(
                        {"type": "text-delta", "index": next_index, "text": str(payload)},
                        ensure_ascii=False,
                    ) + "\n"
                elif kind == "tool_calls":
                    tool_calls = list(payload or [])
                elif kind == "reasoning_content":
                    reasoning_content += str(payload or "")
                elif kind == "usage" and extra:
                    usage["input_tokens"] += int(extra.get("input_tokens") or 0)
                    usage["output_tokens"] += int(extra.get("output_tokens") or 0)
            # A few OpenAI-compatible providers omit tool calls from their SSE
            # stream even though the same response is present in non-streaming
            # mode.  Keep the existing platform fallback so switching the
            # coordinator to DSH does not silently remove tool capability.
            if not text and not tool_calls:
                result = await llm_client.chat(
                    context.db, UUID(context.state["org_id"]),
                    context.state.get("model_alias", "default"), messages,
                    system_prompt=body.system_prompt or "",
                    temperature=body.temperature,
                    max_tokens=body.max_tokens,
                    tools=tools or None,
                    dept_id=context.state.get("department_id"),
                    team_id=context.state.get("team_id"),
                    provider_override=context.provider_override,
                    model_override=context.model_override,
                )
                text = result.content or ""
                tool_calls = list(result.tool_calls or [])
                reasoning_content = result.reasoning_content or ""
                usage["input_tokens"] += int(result.usage.get("input_tokens") or 0)
                usage["output_tokens"] += int(result.usage.get("output_tokens") or 0)
                if text:
                    text_started = True
                    yield json.dumps({
                        "type": "block-start", "index": next_index, "blockType": "text",
                    }) + "\n"
                    yield json.dumps({
                        "type": "text-delta", "index": next_index, "text": text,
                    }, ensure_ascii=False) + "\n"
        if text_started:
            yield json.dumps({
                "type": "block-end", "index": next_index,
                "block": {"type": "text", "text": text},
            }, ensure_ascii=False) + "\n"
            next_index += 1
        if reasoning_content:
            yield json.dumps({
                "type": "block-start", "index": next_index, "blockType": "reasoning",
            }) + "\n"
            yield json.dumps({
                "type": "reasoning-delta", "index": next_index, "text": reasoning_content,
            }, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "block-end", "index": next_index,
                "block": {"type": "reasoning", "text": reasoning_content},
            }, ensure_ascii=False) + "\n"
            next_index += 1
        for call in tool_calls:
            call_id = str(call.get("id") or "")
            name = str(call.get("name") or "")
            arguments = str(call.get("arguments") or "{}")
            yield json.dumps({"type": "block-start", "index": next_index, "blockType": "tool-call"}) + "\n"
            yield json.dumps({
                "type": "tool-call-delta", "index": next_index, "id": call_id,
                "name": name, "argumentsDelta": arguments,
            }, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "block-end", "index": next_index,
                "block": {"type": "tool-call", "id": call_id, "name": name, "arguments": arguments},
            }, ensure_ascii=False) + "\n"
            next_index += 1
        yield json.dumps({
            "type": "usage", "usage": {
                "inputTokens": usage["input_tokens"], "outputTokens": usage["output_tokens"],
            },
        }) + "\n"
        yield json.dumps({
            "type": "finish", "reason": {"kind": "tool-calls" if tool_calls else "stop"},
        }) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@router.post("/tools/execute")
async def execute_tool(
    body: ToolBridgeRequest, authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_service(authorization)
    context = run_registry.get(body.run_token)
    if context is None:
        raise HTTPException(status_code=401, detail="expired run token")
    if _identical_failure_blocked(context.state, body.name, body.arguments):
        preview = json.dumps({
            "status": "error",
            "error": "相同工具和参数已连续失败两次，请改用其他验证方式或如实说明失败。",
            "retryable": False,
        }, ensure_ascii=False)
        return {"ok": False, "content": preview, "value": {"content": preview, "ok": False}}
    call = {"id": f"dsh-{body.name}", "name": body.name, "arguments": body.arguments}
    with bind_runtime(context.deps):
        _message, preview, ok = await _execute_tool_call(context.state, call, context.tool_registry)
    _record_tool_outcome(context.state, body.name, body.arguments, ok=ok)
    return {"ok": ok, "content": preview, "value": {"content": preview, "ok": ok}}
