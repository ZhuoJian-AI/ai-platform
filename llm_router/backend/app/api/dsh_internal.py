"""Private callbacks consumed only by the internal DSH Runtime container."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from app.agents.dsh import registry as run_registry
from app.agents.graph.context import bind_runtime
from app.agents.graph.nodes import _execute_tool_call
from app.config import settings
from app.services import model_gateway as llm_client

logger = structlog.get_logger()
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


class ApprovalBridgeRequest(BaseModel):
    """One ``ToolSpec.approval="ask"`` call the runtime holds until the terminal user decides."""

    run_token: str
    approval_id: str
    tool: str
    # Optional on the runtime side (an asker may have no DSH CallId); never let a missing id 422 into
    # the runtime's fail-closed ``unavailable``.
    call_id: str = ""
    reason: str = ""
    arguments_preview: str = ""
    timeout_ms: int = run_registry.APPROVAL_DEFAULT_TIMEOUT_MS


_MODEL_BRIDGE_ERROR_DETAILS = {
    "deployment_not_verified": "当前模型尚未完成全部能力验证，请管理员在“模型提供商”中完成该模型声明的全部能力测试。",
    "model_gateway_not_enabled": "当前组织尚未启用已验证模型网关，请管理员检查模型网关开关。",
    "invalid_credentials_or_permission": "模型凭证无效，或该 Key 没有模型访问权限。",
    "model_not_found": "模型 ID 不存在，或当前端点不提供该模型。",
    "quota_or_rate_limit": "模型服务余额或配额不足，或请求被限流。",
    "network_timeout": "模型服务响应超时，请稍后重试。",
    "network_failure": "无法连接模型服务，请管理员检查 Base URL 和网络。",
    "provider_service_unavailable": "模型服务暂时不可用，请稍后重试。",
    "invalid_provider_response": "模型服务没有返回有效的最终响应。",
}


def _require_service(authorization: str | None) -> None:
    expected = f"Bearer {settings.dsh_runtime_token}"
    if not authorization or authorization != expected:
        raise HTTPException(status_code=401, detail="invalid DSH service token")


def _model_bridge_http_exception(exc: Exception) -> HTTPException:
    """Translate gateway failures before response headers without leaking provider payloads."""
    category = llm_client.classify_gateway_error(exc)
    status_code = 409 if category in {"deployment_not_verified", "model_gateway_not_enabled"} else 502
    return HTTPException(
        status_code=status_code,
        detail=_MODEL_BRIDGE_ERROR_DETAILS.get(category, "模型服务调用失败，请稍后重试。"),
    )


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


def _authorized_tool_calls(
    calls: list[dict[str, Any]], allowed_names: set[str], *, run_token: str,
) -> list[dict[str, Any]]:
    """Drop provider tool calls that were not advertised for this exact run."""
    allowed: list[dict[str, Any]] = []
    rejected: list[str] = []
    for call in calls:
        name = str(call.get("name") or "")
        if name and name in allowed_names:
            allowed.append(call)
        else:
            rejected.append(name or "<empty>")
    if rejected:
        logger.warning(
            "dsh_model_unadvertised_tool_calls",
            run_token=run_token[:12],
            tools=sorted(set(rejected)),
        )
    return allowed


async def _iterate_with_runtime(source: Any, deps: Any):
    """Advance a model stream with runtime context bound to the current task.

    The bridge prefetches one event before returning ``StreamingResponse``.
    Starlette can consume the remaining body in a different task/context, so a
    ContextVar token must never stay open across an outward ``yield``.
    """
    iterator = aiter(source)
    try:
        while True:
            try:
                with bind_runtime(deps):
                    item = await anext(iterator)
            except StopAsyncIteration:
                return
            yield item
    finally:
        close = getattr(iterator, "aclose", None)
        if close is not None:
            with bind_runtime(deps):
                await close()


@router.post("/model/stream")
async def model_stream(
    body: ModelBridgeRequest, authorization: str | None = Header(default=None),
) -> StreamingResponse:
    _require_service(authorization)
    context = run_registry.get(body.run_token)
    if context is None:
        raise HTTPException(status_code=401, detail="expired run token")

    async def events():
        # 上游 stream_chat 中途抛错时，NDJSON 流不能只是静默断掉——DSH runtime 会当成
        # 「无效流」而无法给用户任何解释。首个事件之前的异常原样抛出，交给下方的预取逻辑
        # 转成结构化 HTTP 错误；已经开始输出后才兜底成 dsh-llm 的终止事件
        # ``{"type":"finish","reason":{"kind":"error","failure":{message, code}}}``。
        started = False
        try:
            async for line in _produce():
                started = True
                yield line
        except Exception as exc:  # noqa: BLE001
            if not started:
                raise
            category = llm_client.classify_gateway_error(exc)
            message = _MODEL_BRIDGE_ERROR_DETAILS.get(category, "模型服务调用失败，请稍后重试。")
            logger.error(
                "dsh_model_stream_failed", run_token=body.run_token[:12],
                category=category, error=str(exc), exc_info=True,
            )
            yield json.dumps({
                "type": "finish",
                "reason": {
                    "kind": "error",
                    "failure": {"message": message, "code": category},
                    # 兼容只读 ``reason.error.message`` 的消费者
                    "error": {"message": message},
                },
            }, ensure_ascii=False) + "\n"

    async def _produce():
        messages = _to_platform_messages(body.messages, context.image_inputs)
        tools = _to_platform_tools(body.tools)
        allowed_tool_names = {
            str(item.get("function", {}).get("name") or "")
            for item in tools
            if str(item.get("function", {}).get("name") or "")
        }
        text = ""
        text_started = False
        next_index = 0
        usage = {"input_tokens": 0, "output_tokens": 0}
        tool_calls: list[dict[str, Any]] = []
        reasoning_content = ""
        model_events = llm_client.stream_chat(
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
        async for kind, payload, extra in _iterate_with_runtime(model_events, context.deps):
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
                tool_calls = _authorized_tool_calls(
                    list(payload or []), allowed_tool_names, run_token=body.run_token,
                )
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
            with bind_runtime(context.deps):
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
            tool_calls = _authorized_tool_calls(
                list(result.tool_calls or []), allowed_tool_names, run_token=body.run_token,
            )
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
        if not text and not tool_calls:
            # A reasoning trace is not a final answer.  Treat a second empty
            # response as an upstream protocol failure so DSH cannot report
            # a successful run with no user-visible result.
            raise llm_client.GatewayError("invalid_provider_response")
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

    # StreamingResponse sends HTTP 200 before iterating its body.  Pull one
    # bridge event first so routing, credentials and an initially-empty provider
    # response become a structured HTTP error that DSH can surface accurately.
    event_stream = events()
    try:
        first_event = await anext(event_stream)
    except StopAsyncIteration as exc:
        raise HTTPException(status_code=502, detail="模型服务没有返回有效的最终响应。") from exc
    except Exception as exc:
        raise _model_bridge_http_exception(exc) from exc

    async def response_events():
        yield first_event
        async for event in event_stream:
            yield event

    return StreamingResponse(response_events(), media_type="application/x-ndjson")


@router.post("/tools/execute")
async def execute_tool(
    body: ToolBridgeRequest, authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_service(authorization)
    context = run_registry.get(body.run_token)
    if context is None:
        raise HTTPException(status_code=401, detail="expired run token")
    if body.name not in context.allowed_tool_names:
        logger.warning(
            "dsh_unadvertised_tool_execution_blocked",
            run_token=body.run_token[:12],
            tool=body.name,
        )
        raise HTTPException(status_code=403, detail="tool is not authorized for this run")
    # Identical-failure blocking moved into the DSH tool pipeline (``policy:repeat_failure_block``);
    # this bridge only authorizes and executes.
    call = {"id": f"dsh-{body.name}", "name": body.name, "arguments": body.arguments}
    with bind_runtime(context.deps):
        message, preview, ok = await _execute_tool_call(context.state, call, context.tool_registry)
    # 这里的返回值是 DSH runtime 喂给模型的 tool result——必须给完整内容。
    # ``preview`` 是 nodes._execute_tool_call 为事件/trace 做的 4000 字截断版，
    # 之前误把它当 content 返回，导致 workspace_read_file 分页、list_files、skill stdout 被截断。
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        content = preview
    return {"ok": ok, "content": content, "value": {"content": content, "ok": ok}, "preview": preview}


@router.post("/approval/request")
async def request_approval(
    body: ApprovalBridgeRequest, authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Relay a risky tool call to the terminal user and block until they decide.

    Publishes ``approval_request`` (then ``approval_decided``) on the run's SSE channel; the
    user's answer arrives via ``POST /terminal/tasks/{task_id}/approvals/{approval_id}``.
    Returns ``{"outcome": "allowed-once" | "rejected" | "cancelled" | "unavailable",
    "decided_by": "user" | "timeout" | "system"}``; the wait is capped at 300 s.
    """
    _require_service(authorization)
    context = run_registry.get(body.run_token)
    if context is None:
        raise HTTPException(status_code=401, detail="expired run token")
    return await run_registry.await_approval(
        context, approval_id=body.approval_id, tool=body.tool, call_id=body.call_id,
        reason=body.reason, arguments_preview=body.arguments_preview, timeout_ms=body.timeout_ms,
    )
