"""OpenAI protocol adapter — handles /v1/chat/completions and /v1/models requests.

Implements the exact wire format expected by the OpenAI SDK,
including streaming SSE chunks with data: [DONE] termination.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import structlog
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from app.models.llm_provider import LlmProvider
from app.services.llm_provider_service import get_decrypted_api_key

logger = structlog.get_logger()


async def proxy_openai_request(
    request: Request,
    provider: LlmProvider,
    body: dict[str, Any],
    api_key: str,
) -> Response:
    """代理 OpenAI API 请求到上游提供商。"""
    upstream_key = await get_decrypted_api_key(provider)
    upstream_url = f"{provider.base_url.rstrip('/')}/chat/completions"

    headers = {
        "Authorization": f"Bearer {upstream_key}",
        "Content-Type": "application/json",
    }

    timeout = httpx.Timeout(provider.timeout_seconds, connect=10.0)

    is_stream = body.get("stream", False)

    if is_stream:
        # 流式请求：不能在 context manager 里返回 StreamingResponse，
        # 因为 generator 被 lazily 消费时 client 已关闭。
        # 创建一个不被 context manager 管辖的 client，生命周期交给 generator。
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
                        "error": {"message": "Upstream provider unavailable", "type": "upstream_error", "code": "502"},
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
    """代理流式请求，逐 chunk 转发 SSE 事件。

    注意：client 的生命周期由本函数返回的 StreamingResponse 管理——
    generator 结束时关闭 client，确保连接不会泄漏。
    """
    async def stream_generator():
        try:
            for attempt in range(provider.max_retries + 1):
                try:
                    async with client.stream("POST", url, json=body, headers=headers) as resp:
                        # ── 上游非 2xx 时，读取完整错误体并转为 OpenAI 错误格式 ──
                        if resp.status_code >= 400:
                            error_body = await resp.aread()
                            logger.error(
                                "upstream_stream_error",
                                status=resp.status_code,
                                body=error_body.decode("utf-8", errors="replace")[:1000],
                            )
                            # 尝试解析上游错误体里的 message
                            try:
                                err_json = json.loads(error_body)
                                msg = err_json.get("error", {}).get("message", "") or error_body.decode("utf-8", errors="replace")[:200]
                            except (json.JSONDecodeError, AttributeError):
                                msg = error_body.decode("utf-8", errors="replace")[:200]

                            error_data = json.dumps({
                                "error": {
                                    "message": f"Upstream error ({resp.status_code}): {msg}",
                                    "type": "upstream_error",
                                    "code": str(resp.status_code),
                                },
                            })
                            yield f"data: {error_data}\n\n".encode()
                            yield b"data: [DONE]\n\n"
                            return

                        if resp.status_code >= 500 and attempt < provider.max_retries:
                            continue

                        async for chunk in resp.aiter_bytes():
                            yield chunk
                        return
                except (httpx.TimeoutException, httpx.ConnectError):
                    if attempt == provider.max_retries:
                        error_data = json.dumps({
                            "error": {"message": "Upstream provider unavailable", "type": "upstream_error", "code": "502"},
                        })
                        yield f"data: {error_data}\n\n".encode()
                        yield b"data: [DONE]\n\n"
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


def make_openai_error(
    status_code: int,
    error_type: str,
    message: str,
    code: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Response:
    """构造 OpenAI 协议格式的错误响应。

    extra 中的字段会合并进 error 对象，用于附带 DLP 命中规则等诊断信息。
    """
    error_obj: dict[str, Any] = {
        "message": message,
        "type": error_type,
        "code": code or str(status_code),
    }
    if extra:
        error_obj.update(extra)
    return Response(
        content=json.dumps({"error": error_obj}),
        status_code=status_code,
        media_type="application/json",
    )


async def list_available_models(
    request: Request,
    provider: LlmProvider,
) -> Response:
    """列出提供商支持的模型（OpenAI /v1/models 格式）。"""
    # 直接使用提供商声明的 supported_models
    models_data = []
    for model_id in provider.supported_models:
        models_data.append({
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": provider.provider_type,
        })

    return Response(
        content=json.dumps({"object": "list", "data": models_data}),
        status_code=200,
        media_type="application/json",
    )
