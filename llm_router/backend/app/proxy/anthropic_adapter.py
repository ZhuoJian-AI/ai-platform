"""Anthropic protocol adapter — handles /v1/messages requests.

Implements the exact wire format expected by the Anthropic SDK,
including streaming SSE events with proper event types.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from app.models.llm_provider import LlmProvider
from app.services.llm_provider_service import get_decrypted_api_key


async def proxy_anthropic_request(
    request: Request,
    provider: LlmProvider,
    body: dict[str, Any],
    api_key: str,
) -> Response:
    """代理 Anthropic API 请求到上游提供商。"""
    upstream_key = await get_decrypted_api_key(provider)
    upstream_url = f"{provider.base_url.rstrip('/')}/v1/messages"

    # 透传所有 Anthropic 专属 headers
    headers = {
        "x-api-key": upstream_key,
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
        "content-type": "application/json",
    }
    # 透传 beta headers
    if beta := request.headers.get("anthropic-beta"):
        headers["anthropic-beta"] = beta

    timeout = httpx.Timeout(provider.timeout_seconds, connect=10.0)

    is_stream = body.get("stream", False)

    if is_stream:
        client = httpx.AsyncClient(timeout=timeout)
        return await _proxy_stream(client, upstream_url, headers, body, provider)
    else:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await _proxy_non_stream(client, upstream_url, headers, body, provider)


async def _proxy_non_stream(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    provider: LlmProvider,
) -> Response:
    """代理非流式请求。"""
    for attempt in range(provider.max_retries + 1):
        try:
            resp = await client.post(url, json=body, headers=headers)
            if resp.status_code < 500:
                break
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt == provider.max_retries:
                return Response(
                    content=json.dumps({
                        "type": "error",
                        "error": {"type": "upstream_error", "message": "Upstream provider unavailable"},
                    }),
                    status_code=502,
                    media_type="application/json",
                )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


async def _proxy_stream(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    provider: LlmProvider,
) -> StreamingResponse:
    """代理流式请求，逐 chunk 转发 SSE 事件。"""
    async def stream_generator():
        try:
            for attempt in range(provider.max_retries + 1):
                try:
                    async with client.stream("POST", url, json=body, headers=headers) as resp:
                        if resp.status_code >= 500 and attempt < provider.max_retries:
                            continue
                        async for chunk in resp.aiter_bytes():
                            yield chunk
                        return
                except (httpx.TimeoutException, httpx.ConnectError):
                    if attempt == provider.max_retries:
                        error_event = (
                            f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'type': 'upstream_error', 'message': 'Upstream provider unavailable'}})}\n\n"
                        )
                        yield error_event.encode()
                        return
        finally:
            await client.aclose()

    return StreamingResponse(
        stream_generator(),
        status_code=200,
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "x-accel-buffering": "no",
        },
    )


def make_anthropic_error(
    status_code: int,
    error_type: str,
    message: str,
    extra: dict[str, Any] | None = None,
) -> Response:
    """构造 Anthropic 协议格式的错误响应。

    extra 中的字段会合并进 error 对象，用于附带 DLP 命中规则等诊断信息。
    """
    error_obj: dict[str, Any] = {"type": error_type, "message": message}
    if extra:
        error_obj.update(extra)
    return Response(
        content=json.dumps({
            "type": "error",
            "error": error_obj,
        }),
        status_code=status_code,
        media_type="application/json",
    )
