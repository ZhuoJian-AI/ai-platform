"""平台公开模型 API 的固定异步代理流水线。

链路顺序固定为：权限 → 请求 DLP → 路由 → 配额 → 上游 → 响应 DLP → 审计。
普通异步函数足以表达这条单路径处理流程，也避免为每个 HTTP 请求维护图 checkpoint。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Any

import structlog
from starlette.responses import Response, StreamingResponse

from app.auth.api_key_auth import AuthenticatedKey
from app.graph.context import ProxyContext, bind_proxy_runtime
from app.graph.nodes.audit import write_audit
from app.graph.nodes.dlp import dlp_request, dlp_response
from app.graph.nodes.errors import build_error
from app.graph.nodes.proxy import proxy_upstream
from app.graph.nodes.quota import reserve_quota
from app.graph.nodes.routing import resolve_route
from app.graph.nodes.scope import resolve_permissions
from app.graph.state import ProxyState

logger = structlog.get_logger()


def _initial_state(body: dict, protocol: str, is_stream: bool) -> ProxyState:
    return {
        "request_id": str(uuid.uuid4()),
        "protocol": protocol,
        "is_stream": is_stream,
        "start_time": time.monotonic(),
        "body": body,
        "requested_model": body.get("model", "") or "",
    }


def _context(db: Any, request: Any, auth: AuthenticatedKey) -> ProxyContext:
    return {"db": db, "request": request, "auth": auth}


def _apply(state: ProxyState, update: dict | None) -> None:
    if update:
        state.update(update)


async def _finalize_error(state: ProxyState) -> None:
    _apply(state, await build_error(state))
    await write_audit(state)


async def _run_preflight(state: ProxyState) -> bool:
    """执行上游调用前的固定决策链；返回是否可以继续。"""
    for node in (resolve_permissions, dlp_request, resolve_route, reserve_quota):
        _apply(state, await node(state))
        if state.get("error"):
            await _finalize_error(state)
            return False
    return True


async def run_proxy(
    *,
    request: Any,
    auth: AuthenticatedKey,
    db: Any,
    body: dict,
    protocol: str,
) -> Response:
    """执行非流式代理链并构造 HTTP 响应。"""
    state = _initial_state(body, protocol, is_stream=False)
    with bind_proxy_runtime(_context(db, request, auth)):
        if await _run_preflight(state):
            _apply(state, await proxy_upstream(state))
            if state.get("error"):
                await _finalize_error(state)
            else:
                _apply(state, await dlp_response(state))
                if state.get("error"):
                    await _finalize_error(state)
                else:
                    await write_audit(state)

    return Response(
        content=state.get("response_body", b""),
        status_code=state.get("status_code", 200),
        media_type=state.get("content_type", "application/json"),
    )


async def stream_proxy(
    *,
    request: Any,
    auth: AuthenticatedKey,
    db: Any,
    body: dict,
    protocol: str,
) -> Response:
    """先完成早期决策，再实时透传上游字节并在结束后审计。"""
    state = _initial_state(body, protocol, is_stream=True)
    ctx = _context(db, request, auth)
    request_id = state["request_id"]

    with bind_proxy_runtime(ctx):
        can_continue = await _run_preflight(state)
    if not can_continue:
        return Response(
            content=state.get("response_body", b""),
            status_code=state.get("status_code", 200),
            media_type=state.get("content_type", "application/json"),
        )

    async def body_iterator():
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=16)

        async def writer(chunk: Any) -> None:
            if isinstance(chunk, bytes):
                await queue.put(chunk)
            elif isinstance(chunk, bytearray):
                await queue.put(bytes(chunk))
            elif isinstance(chunk, str):
                await queue.put(chunk.encode("utf-8"))
            else:
                logger.warning(
                    "proxy_stream_unexpected_chunk",
                    request_id=request_id,
                    chunk_type=type(chunk).__name__,
                )

        async def execute() -> None:
            cancelled = False
            try:
                with bind_proxy_runtime(ctx, stream_writer=writer):
                    _apply(state, await proxy_upstream(state))
                    if state.get("error"):
                        _apply(state, await build_error(state))
                    await write_audit(state)
            except asyncio.CancelledError:
                cancelled = True
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "proxy_stream_pipeline_error",
                    request_id=request_id,
                    error=str(exc),
                    exc_info=True,
                )
            finally:
                if not cancelled:
                    await queue.put(None)

        task = asyncio.create_task(execute(), name=f"proxy-stream-{request_id}")
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
            await task
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(
        body_iterator(),
        status_code=200,
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "x-accel-buffering": "no",
        },
    )
